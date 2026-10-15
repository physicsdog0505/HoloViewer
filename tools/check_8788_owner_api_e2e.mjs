/**
 * #68 read-only local integration: imports the EXACT #47-owned API shell.
 * No copied backend router, no D1 mutation, no production requests/deploy.
 *
 * Example:
 * node tools/check_8788_owner_api_e2e.mjs /path/to/issue47/checkout
 */
import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import {createServer} from 'node:http';
import {resolve, join} from 'node:path';
import {pathToFileURL} from 'node:url';

const ownerRoot = process.argv[2];
if (!ownerRoot) throw new Error('Pass a local #47 owner-source checkout path');
const expectedOwnerHead = '149a80361654b06377dbae580e1d8da2e5010cf0';
const actualOwnerHead = execFileSync('git', ['-C', ownerRoot, 'rev-parse', 'HEAD'], {encoding:'utf8'}).trim();
assert.equal(actualOwnerHead, expectedOwnerHead, 'Wrong #47 shell version; do not claim exact-head parity');
const shellUrl = pathToFileURL(resolve(ownerRoot, 'backend/today/d1/api-shell.mjs')).href;
const {createExistingApiRouter} = await import(shellUrl);
const pttRoot = process.argv[3] || null;
const expectedPttHead = 'b96d0902a504bc26019efd693a1b3586cfb3d3d2';
let createPttMountedApiRouter = null;
if (pttRoot) {
  const actualPttHead = execFileSync('git', ['-C', pttRoot, 'rev-parse', 'HEAD'], {encoding:'utf8'}).trim();
  assert.equal(actualPttHead, expectedPttHead, 'Wrong #48 PTT mount source version');
  const pttUrl = pathToFileURL(resolve(pttRoot, 'ptt_offline/api_shell_ptt_extension.mjs')).href;
  const extension = await import(pttUrl);
  assert.equal(extension.REVIEWED_API_SHELL_BASE, expectedOwnerHead);
  createPttMountedApiRouter = extension.createPttMountedApiRouter;
}

let selects = 0;
const pttDay = '2026-10-15';
const pttPushes = [
  {
    push_id: 'ptt:v1:'+'a'.repeat(64),
    aid: 'M.1234567890.A.ABC', source_line:1, kind:'推', author:'a',
    content:'first', occurred_at:'2026-10-15T01:00:00Z', floor:1, source_url:null
  },
  {
    push_id: 'ptt:v1:'+'b'.repeat(64),
    aid: 'M.1234567890.A.ABC', source_line:2, kind:'→', author:'b',
    content:'second', occurred_at:'2026-10-15T01:01:00Z', floor:2, source_url:null
  }
];
const db = {prepare(sql) {
  if (sql.includes('catalog_meta')) return {first: async () => null};
  if (sql.includes('public_today_canonical')) return {bind(...params) {
    assert.ok(params.length > 0);
    return {all: async () => { selects++; return {results: []}; }};
  }};
  if (pttRoot && sql.includes('FROM ptt_provider_state')) return {
    bind(day) { assert.equal(day, pttDay); return {
      all:async()=>({results:[{aid:'M.1234567890.A.ABC',last_success_at:'2026-10-15T01:02:00Z',has_gap:0}]})
    }; }
  };
  if (pttRoot && sql.includes('FROM ptt_threads')) return {
    bind(day) { assert.equal(day, pttDay); return {
      all:async()=>({results:[{aid:'M.1234567890.A.ABC'}]})
    }; }
  };
  if (pttRoot && sql.includes('FROM ptt_pushes') && sql.includes('push_id=?')) return {
    bind(day,id) {assert.equal(day,pttDay);return {first:async()=>pttPushes.find(x=>x.push_id===id)??null};}
  };
  if (pttRoot && sql.includes('FROM ptt_pushes')) return {
    bind(...args) {assert.equal(args[0],pttDay);return {all:async()=>{
      const history = sql.includes(' ASC,');
      const limit = args.at(-1);
      const rows = args.length===6
        ? pttPushes.filter(x=>x.occurred_at>args[1] || (x.occurred_at===args[1] && x.push_id>args[4]))
        : pttPushes;
      selects++;
      return {results:(history?rows:rows.toReversed()).slice(0,limit)};
    }};}
  };
  throw Error('unreviewed DB query: ' + String(sql).slice(0, 80));
}};
const env = {DB: db, ALLOWED_ORIGIN: 'https://example.invalid'};
const router = pttRoot ? createPttMountedApiRouter(createExistingApiRouter) : createExistingApiRouter();
const server = createServer(async (req, res) => {
  try {
    const url = 'http://127.0.0.1:' + server.address().port + req.url;
    const response = await router.fetch(new Request(url, {
      method: req.method,
      headers: req.headers,
    }), env);
    res.statusCode = response.status;
    for (const [key, value] of response.headers) res.setHeader(key, value);
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch (error) {
    res.statusCode = 500;
    res.end('fixture-error:' + error.constructor.name);
  }
});
await new Promise((resolveReady, rejectReady) => {
  server.once('error', rejectReady);
  server.listen(0, '127.0.0.1', resolveReady);
});

try {
  const localOrigin = 'http://127.0.0.1:' + server.address().port;
  const health = await fetch(localOrigin + '/health');
  assert.equal(health.status, 200);
  assert.equal((await health.json()).status, 'database_bound');
  const preflight = await fetch(localOrigin + '/v1/catalog/today', {
    method: 'OPTIONS',
    headers: {'Origin': 'https://example.invalid', 'Access-Control-Request-Method': 'GET'},
  });
  assert.equal(preflight.status, 204);
  assert.equal(preflight.headers.get('access-control-max-age'), '600');
  assert.equal(preflight.headers.get('access-control-allow-headers'), 'Accept');
  const missingOriginPreflight = await fetch(localOrigin + '/v1/catalog/today', {method:'OPTIONS'});
  assert.equal(missingOriginPreflight.status, 400);
  assert.equal((await missingOriginPreflight.json()).error, 'origin_required');
  const nonGet = await fetch(localOrigin + '/v1/catalog/today', {method:'POST'});
  assert.equal(nonGet.status, 405);
  const badOrigin = await fetch(localOrigin + '/v1/catalog/today', {headers:{Origin:'https://denied.invalid'}});
  assert.equal(badOrigin.status, 403);
  assert.equal((await badOrigin.json()).error, 'origin_not_allowed');
  const today = await fetch(localOrigin + '/v1/catalog/today?day=2026-10-15');
  assert.equal(today.status, 200);
  const model = await today.json();
  assert.equal(model.schema_version, 'public-consumer-v1');
  assert.equal(Array.isArray(model.streams), true);

  if (pttRoot) {
    const first = await fetch(localOrigin+'/v1/ptt/history?day='+pttDay+'&limit=1');
    assert.equal(first.status,200);
    const firstData = await first.json();
    assert.equal(firstData.pushes.length,1);
    assert.equal(firstData.page.has_more,true);
    const after = firstData.page.next_checkpoint;
    assert.equal(after,pttPushes[0].push_id);
    const second = await fetch(localOrigin+'/v1/ptt/history?day='+pttDay+'&limit=1&after='+encodeURIComponent(after));
    assert.equal(second.status,200);
    const secondData=await second.json();
    assert.equal(secondData.pushes[0].push_id,pttPushes[1].push_id);
    assert.equal(secondData.page.has_more,false);
  }
  const python = spawn('python3', [
    '-B', 'tools/check_8788_local_router_contract.py',
    '--api-base', localOrigin,
    ...(pttRoot?['--ptt-day',pttDay]:[]),
  ], {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {...process.env, PYTHONPATH: process.cwd()},
  });
  const chunks = [], errors = [];
  python.stdout.on('data', x => chunks.push(x));
  python.stderr.on('data', x => errors.push(x));
  const exitCode = await new Promise((r, reject) => {
    python.on('error', reject);
    python.on('close', r);
  });
  assert.equal(exitCode, 0, Buffer.concat(errors).toString());
  const receipt = JSON.parse(Buffer.concat(chunks).toString());
  assert.equal(receipt.canonical_today.schema_version, 'public-consumer-v1');
  assert.equal(receipt.production_deployment, false);
  assert.equal(receipt.ptt_mount_checked, Boolean(pttRoot));
  if (pttRoot) {
    assert.equal(receipt.canonical_ptt.push_count, 2);
    assert.equal(receipt.canonical_ptt.today_enabled_reader_checked, true);
    assert.equal(receipt.canonical_ptt.history_first_count, 1);
    assert.equal(receipt.canonical_ptt.history_second_count, 1);
    assert.equal(receipt.canonical_ptt.history_continuation_checked, true);
  }
  assert.ok(selects >= 2, 'Actual #47 DB query path must execute');
  console.log(JSON.stringify({
    status: 'PASS', api_source: shellUrl, api_source_sha: actualOwnerHead,
    guards: {preflight:true, preflight_no_origin:true, method:true, denied_origin:true},
    shell: 'owner-owned #47 existing-API reconstruction',
    db: 'mock D1-compatible read-only prepare/bind/all',
    db_reads: selects, ptt_combined_mount: Boolean(pttRoot),
    ptt_mount_source_sha: pttRoot ? expectedPttHead : null,
    consumer: receipt,
    prod_deploy: false,
  }, null, 2));
} finally {
  await new Promise((done, reject) => server.close(err => err ? reject(err) : done()));
}
