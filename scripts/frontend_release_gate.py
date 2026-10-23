#!/usr/bin/env python3
"""Pure release-gate helpers for Owner-local frontend deployment."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Iterable, Sequence


class ReleaseGateError(RuntimeError):
    pass


def verify_lineage(head: str, origin_main: str, expected: str) -> None:
    if head != expected:
        raise ReleaseGateError(f"HEAD mismatch: {head} != {expected}")
    if origin_main != expected:
        raise ReleaseGateError(f"origin/main mismatch: {origin_main} != {expected}")


def validate_site_delta(rows: Iterable[str], target_event: str) -> list[str]:
    actual = sorted(row.strip() for row in rows if row.strip())
    expected = sorted([
        f"A\tsite/data/watchalong/events/{target_event}.json",
        "M\tsite/data/watchalong/manifest.json",
    ])
    if actual != expected:
        raise ReleaseGateError(
            "unexpected site delta: "
            + json.dumps({"expected": expected, "actual": actual}, ensure_ascii=False)
        )
    return actual


def _events_by_id(manifest: dict) -> dict[str, dict]:
    events = manifest.get("events")
    if not isinstance(events, list):
        raise ReleaseGateError("manifest.events must be a list")
    result: dict[str, dict] = {}
    for row in events:
        if not isinstance(row, dict) or not row.get("event_id"):
            raise ReleaseGateError("manifest event missing event_id")
        event_id = str(row["event_id"])
        if event_id in result:
            raise ReleaseGateError(f"duplicate event_id: {event_id}")
        result[event_id] = row
    return result


def validate_watchalong_addition(
    production: dict,
    candidate: dict,
    target_event: str,
) -> dict:
    prod = _events_by_id(production)
    cand = _events_by_id(candidate)
    if target_event in prod:
        raise ReleaseGateError(f"target already exists in Production: {target_event}")
    if target_event not in cand:
        raise ReleaseGateError(f"target missing from candidate: {target_event}")
    if set(cand) != set(prod) | {target_event}:
        missing = sorted(set(prod) - set(cand))
        extra = sorted(set(cand) - (set(prod) | {target_event}))
        raise ReleaseGateError(
            "candidate event set is not additive-only: "
            + json.dumps({"missing": missing, "extra": extra}, ensure_ascii=False)
        )
    for event_id, old in prod.items():
        new = cand[event_id]
        if old != new:
            raise ReleaseGateError(f"existing manifest entry changed: {event_id}")
    if candidate.get("event_count") != len(cand):
        raise ReleaseGateError("candidate event_count does not match events")
    if production.get("event_count") != len(prod):
        raise ReleaseGateError("production event_count does not match events")
    if len(cand) != len(prod) + 1:
        raise ReleaseGateError("candidate must add exactly one event")
    return {
        "production_count": len(prod),
        "candidate_count": len(cand),
        "old_entries_preserved": True,
        "existing_event_changed": False,
        "target_event": target_event,
    }


def bounded_retry(
    check: Callable[[], bool],
    delays: Sequence[float] = (0, 2, 4, 8, 12, 20),
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    """Return 1-based successful attempt; raise after bounded read-only retries."""
    last_error: Exception | None = None
    for attempt, delay in enumerate(delays, start=1):
        if delay:
            sleeper(delay)
        try:
            if check():
                return attempt
        except Exception as exc:  # caller decides whether transport failures are retryable
            last_error = exc
    if last_error:
        raise ReleaseGateError(f"readback did not converge: {last_error}") from last_error
    raise ReleaseGateError("readback did not converge")


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
