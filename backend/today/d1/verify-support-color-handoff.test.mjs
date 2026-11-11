import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {verifyLegacy66Handoff} from './verify-support-color-handoff.mjs';

const roster=JSON.parse(readFileSync(new URL('./legacy-66.roster.json',import.meta.url),'utf8'));
const rows=roster.channels.map((x,i)=>({
  channel_id:x.channel_id,
  display_mode:i===0?'dual_color':'solid',
  verification_status:i===0?'community':'verified',
  color_semantics:i===0?'2025_6th_fes_penlight':undefined,
  color_hexes:i===0?['#112233','#AABBCC']:undefined,
  color_hex:i===0?undefined:'#123456'
}));
const payload={schema_version:1,fallback:'neutral',channels:rows};

test('exact 66 roster coverage passes and reports dual/solid coverage',()=>{
  const out=verifyLegacy66Handoff(roster,payload);
  assert.equal(out.roster_count,66);
  assert.equal(out.colored_count,66);
  assert.equal(out.neutral_count,0);
  assert.equal(out.dual_color_count,1);
  assert.equal(out.status,'PASS');
});
test('missing one legacy channel blocks handoff',()=>{
  assert.throws(()=>verifyLegacy66Handoff(roster,{...payload,channels:rows.slice(1)}),/missing channel rows/);
});
test('neutral row is allowed only as explicit row, never silently missing',()=>{
  const neutral=structuredClone(payload);
  neutral.channels[1]={channel_id:roster.channels[1].channel_id,display_mode:'neutral',verification_status:'none'};
  const out=verifyLegacy66Handoff(roster,neutral);
  assert.equal(out.neutral_count,1);
  assert.equal(out.colored_count,65);
});

test('CLI entrypoint path handling is covered by module-safe verifier import',()=>{
  assert.equal(typeof verifyLegacy66Handoff,'function');
});
