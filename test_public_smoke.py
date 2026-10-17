"""Public-only smoke release safety checks; no external credentials required."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

from public_snapshot import load_snapshot

ROOT = Path(__file__).resolve().parent
EXPECTED = {"app.py", "public_snapshot.py", "requirements.txt", "REFERENCES.md", "README.md", "test_public_smoke.py", ".github/workflows/public-smoke-ci.yml", ".github/workflows/deploy-cloudflare-production.yml", "cloudflare/wrangler.json", "cloudflare/DEPLOY.md", "site/index.html", "site/assets/app.js", "site/assets/app.css", "site/assets/viewer-4174.css", "site/assets/config.js", "site/assets/shared-shell.css", "site/assets/viewer-standalone.css", "site/assets/viewer-standalone.js", "site/viewer/index.html", "site/assets/4174-shared-viewing-a144bb3.css", "site/assets/4174-shared-viewing-a144bb3.js", "site/assets/4174-shared-viewing-a144bb3-dom.js", "site/_headers", "AGENTS.md", "HOLOVIEWER_PROJECT_GUIDELINES.md", "docs/PROJECT_STATUS.md", "docs/HANDOFF_TEMPLATE.md", "docs/handoffs/COORDINATION_REVIEW_WINDOW_20261009.md", "docs/4174_UI_PARITY_CONTRACT.md", "docs/handoffs/UI_PARITY_CHECKPOINT_20261015.md", "docs/PUBLIC_LOCAL_ACCEPTANCE.md", "scripts/check_public_local.sh", "scripts/start_public_local.sh", "scripts/public_browser_lifecycle.mjs", "site/custom-view/index.html", "test_4174_ui_parity.py", ".gitignore", "vendor/4174-a144bb3/shared_viewing_core.py", "vendor/4174-a144bb3/client_custom_view.py", "vendor/4174-a144bb3/client_ui_shell.py", "vendor/4174-a144bb3/client_app.py"}

class PublicSmokeTests(unittest.TestCase):
    def test_repository_file_allowlist(self):
        present = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                   if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts and not p.name.endswith(".pyc")}
        self.assertEqual(present, EXPECTED)

    def test_import_boundary_and_disabled_features(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        imports = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imports += [a.name for a in n.names]
            if isinstance(n, ast.ImportFrom):
                imports.append(n.module or "")
        self.assertEqual(imports, ["__future__", "pathlib", "streamlit", "public_snapshot"])
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        for bad in ("BackfillJobQueue", "sqlite3", "subprocess", "requests", "Gemini",
                    "st.navigation", "st.Page", "playVideo", "st.video"):
            self.assertNotIn(bad, source)


    def test_static_deploy_security_boundary(self):
        config = json.loads((ROOT / "cloudflare/wrangler.json").read_text())
        self.assertEqual(set(config), {"name", "compatibility_date", "assets"})
        self.assertEqual(config["name"], "holoviewer-public")
        self.assertEqual(config["assets"], {"directory": "../site", "not_found_handling": "single-page-application"})
        self.assertNotIn("main", config)
        js = (ROOT / "site/assets/app.js").read_text()
        for token in ("setTimeout(", "location.reload(", "eval(", "innerHTML", "document.write("):
            self.assertNotIn(token, js)
        self.assertEqual(js.count("setInterval("), 2)
        self.assertIn("},30000);", js)
        self.assertIn("},10000);", js)
        self.assertIn("credentials:'omit'", js)
        self.assertIn("textContent=", js)
        frontend_config = (ROOT / "site/assets/config.js").read_text()
        self.assertIn("https://holoviewer-public-api.singlebagel.workers.dev", frontend_config)
        self.assertNotIn("CLOUDFLARE_API_TOKEN", frontend_config)

    def test_standalone_viewer_mode_contract(self):
        html = (ROOT / "site/viewer/index.html").read_text(encoding="utf-8")
        js = (ROOT / "site/assets/viewer-standalone.js").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/viewer-standalone.css").read_text(encoding="utf-8")
        app = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        for label in (">預設<", ">輪播<", ">鎖定<"):
            self.assertIn(label, html)
        for old in (">平均<", ">主視角<", ">直播優先<"):
            self.assertNotIn(old, html)
        self.assertIn("const MAX_STREAMS=16;", js)
        self.assertIn("const FOCUS_VISIBLE_SLOTS=4;", js)
        self.assertIn("carousel.checked=currentLayoutPreset()!=='equal';", js)
        self.assertIn("secondaryOffset=(secondaryOffset+Math.min(FOCUS_VISIBLE_SLOTS-1,secondaryCount))%secondaryCount;", js)
        self.assertIn("viewerModeStatus.dataset.mode='lock';", js)
        self.assertIn("function handleFocusAvatarClick(index)", js)
        self.assertIn("currentLayoutPreset()==='focus'&&lockedIndex===index", js)
        self.assertIn("setLayoutPreset('primary');", js)
        self.assertIn("setLayoutPreset('focus');", js)
        self.assertIn("button.addEventListener('click',()=>handleFocusAvatarClick(index));", js)
        self.assertIn(".player-card.viewer-hidden{display:none!important}", css)
        self.assertIn(".viewer-workspace.workspace-focus.layout-primary,.viewer-workspace.workspace-sidebar.layout-primary{", css)
        self.assertIn(".viewer-workspace.workspace-focus.layout-primary .viewer-stage,.viewer-workspace.workspace-sidebar.layout-primary .viewer-stage{display:contents}", css)
        self.assertIn(".transport-button.is-feedback", css)
        self.assertIn("location.href='/viewer/?'+q.toString();", app)

    def test_static_response_content_security_policy(self):
        headers = (ROOT / "site/_headers").read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy:", headers)
        for directive in ("default-src 'none'", "script-src 'self'", "connect-src https://holoviewer-public-api.singlebagel.workers.dev", "frame-src https://www.youtube-nocookie.com", "frame-ancestors 'none'", "object-src 'none'"):
            self.assertIn(directive, headers)
        self.assertNotIn("'unsafe-inline'", headers)
        self.assertNotIn("'unsafe-eval'", headers)

    def test_manual_deployment_release_gate(self):
        workflow = (ROOT / ".github/workflows/deploy-cloudflare-production.yml").read_text()
        for token in ("workflow_dispatch:", "BASELINE-CHECKED", "release_sha", "git rev-parse HEAD", "cloudflare-production", "refs/heads/main", "persist-credentials: false"):
            self.assertIn(token, workflow)
        self.assertNotIn("  push:", workflow)
        self.assertNotIn("github.event_name == 'push'", workflow)
        self.assertNotIn("  schedule:", workflow)
        self.assertIn("workflow_dispatch:", workflow)

    def test_absent_snapshot(self):
        with tempfile.TemporaryDirectory() as t:
            data, error = load_snapshot(Path(t) / "missing.json")
        self.assertIsNone(data)
        self.assertTrue(error)

    def test_snapshot_does_not_leak_extra_fields(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "snapshot.json"
            p.write_text(json.dumps({"schema_version": 1, "generated_at": "2026-01-01T00:00:00Z",
                    "streams": [{"title": "Example", "status": "ended", "video_id": "abcdefghijk",
                                 "private_token": "should never render"}]}), encoding="utf-8")
            data, error = load_snapshot(p)
        self.assertFalse(error)
        self.assertEqual(set(data["streams"][0]), {"title", "status", "video_id"})

    def test_no_accidental_credentials_or_publishable_data(self):
        for p in ROOT.rglob("*"):
            if ".git" in p.parts or "__pycache__" in p.parts:
                continue
            self.assertFalse(p.is_symlink())
            if p.is_file():
                self.assertNotIn(p.suffix.lower(), {".sqlite3", ".db", ".pem", ".p12", ".key"})
        self.assertFalse((ROOT / "published_snapshot.json").exists())

if __name__ == "__main__":
    unittest.main()
