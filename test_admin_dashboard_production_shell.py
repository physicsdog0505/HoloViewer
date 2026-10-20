from __future__ import annotations

import ast
import io
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest

from admin_dashboard.admission import AdmissionRequest, SQLiteReadAdmissionController
from admin_dashboard.auth import AdminAuthenticator, AuthResult, FixtureAdminAuthenticator
from admin_dashboard.capabilities import (
    ArchiveReadScope, D1ReadScope, FakeProductionEvidenceReader,
    ProductionReaderConfig, SourceGate,
)
from admin_dashboard.dashboard import DashboardController
from admin_dashboard.http import DashboardApplication
from admin_dashboard.host_boundary import InternalExposureConfig, evaluate_internal_exposure
from admin_dashboard.integration import build_internal_admin_application
from admin_dashboard.isolated import AuthenticatedDashboard
from admin_dashboard.production_shell import (
    EvidenceReaderSet, ProductionReadOnlyShell, select_reader_provider,
)




def _process_admit(path, key, now, queue):
    ctrl = SQLiteReadAdmissionController(Path(path), source_limits={"d1": (1, 600)})
    req = AdmissionRequest("d1", {"day": "2026-10-20"}, "bounded_sample",
                           "d1_snapshot", "bounded_read", key)
    receipt = ctrl.admit(req, now=now)
    if receipt.admitted:
        ctrl.release(key)
    queue.put((receipt.admitted, receipt.reason, receipt.requests_used))

class _Creds:
    def __init__(self, allowed=()):
        self.allowed = set(allowed)

    def available(self, source):
        return source in self.allowed




def _process_cached_d1(path, value, fail_reader, queue):
    admission = SQLiteReadAdmissionController(Path(path), source_limits={"d1": (6, 600)})
    failures = {"d1": "reader-should-not-run"} if fail_reader else {}
    fake = FakeProductionEvidenceReader(d1=value, failures=failures)
    config = ProductionReaderConfig(d1=SourceGate(True, True))
    shell = ProductionReadOnlyShell(fake, admission, config=config, credentials=_Creds({"d1"}))
    result = shell.read_d1(D1ReadScope("2026-10-20", ()))
    queue.put({
        "available": result["available"],
        "error_code": result["error_code"],
        "reader_calls": list(fake.calls),
        "cache_hit": bool((result.get("admission") or {}).get("cache_hit")),
    })

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

    def test_authenticated_principals_are_distinct_in_audit_but_not_browser(self):
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "data-lifecycle" /
             "d1-job-readback.sanitized.json").read_text(encoding="utf-8"))
        admission = self.admission()
        fake = FakeProductionEvidenceReader(d1=fixture)
        shell = ProductionReadOnlyShell(
            fake, admission, config=self.config(d1=True), credentials=_Creds({"d1"}))
        controller = DashboardController(EvidenceReaderSet(shell).injected(), cooldown_seconds=0)

        bodies = []
        for principal, section in (("admin-a", "data_coverage"), ("admin-b", "sync_monitor")):
            app = AuthenticatedDashboard(
                DashboardApplication(controller),
                FixtureAdminAuthenticator(principal=principal))
            captured = {}
            body = b"".join(app(
                {"REQUEST_METHOD": "GET", "PATH_INFO": "/admin/status",
                 "QUERY_STRING": "section=" + section, "wsgi.input": io.BytesIO()},
                lambda status, headers: captured.update(status=status)))
            self.assertEqual(captured["status"], "200 OK")
            bodies.append(body)

        con = admission._connect()
        principals = [row[0] for row in con.execute(
            "SELECT DISTINCT principal FROM admin_read_audit WHERE source='d1' ORDER BY principal")]
        con.close()
        self.assertEqual(principals, ["admin-a", "admin-b"])
        combined = b"".join(bodies)
        self.assertNotIn(b"admin-a", combined)
        self.assertNotIn(b"admin-b", combined)

    # Admission 5-10
    def request(self, key="k", source="d1", *, mode="bounded_sample", cost_class="bounded_read"):
        request_class = {
            "d1": "d1_snapshot", "archive": "archive_delivery",
            "api_semantic": "api_semantic_health",
            "publisher": "publisher_evidence", "collector": "collector_evidence",
        }[source]
        return AdmissionRequest(source, {"day": "2026-10-20"}, mode,
                                request_class, cost_class, key)

    def test_admission_within_budget(self):
        receipt = self.admission({"d1": (2, 600)}).admit(self.request(), now=1000)
        self.assertTrue(receipt.admitted)
        self.assertEqual(receipt.requests_used, 1)


    def test_automatic_full_partition_is_denied_by_admission_policy(self):
        ctrl = self.admission({"d1": (6, 600)})
        receipt = ctrl.admit(self.request("full", mode="full_partition"), now=1000)
        self.assertFalse(receipt.admitted)
        self.assertEqual(receipt.reason, "admission_denied")

    def test_manual_full_partition_requires_explicit_manual_cost_class(self):
        ctrl = self.admission({"d1": (6, 600)})
        receipt = ctrl.admit(
            self.request("full-manual", mode="full_partition", cost_class="manual_full_partition"),
            now=1000)
        self.assertTrue(receipt.admitted)

    def test_admission_exceeded_fails_closed(self):
        ctrl = self.admission({"d1": (1, 600)})
        first = ctrl.admit(self.request("a"), now=1000)
        ctrl.release("a")
        second = ctrl.admit(self.request("b"), now=1001)
        self.assertTrue(first.admitted)
        self.assertFalse(second.admitted)
        self.assertEqual(second.reason, "budget_exceeded")

    def test_two_processes_share_budget_state(self):
        ctx = multiprocessing.get_context("spawn")
        q1, q2 = ctx.Queue(), ctx.Queue()
        p1 = ctx.Process(target=_process_admit, args=(str(self.state), "p1", 1000, q1))
        p1.start(); p1.join(10)
        self.assertEqual(p1.exitcode, 0)
        self.assertEqual(q1.get(timeout=2)[0], True)
        p2 = ctx.Process(target=_process_admit, args=(str(self.state), "p2", 1001, q2))
        p2.start(); p2.join(10)
        self.assertEqual(p2.exitcode, 0)
        admitted, reason, used = q2.get(timeout=2)
        self.assertFalse(admitted)
        self.assertEqual(reason, "budget_exceeded")
        self.assertEqual(used, 1)

    def test_two_processes_reuse_validated_shared_d1_result_cache(self):
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "data-lifecycle" /
             "d1-job-readback.sanitized.json").read_text(encoding="utf-8"))
        ctx = multiprocessing.get_context("spawn")
        q1, q2 = ctx.Queue(), ctx.Queue()
        p1 = ctx.Process(target=_process_cached_d1,
                         args=(str(self.state), fixture, False, q1))
        p1.start(); p1.join(10)
        self.assertEqual(p1.exitcode, 0)
        first = q1.get(timeout=2)
        self.assertTrue(first["available"])
        self.assertEqual(first["reader_calls"], ["d1"])
        self.assertFalse(first["cache_hit"])

        p2 = ctx.Process(target=_process_cached_d1,
                         args=(str(self.state), fixture, True, q2))
        p2.start(); p2.join(10)
        self.assertEqual(p2.exitcode, 0)
        second = q2.get(timeout=2)
        self.assertTrue(second["available"])
        self.assertEqual(second["reader_calls"], [])
        self.assertTrue(second["cache_hit"])

    def test_cache_hit_receipt_does_not_consume_new_quota(self):
        ctrl = self.admission({"d1": (2, 600)})
        req = self.request("cache-key")
        first = ctrl.admit(req, now=1000)
        self.assertTrue(first.admitted)
        ctrl.release("cache-key")
        receipt = ctrl.cache_hit_receipt(req, now=1001)
        self.assertTrue(receipt.admitted)
        self.assertEqual(receipt.reason, "cache_hit")
        self.assertTrue(receipt.cache_hit)
        self.assertEqual(receipt.requests_used, 1)

    def test_result_cache_ttl_expires_at_sixty_seconds(self):
        ctrl = self.admission({"d1": (6, 600)})
        ctrl.cache_put("cache-key", "d1", {"sanitized": True}, ttl_seconds=60, now=1000)
        value, hit = ctrl.cache_get("cache-key", now=1059)
        self.assertTrue(hit)
        self.assertEqual(value, {"sanitized": True})
        value, hit = ctrl.cache_get("cache-key", now=1060)
        self.assertFalse(hit)
        self.assertIsNone(value)

    def test_corrupt_cached_d1_evidence_fails_closed_without_reader_fallback(self):
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "data-lifecycle" /
             "d1-job-readback.sanitized.json").read_text(encoding="utf-8"))
        fake = FakeProductionEvidenceReader(d1=fixture)
        shell = ProductionReadOnlyShell(
            fake, self.admission(), config=self.config(d1=True), credentials=_Creds({"d1"}))
        first = shell.read_d1(D1ReadScope("2026-10-20", ()))
        self.assertTrue(first["available"])
        con = shell._admission._connect()
        con.execute("UPDATE read_result_cache SET value_json=?",
                    ('{"schema_version":"broken"}',))
        con.close()
        fake.calls.clear()
        second = shell.read_d1(D1ReadScope("2026-10-20", ()))
        self.assertFalse(second["available"])
        self.assertEqual(second["error_code"], "cache_state_error")
        self.assertEqual(fake.calls, [])

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


    def test_wildcard_bind_is_not_isolation_proof(self):
        decision = evaluate_internal_exposure(
            InternalExposureConfig(bind_host="0.0.0.0", behind_authenticated_proxy=True,
                                   internal_network_proven=True))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "wildcard_bind_unproven")

    def test_loopback_internal_boundary_is_allowed(self):
        decision = evaluate_internal_exposure(InternalExposureConfig(bind_host="127.0.0.1"))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.mode, "loopback")

    def test_public_route_is_always_denied(self):
        decision = evaluate_internal_exposure(
            InternalExposureConfig(bind_host="127.0.0.1", public_route_exposed=True))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "public_route_forbidden")


    def test_internal_composition_rejects_wildcard_before_mount(self):
        controller = DashboardController({}, cooldown_seconds=0)
        with self.assertRaises(RuntimeError):
            build_internal_admin_application(
                controller=controller,
                authenticator=FixtureAdminAuthenticator(),
                exposure_config=InternalExposureConfig(bind_host="0.0.0.0"))

    def test_internal_composition_accepts_loopback_and_keeps_auth_first(self):
        calls = []
        controller = DashboardController({
            "data_coverage": lambda: calls.append("reader") or {"days": []}
        }, cooldown_seconds=0)
        app = build_internal_admin_application(
            controller=controller,
            authenticator=FixtureAdminAuthenticator(allow=False),
            exposure_config=InternalExposureConfig(bind_host="127.0.0.1"))
        captured = {}
        app({"REQUEST_METHOD": "GET", "PATH_INFO": "/admin/status",
             "QUERY_STRING": "section=data_coverage"},
            lambda status, headers: captured.update(status=status))
        self.assertEqual(captured["status"], "401 Unauthorized")
        self.assertEqual(calls, [])

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

    def test_disabled_and_credential_denials_are_audited_with_request_principal(self):
        admission = self.admission()
        fake = FakeProductionEvidenceReader(d1={"safe": True})
        shell = ProductionReadOnlyShell(fake, admission, config=self.config(),
                                        credentials=_Creds(), principal="admin-static")
        shell.read_d1(D1ReadScope("2026-10-20", ()))
        con = admission._connect()
        row = con.execute(
            "SELECT principal,admitted,error_code FROM admin_read_audit "
            "WHERE source='d1' ORDER BY id DESC LIMIT 1").fetchone()
        con.close()
        self.assertEqual(row, ("admin-static", 0, "source_disabled"))

    def test_missing_credential_is_unavailable_without_reader_call(self):
        fake = FakeProductionEvidenceReader(d1={"safe": True})
        shell = ProductionReadOnlyShell(fake, self.admission(), config=self.config(d1=True),
                                        credentials=_Creds())
        result = shell.read_d1(D1ReadScope("2026-10-20", ()))
        self.assertFalse(result["available"])
        self.assertEqual(result["error_code"], "credential_missing")
        self.assertEqual(fake.calls, [])


    def test_credential_provider_exception_fails_closed_without_reader_call(self):
        class BadCreds:
            def available(self, source):
                raise RuntimeError("secret credential backend detail")
        fake = FakeProductionEvidenceReader(d1={"safe": True})
        shell = ProductionReadOnlyShell(
            fake, self.admission(), config=self.config(d1=True), credentials=BadCreds())
        result = shell.read_d1(D1ReadScope("2026-10-20", ()))
        self.assertFalse(result["available"])
        self.assertEqual(result["error_code"], "credential_missing")
        self.assertEqual(fake.calls, [])

    def test_shell_disabled_sources_render_unavailable_not_unknown(self):
        shell = ProductionReadOnlyShell(
            FakeProductionEvidenceReader(), self.admission(), config=self.config(),
            credentials=_Creds())
        raw = EvidenceReaderSet(shell).sync_monitor()
        from admin_dashboard.contracts import build_sync_monitor
        monitor = build_sync_monitor(raw)
        states = {x["component"]: x["status"] for x in monitor["jobs"]}
        self.assertEqual(states["Publisher"], "unavailable")
        self.assertEqual(states["Archive"], "unavailable")
        self.assertEqual(states["D1 Snapshot"], "unavailable")

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

    def test_unsanitized_d1_evidence_is_rejected_before_browser_and_cache(self):
        fake = FakeProductionEvidenceReader(d1={
            "schema_version": "holoviewer-d1-sanitized-snapshot-v1",
            "sanitized": True,
            "token": "secret", "account_id": "123", "path": "/Users/name/secret.json",
        })
        shell = ProductionReadOnlyShell(
            fake, self.admission(), config=self.config(d1=True), credentials=_Creds({"d1"}))
        readers = EvidenceReaderSet(shell)
        payload = DashboardController(readers.injected(), cooldown_seconds=0).refresh("data_coverage")
        encoded = json.dumps(payload).lower()
        self.assertNotIn('"token"', encoded)
        self.assertNotIn('"account_id"', encoded)
        self.assertNotIn("/users/name", encoded)
        self.assertIn("cache_state_error", encoded)


    def test_audit_failure_turns_read_unavailable(self):
        class BadAudit(SQLiteReadAdmissionController):
            def audit(self, **kwargs):
                raise RuntimeError("local audit failed")
        admission = BadAudit(self.state, source_limits={"d1": (6, 600)})
        fake = FakeProductionEvidenceReader(d1={"safe": True})
        shell = ProductionReadOnlyShell(
            fake, admission, config=self.config(d1=True), credentials=_Creds({"d1"}))
        result = shell.read_d1(D1ReadScope("2026-10-20", ()))
        self.assertFalse(result["available"])
        self.assertEqual(result["error_code"], "source_unavailable")
        self.assertEqual(fake.calls, ["d1"])

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
