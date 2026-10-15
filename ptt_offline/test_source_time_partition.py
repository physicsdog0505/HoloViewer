import unittest
from ptt_offline.ptt_aid_identity import aid_from_article_url
from ptt_offline.source_time_partition import partition_candidate_rows

URL="https://www.ptt.cc/bbs/C_Chat/M.1789081207.A.5FC.html"
AID=aid_from_article_url(URL)[1]

class PartitionTests(unittest.TestCase):
    def test_recent_unique_year_vs_sparse_multiyear_and_invalid(self):
        rows=[
            {"source_line":1,"ptt_date":"09/11","ptt_time":"07:05",
             "collected_at":"2026-09-11T00:00:00Z"},
            {"source_line":2,"ptt_date":"09/11","ptt_time":"07:06",
             "collected_at":"2029-09-11T00:00:00Z"},
            {"source_line":3,"ptt_date":"02/30","ptt_time":"00:00",
             "collected_at":"2026-09-11T00:00:00Z"},
        ]
        r=partition_candidate_rows(board="C_Chat",aid=AID,url=URL,
                                    rows=rows,timezone_evidence=True)
        self.assertEqual([x["source_line"] for x in r["inferred"]],[1])
        self.assertEqual([x["source_line"] for x in r["pending"]],[2,3])
        self.assertEqual(r["verified"],[])
        self.assertEqual(r["inferred"][0]["classification"],"INFERRED_NOT_VERIFIED")

    def test_pending_row_blocks_checkpoint_even_if_later_row_is_inferred(self):
        rows=[
            {"source_line":1,"ptt_date":"09/11","ptt_time":"07:05",
             "collected_at":"2026-09-11T00:00:00Z"},
            {"source_line":2,"ptt_date":"02/30","ptt_time":"00:00",
             "collected_at":"2026-09-11T00:00:00Z"},
            {"source_line":3,"ptt_date":"09/11","ptt_time":"07:07",
             "collected_at":"2026-09-11T00:00:00Z"},
        ]
        result=partition_candidate_rows(board="C_Chat",aid=AID,url=URL,
                                        rows=rows,timezone_evidence=True)
        self.assertEqual(result["checkpoint_blocked_at"],2)
        self.assertEqual([r["source_line"] for r in result["inferred"]],[1,3])
        self.assertEqual([r["source_line"] for r in result["unblocked_prefix"]],[1])
        self.assertEqual(result["verified"],[])

    def test_no_timezone_authority_blocks_all_without_losing_rows(self):
        r=partition_candidate_rows(board="C_Chat",aid=AID,url=URL,rows=[
            {"source_line":1,"ptt_date":"09/11","ptt_time":"07:05",
             "collected_at":"2026-09-11T00:00:00Z"}])
        self.assertEqual(r["inferred"],[])
        self.assertEqual(r["pending"][0]["reason"],"ptt-display-timezone-unverified")

if __name__=="__main__":
    unittest.main()
