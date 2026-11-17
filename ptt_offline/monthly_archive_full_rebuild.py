"""Build a complete month as one immutable R2-compatible object per Taipei day.

The source SQLite is opened read-only through ``r2_archive_export``.  This
module stages a fresh candidate only; importing it never performs network or
Cloudflare operations.
"""
from __future__ import annotations

import argparse
import calendar
from datetime import datetime, timedelta, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

from .collector_source_preview import open_source
from .monthly_archive_pipeline import canonical_bytes, digest_bytes, validate_month_manifest
from .r2_archive_export import export_archive


TPE=ZoneInfo("Asia/Taipei")
SCHEMA="ptt-r2-archive-v1"
DAILY_SCHEMAS={"holoviewer-ptt-history-day-v1","holoviewer-ptt-history-day-v2"}
COVERAGE_SCHEMA="holoviewer-ptt-month-coverage-v1"
SUPPLEMENT_SCHEMA="holoviewer-ptt-month-supplement-v1"
RECEIPT_SCHEMA="holoviewer-ptt-month-full-rebuild-v1"


class MonthlyArchiveFullRebuildError(RuntimeError):
    pass


_HEADERS=(
    "/ptt/v1/*\n"
    "  Content-Type: application/json; charset=utf-8\n"
    "  Cache-Control: public, max-age=31536000, immutable\n"
    "  Access-Control-Allow-Origin: *\n"
    "  X-Content-Type-Options: nosniff\n\n"
    "/ptt/v1/manifests/*\n"
    "  Cache-Control: no-cache\n"
).encode("utf-8")


def _sha_file(path: Path) -> str:
    digest=sha256()
    with path.open("rb") as handle:
        for block in iter(lambda:handle.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()


def _load_coverage(raw: bytes, *, month: str) -> tuple[dict[str,dict[str,Any]],dict[str,Any]]:
    try:
        body=json.loads(raw)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise MonthlyArchiveFullRebuildError("coverage evidence JSON invalid") from exc
    if not isinstance(body,dict) or body.get("schema_version")!=COVERAGE_SCHEMA:
        raise MonthlyArchiveFullRebuildError("coverage evidence schema mismatch")
    if body.get("month")!=month or not isinstance(body.get("days"),list):
        raise MonthlyArchiveFullRebuildError("coverage evidence month mismatch")
    year,number=map(int,month.split("-"))
    expected=[f"{month}-{day:02d}" for day in range(1,calendar.monthrange(year,number)[1]+1)]
    rows={}
    for item in body["days"]:
        if not isinstance(item,dict) or not isinstance(item.get("day"),str):
            raise MonthlyArchiveFullRebuildError("coverage day entry invalid")
        day=item["day"]
        if day in rows:
            raise MonthlyArchiveFullRebuildError("duplicate coverage day")
        if item.get("coverage_status")!="COMPLETE" or item.get("finalized") is not True:
            raise MonthlyArchiveFullRebuildError("all month days must be finalized COMPLETE")
        evidence=item.get("evidence")
        if not isinstance(evidence,list) or not evidence or not all(
                isinstance(value,str) and value for value in evidence):
            raise MonthlyArchiveFullRebuildError("coverage day evidence required")
        rows[day]=item
    if sorted(rows)!=expected:
        raise MonthlyArchiveFullRebuildError("coverage evidence must contain every calendar day")
    return rows,body


def _read_hourly_rows(root: Path, export_manifest: dict[str,Any]) -> list[dict[str,Any]]:
    rows=[]
    seen=set()
    for item in export_manifest.get("objects",[]):
        key=item.get("key") if isinstance(item,dict) else None
        if not isinstance(key,str) or not key.endswith(".json.gz"):
            raise MonthlyArchiveFullRebuildError("hourly export object key invalid")
        target=root/key
        try:
            with gzip.open(target,"rb") as handle:
                raw=handle.read()
            payload=json.loads(raw)
        except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
            raise MonthlyArchiveFullRebuildError("hourly export object unreadable") from exc
        if digest_bytes(raw)!=item.get("sha256"):
            raise MonthlyArchiveFullRebuildError("hourly export object SHA mismatch")
        pushes=payload.get("pushes") if isinstance(payload,dict) else None
        if (not isinstance(payload,dict) or payload.get("schema_version")!=SCHEMA or
                not isinstance(pushes,list)):
            raise MonthlyArchiveFullRebuildError("hourly export object contract mismatch")
        if len(pushes)!=item.get("pushes"):
            raise MonthlyArchiveFullRebuildError("hourly export push count mismatch")
        for row in pushes:
            identity=row.get("source_record_key") if isinstance(row,dict) else None
            if not isinstance(identity,str) or not identity or identity in seen:
                raise MonthlyArchiveFullRebuildError("duplicate or invalid source row identity")
            seen.add(identity)
            rows.append(row)
    if len(rows)!=export_manifest.get("pushes"):
        raise MonthlyArchiveFullRebuildError("hourly export total push count mismatch")
    return rows


def _read_supplemental_rows(manifest_path: Path) -> tuple[list[dict[str,Any]],bytes]:
    raw=manifest_path.read_bytes()
    try:
        body=json.loads(raw)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise MonthlyArchiveFullRebuildError("supplement manifest invalid") from exc
    objects=body.get("objects") if isinstance(body,dict) else None
    if (not isinstance(body,dict) or body.get("schema_version")!=SUPPLEMENT_SCHEMA or
            not isinstance(objects,list) or not objects):
        raise MonthlyArchiveFullRebuildError("supplement manifest contract mismatch")
    rows=[]
    for item in objects:
        path=item.get("path") if isinstance(item,dict) else None
        if not isinstance(path,str) or not Path(path).is_absolute():
            raise MonthlyArchiveFullRebuildError("supplement object path invalid")
        try:
            object_raw=Path(path).read_bytes()
            payload=json.loads(object_raw)
        except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
            raise MonthlyArchiveFullRebuildError("supplement object unreadable") from exc
        pushes=payload.get("pushes") if isinstance(payload,dict) else None
        actual_sha=digest_bytes(object_raw)
        schema=payload.get("schema_version") if isinstance(payload,dict) else None
        if (actual_sha!=item.get("sha256") or
                not isinstance(payload,dict) or schema not in ({SCHEMA}|DAILY_SCHEMAS) or
                not isinstance(pushes,list) or len(pushes)!=item.get("pushes")):
            raise MonthlyArchiveFullRebuildError(
                "supplement object verification failed: "+str(item.get("source"))+"/"+
                str(item.get("key"))+f" sha={actual_sha==item.get('sha256')}"+
                f" schema={schema} pushes={len(pushes) if isinstance(pushes,list) else 'invalid'}"+
                f" expected_pushes={item.get('pushes')}")
        rows.extend(pushes)
    return rows,raw


def _merge_source_rows(formal: list[dict[str,Any]],
                       local: list[dict[str,Any]]) -> tuple[list[dict[str,Any]],dict[str,int]]:
    """Prefer already-published rows, adding local-only identities fail-closed."""
    source_fields=("aid","source_line","kind","author","content","source_url")
    merged={}
    stats={"formal_rows":len(formal),"local_rows":len(local),
           "formal_duplicate_identities":0,"local_duplicate_identities":0,
           "local_rows_added":0,"minute_differences_preserved_formal":0}
    for origin,rows in (("formal",formal),("local",local)):
        for row in rows:
            identity=row.get("source_record_key") if isinstance(row,dict) else None
            if not isinstance(identity,str) or not identity:
                raise MonthlyArchiveFullRebuildError("supplement source identity invalid")
            previous=merged.get(identity)
            if previous is None:
                merged[identity]=row
                if origin=="local":
                    stats["local_rows_added"]+=1
                continue
            stats[f"{origin}_duplicate_identities"]+=1
            if any(previous.get(field)!=row.get(field) for field in source_fields):
                raise MonthlyArchiveFullRebuildError("source identity content conflict")
            try:
                delta=abs(int(previous["minute_epoch"])-int(row["minute_epoch"]))
            except (KeyError,TypeError,ValueError) as exc:
                raise MonthlyArchiveFullRebuildError("source identity minute invalid") from exc
            if delta>1:
                raise MonthlyArchiveFullRebuildError("source identity minute conflict")
            if delta:
                stats["minute_differences_preserved_formal"]+=1
    return list(merged.values()),stats


def _filter_month_rows(rows: list[dict[str,Any]], *, month: str
                       ) -> tuple[list[dict[str,Any]],int]:
    selected=[]
    outside=0
    for row in rows:
        occurred=row.get("occurred_at") if isinstance(row,dict) else None
        if not isinstance(occurred,str):
            raise MonthlyArchiveFullRebuildError("supplement source occurred_at missing")
        try:
            value=datetime.fromisoformat(occurred.replace("Z","+00:00"))
        except ValueError as exc:
            raise MonthlyArchiveFullRebuildError("supplement source occurred_at invalid") from exc
        if value.tzinfo is None:
            raise MonthlyArchiveFullRebuildError("supplement source timezone missing")
        if value.astimezone(TPE).date().isoformat().startswith(month+"-"):
            selected.append(row)
        else:
            outside+=1
    return selected,outside


def validate_candidate_tree(*, public_root: Path, manifest_key: str,
                            month: str) -> dict[str,int]:
    """Read back and rehash every staged object before it is deployable."""
    manifest_path=public_root/manifest_key
    try:
        manifest_raw=manifest_path.read_bytes()
        manifest=json.loads(manifest_raw)
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise MonthlyArchiveFullRebuildError("candidate manifest unreadable") from exc
    if not isinstance(manifest,dict):
        raise MonthlyArchiveFullRebuildError("candidate manifest object required")
    validate_month_manifest(manifest,month=month)
    year,number=map(int,month.split("-"))
    expected_days=calendar.monthrange(year,number)[1]
    if (len(manifest["days"])!=expected_days or
            len(manifest["objects"])!=expected_days):
        raise MonthlyArchiveFullRebuildError("candidate must have one object per calendar day")
    identities=set()
    pushes=0
    for item in manifest["objects"]:
        key=item["key"]
        try:
            raw=(public_root/key).read_bytes()
            payload=json.loads(raw)
        except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
            raise MonthlyArchiveFullRebuildError("candidate object unreadable") from exc
        rows=payload.get("pushes") if isinstance(payload,dict) else None
        if (digest_bytes(raw)!=item["sha256"] or
                not isinstance(payload,dict) or payload.get("schema_version")!=SCHEMA or
                payload.get("bucket_start")!=item.get("bucket_start") or
                payload.get("bucket_end")!=item.get("bucket_end") or
                not isinstance(rows,list) or len(rows)!=item.get("pushes")):
            raise MonthlyArchiveFullRebuildError("candidate object readback mismatch")
        for row in rows:
            identity=row.get("source_record_key") if isinstance(row,dict) else None
            if not isinstance(identity,str) or not identity or identity in identities:
                raise MonthlyArchiveFullRebuildError("candidate source identity invalid")
            identities.add(identity)
        pushes+=len(rows)
    if pushes!=manifest.get("total_pushes") or pushes!=manifest.get("pushes"):
        raise MonthlyArchiveFullRebuildError("candidate total push count mismatch")
    return {"objects":len(manifest["objects"]),"pushes":pushes,
            "unique_source_record_keys":len(identities)}


def repack_hourly_month(
    *, hourly_root: Path, export_manifest: dict[str,Any], coverage_raw: bytes,
    month: str, public_root: Path, generated_at: str,
    source_snapshot_sha256: str,
    supplemental_rows: list[dict[str,Any]] | None=None,
    supplemental_manifest_sha256: str | None=None,
) -> dict[str,Any]:
    coverage,coverage_body=_load_coverage(coverage_raw,month=month)
    local_rows=_read_hourly_rows(hourly_root,export_manifest)
    formal_rows,outside=_filter_month_rows(supplemental_rows or [],month=month)
    rows,union_audit=_merge_source_rows(formal_rows,local_rows)
    union_audit["supplemental_rows_outside_month_ignored"]=outside
    grouped={day:[] for day in coverage}
    for row in rows:
        occurred=row.get("occurred_at")
        if not isinstance(occurred,str):
            raise MonthlyArchiveFullRebuildError("source row occurred_at missing")
        try:
            value=datetime.fromisoformat(occurred.replace("Z","+00:00"))
        except ValueError as exc:
            raise MonthlyArchiveFullRebuildError("source row occurred_at invalid") from exc
        if value.tzinfo is None:
            raise MonthlyArchiveFullRebuildError("source row timezone missing")
        day=value.astimezone(TPE).date().isoformat()
        if day not in grouped:
            raise MonthlyArchiveFullRebuildError("source row outside month scope")
        grouped[day].append(row)

    public_root.mkdir(parents=True,exist_ok=False)
    objects=[]
    days=[]
    for day in sorted(grouped):
        pushes=sorted(grouped[day],key=lambda row:(
            int(row.get("minute_epoch",-1)),str(row.get("aid","")),
            int(row.get("source_line",-1))))
        if not pushes:
            raise MonthlyArchiveFullRebuildError("calendar day has zero source pushes")
        start=datetime.fromisoformat(day).replace(tzinfo=TPE).astimezone(timezone.utc)
        end=(datetime.fromisoformat(day).replace(tzinfo=TPE)+timedelta(days=1))
        end=end.astimezone(timezone.utc)
        payload={
            "schema_version":SCHEMA,"precision":"minute",
            "bucket_start":start.isoformat(timespec="seconds").replace("+00:00","Z"),
            "bucket_end":end.isoformat(timespec="seconds").replace("+00:00","Z"),
            "coverage_status":"COMPLETE","finalized":True,"pushes":pushes,
        }
        raw=canonical_bytes(payload)
        digest=digest_bytes(raw)
        key=f"ptt/v1/daily/{day[:4]}/{day[5:7]}/{day[8:10]}/{digest[:20]}.json"
        target=public_root/key
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
        objects.append({
            "key":key,"bucket_start":payload["bucket_start"],
            "bucket_end":payload["bucket_end"],"pushes":len(pushes),
            "sha256":digest,"bytes_json":len(raw),
            "coverage_status":"COMPLETE","finalized":True,
        })
        source=coverage[day]
        days.append({
            "day":day,"coverage_status":"COMPLETE","finalized":True,
            "reason":source.get("reason","Verified local source coverage and bounded production evidence"),
            "required_aids":list(source.get("required_aids") or []),
            "push_count":len(pushes),"evidence":list(source["evidence"]),
        })

    coverage_sha=digest_bytes(coverage_raw)
    manifest={
        "schema_version":SCHEMA,"precision":"minute","timezone":"UTC",
        "month":month,"from_day_taipei":days[0]["day"],
        "through_day_taipei":days[-1]["day"],"generated_at":generated_at,
        "partitioning":"one-object-per-taipei-day",
        "pushes":len(rows),"total_pushes":len(rows),
        "total_objects":len(objects),
        "total_canonical_bytes":sum(item["bytes_json"] for item in objects),
        "days":days,"objects":objects,
        "source_snapshot_sha256":source_snapshot_sha256,
        "coverage_evidence_sha256":coverage_sha,
        "supplemental_source_manifest_sha256":supplemental_manifest_sha256,
        "source_union_audit":union_audit,
        "source_archive_manifest_sha256":digest_bytes(canonical_bytes({
            "source_snapshot_sha256":source_snapshot_sha256,
            "coverage_evidence_sha256":coverage_sha,
            "source_export_pushes":export_manifest.get("pushes"),
            "repair_overlap_rows_removed":export_manifest.get("repair_overlap_rows_removed",0),
            "supplemental_source_manifest_sha256":supplemental_manifest_sha256,
            "source_union_audit":union_audit,
        })),
    }
    validate_month_manifest(manifest,month=month)
    manifest_key=f"ptt/v1/manifests/static-assets-full-{month}.json"
    manifest_raw=canonical_bytes(manifest)
    target=public_root/manifest_key
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(manifest_raw)
    (public_root/"_headers").write_bytes(_HEADERS)
    verified=validate_candidate_tree(
        public_root=public_root,manifest_key=manifest_key,month=month)
    return {
        "manifest":manifest,"manifest_key":manifest_key,
        "manifest_sha256":digest_bytes(manifest_raw),
        "object_count":len(objects),"push_count":len(rows),
        "local_readback_verified":True,"validation":verified,
        "source_union_audit":union_audit,
        "coverage_evidence":coverage_body,
    }


def build_full_month_candidate(
    *, source: Path, coverage_path: Path, month: str,
    release_root: Path, generated_at: str,
    supplemental_source_manifest: Path | None=None,
) -> dict[str,Any]:
    public_root=release_root/"candidate"/"public"
    if release_root.exists():
        raise MonthlyArchiveFullRebuildError("release root already exists")
    coverage_raw=coverage_path.read_bytes()
    source_sha=_sha_file(source)
    supplemental_rows=[]
    supplemental_raw=None
    if supplemental_source_manifest is not None:
        supplemental_rows,supplemental_raw=_read_supplemental_rows(
            supplemental_source_manifest)
    with tempfile.TemporaryDirectory(prefix=f"holoviewer-{month}-full-") as tmp:
        hourly_root=Path(tmp)
        year,number=map(int,month.split("-"))
        with open_source(str(source)) as db:
            exported=export_archive(
                db,from_day=f"{month}-01",
                through_day=f"{month}-{calendar.monthrange(year,number)[1]:02d}",
                out_dir=hourly_root)
        result=repack_hourly_month(
            hourly_root=hourly_root,export_manifest=exported,
            coverage_raw=coverage_raw,month=month,public_root=public_root,
            generated_at=generated_at,source_snapshot_sha256=source_sha,
            supplemental_rows=supplemental_rows,
            supplemental_manifest_sha256=(digest_bytes(supplemental_raw)
                                          if supplemental_raw is not None else None))
    receipt={
        "schema_version":RECEIPT_SCHEMA,"status":"MONTH_FULL_REBUILD_READY",
        "month":month,"candidate_public":str(public_root),
        "manifest_key":result["manifest_key"],
        "manifest_sha256":result["manifest_sha256"],
        "object_count":result["object_count"],"push_count":result["push_count"],
        "source_snapshot_sha256":source_sha,
        "coverage_evidence_sha256":digest_bytes(coverage_raw),
        "partitioning":"one-object-per-taipei-day","deployable":True,
        "local_readback_verified":result["local_readback_verified"],
        "unique_source_record_keys":result["validation"]["unique_source_record_keys"],
        "supplemental_source_manifest_sha256":(
            digest_bytes(supplemental_raw) if supplemental_raw is not None else None),
        "source_union_audit":result["source_union_audit"],
    }
    release_root.mkdir(parents=True,exist_ok=True)
    (release_root/"release-receipt.json").write_bytes(
        json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2).encode("utf-8")+b"\n")
    return receipt


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",required=True)
    parser.add_argument("--coverage",required=True)
    parser.add_argument("--month",required=True)
    parser.add_argument("--release-root",required=True)
    parser.add_argument("--generated-at",required=True)
    parser.add_argument("--supplemental-source-manifest")
    args=parser.parse_args(argv)
    try:
        receipt=build_full_month_candidate(
            source=Path(args.source).expanduser(),
            coverage_path=Path(args.coverage).expanduser(),month=args.month,
            release_root=Path(args.release_root).expanduser(),
            generated_at=args.generated_at,
            supplemental_source_manifest=(Path(args.supplemental_source_manifest).expanduser()
                                          if args.supplemental_source_manifest else None))
    except (OSError,ValueError,MonthlyArchiveFullRebuildError) as exc:
        print(json.dumps({"status":"FAILED","failure_code":type(exc).__name__,
                          "failure_detail":str(exc)},sort_keys=True))
        return 2
    print(json.dumps(receipt,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
