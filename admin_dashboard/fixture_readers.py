"""Fixed-path sanitized offline readers for an isolated, not-mounted pilot.

Fixture root is set by trusted host code, never a browser argument.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from data_lifecycle.readback_contracts import validate_api_semantic_health, validate_d1_snapshot
from .coverage import project_coverage
from .isolated import SharedFixtureCache


class FixtureReaders:
    def __init__(self, fixture_root: Path, *, days=None, start_day="2026-10-20",
                 end_day="2026-10-20", cache=None):
        self._root = Path(fixture_root)
        self._days = deepcopy(days or [])
        self._start = start_day
        self._end = end_day
        self._cache = cache if cache is not None else SharedFixtureCache()

    def _fixture(self, filename):
        # Fixed trusted filenames, not supplied by request.
        with (self._root / filename).open(encoding="utf-8") as f:
            return json.load(f)

    def coverage(self):
        snapshot = self._read_d1()
        days = deepcopy(self._days)
        snapshot_day = None
        if isinstance(snapshot, dict):
            binding = snapshot.get("job_binding") if isinstance(snapshot.get("job_binding"), dict) else {}
            scope = binding.get("scope") if isinstance(binding.get("scope"), dict) else {}
            snapshot_day = scope.get("day")
        for day in days:
            ptt = next((x for x in day.get("sources", []) if x.get("source") == "ptt"), None)
            if ptt is not None:
                ptt["target_evidence"] = deepcopy(snapshot) if snapshot and day.get("date") == snapshot_day else None
        return project_coverage(days, start_day=self._start, end_day=self._end)

    def _read_d1_with_cache(self):
        try:
            data = self._fixture("d1-job-readback.sanitized.json")
            validate_d1_snapshot(data)
            binding = data["job_binding"]
            key = (data["schema_version"], json.dumps(data["target"], sort_keys=True),
                   json.dumps(binding["scope"], sort_keys=True),
                   binding["manifest_digest"], data["verification"]["mode"])
            value, hit = self._cache.read(key, lambda: data)
            return value, ("hit" if hit else "miss")
        except (OSError, ValueError, KeyError, TypeError):
            return None, "unavailable"

    def _read_d1(self):
        return self._read_d1_with_cache()[0]

    def _read_archive_sync_job(self):
        try:
            data = self._fixture("archive-sync-jobs.sanitized.json")
            if data.get("schema_version") != "holoviewer-pr147-archive-monitor-fixture-set-v1" or data.get("sanitized") is not True:
                return None
            case = data.get("default_case")
            row = data.get("cases", {}).get(case) if isinstance(data.get("cases"), dict) else None
            return deepcopy(row) if isinstance(row, dict) else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def sync_monitor(self):
        snapshot, cache_status = self._read_d1_with_cache()
        return {"d1_snapshot": snapshot, "d1_cache_status": cache_status,
                "archive_sync_job": self._read_archive_sync_job()}

    def system_health(self):
        try:
            data = validate_api_semantic_health(self._fixture("api-semantic-health.sanitized.json"))
        except (OSError, ValueError, KeyError, TypeError):
            return {"components": {}}
        # HTTP 200 is reachability only. The semantic status must be independently
        # grounded in schema, watermark, source freshness and gap checks.
        probes = data["probes"]
        semantic_statuses = []
        reachability = []
        for p in probes:
            c = p.get("content_health") or {}
            if p.get("name") == "health":
                reachability.append({
                    "name": "health",
                    "http_status": p.get("http_status"),
                    "reachable": p.get("reachable"),
                    "semantic_status": p.get("semantic_status"),
                })
                continue
            if p.get("semantic_status") == "unhealthy":
                status = "unhealthy"
            elif c.get("gap") is True or c.get("source_freshness") == "stale":
                status = "degraded"
            else:
                valid = (p.get("schema_version")
                         and c.get("semantic_watermark")
                         and c.get("source_freshness") == "fresh"
                         and c.get("gap") is False
                         and c.get("coverage_status") not in {"partial", "unknown"})
                status = "healthy" if valid and p.get("semantic_status") == "healthy" else "unknown"
            semantic_statuses.append(status)
        if not semantic_statuses:
            overall = "unknown"
        elif "unhealthy" in semantic_statuses:
            overall = "unhealthy"
        elif "degraded" in semantic_statuses:
            overall = "degraded"
        elif "unknown" in semantic_statuses:
            overall = "unknown"
        else:
            overall = "healthy"
        health_statuses = [item.get("http_status") for item in reachability
                           if isinstance(item.get("http_status"), int)]
        component_http_status = health_statuses[0] if len(health_statuses) == 1 else None
        return {"components": {"Production API": {
            "observed_at": data["observed_at"], "http_status": component_http_status,
            "semantic_check": {
                "status": overall,
                "semantic_probe_statuses": semantic_statuses,
                "reachability_probes": reachability,
            },
            "evidence_source": "sanitized fixture only",
        }}}

    def injected(self):
        return {"data_coverage": self.coverage,
                "sync_monitor": self.sync_monitor,
                "system_health": self.system_health}
