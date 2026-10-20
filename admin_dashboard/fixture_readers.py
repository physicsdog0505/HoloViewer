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
        for day in days:
            ptt = next((x for x in day.get("sources", []) if x.get("source") == "ptt"), None)
            if ptt is not None:
                ptt["target_evidence"] = deepcopy(snapshot) if snapshot else None
        return project_coverage(days, start_day=self._start, end_day=self._end)

    def _read_d1(self):
        try:
            data = self._fixture("d1-job-readback.sanitized.json")
            validate_d1_snapshot(data)
            binding = data["job_binding"]
            key = (data["schema_version"], json.dumps(data["target"], sort_keys=True),
                   json.dumps(binding["scope"], sort_keys=True),
                   binding["manifest_digest"], data["verification"]["mode"])
            return self._cache.read(key, lambda: data)[0]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def sync_monitor(self):
        return {"d1_snapshot": self._read_d1()}

    def system_health(self):
        try:
            data = validate_api_semantic_health(self._fixture("api-semantic-health.sanitized.json"))
        except (OSError, ValueError, KeyError, TypeError):
            return {"components": {}}
        # HTTP 200 is reachability only. The semantic status must be independently
        # grounded in schema, watermark, source freshness and gap checks.
        probes = data["probes"]
        statuses = []
        for p in probes:
            c = p.get("content_health") or {}
            valid = (p.get("name") != "health" and p.get("schema_version")
                     and c.get("semantic_watermark") and c.get("source_freshness") == "fresh"
                     and c.get("gap") is False and c.get("coverage_status") not in {"partial", "unknown"})
            statuses.append("healthy" if valid and p.get("semantic_status") == "healthy"
                            else "degraded" if c.get("gap") is True or c.get("source_freshness") == "stale"
                            else "unknown")
        overall = "degraded" if "degraded" in statuses else "healthy" if statuses and all(s == "healthy" for s in statuses) else "unknown"
        return {"components": {"Production API": {
            "observed_at": data["observed_at"], "http_status": 200,
            "semantic_check": {"status": overall, "probe_statuses": statuses},
            "evidence_source": "sanitized fixture only",
        }}}

    def injected(self):
        return {"data_coverage": self.coverage,
                "sync_monitor": self.sync_monitor,
                "system_health": self.system_health}
