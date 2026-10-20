from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ptt_offline.daily_static_assets_archive import (
    DailyArchiveError,
    build_archive_delivery_evidence,
    build_daily_static_package,
    compute_source_snapshot_hash,
    prepare_static_assets_delivery,
    verify_http_readback,
)


DAY="2026-10-20"
SOURCE_REVISION="ptt-finalized-2026-10-20-r1"
JOB_ID="archive-2026-10-20-attempt-1"


def _receipt(state="VERIFIED_COMPLETE"):
    body={
        "schema_version":"holoviewer-ptt-daily-finalization-v1",
        "sanitized":True,
        "day":DAY,
        "state":state,
        "observed_at":"2026-10-21T07:30:00+08:00",
        "expected_set":{
            "schema_version":"holoviewer-ptt-expected-aids-v1",
            "status":"COMPLETE",
            "evidence_digest":"b"*64,
            "authority":{
                "verified":True,
                "day":DAY,
                "version":"expected-aids-2026-10-20-r1",
            },
            "expected_aids":["1abcDAY","1abcNIGHT"],
        },
        "threads":[],
        "summary":{},
        "archive_ready":state=="VERIFIED_COMPLETE",
        "pr147_ready":state=="VERIFIED_COMPLETE",
        "contract_gaps":[],
        "conflicts":[],
        "safety":{},
        "evidence_digest":"c"*64,
    }
    return body


def _object(aid="1abcDAY",floor=1):
    payload={
        "schema_version":"holoviewer-ptt-history-v1",
        "pushes":[{
            "aid":aid,
            "coverage_day":DAY,
            "source_line":100+floor,
            "source_record_key":f"{DAY}:{aid}:{100+floor}",
            "floor":floor,
            "occurred_at":"2026-10-20T01:00:00Z",
            "content":"",
        }],
    }
    return json.dumps(
        payload,ensure_ascii=False,sort_keys=True,separators=(",",":")
    ).encode("utf-8")


class DailyStaticAssetsArchiveTests(unittest.TestCase):
    def _build(self,root: Path,receipt=None,source_objects=None):
        receipt=receipt or _receipt()
        source_objects=source_objects or [
            ("0100.json",_object("1abcDAY",1)),
            ("0200.json",_object("1abcNIGHT",2)),
        ]
        source_hash=compute_source_snapshot_hash(
            finalization_receipt=receipt,
            source_revision=SOURCE_REVISION,
            source_objects=source_objects,
        )
        return build_daily_static_package(
            finalization_receipt=receipt,
            source_revision=SOURCE_REVISION,
            source_hash=source_hash,
            source_objects=source_objects,
            out_dir=root,
        )

    def _remote(self,root: Path):
        return lambda key:(root/key).read_bytes()

    def test_verified_complete_day_builds_immutable_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            package=self._build(Path(tmp))
            self.assertEqual(package["package_status"],"COMPLETE")
            self.assertTrue(package["immutable"])
            self.assertEqual(package["taipei_day"],DAY)
            self.assertEqual(package["object_count"],2)
            self.assertTrue((Path(tmp)/package["manifest"]["key"]).is_file())
            self.assertEqual(set(package["expected_aids"]),{"1abcDAY","1abcNIGHT"})

    def test_unknown_and_repair_needed_fail_closed(self):
        for state in ("UNKNOWN","REPAIR_NEEDED"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(DailyArchiveError,"not VERIFIED_COMPLETE"):
                    self._build(Path(tmp),receipt=_receipt(state))

    def test_delivery_failure_does_not_change_source_completeness(self):
        with tempfile.TemporaryDirectory() as tmp:
            package=self._build(Path(tmp))
            evidence=build_archive_delivery_evidence(
                package=package,
                finalization_receipt=_receipt(),
                job_id=JOB_ID,
                job_status="failed",
                attempted_at="2026-10-21T07:31:00+08:00",
                succeeded_at=None,
                attempt_count=1,
                uploaded_count=0,
                readback_receipt=None,
                error_code="static-assets-delivery-failed",
            )
            self.assertEqual(evidence["job_status"],"failed")
            self.assertFalse(evidence["job_verified"])
            self.assertEqual(evidence["coverage_summary"]["status"],"COMPLETE")
            self.assertEqual(
                evidence["expected_aid_completeness"]["status"],"COMPLETE")

    def test_delivery_success_but_hash_failure_is_not_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            package=self._build(root)
            bad_key=package["objects"][0]["key"]
            def fetch(key):
                raw=(root/key).read_bytes()
                return b"{}" if key==bad_key else raw
            receipt=verify_http_readback(
                package=package,
                job_id=JOB_ID,
                fetch_bytes=fetch,
                observed_at="2026-10-21T07:32:00+08:00",
            )
            self.assertFalse(receipt["job_verified"])
            self.assertEqual(receipt["error_code"],"object_hash_mismatch")
            evidence=build_archive_delivery_evidence(
                package=package,
                finalization_receipt=_receipt(),
                job_id=JOB_ID,
                job_status="succeeded",
                attempted_at="2026-10-21T07:31:00+08:00",
                succeeded_at="2026-10-21T07:31:30+08:00",
                attempt_count=1,
                uploaded_count=2,
                readback_receipt=receipt,
            )
            self.assertEqual(evidence["job_status"],"succeeded")
            self.assertFalse(evidence["job_verified"])
            self.assertEqual(evidence["coverage_summary"]["status"],"COMPLETE")

    def test_retry_same_package_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            first=self._build(root)
            before={p.relative_to(root).as_posix():p.read_bytes()
                    for p in root.rglob("*") if p.is_file()}
            second=self._build(root)
            after={p.relative_to(root).as_posix():p.read_bytes()
                   for p in root.rglob("*") if p.is_file()}
            self.assertEqual(first,second)
            self.assertEqual(before,after)
            plan1=prepare_static_assets_delivery(package=first,job_id=JOB_ID)
            plan2=prepare_static_assets_delivery(package=second,job_id=JOB_ID)
            self.assertEqual(plan1,plan2)
            self.assertFalse(plan1["production_execution"])
            self.assertFalse(plan1["deploy_authorized"])

    def test_unrelated_historical_days_remain_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            other=root/"ptt/v1/history/2026-10-19/old/0100.json"
            other.parent.mkdir(parents=True)
            other.write_bytes(b'{"keep":"byte-identical"}')
            before=other.read_bytes()
            self._build(root)
            self.assertEqual(other.read_bytes(),before)

    def test_manifest_digest_and_object_sha_are_both_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            package=self._build(root)
            good=verify_http_readback(
                package=package,
                job_id=JOB_ID,
                fetch_bytes=self._remote(root),
                observed_at="2026-10-21T07:32:00+08:00",
            )
            self.assertTrue(good["job_verified"])
            self.assertTrue(good["manifest_digest_match"])
            self.assertTrue(good["content_hash_match"])

            manifest_key=package["manifest"]["key"]
            def bad_manifest(key):
                raw=(root/key).read_bytes()
                return raw+b" " if key==manifest_key else raw
            bad=verify_http_readback(
                package=package,
                job_id="archive-2026-10-20-attempt-2",
                fetch_bytes=bad_manifest,
                observed_at="2026-10-21T07:33:00+08:00",
            )
            self.assertFalse(bad["job_verified"])
            self.assertEqual(bad["error_code"],"manifest_digest_mismatch")

    def test_source_hash_must_bind_exact_input_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(DailyArchiveError,"source_hash does not bind"):
                build_daily_static_package(
                    finalization_receipt=_receipt(),
                    source_revision=SOURCE_REVISION,
                    source_hash="a"*64,
                    source_objects=[("0100.json",_object("1abcDAY",1))],
                    out_dir=Path(tmp),
                )

    def test_package_rejects_rows_outside_verified_identity_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(DailyArchiveError,"outside verified expected set"):
                self._build(
                    Path(tmp),
                    source_objects=[("0100.json",_object("1notExpected",1))],
                )


if __name__=="__main__":
    unittest.main()
