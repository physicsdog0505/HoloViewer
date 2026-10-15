/** Legacy compatibility only: historical public_history/public_catalog tables. */
const videoId=/^[A-Za-z0-9_-]{11}$/;
function response(data,status=200,age=30){return new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'public, max-age='+age}});}
export async function legacyHistory(request,env){
 const p=new URL(request.url).searchParams,day=p.get('day')??'';
 const rawLimit=p.get('limit')??'50',rawOffset=p.get('offset')??'0';
 if(!/^\d{4}-\d{2}-\d{2}$/.test(day)||!Number.isFinite(Date.parse(day+'T00:00:00Z'))||
    !/^\d+$/.test(rawLimit)||Number(rawLimit)<1||Number(rawLimit)>50||
    !/^\d+$/.test(rawOffset)||Number(rawOffset)>1000000)
   return response({error:'invalid_history_query'},400,0);
 const limit=Number(rawLimit),offset=Number(rawOffset);
 const count=await env.DB.prepare('SELECT COUNT(*) AS total FROM public_history WHERE day=?').bind(day).first();
 const rows=await env.DB.prepare('SELECT * FROM public_history WHERE day=? ORDER BY id LIMIT ? OFFSET ?').bind(day,limit,offset).all();
 return response({day,total:count?.total??0,limit,offset,items:rows.results??[]});
}
export async function legacyVideo(request,env){
 const id=decodeURIComponent(new URL(request.url).pathname.split('/').at(-1)??'');
 if(!videoId.test(id))return response({error:'invalid_video_id'},400,0);
 const video=await env.DB.prepare('SELECT * FROM public_catalog WHERE video_id=?').bind(id).first();
 if(!video)return response({error:'not_found'},404,0);
 return response(video);
}
