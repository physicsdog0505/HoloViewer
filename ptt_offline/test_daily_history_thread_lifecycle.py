from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest
from zoneinfo import ZoneInfo

from ptt_offline.daily_history_runtime import _build_thread_lifecycle_source_object
from ptt_offline.daily_static_assets_archive import _validate_payload


TPE=ZoneInfo("Asia/Taipei")


def local(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TPE)


def row(*,aid: str,key: str,occurred: str,thread_start: str,floor: int) -> dict:
    epoch=int(local(thread_start).timestamp())
    return {
        "aid":aid,
        "source_line":floor+100,
        "source_record_key":key,
        "floor":floor,
        "floor_quality":"per-thread-ordinal",
        "occurred_at":local(occurred).astimezone(timezone.utc).isoformat().replace("+00:00","Z"),
        "source_url":f"https://www.ptt.cc/bbs/C_Chat/M.{epoch}.A.TEST.html",
        "content":key,
    }


class ThreadLifecycleArchiveTests(unittest.TestCase):
    def test_target_night_tail_survives_midnight_until_0730_cap(self):
        day="2026-10-22"
        day_aid="1day"
        night_aid="1night"
        successor="1next"
        payload={"pushes":[
            row(aid=day_aid,key="day",occurred="2026-10-22T09:00:00",
                thread_start="2026-10-22T08:00:00",floor=1),
            row(aid=night_aid,key="night-before-midnight",occurred="2026-10-22T23:30:00",
                thread_start="2026-10-22T18:00:00",floor=2),
            row(aid=night_aid,key="night-0609",occurred="2026-10-23T06:09:00",
                thread_start="2026-10-22T18:00:00",floor=3),
            row(aid=successor,key="next-0731",occurred="2026-10-23T07:31:00",
                thread_start="2026-10-23T07:31:00",floor=1),
        ]}
        _,raw=_build_thread_lifecycle_source_object(
            day=day,
            payloads=[payload],
            expected_aids={day_aid,night_aid},
            expected_thread_epochs={
                day_aid:local("2026-10-22T08:00:00"),
                night_aid:local("2026-10-22T18:00:00"),
            },
        )
        body=json.loads(raw)
        self.assertEqual(body["schema_version"],"holoviewer-ptt-history-day-v2")
        self.assertEqual(body["partition_kind"],"expected-thread-lifecycle")
        self.assertEqual(body["membership"]["handoff_source"],"closeout-limit")
        self.assertEqual(body["membership"]["post_midnight_tail_pushes"],1)
        self.assertEqual(
            [x["source_record_key"] for x in body["pushes"]],
            ["day","night-before-midnight","night-0609"],
        )
        self.assertNotIn("next-0731",[x["source_record_key"] for x in body["pushes"]])
        count,_,aids=_validate_payload(
            raw=raw,day=day,expected_aids={day_aid,night_aid})
        self.assertEqual(count,3)
        self.assertEqual(aids,{day_aid,night_aid})

    def test_successor_before_0730_closes_lifecycle_early(self):
        day="2026-10-22"
        night_aid="1night"
        successor="1next"
        payload={"pushes":[
            row(aid=night_aid,key="night-0615",occurred="2026-10-23T06:15:00",
                thread_start="2026-10-22T18:00:00",floor=10),
            row(aid=successor,key="next-0630",occurred="2026-10-23T06:31:00",
                thread_start="2026-10-23T06:30:00",floor=1),
            row(aid=night_aid,key="night-late-0645",occurred="2026-10-23T06:45:00",
                thread_start="2026-10-22T18:00:00",floor=11),
        ]}
        _,raw=_build_thread_lifecycle_source_object(
            day=day,
            payloads=[payload],
            expected_aids={night_aid},
            expected_thread_epochs={
                night_aid:local("2026-10-22T18:00:00"),
            },
        )
        body=json.loads(raw)
        self.assertEqual(body["membership"]["handoff_source"],"successor-thread")
        self.assertEqual(body["membership"]["successor_aid"],successor)
        self.assertEqual(
            body["membership"]["handoff_boundary"],
            local("2026-10-23T06:30:00").astimezone(timezone.utc)
                .isoformat(timespec="seconds").replace("+00:00","Z"),
        )
        self.assertEqual(
            [x["source_record_key"] for x in body["pushes"]],
            ["night-0615"],
        )

    def test_adjacent_day_does_not_reclaim_previous_night_tail(self):
        day="2026-10-23"
        prior_night="1priorNight"
        current_day="1currentDay"
        payload={"pushes":[
            row(aid=prior_night,key="prior-0609",occurred="2026-10-23T06:09:00",
                thread_start="2026-10-22T18:00:00",floor=30),
            row(aid=current_day,key="current-0731",occurred="2026-10-23T07:31:00",
                thread_start="2026-10-23T07:31:00",floor=1),
        ]}
        _,raw=_build_thread_lifecycle_source_object(
            day=day,
            payloads=[payload],
            expected_aids={current_day},
            expected_thread_epochs={
                current_day:local("2026-10-23T07:31:00"),
            },
        )
        body=json.loads(raw)
        self.assertEqual(
            [x["source_record_key"] for x in body["pushes"]],
            ["current-0731"],
        )
        excluded={x["aid"]:x["reason"] for x in body["membership"]["excluded_aids"]}
        self.assertEqual(excluded[prior_night],"previous-lifecycle-thread")


    def test_validator_rejects_closeout_limit_with_early_partition_end(self):
        day="2026-10-22"
        aid="1night"
        payload={"pushes":[
            row(aid=aid,key="night-0609",occurred="2026-10-23T06:09:00",
                thread_start="2026-10-22T18:00:00",floor=3),
        ]}
        _,raw=_build_thread_lifecycle_source_object(
            day=day,payloads=[payload],expected_aids={aid},
            expected_thread_epochs={aid:local("2026-10-22T18:00:00")})
        body=json.loads(raw)
        early=local("2026-10-23T06:30:00").astimezone(timezone.utc) \
            .isoformat(timespec="seconds").replace("+00:00","Z")
        body["partition_end"]=early
        body["membership"]["handoff_boundary"]=early
        with self.assertRaisesRegex(Exception,"closeout-limit handoff must equal closeout cap"):
            _validate_payload(
                raw=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode(),
                day=day,expected_aids={aid})

    def test_validator_rejects_successor_thread_without_successor_aid(self):
        day="2026-10-22"
        aid="1night"
        successor="1next"
        payload={"pushes":[
            row(aid=aid,key="night-0615",occurred="2026-10-23T06:15:00",
                thread_start="2026-10-22T18:00:00",floor=10),
            row(aid=successor,key="next-0630",occurred="2026-10-23T06:31:00",
                thread_start="2026-10-23T06:30:00",floor=1),
        ]}
        _,raw=_build_thread_lifecycle_source_object(
            day=day,payloads=[payload],expected_aids={aid},
            expected_thread_epochs={aid:local("2026-10-22T18:00:00")})
        body=json.loads(raw)
        body["membership"]["successor_aid"]=None
        with self.assertRaisesRegex(Exception,"successor-thread handoff requires successor AID"):
            _validate_payload(
                raw=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode(),
                day=day,expected_aids={aid})

    def test_validator_rejects_successor_aid_inside_expected_set(self):
        day="2026-10-22"
        aid="1night"
        successor="1next"
        payload={"pushes":[
            row(aid=aid,key="night-0615",occurred="2026-10-23T06:15:00",
                thread_start="2026-10-22T18:00:00",floor=10),
            row(aid=successor,key="next-0630",occurred="2026-10-23T06:31:00",
                thread_start="2026-10-23T06:30:00",floor=1),
        ]}
        _,raw=_build_thread_lifecycle_source_object(
            day=day,payloads=[payload],expected_aids={aid},
            expected_thread_epochs={aid:local("2026-10-22T18:00:00")})
        body=json.loads(raw)
        body["membership"]["successor_aid"]=aid
        with self.assertRaisesRegex(Exception,"successor-thread AID must be outside expected set"):
            _validate_payload(
                raw=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode(),
                day=day,expected_aids={aid})

    def test_validator_rejects_serialized_closeout_limit_mismatch(self):
        day="2026-10-22"
        aid="1night"
        payload={"pushes":[
            row(aid=aid,key="night-0609",occurred="2026-10-23T06:09:00",
                thread_start="2026-10-22T18:00:00",floor=3),
        ]}
        _,raw=_build_thread_lifecycle_source_object(
            day=day,payloads=[payload],expected_aids={aid},
            expected_thread_epochs={aid:local("2026-10-22T18:00:00")})
        body=json.loads(raw)
        body["membership"]["closeout_limit"]="2026-10-23T00:00:00Z"
        with self.assertRaisesRegex(Exception,"day.json closeout limit mismatch"):
            _validate_payload(
                raw=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode(),
                day=day,expected_aids={aid})


if __name__=="__main__":
    unittest.main()
