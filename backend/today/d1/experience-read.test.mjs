import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {detectCollabCandidates,handleExperienceRead} from './experience-read.mjs';

const C1='UC'+'A'.repeat(22),C2='UC'+'B'.repeat(22);
function db(){
 const raw=new DatabaseSync(':memory:');
 raw.exec(readFileSync(new URL('./0002_today_canonical.sql',import.meta.url),'utf8'));
 raw.exec(readFileSync(new URL('./experience-read.PROPOSED.sql',import.meta.url),'utf8'));
 raw.exec('CREATE TABLE public_catalog(video_id TEXT,channel_id TEXT,avatar_url TEXT,actual_start TEXT,scheduled_start TEXT)');
 raw.exec('CREATE TABLE public_history(taipei_day TEXT,video_id TEXT,title TEXT,channel_id TEXT,channel_name TEXT,avatar_url TEXT,actual_start TEXT,actual_end TEXT,scheduled_start TEXT)');
 function stmt(sql,params=[]){return{
  bind(...x){return stmt(sql,x)},
  async first(){return raw.prepare(sql).get(...params)??null},
  async all(){return {results:raw.prepare(sql).all(...params)}},
  async run(){return raw.prepare(sql).run(...params)}
 }}
 return {raw,prepare(sql){return stmt(sql)},close(){raw.close()}};
}
test('4174 collab candidate rules remain candidate-only and sync only verified ended VODs',()=>{
 const events=detectCollabCandidates([
  {video_id:'aaaaaaaaaaa',channel_id:C1,channel_name:'A',title:'【ホロARK】day',lifecycle_state:'ended',actual_start:'2026-10-15T15:00:00Z',actual_end:'2026-10-15T17:00:00Z'},
  {video_id:'bbbbbbbbbbb',channel_id:C2,channel_name:'B',title:'【ホロARK】day',lifecycle_state:'ended',actual_start:'2026-10-15T17:00:00Z',actual_end:'2026-10-15T19:00:00Z'}
 ]);
 assert.equal(events.length,1);
 assert.equal(events[0].event_id,'ark:2026-10-15');
 assert.equal(events[0].candidate,true);
 assert.equal(events[0].sync.available,true);
 assert.equal(events[0].sync.basis,'youtube_actual_start');
 assert.equal(events[0].streams[1].sync_offset_ms,7200000);
});
test('history collab keeps 00-05:59 Taipei POVs on prior 06:00 event-day',async()=>{
 const d=db();
 d.raw.prepare('INSERT INTO public_history VALUES(?,?,?,?,?,?,?,?,?)').run('2026-10-15','aaaaaaaaaaa','【ホロARK】day',C1,'A',null,'2026-10-15T15:00:00Z','2026-10-15T18:00:00Z',null);
 d.raw.prepare('INSERT INTO public_history VALUES(?,?,?,?,?,?,?,?,?)').run('2026-10-16','bbbbbbbbbbb','【ホロARK】day',C2,'B',null,'2026-10-15T17:00:00Z','2026-10-15T20:00:00Z',null);
 const r=await handleExperienceRead(new Request('https://api.example/v1/collab/history?day=2026-10-15'),{DB:d});
 assert.equal(r.status,200);
 const body=await r.json();
 assert.equal(body.events.length,1);
 assert.equal(body.events[0].event_id,'ark:2026-10-15');
 assert.deepEqual(new Set(body.events[0].streams.map(x=>x.video_id)),new Set(['aaaaaaaaaaa','bbbbbbbbbbb']));
 d.close();
});
test('shared-topic current collab is conservative and does not enable archive sync for live streams',async()=>{
 const d=db();
 d.raw.prepare('INSERT INTO public_today_catalog_meta VALUES(1,?,?,?,?,?,?)').run('r1','2026-10-15T22:10:00Z',2,2,0,null);
 d.raw.prepare('INSERT INTO public_today_approved_channels VALUES(?,?,?,?)').run(C1,'r1','2026-10-15T22:00:00Z','hololive');
 d.raw.prepare('INSERT INTO public_today_approved_channels VALUES(?,?,?,?)').run(C2,'r1','2026-10-15T22:00:00Z','hololive');
 const ins=d.raw.prepare(`INSERT INTO public_today_canonical(video_id,publisher_channel_id,roster_version,channel_group,title,channel_name,lifecycle_state,lifecycle_observed_at,checked_at,scheduled_start,actual_start,actual_end,source_label,source_checksum) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`);
 ins.run('aaaaaaaaaaa',C1,'r1','hololive','SPECIALGAME together','A','live','2026-10-15T22:10:00Z','2026-10-15T22:10:00Z',null,'2026-10-15T22:00:00Z',null,'YouTube','x');
 ins.run('bbbbbbbbbbb',C2,'r1','hololive','SPECIALGAME POV','B','live','2026-10-15T22:10:00Z','2026-10-15T22:10:00Z',null,'2026-10-15T22:05:00Z',null,'YouTube','y');
 const r=await handleExperienceRead(new Request('https://api.example/v1/collab/live'),{DB:d},new Date('2026-10-15T22:11:00Z'));
 assert.equal(r.status,200);
 const body=await r.json();
 assert.equal(body.events.length,1);
 assert.equal(body.events[0].confidence,'shared-topic');
 assert.equal(body.events[0].sync.available,false);
 d.close();
});
test('Watchalong APIs expose minimal derived metadata only and are feature-gated',async()=>{
 const d=db();
 const id='watch:'+'a'.repeat(20);
 d.raw.prepare("INSERT INTO public_watchalong_events VALUES(?,?,?,?,?,?,?,?,?,?,?)").run(id,'M.1','Hololive live list','https://www.ptt.cc/bbs/C_Chat/M.1.A.html','2026-10-15T10:00:00+08:00','2026-10-15','20:00','同時視聴 movie',0,'2026-10-15T12:00:00Z','ptt_watchalong_parser');
 d.raw.prepare('INSERT INTO public_watchalong_streams VALUES(?,?,?,?)').run(id,0,'Host A','aaaaaaaaaaa');
 let r=await handleExperienceRead(new Request('https://api.example/v1/watchalong/recent'),{DB:d},new Date('2026-10-15T12:00:00Z'));
 assert.equal(r.status,503);
 r=await handleExperienceRead(new Request('https://api.example/v1/watchalong/recent'),{DB:d,WATCHALONG_EVENTS_ENABLED:'true'},new Date('2026-10-15T12:00:00Z'));
 assert.equal(r.status,200);
 const body=await r.json();
 assert.equal(body.events.length,1);
 assert.deepEqual(body.events[0].hosts,[{label:'Host A',video_id:'aaaaaaaaaaa'}]);
 assert.equal(body.events[0].source_mapping,null);
 assert.deepEqual(body.events[0].capabilities,{source_mapping:false,translation:false,telemetry:false});
 assert.equal('body_text' in body.events[0],false);
 d.close();
});
test('experience routes reject invalid day/event ids and remain GET-only',async()=>{
 const d=db(),env={DB:d,WATCHALONG_EVENTS_ENABLED:'true'};
 assert.equal((await handleExperienceRead(new Request('https://api.example/v1/collab/history?day=bad'),env)).status,400);
 assert.equal((await handleExperienceRead(new Request('https://api.example/v1/watchalong/events/not-safe'),env)).status,400);
 assert.equal((await handleExperienceRead(new Request('https://api.example/v1/collab/live',{method:'POST'}),env)).status,405);
 d.close();
});

test('Watchalong recent uses limit+1 and reports has_more without over-returning',async()=>{
 const d=db(),id1='watch:'+'a'.repeat(20),id2='watch:'+'b'.repeat(20);
 for(const [id,day,stamp,vid] of [[id1,'2026-10-15','2026-10-15T10:00:00+08:00','aaaaaaaaaaa'],[id2,'2026-10-14','2026-10-14T10:00:00+08:00','bbbbbbbbbbb']]){
  d.raw.prepare("INSERT INTO public_watchalong_events VALUES(?,?,?,?,?,?,?,?,?,?,?)").run(id,'M.1','title','https://www.ptt.cc/bbs/C_Chat/M.1.A.html',stamp,day,'20:00','同時視聴',0,'2026-10-15T12:00:00Z','ptt_watchalong_parser');
  d.raw.prepare('INSERT INTO public_watchalong_streams VALUES(?,?,?,?)').run(id,0,'Host',vid);
 }
 const r=await handleExperienceRead(new Request('https://api.example/v1/watchalong/recent?days=30&limit=1'),{DB:d,WATCHALONG_EVENTS_ENABLED:'true'},new Date('2026-10-15T12:00:00Z'));
 const body=await r.json();
 assert.equal(body.limit,1);
 assert.equal(body.has_more,true);
 assert.equal(body.events.length,1);
 d.close();
});
