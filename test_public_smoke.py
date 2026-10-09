"""Public-only smoke release safety checks; no external credentials required."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

from public_snapshot import load_snapshot

ROOT = Path(__file__).resolve().parent
EXPECTED = {"app.py", "public_snapshot.py", "requirements.txt", "REFERENCES.md", "README.md", "test_public_smoke.py", ".github/workflows/public-smoke-ci.yml", ".gitignore", "index.html", "custom-view/index.html", "custom-view/session/index.html", "watchalong/index.html", "ptt-today/index.html", "test_pages_poc.py", "test_cloud_client.mjs", ".github/workflows/pages-poc.yml", "docs/PAGES_CLIENT_UI_RELEASE_GATE.md", "docs/PUBLIC_DATA_CLIENT_V1.md", "docs/RELAY_SNAPSHOT_COVERAGE_GATE.md", "docs/PTT_READER_PARITY_CONTRACT.md", "assets/cloud-client.js", "public-data/config.json", "public-data/demo/home.json", "public-data/demo/ptt.json", "public-data/demo/watchalong.json", "public-data/demo/transcripts.json", "relay/worker.mjs", "relay/schema.sql", "relay/README.md", "relay/wrangler.example.toml", "test_relay_worker.mjs"}

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
