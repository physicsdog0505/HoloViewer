"""Prepare and release a dedicated monthly PTT Static Assets tree.

Preparation mirrors and verifies every currently published immutable object,
then appends locally verified daily closeouts. Deployment is explicit and has a
readback/rollback boundary. Importing this module performs no network or writes.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable
from urllib.request import Request, urlopen

from .monthly_archive_pipeline import (
    MonthlyArchivePipelineError,
    build_month_candidate_from_state,
    canonical_bytes,
    digest_bytes,
    validate_month_manifest,
    write_month_candidate_tree,
)


class MonthlyArchiveReleaseError(RuntimeError):
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


def _safe_key(key: object) -> str:
    if (not isinstance(key,str) or key.startswith("/") or ".." in key.split("/") or
            not key.startswith("ptt/v1/") or not key.endswith(".json")):
        raise MonthlyArchiveReleaseError("unsafe Static Assets key")
    return key


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp,path)


def _validate_object(raw: bytes, item: dict[str,Any]) -> None:
    if digest_bytes(raw)!=item.get("sha256"):
        raise MonthlyArchiveReleaseError("mirrored object sha mismatch")
    try:
        payload=json.loads(raw)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise MonthlyArchiveReleaseError("mirrored object JSON invalid") from exc
    count=item.get("pushes",item.get("push_count"))
    start=item.get("bucket_start",item.get("partition_start"))
    end=item.get("bucket_end",item.get("partition_end"))
    if (not isinstance(payload,dict) or payload.get("schema_version")!="ptt-r2-archive-v1" or
            not isinstance(payload.get("pushes"),list) or len(payload["pushes"])!=count or
            payload.get("bucket_start",payload.get("partition_start"))!=start or
            payload.get("bucket_end",payload.get("partition_end"))!=end):
        raise MonthlyArchiveReleaseError("mirrored object contract mismatch")


def prepare_release(
    *, month: str, base_url: str, manifest_key: str, target: str,
    state_root: Path, release_root: Path, generated_at: str,
    fetcher: Callable[[str],bytes],
    expected_manifest_sha256: str | None=None,
) -> dict[str,Any]:
    """Create candidate and rollback trees without deploying either one."""
    if not base_url.startswith("https://") or not target:
        raise MonthlyArchiveReleaseError("sanitized monthly release target required")
    release_root=release_root.expanduser().resolve()
    protected={Path("/").resolve(),Path.home().resolve(),state_root.expanduser().resolve()}
    if release_root in protected or len(release_root.parts)<3:
        raise MonthlyArchiveReleaseError("unsafe monthly release root")
    manifest_key=_safe_key(manifest_key)
    manifest_raw=fetcher(base_url.rstrip("/")+"/"+manifest_key)
    if (expected_manifest_sha256 is not None and
            digest_bytes(manifest_raw)!=expected_manifest_sha256):
        raise MonthlyArchiveReleaseError("production manifest changed since approval")
    try:
        current=json.loads(manifest_raw)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise MonthlyArchiveReleaseError("production manifest JSON invalid") from exc
    if not isinstance(current,dict):
        raise MonthlyArchiveReleaseError("production manifest object required")
    try:
        validate_month_manifest(current,month=month)
    except MonthlyArchivePipelineError as exc:
        raise MonthlyArchiveReleaseError("production manifest contract invalid") from exc

    candidate_root=release_root/"candidate"/"public"
    rollback_root=release_root/"rollback"/"public"
    cache_root=release_root/"cache"/"public"
    for transient in (candidate_root.parent,rollback_root.parent):
        if transient.exists():
            shutil.rmtree(transient)
    candidate_root.mkdir(parents=True)
    rollback_root.mkdir(parents=True)
    cache_root.mkdir(parents=True,exist_ok=True)
    mirrored=[]
    fetched=0
    reused=0
    for item in current["objects"]:
        key=_safe_key(item.get("key"))
        cached=cache_root/key
        raw=None
        if cached.is_file():
            probe=cached.read_bytes()
            try:
                _validate_object(probe,item)
            except MonthlyArchiveReleaseError:
                pass
            else:
                raw=probe
                reused+=1
        if raw is None:
            raw=fetcher(base_url.rstrip("/")+"/"+key)
            _validate_object(raw,item)
            _write(cached,raw)
            fetched+=1
        _write(candidate_root/key,raw)
        _write(rollback_root/key,raw)
        mirrored.append(key)
    _write(candidate_root/manifest_key,manifest_raw)
    _write(rollback_root/manifest_key,manifest_raw)
    _write(candidate_root/"_headers",_HEADERS)
    _write(rollback_root/"_headers",_HEADERS)

    candidate=build_month_candidate_from_state(
        month=month,existing_manifest=current,state_root=state_root,
        generated_at=generated_at)
    write_month_candidate_tree(
        out_dir=candidate_root,candidate=candidate,manifest_key=manifest_key)
    receipt={
        "schema_version":"holoviewer-ptt-monthly-release-v1",
        "status":"MONTHLY_RELEASE_READY",
        "month":month,"target":target,"base_url":base_url,
        "manifest_key":manifest_key,
        "previous_manifest_sha256":digest_bytes(manifest_raw),
        "candidate_manifest_sha256":digest_bytes(candidate["manifest_raw"]),
        "mirrored_existing_objects":len(mirrored),
        "fetched_existing_objects":fetched,
        "reused_cached_objects":reused,
        "new_objects":len(candidate["objects"]),
        "processed_days":candidate["processed_days"],
        "candidate_public":str(candidate_root),
        "rollback_public":str(rollback_root),
        "deployable":candidate["changed"] is True,
    }
    _write(release_root/"release-receipt.json",
           json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2).encode("utf-8")+b"\n")
    return receipt


def _wrangler_config(*, root: Path, target: str) -> Path:
    config=root.parent/"wrangler.json"
    _write(config,canonical_bytes({
        "name":target,"compatibility_date":"2026-11-14",
        "assets":{"directory":str(root),"not_found_handling":"404-page"},
    }))
    return config


def deploy_prepared_release(
    *, receipt: dict[str,Any], wrangler_command: list[str],
    fetcher: Callable[[str],bytes],
    runner: Callable[[list[str]],subprocess.CompletedProcess[str]] | None=None,
) -> dict[str,Any]:
    """Deploy exact prepared bytes, verify readback, and rollback on uncertainty."""
    if receipt.get("status")!="MONTHLY_RELEASE_READY" or receipt.get("deployable") is not True:
        raise MonthlyArchiveReleaseError("deployable prepared receipt required")
    if not wrangler_command or not all(isinstance(x,str) and x for x in wrangler_command):
        raise MonthlyArchiveReleaseError("wrangler command required")
    candidate_root=Path(receipt["candidate_public"])
    rollback_root=Path(receipt["rollback_public"])
    target=str(receipt["target"])
    base=str(receipt["base_url"]).rstrip("/")
    manifest_key=_safe_key(receipt["manifest_key"])
    execute=runner or (lambda command:subprocess.run(
        command,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False))

    def deploy(root: Path) -> subprocess.CompletedProcess[str]:
        config=_wrangler_config(root=root,target=target)
        result=execute([*wrangler_command,"deploy","--config",str(config)])
        if result.returncode!=0:
            raise MonthlyArchiveReleaseError("Static Assets deploy returned nonzero")
        return result

    active=fetcher(base+"/"+manifest_key)
    if digest_bytes(active)!=receipt.get("previous_manifest_sha256"):
        raise MonthlyArchiveReleaseError(
            "production manifest changed after release preparation")
    deploy(candidate_root)
    try:
        remote=fetcher(base+"/"+manifest_key)
        if digest_bytes(remote)!=receipt["candidate_manifest_sha256"]:
            raise MonthlyArchiveReleaseError("candidate manifest readback mismatch")
        manifest=json.loads(remote)
        for item in manifest.get("objects",[]):
            if item.get("source_daily_manifest_digest"):
                raw=fetcher(base+"/"+_safe_key(item.get("key")))
                _validate_object(raw,item)
    except Exception as exc:
        try:
            deploy(rollback_root)
            restored=fetcher(base+"/"+manifest_key)
            rollback_verified=(digest_bytes(restored)==receipt["previous_manifest_sha256"])
        except Exception:
            rollback_verified=False
        raise MonthlyArchiveReleaseError(
            "candidate readback failed; rollback_verified="+str(rollback_verified).lower()) from exc
    return {
        **deepcopy(receipt),"status":"MONTHLY_RELEASE_DEPLOYED",
        "remote_readback_verified":True,"rollback_used":False,
    }


def http_fetch(url: str, *, timeout: int=30) -> bytes:
    request=Request(url,headers={"Accept":"application/json","User-Agent":"holoviewer-monthly-release/1"})
    with urlopen(request,timeout=timeout) as response:
        if response.status!=200:
            raise MonthlyArchiveReleaseError("Static Assets readback HTTP status mismatch")
        return response.read()


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="cmd",required=True)
    prepare=sub.add_parser("prepare")
    prepare.add_argument("--month",required=True)
    prepare.add_argument("--base-url",required=True)
    prepare.add_argument("--manifest-key",required=True)
    prepare.add_argument("--target",required=True)
    prepare.add_argument("--state-root",required=True)
    prepare.add_argument("--release-root",required=True)
    prepare.add_argument("--generated-at",required=True)
    prepare.add_argument("--expected-manifest-sha256",required=True)
    deploy=sub.add_parser("deploy")
    deploy.add_argument("--receipt",required=True)
    deploy.add_argument("--wrangler-command-json",default='["npx","wrangler"]')
    update=sub.add_parser("update")
    update.add_argument("--month",required=True)
    update.add_argument("--base-url",required=True)
    update.add_argument("--manifest-key",required=True)
    update.add_argument("--target",required=True)
    update.add_argument("--state-root",required=True)
    update.add_argument("--release-root",required=True)
    update.add_argument("--generated-at")
    update.add_argument("--wrangler-command-json",default='["npx","wrangler"]')
    args=parser.parse_args(argv)
    try:
        if args.cmd=="prepare":
            body=prepare_release(
                month=args.month,base_url=args.base_url,
                manifest_key=args.manifest_key,target=args.target,
                state_root=Path(args.state_root).expanduser(),
                release_root=Path(args.release_root).expanduser(),
                generated_at=(args.generated_at or datetime.now(timezone.utc).replace(
                    microsecond=0).isoformat().replace("+00:00","Z")),fetcher=http_fetch,
                expected_manifest_sha256=args.expected_manifest_sha256)
        elif args.cmd=="deploy":
            receipt=json.loads(Path(args.receipt).read_text(encoding="utf-8"))
            command=json.loads(args.wrangler_command_json)
            if not isinstance(receipt,dict) or not isinstance(command,list):
                raise MonthlyArchiveReleaseError("release receipt or wrangler command invalid")
            body=deploy_prepared_release(
                receipt=receipt,wrangler_command=command,fetcher=http_fetch)
        else:
            manifest_url=args.base_url.rstrip("/")+"/"+_safe_key(args.manifest_key)
            locked=http_fetch(manifest_url)
            receipt=prepare_release(
                month=args.month,base_url=args.base_url,
                manifest_key=args.manifest_key,target=args.target,
                state_root=Path(args.state_root).expanduser(),
                release_root=Path(args.release_root).expanduser(),
                generated_at=(args.generated_at or datetime.now(timezone.utc).replace(
                    microsecond=0).isoformat().replace("+00:00","Z")),fetcher=http_fetch,
                expected_manifest_sha256=digest_bytes(locked))
            command=json.loads(args.wrangler_command_json)
            if not isinstance(command,list):
                raise MonthlyArchiveReleaseError("wrangler command invalid")
            if receipt.get("deployable") is not True:
                body={**receipt,"status":"MONTHLY_RELEASE_ALREADY_CURRENT"}
            else:
                body=deploy_prepared_release(
                    receipt=receipt,wrangler_command=command,fetcher=http_fetch)
    except (OSError,ValueError,MonthlyArchiveReleaseError) as exc:
        print(json.dumps({
            "schema_version":"holoviewer-ptt-monthly-release-v1",
            "status":"FAILED","failure_code":type(exc).__name__,
            "failure_detail":str(exc),
        },ensure_ascii=False,sort_keys=True))
        return 2
    print(json.dumps(body,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
