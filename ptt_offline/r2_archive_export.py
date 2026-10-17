"""Export verified Collector PTT pushes into immutable hourly R2 archive objects.

The archive is VOD-agnostic. Each push keeps its absolute UTC minute; a browser
maps it to a VOD by subtracting the catalog video's actual_start. PTT only has
minute precision, so no synthetic seconds or per-video offset is created.
"""
from __future__ import annotations
import argparse, gzip, json, re, sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from .collector_source_preview import open_source, verify_schema
from .ptt_aid_identity import verify_aid_url
from .public_today_contract import ContractError, normalize_public_aid
from .url_epoch_authority import reconstruct_events

TPE=ZoneInfo("Asia/Taipei")
SCHEMA="ptt-r2-archive-v1"
CHUNK_MINUTES=60
URL_EPOCH=re.compile(r"/M\.([0-9]{9,11})\.A\.")

def _utc(iso: str) -> datetime:
    dt=datetime.fromisoformat(iso.replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ContractError("timezone-aware timestamp required")
    return dt.astimezone(timezone.utc)

def _hour_start(occurred_at: str) -> datetime:
    dt=_utc(occurred_at)
    return dt.replace(minute=0,second=0,microsecond=0)

def _key(start: datetime) -> str:
    return start.strftime("ptt/v1/chunks/%Y/%m/%d/%H00.json.gz")

def _event_row(event: dict, *, url: str) -> dict:
    occurred=_utc(event["occurred_at"]).replace(second=0,microsecond=0)
    return {
        "occurred_at":occurred.isoformat(timespec="seconds").replace("+00:00","Z"),
        "minute_epoch":int(occurred.timestamp()//60),
        "aid":normalize_public_aid(event["aid"]),
        "source_line":event["source_line"],
        "source_page":event.get("source_page"),
        "kind":event.get("kind"),
        "author":event.get("author") or "",
        "content":event.get("content") or "",
        "source_url":url,
        "source_record_key":event["source_record_key"],
    }

def export_archive(db, *, from_day: str, through_day: str, out_dir: Path) -> dict:
    verify_schema(db)
    start_local=datetime.combine(date.fromisoformat(from_day),datetime.min.time(),tzinfo=TPE)
    end_local=datetime.combine(date.fromisoformat(through_day)+timedelta(days=1),datetime.min.time(),tzinfo=TPE)
    start_utc=start_local.astimezone(timezone.utc)
    end_utc=end_local.astimezone(timezone.utc)
    chunks=defaultdict(list)
    articles_scanned=0
    pushes_selected=0
    rejected=[]

    articles=db.execute(
        """SELECT id,board,aid,url,last_seen_at FROM articles
           WHERE board='C_Chat' ORDER BY id"""
    ).fetchall()
    keys=("source_line","source_page","kind","author","content","ptt_date","ptt_time","collected_at")
    for article_id,board,raw_aid,url,last_seen_at in articles:
        match=URL_EPOCH.search(url or "")
        if not match:
            continue
        posted=datetime.fromtimestamp(int(match.group(1)),tz=timezone.utc)
        # Daily Holo threads are short lived. Keep a two-day pre-boundary margin
        # so a thread opened just before midnight can contribute Oct 1 pushes.
        if posted >= end_utc or posted < start_utc-timedelta(days=2):
            continue
        raw=db.execute(
            """SELECT source_line,source_page,kind,author,content,ptt_date,ptt_time,collected_at
               FROM pushes WHERE article_id=? ORDER BY source_line""",
            (article_id,),
        ).fetchall()
        if not raw:
            continue
        articles_scanned+=1
        try:
            events=reconstruct_events(
                board=board,aid=raw_aid,url=url,identity_verifier=verify_aid_url,
                pushes=[dict(zip(keys,row)) for row in raw],
            )
        except ContractError as exc:
            rejected.append({"aid":raw_aid,"url":url,"reason":str(exc)})
            continue
        for event in events:
            when=_utc(event["occurred_at"])
            if not start_utc<=when<end_utc:
                continue
            row=_event_row(event,url=url)
            chunks[_key(_hour_start(row["occurred_at"]))].append(row)
            pushes_selected+=1

    if rejected:
        raise ContractError("archive export rejected relevant article chronology: "+json.dumps(rejected,ensure_ascii=False))

    out_dir.mkdir(parents=True,exist_ok=True)
    objects=[]
    for key in sorted(chunks):
        rows=sorted(chunks[key],key=lambda r:(r["minute_epoch"],r["aid"],r["source_line"]))
        start=_hour_start(rows[0]["occurred_at"])
        payload={
            "schema_version":SCHEMA,
            "precision":"minute",
            "bucket_start":start.isoformat(timespec="seconds").replace("+00:00","Z"),
            "bucket_end":(start+timedelta(hours=1)).isoformat(timespec="seconds").replace("+00:00","Z"),
            "pushes":rows,
        }
        raw=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode("utf-8")
        digest=sha256(raw).hexdigest()
        target=out_dir/key
        target.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(target,"wb",compresslevel=9,mtime=0) as handle:
            handle.write(raw)
        objects.append({
            "key":key,
            "bucket_start":payload["bucket_start"],
            "bucket_end":payload["bucket_end"],
            "pushes":len(rows),
            "sha256":digest,
            "bytes_gzip":target.stat().st_size,
        })

    manifest={
        "schema_version":SCHEMA,
        "precision":"minute",
        "chunk_minutes":CHUNK_MINUTES,
        "timezone":"UTC",
        "vod_mapping":"vod_minute=floor((push.occurred_at-actual_start)/60s)",
        "from_day_taipei":from_day,
        "through_day_taipei":through_day,
        "articles_scanned":articles_scanned,
        "pushes":pushes_selected,
        "objects":objects,
    }
    manifest_path=out_dir/f"ptt/v1/manifests/{from_day}_{through_day}.json"
    manifest_path.parent.mkdir(parents=True,exist_ok=True)
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return {**manifest,"manifest_key":str(manifest_path.relative_to(out_dir))}

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--source",required=True)
    p.add_argument("--from-day",required=True)
    p.add_argument("--through-day",required=True)
    p.add_argument("--out-dir",required=True)
    args=p.parse_args(argv)
    out=Path(args.out_dir)
    with open_source(args.source) as db:
        receipt=export_archive(db,from_day=args.from_day,through_day=args.through_day,out_dir=out)
    print(json.dumps({
        "status":"ARCHIVE_EXPORTED",
        "schema_version":receipt["schema_version"],
        "pushes":receipt["pushes"],
        "objects":len(receipt["objects"]),
        "manifest_key":receipt["manifest_key"],
        "out_dir":str(out),
    },ensure_ascii=False))

if __name__=="__main__": main()
