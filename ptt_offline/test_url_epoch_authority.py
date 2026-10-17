import unittest
from datetime import datetime, timezone
from ptt_offline.public_today_contract import ContractError
from ptt_offline.url_epoch_authority import article_epoch, reconstruct_events


def url_at(utc):
    epoch=int(datetime.fromisoformat(utc.replace("Z","+00:00")).timestamp())
    return f"https://www.ptt.cc/bbs/C_Chat/M.{epoch}.A.ABC.html"


class UrlEpochAuthorityTests(unittest.TestCase):
    verifier=staticmethod(lambda board,aid,url: board == "C_Chat" and aid == "A1")
    def test_missing_or_rejected_identity_fails_closed(self):
        url=url_at("2025-12-31T15:00:00Z")
        with self.assertRaises(ContractError):
            article_epoch(board="C_Chat",aid="A1",url=url)
        with self.assertRaises(ContractError):
            article_epoch(board="C_Chat",aid="A1",url=url,
                          identity_verifier=lambda *args: False)

    def test_verifier_exception_fails_closed(self):
        url=url_at("2025-12-31T15:00:00Z")
        def broken(*args):
            raise RuntimeError("verification unavailable")
        with self.assertRaises(ContractError):
            article_epoch(board="C_Chat",aid="A1",url=url,
                          identity_verifier=broken)

    def test_december_to_january_rollover_and_selected_day(self):
        url=url_at("2025-12-31T15:00:00Z")  # 23:00 Taipei
        rows=[{"source_line":5,"ptt_date":"12/31","ptt_time":"23:01"},
              {"source_line":6,"ptt_date":"01/01","ptt_time":"00:01"}]
        got=reconstruct_events(board="C_Chat",aid="#A1",url=url,pushes=rows,identity_verifier=self.verifier)
        self.assertEqual([r["day"] for r in got],["2025-12-31","2026-01-01"])
        self.assertEqual(got[0]["occurred_at"],"2025-12-31T15:01:00Z")
        self.assertEqual(got[1]["source_record_key"],"A1:6")

    def test_january_first_push_after_december_article(self):
        url=url_at("2025-12-31T15:59:00Z")
        rows=[{"source_line":1,"ptt_date":"01/01","ptt_time":"00:01"}]
        self.assertEqual(reconstruct_events(board="C_Chat",aid="A1",url=url,pushes=rows,identity_verifier=self.verifier)[0]["day"],"2026-01-01")

    def test_reject_malformed_url_or_board(self):
        for board,url in [
            ("C_Chat","http://invalid/M.123.A.ABC.html"),
            ("Other",url_at("2025-12-31T15:00:00Z")),
        ]:
            with self.subTest(board=board,url=url),self.assertRaises(ContractError):
                article_epoch(board=board,aid="A1",url=url,identity_verifier=self.verifier)

    def test_reject_unobserved_year_and_regressive_sequence(self):
        url=url_at("2025-01-01T00:00:00Z")
        cases=[
            [{"source_line":1,"ptt_date":"12/30","ptt_time":"09:00"}],
            [{"source_line":1,"ptt_date":"01/02","ptt_time":"09:00"},
             {"source_line":2,"ptt_date":"01/01","ptt_time":"09:00"}],
            [{"source_line":2,"ptt_date":"01/01","ptt_time":"09:00"},
             {"source_line":1,"ptt_date":"01/01","ptt_time":"09:01"}],
        ]
        for rows in cases:
            with self.subTest(rows=rows),self.assertRaises(ContractError):
                reconstruct_events(board="C_Chat",aid="A1",url=url,pushes=rows,identity_verifier=self.verifier)

    def test_url_seconds_do_not_reject_same_source_minute(self):
        url=url_at("2026-10-06T10:42:17Z")  # 18:42:17 Taipei
        rows=[{"source_line":1,"ptt_date":"10/06","ptt_time":"18:42"}]
        got=reconstruct_events(board="C_Chat",aid="A1",url=url,pushes=rows,identity_verifier=self.verifier)
        self.assertEqual(got[0]["occurred_at"],"2026-10-06T10:42:00Z")
        self.assertEqual(got[0]["time_quality"],"source-minute")

    def test_opt_in_preserves_reviewed_minute_regression(self):
        url=url_at("2026-10-09T10:43:00Z")
        rows=[{"source_line":212,"ptt_date":"10/09","ptt_time":"18:46"},
              {"source_line":235,"ptt_date":"10/09","ptt_time":"18:43"}]
        got=reconstruct_events(board="C_Chat",aid="A1",url=url,pushes=rows,
                               identity_verifier=self.verifier,
                               reviewed_chronology_exceptions=True)
        self.assertEqual(got[1]["occurred_at"],"2026-10-09T10:43:00Z")
        self.assertEqual(got[1]["time_quality"],"source-minute-regression")
        self.assertIn("line 235",got[1]["chronology_note"])


if __name__=="__main__":
    unittest.main()
