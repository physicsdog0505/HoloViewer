from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from ptt_offline.monthly_archive_pipeline import canonical_bytes, digest_bytes
from ptt_offline.monthly_archive_release import (
    MonthlyArchiveReleaseError,
    deploy_prepared_release,
    prepare_release,
)


class MonthlyArchiveReleaseTests(unittest.TestCase):
    def fixture(self,root: Path):
        old_payload={"schema_version":"ptt-r2-archive-v1","precision":"minute",
                     "bucket_start":"2026-11-05T15:00:00Z","bucket_end":"2026-11-05T16:00:00Z",
                     "pushes":[{"source_record_key":"old:1"}]}
        old_raw=canonical_bytes(old_payload)
        manifest={
            "schema_version":"ptt-r2-archive-v1","precision":"minute","timezone":"UTC",
            "from_day_taipei":"2026-11-05","through_day_taipei":"2026-11-05",
            "days":[{"day":"2026-11-05","coverage_status":"COMPLETE","finalized":True,"push_count":1}],
            "objects":[{"key":"ptt/v1/chunks/old.json","bucket_start":old_payload["bucket_start"],
                        "bucket_end":old_payload["bucket_end"],"pushes":1,
                        "sha256":digest_bytes(old_raw),"bytes_json":len(old_raw)}],
            "pushes":1,"total_pushes":1,"total_objects":1,"total_canonical_bytes":len(old_raw),
            "source_archive_manifest_sha256":"a"*64,
        }
        day_payload={"schema_version":"holoviewer-ptt-history-day-v2","precision":"minute",
                     "timezone":"Asia/Taipei","partition_start":"2026-11-05T16:00:00Z",
                     "partition_end":"2026-11-06T23:00:00Z","coverage_day":"2026-11-06",
                     "coverage_status":"COMPLETE","finalized":True,
                     "pushes":[{"source_record_key":"new:1"}]}
        day_raw=canonical_bytes(day_payload)
        key="ptt/v1/history/2026-11-06/source/day.json"
        digest="b"*64
        package={"schema_version":"holoviewer-ptt-daily-static-package-v1",
                 "taipei_day":"2026-11-06","package_status":"COMPLETE","immutable":True,
                 "expected_aids":["new"],"push_count":1,
                 "manifest":{"key":"ptt/v1/manifests/daily/2026-11-06/x.json","digest":digest},
                 "objects":[{"key":key,"sha256":digest_bytes(day_raw),"pushes":1}]}
        job={"job_verified":True,"manifest":package["manifest"]}
        archive=root/"state"/"archive"/"2026-11-06"; archive.mkdir(parents=True)
        (archive/"package.json").write_text(json.dumps(package),encoding="utf-8")
        (archive/"archive-job.json").write_text(json.dumps(job),encoding="utf-8")
        target=root/"state"/"static-public"/key; target.parent.mkdir(parents=True)
        target.write_bytes(day_raw)
        base="https://assets.invalid"
        manifest_key="ptt/v1/manifests/static-assets-full-2026-11.json"
        remote={base+"/"+manifest_key:canonical_bytes(manifest),base+"/ptt/v1/chunks/old.json":old_raw}
        return base,manifest_key,remote

    def test_prepare_mirrors_old_assets_and_appends_daily(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); base,key,remote=self.fixture(root)
            receipt=prepare_release(
                month="2026-11",base_url=base,manifest_key=key,target="monthly-target",
                state_root=root/"state",release_root=root/"release",generated_at="now",
                fetcher=remote.__getitem__)
            candidate=Path(receipt["candidate_public"])
            rollback=Path(receipt["rollback_public"])
            self.assertTrue((candidate/"ptt/v1/chunks/old.json").is_file())
            self.assertTrue((rollback/"ptt/v1/chunks/old.json").is_file())
            self.assertEqual(receipt["processed_days"],["2026-11-06"])
            self.assertTrue(receipt["deployable"])
            self.assertEqual(receipt["fetched_existing_objects"],1)

            second=prepare_release(
                month="2026-11",base_url=base,manifest_key=key,target="monthly-target",
                state_root=root/"state",release_root=root/"release",generated_at="now",
                fetcher=remote.__getitem__)
            self.assertEqual(second["fetched_existing_objects"],0)
            self.assertEqual(second["reused_cached_objects"],1)

    def test_readback_failure_runs_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); base,key,remote=self.fixture(root)
            receipt=prepare_release(
                month="2026-11",base_url=base,manifest_key=key,target="monthly-target",
                state_root=root/"state",release_root=root/"release",generated_at="now",
                fetcher=remote.__getitem__)
            calls=[]
            def runner(command):
                calls.append(command)
                return subprocess.CompletedProcess(command,0,"ok","")
            with self.assertRaisesRegex(MonthlyArchiveReleaseError,"rollback_verified=true"):
                deploy_prepared_release(
                    receipt=receipt,wrangler_command=["wrangler"],
                    runner=runner,fetcher=remote.__getitem__)
            self.assertEqual(len(calls),2)

    def test_manifest_drift_blocks_before_deploy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); base,key,remote=self.fixture(root)
            receipt=prepare_release(
                month="2026-11",base_url=base,manifest_key=key,target="monthly-target",
                state_root=root/"state",release_root=root/"release",generated_at="now",
                fetcher=remote.__getitem__)
            remote[base+"/"+key]=b'{"changed":true}'
            calls=[]
            def runner(command):
                calls.append(command)
                return subprocess.CompletedProcess(command,0,"ok","")
            with self.assertRaisesRegex(
                    MonthlyArchiveReleaseError,"changed after release preparation"):
                deploy_prepared_release(
                    receipt=receipt,wrangler_command=["wrangler"],
                    runner=runner,fetcher=remote.__getitem__)
            self.assertEqual(calls,[])


if __name__=="__main__":
    unittest.main()
