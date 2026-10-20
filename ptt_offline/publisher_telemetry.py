"""Sanitized durable telemetry sidecar for the #48 production Publisher.

Local-only operational evidence for read-only Admin Dashboard consumers.
Never opens SQLite, reads secrets, contacts Cloudflare, or changes retry/cadence.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "holoviewer-sync-job-evidence-v1"
SUCCESS_STATES = {"ACK", "NO_NEW_ROWS", "BASELINED", "PARTIAL_SUCCESS"}


def _atomic_json(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(body, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def load_existing(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    try:
        body = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(body, dict) or body.get("schema_version") != SCHEMA_VERSION:
        return {}
    return body


def update_publisher_telemetry(
    path: str | Path,
    result: dict[str, Any],
    *,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Persist one sanitized Publisher job-evidence snapshot.

    attempt_count is local durable process evidence. There is no automatic retry
    contract, so retry_after/backoff_seconds remain null.
    """
    if not isinstance(result, dict):
        raise TypeError("result must be a mapping")
    previous = load_existing(path)
    prior_item = (
        previous.get("components", {}).get("Publisher", {})
        if isinstance(previous.get("components"), dict) else {}
    )
    attempt_count = prior_item.get("attempt_count")
    attempt_count = attempt_count if isinstance(attempt_count, int) and attempt_count >= 0 else 0
    attempt_count += 1

    stamp = observed_at or result.get("observed_at")
    if not isinstance(stamp, str) or not stamp:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    status = str(result.get("status") or "UNKNOWN")
    last_successful = prior_item.get("last_successful_at")
    if status in SUCCESS_STATES:
        last_successful = stamp

    item = {
        "job_id": result.get("batch_id"),
        "last_attempted_at": stamp,
        "last_successful_at": last_successful,
        "status": (
            "failed" if status in {"STOP_RECONCILE", "REMOTE_UNCERTAIN"}
            else "completed" if status in SUCCESS_STATES
            else "waiting"
        ),
        "attempt_count": attempt_count,
        "retry_after": None,
        "backoff_seconds": None,
        "input_count": result.get("eligible"),
        "published_count": result.get("sent"),
        "verified_count": result.get("sent") if status == "ACK" else None,
        "error_code": result.get("error_class") if status == "STOP_RECONCILE" else None,
        "error_message": None,
        "error_sanitized": False,
        "last_progress_at": stamp,
        "publisher_result": status,
        "http_posts": result.get("http_posts"),
        "articles_checked": result.get("articles_checked"),
        "stale_fenced_rows": result.get("stale_fenced_rows"),
        "backlog_may_remain": result.get("backlog_may_remain"),
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "observed_at": stamp,
        "components": {"Publisher": item},
    }
    _atomic_json(Path(path), body)
    return body
