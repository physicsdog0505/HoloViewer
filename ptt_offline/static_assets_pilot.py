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
from collections import Counter
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
SOURCE_MANIFEST_KEY="ptt/v1/manifests/2026-10-pilot.json"
FULL_MANIFEST_KEY="ptt/v1/manifests/static-assets-full-2026-10.json"


def _manifest_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_object_bytes(root: Path, item: dict) -> tuple[dict,bytes,int]:
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
    return payload,raw,target.stat().st_size


def _read_object(root: Path, item: dict) -> tuple[dict,int]:
    payload,_,size=_read_object_bytes(root,item)
    return payload,size


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
        _,raw,_=_read_object_bytes(archive_root,item)
        if not key.endswith(".json.gz"):
            raise ContractError(f"source archive object is not JSON gzip: {key}")
        asset_key=key.removesuffix(".gz")
        target=out_dir/asset_key
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
        asset_item=dict(item)
        asset_item["key"]=asset_key
        asset_item["source_archive_key"]=key
        asset_item["bytes_json"]=len(raw)
        asset_item["source_gzip_bytes"]=asset_item.pop("bytes_gzip")
        selected.append(asset_item)
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
            "canonical_bytes":sum((out_dir/item["key"]).stat().st_size for item in selected),
            "manifest":str(pilot_path),"worker_code":False,"d1_bindings":0}


def _full_source(archive_root: Path) -> tuple[Path,dict,list[tuple[dict,bytes,int]]]:
    manifest_path=archive_root/SOURCE_MANIFEST_KEY
    try:
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise ContractError("invalid full source manifest") from exc
    objects=manifest.get("objects",[])
    keys=[item.get("key") for item in objects]
    if len(keys)!=len(set(keys)):
        raise ContractError("full source manifest has duplicate object key")
    if manifest.get("total_objects")!=len(objects):
        raise ContractError("full source manifest object count mismatch")
    if manifest.get("total_pushes")!=sum(item.get("pushes",-1) for item in objects):
        raise ContractError("full source manifest push count mismatch")
    loaded=[]
    for item in objects:
        if not item["key"].endswith(".json.gz"):
            raise ContractError(f"source archive object is not JSON gzip: {item['key']}")
        payload,raw,gzip_size=_read_object_bytes(archive_root,item)
        if item.get("bytes_gzip")!=gzip_size:
            raise ContractError(f"source gzip byte count mismatch: {item['key']}")
        loaded.append((payload,raw,gzip_size))
    return manifest_path,manifest,loaded


def audit_full_static_bundle(*, archive_root: Path, out_dir: Path,
                             write_receipt: bool=True) -> dict:
    """Independently reread a complete Static Assets package and its source."""
    source_path,source,source_loaded=_full_source(archive_root)
    manifest_path=out_dir/FULL_MANIFEST_KEY
    try:
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise ContractError("invalid full Static Assets manifest") from exc
    source_objects=source["objects"]
    objects=manifest.get("objects",[])
    source_keys=[item["key"] for item in source_objects]
    output_keys=[item.get("key") for item in objects]
    expected_output_keys=[key.removesuffix(".gz") for key in source_keys]
    if len(output_keys)!=len(set(output_keys)):
        raise ContractError("full Static Assets manifest has duplicate output key")
    if manifest.get("total_objects")!=len(objects) or output_keys!=expected_output_keys:
        raise ContractError("full Static Assets object set differs from source manifest")
    if manifest.get("source_manifest_sha256")!=_manifest_digest(source_path):
        raise ContractError("full Static Assets source manifest SHA mismatch")
    source_identities=[]
    output_identities=[]
    aid_floors=[]
    canonical_bytes=0
    for source_item,(source_payload,source_raw,source_gzip_size),item in zip(
            source_objects,source_loaded,objects):
        expected_key=source_item["key"].removesuffix(".gz")
        if item.get("key")!=expected_key or item.get("source_archive_key")!=source_item["key"]:
            raise ContractError(f"source archive mapping mismatch: {source_item['key']}")
        target=out_dir/expected_key
        try:
            raw=target.read_bytes()
            payload=json.loads(raw)
        except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
            raise ContractError(f"invalid canonical JSON asset: {expected_key}") from exc
        digest=sha256(raw).hexdigest()
        if digest!=item.get("sha256") or digest!=source_item["sha256"]:
            raise ContractError(f"canonical asset SHA mismatch: {expected_key}")
        if len(raw)!=item.get("bytes_json"):
            raise ContractError(f"canonical asset byte count mismatch: {expected_key}")
        if item.get("source_gzip_bytes")!=source_gzip_size:
            raise ContractError(f"source gzip mapping byte count mismatch: {expected_key}")
        if len(payload.get("pushes",[]))!=item.get("pushes"):
            raise ContractError(f"canonical asset push count mismatch: {expected_key}")
        if raw!=source_raw:
            raise ContractError(f"canonical asset bytes differ from source: {expected_key}")
        canonical_bytes+=len(raw)
        for row in source_payload["pushes"]:
            source_identities.append(row["source_record_key"])
        for row in payload["pushes"]:
            output_identities.append(row["source_record_key"])
            if row.get("floor") is None:
                raise ContractError(f"unexpected floor=null: {row['source_record_key']}")
            aid_floors.append((row["aid"],row["floor"]))
    if len(source_identities)!=len(set(source_identities)):
        raise ContractError("source archive has duplicate source_record_key")
    if len(output_identities)!=len(set(output_identities)):
        raise ContractError("Static Assets package has duplicate source_record_key")
    if len(aid_floors)!=len(set(aid_floors)):
        raise ContractError("Static Assets package has duplicate AID/floor")
    if set(output_identities)!=set(source_identities):
        raise ContractError("Static Assets identity set differs from source archive")
    if manifest.get("total_pushes")!=len(output_identities):
        raise ContractError("full Static Assets total push count mismatch")
    if manifest.get("total_canonical_bytes")!=canonical_bytes:
        raise ContractError("full Static Assets canonical byte total mismatch")
    if manifest.get("days")!=source.get("days"):
        raise ContractError("full Static Assets coverage matrix differs from source")
    gzip_assets=sorted(str(path.relative_to(out_dir)) for path in out_dir.rglob("*.gz"))
    if gzip_assets:
        raise ContractError("full Static Assets package contains .gz output")
    coverage=dict(Counter(day["coverage_status"] for day in manifest["days"]))
    audit={
        "status":"PASS","source_manifest_sha256":_manifest_digest(source_path),
        "manifest_sha256":_manifest_digest(manifest_path),
        "total_objects":len(objects),"total_pushes":len(output_identities),
        "total_canonical_bytes":canonical_bytes,
        "duplicate_source_record_keys":0,"duplicate_aid_floors":0,
        "floor_unknown_rows":0,"identity_set_preserved":True,
        "source_archive_mapping_exact":True,"asset_sha_exact":True,
        "asset_byte_length_exact":True,"gzip_assets":0,
        "coverage_status_counts":coverage,
    }
    if write_receipt:
        receipt_path=out_dir.parent/"full-build-audit.json"
        receipt_path.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",
                                encoding="utf-8")
        audit["receipt"]=str(receipt_path)
    return audit


def build_full_static_bundle(*, archive_root: Path, out_dir: Path) -> dict:
    """Build every object declared by the accepted source manifest."""
    if out_dir.exists():
        raise ContractError(f"full Static Assets output already exists: {out_dir}")
    manifest_path,manifest,loaded=_full_source(archive_root)
    selected=[]
    for item,(_,raw,gzip_size) in zip(manifest["objects"],loaded):
        asset_key=item["key"].removesuffix(".gz")
        target=out_dir/asset_key
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
        asset_item=dict(item)
        asset_item["key"]=asset_key
        asset_item["source_archive_key"]=item["key"]
        asset_item["bytes_json"]=len(raw)
        asset_item["source_gzip_bytes"]=gzip_size
        asset_item.pop("bytes_gzip",None)
        selected.append(asset_item)
    full={
        "schema_version":manifest["schema_version"],
        "precision":manifest["precision"],
        "chunk_minutes":manifest["chunk_minutes"],
        "timezone":manifest["timezone"],
        "source_manifest_sha256":_manifest_digest(manifest_path),
        "from_day_taipei":manifest["from_day_taipei"],
        "through_day_taipei":manifest["through_day_taipei"],
        "days":manifest["days"],
        "total_pushes":manifest["total_pushes"],
        "total_objects":manifest["total_objects"],
        "total_canonical_bytes":sum(item["bytes_json"] for item in selected),
        "objects":selected,
    }
    full_path=out_dir/FULL_MANIFEST_KEY
    full_path.parent.mkdir(parents=True,exist_ok=True)
    full_path.write_text(json.dumps(full,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out_dir/"_headers").write_text(
        "/ptt/v1/chunks/*\n"
        "  Content-Type: application/json\n"
        "  Cache-Control: public, max-age=0, must-revalidate\n"
        "  Access-Control-Allow-Origin: *\n"
        "  X-Content-Type-Options: nosniff\n\n"
        "/ptt/v1/manifests/*\n"
        "  Content-Type: application/json; charset=utf-8\n"
        "  Cache-Control: no-cache\n"
        "  Access-Control-Allow-Origin: *\n"
        "  X-Content-Type-Options: nosniff\n",encoding="utf-8")
    config={"name":"holoviewer-ptt-static-assets-full-offline",
            "compatibility_date":"2026-10-18",
            "assets":{"directory":"./public","not_found_handling":"404-page"}}
    (out_dir.parent/"wrangler.jsonc").write_text(
        json.dumps(config,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    browser_check=Path(__file__).with_name("static_assets_pilot")/"public/browser-check.html"
    if browser_check.is_file():
        harness=browser_check.read_text(encoding="utf-8").replace(
            "/ptt/v1/manifests/static-assets-pilot.json",f"/{FULL_MANIFEST_KEY}")
        (out_dir/"browser-check.html").write_text(harness,encoding="utf-8")
    audit=audit_full_static_bundle(archive_root=archive_root,out_dir=out_dir)
    return {"status":"STATIC_FULL_BUNDLE_READY","manifest":str(full_path),
            "objects":full["total_objects"],"pushes":full["total_pushes"],
            "canonical_bytes":full["total_canonical_bytes"],"audit":audit,
            "worker_code":False,"d1_bindings":0}


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
    full_bundle=commands.add_parser("build-full-bundle")
    full_bundle.add_argument("--archive-root",required=True,type=Path)
    full_bundle.add_argument("--out-dir",required=True,type=Path)
    full_audit=commands.add_parser("audit-full-bundle")
    full_audit.add_argument("--archive-root",required=True,type=Path)
    full_audit.add_argument("--out-dir",required=True,type=Path)
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
    elif args.command=="build-full-bundle":
        result=build_full_static_bundle(archive_root=args.archive_root,out_dir=args.out_dir)
    elif args.command=="audit-full-bundle":
        result=audit_full_static_bundle(archive_root=args.archive_root,out_dir=args.out_dir)
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
