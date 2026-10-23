import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ptt_offline.publisher_daily_budget import allows,record,snapshot
from ptt_offline.public_today_contract import ContractError

def ts(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()

class DailyBudgetTests(unittest.TestCase):
    def test_budget_survives_restart_and_blocks_projection(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"daily.json"
            record(p,batches=2,rows=20,modeled_writes=44,modeled_queries=50,
                   now=ts("2026-10-23T12:00:00"),write_cap=50,query_cap=60)
            current=snapshot(p,now=ts("2026-10-23T12:01:00"),write_cap=50,query_cap=60)
            self.assertEqual(current["modeled_writes"],44)
            ok,reason,_=allows(p,projected_writes=7,projected_queries=1,
                               now=ts("2026-10-23T12:01:00"),write_cap=50,query_cap=60)
            self.assertFalse(ok)
            self.assertEqual(reason,"DAILY_MODELED_WRITE_CAP")

    def test_taipei_day_rollover_starts_fresh_budget(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"daily.json"
            # 2026-10-23 23:59 Asia/Taipei
            record(p,batches=1,rows=10,modeled_writes=22,modeled_queries=25,
                   now=ts("2026-10-23T15:59:00"),write_cap=50,query_cap=60)
            before=snapshot(p,now=ts("2026-10-23T15:59:30"),write_cap=50,query_cap=60)
            after=snapshot(p,now=ts("2026-10-23T16:00:01"),write_cap=50,query_cap=60)
            self.assertEqual(before["day"],"2026-10-23")
            self.assertEqual(before["modeled_writes"],22)
            self.assertEqual(after["day"],"2026-10-24")
            self.assertEqual(after["modeled_writes"],0)

    def test_corrupt_or_over_cap_record_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"daily.json"
            p.write_text("{bad",encoding="utf-8")
            with self.assertRaises(ContractError):
                snapshot(p,now=ts("2026-10-23T12:00:00"))
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"daily.json"
            with self.assertRaises(ContractError):
                record(p,batches=1,rows=10,modeled_writes=51,modeled_queries=1,
                       now=ts("2026-10-23T12:00:00"),write_cap=50,query_cap=60)

if __name__=="__main__":
    unittest.main()
