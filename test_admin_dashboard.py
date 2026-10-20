from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ast
import io
import json
import unittest

from admin_dashboard import DashboardApplication, DashboardController, build_sync_monitor, build_system_health
from admin_dashboard.contracts import coverage_sync_consistency
from admin_dashboard.render import render_dashboard

NOW = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)


class DashboardTests(unittest.TestCase):
    def test_dashboard_package_has_no_writer_or_external_io_import(self):
        from pathlib import Path
        forbidden_external = {"subprocess", "requests", "http.client", "urllib.request"}
        for path in (Path(__file__).parent / "admin_dashboard").glob("*.py"):
            imports = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.add(node.module or "")
            self.assertTrue(forbidden_external.isdisjoint(imports), path.name)
            if path.name != "admission.py":
                self.assertNotIn("sqlite3", imports, path.name)

    def test_refresh_calls_readers_only_and_cooldown_bounds_reads(self):
        calls = []
        readers = {name: (lambda name=name: calls.append(name) or ({"sources": []} if name == "data_coverage" else {}))
                   for name in ("data_coverage", "daily_finalization", "sync_monitor", "system_health")}
        controller = DashboardController(readers, cooldown_seconds=30)
        first = controller.refresh(now=NOW)
        second = controller.refresh(now=NOW + timedelta(seconds=5))
        third = controller.refresh("sync_monitor", now=NOW + timedelta(seconds=31))
        self.assertEqual(calls, ["data_coverage", "daily_finalization", "sync_monitor", "system_health", "sync_monitor"])
        self.assertTrue(all(value["refresh"]["status"] == "refreshed" for value in first.values()))
        self.assertTrue(all(value["refresh"]["status"] == "cooldown" for value in second.values()))
        self.assertEqual(third["sync_monitor"]["refresh"]["status"], "refreshed")

    def test_failed_refresh_retains_payload_and_reports_error(self):
        state = {"fail": False}
        def reader():
            if state["fail"]:
                raise OSError("sanitized monitor read failed")
            return {"sources": [{"date": "2026-10-20", "completeness_status": "UNKNOWN"}]}
        controller = DashboardController({"data_coverage": reader}, cooldown_seconds=0)
        good = controller.refresh("data_coverage", now=NOW)["data_coverage"]
        state["fail"] = True
        failed = controller.refresh("data_coverage", now=NOW + timedelta(seconds=1))["data_coverage"]
        self.assertEqual(failed["availability"], "unavailable")
        self.assertEqual(failed["payload"], good["payload"])
        self.assertEqual(failed["error"]["code"], "source_unavailable")
        self.assertEqual(failed["error"]["message"], "read-only monitor source failed")
        self.assertEqual(failed["last_successful_read_at"], good["last_successful_read_at"])
        self.assertNotEqual(failed["read_at"], failed["last_successful_read_at"])
        self.assertEqual(failed["last_good_age_seconds"], 1.0)

    def test_missing_monitor_sources_are_unknown_or_unavailable(self):
        jobs = build_sync_monitor({}, now=NOW)["jobs"]
        self.assertTrue(all(job["status"] == "unknown" for job in jobs))
        health = build_system_health({}, now=NOW)["components"]
        self.assertTrue(all(row["status"] == "unavailable" for row in health))

    def test_stale_healthy_semantic_probe_downgrades_to_unknown(self):
        health = build_system_health({"components": {"Production API": {
            "http_status": 200, "observed_at": "2026-10-20T07:00:00Z",
            "semantic_check": {"status": "healthy"}, "evidence_source": "fixture",
        }}}, now=NOW, stale_after_seconds=120)["components"]
        api = next(row for row in health if row["component"] == "Production API")
        self.assertEqual(api["freshness"], "stale")
        self.assertEqual(api["status"], "unknown")

    def test_process_alive_and_http_200_do_not_imply_health(self):
        health = build_system_health({"components": {
            "Collector": {"process_alive": True, "observed_at": "2026-10-20T07:59:30Z"},
            "Production API": {"http_status": 200, "observed_at": "2026-10-20T07:59:30Z"},
        }}, now=NOW)["components"]
        self.assertEqual(next(x for x in health if x["component"] == "Collector")["status"], "unknown")
        self.assertEqual(next(x for x in health if x["component"] == "Production API")["status"], "unknown")

    def test_sync_failure_is_exposed_without_changing_coverage(self):
        monitor = build_sync_monitor({"publisher_checkpoint": {
            "job_id": "job-1", "state": "failed", "source_identity": "fixture",
        }, "publisher_observed_at": "2026-10-20T07:59:30Z", "job_telemetry": {
            "schema_version": "holoviewer-sync-job-evidence-v1", "components": {"Publisher": {
                "status": "failed", "attempt_count": 3, "error_code": "ACK_TIMEOUT",
                "error_message": "token=must-not-render", "error_sanitized": False,
            }},
        }}, now=NOW)
        publisher = monitor["jobs"][0]
        coverage = {"sources": [{"source": "ptt", "completeness_status": "COMPLETE"}]}
        self.assertEqual(publisher["status"], "failed")
        self.assertEqual(publisher["attempt_count"], 3)
        self.assertIsNone(publisher["error_message"])
        self.assertEqual(coverage_sync_consistency(coverage, monitor),
                         [{"code": "coverage-complete-sync-failed", "severity": "warning"}])

    def test_legacy_manifest_is_not_parsed_as_archive_delivery_job(self):
        monitor = build_sync_monitor({"r2_manifest": {
            "schema_version": "ptt-r2-archive-v1", "generated_at": "2026-10-20T07:59:30Z",
            "total_pushes": 3, "days": [{"coverage_status": "COMPLETE", "finalized": True}],
        }}, now=NOW)
        archive = next(job for job in monitor["jobs"] if job["component"] == "Archive")
        self.assertIsNone(archive["archive_coverage_status"])
        self.assertEqual(archive["status"], "unknown")
        self.assertIn("archive-delivery-job-evidence-unavailable", archive["contract_gaps"])

    def test_only_explicitly_sanitized_error_is_displayed_and_bounded(self):
        monitor = build_sync_monitor({"publisher_checkpoint": {"state": "failed"},
            "job_telemetry": {"schema_version": "holoviewer-sync-job-evidence-v1",
                              "components": {"Publisher": {"status": "failed",
                                  "error_message": "safe\n" + "x" * 300,
                                  "error_sanitized": True}}}}, now=NOW)
        message = monitor["jobs"][0]["error_message"]
        self.assertNotIn("\n", message)
        self.assertLessEqual(len(message), 240)

    def test_http_surface_rejects_writes_and_has_required_tabs(self):
        controller = DashboardController({}, cooldown_seconds=0)
        app = DashboardApplication(controller)
        captured = {}
        def start(status, headers): captured.update(status=status, headers=headers)
        body = b"".join(app({"REQUEST_METHOD": "POST", "PATH_INFO": "/admin/status"}, start))
        self.assertEqual(captured["status"], "405 Method Not Allowed")
        self.assertEqual(json.loads(body)["error"], "read-only endpoint")
        html = render_dashboard()
        for label in ("Data Coverage", "Daily Finalization", "Sync Monitor", "System Health", "重新整理全部"):
            self.assertIn(label, html)
        for forbidden_control in ("Retry Publisher", "Retry Repair", "Replay", "Re-sync", "Upload", "Deploy", "Restart Collector", "Restart Publisher"):
            self.assertNotIn(forbidden_control, html)
        self.assertIn('id="coverage-filter"', html)
        self.assertNotIn("method:'POST'", html)

    def test_status_get_refreshes_requested_section(self):
        controller = DashboardController({"data_coverage": lambda: {"sources": []}}, cooldown_seconds=0)
        app = DashboardApplication(controller)
        captured = {}
        def start(status, headers): captured.update(status=status)
        environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/admin/status",
                   "QUERY_STRING": "section=data_coverage", "wsgi.input": io.BytesIO()}
        body = json.loads(b"".join(app(environ, start)))
        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(body["data_coverage"]["availability"], "available")


if __name__ == "__main__":
    unittest.main()
