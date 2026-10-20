from __future__ import annotations

import io
import json
import threading
import unittest
from pathlib import Path
from datetime import datetime, timezone

from admin_dashboard.dashboard import DashboardController
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
        self.assertEqual(payload["sync_monitor"]["payload"]["jobs"][2]["status"], "unknown")
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

    def test_missing_fixture_fails_closed(self):
        readers = FixtureReaders(ROOT / "nonexistent")
        self.assertEqual(readers.coverage()["days"][0]["status"], "UNKNOWN")
        self.assertEqual(readers.system_health()["components"], {})


if __name__ == "__main__":
    unittest.main()
