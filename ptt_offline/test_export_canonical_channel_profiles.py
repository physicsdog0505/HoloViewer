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

    def support_export(self):
        channels=[{"channel_id":"UC"+format(i,"022d"),"display_mode":"neutral"} for i in range(66)]
        for i in range(56):
            channels[i].update({
              "display_mode":"solid",
              "color_hex":"#112233",
              "verification_status":"verified",
            })
        channels[56].update({
          "display_mode":"dual_color",
          "color_hexes":["#112233","#445566"],
          "verification_status":"community",
          "color_semantics":"2025_6th_fes_penlight",
        })
        return {"schema_version":1,"fallback":"neutral","channels":channels}

    def test_support_color_projection_matches_runtime_contract(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"colors.json"
            p.write_text(json.dumps(self.support_export(),ensure_ascii=False),encoding="utf-8")
            colors,receipt=mod.load_support_colors(p)
            self.assertEqual(receipt["rows"],66)
            self.assertEqual(receipt["colored"],57)
            self.assertEqual(receipt["neutral"],9)
            self.assertEqual(receipt["dual"],1)
            self.assertRegex(receipt["sha256"],r"^[0-9a-f]{64}$")
            self.assertEqual(colors["UC"+format(0,"022d")],{
              "member_accent":"#112233",
              "member_accent_dual":None,
              "support_mode":"solid",
              "support_color_source":"verified",
            })
            self.assertEqual(colors["UC"+format(56,"022d")],{
              "member_accent":"#112233",
              "member_accent_dual":["#112233","#445566"],
              "support_mode":"dual_color",
              "support_color_source":"2025_6th_fes_penlight",
            })
            self.assertEqual(colors["UC"+format(65,"022d")]["support_mode"],"neutral")

    def test_support_color_export_fails_closed_on_unreviewed_evidence(self):
        body=self.support_export()
        body["channels"][0]={
          "channel_id":"UC"+format(0,"022d"),
          "display_mode":"solid",
          "color_hex":"#112233",
          "verification_status":"unknown",
        }
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"colors.json"
            p.write_text(json.dumps(body),encoding="utf-8")
            with self.assertRaises(SystemExit):
                mod.load_support_colors(p)

if __name__=="__main__":
    unittest.main()
