import test from 'node:test';
import assert from 'node:assert/strict';
import host from './worker_host/index.mjs';

// Exercise the real deployed composition and real PTT D1 query handler.
// Read-only fake D1 responds to the precise query shapes used by the route.
function db({threads=['aid-day','aid-night'],rows=[],gap=false}={}){
  let writes=0;
  return {
    get writes(){return writes;},
    prepare(sql){
      if (/\b(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP)\b/i.test(sql)){
        writes++; throw new Error('unexpected write');
      }
      return {bind(...args){
        return {
          async all(){
            if(sql.includes('FROM ptt_provider_state'))return {results:threads.map(aid=>({aid,last_success_at:'2026-10-16T08:00:00Z',has_gap:gap?1:0}))};
            if(sql.includes('FROM ptt_threads'))return {results:threads.map(aid=>({aid}))};
            if(sql.includes('FROM ptt_pushes')){
              const ascending=sql.includes('ORDER BY occurred_at ASC');
              const limit=args.at(-1);
              const anchor=sql.includes('(occurred_at,aid,source_line,push_id)>')?args.slice(1,5):null;
              const cmp=(a,b)=>a.occurred_at.localeCompare(b.occurred_at)||a.aid.localeCompare(b.aid)||a.source_line-b.source_line||a.push_id.localeCompare(b.push_id);
              const dayScoped=sql.includes('WHERE day=?')?rows.filter(r=>r.day===args[0]):rows;
              return {results:dayScoped.filter(r=>!anchor||cmp(r,{occurred_at:anchor[0],aid:anchor[1],source_line:anchor[2],push_id:anchor[3]})>0).sort((a,b)=>ascending?cmp(a,b):-cmp(a,b)).slice(0,limit)};
            }
            return {results:[]};
          },
          async first(){
            if(sql.includes('FROM ptt_pushes')&&sql.includes('push_id=?'))return rows.find(r=>r.push_id===args[1])??null;
            return null;
          }
        };
      }};
    }
  };
}
const url=(route)=>new Request('https://public-api.example'+route);
const row=(id,aid,line,t,day=t.slice(0,10))=>({push_id:id,aid,day,source_line:line,kind:'推',author:'viewer',content:'fixture',occurred_at:t,floor:line,source_url:'https://www.ptt.cc',});
const day='2026-10-16';

test('recent tail merges previous and current Taipei day without writes',async()=>{
  const rows=[
    row('p-old','aid-night',98,'2026-10-15T15:58:00Z','2026-10-15'),
    row('p-last','aid-night',99,'2026-10-15T15:59:00Z','2026-10-15'),
    row('p-mid','aid-day',1,'2026-10-15T16:00:00Z','2026-10-16'),
    row('p-new','aid-day',2,'2026-10-15T16:01:00Z','2026-10-16'),
  ];
  const DB=db({rows});
  const original=Date.now;
  Date.now=()=>Date.parse('2026-10-15T16:05:00Z');
  try{
    const response=await host.fetch(url('/v1/ptt/recent?limit=3'),{DB});
    assert.equal(response.status,200);
    const body=await response.json();
    assert.equal(body.window.kind,'recent-tail');
    assert.deepEqual(body.window.taipei_days,['2026-10-15','2026-10-16']);
    assert.deepEqual(body.pushes.map(r=>r.push_id),['p-last','p-mid','p-new']);
    assert.equal(body.page.limit,3);
    assert.equal(body.page.has_more,true);
    assert.equal(DB.writes,0);
  }finally{Date.now=original;}
});

test('recent tail handles only-current and only-previous day',async()=>{
  const original=Date.now;
  Date.now=()=>Date.parse('2026-10-15T16:05:00Z');
  try{
    for(const fixture of [
      [row('current','aid-day',1,'2026-10-15T16:01:00Z','2026-10-16')],
      [row('previous','aid-night',9,'2026-10-15T15:59:00Z','2026-10-15')],
    ]){
      const DB=db({rows:fixture});
      const response=await host.fetch(url('/v1/ptt/recent?limit=1000'),{DB});
      assert.equal(response.status,200);
      assert.deepEqual((await response.json()).pushes.map(r=>r.push_id),[fixture[0].push_id]);
      assert.equal(DB.writes,0);
    }
  }finally{Date.now=original;}
});

test('recent tail rejects unbounded limit',async()=>{
  const DB=db({rows:[]});
  assert.equal((await host.fetch(url('/v1/ptt/recent?limit=1001'),{DB})).status,400);
  assert.equal(DB.writes,0);
});
test('actual worker host handles health, methods, CORS and empty-day availability',async()=>{
  const DB=db({threads:[]}),env={DB,ALLOWED_ORIGIN:'https://holoviewer.example'};
  assert.equal((await host.fetch(url('/health'),env)).status,200);
  assert.equal((await host.fetch(url('/v1/ptt/today?day='+day),env)).status,503);
  assert.equal((await host.fetch(url('/v1/ptt/history?day='+day),env)).status,503);
  assert.equal((await host.fetch(new Request('https://public-api.example/v1/ptt/today',{method:'OPTIONS',headers:{origin:'https://holoviewer.example'}}),env)).status,204);
  assert.equal((await host.fetch(new Request('https://public-api.example/v1/ptt/today',{method:'POST'}),env)).status,405);
  assert.equal((await host.fetch(new Request('https://public-api.example/v1/ptt/today',{headers:{origin:'https://untrusted.example'}}),env)).status,403);
  assert.equal(DB.writes,0);
});
test('actual worker host has multi-AID Today, forward history cursor and gap',async()=>{
  const DB=db({rows:[row('p1','aid-day',10,'2026-10-16T00:00:00Z'),row('p2','aid-night',11,'2026-10-16T00:01:00Z'),row('p3','aid-night',12,'2026-10-16T00:02:00Z')],gap:true});
  const env={DB};
  const today=await host.fetch(url('/v1/ptt/today?day='+day),env);
  assert.equal(today.status,200);
  const current=await today.json();
  assert.deepEqual(current.pushes.map(r=>r.push_id),['p1','p2','p3']);
  assert.equal(current.completeness.gap,true);
  const first=await host.fetch(url('/v1/ptt/history?day='+day+'&limit=2'),env);
  assert.equal(first.status,200);
  const a=await first.json();
  assert.deepEqual(a.pushes.map(r=>r.push_id),['p1','p2']);
  assert.equal(a.page.has_more,true);
  assert.equal(a.page.next_checkpoint,'p2');
  const second=await host.fetch(url('/v1/ptt/history?day='+day+'&limit=2&after=p2'),env);
  assert.equal(second.status,200);
  assert.deepEqual((await second.json()).pushes.map(r=>r.push_id),['p3']);
  assert.equal((await host.fetch(url('/v1/ptt/history?day='+day+'&after=bad'),env)).status,409);
  assert.equal((await host.fetch(url('/v1/ptt/history?day='+day+'&limit=201'),env)).status,400);
  assert.equal((await host.fetch(url('/v1/ptt/today?day=2026-02-30'),env)).status,400);
  assert.equal(DB.writes,0);
});
