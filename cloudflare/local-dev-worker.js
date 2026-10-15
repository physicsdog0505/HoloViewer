const API_ORIGIN='https://holoviewer-public-api.singlebagel.workers.dev';

export default {
 async fetch(request, env) {
  const url=new URL(request.url);
  if(url.pathname.startsWith('/__api/')){
   const target=new URL(url.pathname.slice('/__api'.length)+url.search,API_ORIGIN);
   const headers=new Headers();
   headers.set('Accept',request.headers.get('Accept')||'application/json');
   const upstream=await fetch(target.toString(),{
    method:request.method,
    headers,
    redirect:'follow'
   });
   const response=new Response(upstream.body,upstream);
   response.headers.set('Cache-Control','no-store');
   return response;
  }
  return env.ASSETS.fetch(request);
 }
};
