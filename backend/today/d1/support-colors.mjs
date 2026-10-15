/** Exact 4174 #338 export contract. Never infer colors from channel names or thumbnails.
 * The runtime must supply the 8501 pinned producer's validated export.
 */
const ID=/^UC[A-Za-z0-9_-]{22}$/;
const HEX=/^#[0-9A-Fa-f]{6}$/;
export function validateSupportColorExport(payload){
 if(!payload||payload.schema_version!==1||payload.fallback!=='neutral'||!Array.isArray(payload.channels))
  throw Error('unsupported 4174 support color export');
 const output=new Map();
 for(const row of payload.channels){
  const id=row?.channel_id;
  if(!ID.test(id??'')||output.has(id))throw Error('invalid/duplicate support channel');
  const community=row.verification_status==='community'&&row.color_semantics==='2025_6th_fes_penlight';
  const verified=row.verification_status==='verified';
  if(row.display_mode==='dual_color'&&community&&Array.isArray(row.color_hexes)&&row.color_hexes.length===2&&row.color_hexes.every(v=>HEX.test(v))){
   output.set(id,{member_accent:row.color_hexes[0].toUpperCase(),member_accent_dual:row.color_hexes.map(v=>v.toUpperCase()),support_mode:'dual_color',support_color_source:'2025_6th_fes_penlight'});
  }else if(row.display_mode==='solid'&&(verified||community)&&HEX.test(row.color_hex??'')){
   output.set(id,{member_accent:row.color_hex.toUpperCase(),member_accent_dual:null,support_mode:'solid',support_color_source:verified?'verified':'2025_6th_fes_penlight'});
  }
 }
 return output;
}
export function supportColorFor(channelId,colors){
 return colors?.get(channelId)??{member_accent:null,member_accent_dual:null,support_mode:'neutral',support_color_source:null};
}
