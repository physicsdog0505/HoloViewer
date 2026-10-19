#!/usr/bin/env node
/**
 * Issue #47 one-shot 2026-10-18 Stream Catalog recovery importer.
 *
 * Default: dry-run only, zero production writes.
 * --apply is intentionally explicit and should only be used after #45 review.
 *
 * Today writes go through existing writeEvidence(...,{projectHistory:false}).
 * No WebSub events are fabricated. History candidates remain review-only.
 */
import {readFileSync,writeFileSync,unlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {validateEvidence,writeEvidence,YOUTUBE_LIVE_SOURCE} from './worker_host/today/store.mjs';

export const TARGET_DAY='2026-10-18';
export const DB_NAME='holoviewer-public-v1';
export const DB_ID='64e1a0ee-1455-4377-9640-3922e8f4d061';
const GROUPS=new Set(['hololive','holostars','mekpark','other']);
const STATES=new Set(['unknown','upcoming','live','ended']);

function sqlLiteral(v){
 if(v===null||v===undefined)return 'NULL';
 if(typeof v==='number'&&Number.isFinite(v))return String(v);
 if(typeof v==='boolean')return v?'1':'0';
 return "'"+String(v).replaceAll("'","''")+"'";
}
export function renderSql(sql,params=[]){
 const parts=String(sql).split('?');
 if(parts.length-1!==params.length)throw Error('SQL bind count mismatch');
 let out=parts[0];
 for(let i=0;i<params.length;i++)out+=sqlLiteral(params[i])+parts[i+1];
 return out;
}
function parseWranglerJson(raw){
 const text=String(raw);
 const start=text.indexOf('[');
 if(start<0)throw Error('Wrangler JSON payload not found');
 return JSON.parse(text.slice(start));
}
class BoundStatement{
 constructor(adapter,sql,params=[]){this.adapter=adapter;this.sql=sql;this.params=params;}
 bind(...params){return new BoundStatement(this.adapter,this.sql,params);}
 _render(){return renderSql(this.sql,this.params);}
 async first(){
   const rows=this.adapter.query(this._render());
   return rows[0]??null;
 }
 async all(){return {results:this.adapter.query(this._render())};}
 async run(){
   if(!this.adapter.apply)throw Error('production mutation disabled');
   this.adapter.execute(this._render());
   return {success:true};
 }
}
export class WranglerD1Adapter{
 constructor({config,apply=false,execImpl=execFileSync}={}){
  if(!config)throw Error('wrangler config required');
  this.config=config;this.apply=apply;this.execImpl=execImpl;this.writeCount=0;
 }
 prepare(sql){return new BoundStatement(this,sql);}
 _args(commandArgs){return ['wrangler','d1','execute',DB_NAME,'--remote','--config',this.config,...commandArgs];}
 query(sql){
   const raw=this.execImpl('npx',this._args(['--command',sql,'--json']),{encoding:'utf8'});
   const body=parseWranglerJson(raw),rows=[];
   for(const part of Array.isArray(body)?body:[body]) if(part&&typeof part==='object')
     rows.push(...(part.results??part.result??[]));
   return rows;
 }
 execute(sql){
   if(!this.apply)throw Error('production mutation disabled');
   this.execImpl('npx',this._args(['--command',sql]),{encoding:'utf8'});
   this.writeCount++;
 }
 async batch(statements){
   if(!this.apply)throw Error('production mutation disabled');
   const path=join(tmpdir(),`hv47-recovery-${process.pid}-${Date.now()}.sql`);
   const sql=statements.map(s=>s._render()).join('\n')+'\n';
   writeFileSync(path,sql,'utf8');
   try{
    this.execImpl('npx',this._args(['--file',path]),{encoding:'utf8'});
    this.writeCount+=statements.length;
   }finally{try{unlinkSync(path)}catch{}}
   return statements.map(()=>({success:true}));
 }
}

export function normalizeRecoveryEvidence(row){
 if(!row||row.today_import_candidate!==true)throw Error('row is not approved Today import candidate');
 const state=STATES.has(row.lifecycle_state)?row.lifecycle_state:'unknown';
 const evidence={
  video_id:String(row.video_id??''),
  channel_id:String(row.channel_id??''),
  roster_version:String(row.roster_version??''),
  group:GROUPS.has(row.group)?row.group:'other',
  title:String(row.title??''),
  channel_name:String(row.channel_name??''),
  lifecycle_state:state,
  observed_at:row.projection_observed_at??null,
  scheduled_start:row.scheduled_start??null,
  actual_start:row.actual_start??null,
  actual_end:row.actual_end??null,
  // Stream Catalog selected these exact YouTube liveStreamingDetails bounds.
  // Recovery transport is recorded in the artifact, not disguised as WebSub.
  source_label:YOUTUBE_LIVE_SOURCE,
 };
 return validateEvidence(evidence);
}
export function recoveryPlan(artifact){
 if(!artifact||artifact.schema_version!=='stream-catalog-recovery-inventory-v1')throw Error('invalid recovery artifact');
 if(artifact.target_day_taipei!==TARGET_DAY)throw Error('wrong recovery day');
 const rows=Array.isArray(artifact.rows)?artifact.rows:[];
 const candidates=[],historyCandidates=[];
 for(const row of rows){
  if(row.today_import_candidate===true)candidates.push(normalizeRecoveryEvidence(row));
  if(row.history_missing_candidate===true)historyCandidates.push({
    video_id:row.video_id,channel_id:row.channel_id,title:row.title,
    scheduled_start:row.scheduled_start??null,actual_start:row.actual_start,
    actual_end:row.actual_end,projection_observed_at:row.projection_observed_at,
  });
 }
 return {
  schema_version:'stream-catalog-recovery-plan-v1',
  target_day_taipei:TARGET_DAY,
  recovery_source:artifact.recovery_source,
  today_candidates:candidates,
  history_missing_candidates:historyCandidates,
 };
}
export async function applyRecoveryPlan(db,plan,{dryRun=true}={}){
 if(!plan||plan.schema_version!=='stream-catalog-recovery-plan-v1')throw Error('invalid recovery plan');
 if(dryRun)return {dry_run:true,writes:0,candidates:plan.today_candidates.length,results:[]};
 const results=[];
 for(const evidence of plan.today_candidates){
  const out=await writeEvidence(db,evidence,{projectHistory:false});
  results.push({video_id:evidence.video_id,...out});
 }
 return {
  dry_run:false,
  candidates:plan.today_candidates.length,
  changed:results.filter(x=>x.changed).length,
  replay:results.filter(x=>x.reason==='replay').length,
  evidence_only:results.filter(x=>x.reason==='evidence_only').length,
  results,
 };
}

function arg(name,args){
 const i=args.indexOf(name);return i>=0?args[i+1]:null;
}
async function main(){
 const args=process.argv.slice(2);
 const artifactPath=arg('--artifact',args);
 const config=arg('--config',args);
 const apply=args.includes('--apply');
 const planOut=arg('--plan-out',args)||'/tmp/hv47-recovery-20261018-plan.json';
 if(!artifactPath)throw Error('--artifact required');
 const artifact=JSON.parse(readFileSync(artifactPath,'utf8'));
 const plan=recoveryPlan(artifact);
 writeFileSync(planOut,JSON.stringify(plan,null,2)+'\n','utf8');
 if(!apply){
  console.log(JSON.stringify({status:'DRY_RUN',today_candidates:plan.today_candidates.length,
    history_missing_candidates:plan.history_missing_candidates.length,writes:0,plan:planOut},null,2));
  return;
 }
 if(!config)throw Error('--config required with --apply');
 const db=new WranglerD1Adapter({config,apply:true});
 const result=await applyRecoveryPlan(db,plan,{dryRun:false});
 console.log(JSON.stringify({...result,adapter_writes:db.writeCount,history_written:false},null,2));
}
if(import.meta.url===`file://${process.argv[1]}`)main().catch(e=>{console.error(e);process.exit(1)});
