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

def vod_minute(push_occurred_at: str, actual_start: str) -> int:
    """Map two timezone-aware absolute timestamps onto a VOD minute."""
    delta=_utc(push_occurred_at)-_utc(actual_start)
    return int(delta.total_seconds()//60)

def _key(start: datetime) -> str:
    return start.strftime("ptt/v1/chunks/%Y/%m/%d/%H00.json.gz")

def _event_row(event: dict, *, url: str) -> dict:
    occurred=_utc(event["occurred_at"]).replace(second=0,microsecond=0)
    row={
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
    for name in ("coverage_day","coverage_status","finalized","source_path",
                 "time_quality","chronology_note"):
        if name in event:
            row[name]=event[name]
    return row

def _write_deterministic_gzip(target: Path, raw: bytes) -> None:
    """Write reproducible gzip bytes on Python 3.12+ without gzip.open mtime."""
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("wb") as output:
        with gzip.GzipFile(filename="",mode="wb",fileobj=output,
                           compresslevel=9,mtime=0) as handle:
            handle.write(raw)

def write_archive_rows(rows: list[dict], *, from_day: str, through_day: str,
                       out_dir: Path, days: list[dict],
                       manifest_name: str | None=None,
                       generated_at: str | None=None) -> dict:
    """Write staged absolute-minute rows with replaceable coverage metadata."""
    allowed={"COMPLETE","UNKNOWN","PARTIAL"}
    priority={"COMPLETE":0,"UNKNOWN":1,"PARTIAL":2}
    day_map={item["day"]:item for item in days}
    if set(item["coverage_status"] for item in days) - allowed:
        raise ContractError("invalid day coverage status")
    if any(item["finalized"] != (item["coverage_status"] == "COMPLETE") for item in days):
        raise ContractError("day finalized flag contradicts coverage status")
    chunks=defaultdict(list)
    seen=set()
    for source in rows:
        row=dict(source)
        occurred=_utc(row["occurred_at"]).replace(second=0,microsecond=0)
        row["occurred_at"]=occurred.isoformat(timespec="seconds").replace("+00:00","Z")
        row["minute_epoch"]=int(occurred.timestamp()//60)
        key=row.get("source_record_key")
        if not isinstance(key,str) or not key or key in seen:
            raise ContractError("duplicate or invalid source_record_key")
        seen.add(key)
        coverage_day=row.get("coverage_day")
        if coverage_day not in day_map:
            raise ContractError("row coverage day missing from manifest")
        expected=day_map[coverage_day]
        row["coverage_status"]=expected["coverage_status"]
        row["finalized"]=expected["finalized"]
        chunks[_key(_hour_start(row["occurred_at"]))].append(row)

    out_dir.mkdir(parents=True,exist_ok=True)
    objects=[]
    for key in sorted(chunks):
        chunk_rows=sorted(chunks[key],key=lambda r:(r["minute_epoch"],r["aid"],r["source_line"]))
        start=_hour_start(chunk_rows[0]["occurred_at"])
        status=max((r["coverage_status"] for r in chunk_rows),key=priority.get)
        finalized=(status == "COMPLETE")
        payload={
            "schema_version":SCHEMA,
            "precision":"minute",
            "bucket_start":start.isoformat(timespec="seconds").replace("+00:00","Z"),
            "bucket_end":(start+timedelta(hours=1)).isoformat(timespec="seconds").replace("+00:00","Z"),
            "coverage_status":status,
            "finalized":finalized,
            "pushes":chunk_rows,
        }
        raw=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode("utf-8")
        target=out_dir/key
        _write_deterministic_gzip(target,raw)
        objects.append({
            "key":key,"bucket_start":payload["bucket_start"],
            "bucket_end":payload["bucket_end"],"pushes":len(chunk_rows),
            "sha256":sha256(raw).hexdigest(),"bytes_gzip":target.stat().st_size,
            "coverage_status":status,"finalized":finalized,
        })
    generated=generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
    manifest={
        "schema_version":SCHEMA,"precision":"minute","chunk_minutes":CHUNK_MINUTES,
        "timezone":"UTC","from_day_taipei":from_day,"through_day_taipei":through_day,
        "generated_at":generated,"total_pushes":len(rows),"pushes":len(rows),
        "total_objects":len(objects),"days":days,"objects":objects,
    }
    name=manifest_name or f"{from_day}_{through_day}.json"
    manifest_path=out_dir/f"ptt/v1/manifests/{name}"
    manifest_path.parent.mkdir(parents=True,exist_ok=True)
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return {**manifest,"manifest_key":str(manifest_path.relative_to(out_dir))}

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

    target_dates=[]
    cursor=start_local.date()
    while cursor<end_local.date():
        target_dates.append(cursor)
        cursor+=timedelta(days=1)
    target_md={d.strftime("%m/%d") for d in target_dates}
    target_years={d.year for d in target_dates}

    articles=db.execute(
        """SELECT id,board,aid,url,last_seen_at FROM articles
           WHERE board='C_Chat' ORDER BY id"""
    ).fetchall()
    keys=("source_line","source_page","kind","author","content","ptt_date","ptt_time","collected_at")
    for article_id,board,raw_aid,url,last_seen_at in articles:
        match=URL_EPOCH.search(url or "")
        if not match:
            continue
        posted=datetime.fromtimestamp(int(match.group(1)),tz=timezone.utc).astimezone(TPE)
        # MM/DD repeats every year, so URL epoch year is part of candidate
        # selection. Include the previous year only for a January boundary.
        allowed_years=set(target_years)
        if any(d.month==1 for d in target_dates):
            allowed_years|={min(target_years)-1}
        if posted.year not in allowed_years or posted.astimezone(timezone.utc)>=end_utc:
            continue
        marks=",".join("?" for _ in target_md)
        candidate=db.execute(
            f"SELECT 1 FROM pushes WHERE article_id=? AND ptt_date IN ({marks}) LIMIT 1",
            (article_id,*sorted(target_md)),
        ).fetchone()
        if candidate is None:
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
        _write_deterministic_gzip(target,raw)
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
