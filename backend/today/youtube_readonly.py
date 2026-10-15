"""Bounded real YouTube Data API reader; NEVER writes D1 or schedules recurring jobs.
Roster JSON: {"version":"owner-approved-id","channels":[{"id":"UC...","group":"hololive","uploads_playlist":"UU..."}]}.
This tool requires an explicitly supplied, reviewed roster; no prototype roster fallback.
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from .ingest import ApprovedRoster, ingest_batches

CHANNEL = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
PLAYLIST = re.compile(r"^UU[A-Za-z0-9_-]{22}$")
VIDEO = re.compile(r"^[A-Za-z0-9_-]{11}$")
BASE = "https://www.googleapis.com/youtube/v3/"

def approved_roster(document):
    if not isinstance(document, dict) or not isinstance(document.get("channels"), list):
        raise ValueError("explicit channel roster required")
    entries = document["channels"]
    if not 1 <= len(entries) <= 100 or len(entries) != len({e.get("id") for e in entries}):
        raise ValueError("roster must contain 1..100 unique channels")
    if any(not isinstance(e,dict) or not CHANNEL.fullmatch(e.get("id","")) or
           not PLAYLIST.fullmatch(e.get("uploads_playlist","")) or
           e["uploads_playlist"] != "UU"+e["id"][2:] for e in entries):
        raise ValueError("channel/uploads playlist identity mismatch")
    groups = {e["id"]:e["group"] for e in entries}
    return ApprovedRoster(document.get("version",""),frozenset(groups),groups),entries

def live_provider_sample(roster_document, api_key, *, request_json=None, observed_at=None,
                         max_channels=3, max_pages=1, max_videos=50, discover_broadcasts=False):
    """Real provider transport, fully injected for deterministic offline testing.
    Explicit conservative bounds; returns receipt and normalized records only, no mutation.
    """
    roster, entries=approved_roster(roster_document)
    if not 1<=max_channels<=3 or not 1<=max_pages<=2 or not 1<=max_videos<=50:
        raise ValueError("one-shot sample limits exceeded")
    if not isinstance(api_key,str) or not api_key:
        raise ValueError("YouTube key required")
    if len(entries)>max_channels:
        raise ValueError("roster exceeds authorized probe scope")
    if request_json is None:
        def request_json(endpoint, params):
            url=BASE+endpoint+"?"+urllib.parse.urlencode({**params,"key":api_key})
            request=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"HoloViewer-Today-ReadOnly/1"})
            with urllib.request.urlopen(request,timeout=15) as response:
                return json.load(response)
    observed=observed_at or datetime.now(timezone.utc)
    pages={}
    api_calls=0
    estimated_units=0
    for entry in entries:
        ident=entry["id"]
        token=None
        selected=[]
        for _ in range(max_pages):
            args={"part":"contentDetails","playlistId":entry["uploads_playlist"],"maxResults":max_videos}
            if token: args["pageToken"]=token
            data=request_json("playlistItems",args)
            api_calls+=1
            estimated_units+=1
            if not isinstance(data,dict) or not isinstance(data.get("items"),list):
                raise ValueError("malformed playlistItems")
            ids=[x.get("contentDetails",{}).get("videoId") for x in data["items"]]
            if any(not isinstance(v,str) or not VIDEO.fullmatch(v) for v in ids):
                raise ValueError("bad playlist video identity")
            selected.append(ids)
            token=data.get("nextPageToken")
            if not token:break
        if discover_broadcasts:
            # search.list is costly (100 quota units), but uploads playlists cannot
            # reliably enumerate upcoming/live announcements. Never infer completeness.
            for event_type in ('live','upcoming'):
                query=request_json('search',{'part':'id','channelId':ident,'eventType':event_type,
                                             'type':'video','maxResults':max_videos})
                api_calls+=1
                estimated_units+=100
                if not isinstance(query,dict) or not isinstance(query.get('items'),list):
                    raise ValueError('malformed search discovery response')
                extra=[item.get('id',{}).get('videoId') for item in query['items']]
                if any(not isinstance(v,str) or not VIDEO.fullmatch(v) for v in extra):
                    raise ValueError('bad search video identity')
                selected[-1].extend(extra)
        pages[ident]=selected
    # Explicit fixed candidates; do not let ingest_batches call more than one metadata batch.
    flat=list(dict.fromkeys(v for channel_pages in pages.values() for page in channel_pages for v in page))
    if len(flat)>50:raise ValueError("metadata batch exceeds one-shot limit")
    def metadata(ids):
        nonlocal api_calls,estimated_units
        answer=request_json("videos",{"part":"snippet,liveStreamingDetails,status","id":",".join(ids),"maxResults":50})
        api_calls+=1
        estimated_units+=1
        if not isinstance(answer,dict) or not isinstance(answer.get("items"),list):
            raise ValueError("malformed videos response")
        return {v["id"]:v for v in answer["items"] if isinstance(v,dict) and VIDEO.fullmatch(v.get("id",""))}
    result=ingest_batches(roster=roster,pages=pages,metadata=metadata,observed_at=observed,
                          reference_now=observed,max_pages_per_channel=max_pages)
    return {"mode":"PROVIDER_READ_ONLY","roster_version":roster.version,"observed_at":observed.isoformat(),
            "api_calls":api_calls,"estimated_quota_units":estimated_units,"channel_count":len(entries),"attempted":result.attempted,
            "gap":result.gap,"failures":result.failures,"needs_review":result.needs_review,
            "records":result.records,"d1_writes":0,
            "limitations":["uploads playlists may omit upcoming/live announcements",
                           "search discovery is optional and costs 100 quota units per channel/event",
                           "no claim of complete livestream coverage","no channel avatar source in this receipt"]}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--approved-roster",required=True)
    parser.add_argument("--out",required=True)
    parser.add_argument("--discover-broadcasts",action="store_true")
    args=parser.parse_args()
    key=os.environ.get("YOUTUBE_API_KEY","")
    try:
        with open(args.approved_roster,encoding="utf-8") as f:roster=json.load(f)
        output=live_provider_sample(roster,key,discover_broadcasts=args.discover_broadcasts)
        with open(args.out,"x",encoding="utf-8") as f:json.dump(output,f,ensure_ascii=False,indent=2,default=str)
        print(json.dumps({"mode":output["mode"],"api_calls":output["api_calls"],
            "records":len(output["records"]),"gap":output["gap"],"out":args.out}))
    except Exception as exc:
        print("read-only provider probe failed: "+str(exc),file=sys.stderr)
        raise SystemExit(1)
if __name__=="__main__":main()
