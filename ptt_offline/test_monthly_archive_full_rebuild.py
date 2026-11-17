from __future__ import annotations

from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from ptt_offline.monthly_archive_full_rebuild import (
    MonthlyArchiveFullRebuildError,
    _merge_source_rows,
    repack_hourly_month,
)
from ptt_offline.monthly_archive_pipeline import canonical_bytes, digest_bytes


class MonthlyArchiveFullRebuildTests(unittest.TestCase):
    def fixture(self,root: Path):
        rows=[]
        for day in range(1,32):
            occurred=f"2026-10-{day:02d}T04:00:00Z"
            rows.append({"occurred_at":occurred,"minute_epoch":int(
                datetime.fromisoformat(occurred.replace("Z","+00:00")).timestamp()//60),
                "aid":"aid","source_line":day,"source_record_key":f"aid:{day}"})
        payload={"schema_version":"ptt-r2-archive-v1","precision":"minute",
                 "bucket_start":"2026-10-01T04:00:00Z",
                 "bucket_end":"2026-11-01T04:00:00Z","pushes":rows}
        raw=canonical_bytes(payload)
        key="ptt/v1/chunks/all.json.gz"
        target=root/key; target.parent.mkdir(parents=True)
        with gzip.open(target,"wb") as handle:
            handle.write(raw)
        export={"pushes":31,"repair_overlap_rows_removed":0,
                "objects":[{"key":key,"sha256":digest_bytes(raw),"pushes":31}]}
        coverage={"schema_version":"holoviewer-ptt-month-coverage-v1","month":"2026-10",
                  "days":[{"day":f"2026-10-{day:02d}","coverage_status":"COMPLETE",
                           "finalized":True,"required_aids":["aid"],
                           "evidence":["fixture"]} for day in range(1,32)]}
        return export,json.dumps(coverage).encode()

    def test_rebuild_writes_one_object_per_taipei_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); hourly=root/"hourly"; public=root/"public"
            export,coverage=self.fixture(hourly)
            result=repack_hourly_month(
                hourly_root=hourly,export_manifest=export,coverage_raw=coverage,
                month="2026-10",public_root=public,
                generated_at="2026-11-18T00:00:00Z",
                source_snapshot_sha256="a"*64)
            manifest=result["manifest"]
            self.assertEqual(manifest["partitioning"],"one-object-per-taipei-day")
            self.assertEqual(manifest["total_objects"],31)
            self.assertEqual(manifest["total_pushes"],31)
            self.assertEqual(len(manifest["days"]),31)
            self.assertTrue(all((public/item["key"]).is_file() for item in manifest["objects"]))

    def test_incomplete_day_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); export,coverage=self.fixture(root/"hourly")
            body=json.loads(coverage); body["days"][10]["coverage_status"]="UNKNOWN"
            body["days"][10]["finalized"]=False
            with self.assertRaisesRegex(MonthlyArchiveFullRebuildError,"finalized COMPLETE"):
                repack_hourly_month(
                    hourly_root=root/"hourly",export_manifest=export,
                    coverage_raw=json.dumps(body).encode(),month="2026-10",
                    public_root=root/"public",generated_at="now",
                    source_snapshot_sha256="a"*64)

    def test_formal_rows_are_preserved_and_local_only_rows_are_added(self):
        formal={"source_record_key":"aid:1","aid":"aid","source_line":1,
                "kind":"推","author":"a","content":"x","source_url":"https://example.test",
                "minute_epoch":100,"occurred_at":"2026-10-01T00:40:00Z"}
        local={**formal,"minute_epoch":99,"occurred_at":"2026-10-01T00:39:00Z"}
        added={**formal,"source_record_key":"aid:2","source_line":2,
               "minute_epoch":101,"occurred_at":"2026-10-01T00:41:00Z"}
        rows,audit=_merge_source_rows([formal],[local,added])
        by_key={row["source_record_key"]:row for row in rows}
        self.assertEqual(by_key["aid:1"]["minute_epoch"],100)
        self.assertEqual(audit["local_rows_added"],1)
        self.assertEqual(audit["minute_differences_preserved_formal"],1)

    def test_source_identity_content_conflict_is_rejected(self):
        formal={"source_record_key":"aid:1","aid":"aid","source_line":1,
                "kind":"推","author":"a","content":"x","source_url":"https://example.test",
                "minute_epoch":100}
        with self.assertRaisesRegex(MonthlyArchiveFullRebuildError,"content conflict"):
            _merge_source_rows([formal],[{**formal,"content":"different"}])


if __name__=="__main__":
    unittest.main()
