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
import time
from datetime import datetime, timedelta, timezone
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
    validate_finalization_receipt,
    verify_http_readback,
)
from .r2_archive_export import export_archive

CONFIG_SCHEMA="holoviewer-ptt-daily-history-runtime-config-v1"
LIFECYCLE_V2_CUTOVER_DAY="2026-10-23"
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


def _validate_expected_contract_digest(body: dict[str,Any]) -> None:
    digest=body.get("evidence_digest")
    if not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest):
        raise DailyHistoryRuntimeError("expected-AID evidence_digest missing")
    material=json.loads(json.dumps(body))
    material.pop("evidence_digest",None)

    # expected_aids_from_discovery() is a reviewed v1 adapter layered on top of
    # build_expected_aid_contract(). The builder computes evidence_digest first;
    # the adapter then appends these two provenance annotations. They are not part
    # of the builder-signed material, so validate their consistency separately
    # and exclude them from digest recomputation.
    if material.get("source_kind")=="sanitized-collector-discovery":
        target_count=material.get("discovery_target_count")
        expected_rows=material.get("expected")
        if not isinstance(target_count,int) or not isinstance(expected_rows,list):
            raise DailyHistoryRuntimeError("expected-AID discovery annotation invalid")
        if material.get("status")=="COMPLETE" and target_count!=len(expected_rows):
            raise DailyHistoryRuntimeError("expected-AID discovery target count mismatch")
        material.pop("source_kind",None)
        material.pop("discovery_target_count",None)

    authority=material.get("authority")
    if isinstance(authority,dict):
        evidence_hash=authority.get("evidence_hash")
        # Two reviewed v1 authority modes are valid:
        # 1. builder receives no authority hash, computes the contract digest
        #    with evidence_hash=null, then mirrors that digest back into the
        #    serialized authority field;
        # 2. upstream authority supplies its own SHA-256 evidence hash. In that
        #    case the external hash is identity-bearing material and must remain
        #    present while recomputing the contract digest.
        if evidence_hash==digest:
            authority["evidence_hash"]=None
        elif evidence_hash is not None:
            if not isinstance(evidence_hash,str) or not re.fullmatch(r"[0-9a-f]{64}",evidence_hash):
                raise DailyHistoryRuntimeError("expected-AID authority evidence_hash invalid")
    if sha256(_canonical_bytes(material)).hexdigest()!=digest:
        raise DailyHistoryRuntimeError("expected-AID evidence_digest mismatch")


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
    _validate_expected_contract_digest(body)
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
    # Repair is an explicit owner-local mutation gate, independent of deploy.
    # A build-only/dry-run with a configured command must remain read-only.
    if config.get("repair_enabled") is not True:
        return None
    raw=config.get("repair_command")
    if raw is None:
        raise DailyHistoryRuntimeError("repair_enabled=true but repair_command is unavailable")
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


def _source_thread_epoch(row: dict[str,Any]) -> datetime | None:
    """Return authoritative article-post epoch from a canonical PTT source URL."""
    source_url=row.get("source_url")
    if not isinstance(source_url,str):
        return None
    match=re.search(r"/M\.([0-9]{9,11})\.A\.",source_url)
    if not match:
        return None
    return datetime.fromtimestamp(int(match.group(1)),tz=timezone.utc)


def _row_time(row: dict[str,Any]) -> datetime:
    value=row.get("occurred_at")
    if not isinstance(value,str):
        raise DailyHistoryRuntimeError("daily source row occurred_at required")
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:
        raise DailyHistoryRuntimeError("daily source row occurred_at invalid") from exc
    if parsed.tzinfo is None:
        raise DailyHistoryRuntimeError("daily source row occurred_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)



def _expected_thread_epochs(expected_contract: dict[str,Any]) -> dict[str,datetime]:
    """Resolve authoritative expected-thread article epochs independent of push rows."""
    rows=expected_contract.get("expected")
    if not isinstance(rows,list) or not rows:
        raise DailyHistoryRuntimeError("expected thread authority metadata required")
    epochs={}
    for item in rows:
        if not isinstance(item,dict):
            raise DailyHistoryRuntimeError("invalid expected thread authority row")
        aid=str(item.get("aid") or "").lstrip("#")
        if not aid:
            raise DailyHistoryRuntimeError("expected thread AID required")
        source_url=item.get("source_url")
        if not isinstance(source_url,str):
            raise DailyHistoryRuntimeError("expected thread source_url authority required")
        match=re.search(r"/M\.([0-9]{9,11})\.A\.",source_url)
        if not match:
            raise DailyHistoryRuntimeError("expected thread article epoch authority unavailable")
        epoch=datetime.fromtimestamp(int(match.group(1)),tz=timezone.utc)
        prior=epochs.get(aid)
        if prior is not None and prior!=epoch:
            raise DailyHistoryRuntimeError("expected thread epoch authority conflict")
        epochs[aid]=epoch
    return epochs

def _build_taipei_day_source_object(*, day: str, payloads: list[dict[str,Any]],
                                    expected_aids: set[str],
                                    expected_thread_epochs: dict[str,datetime]) -> tuple[str,bytes]:
    """Collapse exporter buckets into the canonical one-Taipei-day event partition.

    Membership is not simply "all rows in the exporter window" and is not simply
    "rows whose AID is in today's expected set".

    Canonical membership:
    1. every row must occur inside the exact Taipei calendar-day interval;
    2. rows from the authoritative expected AIDs for this finalized day belong;
    3. rows from exactly one direct predecessor thread may belong anywhere inside
       the target Taipei day. That predecessor is the candidate with the latest
       authoritative article-post epoch before the first expected thread's
       article-post epoch;
    4. older predecessor candidates are proven superseded by that direct
       predecessor; unexpected threads at/after the first expected thread start
       are outside the authoritative day/thread scope;
    5. if an unexpected row cannot be classified with authoritative article-post
       epochs, packaging fails closed instead of silently dropping it.

    This preserves legal cross-midnight pushes from the previous evening thread
    while excluding unrelated/adjacent threads deterministically.
    """
    normalized_expected={str(aid).lstrip("#") for aid in expected_aids if str(aid).lstrip("#")}
    if not normalized_expected:
        raise DailyHistoryRuntimeError("daily source expected AID set required")

    day_start=datetime.fromisoformat(day).replace(tzinfo=TPE)
    day_end=day_start+timedelta(days=1)
    start_utc=day_start.astimezone(timezone.utc)
    end_utc=day_end.astimezone(timezone.utc)

    candidates=[]
    thread_epochs: dict[str,datetime]={}
    for payload in payloads:
        rows=payload.get("pushes")
        if not isinstance(rows,list):
            raise DailyHistoryRuntimeError("daily source object pushes missing")
        for raw in rows:
            if not isinstance(raw,dict):
                raise DailyHistoryRuntimeError("invalid source push row")
            row=dict(raw)
            aid=str(row.get("aid") or "").lstrip("#")
            if not aid:
                raise DailyHistoryRuntimeError("daily source row AID required")
            occurred=_row_time(row)
            if not start_utc<=occurred<end_utc:
                raise DailyHistoryRuntimeError("daily exporter row outside Taipei-day partition")
            epoch=_source_thread_epoch(row)
            prior=thread_epochs.get(aid)
            if epoch is not None:
                if prior is not None and prior!=epoch:
                    raise DailyHistoryRuntimeError("AID has inconsistent source thread epoch")
                thread_epochs[aid]=epoch
            candidates.append((aid,occurred,row))

    normalized_authority={
        str(aid).lstrip("#"):epoch
        for aid,epoch in expected_thread_epochs.items()
        if str(aid).lstrip("#") in normalized_expected
    }
    if set(normalized_authority)!=normalized_expected:
        raise DailyHistoryRuntimeError("expected thread epoch authority incomplete")
    if any(not isinstance(epoch,datetime) or epoch.tzinfo is None
           for epoch in normalized_authority.values()):
        raise DailyHistoryRuntimeError("invalid expected thread epoch authority")
    first_expected_epoch=min(
        epoch.astimezone(timezone.utc) for epoch in normalized_authority.values())
    unexpected_aids={aid for aid,_,_ in candidates if aid not in normalized_expected}

    predecessor_aid=None
    if unexpected_aids:
        missing_epoch=sorted(aid for aid in unexpected_aids if aid not in thread_epochs)
        if missing_epoch:
            raise DailyHistoryRuntimeError(
                "unexpected AID cannot be classified without source thread epoch")
        predecessor_candidates=[
            (epoch,aid) for aid,epoch in thread_epochs.items()
            if aid in unexpected_aids and first_expected_epoch is not None
            and epoch<first_expected_epoch
        ]
        if predecessor_candidates:
            predecessor_aid=max(predecessor_candidates)[1]

    pushes=[]
    seen=set()
    excluded_counts: dict[str,int]={}
    excluded_reasons: dict[str,str]={}
    carry_in_count=0
    for aid,occurred,row in candidates:
        include=False
        membership_reason=None
        if aid in normalized_expected:
            include=True
            membership_reason="expected-thread"
        elif predecessor_aid is not None and aid==predecessor_aid:
            include=True
            membership_reason="direct-predecessor-cross-midnight"
            carry_in_count+=1
        else:
            epoch=thread_epochs.get(aid)
            if epoch is None or first_expected_epoch is None:
                raise DailyHistoryRuntimeError("unexpected AID membership is not provable")
            if epoch<first_expected_epoch:
                reason="superseded-predecessor"
            else:
                reason="outside-authoritative-expected-thread-set"
            excluded_counts[aid]=excluded_counts.get(aid,0)+1
            excluded_reasons[aid]=reason
            continue

        if row.get("floor") is None or row.get("floor_quality")!="per-thread-ordinal":
            raise DailyHistoryRuntimeError(
                "VERIFIED_COMPLETE archive requires authoritative per-thread floor")
        identity=row.get("source_record_key")
        if not isinstance(identity,str) or not identity:
            raise DailyHistoryRuntimeError("daily source requires stable source_record_key")
        if identity in seen:
            raise DailyHistoryRuntimeError("duplicate source_record_key across daily source")
        seen.add(identity)
        row["coverage_day"]=day
        row["coverage_status"]="COMPLETE"
        row["finalized"]=True
        row["day_membership"]=membership_reason
        pushes.append(row)

    if not pushes:
        raise DailyHistoryRuntimeError("no archive pushes for finalized day")
    pushes.sort(key=lambda row:(
        _row_time(row),
        str(row.get("aid") or ""),
        int(row.get("source_line") or 0),
        str(row.get("source_record_key") or ""),
    ))
    payload={
        "schema_version":"holoviewer-ptt-history-day-v1",
        "precision":"minute",
        "timezone":"Asia/Taipei",
        "partition_kind":"taipei-day",
        "partition_start":start_utc.isoformat(timespec="seconds").replace("+00:00","Z"),
        "partition_end":end_utc.isoformat(timespec="seconds").replace("+00:00","Z"),
        "coverage_day":day,
        "coverage_status":"COMPLETE",
        "finalized":True,
        "membership":{
            "rule":"taipei-day-expected-plus-direct-predecessor-v1",
            "expected_aids":sorted(normalized_expected),
            "direct_predecessor_aid":predecessor_aid,
            "first_expected_thread_start":
                first_expected_epoch.isoformat(timespec="seconds").replace("+00:00","Z"),
            "cross_midnight_carry_in_pushes":carry_in_count,
            "excluded_aids":[{
                "aid":aid,
                "pushes":excluded_counts[aid],
                "reason":excluded_reasons[aid],
            } for aid in sorted(excluded_counts)],
            "silent_drop":False,
        },
        "pushes":pushes,
    }
    return "day.json",_canonical_bytes(payload)


def _build_thread_lifecycle_source_object(
    *,
    day: str,
    payloads: list[dict[str,Any]],
    expected_aids: set[str],
    expected_thread_epochs: dict[str,datetime],
) -> tuple[str,bytes]:
    """Build one archive object owned by the target day's expected threads.

    The target day owns its authoritative expected day/night threads through the
    first next-day successor-thread handoff, capped at 07:30 Asia/Taipei. This
    permits a target night thread to contribute its post-midnight tail while
    preventing the same rows from being carried into the adjacent day's archive.
    """
    normalized_expected={
        str(aid).lstrip("#") for aid in expected_aids if str(aid).lstrip("#")
    }
    if not normalized_expected:
        raise DailyHistoryRuntimeError("daily source expected AID set required")

    day_start=datetime.fromisoformat(day).replace(tzinfo=TPE)
    next_midnight=day_start+timedelta(days=1)
    closeout_limit=next_midnight+timedelta(hours=7,minutes=30)
    start_utc=day_start.astimezone(timezone.utc)
    next_midnight_utc=next_midnight.astimezone(timezone.utc)
    closeout_limit_utc=closeout_limit.astimezone(timezone.utc)

    normalized_authority={
        str(aid).lstrip("#"):epoch
        for aid,epoch in expected_thread_epochs.items()
        if str(aid).lstrip("#") in normalized_expected
    }
    if set(normalized_authority)!=normalized_expected:
        raise DailyHistoryRuntimeError("expected thread epoch authority incomplete")
    if any(not isinstance(epoch,datetime) or epoch.tzinfo is None
           for epoch in normalized_authority.values()):
        raise DailyHistoryRuntimeError("invalid expected thread epoch authority")

    first_expected_epoch=min(
        epoch.astimezone(timezone.utc) for epoch in normalized_authority.values())

    candidates=[]
    thread_epochs: dict[str,datetime]={}
    for payload in payloads:
        rows=payload.get("pushes")
        if not isinstance(rows,list):
            raise DailyHistoryRuntimeError("daily source object pushes missing")
        for raw in rows:
            if not isinstance(raw,dict):
                raise DailyHistoryRuntimeError("invalid source push row")
            row=dict(raw)
            aid=str(row.get("aid") or "").lstrip("#")
            if not aid:
                raise DailyHistoryRuntimeError("daily source row AID required")
            occurred=_row_time(row)
            epoch=_source_thread_epoch(row)
            prior=thread_epochs.get(aid)
            if epoch is not None:
                if prior is not None and prior!=epoch:
                    raise DailyHistoryRuntimeError("AID has inconsistent source thread epoch")
                thread_epochs[aid]=epoch
            candidates.append((aid,occurred,row))

    # Any unexpected thread born after the target midnight and before the
    # 07:30 closeout cap is the authoritative next-owner handoff.
    successor_candidates=[]
    for aid,epoch in thread_epochs.items():
        if aid in normalized_expected:
            continue
        epoch_utc=epoch.astimezone(timezone.utc)
        if next_midnight_utc<=epoch_utc<closeout_limit_utc:
            successor_candidates.append((epoch_utc,aid))
        elif first_expected_epoch<=epoch_utc<next_midnight_utc:
            # A non-authoritative thread born inside the target lifecycle makes
            # ownership ambiguous; fail closed instead of silently excluding it.
            raise DailyHistoryRuntimeError(
                "unexpected thread inside authoritative target lifecycle")

    successor_aid=None
    handoff_boundary=closeout_limit_utc
    handoff_source="closeout-limit"
    if successor_candidates:
        handoff_boundary,successor_aid=min(successor_candidates)
        handoff_source="successor-thread"

    pushes=[]
    seen=set()
    excluded_counts: dict[str,int]={}
    excluded_reasons: dict[str,str]={}
    post_midnight_tail=0

    def exclude(aid: str, reason: str) -> None:
        excluded_counts[aid]=excluded_counts.get(aid,0)+1
        excluded_reasons[aid]=reason

    for aid,occurred,row in candidates:
        if occurred<start_utc:
            exclude(aid,"before-target-lifecycle")
            continue
        if occurred>=closeout_limit_utc:
            exclude(aid,"after-closeout-limit")
            continue

        if aid not in normalized_expected:
            epoch=thread_epochs.get(aid)
            if epoch is None:
                raise DailyHistoryRuntimeError(
                    "unexpected AID cannot be classified without source thread epoch")
            epoch_utc=epoch.astimezone(timezone.utc)
            if epoch_utc<first_expected_epoch:
                exclude(aid,"previous-lifecycle-thread")
            elif epoch_utc>=next_midnight_utc:
                exclude(aid,"successor-thread")
            else:
                raise DailyHistoryRuntimeError(
                    "unexpected AID membership is not provable")
            continue

        if occurred>=handoff_boundary:
            exclude(aid,"after-authoritative-handoff")
            continue

        if row.get("floor") is None or row.get("floor_quality")!="per-thread-ordinal":
            raise DailyHistoryRuntimeError(
                "VERIFIED_COMPLETE archive requires authoritative per-thread floor")
        identity=row.get("source_record_key")
        if not isinstance(identity,str) or not identity:
            raise DailyHistoryRuntimeError("daily source requires stable source_record_key")
        if identity in seen:
            raise DailyHistoryRuntimeError("duplicate source_record_key across daily source")
        seen.add(identity)

        row["coverage_day"]=day
        row["coverage_status"]="COMPLETE"
        row["finalized"]=True
        row["day_membership"]="expected-thread-lifecycle"
        pushes.append(row)
        if occurred>=next_midnight_utc:
            post_midnight_tail+=1

    if not pushes:
        raise DailyHistoryRuntimeError("no archive pushes for finalized day")

    pushes.sort(key=lambda row:(
        _row_time(row),
        str(row.get("aid") or ""),
        int(row.get("source_line") or 0),
        str(row.get("source_record_key") or ""),
    ))

    payload={
        "schema_version":"holoviewer-ptt-history-day-v2",
        "precision":"minute",
        "timezone":"Asia/Taipei",
        "partition_kind":"expected-thread-lifecycle",
        "partition_start":start_utc.isoformat(timespec="seconds").replace("+00:00","Z"),
        "partition_end":
            handoff_boundary.isoformat(timespec="seconds").replace("+00:00","Z"),
        "coverage_day":day,
        "coverage_status":"COMPLETE",
        "finalized":True,
        "membership":{
            "rule":"expected-thread-lifecycle-v2",
            "expected_aids":sorted(normalized_expected),
            "first_expected_thread_start":
                first_expected_epoch.isoformat(timespec="seconds").replace("+00:00","Z"),
            "closeout_limit":
                closeout_limit_utc.isoformat(timespec="seconds").replace("+00:00","Z"),
            "handoff_boundary":
                handoff_boundary.isoformat(timespec="seconds").replace("+00:00","Z"),
            "handoff_source":handoff_source,
            "successor_aid":successor_aid,
            "post_midnight_tail_pushes":post_midnight_tail,
            "excluded_aids":[{
                "aid":aid,
                "pushes":excluded_counts[aid],
                "reason":excluded_reasons[aid],
            } for aid in sorted(excluded_counts)],
            "silent_drop":False,
        },
        "pushes":pushes,
    }
    return "day.json",_canonical_bytes(payload)


def _daily_source_objects(*, source: Path, day: str, work_dir: Path,
                          expected_aids: set[str],
                          expected_thread_epochs: dict[str,datetime]) -> list[tuple[str,bytes]]:
    archive_root=work_dir/"source-archive"
    with open_source(str(source)) as db:
        next_day=(datetime.fromisoformat(day)+timedelta(days=1)).date().isoformat()
        receipt=export_archive(
            db,from_day=day,through_day=next_day,out_dir=archive_root)
    payloads=[]
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
        if not isinstance(payload,dict):
            raise DailyHistoryRuntimeError("invalid daily source archive payload")
        payloads.append(payload)
    if not payloads:
        raise DailyHistoryRuntimeError("no archive objects for finalized day")
    return [_build_thread_lifecycle_source_object(
        day=day,payloads=payloads,expected_aids=expected_aids,
        expected_thread_epochs=expected_thread_epochs)]

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


def _verify_http_readback_with_retry(*, package: dict[str,Any], job_id: str,
                                     base_url: str, target_identity: str,
                                     timeout: int, attempts: int,
                                     delay_seconds: float) -> dict[str,Any]:
    if not 1<=attempts<=12:
        raise DailyHistoryRuntimeError("readback_attempts outside 1..12")
    if not 0<=delay_seconds<=30:
        raise DailyHistoryRuntimeError("readback_retry_seconds outside 0..30")
    fetch=_http_fetcher(base_url,timeout=timeout)
    receipt=None
    for index in range(attempts):
        receipt=verify_http_readback(
            package=package,job_id=job_id,fetch_bytes=fetch,
            observed_at=datetime.now(TPE).isoformat(),
            target_identity=target_identity,
        )
        if receipt.get("job_verified") is True:
            return receipt
        if index+1<attempts and delay_seconds:
            time.sleep(delay_seconds)
    assert receipt is not None
    return receipt


def _stable_finalization_material(receipt: object) -> object:
    """Compare closeout semantics while ignoring observation-only identity.

    Both the #48 finalization receipt and the public date-search expected-AID
    contract are freshly observed on every invocation. Their timestamps and
    digest mirrors therefore change even when the authoritative day/AID set and
    Collector coverage are byte-for-byte unchanged. Those observation-only
    fields must not mint another immutable historical revision.

    We still retain the authority kind/day/version/issuer/evidence_id,
    expected_aids/status, per-thread coverage digests, gaps/conflicts and safety
    state. A real authority/AID/coverage change therefore invalidates reuse.
    """
    if not isinstance(receipt,dict):
        return None
    body=json.loads(json.dumps(receipt))
    body.pop("observed_at",None)
    body.pop("evidence_digest",None)

    expected=body.get("expected_set")
    if isinstance(expected,dict):
        expected.pop("evidence_digest",None)
        authority=expected.get("authority")
        if isinstance(authority,dict):
            authority.pop("observed_at",None)
            authority.pop("evidence_hash",None)
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


def run_packaging_acceptance(
    *,
    config: dict[str,Any],
    day: str,
    finalization_path: Path,
    expected_contract_path: Path,
) -> dict[str,Any]:
    """Build one finalized Taipei-day package without re-running #48 completeness.

    This is the Owner-local safe acceptance seam. It consumes already-finalized
    #48 authority, reads the Collector SQLite only as an immutable archive source,
    never invokes coverage classification/repair, and refuses deploy=true.
    """
    if config.get("deploy") is True:
        raise DailyHistoryRuntimeError("packaging acceptance requires deploy=false")
    if config.get("repair_enabled") is True:
        raise DailyHistoryRuntimeError("packaging acceptance requires repair_enabled=false")

    source: Path=config["_collector_path"]
    state_root: Path=config["_state_path"]
    state_root.mkdir(parents=True,exist_ok=True)

    finalization=_load_json(finalization_path.expanduser())
    try:
        validate_finalization_receipt(finalization)
    except Exception as exc:
        raise DailyHistoryRuntimeError("fresh finalization receipt rejected") from exc
    if finalization.get("day")!=day:
        raise DailyHistoryRuntimeError("fresh finalization day mismatch")

    expected=_load_json(expected_contract_path.expanduser())
    if expected.get("schema_version")!="holoviewer-ptt-expected-aids-v1":
        raise DailyHistoryRuntimeError("expected-AID contract schema mismatch")
    if expected.get("day")!=day:
        raise DailyHistoryRuntimeError("expected-AID contract day mismatch")
    _validate_expected_contract_digest(expected)
    if expected.get("status")!="COMPLETE":
        raise DailyHistoryRuntimeError("expected-AID contract is not COMPLETE")

    expected_rows=expected.get("expected")
    if not isinstance(expected_rows,list):
        raise DailyHistoryRuntimeError("expected-AID rows required")
    expected_aids={
        str(row.get("aid") or "").lstrip("#")
        for row in expected_rows if isinstance(row,dict)
    }
    expected_aids.discard("")
    finalized_expected={
        str(aid).lstrip("#")
        for aid in finalization["expected_set"]["expected_aids"]
    }
    if expected_aids!=finalized_expected:
        raise DailyHistoryRuntimeError("fresh finalization/expected-AID set mismatch")
    expected_digest=finalization["expected_set"].get("evidence_digest")
    if expected_digest!=expected.get("evidence_digest"):
        raise DailyHistoryRuntimeError("fresh finalization expected-set digest mismatch")

    expected_epochs=_expected_thread_epochs(expected)
    with tempfile.TemporaryDirectory(
        prefix=f"holoviewer-packaging-{day}-",dir=state_root
    ) as tmp:
        source_objects=_daily_source_objects(
            source=source,day=day,work_dir=Path(tmp),
            expected_aids=finalized_expected,
            expected_thread_epochs=expected_epochs,
        )

    public,_=ensure_static_root(
        state_root=state_root,target=str(config["static_target"]))
    source_revision=f"collector-finalized-{day}-post-authority-v1"
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
    package_path=state_root/"archive"/day/"package.json"
    _atomic_json(package_path,package)

    if package.get("package_status")!="COMPLETE":
        raise DailyHistoryRuntimeError("Static Assets package validation incomplete")
    if package.get("object_count")!=1:
        raise DailyHistoryRuntimeError("one Taipei day must package exactly one day.json")
    objects=package.get("objects")
    if not isinstance(objects,list) or len(objects)!=1:
        raise DailyHistoryRuntimeError("one day.json package object required")
    if objects[0].get("logical_key")!="day.json":
        raise DailyHistoryRuntimeError("canonical daily object must be day.json")

    day_object_path=public/str(objects[0]["key"])
    if not day_object_path.is_file():
        raise DailyHistoryRuntimeError("staged day.json missing")
    day_payload=_load_json(day_object_path)
    membership=day_payload.get("membership")
    if not isinstance(membership,dict):
        raise DailyHistoryRuntimeError("day.json membership audit missing")
    excluded=membership.get("excluded_aids")
    if not isinstance(excluded,list):
        raise DailyHistoryRuntimeError("day.json excluded-AID audit missing")
    # "unexpected" means unclassified data that survived packaging. A legal
    # direct predecessor is classified carry-in and is reported separately.
    classified_allowed=set(finalized_expected)
    predecessor=membership.get("direct_predecessor_aid")
    if isinstance(predecessor,str) and predecessor:
        classified_allowed.add(predecessor.lstrip("#"))
    packaged_aids={
        str(row.get("aid") or "").lstrip("#")
        for row in day_payload.get("pushes",[]) if isinstance(row,dict)
    }
    unexpected=sorted(aid for aid in packaged_aids if aid not in classified_allowed)
    if unexpected:
        raise DailyHistoryRuntimeError("unclassified unexpected AID survived day.json packaging")

    return {
        "status":"READY_TO_DEPLOY",
        "day":day,
        "finalization_digest":finalization["evidence_digest"],
        "expected_set_digest":expected["evidence_digest"],
        "expected_aids":sorted(finalized_expected),
        "packaged_aids":sorted(packaged_aids),
        "direct_predecessor_aid":predecessor,
        "excluded_aids":excluded,
        "unexpected_aids":unexpected,
        "source_object_count":len(source_objects),
        "object_count":package["object_count"],
        "push_count":package["push_count"],
        "manifest_digest":package["manifest"]["digest"],
        "source_hash":package["source_hash"],
        "package":str(package_path),
        "day_json":str(day_object_path),
        "package_validation":"PASS",
        "repair_enabled":False,
        "deploy":False,
        "archive_deployed":False,
    }


def run_closeout(*, config: dict[str,Any], day: str | None=None) -> dict[str,Any]:
    source: Path=config["_collector_path"]
    state_root: Path=config["_state_path"]
    state_root.mkdir(parents=True,exist_ok=True)
    target_day=day or previous_taipei_day()
    if target_day < LIFECYCLE_V2_CUTOVER_DAY:
        return {
            "status":"PRE_CUTOVER_IMMUTABLE",
            "day":target_day,
            "cutover_day":LIFECYCLE_V2_CUTOVER_DAY,
            "archive_deployed":False,
            "reason":"historical-v1-production-archive-immutable",
        }
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
    expected_epochs=_expected_thread_epochs(expected)
    with tempfile.TemporaryDirectory(prefix=f"holoviewer-{target_day}-",dir=state_root) as tmp:
        source_objects=_daily_source_objects(
            source=source,day=target_day,work_dir=Path(tmp),expected_aids=expected_aids,
            expected_thread_epochs=expected_epochs)

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

    # Workers Static Assets can become edge-readable moments after Wrangler
    # reports deploy success. If this exact manifest was already delivered but
    # its first readback missed propagation, retry readback before creating a
    # second deployment/version.
    if (prior and prior.get("job_status")=="succeeded"
            and isinstance(prior.get("manifest"),dict)
            and prior["manifest"].get("digest")==package["manifest"]["digest"]
            and isinstance(prior.get("job_id"),str)):
        recovered=_verify_http_readback_with_retry(
            package=package,job_id=prior["job_id"],
            base_url=str(config["base_url"]),
            target_identity=str(config["static_target"]),
            timeout=int(config.get("readback_timeout_seconds",20)),
            attempts=int(config.get("readback_attempts",6)),
            delay_seconds=float(config.get("readback_retry_seconds",2)),
        )
        if recovered.get("job_verified") is True:
            recovered_evidence=build_archive_delivery_evidence(
                package=package,finalization_receipt=finalization,
                job_id=prior["job_id"],job_status="succeeded",
                attempted_at=prior.get("attempted_at"),
                succeeded_at=prior.get("succeeded_at"),
                attempt_count=previous_attempt,
                uploaded_count=prior.get("uploaded_count"),
                readback_receipt=recovered,error_code=None,
                target_identity=str(config["static_target"]),
            )
            _atomic_json(prior_path,recovered_evidence)
            _atomic_json(state_root/"latest-archive-job.json",recovered_evidence)
            return {
                "status":"VERIFIED_COMPLETE_PUBLISHED",
                "day":target_day,
                "manifest_digest":package["manifest"]["digest"],
                "object_count":package["object_count"],
                "push_count":package["push_count"],
                "archive_deployed":False,
                "readback_recovered":True,
                "archive_job":str(prior_path),
            }

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

    readback=_verify_http_readback_with_retry(
        package=package,job_id=job_id,
        base_url=str(config["base_url"]),
        target_identity=str(config["static_target"]),
        timeout=int(config.get("readback_timeout_seconds",20)),
        attempts=int(config.get("readback_attempts",6)),
        delay_seconds=float(config.get("readback_retry_seconds",2)),
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

    accept=sub.add_parser("accept-package")
    accept.add_argument("--config",required=True)
    accept.add_argument("--day",required=True)
    accept.add_argument("--finalization",required=True)
    accept.add_argument("--expected-contract",required=True)

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
        if result["status"] in {"NOT_ARCHIVE_READY","PRE_CUTOVER_IMMUTABLE"}:
            raise SystemExit(2)
        return
    if args.cmd=="accept-package":
        config=load_config(Path(args.config).expanduser())
        with _Lock(config["_state_path"]/"daily-history.lock"):
            result=run_packaging_acceptance(
                config=config,
                day=args.day,
                finalization_path=Path(args.finalization),
                expected_contract_path=Path(args.expected_contract),
            )
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
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
