import {readFileSync} from 'node:fs';
import {validateSupportColorExport} from './support-colors.mjs';

const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;

export function verifyLegacy66Handoff(rosterPayload,colorPayload){
  if(!rosterPayload||rosterPayload.schema!=='holoviewer-channel-roster-starter-v1'||!Array.isArray(rosterPayload.channels))
    throw Error('invalid legacy66 roster');
  const rosterIds=rosterPayload.channels.map(x=>x?.channel_id);
  if(rosterIds.length!==66||new Set(rosterIds).size!==66||rosterIds.some(x=>!CHANNEL.test(x??'')))
    throw Error('legacy66 roster identity mismatch');

  const rawRows=colorPayload?.channels;
  if(!Array.isArray(rawRows))throw Error('invalid color export rows');
  const seen=new Map();
  for(const row of rawRows){
    const id=row?.channel_id;
    if(!CHANNEL.test(id??''))throw Error('invalid support channel id');
    if(seen.has(id))throw Error('duplicate support channel id');
    seen.set(id,row);
  }

  const validated=validateSupportColorExport(colorPayload);
  const missing=rosterIds.filter(id=>!seen.has(id));
  const extra=[...seen.keys()].filter(id=>!rosterIds.includes(id));
  const colored=rosterIds.filter(id=>validated.has(id));
  const neutral=rosterIds.filter(id=>seen.has(id)&&!validated.has(id));
  const dual=colored.filter(id=>validated.get(id)?.support_mode==='dual_color');

  if(missing.length)throw Error('legacy66 color export missing channel rows: '+missing.join(','));
  return {
    roster_count:rosterIds.length,
    export_rows:rawRows.length,
    colored_count:colored.length,
    neutral_count:neutral.length,
    dual_color_count:dual.length,
    extra_channel_ids:extra,
    colored_channel_ids:colored,
    neutral_channel_ids:neutral,
    schema_version:colorPayload.schema_version,
    fallback:colorPayload.fallback,
    status:'PASS'
  };
}

if(import.meta.url===new URL(process.argv[1], 'file://').href){
  const [rosterPath,colorPath]=process.argv.slice(2);
  if(!rosterPath||!colorPath){
    console.error('usage: node verify-support-color-handoff.mjs <legacy66.json> <holoviewer-channel-support-colors.json>');
    process.exit(2);
  }
  const roster=JSON.parse(readFileSync(rosterPath,'utf8'));
  const colors=JSON.parse(readFileSync(colorPath,'utf8'));
  console.log(JSON.stringify(verifyLegacy66Handoff(roster,colors),null,2));
}
