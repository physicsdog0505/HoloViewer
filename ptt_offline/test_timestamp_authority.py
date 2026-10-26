import unittest

from ptt_offline.public_today_contract import ContractError
from ptt_offline.timestamp_authority import resolve_source_timestamp, selected_taipei_day


class TimestampAuthorityTests(unittest.TestCase):
    def test_requires_explicit_year_timezone_and_source_ref(self):
        base=dict(ptt_date="12/31",ptt_time="23:59")
        for evidence in (
            {},
            {"authority":"verified_ptt_screen_calendar","year":2026,"timezone":"UTC","source_ref":"screen:1"},
            {"authority":"verified_ptt_screen_calendar","year":2026,"timezone":"Asia/Taipei"},
            {"authority":"guess","year":2026,"timezone":"Asia/Taipei","source_ref":"screen:1"},
        ):
            with self.subTest(evidence=evidence):
                with self.assertRaises(ContractError):
                    resolve_source_timestamp(**base,evidence=evidence)

    def test_year_rollover_is_never_inferred(self):
        e2025={"authority":"verified_ptt_screen_calendar","year":2025,
               "timezone":"Asia/Taipei","source_ref":"fixture:2025"}
        e2026={"authority":"verified_ptt_screen_calendar","year":2026,
               "timezone":"Asia/Taipei","source_ref":"fixture:2026"}
        a=resolve_source_timestamp(ptt_date="01/01",ptt_time="00:01",evidence=e2025)
        b=resolve_source_timestamp(ptt_date="01/01",ptt_time="00:01",evidence=e2026)
        self.assertEqual(selected_taipei_day(a),"2025-01-01")
        self.assertEqual(selected_taipei_day(b),"2026-01-01")
        self.assertNotEqual(a,b)

    def test_invalid_calendar_fails_closed(self):
        evidence={"authority":"verified_archive_calendar","year":2026,
                  "timezone":"Asia/Taipei","source_ref":"archive:fixture"}
        with self.assertRaises(ContractError):
            resolve_source_timestamp(ptt_date="02/30",ptt_time="12:00",evidence=evidence)


if __name__=="__main__":
    unittest.main()
