"""Production-gated daily previous-day PTT closeout runtime.

This runner composes the already-reviewed contracts:
- #48 daily finalization / exact-AID coverage classification;
- #160 immutable Workers Static Assets package + readback evidence.

It is intentionally fail-closed. Expected-AID authority must come from an
external reviewed producer. A bounded repair command is optional; when present
it receives only the exact missing AID/source ranges on stdin, and the runner
always re-reads Collector coverage afterward instead of trusting command output.

The runtime can build only, or (with explicit config deploy=true) execute an
assets-only Wrangler deploy against a dedicated Static Assets project. It never
touches holoviewer-public-api, D1, R2, Publisher checkpoints, or Collector
process lifecycle.
"""
from __future__ import annotations

import argparse
import fcntl
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
from datetime import datetime
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .collector_integrity_export import export_article_integrity
from .collector_source_preview import open_source
from .daily_ptt_finalization import finalize_day, previous_taipei_day
from .daily_static_assets_archive import (
    build_archive_delivery_evidence,
    build_daily_static_package,
    compute_source_snapshot_hash,
    prepare_static_assets_delivery,
    verify_http_readback,
)
from .r2_archive_export import export_archive

CONFIG_SCHEMA="holoviewer-ptt-daily-history-runtime-config-v1"
TPE=ZoneInfo("Asia/Taipei")
SAFE_TARGET=re.compile(r"^[A-Za-z0-9._-]{1,80}$")
UUID_RE=re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",re.I)


class DailyHistoryRuntimeError(RuntimeError):
    pass


class RepairCommandFailed(DailyHistoryRuntimeError):
    pass


class StaticAssetsDeployFailed(DailyHistoryRuntimeError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    os.replace(tmp,path)


def _load_json(path: Path) -> dict[str,Any]:
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise DailyHistoryRuntimeError("invalid JSON evidence file") from exc
    if not isinstance(value,dict):
        raise DailyHistoryRuntimeError("JSON evidence object required")
    return value


def load_config(path: Path) -> dict[str,Any]:
    body=_load_json(path)
    if body.get("schema_version")!=CONFIG_SCHEMA:
        raise DailyHistoryRuntimeError("unsupported daily history runtime config")
    collector=Path(str(body.get("collector_source") or "")).expanduser()
    state=Path(str(body.get("state_root") or "")).expanduser()
    if not collector.is_file():
        raise DailyHistoryRuntimeError("Collector SQLite unavailable")
    if not str(state):
        raise DailyHistoryRuntimeError("state_root required")
    target=body.get("static_target")
    if not isinstance(target,str) or not SAFE_TARGET.fullmatch(target):
        raise DailyHistoryRuntimeError("sanitized Static Assets target required")
    base_url=body.get("base_url")
    if not isinstance(base_url,str) or not base_url.startswith("https://"):
        raise DailyHistoryRuntimeError("https base_url required")
    body["_collector_path"]=collector.resolve()
    body["_state_path"]=state.resolve()
    return body


def _expand_command(raw: object, *, day: str, source: Path) -> list[str]:
    if not isinstance(raw,list) or not raw or not all(isinstance(x,str) and x for x in raw):
        raise DailyHistoryRuntimeError("command must be a non-empty string array")
    return [x.replace("{day}",day).replace("{source}",str(source)) for x in raw]


def _run_json_command(command: list[str], *, timeout: int, stdin: dict[str,Any] | None=None) -> dict[str,Any]:
    try:
        result=subprocess.run(
            command,
            input=(json.dumps(stdin,ensure_ascii=False,separators=(",",":"))+"\n") if stdin is not None else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise DailyHistoryRuntimeError("evidence producer command failed") from exc
    if result.returncode!=0:
        raise DailyHistoryRuntimeError("evidence producer command returned nonzero")
    try:
        body=json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DailyHistoryRuntimeError("evidence producer did not return one JSON object") from exc
    if not isinstance(body,dict):
        raise DailyHistoryRuntimeError("evidence producer JSON object required")
    return body


def load_expected_contract(config: dict[str,Any], *, day: str) -> dict[str,Any]:
    source: Path=config["_collector_path"]
    if isinstance(config.get("expected_contract_path"),str):
        path=Path(config["expected_contract_path"].replace("{day}",day)).expanduser()
        body=_load_json(path)
    else:
        command=_expand_command(config.get("expected_contract_command"),day=day,source=source)
        body=_run_json_command(command,timeout=int(config.get("expected_timeout_seconds",60)))
    if body.get("schema_version")!="holoviewer-ptt-expected-aids-v1":
        raise DailyHistoryRuntimeError("expected-AID contract schema mismatch")
    if body.get("day")!=day:
        raise DailyHistoryRuntimeError("expected-AID contract day mismatch")
    return body


def coverage_from_collector(*, source: Path, day: str, expected_contract: dict[str,Any]) -> dict[str,dict[str,Any]]:
    rows=expected_contract.get("expected")
    if not isinstance(rows,list):
        return {}
    aids=[]
    for row in rows:
        if isinstance(row,dict) and isinstance(row.get("aid"),str):
            aid=row["aid"].lstrip("#")
            if aid not in aids:
                aids.append(aid)
    result={}
    with open_source(str(source)) as db:
        for aid in aids:
            try:
                evidence=export_article_integrity(db,day=day,aid=aid)
            except Exception:
                continue
            result[aid]=evidence["source_coverage"]
    return result


def make_repair_executor(config: dict[str,Any], *, day: str) -> Callable[[dict[str,Any]],dict[str,Any]] | None:
    raw=config.get("repair_command")
    if raw is None:
        return None
    source: Path=config["_collector_path"]
    command=_expand_command(raw,day=day,source=source)
    timeout=int(config.get("repair_timeout_seconds",600))
    if timeout<1 or timeout>1800:
        raise DailyHistoryRuntimeError("repair timeout outside 1..1800s")

    def execute(request: dict[str,Any]) -> dict[str,Any]:
        if request.get("mode")!="bounded-missing-ranges-only":
            raise RepairCommandFailed("unbounded repair request rejected")
        try:
            subprocess_result=subprocess.run(
                command,
                input=json.dumps(request,ensure_ascii=False,separators=(",",":"))+"\n",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                env={**os.environ,
                     "HOLOVIEWER_REPAIR_DAY":str(request["day"]),
                     "HOLOVIEWER_REPAIR_AID":str(request["aid"]),
                     "HOLOVIEWER_COLLECTOR_SOURCE":str(source)},
            )
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise RepairCommandFailed("bounded repair command failed") from exc
        if subprocess_result.returncode!=0:
            raise RepairCommandFailed("bounded repair command nonzero")
        # Never trust command stdout as completeness authority. Re-read the
        # exact AID from the Collector and let the same #48 classifier decide.
        with open_source(str(source)) as db:
            evidence=export_article_integrity(
                db,day=str(request["day"]),aid=str(request["aid"]))
        return evidence["source_coverage"]

    return execute


def _daily_source_objects(*, source: Path, day: str, work_dir: Path,
                          expected_aids: set[str]) -> list[tuple[str,bytes]]:
    archive_root=work_dir/"source-archive"
    with open_source(str(source)) as db:
        receipt=export_archive(db,from_day=day,through_day=day,out_dir=archive_root)
    objects=[]
    for item in receipt.get("objects",[]):
        key=item.get("key")
        if not isinstance(key,str) or not key.endswith(".json.gz"):
            raise DailyHistoryRuntimeError("unexpected archive object key")
        target=archive_root/key
        try:
            with gzip.open(target,"rb") as handle:
                raw=handle.read()
            if sha256(raw).hexdigest()!=item.get("sha256"):
                raise DailyHistoryRuntimeError("source archive object SHA mismatch")
            payload=json.loads(raw)
        except (OSError,UnicodeDecodeError,json.JSONDecodeError) as exc:
            raise DailyHistoryRuntimeError("invalid daily source archive object") from exc
        pushes=payload.get("pushes")
        if not isinstance(pushes,list):
            raise DailyHistoryRuntimeError("daily source object pushes missing")
        for row in pushes:
            if not isinstance(row,dict):
                raise DailyHistoryRuntimeError("invalid source push row")
            aid=str(row.get("aid") or "").lstrip("#")
            if aid not in expected_aids:
                raise DailyHistoryRuntimeError("daily source contains unexpected AID")
            if row.get("floor") is None or row.get("floor_quality")!="per-thread-ordinal":
                raise DailyHistoryRuntimeError("VERIFIED_COMPLETE archive requires authoritative per-thread floor")
            row["coverage_day"]=day
            row["coverage_status"]="COMPLETE"
            row["finalized"]=True
        canonical=_canonical_bytes(payload)
        logical=key.removesuffix(".gz")
        objects.append((logical,canonical))
    if not objects:
        raise DailyHistoryRuntimeError("no archive objects for finalized day")
    return objects


_HEADERS=(
    "/ptt/v1/history/*\n"
    "  Content-Type: application/json\n"
    "  Cache-Control: public, max-age=31536000, immutable\n"
    "  Access-Control-Allow-Origin: *\n"
    "  X-Content-Type-Options: nosniff\n\n"
    "/ptt/v1/manifests/daily/*\n"
    "  Content-Type: application/json; charset=utf-8\n"
    "  Cache-Control: no-cache\n"
    "  Access-Control-Allow-Origin: *\n"
    "  X-Content-Type-Options: nosniff\n"
).encode("utf-8")


def ensure_static_root(*, state_root: Path, target: str) -> tuple[Path,Path]:
    public=state_root/"static-public"
    public.mkdir(parents=True,exist_ok=True)
    headers=public/"_headers"
    if headers.exists() and headers.read_bytes()!=_HEADERS:
        raise DailyHistoryRuntimeError("Static Assets _headers drift")
    if not headers.exists():
        headers.write_bytes(_HEADERS)
    config_path=state_root/"wrangler.daily-history.json"
    config={
        "name":target,
        "compatibility_date":"2026-10-21",
        "assets":{"directory":"./static-public","not_found_handling":"404-page"},
    }
    raw=json.dumps(config,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    if config_path.exists() and config_path.read_text(encoding="utf-8")!=raw:
        raise DailyHistoryRuntimeError("Wrangler Static Assets config drift")
    if not config_path.exists():
        config_path.write_text(raw,encoding="utf-8")
    return public,config_path


def _http_fetcher(base_url: str, *, timeout: int=20) -> Callable[[str],bytes]:
    base=base_url.rstrip("/")
    def fetch(key: str) -> bytes:
        url=base+"/"+"/".join(quote(part,safe="") for part in key.split("/"))
        req=Request(url,headers={"Accept":"application/json","Cache-Control":"no-cache",
                                "User-Agent":"HoloViewer-Archive-Readback/1"})
        try:
            with urlopen(req,timeout=timeout) as response:
                if response.status!=200:
                    raise DailyHistoryRuntimeError("Static Assets readback HTTP status mismatch")
                return response.read()
        except HTTPError as exc:
            raise DailyHistoryRuntimeError("Static Assets readback unavailable") from exc
    return fetch


def _deploy_static_assets(*, state_root: Path, config_path: Path,
                          wrangler_command: list[str]) -> dict[str,Any]:
    command=list(wrangler_command)+["deploy","--config",str(config_path)]
    attempted=datetime.now(TPE).isoformat()
    try:
        result=subprocess.run(
            command,cwd=state_root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            timeout=600,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise StaticAssetsDeployFailed("Static Assets deploy execution failed") from exc
    log_path=state_root/"last-static-assets-deploy.log"
    log_path.write_text(result.stdout or "",encoding="utf-8")
    if result.returncode!=0:
        raise StaticAssetsDeployFailed("Static Assets deploy returned nonzero")
    match=UUID_RE.search(result.stdout or "")
    return {
        "attempted_at":attempted,
        "succeeded_at":datetime.now(TPE).isoformat(),
        "version_id":match.group(0) if match else None,
    }


def _previous_attempt(path: Path) -> dict[str,Any] | None:
    if not path.is_file():
        return None
    try:
        body=_load_json(path)
    except DailyHistoryRuntimeError:
        return None
    return body


def _stable_finalization_material(receipt: object) -> object:
    """Compare finalization semantics while ignoring observation-only identity.

    #48 receipts intentionally include observed_at in evidence_digest. A daily
    closeout rerun minutes later must not mint a new historical package merely
    because the observation clock changed. Coverage digests / expected-set
    evidence still participate, so any source/authority change invalidates
    reuse.
    """
    if not isinstance(receipt,dict):
        return None
    body=json.loads(json.dumps(receipt))
    body.pop("observed_at",None)
    body.pop("evidence_digest",None)
    return body


def _reuse_verified_finalization(path: Path, current: dict[str,Any]) -> dict[str,Any]:
    if current.get("state")!="VERIFIED_COMPLETE" or not path.is_file():
        return current
    try:
        previous=_load_json(path)
    except DailyHistoryRuntimeError:
        return current
    if (previous.get("state")=="VERIFIED_COMPLETE"
            and previous.get("archive_ready") is True
            and _stable_finalization_material(previous)
                ==_stable_finalization_material(current)):
        return previous
    return current


def run_closeout(*, config: dict[str,Any], day: str | None=None) -> dict[str,Any]:
    source: Path=config["_collector_path"]
    state_root: Path=config["_state_path"]
    state_root.mkdir(parents=True,exist_ok=True)
    target_day=day or previous_taipei_day()
    expected=load_expected_contract(config,day=target_day)
    coverage=coverage_from_collector(source=source,day=target_day,expected_contract=expected)
    repair_executor=make_repair_executor(config,day=target_day)
    finalization=finalize_day(
        day=target_day,
        expected_contract=expected,
        coverage_by_aid=coverage,
        repair_executor=repair_executor,
        observed_at=datetime.now(TPE).isoformat(),
    )
    finalization_path=state_root/"finalization"/f"{target_day}.json"
    finalization=_reuse_verified_finalization(finalization_path,finalization)
    _atomic_json(finalization_path,finalization)
    _atomic_json(state_root/"latest-finalization.json",finalization)

    if finalization.get("state")!="VERIFIED_COMPLETE":
        return {
            "status":"NOT_ARCHIVE_READY",
            "day":target_day,
            "state":finalization.get("state"),
            "finalization_receipt":str(finalization_path),
            "archive_deployed":False,
        }

    expected_aids={str(aid).lstrip("#") for aid in finalization["expected_set"]["expected_aids"]}
    with tempfile.TemporaryDirectory(prefix=f"holoviewer-{target_day}-",dir=state_root) as tmp:
        source_objects=_daily_source_objects(
            source=source,day=target_day,work_dir=Path(tmp),expected_aids=expected_aids)

    public,wrangler_config=ensure_static_root(
        state_root=state_root,target=str(config["static_target"]))
    source_revision=f"collector-finalized-{target_day}-v1"
    source_hash=compute_source_snapshot_hash(
        finalization_receipt=finalization,
        source_revision=source_revision,
        source_objects=source_objects,
    )
    package=build_daily_static_package(
        finalization_receipt=finalization,
        source_revision=source_revision,
        source_hash=source_hash,
        source_objects=source_objects,
        out_dir=public,
    )
    package_path=state_root/"archive"/target_day/"package.json"
    _atomic_json(package_path,package)

    prior_path=state_root/"archive"/target_day/"archive-job.json"
    prior=_previous_attempt(prior_path)
    if (prior and prior.get("job_verified") is True
            and isinstance(prior.get("manifest"),dict)
            and prior["manifest"].get("digest")==package["manifest"]["digest"]):
        _atomic_json(state_root/"latest-archive-job.json",prior)
        return {
            "status":"ALREADY_VERIFIED",
            "day":target_day,
            "manifest_digest":package["manifest"]["digest"],
            "archive_deployed":False,
            "archive_job":str(prior_path),
        }

    previous_attempt=int(prior.get("attempt_count") or 0) if prior else 0
    attempt_count=previous_attempt+1
    job_id=f"archive-{target_day}-{package['manifest']['digest'][:12]}-a{attempt_count}"
    plan=prepare_static_assets_delivery(
        package=package,job_id=job_id,target_identity=str(config["static_target"]))
    _atomic_json(state_root/"archive"/target_day/"delivery-plan.json",plan)

    if config.get("deploy") is not True:
        return {
            "status":"READY_TO_DEPLOY",
            "day":target_day,
            "manifest_digest":package["manifest"]["digest"],
            "object_count":package["object_count"],
            "push_count":package["push_count"],
            "archive_deployed":False,
            "package":str(package_path),
        }

    raw_wrangler=config.get("wrangler_command",["npx","wrangler"])
    if not isinstance(raw_wrangler,list) or not raw_wrangler or not all(isinstance(x,str) for x in raw_wrangler):
        raise DailyHistoryRuntimeError("wrangler_command must be a string array")

    attempted_at=datetime.now(TPE).isoformat()
    try:
        deploy=_deploy_static_assets(
            state_root=state_root,config_path=wrangler_config,
            wrangler_command=raw_wrangler)
    except StaticAssetsDeployFailed:
        evidence=build_archive_delivery_evidence(
            package=package,finalization_receipt=finalization,job_id=job_id,
            job_status="failed",attempted_at=attempted_at,succeeded_at=None,
            attempt_count=attempt_count,uploaded_count=0,readback_receipt=None,
            error_code="static-assets-deploy-failed",
            target_identity=str(config["static_target"]),
        )
        _atomic_json(prior_path,evidence)
        _atomic_json(state_root/"latest-archive-job.json",evidence)
        raise

    readback=verify_http_readback(
        package=package,job_id=job_id,
        fetch_bytes=_http_fetcher(str(config["base_url"]),
                                  timeout=int(config.get("readback_timeout_seconds",20))),
        observed_at=datetime.now(TPE).isoformat(),
        target_identity=str(config["static_target"]),
    )
    evidence=build_archive_delivery_evidence(
        package=package,finalization_receipt=finalization,job_id=job_id,
        job_status="succeeded",attempted_at=deploy["attempted_at"],
        succeeded_at=deploy["succeeded_at"],attempt_count=attempt_count,
        uploaded_count=package["object_count"],readback_receipt=readback,
        error_code=None if readback.get("job_verified") else "static-assets-readback-failed",
        target_identity=str(config["static_target"]),
    )
    _atomic_json(prior_path,evidence)
    _atomic_json(state_root/"latest-archive-job.json",evidence)
    if evidence.get("job_verified") is not True:
        raise DailyHistoryRuntimeError("Static Assets deploy readback did not verify")
    return {
        "status":"VERIFIED_COMPLETE_PUBLISHED",
        "day":target_day,
        "manifest_digest":package["manifest"]["digest"],
        "object_count":package["object_count"],
        "push_count":package["push_count"],
        "archive_deployed":True,
        "version_id":deploy.get("version_id"),
        "archive_job":str(prior_path),
    }


def install_launchd(*, config_path: Path, repo_root: Path,
                    python_executable: str, label: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}",label):
        raise DailyHistoryRuntimeError("invalid launchd label")
    plist=Path.home()/"Library"/"LaunchAgents"/f"{label}.plist"
    plist.parent.mkdir(parents=True,exist_ok=True)
    logs=Path.home()/"Library"/"Logs"
    args=[
        python_executable,"-B","-m","ptt_offline.daily_history_runtime",
        "run","--config",str(config_path.resolve()),
    ]
    import plistlib
    body={
        "Label":label,
        "ProgramArguments":args,
        "WorkingDirectory":str(repo_root.resolve()),
        "StartCalendarInterval":{"Hour":7,"Minute":30},
        "RunAtLoad":False,
        "StandardOutPath":str(logs/f"{label}.out.log"),
        "StandardErrorPath":str(logs/f"{label}.err.log"),
    }
    raw=plistlib.dumps(body,fmt=plistlib.FMT_XML,sort_keys=True)
    if plist.exists() and plist.read_bytes()!=raw:
        raise DailyHistoryRuntimeError("launchd plist already exists with different content")
    if not plist.exists():
        plist.write_bytes(raw)
    return plist


class _Lock:
    def __init__(self,path: Path):
        self.path=path
        self.handle=None
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.handle=self.path.open("a+")
        try:
            fcntl.flock(self.handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DailyHistoryRuntimeError("daily history runtime already running") from exc
        return self
    def __exit__(self,*_):
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(),fcntl.LOCK_UN)
            self.handle.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description="Daily previous-day PTT finalize/archive runtime")
    sub=parser.add_subparsers(dest="cmd",required=True)

    run=sub.add_parser("run")
    run.add_argument("--config",required=True)
    run.add_argument("--day")

    install=sub.add_parser("install-launchd")
    install.add_argument("--config",required=True)
    install.add_argument("--repo-root",required=True)
    install.add_argument("--python",required=True)
    install.add_argument("--label",default="com.holoviewer.ptt-history-closeout")

    args=parser.parse_args(argv)
    if args.cmd=="run":
        config=load_config(Path(args.config).expanduser())
        with _Lock(config["_state_path"]/"daily-history.lock"):
            result=run_closeout(config=config,day=args.day)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        if result["status"]=="NOT_ARCHIVE_READY":
            raise SystemExit(2)
        return
    if args.cmd=="install-launchd":
        path=install_launchd(
            config_path=Path(args.config).expanduser(),
            repo_root=Path(args.repo_root).expanduser(),
            python_executable=args.python,
            label=args.label,
        )
        print(json.dumps({"status":"LAUNCHD_PLIST_READY","path":str(path)},ensure_ascii=False))


if __name__=="__main__":
    main()
