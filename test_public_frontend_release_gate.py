from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.run_public_frontend_owner_release import (
    FOREIGN_PREFIXES,
    PROTECTED_RUNTIME_PREFIXES,
    frontend_release_scope_gate,
    is_foreign_rel,
    is_protected_runtime_rel,
    is_spa_fallback_html,
    normalize_custom_html_edge,
    ownership_gate,
)


class PublicFrontendReleaseGateTests(unittest.TestCase):
    def test_foreign_prefixes_reject_youtube_and_ptt(self):
        self.assertTrue(is_foreign_rel("youtube/v1/manifest.json"))
        self.assertTrue(is_foreign_rel("ptt/v1/manifests/x.json"))
        self.assertTrue(is_foreign_rel("data/watchalong/manifest.json"))
        self.assertFalse(is_foreign_rel("data/search/aliases/v1/latest.json"))

    def test_ownership_gate_accepts_frontend_without_watchalong_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "site").mkdir(parents=True)
            result = ownership_gate(root)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["forbidden_count"], 0)

    def test_ownership_gate_rejects_watchalong_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "site/data/watchalong/manifest.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}")
            with self.assertRaisesRegex(Exception, "foreign-owner assets"):
                ownership_gate(root)

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
        self.assertEqual(FOREIGN_PREFIXES, ("youtube/v1/", "ptt/v1/", "data/watchalong/"))


    def test_protected_runtime_prefix_contract_is_explicit(self):
        self.assertEqual(
            PROTECTED_RUNTIME_PREFIXES,
            ("data/search/aliases/",),
        )
        self.assertTrue(is_protected_runtime_rel("data/search/aliases/v1/latest.json"))
        self.assertFalse(is_protected_runtime_rel("data/watchalong/manifest.json"))
        self.assertFalse(is_protected_runtime_rel("assets/app.js"))

    def test_frontend_release_scope_gate_blocks_alias_change(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            target = root / "site/data/search/aliases/v1/latest.json"
            target.parent.mkdir(parents=True)
            target.write_text('{"v":1}')
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=root, check=True, stdout=subprocess.DEVNULL)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            target.write_text('{"v":2}')
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "alias"], cwd=root, check=True, stdout=subprocess.DEVNULL)
            head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            with self.assertRaisesRegex(Exception, "protected runtime data changes"):
                frontend_release_scope_gate(root, base, head)

    def test_frontend_release_scope_gate_does_not_own_watchalong_data(self):
        self.assertFalse(is_protected_runtime_rel("data/watchalong/manifest.json"))
        self.assertTrue(is_foreign_rel("data/watchalong/manifest.json"))

    def test_frontend_release_scope_gate_allows_frontend_asset_change(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            target = root / "site/assets/app.js"
            target.parent.mkdir(parents=True)
            target.write_text("one")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=root, check=True, stdout=subprocess.DEVNULL)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            target.write_text("two")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "frontend"], cwd=root, check=True, stdout=subprocess.DEVNULL)
            head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            result = frontend_release_scope_gate(root, base, head)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["protected_runtime_change_count"], 0)


    def test_spa_fallback_html_detects_index_fallback(self):
        self.assertTrue(is_spa_fallback_html(b"<!doctype html><html></html>"))
        self.assertTrue(is_spa_fallback_html(b"  \n<!DOCTYPE html><html></html>"))

    def test_legacy_youtube_inventory_treats_spa_fallback_as_absent(self):
        import scripts.run_public_frontend_owner_release as release
        original_fetch=release.fetch
        original_parse=release.parse_frontend_config
        try:
            release.fetch=lambda origin,path,allow_404=False: b'<!doctype html><html><body>app</body></html>' if path=='/youtube/v1/manifest.json' else None
            release.parse_frontend_config=lambda repo: ('https://holoviewer-youtube-static-assets.singlebagel.workers.dev','https://holoviewer-watchalong-static-assets.singlebagel.workers.dev',[])
            result=release.enumerate_first_run_foreign(Path('.'))
            self.assertEqual(result['youtube_count'],0)
            self.assertEqual(result['youtube_paths'],[])
        finally:
            release.fetch=original_fetch
            release.parse_frontend_config=original_parse

    def test_legacy_youtube_inventory_blocks_non_json_non_html(self):
        import scripts.run_public_frontend_owner_release as release
        original_fetch=release.fetch
        original_parse=release.parse_frontend_config
        try:
            release.fetch=lambda origin,path,allow_404=False: b'not-json' if path=='/youtube/v1/manifest.json' else None
            release.parse_frontend_config=lambda repo: ('https://holoviewer-youtube-static-assets.singlebagel.workers.dev','https://holoviewer-watchalong-static-assets.singlebagel.workers.dev',[])
            with self.assertRaisesRegex(Exception,'neither JSON nor SPA fallback'):
                release.enumerate_first_run_foreign(Path('.'))
        finally:
            release.fetch=original_fetch
            release.parse_frontend_config=original_parse
    def test_spa_fallback_html_rejects_json(self):
        self.assertFalse(is_spa_fallback_html(b'{"schema_version":1}'))
        self.assertFalse(is_spa_fallback_html(None))

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


    def test_wrangler_local_cache_does_not_dirty_release_worktree(self):
        gitignore=(Path(__file__).resolve().parent / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".wrangler/",gitignore)

        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            subprocess.run(["git","init"],cwd=root,check=True,stdout=subprocess.DEVNULL)
            subprocess.run(["git","config","user.email","test@example.com"],cwd=root,check=True)
            subprocess.run(["git","config","user.name","Test"],cwd=root,check=True)
            (root/".gitignore").write_text(gitignore,encoding="utf-8")
            (root/"tracked.txt").write_text("ok",encoding="utf-8")
            subprocess.run(["git","add","."],cwd=root,check=True)
            subprocess.run(["git","commit","-m","base"],cwd=root,check=True,stdout=subprocess.DEVNULL)
            cache=root/".wrangler/cache/wrangler-account.json"
            cache.parent.mkdir(parents=True)
            cache.write_text('{"account":"generated"}',encoding="utf-8")
            status=subprocess.check_output(
                ["git","status","--porcelain","--untracked-files=all"],
                cwd=root,text=True
            ).strip()
            self.assertEqual(status,"")


if __name__ == "__main__":
    unittest.main()
