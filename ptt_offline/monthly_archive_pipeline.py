"""Build a production-reader-compatible monthly PTT archive candidate.

The daily closeout runtime emits one verified lifecycle object per Taipei day.
The production reader consumes ``ptt-r2-archive-v1`` manifests and objects. This
module is the deliberately offline seam between those contracts. It never
deploys, fetches network data, or mutates Collector/D1/Publisher state.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable


R2_SCHEMA="ptt-r2-archive-v1"
DAILY_SCHEMA="holoviewer-ptt-daily-static-package-v1"
DAY_SCHEMA="holoviewer-ptt-history-day-v2"
SHA256_RE=re.compile(r"^[0-9a-f]{64}$")


class MonthlyArchivePipelineError(RuntimeError):
    pass


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,ensure_ascii=False,sort_keys=True,separators=(",",":"),
    ).encode("utf-8")


def digest_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _canonical_day(value: object, *, label: str) -> str:
    if not isinstance(value,str):
        raise MonthlyArchivePipelineError(f"{label} missing")
    try:
        parsed=date.fromisoformat(value)
    except ValueError as exc:
        raise MonthlyArchivePipelineError(f"{label} invalid") from exc
    if parsed.isoformat()!=value:
        raise MonthlyArchivePipelineError(f"{label} invalid")
    return value


def _sha(value: object, *, label: str) -> str:
    if not isinstance(value,str) or not SHA256_RE.fullmatch(value):
        raise MonthlyArchivePipelineError(f"{label} invalid")
    return value


def validate_month_manifest(manifest: dict[str,Any], *, month: str) -> None:
    if manifest.get("schema_version")!=R2_SCHEMA:
        raise MonthlyArchivePipelineError("monthly manifest schema mismatch")
    if manifest.get("precision")!="minute" or manifest.get("timezone")!="UTC":
        raise MonthlyArchivePipelineError("monthly manifest time contract mismatch")
    objects=manifest.get("objects")
    days=manifest.get("days")
    if not isinstance(objects,list) or not isinstance(days,list):
        raise MonthlyArchivePipelineError("monthly manifest arrays required")
    seen=set()
    for item in objects:
        if not isinstance(item,dict) or not isinstance(item.get("key"),str):
            raise MonthlyArchivePipelineError("monthly object entry invalid")
        if item["key"] in seen or not item["key"].endswith(".json"):
            raise MonthlyArchivePipelineError("monthly object key invalid")
        seen.add(item["key"])
        _sha(item.get("sha256"),label="monthly object sha256")
        count=item.get("pushes",item.get("push_count"))
        if not isinstance(count,int) or count<0:
            raise MonthlyArchivePipelineError("monthly object push count invalid")
    seen_days=set()
    for row in days:
        if not isinstance(row,dict):
            raise MonthlyArchivePipelineError("monthly day entry invalid")
        day=_canonical_day(row.get("day"),label="monthly day")
        if not day.startswith(month+"-") or day in seen_days:
            raise MonthlyArchivePipelineError("monthly day scope invalid")
        seen_days.add(day)


def _load_verified_daily(
    *, package: dict[str,Any], archive_job: dict[str,Any],
    object_loader: Callable[[str],bytes], month: str,
) -> tuple[dict[str,Any],dict[str,Any],bytes]:
    day=_canonical_day(package.get("taipei_day"),label="daily package day")
    if not day.startswith(month+"-"):
        raise MonthlyArchivePipelineError("daily package month mismatch")
    if (package.get("schema_version")!=DAILY_SCHEMA or
            package.get("package_status")!="COMPLETE" or
            package.get("immutable") is not True):
        raise MonthlyArchivePipelineError("daily package is not immutable COMPLETE")
    if archive_job.get("job_verified") is not True:
        raise MonthlyArchivePipelineError("daily archive readback is not verified")
    package_manifest=package.get("manifest")
    job_manifest=archive_job.get("manifest")
    if not isinstance(package_manifest,dict) or not isinstance(job_manifest,dict):
        raise MonthlyArchivePipelineError("daily manifest identity missing")
    digest=_sha(package_manifest.get("digest"),label="daily manifest digest")
    if digest!=job_manifest.get("digest") or package_manifest.get("key")!=job_manifest.get("key"):
        raise MonthlyArchivePipelineError("daily archive job identity mismatch")
    objects=package.get("objects")
    if not isinstance(objects,list) or len(objects)!=1:
        raise MonthlyArchivePipelineError("daily package must contain one lifecycle object")
    source=objects[0]
    if not isinstance(source,dict) or not isinstance(source.get("key"),str):
        raise MonthlyArchivePipelineError("daily lifecycle object invalid")
    raw=object_loader(source["key"])
    if digest_bytes(raw)!=_sha(source.get("sha256"),label="daily object sha256"):
        raise MonthlyArchivePipelineError("daily lifecycle object sha mismatch")
    try:
        payload=json.loads(raw)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise MonthlyArchivePipelineError("daily lifecycle object JSON invalid") from exc
    if (not isinstance(payload,dict) or payload.get("schema_version")!=DAY_SCHEMA or
            payload.get("coverage_day")!=day or payload.get("coverage_status")!="COMPLETE" or
            payload.get("finalized") is not True or not isinstance(payload.get("pushes"),list)):
        raise MonthlyArchivePipelineError("daily lifecycle object contract mismatch")
    if len(payload["pushes"])!=package.get("push_count") or len(payload["pushes"])!=source.get("pushes"):
        raise MonthlyArchivePipelineError("daily lifecycle push count mismatch")
    identities=set()
    for row in payload["pushes"]:
        identity=row.get("source_record_key") if isinstance(row,dict) else None
        if not isinstance(identity,str) or not identity or identity in identities:
            raise MonthlyArchivePipelineError("daily lifecycle identities invalid")
        identities.add(identity)
    return package,payload,raw


def advance_month_candidate(
    *, month: str, existing_manifest: dict[str,Any],
    package: dict[str,Any], archive_job: dict[str,Any],
    object_loader: Callable[[str],bytes], generated_at: str,
) -> dict[str,Any]:
    """Append one verified daily lifecycle object to a legacy-compatible month."""
    if not re.fullmatch(r"\d{4}-\d{2}",month):
        raise MonthlyArchivePipelineError("month must be YYYY-MM")
    validate_month_manifest(existing_manifest,month=month)
    package,payload,_=_load_verified_daily(
        package=package,archive_job=archive_job,object_loader=object_loader,
        month=month)
    day=package["taipei_day"]
    existing_day=next((row for row in existing_manifest["days"] if row.get("day")==day),None)
    if existing_day is not None:
        if (existing_day.get("coverage_status")=="COMPLETE" and
                existing_day.get("push_count")==package["push_count"] and
                existing_day.get("daily_manifest_digest")==package["manifest"]["digest"]):
            return {"changed":False,"manifest":deepcopy(existing_manifest),"object":None}
        raise MonthlyArchivePipelineError("monthly day already exists with different identity")

    r2_payload={
        "schema_version":R2_SCHEMA,
        "precision":"minute",
        "bucket_start":payload["partition_start"],
        "bucket_end":payload["partition_end"],
        "pushes":payload["pushes"],
    }
    object_raw=canonical_bytes(r2_payload)
    object_sha=digest_bytes(object_raw)
    object_key=(
        f"ptt/v1/daily/{day[:4]}/{day[5:7]}/{day[8:10]}/"
        f"{object_sha[:20]}.json"
    )
    object_entry={
        "key":object_key,
        "bucket_start":payload["partition_start"],
        "bucket_end":payload["partition_end"],
        "pushes":len(payload["pushes"]),
        "sha256":object_sha,
        "bytes_json":len(object_raw),
        "source_daily_manifest_key":package["manifest"]["key"],
        "source_daily_manifest_digest":package["manifest"]["digest"],
    }
    day_entry={
        "day":day,"coverage_status":"COMPLETE","finalized":True,
        "reason":"Verified daily closeout and immutable Static Assets readback",
        "expected_thread_count":len(package.get("expected_aids") or []),
        "required_aids":list(package.get("expected_aids") or []),
        "push_count":len(payload["pushes"]),
        "daily_manifest_digest":package["manifest"]["digest"],
    }
    candidate=deepcopy(existing_manifest)
    candidate["objects"].append(object_entry)
    candidate["objects"].sort(key=lambda row:(
        str(row.get("bucket_start") or row.get("partition_start") or ""),
        str(row.get("key") or "")))
    candidate["days"].append(day_entry)
    candidate["days"].sort(key=lambda row:row["day"])
    candidate["from_day_taipei"]=candidate["days"][0]["day"]
    candidate["through_day_taipei"]=candidate["days"][-1]["day"]
    candidate["generated_at"]=generated_at
    candidate["pushes"]=sum(int(row.get("pushes",row.get("push_count",0))) for row in candidate["objects"])
    candidate["total_pushes"]=candidate["pushes"]
    candidate["total_objects"]=len(candidate["objects"])
    candidate["total_canonical_bytes"]=sum(int(row.get("bytes_json",0)) for row in candidate["objects"])
    lineage=list(candidate.get("incremental_daily_sources") or [])
    lineage.append({
        "day":day,"manifest_key":package["manifest"]["key"],
        "manifest_digest":package["manifest"]["digest"],
        "object_sha256":object_sha,
    })
    lineage.sort(key=lambda row:row["day"])
    candidate["incremental_daily_sources"]=lineage
    base_hash=str(existing_manifest.get("source_archive_manifest_sha256") or "")
    candidate["source_archive_manifest_sha256"]=digest_bytes(canonical_bytes({
        "base":base_hash,"daily":lineage,
    }))
    validate_month_manifest(candidate,month=month)
    return {
        "changed":True,"manifest":candidate,"manifest_raw":canonical_bytes(candidate),
        "object":{"key":object_key,"raw":object_raw,"sha256":object_sha},
    }


def write_candidate_tree(*, out_dir: Path, candidate: dict[str,Any],
                         manifest_key: str) -> dict[str,Any]:
    if candidate.get("changed") is not True or not isinstance(candidate.get("object"),dict):
        raise MonthlyArchivePipelineError("changed candidate required")
    obj=candidate["object"]
    object_path=out_dir/obj["key"]
    manifest_path=out_dir/manifest_key
    object_path.parent.mkdir(parents=True,exist_ok=True)
    manifest_path.parent.mkdir(parents=True,exist_ok=True)
    object_path.write_bytes(obj["raw"])
    manifest_path.write_bytes(candidate["manifest_raw"])
    return {
        "manifest_path":str(manifest_path),
        "manifest_sha256":digest_bytes(candidate["manifest_raw"]),
        "object_path":str(object_path),"object_sha256":obj["sha256"],
    }


def build_month_candidate_from_state(
    *, month: str, existing_manifest: dict[str,Any], state_root: Path,
    generated_at: str,
) -> dict[str,Any]:
    """Advance a month with every locally verified daily receipt, oldest first."""
    archive_root=state_root/"archive"
    static_root=state_root/"static-public"
    manifest=deepcopy(existing_manifest)
    new_objects=[]
    processed=[]
    skipped=[]
    if not archive_root.is_dir():
        raise MonthlyArchivePipelineError("daily archive state root unavailable")
    for day_dir in sorted(archive_root.iterdir(),key=lambda path:path.name):
        day=day_dir.name
        if not day.startswith(month+"-"):
            continue
        package_path=day_dir/"package.json"
        job_path=day_dir/"archive-job.json"
        try:
            package=json.loads(package_path.read_text(encoding="utf-8"))
            job=json.loads(job_path.read_text(encoding="utf-8"))
        except (OSError,UnicodeDecodeError,json.JSONDecodeError):
            skipped.append({"day":day,"reason":"verified-package-receipt-unavailable"})
            continue
        if not isinstance(package,dict) or not isinstance(job,dict) or job.get("job_verified") is not True:
            skipped.append({"day":day,"reason":"archive-readback-not-verified"})
            continue
        if any(row.get("day")==day for row in manifest.get("days",[])):
            skipped.append({"day":day,"reason":"already-in-month-manifest"})
            continue
        result=advance_month_candidate(
            month=month,existing_manifest=manifest,package=package,
            archive_job=job,object_loader=lambda key:(static_root/key).read_bytes(),
            generated_at=generated_at)
        if result["changed"] is True:
            manifest=result["manifest"]
            new_objects.append(result["object"])
            processed.append(day)
    manifest["generated_at"]=generated_at
    return {
        "changed":bool(new_objects),"manifest":manifest,
        "manifest_raw":canonical_bytes(manifest),"objects":new_objects,
        "processed_days":processed,"skipped_days":skipped,
        "required_existing_objects":[row["key"] for row in existing_manifest.get("objects",[])],
    }


def write_month_candidate_tree(*, out_dir: Path, candidate: dict[str,Any],
                               manifest_key: str) -> dict[str,Any]:
    if not isinstance(candidate.get("manifest_raw"),(bytes,bytearray)):
        raise MonthlyArchivePipelineError("month candidate manifest bytes required")
    for obj in candidate.get("objects",[]):
        target=out_dir/obj["key"]
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(obj["raw"])
    manifest_path=out_dir/manifest_key
    manifest_path.parent.mkdir(parents=True,exist_ok=True)
    manifest_path.write_bytes(candidate["manifest_raw"])
    receipt={
        "schema_version":"holoviewer-ptt-monthly-candidate-v1",
        "status":"MONTHLY_CANDIDATE_READY",
        "changed":candidate.get("changed") is True,
        "processed_days":candidate.get("processed_days",[]),
        "skipped_days":candidate.get("skipped_days",[]),
        "manifest_key":manifest_key,
        "manifest_path":str(manifest_path),
        "manifest_sha256":digest_bytes(bytes(candidate["manifest_raw"])),
        "new_object_count":len(candidate.get("objects",[])),
        "required_existing_objects":candidate.get("required_existing_objects",[]),
        "deployable":False,
        "deploy_blocker":"existing-production-objects-must-be-mirrored-and-verified",
    }
    receipt_path=out_dir/"candidate-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
        encoding="utf-8")
    return receipt


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month",required=True)
    parser.add_argument("--existing-manifest",required=True)
    parser.add_argument("--state-root",required=True)
    parser.add_argument("--out-dir",required=True)
    parser.add_argument("--manifest-key",required=True)
    parser.add_argument("--generated-at",required=True)
    args=parser.parse_args(argv)
    try:
        existing=json.loads(Path(args.existing_manifest).read_text(encoding="utf-8"))
        if not isinstance(existing,dict):
            raise MonthlyArchivePipelineError("existing manifest object required")
        candidate=build_month_candidate_from_state(
            month=args.month,existing_manifest=existing,
            state_root=Path(args.state_root).expanduser(),generated_at=args.generated_at)
        receipt=write_month_candidate_tree(
            out_dir=Path(args.out_dir).expanduser(),candidate=candidate,
            manifest_key=args.manifest_key)
    except (OSError,UnicodeDecodeError,json.JSONDecodeError,MonthlyArchivePipelineError) as exc:
        print(json.dumps({
            "schema_version":"holoviewer-ptt-monthly-candidate-v1",
            "status":"FAILED","failure_code":type(exc).__name__,
            "failure_detail":str(exc),
        },ensure_ascii=False,sort_keys=True))
        return 2
    print(json.dumps(receipt,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
