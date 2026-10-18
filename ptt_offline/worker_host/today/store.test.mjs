// Run: node --test backend/today/d1/store.test.mjs
// Offline D1-compatible facade using Node built-in SQLite; no Cloudflare calls.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {writeEvidence,setCoverage,readToday,YOUTUBE_LIVE_SOURCE,HISTORY_SOURCE_REVISION} from './store.mjs';
const C='UC'+'A'.repeat(22), V='abcdefghijk';
function fixture({id=V,state='live',observed='2026-10-15T11:59:00Z',end=null,group='hololive'}={}) {
  return {video_id:id,channel_id:C,roster_version:'fixture-v1',group,
    title:'Fixture',channel_name:'Fixture channel',lifecycle_state:state,
    observed_at:observed,scheduled_start:'2026-10-16T00:00:00Z',
    actual_start:state==='upcoming'?null:'2026-10-15T11:00:00Z',
    actual_end:end,source_label:YOUTUBE_LIVE_SOURCE};
}
function db() {
  const sqlite=new DatabaseSync(':memory:');
  sqlite.exec(readFileSync(new URL('./0002_today_canonical.sql',import.meta.url),'utf8'));
  sqlite.exec('CREATE TABLE public_catalog(video_id TEXT,channel_id TEXT,avatar_url TEXT,actual_start TEXT,scheduled_start TEXT)');
  sqlite.exec(`CREATE TABLE public_history(
    video_id TEXT PRIMARY KEY NOT NULL,taipei_day TEXT NOT NULL,title TEXT NOT NULL,
    channel_id TEXT NOT NULL,channel_name TEXT NOT NULL DEFAULT '',avatar_url TEXT NOT NULL DEFAULT '',
    scheduled_start TEXT,actual_start TEXT,actual_end TEXT NOT NULL,source_revision TEXT NOT NULL,published_at TEXT NOT NULL
  )`);
  function statement(sql,params=[]){
    return {
      bind(...values){return statement(sql,values)},
      async first(){return sqlite.prepare(sql).get(...params)??null},
      async all(){return {results:sqlite.prepare(sql).all(...params)}},
      async run(){return sqlite.prepare(sql).run(...params)}
    };
  }
  const wrap={
    prepare(sql){return statement(sql)},
    async batch(statements){
      sqlite.exec('BEGIN IMMEDIATE');
      try {
        const result=[];
        for(const s of statements) result.push(await s.run());
        sqlite.exec('COMMIT');
        return result;
      } catch(e) {
        sqlite.exec('ROLLBACK');
        throw e;
      }
    },
    close(){sqlite.close()},
    raw:sqlite
  };
  return wrap;
}
test('create/replay/update/read and durable END',async()=>{
  const d=db();
  assert.equal((await writeEvidence(d,fixture())).changed,true);
  assert.equal((await writeEvidence(d,fixture())).changed,false);
  assert.equal(d.raw.prepare('SELECT COUNT(*) n FROM public_today_evidence').get().n,1);
  const ended=fixture({state:'ended',observed:'2026-10-15T12:02:00Z',end:'2026-10-15T12:01:00Z'});
  assert.equal((await writeEvidence(d,ended)).changed,true);
  const old=fixture({observed:'2026-10-15T12:04:00Z'});
  assert.equal((await writeEvidence(d,old)).changed,false);
  await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-15T12:04:00Z',expected_channels:1,scanned_channels:1,gap:false,approved_channels:[{id:C,group:'hololive'}],checkpoint:'cp_abcdefgh'});
  const result=await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T16:00:00Z')});
  assert.equal(result.streams.length,1);
  assert.equal(result.streams[0].lifecycle_state,'ended');
  assert.equal(result.completeness.status,'partial'); // no self-certified COMPLETE
  assert.equal(result.checkpoint,'cp_abcdefgh');
  assert.equal(d.raw.prepare('SELECT COUNT(*) n FROM public_today_evidence').get().n,3);
  d.close();
});
test('same observation key cannot introduce contradictory facts',async()=>{
  const d=db();await writeEvidence(d,fixture());
  await assert.rejects(()=>writeEvidence(d,{...fixture(),title:'Contradiction'}),/contradictory/);
  d.close();
});
test('new approved roster updates same publisher and preserves both evidence versions',async()=>{
  const d=db();await writeEvidence(d,fixture());
  const next={...fixture({observed:'2026-10-15T12:05:00Z'}),roster_version:'fixture-v2'};
  assert.equal((await writeEvidence(d,next)).changed,true);
  assert.equal((await writeEvidence(d,next)).changed,false);
  assert.equal(d.raw.prepare('SELECT roster_version FROM public_today_canonical WHERE video_id=?').get(V).roster_version,'fixture-v2');
  assert.equal(d.raw.prepare('SELECT COUNT(DISTINCT roster_version) n FROM public_today_evidence WHERE video_id=?').get(V).n,2);
  await setCoverage(d,{roster_version:'fixture-v2',last_success_at:'2026-10-15T12:05:00Z',expected_channels:1,scanned_channels:1,gap:false,approved_channels:[{id:C,group:'hololive'}]});
  assert.equal((await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T12:06:00Z')})).streams.length,1);
  d.close();
});
test('changed publisher still rejects',async()=>{
  const d=db();await writeEvidence(d,fixture());
  await assert.rejects(()=>writeEvidence(d,{...fixture({observed:'2026-10-15T12:05:00Z'}),channel_id:'UC'+'B'.repeat(22)}),/mismatch/);
  d.close();
});
test('coverage cannot leak integer checkpoint; empty result stays partial/unverified',async()=>{
  const d=db();
  await setCoverage(d,{roster_version:'fixture-v1',expected_channels:1,scanned_channels:0,gap:true,approved_channels:[{id:C,group:'hololive'}],checkpoint:7});
  const x=await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T12:00:00Z')});
  assert.equal(x.streams.length,0);
  assert.equal(x.completeness.gap,true);
  assert.equal(x.checkpoint,null);
  assert.notEqual(x.completeness.status,'complete');
  d.close();
});
test('migration can be applied repeatedly without dropping data',async()=>{
  const d=db();await writeEvidence(d,fixture());
  d.raw.exec(readFileSync(new URL('./0002_today_canonical.sql',import.meta.url),'utf8'));
  assert.equal(d.raw.prepare('SELECT COUNT(*) n FROM public_today_canonical').get().n,1);
  d.close();
});
test('invalid lifecycle and bad day reject without source modifications',async()=>{
  const d=db();
  await assert.rejects(()=>writeEvidence(d,fixture({state:'ended',end:null})),/end requires positive/);
  await assert.rejects(()=>readToday(d,{day:'2026-1-5'}));
  d.close();
});

test('Taipei requested day excludes unrelated prior-day entries',async()=>{
  const d=db();
  await writeEvidence(d,{...fixture({id:'oldvideo001',state:'unknown',observed:'2026-10-13T08:00:00Z'}),actual_start:null,scheduled_start:'2026-10-13T09:00:00Z'});
  await writeEvidence(d,{...fixture({id:'newvideo001',state:'upcoming',observed:'2026-10-15T02:00:00Z'}),actual_start:null,scheduled_start:'2026-10-15T03:00:00Z'});
  await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-15T02:00:00Z',expected_channels:1,scanned_channels:1,gap:false,approved_channels:[{id:C,group:'hololive'}]});
  const result=await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T02:01:00Z')});
  assert.deepEqual(result.streams.map(x=>x.video_id),['newvideo001']);
  d.close();
});
test('bounded cross-midnight LIVE survives and unrelated ancient LIVE is excluded',async()=>{
  const d=db();
  await writeEvidence(d,{...fixture({id:'carrylive01',observed:'2026-10-15T01:59:00Z'}),actual_start:'2026-10-14T13:00:00Z',scheduled_start:'2026-10-14T13:00:00Z'});
  await writeEvidence(d,{...fixture({id:'distantlive',observed:'2026-10-12T02:00:00Z'}),actual_start:'2026-10-12T01:00:00Z',scheduled_start:'2026-10-12T01:00:00Z'});
  await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-15T02:00:00Z',expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
  const result=await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T02:00:00Z')});
  assert.deepEqual(result.streams.map(x=>x.video_id),['carrylive01']);
  d.close();
});

test('roster v2 activates approved publisher without freezing v1 canonical row',async()=>{
  const d=db();await writeEvidence(d,fixture());
  await setCoverage(d,{roster_version:'fixture-v2',last_success_at:'2026-10-15T12:00:00Z',
    expected_channels:1,scanned_channels:1,gap:false,approved_channels:[{id:C,group:'hololive'}]});
  const rows=await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T12:01:00Z')});
  assert.equal(rows.streams.length,1);
  assert.equal(rows.streams[0].video_id,V);
  assert.equal(d.raw.prepare('SELECT roster_version FROM public_today_canonical WHERE video_id=?').get(V).roster_version,'fixture-v1');
  d.close();
});
test('removed publisher excluded immediately at approved roster rollover',async()=>{
  const d=db();await writeEvidence(d,fixture());
  const removed='UC'+'B'.repeat(22);
  await setCoverage(d,{roster_version:'fixture-v2',last_success_at:'2026-10-15T12:00:00Z',
    expected_channels:1,scanned_channels:1,gap:false,approved_channels:[{id:removed,group:'other'}]});
  const rows=await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T12:01:00Z')});
  assert.equal(rows.streams.length,0);
  d.close();
});

test('channel avatar projects only approved existing catalog channel artwork, not thumbnails',async()=>{
 const d=db();

 d.raw.prepare('INSERT INTO public_catalog VALUES(?,?,?,?,?)').run('catalog0001',C,'https://yt3.ggpht.com/verified-avatar',null,'2026-10-15T12:00:00Z');
 await writeEvidence(d,fixture());
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-15T11:59:00Z',expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
 const result=await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T12:01:00Z')});
 assert.equal(result.streams[0].avatar_url,'https://yt3.ggpht.com/verified-avatar');
 d.raw.prepare('UPDATE public_catalog SET avatar_url=?').run('https://evil.example/video-thumbnail.png');
 const denied=await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T12:01:00Z')});
 assert.equal(denied.streams[0].avatar_url,null);
 d.close();
});

test('Today LIMIT explicitly reports truncation, retaining title and source for client highlight scoring',async()=>{
 const d=db();
 for(let i=0;i<201;i++){
  const video_id='v'+String(i).padStart(10,'0');
  await writeEvidence(d,{...fixture({id:video_id,observed:'2026-10-15T11:59:00Z'}),title:i===0?'重大告知 生日':'Other',source_label:YOUTUBE_LIVE_SOURCE});
 }
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-15T12:00:00Z',expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
 const x=await readToday(d,{day:'2026-10-15',limit:200,now:new Date('2026-10-15T12:00:00Z')});
 assert.equal(x.streams.length,200);assert.equal(x.completeness.limited,true);assert.equal(x.completeness.gap,true);
 assert.equal(x.streams[0].source_label,'YouTube');
 d.close();
});
test('accepted 20-minute item freshness status at 19, 21 and 31 minutes',async()=>{
 const d=db();await writeEvidence(d,fixture({observed:'2026-10-15T12:00:00Z'}));
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-15T12:00:00Z',expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
 for(const [minutes,expected] of [[19,'live'],[21,'stale'],[31,'stale']]){
  const x=await readToday(d,{day:'2026-10-15',now:new Date(Date.parse('2026-10-15T12:00:00Z')+minutes*60000)});
  assert.equal(x.streams[0].lifecycle_state,expected);
 }
 d.close();
});

test('offset paging surfaces older highlight candidates instead of silently dropping them',async()=>{
 const d=db();
 for(let i=0;i<205;i++)await writeEvidence(d,{...fixture({id:'p'+String(i).padStart(10,'0')}),title:i===0?'誕生日 重大告知':'regular stream'});
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-15T12:00:00Z',expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
 const first=await readToday(d,{day:'2026-10-15',limit:200,offset:0,now:new Date('2026-10-15T12:00:00Z')});
 const second=await readToday(d,{day:'2026-10-15',limit:200,offset:200,now:new Date('2026-10-15T12:00:00Z')});
 assert.equal(first.completeness.has_more,true);
 assert.equal(second.completeness.has_more,false);
 assert.equal(second.streams.length,5);
 assert.equal(new Set([...first.streams,...second.streams].map(x=>x.video_id)).size,205);
 assert.ok([...first.streams,...second.streams].some(x=>x.title.includes('誕生日')));
 await assert.rejects(()=>readToday(d,{day:'2026-10-15',offset:10001}),/offset/);
 d.close();
});
test('overnight Home reads previous day until 05:59 Taipei but not after 06:00',async()=>{
 const d=db();
 await writeEvidence(d,{...fixture({id:'oldnight001',state:'ended',observed:'2026-10-15T15:57:00Z',end:'2026-10-15T15:56:00Z'}),actual_start:'2026-10-15T15:00:00Z',scheduled_start:'2026-10-15T15:00:00Z'});
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-15T16:00:00Z',expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
 for(const [time,count] of [['2026-10-15T16:15:00Z',1],['2026-10-15T21:59:00Z',1],['2026-10-15T22:00:00Z',0]]){
  const x=await readToday(d,{day:'2026-10-16',now:new Date(time)});
  assert.equal(x.streams.length,count,time);
 }
 d.close();
});

test('new verified profile avatar is opt-in and legacy API remains readable before migration',async()=>{
 const d=db();
 await writeEvidence(d,fixture());
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-15T12:00:00Z',expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
 const old=await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T12:00:00Z')});
 assert.equal(old.streams[0].avatar_url,null);
 d.raw.exec(readFileSync(new URL('./websub-event-queue.PROPOSED.sql',import.meta.url),'utf8'));
 d.raw.exec(readFileSync(new URL('./websub-hardening.PROPOSED.sql',import.meta.url),'utf8'));
 d.raw.prepare("INSERT INTO public_today_channel_profiles(channel_id,roster_version,channel_title,avatar_url,fetched_at,source) VALUES(?,?,?,?,?,'youtube_channels_list')")
  .run(C,'fixture-v1','Verified','https://yt3.ggpht.com/approved','2026-10-15T12:00:00Z');
 const fresh=await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T12:00:00Z'),profileTableEnabled:true});
 assert.equal(fresh.streams[0].avatar_url,'https://yt3.ggpht.com/approved');
 const unchanged=await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T12:00:00Z')});
 assert.equal(unchanged.streams[0].avatar_url,null);
 d.close();
});

test('4174 Home envelope degrades malformed optional fields per-row instead of failing whole response',async()=>{
 const d=db();
 await writeEvidence(d,fixture());
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-15T12:00:00Z',expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
 const corrupt={
  ...d,
  prepare(sql){
   const stmt=d.prepare(sql);
   if(!sql.includes('SELECT public_today_canonical.*')) return stmt;
   return {
    bind(...args){
     const bound=stmt.bind(...args);
     return {
      async all(){
       const out=await bound.all();
       if(out.results?.[0]) Object.assign(out.results[0],{
        title:null,channel_name:null,channel_group:'invalid',
        scheduled_start:'not-a-time',actual_start:'not-a-time',
        source_label:null,trusted_channel_avatar:'javascript:bad'
       });
       return out;
      }
     };
    }
   };
  }
 };
 const result=await readToday(corrupt,{day:'2026-10-15',now:new Date('2026-10-15T12:00:00Z')});
 assert.equal(result.streams.length,1);
 assert.deepEqual({
  video_id:result.streams[0].video_id,
  title:result.streams[0].title,
  channel_id:result.streams[0].channel_id,
  channel_name:result.streams[0].channel_name,
  group:result.streams[0].group,
  start_at:result.streams[0].start_at,
  avatar_url:result.streams[0].avatar_url,
  source_label:result.streams[0].source_label
 },{video_id:V,title:'',channel_id:C,channel_name:'',group:'other',start_at:null,avatar_url:null,source_label:''});
 d.close();
});

test('4174 Home drops a row with corrupt primary identity but preserves valid siblings',async()=>{
 const d=db();
 await writeEvidence(d,fixture());
 await writeEvidence(d,fixture({id:'zzzzzzzzzzz'}));
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-15T12:00:00Z',expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
 const corrupt={
  ...d,
  prepare(sql){
   const stmt=d.prepare(sql);
   if(!sql.includes('SELECT public_today_canonical.*')) return stmt;
   return {
    bind(...args){
     const bound=stmt.bind(...args);
     return {async all(){
      const out=await bound.all();
      if(out.results?.[0]) out.results[0].video_id='bad';
      return out;
     }};
    }
   };
  }
 };
 const result=await readToday(corrupt,{day:'2026-10-15',now:new Date('2026-10-15T12:00:00Z')});
 assert.equal(result.streams.length,1);
 assert.match(result.streams[0].video_id,/^[A-Za-z0-9_-]{11}$/);
 d.close();
});

test('Today membership uses actual/scheduled starts, not later refresh or end timestamps',async()=>{
 const d=db();
 const cases=[
  {id:'oct13ended1',start:'2026-10-13T10:00:00Z',end:'2026-10-13T12:00:00Z',observed:'2026-10-16T07:00:00Z',state:'ended',visible:false},
  {id:'oct14ended1',start:'2026-10-14T10:00:00Z',end:'2026-10-14T12:00:00Z',observed:'2026-10-16T07:00:00Z',state:'ended',visible:false},
  {id:'oct16ended1',start:'2026-10-16T02:00:00Z',end:'2026-10-16T03:00:00Z',observed:'2026-10-16T07:00:00Z',state:'ended',visible:true},
  {id:'oct16upcom1',start:'2026-10-16T12:00:00Z',end:null,observed:'2026-10-16T07:00:00Z',state:'upcoming',visible:true},
  {id:'oct16live01',start:'2026-10-16T06:00:00Z',end:null,observed:'2026-10-16T07:00:00Z',state:'live',visible:true},
  {id:'crosslive01',start:'2026-10-15T14:00:00Z',end:null,observed:'2026-10-16T06:59:00Z',state:'live',visible:true},
  {id:'staleoldlv1',start:'2026-10-13T12:00:00Z',end:null,observed:'2026-10-14T12:00:00Z',state:'live',visible:false},
 ];
 for(const c of cases){
  await writeEvidence(d,{...fixture({id:c.id,state:c.state,observed:c.observed,end:c.end}),
    actual_start:c.state==='upcoming'?null:c.start,scheduled_start:c.start});
 }
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-16T07:00:00Z',
  expected_channels:1,scanned_channels:1,gap:false,approved_channels:[{id:C,group:'hololive'}]});
 const x=await readToday(d,{day:'2026-10-16',now:new Date('2026-10-16T07:00:00Z')});
 const present=new Set(x.streams.map(r=>r.video_id));
 for(const c of cases)assert.equal(present.has(c.id),c.visible,c.id);
 // Today filtering is a read-only projection; older source remains untouched.
 assert.equal(d.raw.prepare('SELECT COUNT(*) AS n FROM public_today_canonical').get().n,cases.length);
 d.close();
});


test('ended Today row exposes authoritative YouTube actual bounds for same-day PTT bridge',async()=>{
 const d=db();
 await writeEvidence(d,{
  ...fixture({id:'zPCcFbCONek',state:'ended',observed:'2026-10-18T04:50:19Z',end:'2026-10-18T04:49:00Z'}),
  scheduled_start:'2026-10-18T03:15:00Z',
  actual_start:'2026-10-18T03:15:53Z',
  actual_end:'2026-10-18T04:49:00Z',
  source_label:YOUTUBE_LIVE_SOURCE
 });
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-18T04:50:19Z',
  expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
 const x=await readToday(d,{day:'2026-10-18',now:new Date('2026-10-18T04:51:00Z')});
 assert.equal(x.streams.length,1);
 const row=x.streams[0];
 assert.equal(row.video_id,'zPCcFbCONek');
 assert.equal(row.lifecycle_state,'ended');
 assert.equal(row.actual_start,'2026-10-18T03:15:53Z');
 assert.equal(row.actual_end,'2026-10-18T04:49:00Z');
 assert.equal(row.anchor_source,'youtube-liveStreamingDetails-actualStartTime');
 assert.equal(row.start_at,row.actual_start);
 d.close();
});

test('Today projection never exposes untrusted actual bounds as authoritative',async()=>{
 const d=db();
 await writeEvidence(d,{
  ...fixture({id:'untrusted01',state:'ended',observed:'2026-10-18T04:50:19Z',end:'2026-10-18T04:49:00Z'}),
  scheduled_start:'2026-10-18T03:15:00Z',
  actual_start:'2026-10-18T03:15:53Z',
  actual_end:'2026-10-18T04:49:00Z',
  source_label:'legacy-import'
 });
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-18T04:50:19Z',
  expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
 const x=await readToday(d,{day:'2026-10-18',now:new Date('2026-10-18T04:51:00Z')});
 assert.equal(x.streams.length,1);
 assert.equal(x.streams[0].actual_start,null);
 assert.equal(x.streams[0].actual_end,null);
 assert.equal(x.streams[0].anchor_source,null);
 assert.equal(x.streams[0].start_at,'2026-10-18T03:15:00Z');
 d.close();
});


test('trusted ended evidence is idempotently projected into recent public_history',async()=>{
 const d=db();
 const ended={
  ...fixture({id:'recenthist01',state:'ended',observed:'2026-10-18T05:00:00Z',end:'2026-10-18T04:49:00Z'}),
  scheduled_start:'2026-10-18T03:15:00Z',
  actual_start:'2026-10-18T03:15:53Z',
  actual_end:'2026-10-18T04:49:00Z',
  source_label:YOUTUBE_LIVE_SOURCE
 };
 await writeEvidence(d,ended);
 const row=d.raw.prepare('SELECT * FROM public_history WHERE video_id=?').get('recenthist01');
 assert.equal(row.taipei_day,'2026-10-18');
 assert.equal(row.actual_start,'2026-10-18T03:15:53Z');
 assert.equal(row.actual_end,'2026-10-18T04:49:00Z');
 assert.equal(row.source_revision,HISTORY_SOURCE_REVISION);
 assert.equal(d.raw.prepare('SELECT COUNT(*) n FROM public_history WHERE video_id=?').get('recenthist01').n,1);
 const newer={...ended,observed_at:'2026-10-18T05:05:00Z'};
 await writeEvidence(d,newer);
 assert.equal(d.raw.prepare('SELECT COUNT(*) n FROM public_history WHERE video_id=?').get('recenthist01').n,1);
 assert.equal(d.raw.prepare('SELECT published_at FROM public_history WHERE video_id=?').get('recenthist01').published_at,'2026-10-18T05:05:00Z');
 d.close();
});

test('Today 4174 rules keep yesterday ended until noon, then remove it',async()=>{
 const d=db();
 await writeEvidence(d,{
  ...fixture({id:'yesterday01',state:'ended',observed:'2026-10-17T15:55:00Z',end:'2026-10-17T15:50:00Z'}),
  scheduled_start:'2026-10-17T14:00:00Z',actual_start:'2026-10-17T14:01:00Z',
  actual_end:'2026-10-17T15:50:00Z',source_label:YOUTUBE_LIVE_SOURCE
 });
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-18T01:00:00Z',
  expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
 const morning=await readToday(d,{day:'2026-10-18',now:new Date('2026-10-18T03:59:59Z')});
 assert.deepEqual(morning.streams.map(x=>x.video_id),['yesterday01']);
 const noon=await readToday(d,{day:'2026-10-18',now:new Date('2026-10-18T04:00:00Z')});
 assert.deepEqual(noon.streams.map(x=>x.video_id),[]);
 d.close();
});

test('Today 4174 rules keep fresh live regardless start date and drop stale live',async()=>{
 const d=db();
 await writeEvidence(d,{
  ...fixture({id:'oldlive0001',state:'live',observed:'2026-10-18T03:50:00Z'}),
  scheduled_start:'2026-10-16T03:00:00Z',actual_start:'2026-10-16T03:01:00Z',
  actual_end:null,source_label:YOUTUBE_LIVE_SOURCE
 });
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-18T03:50:00Z',
  expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
 const fresh=await readToday(d,{day:'2026-10-18',now:new Date('2026-10-18T04:10:00Z')});
 assert.equal(fresh.streams[0].video_id,'oldlive0001');
 assert.equal(fresh.streams[0].lifecycle_state,'live');
 const stale=await readToday(d,{day:'2026-10-18',now:new Date('2026-10-18T04:10:01Z')});
 assert.equal(stale.streams.length,0);
 d.close();
});

test('Today 4174 rules keep current-day and future upcoming without observation freshness',async()=>{
 const d=db();
 await writeEvidence(d,{
  ...fixture({id:'todayupcom1',state:'upcoming',observed:'2026-10-17T00:00:00Z'}),
  scheduled_start:'2026-10-18T08:00:00Z',actual_start:null,actual_end:null
 });
 await writeEvidence(d,{
  ...fixture({id:'futureup001',state:'upcoming',observed:'2026-10-17T00:00:00Z'}),
  scheduled_start:'2026-10-20T08:00:00Z',actual_start:null,actual_end:null
 });
 await writeEvidence(d,{
  ...fixture({id:'pastupcom01',state:'upcoming',observed:'2026-10-17T00:00:00Z'}),
  scheduled_start:'2026-10-17T08:00:00Z',actual_start:null,actual_end:null
 });
 await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-18T00:00:00Z',
  expected_channels:1,scanned_channels:1,gap:true,approved_channels:[{id:C,group:'hololive'}]});
 const x=await readToday(d,{day:'2026-10-18',now:new Date('2026-10-18T05:00:00Z')});
 assert.deepEqual(new Set(x.streams.map(r=>r.video_id)),new Set(['todayupcom1','futureup001']));
 assert.ok(x.streams.every(r=>r.lifecycle_state==='upcoming'||r.lifecycle_state==='waiting'));
 d.close();
});
