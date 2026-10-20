from __future__ import annotations

import io
import json
import threading
import unittest
from pathlib import Path
from datetime import datetime, timezone

from admin_dashboard.dashboard import DashboardController
from admin_dashboard.contracts import build_sync_monitor, coverage_sync_consistency
from admin_dashboard.http import DashboardApplication
from admin_dashboard.isolated import AuthenticatedDashboard, SharedFixtureCache
from admin_dashboard.fixture_readers import FixtureReaders
from admin_dashboard.render import render_dashboard

ROOT = Path(__file__).parent / "fixtures" / "data-lifecycle"


class IsolatedPilotTests(unittest.TestCase):
    def request(self, app, method="GET", path="/admin/status"):
        capture = {}
        def start(status, headers):
            capture["status"] = status
            capture["headers"] = dict(headers)
        result = b"".join(app({"REQUEST_METHOD": method, "PATH_INFO": path,
                               "QUERY_STRING": "", "wsgi.input": io.BytesIO()}, start))
        return capture["status"], result

    def test_auth_gate_precedes_handler(self):
        calls = []
        def handler(env, start):
            calls.append(1)
            start("200 OK", [])
            return [b"ok"]
        app = AuthenticatedDashboard(handler, lambda env: False)
        self.assertEqual(self.request(app)[0], "401 Unauthorized")
        self.assertFalse(calls)
        app = AuthenticatedDashboard(handler, lambda env: True)
        self.assertEqual(self.request(app)[0], "200 OK")
        self.assertEqual(len(calls), 1)

    def test_authenticated_fixture_only_get_and_write_rejection(self):
        readers = FixtureReaders(ROOT).injected()
        app = AuthenticatedDashboard(DashboardApplication(DashboardController(readers)),
                                     lambda env: True)
        status, body = self.request(app)
        self.assertEqual(status, "200 OK")
        payload = json.loads(body)
        self.assertEqual(payload["data_coverage"]["payload"]["days"][0]["status"], "UNKNOWN")
        archive = next(x for x in payload["sync_monitor"]["payload"]["jobs"] if x["component"] == "Archive")
        self.assertEqual(archive["status"], "completed")
        self.assertEqual(archive["target"], "workers-static-assets")
        for method in ("POST", "PUT", "DELETE"):
            self.assertEqual(self.request(app, method)[0], "405 Method Not Allowed")

    def test_legacy_and_bounded_never_complete_in_browser(self):
        html = render_dashboard()
        self.assertIn("full_partition", html)
        self.assertIn("complete_partition_proven", html)
        self.assertNotIn("target?.verified===true", html)
        self.assertNotIn("innerHTML", html)

    def test_fixture_readback_is_bounded_and_health_not_http(self):
        readers = FixtureReaders(ROOT)
        snapshot = readers._read_d1()
        self.assertEqual(snapshot["verification"]["mode"], "bounded_sample")
        self.assertFalse(snapshot["verification"]["job_verified"])
        api = readers.system_health()["components"]["Production API"]
        self.assertNotEqual(api["semantic_check"]["status"], "healthy")

    def test_shared_cache_coalesces_threads(self):
        cache = SharedFixtureCache(ttl_seconds=60)
        key = ("v1", "d1", "day", "sha256:fixture", "bounded_sample")
        count = []
        barrier = threading.Barrier(6)
        results = []
        def worker():
            barrier.wait()
            result, hit = cache.read(key, lambda: count.append(1) or {"value": 1})
            results.append(result)
        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=5)
        self.assertEqual(len(count), 1)
        self.assertEqual(len(results), 6)


    def archive_case(self, name):
        value = json.loads((ROOT / "archive-sync-jobs.sanitized.json").read_text(encoding="utf-8"))
        return value["cases"][name]

    def test_archive_placeholder_is_target_neutral_and_unknown(self):
        monitor = build_sync_monitor({})
        archive = next(x for x in monitor["jobs"] if x["component"] == "Archive")
        self.assertEqual(archive["status"], "unknown")
        self.assertIsNone(archive["target"])
        self.assertIn("archive-delivery-job-evidence-unavailable", archive["contract_gaps"])


    def test_archive_manifest_complete_without_job_stays_unknown(self):
        monitor = build_sync_monitor({"archive_sync_job": self.archive_case("manifest_complete_job_not_run")})
        archive = next(x for x in monitor["jobs"] if x["component"] == "Archive")
        self.assertEqual(archive["archive_coverage_status"], "COMPLETE")
        self.assertEqual(archive["status"], "unknown")
        self.assertEqual(archive["expected_aid_status"], "UNKNOWN")

    def test_archive_completed_job_does_not_promote_partial_coverage(self):
        monitor = build_sync_monitor({"archive_sync_job": self.archive_case("job_success_manifest_partial")})
        archive = next(x for x in monitor["jobs"] if x["component"] == "Archive")
        self.assertEqual(archive["status"], "completed")
        self.assertEqual(archive["archive_coverage_status"], "PARTIAL")
        self.assertEqual(archive["expected_aid_status"], "UNKNOWN")

    def test_archive_full_partition_verification_is_visible_only_as_job_verification(self):
        monitor = build_sync_monitor({"archive_sync_job": self.archive_case("static_success_full")})
        archive = next(x for x in monitor["jobs"] if x["component"] == "Archive")
        self.assertTrue(archive["job_verified"])
        self.assertEqual(archive["verification_mode"], "full_partition")
        self.assertEqual(archive["archive_coverage_status"], "COMPLETE")
        self.assertEqual(archive["expected_aid_status"], "UNKNOWN")

    def test_archive_bounded_sample_never_verifies_whole_job(self):
        monitor = build_sync_monitor({"archive_sync_job": self.archive_case("bounded_sample")})
        archive = next(x for x in monitor["jobs"] if x["component"] == "Archive")
        self.assertEqual(archive["verification_mode"], "bounded_sample")
        self.assertFalse(archive["job_verified"])

    def test_archive_expected_aid_missing_remains_unknown_when_delivery_verified(self):
        monitor = build_sync_monitor({"archive_sync_job": self.archive_case("static_success_full")})
        archive = next(x for x in monitor["jobs"] if x["component"] == "Archive")
        self.assertTrue(archive["job_verified"])
        self.assertEqual(archive["expected_aid_status"], "UNKNOWN")

    def test_archive_static_assets_target_is_not_r2(self):
        monitor = build_sync_monitor({"archive_sync_job": self.archive_case("static_success_full")})
        archive = next(x for x in monitor["jobs"] if x["component"] == "Archive")
        self.assertEqual(archive["target"], "workers-static-assets")
        html = render_dashboard()
        self.assertIn('"Static Assets"', html)

    def test_archive_projection_sensitive_fields_are_scrubbed_from_browser(self):
        row = self.archive_case("static_success_full")
        row["evidence_source_fields"]["token"] = "must-not-leak"
        row["evidence_source_fields"]["author"] = "must-not-leak"
        controller = DashboardController({"sync_monitor": lambda: {"archive_sync_job": row}}, cooldown_seconds=0)
        payload = controller.refresh("sync_monitor", now=datetime(2026, 10, 20, 11, 30, 30, tzinfo=timezone.utc))
        archive = next(x for x in payload["sync_monitor"]["payload"]["jobs"] if x["component"] == "Archive")
        self.assertNotIn("token", archive["evidence_source_fields"])
        self.assertNotIn("author", archive["evidence_source_fields"])

    def test_invalid_archive_projection_fails_closed(self):
        monitor = build_sync_monitor({"archive_sync_job": {"component": "Archive", "status": "completed"}})
        archive = next(x for x in monitor["jobs"] if x["component"] == "Archive")
        self.assertEqual(archive["status"], "unknown")
        self.assertIn("invalid-archive-sync-job-projection", archive["contract_gaps"])

    def test_d1_monitor_uses_job_binding_not_snapshot_id_and_exposes_cost(self):
        readers = FixtureReaders(ROOT)
        evidence = readers.sync_monitor()
        monitor = build_sync_monitor(evidence, now=datetime(2026, 10, 20, 11, 30, 30, tzinfo=timezone.utc))
        d1 = next(x for x in monitor["jobs"] if x["component"] == "D1 Snapshot")
        snapshot = evidence["d1_snapshot"]
        self.assertEqual(d1["job_id"], snapshot["job_binding"]["job_id"])
        self.assertNotEqual(d1["job_id"], snapshot["snapshot_id"])
        self.assertEqual(d1["snapshot_id"], snapshot["snapshot_id"])
        self.assertEqual(d1["manifest_digest"], snapshot["job_binding"]["manifest_digest"])
        self.assertEqual(d1["source_revision"], snapshot["job_binding"]["source_revision"])
        self.assertEqual(d1["verification_mode"], "bounded_sample")
        self.assertEqual(d1["queries_used"], 2)
        self.assertEqual(d1["max_queries"], 3)
        self.assertIn(d1["cache_status"], {"hit", "miss"})

    def test_multi_day_consistency_never_correlates_unscoped_jobs(self):
        coverage = {"days": [{"date": "2026-10-20", "status": "COMPLETE"}]}
        monitor = {"jobs": [{"component": "Publisher", "status": "failed", "scope": None}]}
        self.assertEqual(coverage_sync_consistency(coverage, monitor),
                         [{"code": "comparison-scope-unbound", "severity": "unknown"}])

    def test_browser_privacy_boundary_drops_secrets_but_keeps_content_hash(self):
        controller = DashboardController({"data_coverage": lambda: {
            "days": [{
                "date": "2026-10-20",
                "status": "UNKNOWN",
                "author": "must-not-leak",
                "content": "must-not-leak",
                "api_key": "must-not-leak",
                "nested": {
                    "token": "must-not-leak",
                    "content_hash": "sha256:" + "a" * 64,
                    "sidecar": "/Users/example/private/sidecar.json",
                    "api_path": "/health",
                },
            }]
        }}, cooldown_seconds=0)
        payload = controller.refresh("data_coverage", now=datetime(2026, 10, 20, 11, 30, 30, tzinfo=timezone.utc))
        day = payload["data_coverage"]["payload"]["days"][0]
        self.assertNotIn("author", day)
        self.assertNotIn("content", day)
        self.assertNotIn("api_key", day)
        self.assertNotIn("token", day["nested"])
        self.assertEqual(day["nested"]["content_hash"], "sha256:" + "a" * 64)
        self.assertEqual(day["nested"]["sidecar"], "[redacted-local-path]")
        self.assertEqual(day["nested"]["api_path"], "/health")

    def test_dashboard_payload_does_not_expose_sensitive_keys(self):
        readers = FixtureReaders(ROOT).injected()
        payload = DashboardController(readers, cooldown_seconds=0).refresh(
            now=datetime(2026, 10, 20, 11, 30, 30, tzinfo=timezone.utc))
        forbidden = {"author", "content", "cookie", "authorization", "api_key", "hmac_secret",
                     "password", "raw_error", "wrangler_credential", "filesystem_secret_path"}
        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertNotIn(str(key).lower(), forbidden)
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(payload)
        html = render_dashboard().lower()
        for marker in ("hmac secret", "wrangler credential", "filesystem secret path", "api key"):
            self.assertNotIn(marker, html)


    def test_semantic_health_aggregate_excludes_reachability_probe(self):
        readers = FixtureReaders(ROOT)
        health = readers.system_health()["components"]["Production API"]
        semantic = health["semantic_check"]
        self.assertEqual(semantic["status"], "degraded")
        self.assertTrue(semantic["reachability_probes"])
        self.assertNotIn("unknown", semantic["semantic_probe_statuses"])

    def test_healthy_semantic_probes_can_aggregate_healthy(self):
        readers = FixtureReaders(ROOT)
        original = readers._fixture
        def fixture(name):
            value = original(name)
            if name == "api-semantic-health.sanitized.json":
                value = json.loads(json.dumps(value))
                ptt = next(x for x in value["probes"] if x["name"] == "ptt_today")
                ptt["semantic_status"] = "healthy"
                ptt["reason"] = "schema-and-watermark-valid"
                ptt["content_health"]["gap"] = False
                ptt["content_health"]["coverage_status"] = "complete"
            return value
        readers._fixture = fixture
        health = readers.system_health()["components"]["Production API"]
        self.assertEqual(health["semantic_check"]["status"], "healthy")
        self.assertEqual(health["http_status"], 200)

    def test_http_status_comes_from_health_probe(self):
        readers = FixtureReaders(ROOT)
        original = readers._fixture
        def fixture_503(name):
            value = original(name)
            if name == "api-semantic-health.sanitized.json":
                value = json.loads(json.dumps(value))
                health = next(x for x in value["probes"] if x["name"] == "health")
                health["http_status"] = 503
                health["reachable"] = False
            return value
        readers._fixture = fixture_503
        component = readers.system_health()["components"]["Production API"]
        self.assertEqual(component["http_status"], 503)
        self.assertNotEqual(component["semantic_check"]["status"], "healthy")

    def test_missing_health_probe_exposes_null_http_status(self):
        readers = FixtureReaders(ROOT)
        original = readers._fixture
        def fixture_no_health(name):
            value = original(name)
            if name == "api-semantic-health.sanitized.json":
                value = json.loads(json.dumps(value))
                value["probes"] = [x for x in value["probes"] if x["name"] != "health"]
            return value
        readers._fixture = fixture_no_health
        component = readers.system_health()["components"]["Production API"]
        self.assertIsNone(component["http_status"])

    def test_current_health_probe_200_is_preserved(self):
        readers = FixtureReaders(ROOT)
        component = readers.system_health()["components"]["Production API"]
        self.assertEqual(component["http_status"], 200)

    def test_health_only_fixture_cannot_certify_healthy(self):
        readers = FixtureReaders(ROOT)
        original = readers._fixture
        def fixture(name):
            if name == "api-semantic-health.sanitized.json":
                return {
                    "schema_version": "holoviewer-api-semantic-health-v1",
                    "sanitized": True,
                    "observed_at": "2026-10-20T11:30:00Z",
                    "overall_status": "unknown",
                    "probes": [{
                        "name": "health", "http_status": 200, "reachable": True,
                        "semantic_status": "unknown", "schema_version": "v1",
                        "observed_at": "2026-10-20T11:30:00Z"
                    }],
                    "query_budget": {"http_requests_used": 1, "http_requests_max": 4,
                                     "cache_ttl_seconds": 60},
                    "contract_gaps": ["fixture-only"]
                }
            return original(name)
        readers._fixture = fixture
        health = readers.system_health()["components"]["Production API"]
        self.assertEqual(health["semantic_check"]["status"], "unknown")

    def test_missing_fixture_fails_closed(self):
        readers = FixtureReaders(ROOT / "nonexistent")
        self.assertEqual(readers.coverage()["days"][0]["status"], "UNKNOWN")
        self.assertEqual(readers.system_health()["components"], {})


if __name__ == "__main__":
    unittest.main()
