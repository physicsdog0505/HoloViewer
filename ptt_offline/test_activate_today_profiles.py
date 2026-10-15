import json, tempfile, unittest
from pathlib import Path
from ptt_offline.activate_today_profiles import validated_profiles, q

class ActivateTodayProfilesTests(unittest.TestCase):
    def make_receipt(self, mutate=None):
        channels=[]
        for i in range(66):
            row={
                "channel_id":"UC"+f"{i:022d}",
                "channel_title":f"Channel {i}",
                "avatar_url":f"https://yt3.ggpht.com/avatar-{i}"
            }
            channels.append(row)
        body={"count":66,"avatar_count":66,"fetched_at":"2026-10-15T21:00:00Z","channels":channels}
        if mutate: mutate(body)
        td=tempfile.TemporaryDirectory()
        p=Path(td.name)/"profiles.json"
        p.write_text(json.dumps(body),encoding="utf-8")
        return td,p

    def test_exact_66_verified_profiles_pass(self):
        td,p=self.make_receipt()
        try:
            rows,stamp=validated_profiles(p)
            self.assertEqual(len(rows),66)
            self.assertEqual(stamp,"2026-10-15T21:00:00Z")
        finally: td.cleanup()

    def test_duplicate_channel_fails_closed(self):
        def mutate(body): body["channels"][1]["channel_id"]=body["channels"][0]["channel_id"]
        td,p=self.make_receipt(mutate)
        try:
            with self.assertRaises(SystemExit): validated_profiles(p)
        finally: td.cleanup()

    def test_untrusted_avatar_host_fails_closed(self):
        def mutate(body): body["channels"][0]["avatar_url"]="https://example.com/avatar"
        td,p=self.make_receipt(mutate)
        try:
            with self.assertRaises(SystemExit): validated_profiles(p)
        finally: td.cleanup()

    def test_sql_quote(self):
        self.assertEqual(q("A'B"), "'A''B'")

if __name__=="__main__":
    unittest.main()
