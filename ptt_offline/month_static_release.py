"""Fail-closed release staging for the shared historical Static Assets worker.

This module only assembles a reviewable directory.  It deliberately contains
no Cloudflare client, credential lookup, subprocess call, or deploy action.
"""
from __future__ import annotations

import argparse
import calendar
import json
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

from .month_static_publish import (
    ARCHIVE_SCHEMA,
    MonthPublishError,
    _digest,
    _http_bytes,
    _package_files,
    _safe_key,
    readback_http,
)


RELEASE_SCHEMA="holoviewer-ptt-static-assets-release-v1"


def _load_json(path: Path, label: str) -> dict[str,Any]:
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise MonthPublishError(f"{label} is unreadable") from exc
    if not isinstance(value,dict):
        raise MonthPublishError(f"{label} must be a JSON object")
    return value


def _copy_exact(source: Path, target: Path, key: str) -> str:
    try:
        source_digest=_digest(source)
    except OSError as exc:
        raise MonthPublishError(f"release source missing: {key}") from exc
    if target.exists():
        if _digest(target)!=source_digest:
            raise MonthPublishError(f"release key collision: {key}")
        return "noop"
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,target)
    if _digest(target)!=source_digest:
        raise MonthPublishError(f"release copy verification failed: {key}")
    return "copied"


def _baseline_files(public: Path, expected: dict[str,Any]) -> tuple[list[str],dict[str,Any]]:
    key=_safe_key(expected.get("manifest_key"))
    manifest_path=public/key
    expected_digest=expected.get("sha256")
    if not isinstance(expected_digest,str) or _digest(manifest_path)!=expected_digest:
        raise MonthPublishError(f"baseline manifest SHA mismatch: {key}")
    manifest=_load_json(manifest_path,"baseline manifest")
    if manifest.get("schema_version")!=ARCHIVE_SCHEMA:
        raise MonthPublishError(f"baseline manifest schema mismatch: {key}")
    objects=manifest.get("objects")
    if not isinstance(objects,list) or manifest.get("total_objects")!=len(objects):
        raise MonthPublishError(f"baseline object count mismatch: {key}")
    keys=[]
    for item in objects:
        if not isinstance(item,dict):
            raise MonthPublishError(f"baseline object entry invalid: {key}")
        object_key=_safe_key(item.get("key"))
        if object_key in keys:
            raise MonthPublishError(f"duplicate baseline object: {object_key}")
        path=public/object_key
        if _digest(path)!=item.get("sha256"):
            raise MonthPublishError(f"baseline object SHA mismatch: {object_key}")
        if isinstance(item.get("bytes_json"),int) and path.stat().st_size!=item["bytes_json"]:
            raise MonthPublishError(f"baseline object size mismatch: {object_key}")
        keys.append(object_key)
    return keys+[key],manifest


def _candidate_specs(spec: dict[str,Any]) -> list[dict[str,Any]]:
    values=spec.get("candidates")
    if values is None and isinstance(spec.get("candidate"),dict):
        values=[spec["candidate"]]
    if (not isinstance(values,list) or not values or
            any(not isinstance(value,dict) for value in values)):
        raise MonthPublishError("release candidates are missing")
    months=[value.get("month") for value in values]
    if len(months)!=len(set(months)):
        raise MonthPublishError("release candidate months are duplicated")
    return values


def stage_release(*, spec_path: Path, baseline_public: list[Path], out_dir: Path,
                  month_package: Path|None=None,
                  month_packages: list[Path]|None=None) -> dict[str,Any]:
    """Create an exact union of reviewed baselines and new month packages."""
    if out_dir.exists():
        raise MonthPublishError("release output already exists")
    spec=_load_json(spec_path,"release specification")
    if spec.get("schema_version")!=RELEASE_SCHEMA:
        raise MonthPublishError("release specification schema mismatch")
    baselines=spec.get("baselines")
    if not isinstance(baselines,list) or len(baselines)!=len(baseline_public):
        raise MonthPublishError("baseline directory count differs from release specification")

    packages=list(month_packages or ([] if month_package is None else [month_package]))
    candidates=_candidate_specs(spec)
    if len(packages)!=len(candidates):
        raise MonthPublishError("month package count differs from release specification")
    candidate_inputs=[]
    for package,candidate in zip(packages,candidates):
        receipt=_load_json(package/"build-receipt.json","month build receipt")
        exact={
            "month":receipt.get("month"),
            "source_sqlite_sha256":receipt.get("source_sqlite_sha256"),
            "source_audit_sha256":receipt.get("source_audit_sha256"),
            "manifest_key":receipt.get("manifest_key"),
            "manifest_digest":receipt.get("manifest_digest"),
            "registration_identity":receipt.get("registration_identity"),
            "article_set_sha256":receipt.get("article_set_sha256"),
            "articles":receipt.get("articles"),
            "pushes":receipt.get("pushes"),
            "objects":receipt.get("objects"),
        }
        if exact!=candidate:
            raise MonthPublishError("month package identity differs from release specification")
        candidate_inputs.append((package,_package_files(package,receipt)))

    public=out_dir/"public"
    copied=noops=0
    baseline_receipts=[]
    all_keys=set()
    for root,expected in zip(baseline_public,baselines):
        if not isinstance(expected,dict):
            raise MonthPublishError("baseline release entry is invalid")
        keys,manifest=_baseline_files(root,expected)
        for key in keys:
            result=_copy_exact(root/key,public/key,key)
            copied+=result=="copied"; noops+=result=="noop"
            all_keys.add(key)
        baseline_receipts.append({
            "manifest_key":expected["manifest_key"],"sha256":expected["sha256"],
            "objects":manifest["total_objects"],"pushes":manifest.get("total_pushes"),
        })

    # Candidate _headers is the reviewed union policy.  Baseline helper files and
    # old _headers are intentionally excluded from the deployable directory.
    for package,candidate_files in candidate_inputs:
        for key in candidate_files:
            result=_copy_exact(package/"public"/key,public/key,key)
            copied+=result=="copied"; noops+=result=="noop"
            all_keys.add(key)

    target=spec.get("target")
    if not isinstance(target,dict) or not target.get("worker_name"):
        raise MonthPublishError("release target is invalid")
    wrangler={
        "name":target["worker_name"],
        "compatibility_date":spec.get("compatibility_date","2026-10-18"),
        "assets":{"directory":"./public","not_found_handling":"404-page"},
    }
    (out_dir/"wrangler.jsonc").write_text(
        json.dumps(wrangler,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    sizes={key:(public/key).stat().st_size for key in all_keys}
    largest_key=max(sizes,key=sizes.get)
    release={
        "schema_version":RELEASE_SCHEMA,"status":"PASS",
        "target":target,"baselines":baseline_receipts,"candidates":candidates,
        "deployable_files":len(all_keys),"copied_files":copied,"noop_files":noops,
        "deployable_bytes":sum(sizes.values()),"largest_asset_key":largest_key,
        "largest_asset_bytes":sizes[largest_key],
        "headers_sha256":_digest(public/"_headers"),
        "production_execution":False,"cloudflare_execution":False,
        "owner_command":(
            "OWNER_LOCAL=YES GITHUB_ACTIONS=NO CI_DEPLOY=NO npx wrangler deploy "
            f"--config {out_dir.resolve()}/wrangler.jsonc"),
    }
    receipt_path=out_dir/"release-receipt.json"
    receipt_path.write_text(
        json.dumps(release,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    release["receipt_sha256"]=sha256(receipt_path.read_bytes()).hexdigest()
    return release


def verify_release_http(*, spec_path: Path, observed_at: str) -> dict[str,Any]:
    """Verify the candidate and preserved baselines from the real public URL."""
    spec=_load_json(spec_path,"release specification")
    if spec.get("schema_version")!=RELEASE_SCHEMA:
        raise MonthPublishError("release specification schema mismatch")
    target=spec.get("target")
    candidates=_candidate_specs(spec)
    baselines=spec.get("baselines")
    if not isinstance(target,dict) or not isinstance(baselines,list):
        raise MonthPublishError("release specification is incomplete")
    base_url=target.get("base_url")
    if not isinstance(base_url,str) or not base_url.startswith("https://"):
        raise MonthPublishError("production readback requires an HTTPS base URL")

    preserved=[]
    for expected in baselines:
        key=_safe_key(expected.get("manifest_key"))
        raw=_http_bytes(base_url,key)
        if sha256(raw).hexdigest()!=expected.get("sha256"):
            raise MonthPublishError(f"production baseline manifest changed: {key}")
        try:
            manifest=json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MonthPublishError(f"production baseline manifest is invalid: {key}") from exc
        verified=0
        for item in manifest.get("objects",[]):
            object_key=_safe_key(item.get("key"))
            if sha256(_http_bytes(base_url,object_key)).hexdigest()!=item.get("sha256"):
                raise MonthPublishError(f"production baseline object changed: {object_key}")
            verified+=1
        if verified!=manifest.get("total_objects"):
            raise MonthPublishError(f"production baseline object count changed: {key}")
        preserved.append({"manifest_key":key,"sha256":expected["sha256"],
                          "objects_verified":verified})

    candidate_readbacks=[]
    representative=[]
    for candidate in candidates:
        readback=readback_http(
            base_url=base_url,
            registration_key=f"ptt/v1/registrations/{candidate['month']}.json",
            job_id=f"production-{candidate['month']}-{candidate['registration_identity'][:16]}",
            observed_at=observed_at,target_identity=target["worker_name"],
            expected_registration_identity=candidate["registration_identity"])
        if not readback.get("job_verified"):
            raise MonthPublishError("production candidate full readback failed")
        candidate_readbacks.append(readback)

        manifest_raw=_http_bytes(base_url,candidate["manifest_key"])
        if sha256(manifest_raw).hexdigest()!=candidate["manifest_digest"]:
            raise MonthPublishError("production candidate manifest digest mismatch")
        manifest=json.loads(manifest_raw)
        year,month=map(int,candidate["month"].split("-"))
        last=calendar.monthrange(year,month)[1]
        wanted={f"{candidate['month']}-01",f"{candidate['month']}-15",
                f"{candidate['month']}-{last:02d}"}
        for item in manifest["objects"]:
            if not wanted:
                break
            raw=_http_bytes(base_url,item["key"])
            body=json.loads(raw)
            days={row.get("coverage_day") for row in body.get("pushes",[])}
            for day in sorted(wanted&days):
                representative.append({"day":day,"key":item["key"],
                                       "sha256":item["sha256"]})
                wanted.remove(day)
        if wanted:
            raise MonthPublishError("early/mid/late production samples are incomplete")

        first_key=manifest["objects"][0]["key"]
        header_contracts=(
            (candidate["manifest_key"],"application/json","no-cache"),
            (first_key,"application/json","public, max-age=0, must-revalidate"),
        )
        for key,expected_type,expected_cache in header_contracts:
            url=base_url.rstrip("/")+"/"+quote(_safe_key(key),safe="/")
            with urlopen(url,timeout=10) as response:
                if expected_type not in response.headers.get("Content-Type",""):
                    raise MonthPublishError(f"production content type mismatch: {key}")
                if response.headers.get("Access-Control-Allow-Origin")!="*":
                    raise MonthPublishError(f"production CORS header mismatch: {key}")
                if response.headers.get("Cache-Control")!=expected_cache:
                    raise MonthPublishError(f"production cache header mismatch: {key}")
                if response.headers.get("X-Content-Type-Options")!="nosniff":
                    raise MonthPublishError(f"production nosniff header mismatch: {key}")
                if response.headers.get("Content-Security-Policy") is not None:
                    raise MonthPublishError(f"production CSP baseline changed: {key}")
    missing_url=base_url.rstrip("/")+"/ptt/v1/manifests/static-assets-full-1900-01.json"
    try:
        urlopen(missing_url,timeout=10)
    except HTTPError as exc:
        if exc.code!=404:
            raise MonthPublishError("production missing-object response is not 404") from exc
    else:
        raise MonthPublishError("production missing-object response is not 404")

    return {"schema_version":RELEASE_SCHEMA,"status":"PASS","observed_at":observed_at,
            "target":target,"baselines":preserved,"candidates":candidates,
            "candidate_readbacks":candidate_readbacks,
            "representative_days":representative,
            "cors_verified":True,"content_type_verified":True,"missing_object_404":True,
            "production_execution":False}


def main(argv: list[str]|None=None) -> int:
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest="command",required=True)
    stage=sub.add_parser("stage")
    stage.add_argument("--spec",required=True,type=Path)
    stage.add_argument("--month-package",required=True,type=Path,action="append")
    stage.add_argument("--baseline-public",required=True,type=Path,action="append")
    stage.add_argument("--out",required=True,type=Path)
    verify=sub.add_parser("verify-http")
    verify.add_argument("--spec",required=True,type=Path)
    verify.add_argument("--observed-at",required=True)
    verify.add_argument("--receipt",type=Path)
    args=parser.parse_args(argv)
    if args.command=="stage":
        result=stage_release(spec_path=args.spec,month_packages=args.month_package,
                             baseline_public=args.baseline_public,out_dir=args.out)
    else:
        result=verify_release_http(spec_path=args.spec,observed_at=args.observed_at)
        if args.receipt:
            args.receipt.write_text(
                json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",
                encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
