import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location("audit_watchalong",Path(__file__).with_name("audit-watchalong-release.py"))
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class AuditTests(unittest.TestCase):
    def make(self,broken=False):
        d=tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root=Path(d.name)
        events=[]
        for i,day in enumerate(sorted(audit.EXPECTED_DAYS)):
            events.append({"event_id":f"watch:{i:020x}","aid":"M.1790851704.A.BFA",
                "article_title":"Hololive","source_url":"https://www.ptt.cc/bbs/C_Chat/M.1790851704.A.BFA.html",
                "article_datetime":"2026-10-01T12:00:00+08:00","day":day,
                "scheduled_time":"12:00","description":"兎田ぺこら 無職轉生 同時視聽",
                "member_only":False,"streams":[{"label":"Pekora","video_id":"eFYByyw5AJc"}]})
        if broken:events[0]["streams"]=[]
        jp=root/"out.json";sq=root/"out.sql"
        jp.write_text(json.dumps({"schema_version":"public-watchalong-export-v1","imported_at":"2026-10-16T00:00:00Z","event_count":3,"events":events}))
        sq.write_text("BEGIN TRANSACTION;\nINSERT INTO public_watchalong_events(event_id) VALUES('a');\nDELETE FROM public_watchalong_streams WHERE event_id='a';\nINSERT INTO public_watchalong_streams(event_id) VALUES('a');\nCOMMIT;")
        return sq,jp
    def test_valid_release(self):
        sql,jp=self.make()
        receipt=audit.audit(sql,jp)
        self.assertEqual(receipt["status"],"PASS")
        self.assertEqual(len(receipt["sha256_sql"]),64)
        self.assertTrue(receipt["mushoku_3_of_3"])
    def test_orphan_fails(self):
        sql,jp=self.make(True)
        self.assertEqual(audit.audit(sql,jp)["status"],"BLOCKED")
    def test_other_table_fails(self):
        sql,jp=self.make()
        sql.write_text(sql.read_text().replace("COMMIT;","DELETE FROM public_today_canonical;\nCOMMIT;"))
        self.assertEqual(audit.audit(sql,jp)["status"],"BLOCKED")
    def test_unauthorized_payload_fails(self):
        sql,jp=self.make()
        raw=json.loads(jp.read_text());raw["events"][0]["transcript"]="private"
        jp.write_text(json.dumps(raw))
        self.assertEqual(audit.audit(sql,jp)["status"],"BLOCKED")

if __name__=="__main__":unittest.main()
