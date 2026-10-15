/**
 * #47 GET-only route bridge for the existing holoviewer-public-api Worker.
 * Its owner may call handleTodayRead(request, env) from the existing route table.
 * No Worker creation, deploy, migration, provider API calls or implicit side effects.
 */
import {readToday} from './store.mjs';
const MAX_BODY = 262144;
function json(body,status=200,headers={}) {
  return new Response(JSON.stringify(body),{status,headers:{
    'content-type':'application/json; charset=utf-8',
    'cache-control':'public, max-age=30',
    'x-content-type-options':'nosniff',
    ...headers
  }});
}
export async function handleTodayRead(request,env,now=new Date()) {
  if (!request || request.method!=='GET') return json({error:'method_not_allowed'},405,{allow:'GET'});
  if (!env?.DB || typeof env.DB.prepare!=='function') return json({error:'service_unavailable'},503);
  let url;
  try {url=new URL(request.url);} catch {return json({error:'bad_request'},400);}
  if (url.pathname!=='/v1/catalog/today') return json({error:'not_found'},404);
  const taipeiDay=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
  const day=url.searchParams.get('day')??taipeiDay;
  const rawLimit=url.searchParams.get('limit')??'200';
  if (!/^[1-9][0-9]{0,2}$/.test(rawLimit) || Number(rawLimit)>200) return json({error:'bad_limit'},400);
  try {
    const result=await readToday(env.DB,{day,limit:Number(rawLimit),now});
    const serialized=JSON.stringify(result);
    if (new TextEncoder().encode(serialized).length>MAX_BODY) return json({error:'response_limit'},503);
    return new Response(serialized,{status:200,headers:{
      'content-type':'application/json; charset=utf-8',
      'cache-control':'public, max-age=30',
      'x-content-type-options':'nosniff'
    }});
  } catch (error) {
    if (/invalid (canonical Today day|limit)/.test(String(error?.message??''))) return json({error:'invalid_request'},400);
    return json({error:'temporarily_unavailable'},503);
  }
}
