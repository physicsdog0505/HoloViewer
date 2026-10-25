from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.run_public_frontend_owner_release import (
    FOREIGN_PREFIXES,
    ReleaseBlocked,
    _legacy_frontend_youtube_manifest,
    is_foreign_rel,
    is_spa_fallback_html,
    normalize_custom_html_edge,
    ownership_gate,
)


class PublicFrontendReleaseGateTests(unittest.TestCase):
    def test_foreign_prefixes_reject_youtube_and_ptt(self):
        self.assertTrue(is_foreign_rel("youtube/v1/manifest.json"))
        self.assertTrue(is_foreign_rel("ptt/v1/manifests/x.json"))
        self.assertFalse(is_foreign_rel("data/watchalong/manifest.json"))
        self.assertFalse(is_foreign_rel("data/search/aliases/v1/latest.json"))

    def test_ownership_gate_accepts_frontend_owned_runtime_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "site/data/watchalong").mkdir(parents=True)
            (root / "site/data/watchalong/manifest.json").write_text("{}")
            result = ownership_gate(root)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["forbidden_count"], 0)

    def test_ownership_gate_rejects_foreign_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "site/data/watchalong").mkdir(parents=True)
            (root / "site/data/watchalong/manifest.json").write_text("{}")
            target = root / "site/youtube/v1/manifest.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}")
            with self.assertRaisesRegex(Exception, "foreign-owner assets"):
                ownership_gate(root)

    def test_foreign_prefix_contract_is_explicit(self):
        self.assertEqual(FOREIGN_PREFIXES, ("youtube/v1/", "ptt/v1/"))


    def test_spa_fallback_html_detects_index_fallback(self):
        self.assertTrue(is_spa_fallback_html(b"<!doctype html><html></html>"))
        self.assertTrue(is_spa_fallback_html(b"  \n<!DOCTYPE html><html></html>"))

    def test_spa_fallback_html_rejects_json(self):
        self.assertFalse(is_spa_fallback_html(b'{"schema_version":1}'))
        self.assertFalse(is_spa_fallback_html(None))


    @patch("scripts.run_public_frontend_owner_release.fetch")
    def test_legacy_youtube_dual_spa_fallback_is_absent(self, fetch_mock):
        fetch_mock.side_effect = [
            b"<!doctype html><html></html>",
            b"<!DOCTYPE html><html></html>",
        ]
        self.assertIsNone(_legacy_frontend_youtube_manifest())

    @patch("scripts.run_public_frontend_owner_release.fetch")
    def test_legacy_youtube_single_origin_fallback_fails_closed(self, fetch_mock):
        fetch_mock.side_effect = [
            b"<!doctype html><html></html>",
            b'{"schema_version":1}',
        ]
        with self.assertRaisesRegex(ReleaseBlocked, "only one Production origin"):
            _legacy_frontend_youtube_manifest()

    @patch("scripts.run_public_frontend_owner_release.fetch")
    def test_legacy_youtube_dual_json_requires_identical_bytes(self, fetch_mock):
        fetch_mock.side_effect = [
            b'{"schema_version":1}',
            b'{"schema_version":2}',
        ]
        with self.assertRaisesRegex(ReleaseBlocked, "differs between Production origins"):
            _legacy_frontend_youtube_manifest()

    @patch("scripts.run_public_frontend_owner_release.fetch")
    def test_legacy_youtube_dual_json_returns_manifest(self, fetch_mock):
        raw = b'{"schema_version":1,"months":[]}'
        fetch_mock.side_effect = [raw, raw]
        self.assertEqual(
            _legacy_frontend_youtube_manifest(),
            {"schema_version": 1, "months": []},
        )

    def test_custom_html_exact_body_passes_unchanged(self):
        body = b"<!doctype html><html><body><script src=\"assets/app.js\"></script></body></html>"
        self.assertEqual(normalize_custom_html_edge(body), body)

    def test_custom_html_single_cloudflare_beacon_is_removed(self):
        base = b"<!doctype html><html><body><script src=\"assets/app.js\"></script></body></html>"
        beacon = (
            b'<script type="module" '
            b'src="https://static.cloudflareinsights.com/beacon.min.js/vce701823e78c4301a35b7e07294d87301792088814092" '
            b'integrity="sha512-example" '
            b'data-cf-beacon=\'{"version":"2024.11.0","token":"abc"}\' '
            b'crossorigin="anonymous"></script>'
        )
        actual = base.replace(b"</body>", beacon + b"</body>")
        self.assertEqual(normalize_custom_html_edge(actual), base)

    def test_custom_html_arbitrary_injected_script_is_not_removed(self):
        base = b"<!doctype html><html><body></body></html>"
        injected = base.replace(
            b"</body>",
            b'<script src="https://evil.example/x.js"></script></body>',
        )
        self.assertEqual(normalize_custom_html_edge(injected), injected)
        self.assertNotEqual(normalize_custom_html_edge(injected), base)

    def test_custom_html_multiple_cloudflare_beacons_fail_closed(self):
        beacon = (
            b'<script src="https://static.cloudflareinsights.com/beacon.min.js/v1" '
            b'data-cf-beacon=\'{}\'></script>'
        )
        with self.assertRaisesRegex(Exception, "multiple Cloudflare Insights"):
            normalize_custom_html_edge(beacon + beacon)


    def test_custom_html_production_beacon_shape_is_removed(self):
        base = b'<!doctype html><html><body><script src="assets/app.js"></script></body></html>'
        beacon = (
            b'<script type="module" '
            b'src="https://static.cloudflareinsights.com/beacon.min.js/vce701823e78c4301a35b7e07294d87301792088814092" '
            b'integrity="sha512-UKNk8GbxkABxKcXYuLkO16EleLGUkcvJWtpSNmExE0Too3ZaFAxTscNWEc1OdAv5/BikHawapSCaiD2XCmp+Bw==" '
            b'data-cf-beacon=\'{"version":"2024.11.0","token":"a62034925dc54f7fb79bb8d87b82c6ed","r":1,"spa":2}\' '
            b'crossorigin="anonymous"></script>'
        )
        actual = base.replace(b"</body>", beacon + b"\n</body>")
        self.assertEqual(normalize_custom_html_edge(actual), base)

    def test_custom_html_beacon_does_not_hide_other_whitespace_drift(self):
        base = b'<!doctype html><html><body></body></html>'
        beacon = (
            b'<script src="https://static.cloudflareinsights.com/beacon.min.js/v1" '
            b'data-cf-beacon=\'{}\'></script>'
        )
        actual = base.replace(b"</body>", beacon + b"  </body>")
        normalized = normalize_custom_html_edge(actual)
        self.assertEqual(normalized, base.replace(b"</body>", b"  </body>"))
        self.assertNotEqual(normalized, base)


if __name__ == "__main__":
    unittest.main()
