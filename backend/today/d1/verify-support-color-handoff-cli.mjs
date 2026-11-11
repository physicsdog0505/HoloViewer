import {readFileSync} from 'node:fs';
import {verifyLegacy66Handoff} from './verify-support-color-handoff.mjs';

const [rosterPath,colorPath]=process.argv.slice(2);
if(!rosterPath||!colorPath){
  console.error('usage: node verify-support-color-handoff-cli.mjs <legacy66.json> <holoviewer-channel-support-colors.json>');
  process.exit(2);
}
try{
  const roster=JSON.parse(readFileSync(rosterPath,'utf8'));
  const colors=JSON.parse(readFileSync(colorPath,'utf8'));
  console.log(JSON.stringify(verifyLegacy66Handoff(roster,colors),null,2));
}catch(error){
  console.error('VERIFY_FAILED:',error?.message??String(error));
  process.exit(1);
}
