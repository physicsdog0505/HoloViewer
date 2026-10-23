// Isolated, review-only Collab D1 atomic batch engine.
// This module exposes NO fetch/scheduled handler and performs no network calls.
// Caller MUST supply a disposable D1 binding; never pass the Production DB.
const TARGET = "holoserver-hide-and-seek:5680e7ec7c29074a";
const REVISION = "sha256:8d0e11e2c08764f643c7751e08ea55e558b71f65eca71a25d89159022ca6fdeb";
const PROD_DB_ID = "64e1a0ee-1455-4377-9640-3922e8f4d061";

function fail(reason) { throw new Error("STOP: " + reason); }

export function assertDisposableIdentity(identity) {
  if (!identity || identity.kind !== "disposable-cloudflare-d1" ||
      !identity.database_id || identity.database_id === PROD_DB_ID ||
      !identity.binding || identity.binding !== "DB" ||
      !identity.name || !identity.name.startsWith("hv197-collab-disposable-")) {
    fail("disposable D1 identity not proven");
  }
  return identity;
}

export function canonicalJson(value) {
  if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
  if (value !== null && typeof value === "object") {
    return "{" + Object.keys(value).sort().map(k => JSON.stringify(k) + ":" + canonicalJson(value[k])).join(",") + "}";
  }
  return JSON.stringify(value);
}

export async function digest(value) {
  const bytes = new TextEncoder().encode(canonicalJson(value));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, "0")).join("");
}

export function makeBatchPacket(artifact, { mode = "initial", injectedFailure = false } = {}) {
  if (!artifact || artifact.projection_key !== "live" ||
      artifact.source_revision !== REVISION || !Array.isArray(artifact.events)) fail("artifact mismatch");
  const rows = artifact.events;
  if (mode === "initial" && (rows.length !== 1 || rows[0].event_id !== TARGET ||
      rows[0].live_scope !== false)) fail("unexpected canonical event");
  if (mode === "empty-next-live" && rows.length !== 0) fail("next-live must be empty");
  if (!["initial", "empty-next-live"].includes(mode)) fail("invalid mode");

  const update = {
    sql: "UPDATE public_collab_events SET live_scope=0 WHERE is_current=1 AND live_scope=1",
    bindings: []
  };
  const event = rows.length ? rows[0] : null;
  const insert = {
    sql: "INSERT INTO public_collab_events(event_id,event_key,label,confidence,event_date,start_at,end_at,review_status,payload_json,live_scope,is_current,source_revision,published_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET event_key=excluded.event_key,label=excluded.label,confidence=excluded.confidence,event_date=excluded.event_date,start_at=excluded.start_at,end_at=excluded.end_at,review_status=excluded.review_status,payload_json=excluded.payload_json,live_scope=excluded.live_scope,is_current=1,source_revision=excluded.source_revision,published_at=excluded.published_at",
    bindings: event ? [
      event.event_id,event.event_key,event.label,event.confidence,event.event_date,event.start_at,event.end_at,
      event.review_status,canonicalJson(event.payload),event.live_scope ? 1 : 0,1,
      artifact.source_revision,artifact.generated_at
    ] : []
  };
  const meta = {
    sql: "INSERT INTO public_collab_projection_meta(projection_key,source_revision,published_at,range_start,range_end,source_event_count,effective_event_count) VALUES(?,?,?,?,?,?,?) ON CONFLICT(projection_key) DO UPDATE SET source_revision=excluded.source_revision,published_at=excluded.published_at,range_start=excluded.range_start,range_end=excluded.range_end,source_event_count=excluded.source_event_count,effective_event_count=excluded.effective_event_count",
    bindings: ["live",artifact.source_revision,artifact.generated_at,artifact.source.range_start,artifact.source.range_end,
      artifact.source_event_count,artifact.effective_event_count]
  };
  if (injectedFailure) {
    if (mode !== "initial") fail("failure injection only for initial acceptance");
    insert.sql = "INSERT INTO public_collab_events(THIS_COLUMN_DOES_NOT_EXIST) VALUES(?)";
    insert.bindings = ["expected-failure"];
  }
  // Zero-event next-live batch intentionally has two DML statements.
  return rows.length ? [update, insert, meta] : [update, meta];
}

export async function packetReceipt(packet, identity) {
  assertDisposableIdentity(identity);
  return {
    identity, statement_digests: await Promise.all(packet.map(digest)),
    combined_packet_digest: await digest(packet), statement_count: packet.length,
    production_approved: false
  };
}

export async function executeDisposableBatch(db, packet, identity) {
  assertDisposableIdentity(identity);
  if (!db || typeof db.batch !== "function" || typeof db.prepare !== "function") fail("D1 API unavailable");
  // Caller must independently prove binding identity with authenticated Wrangler
  // account/config and a sentinel. This metadata check alone is insufficient.
  const statements = packet.map(s => db.prepare(s.sql).bind(...s.bindings));
  return db.batch(statements);
}
