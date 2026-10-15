import test from 'node:test';
import assert from 'node:assert/strict';
import worker from './api-worker-entry.mjs';
const ORIGIN='https://holoviewer-public.singlebagel.workers.dev';
const queries=[];
const DB={prepare(sql){queries.push(sql);return {bind(...args){return {
 async first(){return sql.includes('COUNT(*)')?{total:0}:null},
 async all(){return {results:[]}
 }},async first(){return null}}}};
const env={DB,ALLOWED_ORIGIN:ORIGIN};
test('deployment entry preserves health and legacy history envelope',async()=>{
 const health=await worker.fetch(new Request('https://api.example/health',{headers:{origin:ORIGIN}}),env);
 assert.equal(health.status,200);assert.equal((await health.json()).status,'database_bound');
 assert.equal(health.headers.get('access-control-allow-origin'),ORIGIN);
 const history=await worker.fetch(new Request('https://api.example/v1/history?day=2026-10-15&limit=1&offset=0',{headers:{origin:ORIGIN}}),env);
 assert.equal(history.status,200);
 assert.deepEqual(await history.json(),{day:'2026-10-15',total:0,limit:1,offset:0,items:[]});
});
test('deployment entry serves canonical Today but not PTT before separate approval',async()=>{
 const today=await worker.fetch(new Request('https://api.example/v1/catalog/today?day=2026-10-15&limit=1',{headers:{origin:ORIGIN}}),env);
 assert.equal(today.status,200);
 const result=await today.json();
 assert.equal(result.schema_version,'public-consumer-v1');
 assert.notEqual(result.source,'d1_public_projection');
 assert.equal((await worker.fetch(new Request('https://api.example/v1/ptt/today',{headers:{origin:ORIGIN}}),env)).status,404);
 assert.equal(queries.some(sql=>/INSERT|UPDATE|DELETE/i.test(sql)),false);
});
test('deployment entry requires explicitly configured origin',async()=>{
 const r=await worker.fetch(new Request('https://api.example/health',{headers:{origin:ORIGIN}}),{DB});
 assert.equal(r.status,403);
});
