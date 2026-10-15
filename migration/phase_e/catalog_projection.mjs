/* Read-only projection of confirmed Public Today/History consumer shapes.
 * This does not create records, infer lifecycle, or declare data complete.
 */
const ID_RE=/^[A-Za-z0-9_-]{11}$/;
export const LIVE_BUCKETS=Object.freeze(["live","upcoming","unknown","ended"]);

function streamsFrom(payload,kind){
 if(!payload || typeof payload!=="object" || Array.isArray(payload)) throw new TypeError("invalid API payload");
 const list=kind==="today" ? (payload.streams ?? payload.items) : payload.items;
 if(!Array.isArray(list)) throw new TypeError("missing stream list");
 return list.filter(item=>item && typeof item==="object" && ID_RE.test(item.video_id ?? ""));
}
export function todayProjection(payload){
 const rows=streamsFrom(payload,"today");
 const buckets={live:[],upcoming:[],unknown:[],ended:[]};
 for(const item of rows){
  const lifecycle=String(item.lifecycle_state ?? item.state ?? "unknown").toLowerCase();
  const bucket=lifecycle==="live"?"live":
   lifecycle==="upcoming"||lifecycle==="waiting"?"upcoming":
   lifecycle==="ended"?"ended":"unknown";
  buckets[bucket].push(item);
 }
 return {buckets,items:rows, freshness:payload.freshness ?? null,
   complete:payload.complete === true};
}
export function historyProjection(payload){
 const rows=streamsFrom(payload,"history");
 const total=Number.isInteger(payload.total) && payload.total>=0 ? payload.total : null;
 return {items:rows,total,hasMore:payload.has_more===true,
   freshness:payload.freshness ?? null,complete:payload.complete===true};
}
