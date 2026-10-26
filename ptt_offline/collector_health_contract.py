"""Stable Collector health normalization contract for the 07:30 gate.

This module contains only the reviewed #48 health classifier. It intentionally
owns no daily completeness, repair, archive, or publication semantics.
"""
from __future__ import annotations

from typing import Any


def classify_collector_health(health: dict[str,Any] | None) -> dict[str,Any]:
    """Normalize Collector health evidence without performing recovery."""
    required=("process_alive","heartbeat_fresh","live_context_valid","frontier_progressing")
    if not isinstance(health,dict):
        return {
            "status":"UNHEALTHY",
            "healthy":False,
            "failure_codes":["collector-health-unavailable"],
            "live_aid":None,
            "frontier":None,
        }
    failures=[]
    for key in required:
        if health.get(key) is not True:
            failures.append({
                "process_alive":"collector-process-dead",
                "heartbeat_fresh":"collector-heartbeat-stale",
                "live_context_valid":"collector-live-context-invalid",
                "frontier_progressing":"collector-frontier-stalled",
            }[key])
    return {
        "status":"HEALTHY" if not failures else "UNHEALTHY",
        "healthy":not failures,
        "failure_codes":failures,
        "live_aid":health.get("live_aid"),
        "frontier":health.get("frontier"),
    }
