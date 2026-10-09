import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {execFileSync} from "node:child_process";
import {handleRequest, validatePublishBatch} from "./relay/worker.mjs";


function canonicalPushId(push) {
  const material = [
    push.aid,
    push.source_line,
    push.author,
    push.occurred_at,
    push.content,
  ];
  const digest = createHash("sha256")
    .update(JSON.stringify(material), "utf8")
    .digest("hex");
  return `ptt:v1:${digest}`;
}

class FakeStatement {
  constructor(db, sql) { this.db=db; this.sql=sql; this.args=[]; }
  bind(...args) { this.args=args; return this; }
  async run() {
    if (this.sql.startsWith("INSERT OR IGNORE")) {
      this.db.mutationCount++;
      let changed=0;
      for(let n=0;n<this.args.length;n+=11) {
        const [push_id,aid,article_url,source_line,floor,kind,author,content,occurred_at,producer_id,published_at]=this.args.slice(n,n+11);
        this.db.cursor += 1;
        if (this.db.rows.some((row)=>row.push_id===push_id)) continue;
        this.db.rows.push({cursor:this.db.cursor,push_id,aid,article_url,source_line,floor,kind,author,content,occurred_at,producer_id,published_at});
        changed++;
      }
      return {meta:{changes:changed}};
    }
    if (this.sql.startsWith("INSERT INTO ptt_purged_source_floor")) {
      this.db.mutationCount++;
      const keep=this.args[0]+1;
      const boundary=[...this.db.rows].sort((a,b)=>b.cursor-a.cursor)[keep-1]?.cursor || 0;
      for (const row of this.db.rows.filter(r=>r.cursor<boundary)) {
        this.db.floors.set(row.aid,Math.max(this.db.floors.get(row.aid)||0,row.source_line));
      }
      return {meta:{changes:0}};
    }
    if (this.sql.startsWith("INSERT INTO ptt_retention_watermark")) {
      this.db.mutationCount++;
      const keep=this.args[0]+1;
      const boundary=[...this.db.rows].sort((a,b)=>b.cursor-a.cursor)[keep-1]?.cursor || 0;
      for(const row of this.db.rows.filter(row=>row.cursor<boundary)) {
        this.db.watermarks.set(row.aid,Math.max(this.db.watermarks.get(row.aid)||0,row.cursor));
      }
      return {meta:{changes:0}};
    }
    if (this.sql.startsWith("DELETE FROM ptt_write_rate")) return {meta:{changes:0}};
    if (this.sql.startsWith("DELETE FROM")) {
      this.db.mutationCount++;
      const keep=this.args[0]+1;
      const boundary=[...this.db.rows].sort((a,b)=>b.cursor-a.cursor)[keep-1]?.cursor || 0;
      this.db.rows=this.db.rows.filter((row)=>row.cursor>=boundary);
      return {meta:{changes:0}};
    }
    throw new Error("unexpected run SQL");
  }
  async first() {
    if (this.sql.startsWith("SELECT 1 AS ok")) return {ok:1};
    if (this.sql.startsWith("SELECT COALESCE(MAX(cursor)")) return {max_cursor:this.db.cursor};
    if (this.sql.startsWith("SELECT source_line FROM ptt_purged_source_floor"))
      return this.db.floors.has(this.args[0]) ? {source_line:this.db.floors.get(this.args[0])} : null;
    if (this.sql.startsWith("SELECT purged_through_cursor")) return {purged_through_cursor:this.db.watermarks.get(this.args[0])||0};
    throw new Error("unexpected first SQL");
  }
  async all() {
    if (this.sql.startsWith("SELECT aid, source_line FROM ptt_purged_source_floor")) {
      return {results:this.args.filter(aid=>this.db.floors.has(aid)).map(aid=>({aid,source_line:this.db.floors.get(aid)}))};
    }
    if (this.sql.startsWith("SELECT aid, purged_through_cursor FROM ptt_retention_watermark")) {
      return {results:this.args.filter(aid=>this.db.watermarks.has(aid)).map(aid=>({aid,purged_through_cursor:this.db.watermarks.get(aid)}))};
    }
    if (this.sql.startsWith("SELECT push_id")) {
      return {results:this.db.rows.filter(row=>this.args.includes(row.push_id)).map(row=>({push_id:row.push_id}))};
    }
    if (!this.sql.startsWith("SELECT cursor")) throw new Error("unexpected all SQL");
    const [aid,after,limit]=this.args;
    return {results:this.db.rows.filter((row)=>row.aid===aid&&row.cursor>after).sort((a,b)=>a.cursor-b.cursor).slice(0,limit)};
  }
}
class FakeDB {
  constructor(){this.rows=[];this.cursor=0;this.failAtBatchIndex=-1;this.watermarks=new Map();this.floors=new Map();this.mutationCount=0;}
  prepare(sql){
    const db=this;
    const stmt=new FakeStatement(db,sql);
    const originalBind=stmt.bind.bind(stmt);
    stmt.bind=(...args)=>{
      if(args.length>100) throw new Error("D1 per-statement parameter limit exceeded");
      return originalBind(...args);
    };
    return stmt;
  }
  async batch(statements){
    const rows=this.rows.map((row)=>({...row})), cursor=this.cursor, watermarks=new Map(this.watermarks), floors=new Map(this.floors), mutationCount=this.mutationCount;
    const results=[];
    try {
      for(let i=0;i<statements.length;i++){
        if(i===this.failAtBatchIndex) throw new Error("injected batch insert failure");
        results.push(await statements[i].run());
      }
      return results;
    } catch(error){
      this.rows=rows;this.cursor=cursor;this.watermarks=watermarks;this.floors=floors;this.mutationCount=mutationCount;
      throw error;
    }
  }
}

const pushBase={aid:"M.123.A.1",article_url:"https://www.ptt.cc/bbs/C_Chat/M.123.A.1.html",source_line:1,floor:1,kind:"推",author:"viewer",content:"hello",occurred_at:"2026-10-08T12:00:00Z"};
const push={...pushBase,push_id:canonicalPushId(pushBase)};
const batch={schema_version:1,producer_id:"collector-main",published_at:"2026-10-08T12:00:01Z",pushes:[push]};
assert.equal(validatePublishBatch(batch).pushes.length,1);
assert.throws(
  ()=>validatePublishBatch({...batch,pushes:[{...push,push_id:"ptt:C_Chat:legacy:1"}]}),
  /push_id/,
  "legacy push id must be rejected"
);
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
assert.equal(DB.mutationCount,4, "duplicate-only POST must not write or prune");

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
const secondBase={...push,source_line:2,floor:2};
delete secondBase.push_id;
const second={...secondBase,push_id:canonicalPushId(secondBase)};
const thirdBase={...push,source_line:3,floor:3};
delete thirdBase.push_id;
const third={...thirdBase,push_id:canonicalPushId(thirdBase)};
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

// Exercise actual retention pruning, rather than manually setting a watermark.
// The cursor is global across articles; gap detection must remain per AID.
const retentionDB = new FakeDB();
retentionDB.rows = Array.from({length:1002}, (_,i) => {
  const row = {
    ...push,
    aid:i%2===0 ? "M.123.A.1" : "M.123.A.2",
    source_line:i+1,
    floor:i+1,
  };
  delete row.push_id;
  return {...row, cursor:i+1, push_id:canonicalPushId(row)};
});
retentionDB.cursor = 1002;
const retentionEnv = {...env, DB:retentionDB};
response=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},body:JSON.stringify({...batch,pushes:[(()=>{const row={...push,source_line:1003,floor:1003};delete row.push_id;return {...row,push_id:canonicalPushId(row)};})()]})}),retentionEnv);
assert.equal(response.status,200);
assert.equal(retentionDB.rows.length,1000);
assert.equal(retentionDB.watermarks.get("M.123.A.1"),3);
assert.equal(retentionDB.watermarks.get("M.123.A.2"),2);
response=await handleRequest(new Request("https://relay.example/v1/ptt?aid=M.123.A.1&after_cursor=0&limit=200"),retentionEnv);
assert.equal(response.status,200);
const retainedPage=await response.json();
assert.equal(retainedPage.history_gap,true);
assert.equal(retainedPage.purged_through_cursor,3);
assert.equal(retainedPage.pushes[0].cursor,5);
response=await handleRequest(new Request("https://relay.example/v1/ptt?aid=M.123.A.2&after_cursor=2&limit=200"),retentionEnv);
assert.equal((await response.json()).history_gap,false);
// Duplicate publish cannot resurrect purged history or regress watermarks.
response=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},body:JSON.stringify({...batch,pushes:[(()=>{const row={...push,source_line:1003,floor:1003};delete row.push_id;return {...row,push_id:canonicalPushId(row)};})()]})}),retentionEnv);
assert.equal((await response.json()).accepted,0);
assert.equal(retentionDB.watermarks.get("M.123.A.1"),3);



// Sparse cursor proof: logical row count must govern retention, not max(cursor).
const sparseDB = new FakeDB();
sparseDB.rows = Array.from({length:1000}, (_,i)=>({...push,cursor:i===999?9000:i+1,push_id:`sparse-${i}`}));
sparseDB.cursor=9000;
const sparseEnv={...env,DB:sparseDB};
const lateBase={...push,source_line:1005,floor:1005};delete lateBase.push_id;
const late={...lateBase,push_id:canonicalPushId(lateBase)};
response=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{
  method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},
  body:JSON.stringify({...batch,pushes:[late]})
}),sparseEnv);
assert.equal(response.status,200);
assert.equal(sparseDB.rows.length,1000);
assert.equal(sparseDB.rows[0].cursor,2);
assert.equal(sparseDB.watermarks.get(push.aid),1);
const afterFirstMutation=sparseDB.mutationCount;
response=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{
  method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},
  body:JSON.stringify({...batch,pushes:[late]})
}),sparseEnv);
assert.equal((await response.json()).accepted,0);
assert.equal(sparseDB.mutationCount,afterFirstMutation);


 // Duplicate with one fresh push: only the new row should attempt insertion.
const mixedDB = new FakeDB();
const mixedEnv = {...env, DB:mixedDB};
const postMixed = async pushes => {
  const result=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{
    method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},
    body:JSON.stringify({...batch,pushes})
  }),mixedEnv);
  assert.equal(result.status,200);
  return result.json();
};
assert.deepEqual(await postMixed([push]),{schema_version:1,received:1,accepted:1});
assert.equal(mixedDB.cursor,1);
const mixedBefore = mixedDB.mutationCount;
assert.deepEqual(await postMixed([push]),{schema_version:1,received:1,accepted:0});
assert.equal(mixedDB.cursor,1,"duplicate-only POST must not consume AUTOINCREMENT");
assert.equal(mixedDB.mutationCount,mixedBefore);
assert.deepEqual(await postMixed([push,second]),{schema_version:1,received:2,accepted:1});
assert.equal(mixedDB.cursor,2,"mixed duplicate/new POST must insert only new ID");
assert.equal(mixedDB.rows.length,2);
assert.equal(mixedDB.mutationCount,mixedBefore+4);

 // A long-running duplicate storm must not create sparse cursor gaps.
for (let i=0; i<5000; i++) {
  const ack=await postMixed([push,second]);
  assert.equal(ack.accepted,0);
}
assert.equal(mixedDB.cursor,2);
assert.equal(mixedDB.rows.length,2);


// Replay of purged canonical ID is rejected, not resurrected or falsely ACKed.
const purgedReplayDB = new FakeDB();
const purgedReplayEnv = {...env,DB:purgedReplayDB};
purgedReplayDB.floors.set(push.aid, push.source_line);
const replayResult=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{
  method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},
  body:JSON.stringify(batch)
}),purgedReplayEnv);
assert.equal(replayResult.status,409);
assert.equal(purgedReplayDB.rows.length,0);
assert.equal(purgedReplayDB.mutationCount,0);
// Existing migration with watermark but no new provenance floor must fail closed.
const legacyPurgedDB = new FakeDB();
legacyPurgedDB.watermarks.set(push.aid,5);
const legacyReply=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{
  method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},
  body:JSON.stringify(batch)
}),{...env,DB:legacyPurgedDB});
assert.equal(legacyReply.status,409);
assert.equal(legacyPurgedDB.rows.length,0);


// Full Worker-path replay after actual retention must be rejected.
const purgedOld = {...push};
const beforePurgedReplayCount = retentionDB.rows.length;
const replayAfterPrune = await handleRequest(new Request(
  "https://relay.example/v1/ptt/publish", {
    method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},
    body:JSON.stringify({...batch,pushes:[purgedOld]})
  }), retentionEnv);
assert.equal(replayAfterPrune.status,409);
assert.equal(retentionDB.rows.length,beforePurgedReplayCount);

// Two simultaneous producers of the same ID: transaction and UNIQUE must
// allow only one effective accepted mutation even with a shared fake backend.
const concurrentDB=new FakeDB();
const concurrentEnv={...env,DB:concurrentDB};
const postConcurrent = () => handleRequest(new Request(
  "https://relay.example/v1/ptt/publish", {
    method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},
    body:JSON.stringify(batch)
  }), concurrentEnv);
const parallel = await Promise.all([postConcurrent(),postConcurrent()]);
const replies = await Promise.all(parallel.map(r=>r.json()));
assert.equal(replies.reduce((total,r)=>total+r.accepted,0),1);
assert.equal(concurrentDB.rows.length,1);


// A database rate-limit abort is a distinguishable fail-closed HTTP 429,
// rather than a generic 500 or a false matching ACK.
const rateRejectDB = new FakeDB();
rateRejectDB.batch = async () => { throw new Error("minute insert budget exceeded"); };
const rateReject=await handleRequest(new Request(
  "https://relay.example/v1/ptt/publish",{
    method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},
    body:JSON.stringify(batch)
  }),{...env,DB:rateRejectDB});
assert.equal(rateReject.status,429);
assert.match((await rateReject.json()).error,/write budget exceeded/);


// Free-tier D1 compatibility: 200 pushes, many AIDs, duplicate/mixed ACK,
// every single SQL statement <=100 bound params and <=50 statements/request.
const budgetDB=new FakeDB();
let requestQueries=0;
let largestBind=0;
const originalPrepare=budgetDB.prepare.bind(budgetDB);
budgetDB.prepare=sql=>{
  requestQueries++;
  if(requestQueries>50)throw Error("Workers Free query budget exceeded");
  const stmt=originalPrepare(sql);
  const bind=stmt.bind.bind(stmt);
  stmt.bind=(...args)=>{largestBind=Math.max(largestBind,args.length);return bind(...args);};
  return stmt;
};
const budgetEnv={...env,DB:budgetDB};
const makePush=(i,aid)=>{const row={...pushBase,aid,source_line:i+1,floor:i+1};return {...row,push_id:canonicalPushId(row)};};
const fullPushes=Array.from({length:200},(_,i)=>makePush(i,`AID-${i}`));
const publishBudget=async pushes=>{
  requestQueries=0;largestBind=0;
  const result=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{
    method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},
    body:JSON.stringify({...batch,pushes})
  }),budgetEnv);
  return {status:result.status,body:await result.json(),queries:requestQueries,binds:largestBind};
};
let full=await publishBudget(fullPushes);
assert.equal(full.status,200);
assert.equal(full.body.received,200);
assert.equal(full.body.accepted,200);
assert.ok(full.queries<=50);
assert.ok(full.binds<=100);
assert.equal(budgetDB.rows.length,200);
const noOpMutationCount=budgetDB.mutationCount;
full=await publishBudget(fullPushes);
assert.equal(full.status,200);
assert.equal(full.body.received,200);
assert.equal(full.body.accepted,0);
assert.ok(full.queries<=50);
assert.equal(budgetDB.mutationCount,noOpMutationCount,
  "full-size duplicate-only POST must execute no mutating SQL");
assert.equal(budgetDB.rows.length,200);
const extraPushes=Array.from({length:100},(_,i)=>makePush(i+200,`AID-extra-${i}`));
full=await publishBudget([...fullPushes.slice(0,100),...extraPushes]);
assert.equal(full.status,200);
assert.equal(full.body.received,200);
assert.equal(full.body.accepted,100);
assert.equal(budgetDB.rows.length,300);
assert.ok(full.queries<=50 && full.binds<=100);
budgetDB.floors.set("AID-blocked",3);
full=await publishBudget([makePush(0,"AID-blocked")]);
assert.equal(full.status,409);
assert.equal(budgetDB.rows.length,300);
// Fail-closed across 3 floor-query chunks (200 distinct article IDs):
// source-line rejection in the *last* chunk must abort BEFORE mutating batch.
const lateBlockDB=new FakeDB();
const lateBlockEnv={...env,DB:lateBlockDB};
const lastAid="AID-199";
lateBlockDB.floors.set(lastAid,200);
const lastResponse=await handleRequest(new Request("https://relay.example/v1/ptt/publish",{
  method:"POST",headers:{"authorization":"Bearer secret","content-type":"application/json"},
  body:JSON.stringify({...batch,pushes:fullPushes})
}),lateBlockEnv);
assert.equal(lastResponse.status,409);
assert.equal(lateBlockDB.rows.length,0);
assert.equal(lateBlockDB.mutationCount,0);
const originalBudgetBatch=budgetDB.batch.bind(budgetDB);
budgetDB.batch=async()=>{throw new Error("hour insert budget exceeded");};
full=await publishBudget([makePush(400,"AID-429")]);
assert.equal(full.status,429);
budgetDB.batch=originalBudgetBatch;

// Read responses must stay within the relay v1 512 KiB wire bound and paginate.
const byteDB = new FakeDB();
byteDB.rows = Array.from({length:500}, (_,i) => {
  const row = {
    ...push,
    aid:"M.123.A.9",
    source_line:i+1,
    floor:i+1,
    content:"界".repeat(1000),
  };
  delete row.push_id;
  return {...row, cursor:i+1, push_id:canonicalPushId(row)};
});
byteDB.cursor = 500;
const byteEnv = {...env, DB:byteDB};
response = await handleRequest(
  new Request("https://relay.example/v1/ptt?aid=M.123.A.9&after_cursor=0&limit=500"),
  byteEnv,
);
assert.equal(response.status,200);
const firstText = await response.text();
assert.ok(new TextEncoder().encode(firstText).byteLength <= 512 * 1024);
const firstPage = JSON.parse(firstText);
assert.equal(firstPage.has_more,true);
assert.ok(firstPage.pushes.length > 0 && firstPage.pushes.length < 500);
response = await handleRequest(
  new Request(`https://relay.example/v1/ptt?aid=M.123.A.9&after_cursor=${firstPage.next_cursor}&limit=500`),
  byteEnv,
);
assert.equal(response.status,200);
const secondPage = await response.json();
assert.ok(secondPage.pushes.length > 0);
assert.ok(secondPage.next_cursor > firstPage.next_cursor);

execFileSync("python3", ["test_relay_schema_sqlite.py"], {stdio: "inherit"});
console.log("relay worker adapter tests: pass");
