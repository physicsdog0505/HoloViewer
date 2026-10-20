import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';

import {readChannelProfile,neutralChannelProfile} from './worker_host/today/channel-profile.mjs';
import {upsertChannelProfiles} from './worker_host/today/channel-profile-write.mjs';
import {handleChannelProfileRead} from './worker_host/today/channel-profile-read.mjs';
import {handleVideoMetadataRead} from './worker_host/today/video-metadata-read.mjs';
import {handleExperienceRead} from './worker_host/today/experience-read.mjs';

const CHANNEL='UC'+'A'.repeat(22);
const VIDEO='abcdefghijk';
const EVENT='watch:'+'a'.repeat(20);

function sqliteD1(){
 const sqlite=new DatabaseSync(':memory:');
 sqlite.exec(readFileSync(new URL('./worker_host/today/0002_today_canonical.sql',import.meta.url),'utf8'));
 sqlite.exec(readFileSync(new URL('./worker_host/today/0004_video_metadata_cache.sql',import.meta.url),'utf8'));
 sqlite.exec(readFileSync(new URL('./worker_host/today/0005_channel_profiles.sql',import.meta.url),'utf8'));
 sqlite.exec(readFileSync(new URL('./worker_host/today/watchalong-read.sql',import.meta.url),'utf8'));
 sqlite.exec("CREATE TABLE public_history(video_id TEXT PRIMARY KEY,taipei_day TEXT,title TEXT,channel_id TEXT,channel_name TEXT,avatar_url TEXT,scheduled_start TEXT,actual_start TEXT,actual_end TEXT,source_revision TEXT,published_at TEXT);");
 sqlite.exec("CREATE TABLE public_catalog(video_id TEXT PRIMARY KEY,title TEXT,channel_id TEXT,channel_name TEXT,avatar_url TEXT,lifecycle_state TEXT,scheduled_start TEXT,actual_start TEXT,actual_end TEXT);");
 sqlite.exec("CREATE TABLE ptt_threads(day TEXT NOT NULL,aid TEXT NOT NULL,source_url TEXT,verified_at TEXT,PRIMARY KEY(day,aid));");
 function stmt(sql,params=[]){return {
  bind(...values){return stmt(sql,values)},
  async first(){return sqlite.prepare(sql).get(...params)??null},
  async all(){return {results:sqlite.prepare(sql).all(...params)}},
  async run(){return sqlite.prepare(sql).run(...params)}
 }}
 return {
  raw:sqlite,
  prepare(sql){return stmt(sql)},
  async batch(statements){
   sqlite.exec('BEGIN IMMEDIATE');
   try{const out=[];for(const s of statements)out.push(await s.run());sqlite.exec('COMMIT');return out}
   catch(e){sqlite.exec('ROLLBACK');throw e}
  },
  close(){sqlite.close()}
 };
}

function profile(){
 return {
  channel_id:CHANNEL,
  channel_name:'Canonical Channel',
  display_name:'Canonical Member',
  avatar_url:'https://yt3.ggpht.com/avatar',
  group:'hololive',
  member_accent:'#123456',
  member_accent_dual:null,
  support_mode:'solid',
  support_color_source:'verified',
  profile_revision:'profile-r1',
  updated_at:'2026-10-20T12:00:00Z'
 };
}

test('canonical profile round-trips through one shared projection',async()=>{
 const db=sqliteD1();
 await upsertChannelProfiles(db,[profile()]);
 const out=await readChannelProfile(db,CHANNEL);
 assert.equal(out.channel_id,CHANNEL);
 assert.equal(out.channel_name,'Canonical Channel');
 assert.equal(out.display_name,'Canonical Member');
 assert.equal(out.avatar_url,'https://yt3.ggpht.com/avatar');
 assert.equal(out.group,'hololive');
 assert.equal(out.member_accent,'#123456');
 assert.equal(out.support_mode,'solid');
 assert.equal(out.profile_revision,'profile-r1');
 db.close();
});

test('unknown channel is explicit null/neutral, never guessed from label',async()=>{
 const db=sqliteD1();
 const unknown='UC'+'Z'.repeat(22);
 const out=await readChannelProfile(db,unknown);
 assert.deepEqual(out,neutralChannelProfile(unknown));
 db.close();
});

test('profile API is keyed only by channel_id',async()=>{
 const db=sqliteD1();
 await upsertChannelProfiles(db,[profile()]);
 const req=new Request('https://api.example/v1/channels/'+CHANNEL+'/profile');
 const res=await handleChannelProfileRead(req,{DB:db});
 const body=await res.json();
 assert.equal(res.status,200);
 assert.equal(body.schema_version,'holoviewer-channel-profile-v1');
 assert.equal(body.profile.channel_id,CHANNEL);
 assert.equal(body.profile.display_name,'Canonical Member');
 db.close();
});

test('video metadata includes the canonical nested channel profile',async()=>{
 const db=sqliteD1();
 await upsertChannelProfiles(db,[profile()]);
 db.raw.prepare("INSERT INTO public_today_catalog_meta(singleton,roster_version,last_success_at,expected_channels,scanned_channels,gap,checkpoint) VALUES(1,'r1','2026-10-20T12:00:00Z',1,1,0,NULL)").run();
 db.raw.prepare("INSERT INTO public_today_approved_channels(channel_id,roster_version,activated_at,channel_group) VALUES(?,?,?,?)")
  .run(CHANNEL,'r1','2026-10-20T12:00:00Z','hololive');
 db.raw.prepare("INSERT INTO public_today_canonical(video_id,publisher_channel_id,roster_version,channel_group,title,channel_name,lifecycle_state,lifecycle_observed_at,checked_at,scheduled_start,actual_start,actual_end,source_label,source_checksum) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
  .run(VIDEO,CHANNEL,'r1','hololive','Video','Old Name','ended','2026-10-20T12:00:00Z','2026-10-20T12:00:00Z','2026-10-20T10:00:00Z','2026-10-20T10:00:05Z','2026-10-20T11:00:00Z','YouTube liveStreamingDetails','x');
 const res=await handleVideoMetadataRead(new Request('https://api.example/v1/videos/'+VIDEO+'/metadata'),{DB:db});
 const body=await res.json();
 assert.equal(res.status,200);
 assert.equal(body.channel_id,CHANNEL);
 assert.equal(body.channel.channel_id,CHANNEL);
 assert.equal(body.channel.display_name,'Canonical Member');
 assert.equal(body.avatar_url,'https://yt3.ggpht.com/avatar');
 db.close();
});

test('Watchalong host resolves channel_id from video identity and attaches same profile',async()=>{
 const db=sqliteD1();
 await upsertChannelProfiles(db,[profile()]);
 db.raw.prepare("INSERT INTO public_history(video_id,taipei_day,title,channel_id,channel_name,avatar_url,scheduled_start,actual_start,actual_end,source_revision,published_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
  .run(VIDEO,'2026-10-20','VOD',CHANNEL,'Old Name','','2026-10-20T10:00:00Z','2026-10-20T10:00:05Z','2026-10-20T11:00:00Z','youtube-videos-list:liveStreamingDetails','2026-10-20T12:00:00Z');
 db.raw.prepare("INSERT INTO public_watchalong_events(event_id,aid,article_title,source_url,article_datetime,day,scheduled_time,description,member_only,imported_at,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
  .run(EVENT,'#a','Article','https://example.invalid','2026-10-20T12:00:00Z','2026-10-20','20:00','Watchalong',0,'2026-10-20T12:00:00Z','ptt_watchalong_parser');
 db.raw.prepare("INSERT INTO public_watchalong_streams(event_id,ordinal,label,video_id) VALUES(?,?,?,?)")
  .run(EVENT,0,'This label is not identity',VIDEO);
 const res=await handleExperienceRead(new Request('https://api.example/v1/watchalong/events/'+EVENT),{DB:db,WATCHALONG_EVENTS_ENABLED:'true'});
 const body=await res.json();
 assert.equal(res.status,200);
 assert.equal(body.event.hosts[0].label,'This label is not identity');
 assert.equal(body.event.hosts[0].channel_id,CHANNEL);
 assert.equal(body.event.hosts[0].channel.channel_id,CHANNEL);
 assert.equal(body.event.hosts[0].channel.display_name,'Canonical Member');
 db.close();
});

test('legacy migration data resolves identically across direct profile, Today, History, metadata, Collab and Watchalong',async()=>{
 const db=sqliteD1();
 db.raw.prepare("INSERT INTO public_catalog(video_id,title,channel_id,channel_name,avatar_url,lifecycle_state,scheduled_start,actual_start,actual_end) VALUES(?,?,?,?,?,?,?,?,?)")
  .run(VIDEO,'Legacy',CHANNEL,'Legacy Channel','https://yt3.ggpht.com/legacy-avatar','ended','2026-10-20T10:00:00Z','2026-10-20T10:00:05Z','2026-10-20T11:00:00Z');
 db.raw.prepare("INSERT INTO public_today_catalog_meta(singleton,roster_version,last_success_at,expected_channels,scanned_channels,gap,checkpoint) VALUES(1,'r1','2026-10-20T12:00:00Z',1,1,0,NULL)").run();
 db.raw.prepare("INSERT INTO public_today_approved_channels(channel_id,roster_version,activated_at,channel_group) VALUES(?,?,?,?)")
  .run(CHANNEL,'r1','2026-10-20T12:00:00Z','hololive');
 db.raw.prepare("INSERT INTO public_today_canonical(video_id,publisher_channel_id,roster_version,channel_group,title,channel_name,lifecycle_state,lifecycle_observed_at,checked_at,scheduled_start,actual_start,actual_end,source_label,source_checksum) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
  .run(VIDEO,CHANNEL,'r1','hololive','Video','Today Name','ended','2026-10-20T12:00:00Z','2026-10-20T12:00:00Z','2026-10-20T10:00:00Z','2026-10-20T10:00:05Z','2026-10-20T11:00:00Z','YouTube liveStreamingDetails','x');
 db.raw.prepare("INSERT INTO public_history(video_id,taipei_day,title,channel_id,channel_name,avatar_url,scheduled_start,actual_start,actual_end,source_revision,published_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
  .run(VIDEO,'2026-10-20','VOD',CHANNEL,'History Name','','2026-10-20T10:00:00Z','2026-10-20T10:00:05Z','2026-10-20T11:00:00Z','youtube-videos-list:liveStreamingDetails','2026-10-20T12:00:00Z');
 db.raw.prepare("INSERT INTO public_watchalong_events(event_id,aid,article_title,source_url,article_datetime,day,scheduled_time,description,member_only,imported_at,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
  .run(EVENT,'#a','Article','https://example.invalid','2026-10-20T12:00:00Z','2026-10-20','20:00','Watchalong',0,'2026-10-20T12:00:00Z','ptt_watchalong_parser');
 db.raw.prepare("INSERT INTO public_watchalong_streams(event_id,ordinal,label,video_id) VALUES(?,?,?,?)").run(EVENT,0,'Any label',VIDEO);

 const direct=(await (await handleChannelProfileRead(new Request('https://api.example/v1/channels/'+CHANNEL+'/profile'),{DB:db})).json()).profile;
 const metadata=await (await handleVideoMetadataRead(new Request('https://api.example/v1/videos/'+VIDEO+'/metadata'),{DB:db})).json();
 const watch=await (await handleExperienceRead(new Request('https://api.example/v1/watchalong/events/'+EVENT),{DB:db,WATCHALONG_EVENTS_ENABLED:'true'})).json();
 const collab=await (await handleExperienceRead(new Request('https://api.example/v1/collab/history?day=2026-10-20'),{DB:db})).json();
 const {readToday}=await import('./worker_host/today/store.mjs');
 const {legacyHistory}=await import('./worker_host/today/legacy-compat.mjs');
 const today=(await readToday(db,{day:'2026-10-20',now:new Date('2026-10-20T12:00:00Z')})).streams[0].channel;
 const history=(await (await legacyHistory(new Request('https://api.example/v1/history?day=2026-10-20'),{DB:db})).json()).items[0].channel;

 for(const candidate of [today,history,metadata.channel,watch.event.hosts[0].channel]){
  assert.equal(candidate.avatar_url,direct.avatar_url);
  assert.equal(candidate.group,direct.group);
  assert.equal(candidate.channel_name,direct.channel_name);
  assert.equal(candidate.support_mode,direct.support_mode);
  assert.deepEqual(candidate.member_accent_dual,direct.member_accent_dual);
 }
 assert.equal(direct.avatar_url,'https://yt3.ggpht.com/legacy-avatar');
 assert.equal(direct.group,'hololive');
 assert.equal(Array.isArray(collab.events),true);
 db.close();
});

test('canonical row overrides transitional legacy sources everywhere',async()=>{
 const db=sqliteD1();
 db.raw.prepare("INSERT INTO public_catalog(video_id,title,channel_id,channel_name,avatar_url,lifecycle_state,scheduled_start,actual_start,actual_end) VALUES(?,?,?,?,?,?,?,?,?)")
  .run(VIDEO,'Legacy',CHANNEL,'Legacy Channel','https://yt3.ggpht.com/legacy-avatar','ended',null,null,null);
 db.raw.prepare("INSERT INTO public_today_approved_channels(channel_id,roster_version,activated_at,channel_group) VALUES(?,?,?,?)")
  .run(CHANNEL,'r1','2026-10-20T12:00:00Z','other');
 await upsertChannelProfiles(db,[profile()]);
 const direct=await readChannelProfile(db,CHANNEL);
 assert.equal(direct.avatar_url,'https://yt3.ggpht.com/avatar');
 assert.equal(direct.group,'hololive');
 assert.equal(direct.channel_name,'Canonical Channel');
 db.close();
});

test('equal timestamp different canonical profile revision fails closed and identical replay is idempotent',async()=>{
 const db=sqliteD1();
 const first=profile();
 assert.equal((await upsertChannelProfiles(db,[first])).profiles_written,1);
 assert.equal((await upsertChannelProfiles(db,[first])).profiles_written,0);
 await assert.rejects(
  ()=>upsertChannelProfiles(db,[{...first,display_name:'Different',profile_revision:'profile-r2'}]),
  /same-timestamp profile conflict/
 );
 const stored=await readChannelProfile(db,CHANNEL);
 assert.equal(stored.display_name,'Canonical Member');
 assert.equal(stored.profile_revision,'profile-r1');
 db.close();
});

test('Watchalong unknown video keeps channel_id null and neutral profile instead of label inference',async()=>{
 const db=sqliteD1();
 db.raw.prepare("INSERT INTO public_watchalong_events(event_id,aid,article_title,source_url,article_datetime,day,scheduled_time,description,member_only,imported_at,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
  .run(EVENT,'#a','Article','https://example.invalid','2026-10-20T12:00:00Z','2026-10-20','20:00','Watchalong',0,'2026-10-20T12:00:00Z','ptt_watchalong_parser');
 db.raw.prepare("INSERT INTO public_watchalong_streams(event_id,ordinal,label,video_id) VALUES(?,?,?,?)")
  .run(EVENT,0,'兎田ぺこら',VIDEO);
 const res=await handleExperienceRead(new Request('https://api.example/v1/watchalong/events/'+EVENT),{DB:db,WATCHALONG_EVENTS_ENABLED:'true'});
 const body=await res.json();
 assert.equal(res.status,200);
 assert.equal(body.event.hosts[0].channel_id,null);
 assert.equal(body.event.hosts[0].channel.support_mode,'neutral');
 assert.equal(body.event.hosts[0].channel.avatar_url,null);
 db.close();
});
