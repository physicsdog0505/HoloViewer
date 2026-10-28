from __future__ import annotations

import copy
import json
import unittest
from hashlib import sha256

from ptt_offline.monthly_catalog import (
    CATALOG_SCHEMA,
    DAILY_SCHEMA,
    LEGACY_SCHEMA,
    MonthlyCatalogError,
    advance_verified_daily,
    canonical_bytes,
    seed_verified_legacy,
)


def z(day: str, hhmm: str) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(day + "T" + hhmm + ":00+08:00").astimezone(
        ZoneInfo("UTC")
    ).isoformat(timespec="seconds").replace("+00:00", "Z")


def fixture_day(day: str, pushes: int, *, lifecycle=False):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    start = z(day, "00:00")
    if lifecycle:
        dt = datetime.fromisoformat(day + "T00:00:00+08:00") + timedelta(days=1, hours=1)
        end = dt.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds").replace("+00:00", "Z")
        closeout = (datetime.fromisoformat(day + "T00:00:00+08:00") + timedelta(days=1, hours=7, minutes=30)).astimezone(
            ZoneInfo("UTC")
        ).isoformat(timespec="seconds").replace("+00:00", "Z")
        schema = "holoviewer-ptt-history-day-v2"
        membership = {
            "rule": "expected-thread-lifecycle-v2", "silent_drop": False,
            "handoff_boundary": end, "closeout_limit": closeout,
            "handoff_source": "successor-thread", "successor_aid": "next",
            "expected_aids": ["aid"],
        }
        extra = {"partition_kind": "expected-thread-lifecycle"}
    else:
        dt = datetime.fromisoformat(day + "T00:00:00+08:00") + timedelta(days=1)
        end = dt.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds").replace("+00:00", "Z")
        schema = "holoviewer-ptt-history-day-v1"
        membership = {
            "rule": "taipei-day-expected-plus-direct-predecessor-v1",
            "silent_drop": False, "expected_aids": ["aid"],
        }
        extra = {}
    rows = [{
        "aid": "aid", "source_line": i + 1, "source_record_key": f"aid:{i+1}",
        "occurred_at": z(day, "12:00"), "coverage_day": day, "floor": i + 1,
        "floor_quality": "per-thread-ordinal", "content": f"p{i}",
    } for i in range(pushes)]
    payload = {
        "schema_version": schema, "partition_start": start, "partition_end": end,
        "membership": membership, "pushes": rows, **extra,
    }
    raw = canonical_bytes(payload)
    key = f"ptt/v1/history/{day}/source/day.json"
    manifest = {
        "schema_version": DAILY_SCHEMA, "taipei_day": day,
        "source_hash": sha256(("source:" + day).encode()).hexdigest(),
        "total_objects": 1, "total_pushes": pushes,
        "objects": [{"key": key, "sha256": sha256(raw).hexdigest(), "bytes": len(raw), "pushes": pushes}],
    }
    manifest_raw = canonical_bytes(manifest)
    manifest_key = f"ptt/v1/manifests/daily/{day}/{sha256(manifest_raw).hexdigest()}.json"
    return manifest_key, manifest_raw, {key: raw}


def evidence(day, manifest_raw):
    return (
        {"day": day, "state": "VERIFIED_COMPLETE", "archive_ready": True},
        {
            "day": day, "job_verified": True, "manifest_verified": True,
            "manifest_digest": sha256(manifest_raw).hexdigest(),
            "remote_readback": {
                "object_sha_verified": True, "push_count_verified": True,
                "partition_range_verified": True,
            },
        },
    )


def legacy_fixture():
    obj = {
        "key": "ptt/v1/months/2026-10/chunks/2026/10/01/0000.json",
        "sha256": "1" * 64, "bytes": 10, "pushes": 1,
        "bucket_start": "2026-09-30T16:00:00Z", "bucket_end": "2026-09-30T17:00:00Z",
        "coverage_status": "COMPLETE", "finalized": True,
    }
    manifest = {
        "schema_version": LEGACY_SCHEMA, "precision": "minute", "timezone": "UTC",
        "month": "2026-10", "objects": [obj],
        "days": [{"day": f"2026-10-{i:02d}", "coverage_status": "COMPLETE", "finalized": True}
                 for i in range(1, 18)]
                + [{"day": "2026-10-18", "coverage_status": "PARTIAL", "finalized": False}],
    }
    return canonical_bytes(manifest)


class MonthlyCatalogTests(unittest.TestCase):
    def advance(self, day, count, existing=None, **kw):
        key, mraw, objects = fixture_day(day, count, lifecycle=kw.pop("lifecycle", False))
        fin, job = evidence(day, mraw)
        result = advance_verified_daily(
            month="2026-10", existing_catalog_raw=existing,
            downstream_authorized=kw.pop("authorized", True),
            finalization=kw.pop("finalization", fin),
            archive_job=kw.pop("archive_job", job),
            base_url="https://holoviewer-ptt-static-assets.singlebagel.workers.dev",
            manifest_key=key, manifest_raw=kw.pop("manifest_raw", mraw),
            object_loader=kw.pop("object_loader", lambda k: objects[k]),
        )
        return result, (key, mraw, objects, fin, job)

    def test_first_verified_day_creates_monthly_catalog(self):
        result, _ = self.advance("2026-10-24", 2294)
        self.assertTrue(result["changed"])
        self.assertEqual(result["catalog"]["schema_version"], CATALOG_SCHEMA)
        self.assertEqual(result["catalog"]["days"][0]["push_count"], 2294)
        self.assertEqual(result["key"], "ptt/v1/manifests/monthly/2026-10.json")

    def test_second_verified_day_appends_incrementally(self):
        first, _ = self.advance("2026-10-24", 2294)
        second, _ = self.advance("2026-10-25", 2232, existing=first["raw"])
        self.assertEqual([x["day"] for x in second["catalog"]["days"]], ["2026-10-24", "2026-10-25"])
        self.assertEqual(second["catalog"]["days"][1]["push_count"], 2232)

    def test_same_day_same_digest_is_idempotent_noop(self):
        first, bundle = self.advance("2026-10-24", 2294)
        key, mraw, objects, fin, job = bundle
        second = advance_verified_daily(
            month="2026-10", existing_catalog_raw=first["raw"], downstream_authorized=True,
            finalization=fin, archive_job=job,
            base_url="https://holoviewer-ptt-static-assets.singlebagel.workers.dev",
            manifest_key=key, manifest_raw=mraw, object_loader=lambda k: objects[k],
        )
        self.assertFalse(second["changed"])
        self.assertEqual(second["raw"], first["raw"])

    def test_same_day_different_digest_fails_closed(self):
        first, _ = self.advance("2026-10-24", 2294)
        key, mraw, objects = fixture_day("2026-10-24", 3)
        fin, job = evidence("2026-10-24", mraw)
        with self.assertRaisesRegex(MonthlyCatalogError, "conflicting verified digest"):
            advance_verified_daily(
                month="2026-10", existing_catalog_raw=first["raw"], downstream_authorized=True,
                finalization=fin, archive_job=job, base_url="https://holoviewer-ptt-static-assets.singlebagel.workers.dev",
                manifest_key=key, manifest_raw=mraw, object_loader=lambda k: objects[k],
            )

    def test_deploy_or_readback_failure_leaves_monthly_unchanged(self):
        first, bundle = self.advance("2026-10-24", 2294)
        _, _, _, _, job = bundle
        bad_job = copy.deepcopy(job); bad_job["job_verified"] = False
        with self.assertRaises(MonthlyCatalogError):
            self.advance("2026-10-25", 2232, existing=first["raw"], archive_job=bad_job)
        self.assertEqual([x["day"] for x in json.loads(first["raw"])["days"]], ["2026-10-24"])

    def test_incomplete_day_cannot_enter_catalog(self):
        key, mraw, objects = fixture_day("2026-10-25", 2)
        fin, job = evidence("2026-10-25", mraw); fin["state"] = "REPAIR_NEEDED"
        with self.assertRaisesRegex(MonthlyCatalogError, "not VERIFIED_COMPLETE"):
            advance_verified_daily(
                month="2026-10", existing_catalog_raw=None, downstream_authorized=True,
                finalization=fin, archive_job=job, base_url="https://holoviewer-ptt-static-assets.singlebagel.workers.dev",
                manifest_key=key, manifest_raw=mraw, object_loader=lambda k: objects[k],
            )

    def test_legacy_and_daily_days_coexist(self):
        legacy = seed_verified_legacy(
            month="2026-10", existing_catalog_raw=None,
            base_url="https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev",
            manifest_key="ptt/v1/manifests/static-assets-full-2026-10.json",
            manifest_raw=legacy_fixture(), legacy_readback_verified=True,
        )
        self.assertEqual(len(legacy["catalog"]["days"]), 17)
        daily, _ = self.advance("2026-10-24", 2294, existing=legacy["raw"])
        daily2, _ = self.advance("2026-10-25", 2232, existing=daily["raw"])
        days = {x["day"]: x for x in daily2["catalog"]["days"]}
        self.assertEqual(days["2026-10-01"]["source"]["kind"], "legacy-archive-v1")
        self.assertEqual(days["2026-10-17"]["source"]["kind"], "legacy-archive-v1")
        self.assertEqual(days["2026-10-24"]["source"]["kind"], "daily-package-v1")
        self.assertEqual(days["2026-10-25"]["push_count"], 2232)
        self.assertNotIn("2026-10-18", days)

    def test_unverified_legacy_cannot_be_relabeled_complete(self):
        with self.assertRaisesRegex(MonthlyCatalogError, "lacks verified readback"):
            seed_verified_legacy(
                month="2026-10", existing_catalog_raw=None, base_url="https://legacy.example",
                manifest_key="ptt/v1/manifests/static-assets-full-2026-10.json",
                manifest_raw=legacy_fixture(), legacy_readback_verified=False,
            )

    def test_bad_sha_rejected(self):
        key, mraw, objects = fixture_day("2026-10-24", 2)
        manifest = json.loads(mraw); manifest["objects"][0]["sha256"] = "0" * 64
        tampered = canonical_bytes(manifest); fin, job = evidence("2026-10-24", tampered)
        with self.assertRaisesRegex(MonthlyCatalogError, "SHA mismatch"):
            advance_verified_daily(
                month="2026-10", existing_catalog_raw=None, downstream_authorized=True,
                finalization=fin, archive_job=job, base_url="https://example.test",
                manifest_key=key, manifest_raw=tampered, object_loader=lambda k: objects[k],
            )

    def test_bad_push_count_rejected(self):
        key, mraw, objects = fixture_day("2026-10-24", 2)
        manifest = json.loads(mraw); manifest["objects"][0]["pushes"] = 3
        tampered = canonical_bytes(manifest); fin, job = evidence("2026-10-24", tampered)
        with self.assertRaisesRegex(MonthlyCatalogError, "push count mismatch"):
            advance_verified_daily(
                month="2026-10", existing_catalog_raw=None, downstream_authorized=True,
                finalization=fin, archive_job=job, base_url="https://example.test",
                manifest_key=key, manifest_raw=tampered, object_loader=lambda k: objects[k],
            )

    def test_bad_partition_range_rejected(self):
        key, mraw, objects = fixture_day("2026-10-24", 2)
        k = next(iter(objects)); payload = json.loads(objects[k]); payload["partition_end"] = payload["partition_start"]
        bad = canonical_bytes(payload); manifest = json.loads(mraw); manifest["objects"][0]["sha256"] = sha256(bad).hexdigest()
        tampered = canonical_bytes(manifest); fin, job = evidence("2026-10-24", tampered)
        with self.assertRaisesRegex(MonthlyCatalogError, "partition range mismatch"):
            advance_verified_daily(
                month="2026-10", existing_catalog_raw=None, downstream_authorized=True,
                finalization=fin, archive_job=job, base_url="https://example.test",
                manifest_key=key, manifest_raw=tampered, object_loader=lambda _: bad,
            )

    def test_duplicate_source_record_key_rejected(self):
        key, mraw, objects = fixture_day("2026-10-24", 2)
        k = next(iter(objects)); payload = json.loads(objects[k])
        payload["pushes"][1]["source_record_key"] = payload["pushes"][0]["source_record_key"]
        bad = canonical_bytes(payload); manifest = json.loads(mraw); manifest["objects"][0]["sha256"] = sha256(bad).hexdigest()
        tampered = canonical_bytes(manifest); fin, job = evidence("2026-10-24", tampered)
        with self.assertRaisesRegex(MonthlyCatalogError, "duplicate source_record_key"):
            advance_verified_daily(
                month="2026-10", existing_catalog_raw=None, downstream_authorized=True,
                finalization=fin, archive_job=job, base_url="https://example.test",
                manifest_key=key, manifest_raw=tampered, object_loader=lambda _: bad,
            )

    def test_taipei_midnight_boundary_pass(self):
        result, _ = self.advance("2026-10-24", 1)
        day = result["catalog"]["days"][0]
        self.assertEqual(day["partition_start"], "2026-10-23T16:00:00Z")
        self.assertEqual(day["partition_end"], "2026-10-24T16:00:00Z")

    def test_lifecycle_v2_partition_end_pass(self):
        result, _ = self.advance("2026-10-25", 1, lifecycle=True)
        day = result["catalog"]["days"][0]
        self.assertEqual(day["partition_start"], "2026-10-24T16:00:00Z")
        self.assertEqual(day["partition_end"], "2026-10-25T17:00:00Z")

    def test_downstream_authorized_false_blocks_publication(self):
        with self.assertRaisesRegex(MonthlyCatalogError, "downstream_authorized=false"):
            self.advance("2026-10-24", 1, authorized=False)

    def test_downstream_authorized_true_verified_package_advances(self):
        result, _ = self.advance("2026-10-25", 2232, authorized=True)
        self.assertEqual(result["catalog"]["updated_through"], "2026-10-25")

    def test_acceptance_fixture_counts(self):
        r24, _ = self.advance("2026-10-24", 2294)
        r25, _ = self.advance("2026-10-25", 2232, existing=r24["raw"])
        by_day = {x["day"]: x for x in r25["catalog"]["days"]}
        self.assertEqual(by_day["2026-10-24"]["push_count"], 2294)
        self.assertEqual(by_day["2026-10-25"]["push_count"], 2232)


if __name__ == "__main__":
    unittest.main()
