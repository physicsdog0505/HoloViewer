/**
 * #68 LOCAL-ONLY owner Router host for the Pyodide -> combined Router -> mock D1 proof.
 * Imports exact #47/#48 modules from caller-provided checkouts. No copied Router,
 * no production request, no D1 mutation and no deployment.
 *
 * Usage:
 *   node tools/serve_8788_owner_api_mock.mjs <issue47-root> <issue48-root> <port>
 */
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createServer} from 'node:http';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const [owner47, owner48, rawPort] = process.argv.slice(2);
if (!owner47 || !owner48 || !rawPort) throw new Error('Pass #47 root, #48 root, and loopback port');
const port = Number(rawPort);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid loopback port');

const expected47 = '149a80361654b06377dbae580e1d8da2e5010cf0';
const expected48 = 'b96d0902a504bc26019efd693a1b3586cfb3d3d2';
const actual47 = execFileSync('git', ['-C', owner47, 'rev-parse', 'HEAD'], {encoding:'utf8'}).trim();
const actual48 = execFileSync('git', ['-C', owner48, 'rev-parse', 'HEAD'], {encoding:'utf8'}).trim();
assert.equal(actual47, expected47, 'Wrong #47 owner source');
assert.equal(actual48, expected48, 'Wrong #48 owner source');

const shell = await import(pathToFileURL(resolve(owner47, 'backend/today/d1/api-shell.mjs')).href);
const extension = await import(pathToFileURL(resolve(owner48, 'ptt_offline/api_shell_ptt_extension.mjs')).href);
assert.equal(extension.REVIEWED_API_SHELL_BASE, expected47);
const router = extension.createPttMountedApiRouter(shell.createExistingApiRouter);

const day = '2026-10-15';
const pushes = [{
  push_id: 'ptt:v1:' + 'c'.repeat(64),
  aid: 'M.1234567890.A.ABC', source_line: 1, kind: '推', author: 'fixture',
  content: 'combined-router-proof', occurred_at: '2026-10-15T01:00:00Z',
  floor: 1, source_url: null
}];
let dbReads = 0;
const db = {prepare(sql) {
  if (sql.includes('catalog_meta')) return {first: async () => null};
  if (sql.includes('public_today_canonical')) return {bind(...params) {
    assert.ok(params.length > 0);
    return {all: async () => { dbReads++; return {results: []}; }};
  }};
  if (sql.includes('COUNT(*) AS total FROM public_history')) return {
    bind(d) { assert.equal(d, day); return {first: async () => ({total: 0})}; }
  };
  if (sql.includes('FROM public_history WHERE day=? ORDER BY id')) return {
    bind(d) { assert.equal(d, day); return {all: async () => ({results: []})}; }
  };
  if (sql.includes('FROM public_catalog WHERE video_id=?')) return {
    bind(id) { return {first: async () => ({video_id: id, title: 'fixture'})}; }
  };
  if (sql.includes('FROM ptt_provider_state')) return {
    bind(d) { assert.equal(d, day); return {all: async () => ({results: [{
      aid: pushes[0].aid, last_success_at: '2026-10-15T01:01:00Z', has_gap: 0
    }]})}; }
  };
  if (sql.includes('FROM ptt_threads')) return {
    bind(d) { assert.equal(d, day); return {all: async () => ({results: [{aid: pushes[0].aid}]})}; }
  };
  if (sql.includes('FROM ptt_pushes') && sql.includes('push_id=?')) return {
    bind(d,id) { assert.equal(d, day); return {first: async () => pushes.find(x => x.push_id === id) ?? null}; }
  };
  if (sql.includes('FROM ptt_pushes')) return {
    bind(...args) { assert.equal(args[0], day); return {all: async () => {
      dbReads++;
      return {results: pushes.slice(0, args.at(-1))};
    }}; }
  };
  throw new Error('Unreviewed mock-D1 query: ' + String(sql).slice(0, 100));
}};

const env = {DB: db, ALLOWED_ORIGIN: 'https://example.invalid'};
const server = createServer(async (req, res) => {
  try {
    if (req.url === '/__proof') {
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({status:'ready', db_reads:dbReads, issue47:actual47, issue48:actual48}));
      return;
    }
    const url = 'http://127.0.0.1:' + port + req.url;
    const response = await router.fetch(new Request(url, {method:req.method, headers:req.headers}), env);
    res.statusCode = response.status;
    for (const [key,value] of response.headers) res.setHeader(key,value);
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch (error) {
    res.statusCode = 500;
    res.setHeader('content-type', 'text/plain');
    res.end('fixture-error:' + error.constructor.name);
  }
});

await new Promise((resolveReady, rejectReady) => {
  server.once('error', rejectReady);
  server.listen(port, '127.0.0.1', resolveReady);
});
console.log(JSON.stringify({status:'READY', port, issue47:actual47, issue48:actual48}));

const stop = () => new Promise((resolveStop) => server.close(() => resolveStop()));
await new Promise((resolveSignal) => {
  process.once('SIGTERM', resolveSignal);
  process.once('SIGINT', resolveSignal);
});
await stop();
