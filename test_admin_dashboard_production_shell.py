from __future__ import annotations

import ast
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

from admin_dashboard.admission import AdmissionRequest, SQLiteReadAdmissionController
from admin_dashboard.auth import AdminAuthenticator, AuthResult, FixtureAdminAuthenticator
from admin_dashboard.capabilities import (
    ArchiveReadScope, D1ReadScope, FakeProductionEvidenceReader,
    ProductionReaderConfig, SourceGate,
)
from admin_dashboard.dashboard import DashboardController
from admin_dashboard.http import DashboardApplication
from admin_dashboard.isolated import AuthenticatedDashboard
from admin_dashboard.production_shell import (
    EvidenceReaderSet, ProductionReadOnlyShell, select_reader_provider,
)


class _Creds:
    def __init__(self, allowed=()):
        self.allowed = set(allowed)

    def available(self, source):
        return source in self.allowed


class _ExplodingAuth:
    def authenticate(self, request_context):
        raise RuntimeError("secret auth backend detail")


class ProductionShellPhase1Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "admission.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def admission(self, limits=None):
        return SQLiteReadAdmissionController(
            self.state, source_limits=limits or {
                "d1": (6, 600), "archive": (6, 600), "api_semantic": (6, 600),
                "publisher": (6, 600), "collector": (6, 600),
            })

    def config(self, **enabled):
        def gate(source, credential=True):
            return SourceGate(bool(enabled.get(source, False)), credential)
        return ProductionReaderConfig(
            d1=gate("d1"), archive=gate("archive"), api_semantic=gate("api_semantic"),
            publisher=gate("publisher", False), collector=gate("collector", False),
        )

    # Auth 1-4
    def test_unauthorized_request_never_calls_reader(self):
        calls = []
        app = DashboardApplication(DashboardController({
            "data_coverage": lambda: calls.append(1) or {"days": []}
        }, cooldown_seconds=0))
        wrapped = AuthenticatedDashboard(app, FixtureAdminAuthenticator(allow=False))
        captured = {}
        body = b"".join(wrapped(
            {"REQUEST_METHOD": "GET", "PATH_INFO": "/admin/status",
             "QUERY_STRING": "section=data_coverage", "wsgi.input": io.BytesIO()},
            lambda status, headers: captured.update(status=status)))
        self.assertEqual(captured["status"], "401 Unauthorized")
        self.assertEqual(calls, [])
        self.assertEqual(json.loads(body), {"error": "unauthorized"})

    def test_authenticator_exception_denies_before_reader(self):
        calls = []
        app = DashboardApplication(DashboardController({
            "data_coverage": lambda: calls.append(1) or {"days": []}
        }, cooldown_seconds=0))
        wrapped = AuthenticatedDashboard(app, _ExplodingAuth())
        captured = {}
        wrapped({"REQUEST_METHOD": "GET", "PATH_INFO": "/admin/status"},
                lambda status, headers: captured.update(status=status))
        self.assertEqual(captured["status"], "401 Unauthorized")
        self.assertEqual(calls, [])

    def test_authorized_fixture_reader_works(self):
        calls = []
        app = DashboardApplication(DashboardController({
            "data_coverage": lambda: calls.append(1) or {"days": []}
        }, cooldown_seconds=0))
        wrapped = AuthenticatedDashboard(app, FixtureAdminAuthenticator())
        captured = {}
        wrapped({"REQUEST_METHOD": "GET", "PATH_INFO": "/admin/status",
                 "QUERY_STRING": "section=data_coverage"},
                lambda status, headers: captured.update(status=status))
        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(calls, [1])

    def test_auth_material_never_enters_browser_payload(self):
        result = AuthResult.allow("fixture-principal", "fixture")
        self.assertFalse(hasattr(result, "credential"))
        self.assertFalse(hasattr(result, "token"))
        app = DashboardApplication(DashboardController({
            "data_coverage": lambda: {"days": []}
        }, cooldown_seconds=0))
        wrapped = AuthenticatedDashboard(app, FixtureAdminAuthenticator())
        captured = {}
        body = b"".join(wrapped(
            {"REQUEST_METHOD": "GET", "PATH_INFO": "/admin/status",
             "QUERY_STRING": "section=data_coverage"},
            lambda status, headers: captured.update(status=status)))
        self.assertNotIn(b"fixture-principal", body)
        self.assertNotIn(b"legacy-fixture", body)

    # Admission 5-10
    def request(self, key="k", source="d1"):
        return AdmissionRequest(source, {"day": "2026-10-20"}, "bounded_sample",
                                "fixture-read", "bounded_read", key)

    def test_admission_within_budget(self):
        receipt = self.admission({"d1": (2, 600)}).admit(self.request(), now=1000)
        self.assertTrue(receipt.admitted)
        self.assertEqual(receipt.requests_used, 1)

    def test_admission_exceeded_fails_closed(self):
        ctrl = self.admission({"d1": (1, 600)})
        first = ctrl.admit(self.request("a"), now=1000)
        ctrl.release("a")
        second = ctrl.admit(self.request("b"), now=1001)
        self.assertTrue(first.admitted)
        self.assertFalse(second.admitted)
        self.assertEqual(second.reason, "budget_exceeded")

    def test_two_controller_instances_share_budget_state(self):
        one = self.admission({"d1": (1, 600)})
        two = SQLiteReadAdmissionController(self.state, source_limits={"d1": (1, 600)})
        self.assertTrue(one.admit(self.request("p1"), now=1000).admitted)
        one.release("p1")
        receipt = two.admit(self.request("p2"), now=1001)
        self.assertFalse(receipt.admitted)
        self.assertEqual(receipt.reason, "budget_exceeded")

    def test_concurrent_same_key_is_coalesced(self):
        one = self.admission({"d1": (6, 600)})
        two = SQLiteReadAdmissionController(self.state, source_limits={"d1": (6, 600)})
        self.assertTrue(one.admit(self.request("same"), now=1000).admitted)
        receipt = two.admit(self.request("same"), now=1001)
        self.assertFalse(receipt.admitted)
        self.assertTrue(receipt.coalesced)
        self.assertEqual(receipt.reason, "coalesced_inflight")
        one.release("same")

    def test_expired_window_resets_safely(self):
        ctrl = self.admission({"d1": (1, 10)})
        self.assertTrue(ctrl.admit(self.request("a"), now=1000).admitted)
        ctrl.release("a")
        later = ctrl.admit(self.request("b"), now=1011)
        self.assertTrue(later.admitted)
        self.assertEqual(later.requests_used, 1)

    def test_corrupt_admission_state_fails_closed(self):
        ctrl = self.admission({"d1": (1, 600)})
        self.state.write_bytes(b"not-a-sqlite-database")
        receipt = ctrl.admit(self.request("bad"), now=1000)
        self.assertFalse(receipt.admitted)
        self.assertEqual(receipt.reason, "admission_state_error")

    # Capability 11-15
    def test_reader_interface_has_no_arbitrary_sql(self):
        reader = FakeProductionEvidenceReader()
        self.assertFalse(hasattr(reader, "execute_sql"))
        self.assertFalse(hasattr(reader, "query"))

    def test_reader_interface_has_no_arbitrary_url(self):
        reader = FakeProductionEvidenceReader()
        self.assertFalse(hasattr(reader, "read_url"))
        self.assertFalse(hasattr(reader, "fetch_url"))

    def test_reader_interface_has_no_arbitrary_filesystem_path(self):
        reader = FakeProductionEvidenceReader()
        self.assertFalse(hasattr(reader, "read_path"))
        self.assertFalse(hasattr(reader, "open_file"))

    def test_disabled_source_is_unavailable_without_reader_call(self):
        fake = FakeProductionEvidenceReader(d1={"safe": True})
        shell = ProductionReadOnlyShell(fake, self.admission(), config=self.config(),
                                        credentials=_Creds({"d1"}))
        result = shell.read_d1(D1ReadScope("2026-10-20", ()))
        self.assertFalse(result["available"])
        self.assertEqual(result["error_code"], "source_disabled")
        self.assertEqual(fake.calls, [])

    def test_missing_credential_is_unavailable_without_reader_call(self):
        fake = FakeProductionEvidenceReader(d1={"safe": True})
        shell = ProductionReadOnlyShell(fake, self.admission(), config=self.config(d1=True),
                                        credentials=_Creds())
        result = shell.read_d1(D1ReadScope("2026-10-20", ()))
        self.assertFalse(result["available"])
        self.assertEqual(result["error_code"], "credential_missing")
        self.assertEqual(fake.calls, [])

    # Failure isolation 16-18
    def test_d1_failure_does_not_break_archive(self):
        fake = FakeProductionEvidenceReader(
            archive={"component": "Archive", "status": "unknown", "contract_gaps": []},
            failures={"d1": "boom"})
        shell = ProductionReadOnlyShell(
            fake, self.admission(), config=self.config(d1=True, archive=True),
            credentials=_Creds({"d1", "archive"}))
        readers = EvidenceReaderSet(shell)
        result = readers.sync_monitor()
        self.assertIsNone(result["d1_snapshot"])
        self.assertIsNotNone(result["archive_sync_job"])

    def test_archive_failure_does_not_break_system_health(self):
        fake = FakeProductionEvidenceReader(
            collector={"Collector": {"semantic_check": {"status": "healthy"}}},
            failures={"archive": "boom"})
        shell = ProductionReadOnlyShell(
            fake, self.admission(), config=self.config(archive=True, collector=True),
            credentials=_Creds({"archive"}))
        result = EvidenceReaderSet(shell).system_health()
        self.assertEqual(result["components"]["Collector"]["semantic_check"]["status"], "healthy")
        self.assertEqual(result["components"]["Archive"]["semantic_check"]["status"], "unavailable")

    def test_api_failure_does_not_break_coverage(self):
        fake = FakeProductionEvidenceReader(d1={"sanitized": True}, failures={"api_semantic": "boom"})
        shell = ProductionReadOnlyShell(
            fake, self.admission(), config=self.config(d1=True, api_semantic=True),
            credentials=_Creds({"d1", "api_semantic"}))
        result = EvidenceReaderSet(shell).coverage()
        self.assertEqual(result["days"][0]["status"], "UNKNOWN")
        self.assertEqual(fake.calls, ["d1"])

    # Privacy 19-21
    def test_reader_exception_text_is_not_leaked(self):
        fake = FakeProductionEvidenceReader(failures={"d1": "token=secret path=/Users/private"})
        shell = ProductionReadOnlyShell(
            fake, self.admission(), config=self.config(d1=True), credentials=_Creds({"d1"}))
        result = shell.read_d1(D1ReadScope("2026-10-20", ()))
        self.assertEqual(result["error_code"], "source_unavailable")
        self.assertNotIn("secret", json.dumps(result))

    def test_browser_shell_payload_scrubs_secret_token_account_and_path(self):
        fake = FakeProductionEvidenceReader(d1={
            "token": "secret", "account_id": "123", "path": "/Users/name/secret.json",
            "content_hash": "sha256:ok",
        })
        shell = ProductionReadOnlyShell(
            fake, self.admission(), config=self.config(d1=True), credentials=_Creds({"d1"}))
        readers = EvidenceReaderSet(shell)
        payload = DashboardController(readers.injected(), cooldown_seconds=0).refresh("data_coverage")
        encoded = json.dumps(payload).lower()
        self.assertNotIn('"token"', encoded)
        self.assertNotIn('"account_id"', encoded)
        self.assertNotIn("/users/name", encoded)
        self.assertIn("content_hash", encoded)

    def test_audit_schema_is_sanitized(self):
        ctrl = self.admission()
        ctrl.audit(principal="admin", source="d1", operation_class="snapshot",
                   scope_hash="sha256:scope", admitted=True, cache_hit=False,
                   duration_bucket="short", result_class="ok", error_code=None)
        con = ctrl._connect()
        columns = [row[1] for row in con.execute("PRAGMA table_info(admin_read_audit)")]
        con.close()
        forbidden = {"sql", "token", "credential", "url", "payload", "content", "author"}
        self.assertTrue(forbidden.isdisjoint(set(columns)))

    # Writer isolation 22-24
    def test_admin_modules_have_no_writer_uploader_deployer_imports(self):
        root = Path(__file__).parent / "admin_dashboard"
        forbidden = ("writer", "uploader", "deploy", "migration", "restart", "publisher_writer")
        hits = []
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.lower() for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").lower()]
                else:
                    continue
                if any(word in name for name in names for word in forbidden):
                    hits.append((path.name, names))
        self.assertEqual(hits, [])

    def test_write_methods_still_rejected(self):
        app = DashboardApplication(DashboardController({}, cooldown_seconds=0))
        for method in ("POST", "PUT", "DELETE"):
            captured = {}
            body = b"".join(app({"REQUEST_METHOD": method, "PATH_INFO": "/admin/status"},
                                lambda status, headers: captured.update(status=status)))
            self.assertEqual(captured["status"], "405 Method Not Allowed")
            self.assertEqual(json.loads(body)["error"], "read-only endpoint")

    def test_reader_capability_has_no_mutation_method(self):
        fake = FakeProductionEvidenceReader()
        for name in ("write", "upload", "deploy", "restart", "repair", "delete",
                     "backfill", "resync", "retry"):
            self.assertFalse(any(name in attr.lower() for attr in dir(fake)))

    def test_provider_selection_defaults_fixture_and_never_autodetects(self):
        fixture = {"fixture": True}
        self.assertIs(select_reader_provider(fixture_readers=fixture), fixture)
        with self.assertRaises(RuntimeError):
            select_reader_provider(mode="production", fixture_readers=fixture)

    def test_d1_scope_enforces_reviewed_bounds(self):
        D1ReadScope("2026-10-20", (), page_size=100, max_pages=5, query_groups=3)
        with self.assertRaises(ValueError):
            D1ReadScope("2026-10-20", (), page_size=101)
        with self.assertRaises(ValueError):
            D1ReadScope("2026-10-20", (), max_pages=6)
        with self.assertRaises(ValueError):
            D1ReadScope("2026-10-20", (), query_groups=4)


if __name__ == "__main__":
    unittest.main()
