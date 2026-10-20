import json
from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ptt_offline.diagnose_current_day import diagnose


class CurrentDayDiagnosisTests(unittest.TestCase):
    def test_reports_rows_after_baseline_without_content(self):
        source_identity="a"*64
        plan={
            "status":"READY","aid":"1abc","source_identity":source_identity,
            "candidate_rows":[
                {"source_line":100,"day":"2026-10-20","content":"secret-a"},
                {"source_line":101,"day":"2026-10-20","content":"secret-b"},
                {"source_line":102,"day":"2026-10-20","content":"secret-c"},
            ],
            "pending_source_lines":[103],
            "checked_source_rows":4,
            "latest_scanned_source_line":103,
            "floor_authoritative":True,
            "scan_truncated":False,
        }
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)
            (state/(source_identity+".json")).write_text(json.dumps({
                "status":"ACKED","baseline_source_line":100,"accepted":{"1abc:100":"digest"},
            }),encoding="utf-8")
            with patch("ptt_offline.diagnose_current_day.open_source",
                       return_value=nullcontext(object())), \
                 patch("ptt_offline.diagnose_current_day.active_article_ids",
                       return_value=[7]), \
                 patch("ptt_offline.diagnose_current_day.inspect_latest_article",
                       return_value=plan):
                result=diagnose(source="/unused.sqlite3",state_dir=str(state))

        row=result["articles"][0]
        self.assertEqual(row["candidate_after_baseline_count"],2)
        self.assertEqual(row["latest_candidate_after_baseline"],102)
        self.assertEqual(row["pending_after_baseline_count"],1)
        self.assertNotIn("content",json.dumps(result))


if __name__=="__main__":
    unittest.main()
