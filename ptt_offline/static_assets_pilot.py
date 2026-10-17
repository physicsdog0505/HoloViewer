"""Offline-only Workers Static Assets bundle and historical VOD resolver.

This module never calls Cloudflare, YouTube, a Worker API, or D1.  It prepares
and verifies a small directory that can be considered for a separately named
Static Assets deployment only after explicit owner approval.
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from .public_today_contract import ContractError
from .public_today_contract import normalize_public_aid
from .r2_archive_export import (_key, _per_thread_floors, _utc, vod_minute,
                                write_archive_rows)

TPE=ZoneInfo("Asia/Taipei")
STATUS_PRIORITY={"COMPLETE":0,"UNKNOWN":1,"PARTIAL":2,"MISSING":3}


def _manifest_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_object(root: Path, item: dict) -> tuple[dict,int]:
    target=root/item["key"]
    if not target.is_file():
        raise ContractError(f"manifest object missing: {item['key']}")
    with gzip.open(target,"rb") as handle:
        raw=handle.read()
    if sha256(raw).hexdigest() != item["sha256"]:
        raise ContractError(f"manifest object SHA mismatch: {item['key']}")
    try:
        payload=json.loads(raw)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise ContractError(f"invalid gzip JSON: {item['key']}") from exc
    if len(payload.get("pushes",[])) != item["pushes"]:
        raise ContractError(f"manifest object count mismatch: {item['key']}")
    return payload,target.stat().st_size


def build_static_bundle(*, archive_root: Path, out_dir: Path,
                        object_keys: list[str]) -> dict:
    """Copy a bounded, verified subset into an asset-only deployment folder."""
    manifest_path=archive_root/"ptt/v1/manifests/2026-10-pilot.json"
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    by_key={item["key"]:item for item in manifest["objects"]}
    if not 1<=len(object_keys)<=3 or len(set(object_keys))!=len(object_keys):
        raise ContractError("static pilot requires 1-3 distinct objects")
    selected=[]
    for key in object_keys:
        item=by_key.get(key)
        if item is None:
            raise ContractError(f"object is not in source manifest: {key}")
        _read_object(archive_root,item)
        target=out_dir/key
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(archive_root/key,target)
        selected.append(item)
    pilot={
        "schema_version":manifest["schema_version"],
        "precision":manifest["precision"],
        "chunk_minutes":manifest["chunk_minutes"],
        "timezone":manifest["timezone"],
        "source_manifest_sha256":_manifest_digest(manifest_path),
        "from_day_taipei":manifest["from_day_taipei"],
        "through_day_taipei":manifest["through_day_taipei"],
        "days":manifest["days"],
        "total_pushes":sum(item["pushes"] for item in selected),
        "total_objects":len(selected),
        "objects":selected,
    }
    pilot_path=out_dir/"ptt/v1/manifests/static-assets-pilot.json"
    pilot_path.parent.mkdir(parents=True,exist_ok=True)
    pilot_path.write_text(json.dumps(pilot,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    # Revalidation is intentionally safe for both finalized and replaceable
    # same-key chunks.  Immutable caching needs fingerprinted/versioned URLs.
    (out_dir/"_headers").write_text(
        "/ptt/v1/chunks/*\n"
        "  Content-Type: application/json\n"
        "  Content-Encoding: gzip\n"
        "  Cache-Control: public, max-age=0, must-revalidate\n"
        "  Access-Control-Allow-Origin: *\n"
        "  X-Content-Type-Options: nosniff\n\n"
        "/ptt/v1/manifests/*\n"
        "  Content-Type: application/json; charset=utf-8\n"
        "  Cache-Control: no-cache\n"
        "  Access-Control-Allow-Origin: *\n"
        "  X-Content-Type-Options: nosniff\n",
        encoding="utf-8",
    )
    config={
        "name":"holoviewer-ptt-static-assets-pilot",
        "compatibility_date":"2026-10-18",
        "assets":{"directory":"./public","not_found_handling":"404-page"},
    }
    (out_dir.parent/"wrangler.jsonc").write_text(
        json.dumps(config,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    browser_check=Path(__file__).with_name("static_assets_pilot")/"public/browser-check.html"
    if browser_check.is_file():
        shutil.copyfile(browser_check,out_dir/"browser-check.html")
    return {"status":"STATIC_BUNDLE_READY","objects":len(selected),
            "pushes":pilot["total_pushes"],
            "gzip_bytes":sum((out_dir/item["key"]).stat().st_size for item in selected),
            "manifest":str(pilot_path),"worker_code":False,"d1_bindings":0}


def _floor_indexes(source_paths: list[Path]) -> list[dict[tuple[str,int],tuple[int,str]]]:
    indexes=[]
    for path in source_paths:
        index={}
        db=sqlite3.connect(f"file:{path}?mode=ro&immutable=1",uri=True)
        db.row_factory=sqlite3.Row
        try:
            for article in db.execute("SELECT id,aid FROM articles WHERE board='C_Chat'"):
                raw=[dict(row) for row in db.execute(
                    "SELECT source_line,source_page FROM pushes WHERE article_id=? ORDER BY source_line",
                    (article["id"],),
                )]
                floors,quality=_per_thread_floors(db,article["id"],raw)
                aid=normalize_public_aid(article["aid"])
                for line,floor in floors.items():
                    key=(aid,line)
                    value=(floor,quality)
                    if key in index and index[key] != value:
                        raise ContractError(f"conflicting floor evidence within source: {aid}:{line}")
                    index[key]=value
        finally:
            db.close()
        indexes.append(index)
    return indexes


def enrich_archive_floors(*, archive_root: Path, out_dir: Path,
                          source_paths: list[Path]) -> dict:
    """Add proven floors to the fixed source manifest row set only."""
    source_manifest_path=archive_root/"ptt/v1/manifests/2026-10-pilot.json"
    source_manifest=json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if len(source_paths)!=2:
        raise ContractError("pilot floor enrichment requires backfill then operational source")
    floor_indexes=_floor_indexes(source_paths)
    rows=[]
    unknown=[]
    original_keys=[]
    for item in source_manifest["objects"]:
        payload,_=_read_object(archive_root,item)
        for source in payload["pushes"]:
            row=dict(source)
            original_keys.append(row["source_record_key"])
            # Preserve the row's recorded authoritative provenance. Some
            # 10/07 night-thread rows fall in the 10/08 Taipei coverage day,
            # so a date-only cutover would choose the wrong database.
            provenance=str(row.get("source_path","")).lower()
            authority=0 if "issue403" in provenance and "missing" in provenance else 1
            evidence=floor_indexes[authority].get(
                (normalize_public_aid(row["aid"]),row["source_line"]))
            if evidence is None:
                row["floor"]=None
                row["floor_quality"]="unknown"
                unknown.append(row["source_record_key"])
            else:
                row["floor"],row["floor_quality"]=evidence
            rows.append(row)
    if len(rows) != source_manifest["total_pushes"]:
        raise ContractError("source manifest row count changed during floor enrichment")
    if len(set(original_keys)) != len(original_keys):
        raise ContractError("source archive has duplicate source_record_key")
    receipt=write_archive_rows(
        rows,from_day=source_manifest["from_day_taipei"],
        through_day=source_manifest["through_day_taipei"],out_dir=out_dir,
        days=source_manifest["days"],manifest_name="2026-10-pilot.json",
        generated_at=source_manifest.get("generated_at"),
    )
    if receipt["total_pushes"] != source_manifest["total_pushes"]:
        raise ContractError("floor enrichment changed total pushes")
    output_keys=[]
    duplicate_floors=[]
    floors_by_aid={}
    for item in receipt["objects"]:
        payload,_=_read_object(out_dir,item)
        for row in payload["pushes"]:
            output_keys.append(row["source_record_key"])
            if row["floor"] is not None:
                key=(row["aid"],row["floor"])
                previous=floors_by_aid.get(key)
                if previous is not None and previous != row["source_record_key"]:
                    duplicate_floors.append(key)
                floors_by_aid[key]=row["source_record_key"]
    if set(output_keys) != set(original_keys) or duplicate_floors:
        raise ContractError("floor enrichment changed identity or duplicated per-AID floors")
    audit={
        "status":"PASS","source_manifest_sha256":_manifest_digest(source_manifest_path),
        "total_pushes":len(rows),"total_objects":receipt["total_objects"],
        "floor_known_rows":len(rows)-len(unknown),"floor_unknown_rows":len(unknown),
        "unknown_floor_source_record_keys":unknown,
        "duplicate_source_record_keys":len(output_keys)-len(set(output_keys)),
        "duplicate_aid_floors":len(duplicate_floors),
        "identity_set_preserved":set(output_keys)==set(original_keys),
        "gzip_bytes":sum(item["bytes_gzip"] for item in receipt["objects"]),
        "manifest":receipt["manifest_key"],
    }
    (out_dir/"floor-audit.json").write_text(
        json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return audit


def measure_archive(*, archive_root: Path, manifest_path: Path) -> dict:
    """Measure actual hourly assets and a deterministic UTC-day repack."""
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    daily={}
    hourly_bytes=0
    largest_hourly=0
    for item in manifest["objects"]:
        payload,size=_read_object(archive_root,item)
        hourly_bytes+=size
        largest_hourly=max(largest_hourly,size)
        for row in payload["pushes"]:
            daily.setdefault(row["occurred_at"][:10],[]).append(row)
    daily_bytes=0
    largest_daily=0
    daily_items=[]
    for day,rows in daily.items():
        start=datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        payload={"schema_version":manifest["schema_version"],"precision":"minute",
                 "bucket_start":start.isoformat().replace("+00:00","Z"),
                 "bucket_end":(start+timedelta(days=1)).isoformat().replace("+00:00","Z"),
                 "pushes":sorted(rows,key=lambda row:(row["minute_epoch"],row["aid"],row["source_line"]))}
        compressed=gzip.compress(json.dumps(payload,ensure_ascii=False,separators=(",",":"))
                                 .encode("utf-8"),compresslevel=9,mtime=0)
        daily_bytes+=len(compressed)
        largest_daily=max(largest_daily,len(compressed))
        daily_items.append({"day_utc":day,"pushes":len(rows),"gzip_bytes":len(compressed)})
    return {
        "total_pushes":manifest["total_pushes"],
        "hourly_objects":len(manifest["objects"]),"hourly_gzip_bytes":hourly_bytes,
        "largest_hourly_gzip_bytes":largest_hourly,
        "utc_daily_objects":len(daily),"utc_daily_gzip_bytes":daily_bytes,
        "largest_utc_daily_gzip_bytes":largest_daily,
        "daily_minus_hourly_bytes":daily_bytes-hourly_bytes,
        "utc_daily":sorted(daily_items,key=lambda item:item["day_utc"]),
    }


def _intersecting_keys(start: datetime, end: datetime) -> list[str]:
    cursor=start.replace(minute=0,second=0,microsecond=0)
    keys=[]
    while cursor<end:
        keys.append(_key(cursor))
        cursor+=timedelta(hours=1)
    return keys


def _coverage_days(start: datetime, end: datetime) -> list[str]:
    cursor=start.astimezone(TPE).date()
    final=(end-timedelta(microseconds=1)).astimezone(TPE).date()
    days=[]
    while cursor<=final:
        days.append(cursor.isoformat())
        cursor+=timedelta(days=1)
    return days


def resolve_vod(*, archive_root: Path, manifest_path: Path,
                actual_start: str, actual_end: str,
                anchor_source: str) -> dict:
    """Resolve absolute-time archive rows for one authoritative VOD window."""
    if anchor_source != "youtube-liveStreamingDetails-actualStartTime":
        raise ContractError("resolver requires authoritative YouTube actualStartTime")
    start=_utc(actual_start)
    end=_utc(actual_end)
    if end<=start:
        raise ContractError("actual_end must be after actual_start")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    objects={item["key"]:item for item in manifest["objects"]}
    day_map={item["day"]:item for item in manifest["days"]}
    touched_days=_coverage_days(start,end)
    statuses=[day_map.get(day,{"coverage_status":"MISSING"})["coverage_status"]
              for day in touched_days]
    coverage_status=max(statuses,key=STATUS_PRIORITY.get)
    object_keys=[]
    pushes=[]
    bytes_gzip=0
    absent_hour_objects=[]
    for key in _intersecting_keys(start,end):
        item=objects.get(key)
        if item is None:
            # Exporter intentionally omits empty UTC hours. Completeness comes
            # from the day coverage matrix, not from synthesizing empty files.
            absent_hour_objects.append(key)
            continue
        payload,size=_read_object(archive_root,item)
        bytes_gzip+=size
        object_keys.append(key)
        for row in payload["pushes"]:
            occurred=_utc(row["occurred_at"])
            if start<=occurred<end:
                loaded_row=dict(row)
                loaded_row["vod_minute"]=vod_minute(row["occurred_at"],actual_start)
                pushes.append(loaded_row)
    seen=set()
    deduped=[]
    duplicates=[]
    for row in sorted(pushes,key=lambda item:(_utc(item["occurred_at"]),item["aid"],
                                               item.get("floor") or 0,item["source_line"])):
        key=row["source_record_key"]
        if key in seen:
            duplicates.append(key)
            continue
        seen.add(key)
        deduped.append(row)
    aid_summaries=[]
    for aid in sorted({row["aid"] for row in deduped}):
        aid_rows=[row for row in deduped if row["aid"]==aid]
        known_floors=[row["floor"] for row in aid_rows if row.get("floor") is not None]
        aid_summaries.append({
            "aid":aid,"pushes":len(aid_rows),
            "first_occurred_at":aid_rows[0]["occurred_at"],
            "last_occurred_at":aid_rows[-1]["occurred_at"],
            "first_floor":min(known_floors) if known_floors else None,
            "last_floor":max(known_floors) if known_floors else None,
            "unknown_floors":sum(row.get("floor") is None for row in aid_rows),
        })
    return {
        "actual_start":start.isoformat().replace("+00:00","Z"),
        "actual_end":end.isoformat().replace("+00:00","Z"),
        "coverage_days":touched_days,"coverage_status":coverage_status,
        "strict_complete":coverage_status=="COMPLETE",
        "object_keys":object_keys,"absent_hour_objects":absent_hour_objects,
        "gzip_bytes":bytes_gzip,"pushes":deduped,
        "push_count":len(deduped),"duplicate_source_record_keys":duplicates,
        "aids":aid_summaries,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description="Offline-only PTT Static Assets pilot")
    commands=parser.add_subparsers(dest="command",required=True)
    enrich=commands.add_parser("enrich-floors")
    enrich.add_argument("--archive-root",required=True,type=Path)
    enrich.add_argument("--out-dir",required=True,type=Path)
    enrich.add_argument("--source",required=True,action="append",type=Path)
    bundle=commands.add_parser("build-bundle")
    bundle.add_argument("--archive-root",required=True,type=Path)
    bundle.add_argument("--out-dir",required=True,type=Path)
    bundle.add_argument("--object",required=True,action="append")
    resolve=commands.add_parser("resolve-vod")
    resolve.add_argument("--archive-root",required=True,type=Path)
    resolve.add_argument("--manifest",required=True,type=Path)
    resolve.add_argument("--actual-start",required=True)
    resolve.add_argument("--actual-end",required=True)
    resolve.add_argument("--anchor-source",required=True,
                         choices=["youtube-liveStreamingDetails-actualStartTime"])
    measure=commands.add_parser("measure")
    measure.add_argument("--archive-root",required=True,type=Path)
    measure.add_argument("--manifest",required=True,type=Path)
    args=parser.parse_args(argv)
    if args.command=="enrich-floors":
        result=enrich_archive_floors(archive_root=args.archive_root,out_dir=args.out_dir,
                                     source_paths=args.source)
    elif args.command=="build-bundle":
        result=build_static_bundle(archive_root=args.archive_root,out_dir=args.out_dir,
                                   object_keys=args.object)
    elif args.command=="resolve-vod":
        result=resolve_vod(archive_root=args.archive_root,manifest_path=args.manifest,
                           actual_start=args.actual_start,actual_end=args.actual_end,
                           anchor_source=args.anchor_source)
        result={key:value for key,value in result.items() if key!="pushes"}
    else:
        result=measure_archive(archive_root=args.archive_root,manifest_path=args.manifest)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
