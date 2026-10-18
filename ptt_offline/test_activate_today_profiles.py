import json, tempfile, unittest
from pathlib import Path
from ptt_offline.activate_today_profiles import validated_profiles, q

class ActivateTodayProfilesTests(unittest.TestCase):
    def make_receipt(self, mutate=None):
        channels=[]
        for i in range(85):
            row={
                "channel_id":"UC"+f"{i:022d}",
                "channel_title":f"Channel {i}",
                "avatar_url":f"https://yt3.ggpht.com/avatar-{i}"
            }
            channels.append(row)
        body={
            "count":85,
            "avatar_count":85,
            "roster_version":"today-roster-v85",
            "fetched_at":"2026-10-15T21:00:00Z",
            "channels":channels
        }
        if mutate: mutate(body)
        td=tempfile.TemporaryDirectory()
        p=Path(td.name)/"profiles.json"
        p.write_text(json.dumps(body),encoding="utf-8")
        return td,p

    def test_exact_active_roster_profiles_pass(self):
        td,p=self.make_receipt()
        try:
            rows,stamp,version=validated_profiles(p)
            self.assertEqual(len(rows),85)
            self.assertEqual(stamp,"2026-10-15T21:00:00Z")
            self.assertEqual(version,"today-roster-v85")
        finally:
            td.cleanup()

    def test_duplicate_channel_fails_closed(self):
        def mutate(body):
            body["channels"][1]["channel_id"]=body["channels"][0]["channel_id"]
        td,p=self.make_receipt(mutate)
        try:
            with self.assertRaises(SystemExit):
                validated_profiles(p)
        finally:
            td.cleanup()

    def test_untrusted_avatar_host_fails_closed(self):
        def mutate(body):
            body["channels"][0]["avatar_url"]="https://example.com/avatar"
        td,p=self.make_receipt(mutate)
        try:
            with self.assertRaises(SystemExit):
                validated_profiles(p)
        finally:
            td.cleanup()

    def test_partial_avatar_receipt_fails_closed(self):
        def mutate(body):
            body["avatar_count"]=84
        td,p=self.make_receipt(mutate)
        try:
            with self.assertRaises(SystemExit):
                validated_profiles(p)
        finally:
            td.cleanup()

    def test_count_is_not_hardcoded_to_66(self):
        td,p=self.make_receipt()
        try:
            rows,_,_=validated_profiles(p)
            self.assertEqual(len(rows),85)
        finally:
            td.cleanup()

    def test_sql_quote(self):
        self.assertEqual(q("A'B"), "'A''B'")

    def test_import_source_avoids_explicit_sql_transaction(self):
        source=Path(__file__).with_name("activate_today_profiles.py").read_text(encoding="utf-8")
        self.assertNotIn('lines=["BEGIN TRANSACTION;"]',source)
        self.assertNotIn('lines.append("COMMIT;")',source)
        self.assertIn("ON CONFLICT(channel_id) DO UPDATE",source)

if __name__=="__main__":
    unittest.main()
