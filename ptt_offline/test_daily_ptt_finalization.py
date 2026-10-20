from __future__ import annotations

from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from ptt_offline.daily_ptt_finalization import (
    finalize_day,
    finalize_previous_day,
    previous_taipei_day,
)
from ptt_offline.data_lifecycle_evidence import (
    build_expected_aid_contract,
    build_source_coverage,
)

TPE=ZoneInfo("Asia/Taipei")
DAY="2026-10-20"
AID="1fixture"
AUTH={
    "kind":"collector-discovery-receipt",
    "evidence_id":"fixture-authority",
    "observed_at":"2026-10-21T00:00:00Z",
    "verified":True,
    "version":"fixture-v1",
    "issuer":"collector-discovery",
}


def expected():
    return build_expected_aid_contract(
        day=DAY,
        entries=[{"period":"all_day","part":1,"aid":AID,
                  "source_url":"https://example.invalid/thread",
                  "authority_record_id":"fixture:all_day:1"}],
        authority=AUTH,
    )


def coverage(*,missing=None,final=6):
    missing=set(missing or [])
    lines=[]
    for line in range(1,final+1):
        if line in missing:
            continue
        if line in (3,4,6):
            lines.append({
                "source_line":line,"record_type":"push",
                "content_empty":line==4,"legal_empty_push":line==4,
            })
        else:
            lines.append({
                "source_line":line,"record_type":"non_push",
                "content_empty":None,"legal_empty_push":False,
            })
    return build_source_coverage(
        day=DAY,aid=AID,article_start_line=1,
        final_source_line=final,lines=lines,
    )


class DailyPttFinalizationTests(unittest.TestCase):
    def test_previous_taipei_day(self):
        now=datetime(2026,10,21,7,30,tzinfo=TPE)
        self.assertEqual(previous_taipei_day(now),"2026-10-20")

    def test_complete_day_is_verified_and_no_repair(self):
        calls=[]
        body=finalize_day(
            day=DAY,expected_contract=expected(),
            coverage_by_aid={AID:coverage()},
            repair_executor=lambda request:calls.append(request),
        )
        self.assertEqual(body["state"],"VERIFIED_COMPLETE")
        self.assertEqual(body["summary"]["verified_complete"],1)
        self.assertEqual(body["summary"]["repair_attempts"],0)
        self.assertEqual(calls,[])
        self.assertTrue(body["archive_ready"])
        self.assertTrue(body["pr147_ready"])

    def test_one_missing_range_repairs_only_that_range(self):
        calls=[]
        def repair(request):
            calls.append(request)
            return coverage()
        body=finalize_day(
            day=DAY,expected_contract=expected(),
            coverage_by_aid={AID:coverage(missing=[3,4])},
            repair_executor=repair,
        )
        self.assertEqual(calls,[{
            "day":DAY,"aid":AID,
            "missing_source_lines":[3,4],
            "repair_ranges":[[3,4]],
            "mode":"bounded-missing-ranges-only",
        }])
        self.assertEqual(body["state"],"VERIFIED_COMPLETE")
        self.assertEqual(body["summary"]["repair_attempts"],1)
        self.assertEqual(body["threads"][0]["pre_repair_state"],"REPAIR_NEEDED")

    def test_unknown_authority_never_repairs(self):
        weak=expected()
        weak["status"]="UNKNOWN"
        weak["authority"]["verified"]=False
        calls=[]
        body=finalize_day(
            day=DAY,expected_contract=weak,
            coverage_by_aid={AID:coverage(missing=[3])},
            repair_executor=lambda request:calls.append(request),
        )
        self.assertEqual(body["state"],"UNKNOWN")
        self.assertEqual(calls,[])
        self.assertEqual(body["summary"]["repair_attempts"],0)

    def test_successful_repair_rechecks_same_classifier(self):
        attempts=[]
        def repair(request):
            attempts.append(request)
            return coverage()
        body=finalize_day(
            day=DAY,expected_contract=expected(),
            coverage_by_aid={AID:coverage(missing=[2,5])},
            repair_executor=repair,
        )
        self.assertEqual(body["state"],"VERIFIED_COMPLETE")
        self.assertEqual(attempts[0]["repair_ranges"],[[2,2],[5,5]])
        self.assertEqual(body["threads"][0]["repair_result"],"VERIFIED_COMPLETE")

    def test_repair_still_incomplete_remains_repair_needed(self):
        def repair(_request):
            return coverage(missing=[5])
        body=finalize_day(
            day=DAY,expected_contract=expected(),
            coverage_by_aid={AID:coverage(missing=[2,5])},
            repair_executor=repair,
        )
        self.assertEqual(body["state"],"REPAIR_NEEDED")
        self.assertEqual(body["threads"][0]["missing_source_lines"],[5])
        self.assertFalse(body["archive_ready"])

    def test_non_authoritative_final_line_is_unknown_and_never_repairs(self):
        weak=coverage(missing=[5])
        weak["contract_gaps"]=sorted(set(
            weak.get("contract_gaps",[])+["collector-article-last-source-line-unavailable"]
        ))
        calls=[]
        body=finalize_day(
            day=DAY,expected_contract=expected(),
            coverage_by_aid={AID:weak},
            repair_executor=lambda request:calls.append(request),
        )
        self.assertEqual(body["state"],"UNKNOWN")
        self.assertEqual(calls,[])
        self.assertFalse(body["threads"][0]["repairable"])

    def test_missing_coverage_is_unknown_and_never_repairs(self):
        calls=[]
        body=finalize_day(
            day=DAY,expected_contract=expected(),coverage_by_aid={},
            repair_executor=lambda request:calls.append(request),
        )
        self.assertEqual(body["state"],"UNKNOWN")
        self.assertEqual(calls,[])

    def test_second_complete_run_is_cheap_noop(self):
        calls=[]
        first=finalize_day(
            day=DAY,expected_contract=expected(),
            coverage_by_aid={AID:coverage()},
            repair_executor=lambda request:calls.append(request),
        )
        second=finalize_day(
            day=DAY,expected_contract=expected(),
            coverage_by_aid={AID:coverage()},
            repair_executor=lambda request:calls.append(request),
        )
        self.assertEqual(first["state"],"VERIFIED_COMPLETE")
        self.assertEqual(second["state"],"VERIFIED_COMPLETE")
        self.assertEqual(calls,[])
        self.assertEqual(second["summary"]["repair_attempts"],0)

    def test_previous_day_wrapper_binds_day(self):
        now=datetime(2026,10,21,7,30,tzinfo=TPE)
        body=finalize_previous_day(
            expected_contract=expected(),
            coverage_by_aid={AID:coverage()},
            now=now,
        )
        self.assertEqual(body["day"],DAY)
        self.assertEqual(body["state"],"VERIFIED_COMPLETE")


if __name__=="__main__":
    unittest.main()
