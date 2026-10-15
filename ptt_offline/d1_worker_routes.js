// #48 production-compatible D1 read routes; not deployed.
// Intended to be mounted into the existing Cloudflare Worker, not a second Worker.
// GET /v1/ptt/today?day=YYYY-MM-DD&limit=300
// GET /v1/ptt/history?day=YYYY-MM-DD&limit=200&after=<push_id>
const dayRe = /^\d{4}-\d{2}-\d{2}$/;
const keys = ['push_id','aid','source_line','kind','author','content','occurred_at','floor','source_url'];
const select = keys.join(',');
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: {'content-type':'application/json; charset=utf-8', 'cache-control':'no-store'}
});

export async function handlePttD1Read(request, db) {
  const u = new URL(request.url);
  const history = u.pathname === '/v1/ptt/history';
  if (!history && u.pathname !== '/v1/ptt/today') return null;
  const day = u.searchParams.get('day') || '';
  const limit = Number(u.searchParams.get('limit') || (history ? '200' : '300'));
  if (!dayRe.test(day) || new Date(day + 'T00:00:00Z').toISOString().slice(0,10) !== day
      || !Number.isInteger(limit) || limit < 1 || limit > (history ? 200 : 300)) {
    return json({error:'invalid day/limit'}, 400);
  }
  try {
    const scope = await db.prepare('SELECT aid,last_success_at,has_gap FROM ptt_provider_state WHERE day=? ORDER BY aid')
      .bind(day).all();
    const threads = await db.prepare('SELECT aid FROM ptt_threads WHERE day=? ORDER BY aid').bind(day).all();
    if (!threads.results?.length) return json({error:'PTT source unavailable'}, 503);
    const asOf = new Date().toISOString();
    // Keyset cursor is a *last push_id*. Never use it alone as an
    // unverified global ordering cursor: resolve its order tuple first.
    const after = history ? u.searchParams.get('after') : null;
    let anchor = null;
    if (after) {
      anchor = await db.prepare('SELECT occurred_at,aid,source_line,push_id FROM ptt_pushes WHERE day=? AND push_id=?')
        .bind(day, after).first();
      if (!anchor) return json({error:'expired history anchor', gap:true}, 409);
    }
    let sql = `SELECT ${select} FROM ptt_pushes WHERE day=?`;
    const binds = [day];
    if (anchor) {
      sql += ' AND (occurred_at,aid,source_line,push_id)>(?,?,?,?)';
      binds.push(anchor.occurred_at,anchor.aid,anchor.source_line,anchor.push_id);
    }
    sql += ` ORDER BY occurred_at,aid,source_line,push_id LIMIT ?`;
    binds.push(limit + 1);
    const got = await db.prepare(sql).bind(...binds).all();
    const raw = got.results || [];
    // History uses forward paging. Today serves newest N in consumer order.
    const visible = history ? raw.slice(0,limit) : raw.slice(-limit);
    const hasMore = raw.length > limit;
    const newestCheck = (scope.results || []).map(x=>x.last_success_at).filter(Boolean);
    const lastSuccess = newestCheck.length ? newestCheck.sort()[0] : null;
    const stale = !lastSuccess || (Date.now() - Date.parse(lastSuccess)) > 30000;
    const gap = (scope.results || []).some(x=>Boolean(x.has_gap));
    const projected = visible.map(row => Object.fromEntries(keys.map(k=>[k,row[k] ?? null])));
    return json({
      schema_version:'public-consumer-v1', day, as_of:asOf,
      freshness:{status:stale?'stale':'fresh',last_success_at:lastSuccess},
      completeness:{status:'partial',gap},
      checkpoint:null,
      pushes:projected,
      page:{limit,has_more:hasMore,next_checkpoint:history && hasMore && visible.length ? visible.at(-1).push_id : null}
    });
  } catch (_error) {
    return json({error:'PTT source unavailable'},503);
  }
}
