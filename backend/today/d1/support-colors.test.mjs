import test from 'node:test';import assert from 'node:assert/strict';import {validateSupportColorExport,supportColorFor} from './support-colors.mjs';
const a='UC'+'A'.repeat(22),b='UC'+'B'.repeat(22);
test('exact 4174 verified solid and 2025 community dual retain immutable hex',()=>{
 const colors=validateSupportColorExport({schema_version:1,fallback:'neutral',channels:[
 {channel_id:a,display_mode:'solid',verification_status:'verified',color_hex:'#aa22bb'},
 {channel_id:b,display_mode:'dual_color',verification_status:'community',color_semantics:'2025_6th_fes_penlight',color_hexes:['#123456','#abcdef']}]});
 assert.deepEqual(supportColorFor(a,colors),{member_accent:'#AA22BB',member_accent_dual:null,support_mode:'solid',support_color_source:'verified'});
 assert.deepEqual(supportColorFor(b,colors).member_accent_dual,['#123456','#ABCDEF']);
 assert.equal(supportColorFor('UC'+'C'.repeat(22),colors).member_accent,null);
});
test('reject forged duplicate identities; invalid unverified data never overrides fallback',()=>{
 assert.throws(()=>validateSupportColorExport({schema_version:1,fallback:'neutral',channels:[{channel_id:a},{channel_id:a}]}),/duplicate/);
 const v=validateSupportColorExport({schema_version:1,fallback:'neutral',channels:[{channel_id:a,display_mode:'solid',verification_status:'community',color_hex:'#FFFFFF',color_semantics:'unknown'}]});
 assert.equal(supportColorFor(a,v).member_accent,null);
});
