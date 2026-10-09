const SCHEMA_VERSION = 1;
const MAX_BATCH_PUSHES = 200;
const MAX_READ_PUSHES = 500;
const MAX_BATCH_BYTES = 256 * 1024;
const MAX_READ_BYTES = 512 * 1024;
const DEFAULT_RETENTION_ROWS = 100000;
const AID = /^[A-Za-z0-9._-]{1,32}$/;
const PUSH_ID = /^ptt:v1:[0-9a-f]{64}$/;
const PRODUCER = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/;
const KINDS = new Set(["推", "噓", "嘘", "→"]);

export class RelayError extends Error {
  constructor(message, status = 400) {
    super(message);
    this.name = "RelayError";
    this.status = status;
  }
}

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...headers,
    },
  });
}

function utcZ(value, field) {
  if (typeof value !== "string" || !value.endsWith("Z") || Number.isNaN(Date.parse(value))) {
    throw new RelayError(`${field} must be UTC-Z timestamp`);
  }
  return value;
}

function boundedText(value, field, maximum, allowEmpty = false) {
  if (typeof value !== "string" || (!allowEmpty && !value) || value.length > maximum) {
    throw new RelayError(`${field} is invalid`);
  }
  for (const ch of value) {
    if (ch.charCodeAt(0) < 32 && ch !== "\t") throw new RelayError(`${field} contains control characters`);
  }
  return value;
}

function validatePush(raw) {
  const fields = ["push_id","aid","article_url","source_line","floor","kind","author","content","occurred_at"].sort().join();
  if (!raw || typeof raw !== "object" || Array.isArray(raw) || Object.keys(raw).sort().join() !== fields) {
    throw new RelayError("push fields mismatch v1 contract");
  }
  if (!PUSH_ID.test(raw.push_id)) throw new RelayError("invalid push_id");
  if (!AID.test(raw.aid)) throw new RelayError("invalid aid");
  const article = boundedText(raw.article_url, "article_url", 512);
  if (!(article.startsWith("https://www.ptt.cc/") || article.startsWith("https://ptt.cc/"))) {
    throw new RelayError("article_url must be HTTPS PTT URL");
  }
  if (!Number.isSafeInteger(raw.source_line) || raw.source_line < 1) throw new RelayError("invalid source_line");
  if (raw.floor !== null && (!Number.isSafeInteger(raw.floor) || raw.floor < 1)) throw new RelayError("invalid floor");
  if (!KINDS.has(raw.kind)) throw new RelayError("invalid kind");
  boundedText(raw.author, "author", 64);
  boundedText(raw.content, "content", 1000, true);
  utcZ(raw.occurred_at, "occurred_at");
  return raw;
}

export function validatePublishBatch(raw) {
  const fields = ["schema_version","producer_id","published_at","pushes"].sort().join();
  if (!raw || typeof raw !== "object" || Array.isArray(raw) || Object.keys(raw).sort().join() !== fields) {
    throw new RelayError("publish batch fields mismatch v1 contract");
  }
  if (raw.schema_version !== SCHEMA_VERSION) throw new RelayError("unsupported schema version");
  if (typeof raw.producer_id !== "string" || !PRODUCER.test(raw.producer_id)) throw new RelayError("invalid producer_id");
  utcZ(raw.published_at, "published_at");
  if (!Array.isArray(raw.pushes) || raw.pushes.length > MAX_BATCH_PUSHES) throw new RelayError("invalid publish push list");
  const pushes = raw.pushes.map(validatePush);
  if (new Set(pushes.map((item) => item.push_id)).size !== pushes.length) throw new RelayError("duplicate push_id in batch");
  return {...raw, pushes};
}

function publicHeaders(env) {
  return {
    "access-control-allow-origin": env.PUBLIC_ORIGIN || "https://physicsdog0505.github.io",
    "access-control-allow-methods": "GET, OPTIONS",
    "access-control-allow-headers": "accept",
    "vary": "Origin",
  };
}

async function readBody(request) {
  const announced = Number(request.headers.get("content-length") || 0);
  if (announced > MAX_BATCH_BYTES) throw new RelayError("publish batch exceeds byte limit", 413);
  const buffer = await request.arrayBuffer();
  if (buffer.byteLength > MAX_BATCH_BYTES) throw new RelayError("publish batch exceeds byte limit", 413);
  try {
    return JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(buffer));
  } catch (_) {
    throw new RelayError("invalid publish JSON");
  }
}

async function publish(request, env) {
  if (!env.PUBLISH_TOKEN) throw new RelayError("publisher is not configured", 503);
  const auth = request.headers.get("authorization") || "";
  if (auth !== `Bearer ${env.PUBLISH_TOKEN}`) throw new RelayError("unauthorized", 401);
  if (!env.DB) throw new RelayError("relay database is not configured", 503);
  const batch = validatePublishBatch(await readBody(request));
  // Cloudflare D1 batch executes its statements transactionally: do not expose
  // a partially published push batch when a later insert fails.
  if (typeof env.DB.batch !== "function") throw new RelayError("atomic D1 batch is unavailable", 503);
  // A duplicate-only request must not execute mutating SQL. This avoids
  // retention churn during overlapping Publisher retries. The UNIQUE index
  // remains the final concurrency guard for two simultaneous producers.
  const known = new Set();
  if (batch.pushes.length) {
    const placeholders = batch.pushes.map(() => "?").join(",");
    const existing = await env.DB.prepare(
      `SELECT push_id FROM ptt_pushes WHERE push_id IN (${placeholders})`
    ).bind(...batch.pushes.map(push => push.push_id)).all();
    for (const row of existing?.results || []) known.add(String(row.push_id));
  }
  const fresh = batch.pushes.filter(push => !known.has(push.push_id));
  if (!fresh.length) return json({schema_version: 1, accepted: 0, received: batch.pushes.length});

  const statements = fresh.map((push) => env.DB.prepare(
    `INSERT OR IGNORE INTO ptt_pushes
       (push_id, aid, article_url, source_line, floor, kind, author, content, occurred_at, producer_id, published_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).bind(
    push.push_id, push.aid, push.article_url, push.source_line, push.floor,
    push.kind, push.author, push.content, push.occurred_at, batch.producer_id, batch.published_at
  ));
  const keep = Number.isSafeInteger(Number(env.RETENTION_ROWS)) ? Math.max(1000, Number(env.RETENTION_ROWS)) : DEFAULT_RETENTION_ROWS;
  // Retain the newest N *actual rows*, not a max(cursor)-N span: AUTOINCREMENT
  // skips values after ignored inserts. The two statements share a D1 batch
  // transaction, so a deletion never precedes its history-gap watermark.
  const boundary = `SELECT cursor FROM ptt_pushes ORDER BY cursor DESC LIMIT 1 OFFSET ?`;
  statements.push(env.DB.prepare(
    `INSERT INTO ptt_retention_watermark (aid, purged_through_cursor)
       SELECT aid, MAX(cursor) FROM ptt_pushes
       WHERE cursor < COALESCE((${boundary}), 0)
       GROUP BY aid
       ON CONFLICT(aid) DO UPDATE SET purged_through_cursor =
         MAX(ptt_retention_watermark.purged_through_cursor, excluded.purged_through_cursor)`
  ).bind(keep - 1));
  statements.push(env.DB.prepare(
    `DELETE FROM ptt_pushes WHERE cursor < COALESCE((${boundary}), 0)`
  ).bind(keep - 1));
  const results = await env.DB.batch(statements);
  const accepted = results.slice(0, fresh.length).reduce(
    (total, result) => total + (Number(result?.meta?.changes || 0) > 0 ? 1 : 0), 0
  );
  return json({schema_version: 1, accepted, received: batch.pushes.length});
}

function readResponseBody({after, checkedAt, historyGap, purgedThrough, pushes, hasMore}) {
  const next = pushes.length ? pushes[pushes.length - 1].cursor : after;
  return {
    schema_version: 1,
    next_cursor: next,
    has_more: hasMore,
    checked_at: checkedAt,
    history_gap: historyGap,
    purged_through_cursor: purgedThrough,
    pushes,
  };
}

function encodedJsonBytes(value) {
  return new TextEncoder().encode(JSON.stringify(value)).byteLength;
}

async function read(request, env) {
  if (!env.DB) throw new RelayError("relay database is not configured", 503);
  const url = new URL(request.url);
  const aid = url.searchParams.get("aid") || "";
  const after = Number(url.searchParams.get("after_cursor") || 0);
  const requestedLimit = Number(url.searchParams.get("limit") || 200);
  if (!AID.test(aid)) throw new RelayError("invalid aid");
  if (!Number.isSafeInteger(after) || after < 0) throw new RelayError("invalid after_cursor");
  if (!Number.isSafeInteger(requestedLimit) || requestedLimit < 1) throw new RelayError("invalid limit");
  const limit = Math.min(requestedLimit, MAX_READ_PUSHES);
  const watermark = await env.DB.prepare(
    "SELECT purged_through_cursor FROM ptt_retention_watermark WHERE aid = ?"
  ).bind(aid).first();
  const purgedThrough = Number(watermark?.purged_through_cursor || 0);
  const historyGap = after < purgedThrough;
  const result = await env.DB.prepare(
    `SELECT cursor, push_id, aid, article_url, source_line, floor, kind, author, content, occurred_at
     FROM ptt_pushes WHERE aid = ? AND cursor > ? ORDER BY cursor ASC LIMIT ?`
  ).bind(aid, after, limit + 1).all();
  const rows = Array.isArray(result?.results) ? result.results : [];
  const checkedAt = new Date().toISOString();
  const projected = rows.slice(0, limit).map((row) => ({
    push_id: String(row.push_id),
    aid: String(row.aid),
    article_url: String(row.article_url),
    source_line: Number(row.source_line),
    floor: row.floor == null ? null : Number(row.floor),
    kind: String(row.kind),
    author: String(row.author),
    content: String(row.content),
    occurred_at: String(row.occurred_at),
    cursor: Number(row.cursor),
  }));

  const visible = [];
  for (const push of projected) {
    const candidate = [...visible, push];
    // Use has_more=false for the size probe because "false" is one byte
    // larger than "true"; fitting this form guarantees either final form fits.
    const probe = readResponseBody({
      after,
      checkedAt,
      historyGap,
      purgedThrough,
      pushes: candidate,
      hasMore: false,
    });
    if (encodedJsonBytes(probe) > MAX_READ_BYTES) break;
    visible.push(push);
  }

  const hasMore = rows.length > visible.length;
  const body = readResponseBody({
    after,
    checkedAt,
    historyGap,
    purgedThrough,
    pushes: visible,
    hasMore,
  });
  if (encodedJsonBytes(body) > MAX_READ_BYTES) {
    throw new RelayError("read page exceeds byte limit", 500);
  }
  return json(body, 200, publicHeaders(env));
}

export async function handleRequest(request, env) {
  try {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, {status: 204, headers: publicHeaders(env)});
    if (url.pathname === "/healthz" && request.method === "GET") {
      if (!env.DB) throw new RelayError("relay database is not configured", 503);
      await env.DB.prepare("SELECT 1 AS ok").first();
      return json({status: "ok", schema_version: SCHEMA_VERSION}, 200, publicHeaders(env));
    }
    if (url.pathname === "/v1/ptt/publish" && request.method === "POST") return await publish(request, env);
    if (url.pathname === "/v1/ptt" && request.method === "GET") return await read(request, env);
    return json({error: "not found"}, 404, request.method === "GET" ? publicHeaders(env) : {});
  } catch (error) {
    const status = error instanceof RelayError ? error.status : 500;
    const message = error instanceof RelayError ? error.message : "internal relay error";
    return json({error: message}, status, request.method === "GET" ? publicHeaders(env) : {});
  }
}

export default { fetch: handleRequest };
