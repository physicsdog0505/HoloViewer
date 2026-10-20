"""Cache-aware, dependency-injected read-only dashboard refresh controller."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from .contracts import build_sync_monitor, build_system_health, coverage_sync_consistency
from .privacy import sanitize_for_browser

SECTIONS = ("data_coverage", "sync_monitor", "system_health")


class DashboardController:
    def __init__(self, readers: dict, *, cooldown_seconds: int = 30,
                 stale_after_seconds: int = 120):
        if cooldown_seconds < 0 or stale_after_seconds < 1:
            raise ValueError("invalid refresh policy")
        self._readers = dict(readers)
        self._cooldown = cooldown_seconds
        self._stale_after = stale_after_seconds
        self._cache: dict[str, dict] = {}

    def refresh(self, section: str | None = None, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        names = SECTIONS if section is None else (section,)
        if any(name not in SECTIONS for name in names):
            raise ValueError("unknown dashboard section")
        results = {name: self._refresh_one(name, now) for name in names}
        if section is None:
            coverage = results["data_coverage"].get("payload")
            monitor = results["sync_monitor"].get("payload")
            if isinstance(monitor, dict):
                monitor["coverage_consistency"] = coverage_sync_consistency(coverage, monitor)
        return results

    def _refresh_one(self, section: str, now: datetime) -> dict:
        previous = self._cache.get(section)
        if previous is not None:
            elapsed = (now - previous["read_at_dt"]).total_seconds()
            if elapsed < self._cooldown:
                result = deepcopy(previous["public"])
                result["refresh"] = {"status": "cooldown", "retry_after_seconds": self._cooldown - elapsed}
                last_success_dt = previous.get("last_success_dt")
                result["last_good_age_seconds"] = (
                    max(0.0, (now - last_success_dt).total_seconds())
                    if last_success_dt is not None else None
                )
                return result
        reader = self._readers.get(section)
        read_at = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            if not callable(reader):
                raise RuntimeError("monitor source unavailable")
            raw = reader()
            if section == "data_coverage":
                payload = raw
            elif section == "sync_monitor":
                payload = build_sync_monitor(raw, now=now, stale_after_seconds=self._stale_after)
            else:
                payload = build_system_health(raw, now=now, stale_after_seconds=self._stale_after)
            payload = sanitize_for_browser(payload)
            result = {"section": section, "availability": "available", "read_at": read_at,
                      "last_successful_read_at": read_at, "last_good_age_seconds": 0.0,
                      "error": None, "payload": payload,
                      "refresh": {"status": "refreshed", "retry_after_seconds": self._cooldown}}
        except Exception as exc:  # retain last-good data while exposing the read failure
            last_success_dt = previous.get("last_success_dt") if previous else None
            result = {"section": section, "availability": "unavailable", "read_at": read_at,
                      "last_successful_read_at": previous["public"].get("last_successful_read_at") if previous else None,
                      "last_good_age_seconds": (
                          max(0.0, (now - last_success_dt).total_seconds())
                          if last_success_dt is not None else None
                      ),
                      "error": {"code": type(exc).__name__,
                                "message": "read-only monitor source failed"},
                      "payload": deepcopy(previous["public"].get("payload")) if previous else None,
                      "refresh": {"status": "failed", "retry_after_seconds": self._cooldown}}
        self._cache[section] = {
            "read_at_dt": now,
            "last_success_dt": now if result["availability"] == "available"
                               else (previous.get("last_success_dt") if previous else None),
            "public": deepcopy(result),
        }
        return result
