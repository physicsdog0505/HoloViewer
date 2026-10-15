"""Offline validation for the inert #68 production host wiring proposal."""
import json
from pathlib import Path
import unittest

from platform_adapter.public_api import DEFAULT_API
from platform_adapter.ptt_provider import PttPublicReader


class ProductionHostWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / "platform_adapter" / "production_host_wiring_spec.json"
        cls.spec = json.loads(path.read_text(encoding="utf-8"))

    def test_host_identity_stays_owner_gated(self):
        host = self.spec["public_host_worker"]
        self.assertIsNone(host["name"])
        self.assertTrue(host["owner_confirmation_required"])
        self.assertEqual(host["d1_bindings"], [])

    def test_python_worker_and_same_worker_assets_are_explicit(self):
        host = self.spec["public_host_worker"]
        self.assertEqual(host["main"], "entry.py")
        self.assertIn("python_workers", host["compatibility_flags"])
        self.assertEqual(host["assets"]["binding"], "ASSETS")
        self.assertFalse(host["assets"]["run_worker_first"])

    def test_d1_binding_belongs_to_existing_api_not_ui_worker(self):
        api = self.spec["canonical_api"]
        self.assertEqual(api["worker_name"], "holoviewer-public-api")
        self.assertEqual(api["origin"], DEFAULT_API)
        self.assertEqual(api["db_binding"]["owner"], "canonical_api")
        self.assertEqual(api["db_binding"]["binding"], "DB")
        self.assertEqual(api["db_binding"]["database_name"], "holoviewer-public-v1")

    def test_route_and_runtime_env_ownership_is_explicit(self):
        host = self.spec["public_host_worker"]
        api = self.spec["canonical_api"]
        routing = self.spec["routing"]
        self.assertEqual(host["runtime_vars"], {})
        self.assertFalse(host["outbound_api"]["runtime_env_override"])
        self.assertEqual(host["outbound_api"]["origin"], DEFAULT_API)
        self.assertEqual(api["runtime_bindings"]["DB"]["database_name"],
                         "holoviewer-public-v1")
        self.assertIsNone(api["runtime_vars"]["ALLOWED_ORIGIN"]["value"])
        self.assertTrue(api["runtime_vars"]["ALLOWED_ORIGIN"]["owner_confirmation_required"])
        self.assertEqual(routing["static_assets"]["binding"], "ASSETS")
        self.assertFalse(routing["static_assets"]["worker_first"])
        self.assertEqual(routing["canonical_reads"]["methods"], ["GET"])
        self.assertEqual(routing["d1"]["from"], "holoviewer-public-api")
        self.assertEqual(routing["ptt_product"]["state"], "disabled-fail-closed")

    def test_exact_reviewed_owner_sources_are_pinned(self):
        api = self.spec["canonical_api"]
        self.assertEqual(api["issue47_source_sha"],
                         "149a80361654b06377dbae580e1d8da2e5010cf0")
        self.assertEqual(api["issue48_mount_sha"],
                         "b96d0902a504bc26019efd693a1b3586cfb3d3d2")

    def test_product_ptt_remains_disabled_fail_closed(self):
        ptt = self.spec["ptt_product"]
        self.assertFalse(ptt["enabled"])
        self.assertTrue(ptt["fail_closed"])
        self.assertFalse(PttPublicReader().enabled)

    def test_mutation_gates_are_not_omitted(self):
        gates = set(self.spec["forbidden_mutations_without_owner_gate"])
        self.assertEqual(gates, {
            "deploy", "route_or_domain_change", "d1_migration_or_write",
            "publisher_or_cron_activation", "secret_change", "merge_or_cutover",
        })


if __name__ == "__main__":
    unittest.main()
