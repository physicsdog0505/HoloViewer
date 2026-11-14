from __future__ import annotations

from copy import deepcopy
import json
import unittest

from ptt_offline.monthly_archive_pipeline import (
    MonthlyArchivePipelineError,
    advance_month_candidate,
    build_month_candidate_from_state,
    canonical_bytes,
    digest_bytes,
)
from pathlib import Path
import tempfile


def base_manifest():
    return {
        "schema_version":"ptt-r2-archive-v1","precision":"minute",
        "timezone":"UTC","chunk_minutes":60,"from_day_taipei":"2026-11-05",
        "through_day_taipei":"2026-11-05","generated_at":"old",
        "pushes":1,"total_pushes":1,"total_objects":1,"total_canonical_bytes":10,
        "source_archive_manifest_sha256":"a"*64,
        "days":[{"day":"2026-11-05","coverage_status":"COMPLETE",
                 "finalized":True,"push_count":1}],
        "objects":[{"key":"ptt/v1/chunks/2026/11/05/1500.json",
                    "bucket_start":"2026-11-05T15:00:00Z",
                    "bucket_end":"2026-11-05T16:00:00Z","pushes":1,
                    "sha256":"b"*64,"bytes_json":10}],
    }


def daily_fixture(day="2026-11-06"):
    payload={
        "schema_version":"holoviewer-ptt-history-day-v2","precision":"minute",
        "timezone":"Asia/Taipei","partition_start":"2026-11-05T16:00:00Z",
        "partition_end":"2026-11-06T23:10:00Z","coverage_day":day,
        "coverage_status":"COMPLETE","finalized":True,
        "membership":{"expected_aids":["aid1","aid2"]},
        "pushes":[
            {"aid":"aid1","source_line":1,"source_record_key":"aid1:1",
             "occurred_at":"2026-11-05T16:01:00Z"},
            {"aid":"aid2","source_line":2,"source_record_key":"aid2:2",
             "occurred_at":"2026-11-06T23:00:00Z"},
        ],
    }
    raw=canonical_bytes(payload)
    key=f"ptt/v1/history/{day}/source/day.json"
    manifest_digest="c"*64
    package={
        "schema_version":"holoviewer-ptt-daily-static-package-v1",
        "taipei_day":day,"package_status":"COMPLETE","immutable":True,
        "expected_aids":["aid1","aid2"],"push_count":2,
        "manifest":{"key":f"ptt/v1/manifests/daily/{day}/{manifest_digest}.json",
                    "digest":manifest_digest},
        "objects":[{"key":key,"sha256":digest_bytes(raw),"pushes":2}],
    }
    job={"job_verified":True,"manifest":deepcopy(package["manifest"])}
    return package,job,{key:raw}


class MonthlyArchivePipelineTests(unittest.TestCase):
    def test_verified_daily_appends_reader_compatible_object(self):
        package,job,objects=daily_fixture()
        result=advance_month_candidate(
            month="2026-11",existing_manifest=base_manifest(),package=package,
            archive_job=job,object_loader=objects.__getitem__,
            generated_at="2026-11-14T12:00:00Z")

        self.assertTrue(result["changed"])
        manifest=result["manifest"]
        self.assertEqual(manifest["through_day_taipei"],"2026-11-06")
        self.assertEqual(manifest["total_pushes"],3)
        self.assertEqual(manifest["total_objects"],2)
        self.assertEqual(manifest["days"][-1]["coverage_status"],"COMPLETE")
        payload=json.loads(result["object"]["raw"])
        self.assertEqual(payload["schema_version"],"ptt-r2-archive-v1")
        self.assertEqual(payload["bucket_end"],"2026-11-06T23:10:00Z")
        self.assertEqual(len(payload["pushes"]),2)

    def test_unverified_job_is_rejected(self):
        package,job,objects=daily_fixture()
        job["job_verified"]=False
        with self.assertRaisesRegex(MonthlyArchivePipelineError,"not verified"):
            advance_month_candidate(
                month="2026-11",existing_manifest=base_manifest(),package=package,
                archive_job=job,object_loader=objects.__getitem__,generated_at="now")

    def test_conflicting_existing_day_fails_closed(self):
        package,job,objects=daily_fixture(day="2026-11-05")
        with self.assertRaisesRegex(MonthlyArchivePipelineError,"different identity"):
            advance_month_candidate(
                month="2026-11",existing_manifest=base_manifest(),package=package,
                archive_job=job,object_loader=objects.__getitem__,generated_at="now")

    def test_duplicate_daily_identity_is_rejected(self):
        package,job,objects=daily_fixture()
        payload=json.loads(next(iter(objects.values())))
        payload["pushes"][1]["source_record_key"]="aid1:1"
        raw=canonical_bytes(payload)
        key=package["objects"][0]["key"]
        objects[key]=raw
        package["objects"][0]["sha256"]=digest_bytes(raw)
        with self.assertRaisesRegex(MonthlyArchivePipelineError,"identities"):
            advance_month_candidate(
                month="2026-11",existing_manifest=base_manifest(),package=package,
                archive_job=job,object_loader=objects.__getitem__,generated_at="now")

    def test_state_builder_advances_only_verified_available_days(self):
        package,job,objects=daily_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            day_dir=root/"archive"/"2026-11-06"
            day_dir.mkdir(parents=True)
            (day_dir/"package.json").write_text(json.dumps(package),encoding="utf-8")
            (day_dir/"archive-job.json").write_text(json.dumps(job),encoding="utf-8")
            for key,raw in objects.items():
                target=root/"static-public"/key
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(raw)
            missing=root/"archive"/"2026-11-07"
            missing.mkdir(parents=True)

            result=build_month_candidate_from_state(
                month="2026-11",existing_manifest=base_manifest(),
                state_root=root,generated_at="2026-11-14T12:00:00Z")

        self.assertEqual(result["processed_days"],["2026-11-06"])
        self.assertEqual(result["skipped_days"],[{
            "day":"2026-11-07","reason":"verified-package-receipt-unavailable"}])
        self.assertEqual(len(result["objects"]),1)


if __name__=="__main__":
    unittest.main()
