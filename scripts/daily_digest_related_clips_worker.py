#!/usr/bin/env python3
"""Persistent Terminal worker for Daily Digest related-clips enrichment."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from scripts.daily_digest_related_clips_runtime import (
    RuntimeError334,
    atomic_write_json,
    build_due_jobs,
    discover_accepted_receipts,
    empty_queue,
    empty_state,
    execute_job,
    load_json_or,
    pending_backfill_days,
    record_attempt,
    validate_queue,
    validate_state,
)

TAIPEI = ZoneInfo("Asia/Taipei")
LIVE_ORIGIN = "https://holoviewer-daily-digest-static-assets.singlebagel.workers.dev"


def http_readback(path: str, timeout: float = 30.0) -> bytes:
    request = Request(
        LIVE_ORIGIN + path,
        headers={"User-Agent": "Holodocchi-RelatedClips-Worker/1"},
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _today(now: datetime | None = None) -> str:
    return (now or datetime.now(TAIPEI)).astimezone(TAIPEI).date().isoformat()


def _scheduled_today(now: datetime, hour: int, minute: int) -> datetime:
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def last_execute_day(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict) or payload.get("mode") != "EXECUTE":
        return ""
    return str(payload.get("today") or "")


def write_cycle_receipt(path: Path, result: dict) -> None:
    if result.get("mode") != "EXECUTE":
        return
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "kind": "holodocchi.daily_digest.related_clips.worker_receipt",
            "mode": "EXECUTE",
            "today": result.get("today"),
            "due_jobs": result.get("due_jobs"),
            "completed_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        },
    )


def run_cycle(
    *,
    state_path: Path,
    accepted_receipts_dir: Path,
    backfill_queue_path: Path | None,
    private_repo: Path,
    corpus_root: Path,
    sidecar_root: Path,
    public_repo: Path,
    public_expected_head: str,
    python_executable: str,
    today: str,
    backfill_limit: int,
    execute: bool,
    holodex_api_key_env: str = "HOLODEX_API_KEY",
    readback_fetcher=http_readback,
) -> dict:
    state = validate_state(load_json_or(state_path, empty_state()))
    accepted, candidate_paths = discover_accepted_receipts(accepted_receipts_dir)

    queue_days: list[str] = []
    if backfill_queue_path:
        queue = validate_queue(load_json_or(backfill_queue_path, empty_queue()))
        queue_days = pending_backfill_days(
            queue,
            state,
            limit=backfill_limit,
        )

    jobs = build_due_jobs(
        state,
        accepted_days=accepted,
        today=today,
        backfill_queue=queue_days,
        backfill_limit=backfill_limit,
    )

    results: list[dict] = []
    for job in jobs:
        target_day = str(job["target_day"])
        candidate_path = candidate_paths.get(target_day, "")
        if not candidate_path:
            message = "accepted public candidate unavailable"
            record_attempt(
                state,
                target_day=target_day,
                stage=str(job["stage"]),
                attempted_at=datetime.now(TAIPEI).isoformat(timespec="seconds"),
                error=message,
            )
            results.append(
                {
                    "target_day": target_day,
                    "stage": job["stage"],
                    "status": "skipped",
                    "error": message,
                }
            )
            continue

        try:
            result = execute_job(
                state,
                job=job,
                candidate_path=candidate_path,
                private_repo=private_repo,
                corpus_root=corpus_root,
                sidecar_root=sidecar_root,
                public_repo=public_repo,
                public_expected_head=public_expected_head,
                python_executable=python_executable,
                holodex_api_key_env=holodex_api_key_env,
                execute=execute,
                readback_fetcher=readback_fetcher if execute else None,
            )
        except Exception as exc:
            record_attempt(
                state,
                target_day=target_day,
                stage=str(job["stage"]),
                attempted_at=datetime.now(TAIPEI).isoformat(timespec="seconds"),
                error=str(exc),
            )
            results.append(
                {
                    "target_day": target_day,
                    "stage": job["stage"],
                    "status": "error",
                    "error": str(exc),
                }
            )
            continue

        results.append(
            {
                "target_day": target_day,
                "stage": job["stage"],
                "status": "complete" if execute else "planned",
                "production_mutation": result["production_mutation"],
                **(
                    {
                        "sidecar_sha256": result["sidecar_sha256"],
                        "live_sha256": result["live_sha256"],
                        "clip_count": result["clip_count"],
                    }
                    if execute
                    else {}
                ),
            }
        )

    atomic_write_json(state_path, state)
    return {
        "schema_version": 1,
        "kind": "holodocchi.daily_digest.related_clips.worker_cycle",
        "today": today,
        "mode": "EXECUTE" if execute else "DRY_RUN",
        "due_jobs": len(jobs),
        "results": results,
        "provider_calls_allowed": bool(execute),
        "static_deploy_allowed": bool(execute),
        "frontend_deploy": False,
        "gemini_execution": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--accepted-receipts-dir", required=True, type=Path)
    parser.add_argument("--backfill-queue", type=Path)
    parser.add_argument("--private-repo", required=True, type=Path)
    parser.add_argument("--corpus-root", required=True, type=Path)
    parser.add_argument("--sidecar-root", required=True, type=Path)
    parser.add_argument("--public-repo", required=True, type=Path)
    parser.add_argument("--public-expected-head", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--holodex-api-key-env", default="HOLODEX_API_KEY")
    parser.add_argument("--backfill-limit", type=int, default=5)
    parser.add_argument("--hour", type=int, default=12)
    parser.add_argument("--minute", type=int, default=0)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--today")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--run-receipt", type=Path)
    parser.add_argument("--force-once", action="store_true")
    args = parser.parse_args(argv)

    if not (0 <= args.hour <= 23 and 0 <= args.minute <= 59):
        parser.error("invalid schedule time")
    if args.poll_seconds < 5:
        parser.error("poll-seconds must be >= 5")
    if args.backfill_limit < 0:
        parser.error("backfill-limit must be non-negative")
    if args.execute and not os.environ.get(args.holodex_api_key_env, "").strip():
        parser.error(
            f"--execute requires non-empty environment variable {args.holodex_api_key_env}"
        )

    run_receipt = (
        args.run_receipt.expanduser().resolve()
        if args.run_receipt
        else args.state.expanduser().resolve().with_name("last-worker-run.json")
    )

    kwargs = {
        "state_path": args.state.expanduser().resolve(),
        "accepted_receipts_dir": args.accepted_receipts_dir.expanduser().resolve(),
        "backfill_queue_path": (
            args.backfill_queue.expanduser().resolve()
            if args.backfill_queue
            else None
        ),
        "private_repo": args.private_repo.expanduser().resolve(),
        "corpus_root": args.corpus_root.expanduser().resolve(),
        "sidecar_root": args.sidecar_root.expanduser().resolve(),
        "public_repo": args.public_repo.expanduser().resolve(),
        "public_expected_head": args.public_expected_head,
        "python_executable": args.python,
        "backfill_limit": args.backfill_limit,
        "execute": args.execute,
        "holodex_api_key_env": args.holodex_api_key_env,
    }

    if args.once:
        selected_day = args.today or _today()
        if (
            args.execute
            and not args.force_once
            and last_execute_day(run_receipt) == selected_day
        ):
            print(json.dumps({
                "status": "ALREADY_RAN_TODAY",
                "today": selected_day,
                "mode": "EXECUTE",
                "production_mutation": "NO",
            }, ensure_ascii=False, sort_keys=True))
            return 0
        try:
            result = run_cycle(today=selected_day, **kwargs)
            write_cycle_receipt(run_receipt, result)
        except (OSError, RuntimeError334) as exc:
            print(f"ERROR={exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    print(
        json.dumps(
            {
                "status": "WORKER_STARTED",
                "schedule_timezone": "Asia/Taipei",
                "schedule": f"{args.hour:02d}:{args.minute:02d}",
                "mode": "EXECUTE" if args.execute else "DRY_RUN",
                "frontend_deploy": False,
                "gemini_execution": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )

    last_run_day = last_execute_day(run_receipt) if args.execute else ""
    while True:
        now = datetime.now(TAIPEI)
        today = now.date().isoformat()
        scheduled = _scheduled_today(now, args.hour, args.minute)
        if now >= scheduled and last_run_day != today:
            try:
                result = run_cycle(today=today, **kwargs)
                write_cycle_receipt(run_receipt, result)
                print(
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    flush=True,
                )
                last_run_day = today
            except Exception as exc:
                print(f"related-clips-worker: {exc}", file=sys.stderr, flush=True)
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
