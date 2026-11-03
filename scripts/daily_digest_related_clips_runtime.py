#!/usr/bin/env python3
"""Durable scheduler/state core for Daily Digest related-clips refresh work.

This module deliberately does not activate a production schedule or call Holodex by
itself. It computes due work, persists/reconciles durable state, supports bounded
historical backfill, and builds deterministic monthly cold archives/indexes.
Provider/export/publish adapters remain explicit caller responsibilities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

STATE_KIND = "holodocchi.daily_digest.related_clips.runtime_state"
QUEUE_KIND = "holodocchi.daily_digest.related_clips.backfill_queue"
ARCHIVE_KIND = "holodocchi.daily_digest.related_clips_month"
INDEX_KIND = "holodocchi.daily_digest.related_clips_index"
SIDECAR_KIND = "holodocchi.daily_digest.related_clips"
SCHEMA_VERSION = 1
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

STAGES = (
    ("initial", 0, 0),
    ("t1", 1, 1),
    ("t3", 3, 2),
    ("t7", 7, 3),
)


class RuntimeError334(RuntimeError):
    pass


def canonical_json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _parse_day(value: str) -> date:
    if not DATE_RE.fullmatch(value):
        raise RuntimeError334(f"invalid target day: {value}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError334(f"invalid target day: {value}") from exc


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": STATE_KIND,
        "days": {},
    }


def empty_queue() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": QUEUE_KIND,
        "days": [],
    }


def validate_state(payload: Any) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("kind") != STATE_KIND
        or not isinstance(payload.get("days"), dict)
    ):
        raise RuntimeError334("runtime state contract mismatch")
    return payload


def validate_queue(payload: Any) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("kind") != QUEUE_KIND
        or not isinstance(payload.get("days"), list)
    ):
        raise RuntimeError334("backfill queue contract mismatch")
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in payload["days"]:
        day = str(raw or "").strip()
        _parse_day(day)
        if day not in seen:
            seen.add(day)
            cleaned.append(day)
    return {**payload, "days": cleaned}


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json_bytes(payload)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_json_or(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError334(f"invalid JSON: {path}") from exc
    return value


def discover_accepted_receipts(receipts_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    accepted: dict[str, str] = {}
    candidates: dict[str, str] = {}
    if not receipts_dir.exists():
        return accepted, candidates
    for path in sorted(receipts_dir.glob("*.finalized.json")):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError334(f"invalid accepted receipt: {path}") from exc
        if not isinstance(receipt, dict) or receipt.get("status") != "validated_accepted":
            continue
        target_day = str(receipt.get("target_day") or "").strip()
        _parse_day(target_day)
        digest_sha = str(receipt.get("public_candidate_sha256") or "").strip()
        revision_dir = str(receipt.get("revision_dir") or "").strip()
        if not digest_sha or not revision_dir:
            raise RuntimeError334(f"accepted receipt missing candidate identity: {path}")
        candidate = Path(revision_dir) / f"{target_day}.public-candidate.json"
        if candidate.is_file():
            actual_sha = sha256_bytes(candidate.read_bytes())
            if actual_sha != digest_sha:
                raise RuntimeError334(
                    f"accepted candidate SHA mismatch: {candidate}"
                )
        accepted[target_day] = digest_sha
        candidates[target_day] = str(candidate)
    return accepted, candidates


def build_job_command_plan(
    job: dict[str, Any],
    *,
    candidate_path: str,
    private_repo: Path,
    corpus_root: Path,
    sidecar_root: Path,
    python_executable: str,
) -> dict[str, Any]:
    target_day = str(job.get("target_day") or "")
    _parse_day(target_day)
    candidate = Path(candidate_path)
    work_root = sidecar_root / ".work" / target_day
    language_map = work_root / f"{target_day}.source-languages.json"
    sidecar = (
        sidecar_root
        / target_day[:7]
        / f"{target_day}-related-clips.json"
    )
    exporter = private_repo / "scripts" / "export_daily_digest_source_languages.py"
    resolver = Path(__file__).resolve().parent / "daily_digest_related_clips.py"
    return {
        "target_day": target_day,
        "stage": str(job.get("stage") or ""),
        "digest": str(candidate),
        "source_language_map": str(language_map),
        "sidecar": str(sidecar),
        "commands": [
            [
                python_executable,
                str(exporter),
                str(candidate),
                str(language_map),
                "--corpus-root",
                str(corpus_root),
            ],
            [
                python_executable,
                str(resolver),
                str(candidate),
                str(sidecar),
                "--source-language-map",
                str(language_map),
            ],
        ],
        "provider_execution": "NOT_EXECUTED_BY_PLAN",
        "static_deploy": "NOT_EXECUTED_BY_PLAN",
    }


def day_state(state: dict[str, Any], target_day: str) -> dict[str, Any]:
    _parse_day(target_day)
    days = state["days"]
    row = days.setdefault(
        target_day,
        {
            "target_day": target_day,
            "digest_sha256": "",
            "stages": {name: "pending" for name, _, _ in STAGES},
            "backfill": "pending",
            "last_attempt_at": "",
            "last_success_at": "",
            "clip_count": 0,
            "generated_sidecar_sha256": "",
            "published_live_sha256": "",
            "terminal": False,
            "errors": [],
        },
    )
    stages = row.setdefault("stages", {})
    for name, _, _ in STAGES:
        stages.setdefault(name, "pending")
    row.setdefault("backfill", "pending")
    row.setdefault("terminal", False)
    row.setdefault("errors", [])
    return row


def next_refresh_job(
    state: dict[str, Any],
    *,
    target_day: str,
    digest_sha256: str,
    today: str,
) -> dict[str, Any] | None:
    target = _parse_day(target_day)
    current = _parse_day(today)
    if current < target:
        return None
    row = day_state(state, target_day)
    if row.get("digest_sha256") and row["digest_sha256"] != digest_sha256:
        # A changed accepted Digest invalidates prior refresh completion evidence.
        row["stages"] = {name: "pending" for name, _, _ in STAGES}
        row["terminal"] = False
    row["digest_sha256"] = digest_sha256

    age = (current - target).days
    for stage, offset, priority in STAGES:
        if age >= offset and row["stages"].get(stage) != "complete":
            return {
                "target_day": target_day,
                "stage": stage,
                "priority": priority,
                "digest_sha256": digest_sha256,
                "reason": f"refresh_{stage}",
            }
    return None


def build_due_jobs(
    state: dict[str, Any],
    *,
    accepted_days: dict[str, str],
    today: str,
    backfill_queue: Iterable[str] = (),
    backfill_limit: int = 5,
) -> list[dict[str, Any]]:
    _parse_day(today)
    if backfill_limit < 0:
        raise RuntimeError334("backfill_limit must be non-negative")

    jobs: list[dict[str, Any]] = []
    for target_day in sorted(accepted_days):
        digest_sha = str(accepted_days[target_day] or "").strip()
        if not digest_sha:
            raise RuntimeError334(f"missing digest SHA for {target_day}")
        job = next_refresh_job(
            state,
            target_day=target_day,
            digest_sha256=digest_sha,
            today=today,
        )
        if job:
            jobs.append(job)

    added = 0
    seen_backfill: set[str] = set()
    for target_day in backfill_queue:
        target_day = str(target_day or "").strip()
        _parse_day(target_day)
        if target_day in seen_backfill:
            continue
        seen_backfill.add(target_day)
        row = day_state(state, target_day)
        if row.get("backfill") == "complete":
            continue
        jobs.append(
            {
                "target_day": target_day,
                "stage": "backfill",
                "priority": 4,
                "digest_sha256": str(row.get("digest_sha256") or ""),
                "reason": "historical_backfill",
            }
        )
        added += 1
        if added >= backfill_limit:
            break

    return sorted(jobs, key=lambda item: (item["priority"], item["target_day"]))


def record_attempt(
    state: dict[str, Any],
    *,
    target_day: str,
    stage: str,
    attempted_at: str,
    error: str = "",
) -> None:
    row = day_state(state, target_day)
    row["last_attempt_at"] = attempted_at
    if error:
        row["errors"].append({"at": attempted_at, "stage": stage, "error": error})
        row["errors"] = row["errors"][-10:]


def record_success(
    state: dict[str, Any],
    *,
    target_day: str,
    stage: str,
    succeeded_at: str,
    clip_count: int,
    generated_sha256: str,
    live_sha256: str,
) -> None:
    if not generated_sha256 or generated_sha256 != live_sha256:
        raise RuntimeError334("publication readback SHA mismatch")
    row = day_state(state, target_day)
    if stage == "backfill":
        row["backfill"] = "complete"
        # Historical backfill is terminal when it represents settled history.
        row["terminal"] = True
    elif stage in row["stages"]:
        row["stages"][stage] = "complete"
        if stage == "t7":
            row["terminal"] = True
    else:
        raise RuntimeError334(f"unknown stage: {stage}")
    row["last_success_at"] = succeeded_at
    row["clip_count"] = int(clip_count)
    row["generated_sidecar_sha256"] = generated_sha256
    row["published_live_sha256"] = live_sha256


def reconcile_publication(
    state: dict[str, Any],
    *,
    target_day: str,
    stage: str,
    generated_sha256: str,
    live_sha256: str,
    clip_count: int,
    reconciled_at: str,
) -> bool:
    if not generated_sha256 or generated_sha256 != live_sha256:
        return False
    record_success(
        state,
        target_day=target_day,
        stage=stage,
        succeeded_at=reconciled_at,
        clip_count=clip_count,
        generated_sha256=generated_sha256,
        live_sha256=live_sha256,
    )
    return True


def pending_backfill_days(
    queue: dict[str, Any],
    state: dict[str, Any],
    *,
    limit: int,
) -> list[str]:
    validated = validate_queue(queue)
    result: list[str] = []
    for target_day in validated["days"]:
        if day_state(state, target_day).get("backfill") == "complete":
            continue
        result.append(target_day)
        if len(result) >= limit:
            break
    return result


def month_compaction_eligible(
    state: dict[str, Any],
    *,
    month: str,
    expected_days: Iterable[str],
) -> bool:
    days = list(expected_days)
    if not days:
        return False
    for target_day in days:
        if not target_day.startswith(month + "-"):
            return False
        row = state["days"].get(target_day)
        if not isinstance(row, dict) or row.get("terminal") is not True:
            return False
        if not row.get("published_live_sha256"):
            return False
    return True


def validate_sidecar(sidecar: Any, target_day: str) -> dict[str, Any]:
    if (
        not isinstance(sidecar, dict)
        or sidecar.get("schema_version") != 1
        or sidecar.get("kind") != SIDECAR_KIND
        or sidecar.get("target_day") != target_day
        or sidecar.get("status") not in ("ok", "partial")
        or not isinstance(sidecar.get("stories"), list)
        or not isinstance(sidecar.get("sources"), dict)
    ):
        raise RuntimeError334(f"invalid related-clips sidecar: {target_day}")
    return sidecar


def build_month_archive(
    *,
    month: str,
    sidecars_by_day: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise RuntimeError334(f"invalid month: {month}")
    days: dict[str, dict[str, Any]] = {}
    for target_day in sorted(sidecars_by_day):
        if not target_day.startswith(month + "-"):
            raise RuntimeError334("archive contains foreign month")
        days[target_day] = validate_sidecar(sidecars_by_day[target_day], target_day)
    if not days:
        raise RuntimeError334("cannot compact empty month")
    return {
        "schema_version": 1,
        "kind": ARCHIVE_KIND,
        "month": month,
        "days": days,
    }


def build_storage_index(
    *,
    hot_days: Iterable[str],
    cold_months: Iterable[str],
) -> dict[str, Any]:
    hot: dict[str, str] = {}
    for target_day in sorted(set(hot_days)):
        _parse_day(target_day)
        month = target_day[:7]
        hot[target_day] = (
            f"/data/daily-digest/related-clips/{month}/{target_day}.json"
        )
    cold: dict[str, str] = {}
    for month in sorted(set(cold_months)):
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            raise RuntimeError334(f"invalid cold month: {month}")
        cold[month] = f"/data/daily-digest/related-clips/months/{month}.json"
    return {
        "schema_version": 1,
        "kind": INDEX_KIND,
        "hot_days": hot,
        "cold_months": cold,
    }


def resolve_storage(index: dict[str, Any], target_day: str) -> dict[str, str]:
    _parse_day(target_day)
    hot = index.get("hot_days") if isinstance(index.get("hot_days"), dict) else {}
    cold = (
        index.get("cold_months")
        if isinstance(index.get("cold_months"), dict)
        else {}
    )
    if target_day in hot:
        return {"tier": "hot", "path": str(hot[target_day])}
    month = target_day[:7]
    if month in cold:
        return {"tier": "cold", "path": str(cold[month])}
    return {"tier": "missing", "path": ""}


def digest_unchanged(before: bytes, after: bytes) -> bool:
    return before == after


def sidecar_clip_count(sidecar: dict[str, Any]) -> int:
    total = 0
    for story in sidecar.get("stories", []):
        if isinstance(story, dict) and isinstance(story.get("clips"), list):
            total += len(story["clips"])
    return total


def _run_checked(
    command: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> None:
    result = runner(
        list(command),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if int(getattr(result, "returncode", 1)) != 0:
        stderr = str(getattr(result, "stderr", "") or "").strip()
        stdout = str(getattr(result, "stdout", "") or "").strip()
        detail = stderr or stdout or "command failed"
        raise RuntimeError334(detail)


def execute_job(
    state: dict[str, Any],
    *,
    job: dict[str, Any],
    candidate_path: str,
    private_repo: Path,
    corpus_root: Path,
    sidecar_root: Path,
    public_repo: Path,
    public_expected_head: str,
    static_baseline_version: str,
    python_executable: str,
    holodex_api_key_env: str = "HOLODEX_API_KEY",
    execute: bool = False,
    runner: Callable[..., Any] = subprocess.run,
    readback_fetcher: Callable[[str], bytes] | None = None,
    succeeded_at: str | None = None,
) -> dict[str, Any]:
    plan = build_job_command_plan(
        job,
        candidate_path=candidate_path,
        private_repo=private_repo,
        corpus_root=corpus_root,
        sidecar_root=sidecar_root,
        python_executable=python_executable,
    )
    result: dict[str, Any] = {
        **plan,
        "mode": "EXECUTE" if execute else "DRY_RUN",
        "production_mutation": "PENDING_EXPLICIT_EXECUTE" if execute else "NO",
    }
    if not execute:
        return result

    candidate = Path(candidate_path)
    if not candidate.is_file():
        raise RuntimeError334(f"accepted candidate missing: {candidate}")
    before = candidate.read_bytes()
    expected_digest_sha = str(job.get("digest_sha256") or "").strip()
    if expected_digest_sha and sha256_bytes(before) != expected_digest_sha:
        raise RuntimeError334("accepted candidate SHA changed before execution")
    if not os.environ.get(holodex_api_key_env, "").strip():
        raise RuntimeError334(
            f"{holodex_api_key_env} is required for execute mode"
        )

    record_attempt(
        state,
        target_day=str(job["target_day"]),
        stage=str(job["stage"]),
        attempted_at=succeeded_at or utc_now(),
    )

    env = dict(os.environ)
    for command in plan["commands"]:
        _run_checked(command, env=env, runner=runner)

    after = candidate.read_bytes()
    if not digest_unchanged(before, after):
        raise RuntimeError334("accepted Daily Digest mutated during enrichment")

    sidecar_path = Path(plan["sidecar"])
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError334("generated sidecar unreadable") from exc
    validated = validate_sidecar(sidecar, str(job["target_day"]))
    generated_bytes = canonical_json_bytes(validated)
    generated_sha = sha256_bytes(generated_bytes)
    actual_sha = sha256_bytes(sidecar_path.read_bytes())
    if actual_sha != generated_sha:
        raise RuntimeError334("generated sidecar is not canonical JSON")

    release_script = (
        public_repo / "scripts" / "deploy_daily_digest_static_assets_owner_local.sh"
    )
    _run_checked(
        [str(release_script), "prepare", public_expected_head],
        env=env,
        runner=runner,
    )
    _run_checked(
        [
            str(release_script),
            "deploy",
            public_expected_head,
            static_baseline_version,
        ],
        env=env,
        runner=runner,
    )

    if readback_fetcher is None:
        raise RuntimeError334("execute mode requires live readback fetcher")
    month = str(job["target_day"])[:7]
    live_path = (
        f"/data/daily-digest/{month}/"
        f"{job['target_day']}-related-clips.json"
    )
    live_bytes = readback_fetcher(live_path)
    live_sha = sha256_bytes(live_bytes)
    if live_sha != generated_sha:
        raise RuntimeError334("live related-clips SHA mismatch")

    timestamp = succeeded_at or utc_now()
    record_success(
        state,
        target_day=str(job["target_day"]),
        stage=str(job["stage"]),
        succeeded_at=timestamp,
        clip_count=sidecar_clip_count(validated),
        generated_sha256=generated_sha,
        live_sha256=live_sha,
    )
    result.update(
        {
            "production_mutation": "YES",
            "sidecar_sha256": generated_sha,
            "live_sha256": live_sha,
            "clip_count": sidecar_clip_count(validated),
            "live_path": live_path,
            "state_reconciled": True,
        }
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    accepted_group = parser.add_mutually_exclusive_group(required=True)
    accepted_group.add_argument("--accepted-days", type=Path)
    accepted_group.add_argument("--accepted-receipts-dir", type=Path)
    parser.add_argument("--backfill-queue", type=Path)
    parser.add_argument("--today", required=True)
    parser.add_argument("--backfill-limit", type=int, default=5)
    parser.add_argument(
        "--write-state",
        action="store_true",
        help="persist normalized state after planning; does not execute provider/publish work",
    )
    args = parser.parse_args(argv)

    try:
        state = validate_state(load_json_or(args.state, empty_state()))
        if args.accepted_receipts_dir:
            accepted, _candidate_paths = discover_accepted_receipts(
                args.accepted_receipts_dir
            )
        else:
            accepted = json.loads(args.accepted_days.read_text(encoding="utf-8"))
            if not isinstance(accepted, dict):
                raise RuntimeError334(
                    "accepted-days must be a day -> digest SHA object"
                )
        queue_days: list[str] = []
        if args.backfill_queue:
            queue = validate_queue(load_json_or(args.backfill_queue, empty_queue()))
            queue_days = pending_backfill_days(
                queue,
                state,
                limit=args.backfill_limit,
            )
        jobs = build_due_jobs(
            state,
            accepted_days={str(k): str(v) for k, v in accepted.items()},
            today=args.today,
            backfill_queue=queue_days,
            backfill_limit=args.backfill_limit,
        )
        if args.write_state:
            atomic_write_json(args.state, state)
    except (OSError, json.JSONDecodeError, RuntimeError334) as exc:
        print(f"ERROR={exc}", file=os.sys.stderr)
        return 1

    print("MODE=DRY_RUN_PLAN")
    print(f"TODAY={args.today}")
    print(f"DUE_JOBS={len(jobs)}")
    for index, job in enumerate(jobs, start=1):
        print(
            f"JOB_{index}={job['priority']}:{job['stage']}:{job['target_day']}"
        )
    print("PROVIDER_CALLS=0")
    print("STATIC_DEPLOY=NO")
    print("FRONTEND_DEPLOY=NO")
    print("GEMINI_EXECUTION=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
