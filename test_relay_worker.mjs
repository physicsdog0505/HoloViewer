import assert from "node:assert/strict";
import {handleRequest, validatePublishBatch} from "./relay/worker.mjs";

class FakeStatement {
  constructor(db, sql) { this.db=db; this.sql=sql; this.args=[]; }
  bind(...args) { this.args=args; return this; }
  async run() {
    if (this.sql.startsWith("INSERT OR IGNORE")) {
      const [push_id,aid,article_url,source_line,floor,kind,author,content,occurred_at,producer_id,published_at]=this.args;
      if (this.db.rows.some((row)=>row.push_id===push_id)) return {meta:{changes:0}};
      this.db.cursor += 1;
      this.db.rows.push({cursor:this.db.cursor,push_id,aid,article_url,source_line,floor,kind,author,content,occurred_at,producer_id,published_at});
      return {meta:{changes:1}};
    }
    if (this.sql.startsWith("INSERT INTO ptt_retention_watermark")) {
      const threshold=this.args[0];
      for(const row of this.db.rows.filter(row=>row.cursor<=threshold)) {
        this.db.watermarks.set(row.aid,Math.max(this.db.watermarks.get(row.aid)||0,row.cursor));
      }
      return {meta:{changes:0}};
    }
    if (this.sql.startsWith("DELETE FROM")) {
      const threshold=this.args[0];
      this.db.rows=this.db.rows.filter((row)=>row.cursor>threshold);
      return {meta:{changes:0}};
    }
    throw new Error("unexpected run SQL");
  }
  async first() {
    if (this.sql.startsWith("SELECT 1 AS ok")) return {ok:1};
    if (this.sql.startsWith("SELECT COALESCE(MAX(cursor)")) return {max_cursor:this.db.cursor};
    if (this.sql.startsWith("SELECT purged_through_cursor")) return {purged_through_cursor:this.db.watermarks.get(this.args[0])||0};
    throw new Error("unexpected first SQL");
  }
  async all() {
    if (!this.sql.startsWith("SELECT cursor")) throw new Error("unexpected all SQL");
    const [aid,after,limit]=this.args;
    return {results:this.db.rows.filter((row)=>row.aid===aid&&row.cursor>after).sort((a,b)=>a.cursor-b.cursor).slice(0,limit)};
  }
}
class FakeDB {
  constructor(){this.rows=[];this.cursor=0;this.failAtBatchIndex=-1;this.watermarks=new Map();}
  prepare(sql){return new FakeStatement(this,sql);}
  async batch(statements){
    const rows=this.rows.map((row)=>({...row})), cursor=this.cursor, watermarks=new Map(this.watermarks);
    const results=[];
    try {
      for(let i=0;i<statements.length;i++){
        if(i===this.failAtBatchIndex) throw new Error("injected batch insert failure");
        results.push(await statements[i].run());
      }
      return results;
    } catch(error){
      this.rows=rows;this.cursor=cursor;this.watermarks=watermarks;
      throw error;
    }
  }
}

const push={push_id:"ptt:C_Chat:M.123.A.1:1",aid:"M.123.A.1",article_url:"https://www.ptt.cc/bbs/C_Chat/M.123.A.1.html",source_line:1,floor:1,kind:"推",author:"viewer",content:"hello",occurred_at:"2026-10-08T12:00:00Z"};
const batch={schema_version:1,producer_id:"collector-main",published_at:"2026-10-08T12:00:01Z",pushes:[push]};
assert.equal(validatePublishBatch(batch).pushes.length,1);
assert.throws(()=>validatePublishBatch({...batch,pushes:[push,push]}));

const healthDB=new FakeDB();
let health=await handleRequest(new Request("https://relay.example/healthz"),{DB:healthDB,PUBLIC_ORIGIN:"https://physicsdog0505.github.io"});
assert.equal(health.status,200);
assert.deepEqual(await health.json(),{status:"ok",schema_version:1});

const DB=new FakeDB();
const env={DB,PUBLISH_TOKEN:"secret",PUBLIC_ORIGIN:"https://physicsdog0505.github.io",RETENTION_ROWS:"1000"};
let response=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{method:"POST",headers:{"authorization":"Bearer wrong","content-type":"application/json"},body:JSON.stringify(batch)}),env);
assert.equal(response.status,401);
assert.equal(DB.rows.length,0);

response=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},body:JSON.stringify(batch)}),env);
assert.equal(response.status,200);
assert.equal((await response.json()).accepted,1);
assert.equal(DB.rows.length,1);

response=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},body:JSON.stringify(batch)}),env);
assert.equal((await response.json()).accepted,0);
assert.equal(DB.rows.length,1);

response=await handleRequest(new Request("https://relay.example/v1/ptt?aid=M.123.A.1&after_cursor=0&limit=200"),env);
assert.equal(response.status,200);
assert.equal(response.headers.get("access-control-allow-origin"),"https://physicsdog0505.github.io");
const page=await response.json();
assert.equal(page.schema_version,1);
assert.equal(page.history_gap,false);
assert.equal(page.purged_through_cursor,0);
assert.equal(page.next_cursor,1);
assert.equal(page.has_more,false);
assert.equal(page.pushes.length,1);
assert.equal(page.pushes[0].content,"hello");

response=await handleRequest(new Request("https://relay.example/v1/ptt?aid=M.123.A.1&after_cursor=1&limit=200"),env);
assert.equal((await response.json()).pushes.length,0);


// D1 batch failure must not persist an earlier insert from the same publish request.
const second={...push,push_id:"ptt:C_Chat:M.123.A.1:2",source_line:2,floor:2};
const third={...push,push_id:"ptt:C_Chat:M.123.A.1:3",source_line:3,floor:3};
DB.failAtBatchIndex=1;
response=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},body:JSON.stringify({...batch,pushes:[second,third]})}),env);
assert.equal(response.status,500);
assert.equal(DB.rows.length,1);
assert.equal(DB.cursor,1);
DB.failAtBatchIndex=-1;
response=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},body:JSON.stringify({...batch,pushes:[second,third]})}),env);
assert.equal(response.status,200);
assert.equal((await response.json()).accepted,2);
assert.equal(DB.rows.length,3);


// Simulate a previously retained-and-purged article and assert explicit incompleteness.
DB.watermarks.set("M.123.A.1",1);
response=await handleRequest(new Request("https://relay.example/v1/ptt?aid=M.123.A.1&after_cursor=0&limit=200"),env);
assert.equal(response.status,200);
const gapPage=await response.json();
assert.equal(gapPage.history_gap,true);
assert.equal(gapPage.purged_through_cursor,1);
response=await handleRequest(new Request("https://relay.example/v1/ptt?aid=M.123.A.1&after_cursor=1&limit=200"),env);
assert.equal((await response.json()).history_gap,false);
console.log("relay worker adapter tests: pass");
