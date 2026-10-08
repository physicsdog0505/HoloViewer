"""Preview branch smoke safety: production entrypoint unchanged; no private data."""
from pathlib import Path
import ast
import unittest

ROOT=Path(__file__).resolve().parent

class TestPreviewBoundary(unittest.TestCase):
    def test_preview_is_separate_and_read_only(self):
        src=(ROOT/"preview_app.py").read_text(encoding="utf-8")
        tree=ast.parse(src)
        imports=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                imports.extend(alias.name for alias in node.names)
            if isinstance(node,ast.ImportFrom):
                imports.append(node.module)
        self.assertEqual(imports,["pathlib","streamlit"])
        for banned in ("sqlite3","subprocess","requests","os.environ","private","youtube_metadata","hololive_ptt"):
            self.assertNotIn(banned,src)
        self.assertFalse((ROOT/"client_exact_preview.html").exists(),
                         "Generated HTML cannot be added without separate audit, fixture checksum and PR review.")

    def test_public_main_entrypoint_intact(self):
        source=(ROOT/"app.py").read_text(encoding="utf-8")
        self.assertIn("Public deployment smoke preview only",source)

if __name__=="__main__":
    unittest.main()
