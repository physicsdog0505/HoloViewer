/**
 * #68 read-only local integration: imports the EXACT #47-owned API shell.
 * No copied backend router, no D1 mutation, no production requests/deploy.
 *
 * Example:
 * node tools/check_8788_owner_api_e2e.mjs /path/to/issue47/checkout
 */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {resolve, join} from 'node:path';
import {pathToFileURL} from 'node:url';

const ownerRoot = process.argv[2];
if (!ownerRoot) throw new Error('Pass a local #47 owner-source checkout path');
const shellUrl = pathToFileURL(resolve(ownerRoot, 'backend/today/d1/api-shell.mjs')).href;
const {createExistingApiRouter} = await import(shellUrl);

let selects = 0;
const db = {prepare(sql) {
  if (sql.includes('catalog_meta')) return {first: async () => null};
  if (sql.includes('public_today_canonical')) return {bind(...params) {
    assert.ok(params.length > 0);
    return {all: async () => { selects++; return {results: []}; }};
  }};
  throw Error('unreviewed DB query: ' + String(sql).slice(0, 80));
}};
const env = {DB: db, ALLOWED_ORIGIN: 'https://example.invalid'};
const router = createExistingApiRouter();
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
  const today = await fetch(localOrigin + '/v1/catalog/today?day=2026-10-15');
  assert.equal(today.status, 200);
  const model = await today.json();
  assert.equal(model.schema_version, 'public-consumer-v1');
  assert.equal(Array.isArray(model.streams), true);

  const python = spawn('python3', [
    '-B', 'tools/check_8788_local_router_contract.py',
    '--api-base', localOrigin,
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
  assert.equal(receipt.ptt_mount_checked, false);
  assert.ok(selects >= 2, 'Actual #47 DB query path must execute');
  console.log(JSON.stringify({
    status: 'PASS', api_source: shellUrl,
    shell: 'owner-owned #47 existing-API reconstruction',
    db: 'mock D1-compatible read-only prepare/bind/all',
    db_reads: selects,
    consumer: receipt,
    prod_deploy: false,
  }, null, 2));
} finally {
  await new Promise((done, reject) => server.close(err => err ? reject(err) : done()));
}
