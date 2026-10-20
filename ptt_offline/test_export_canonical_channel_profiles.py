import hashlib, importlib.util, json, tempfile, unittest
from pathlib import Path

MODULE=Path(__file__).with_name("export_canonical_channel_profiles.py")
spec=importlib.util.spec_from_file_location("export_canonical_channel_profiles",MODULE)
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class CanonicalProfileExportTests(unittest.TestCase):
    def test_canonical_bytes_are_stable(self):
        body={"b":2,"a":"日本語","profiles":[{"channel_id":"UC"+"A"*22}]}
        raw=mod.canonical_bytes(body)
        self.assertEqual(raw,mod.canonical_bytes(json.loads(raw)))
        self.assertEqual(hashlib.sha256(raw).hexdigest(),hashlib.sha256(mod.canonical_bytes(body)).hexdigest())

    def test_avatar_allowlist(self):
        self.assertEqual(mod.safe_avatar("https://yt3.ggpht.com/a"),"https://yt3.ggpht.com/a")
        for value in ("http://yt3.ggpht.com/a","https://example.com/a","https://user@yt3.ggpht.com/a"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                mod.safe_avatar(value)

    def test_collect_results_tolerates_wrapped_wrangler_json(self):
        payload=[{"results":[{"a":1}]},{"meta":{"results":[{"a":2}]}}]
        self.assertEqual(mod.collect_results(payload),[{"a":1},{"a":2}])

    def test_config_is_pinned_to_existing_worker_and_d1(self):
        cfg={"name":mod.WORKER,"d1_databases":[{
          "binding":"DB","database_name":mod.DB_NAME,"database_id":mod.DB_ID
        }]}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"wrangler.json"; p.write_text(json.dumps(cfg),encoding="utf-8")
            self.assertIsNone(mod.load_config(p))
            cfg["d1_databases"][0]["database_id"]="wrong"
            p.write_text(json.dumps(cfg),encoding="utf-8")
            with self.assertRaises(SystemExit): mod.load_config(p)

if __name__=="__main__":
    unittest.main()
