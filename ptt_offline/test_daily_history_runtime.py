from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from ptt_offline.data_lifecycle_evidence import (
    build_expected_aid_contract,
    build_source_coverage,
)
from ptt_offline.daily_history_runtime import (
    CONFIG_SCHEMA,
    DailyHistoryRuntimeError,
    load_config,
    make_repair_executor,
    run_closeout,
)


DAY="2026-10-20"
AID="1fixture"
TPE=ZoneInfo("Asia/Taipei")


def expected_contract():
    return build_expected_aid_contract(
        day=DAY,
        entries=[{
            "period":"all_day","part":1,"aid":AID,
            "source_url":"https://example.invalid/thread",
            "authority_record_id":"fixture:all_day:1",
        }],
        authority={
            "kind":"collector-discovery-receipt",
            "evidence_id":"fixture-authority",
            "observed_at":"2026-10-21T00:00:00Z",
            "verified":True,
            "version":"fixture-v1",
            "issuer":"collector-discovery",
        },
    )


def complete_coverage():
    return build_source_coverage(
        day=DAY,aid=AID,article_start_line=1,final_source_line=3,
        lines=[
            {"source_line":1,"record_type":"non_push","content_empty":None,"legal_empty_push":False},
            {"source_line":2,"record_type":"push","content_empty":False,"legal_empty_push":False},
            {"source_line":3,"record_type":"non_push","content_empty":None,"legal_empty_push":False},
        ],
    )


def source_object():
    payload={
        "schema_version":"ptt-r2-archive-v1",
        "precision":"minute",
        "bucket_start":"2026-10-20T01:00:00Z",
        "bucket_end":"2026-10-20T02:00:00Z",
        "pushes":[{
            "aid":AID,
            "coverage_day":DAY,
            "source_line":2,
            "source_record_key":f"{DAY}:{AID}:2",
            "floor":1,
            "floor_quality":"per-thread-ordinal",
            "occurred_at":"2026-10-20T01:01:00Z",
            "content":"",
        }],
    }
    return ("chunks/2026/10/20/0100.json",
            json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode())


class DailyHistoryRuntimeTests(unittest.TestCase):
    def _config(self,root: Path, *, deploy=False):
        collector=root/"collector.sqlite3"
        collector.write_bytes(b"fixture")
        expected=root/"expected.json"
        expected.write_text(json.dumps(expected_contract()),encoding="utf-8")
        state=root/"state"
        config=root/"config.json"
        config.write_text(json.dumps({
            "schema_version":CONFIG_SCHEMA,
            "collector_source":str(collector),
            "state_root":str(state),
            "expected_contract_path":str(expected),
            "static_target":"holoviewer-ptt-static-assets-pilot",
            "base_url":"https://example.invalid",
            "deploy":deploy,
            "wrangler_command":["npx","wrangler"],
        }),encoding="utf-8")
        return config,state

    def test_load_config_rejects_missing_collector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            config=root/"config.json"
            config.write_text(json.dumps({
                "schema_version":CONFIG_SCHEMA,
                "collector_source":str(root/"missing.sqlite3"),
                "state_root":str(root/"state"),
                "static_target":"holoviewer-ptt-static-assets-pilot",
                "base_url":"https://example.invalid",
            }),encoding="utf-8")
            with self.assertRaisesRegex(DailyHistoryRuntimeError,"Collector SQLite unavailable"):
                load_config(config)

    def test_tampered_expected_contract_fails_before_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path,_=self._config(Path(tmp),deploy=False)
            config=load_config(config_path)
            path=Path(config["expected_contract_path"])
            body=json.loads(path.read_text())
            body["expected"][0]["aid"]="1tampered"
            path.write_text(json.dumps(body),encoding="utf-8")
            with patch("ptt_offline.daily_history_runtime.coverage_from_collector") as coverage:
                with self.assertRaisesRegex(DailyHistoryRuntimeError,"evidence_digest mismatch"):
                    run_closeout(config=config,day=DAY)
            coverage.assert_not_called()

    def test_repair_command_is_inert_until_explicitly_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path,_=self._config(Path(tmp),deploy=False)
            body=json.loads(config_path.read_text())
            body["repair_command"]=["python3","bounded_repair_request.py"]
            config_path.write_text(json.dumps(body),encoding="utf-8")
            config=load_config(config_path)
            self.assertIsNone(make_repair_executor(config,day=DAY))
            config["repair_enabled"]=True
            self.assertTrue(callable(make_repair_executor(config,day=DAY)))

    def test_noncomplete_day_stops_before_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path,state=self._config(Path(tmp),deploy=False)
            config=load_config(config_path)
            weak=complete_coverage()
            weak["status"]="REPAIR_NEEDED"
            weak["missing_source_lines"]=[2]
            weak["contract_gaps"]=["source-line-gap"]
            with patch("ptt_offline.daily_history_runtime.coverage_from_collector",
                       return_value={AID:weak}), \
                 patch("ptt_offline.daily_history_runtime._daily_source_objects") as build:
                result=run_closeout(config=config,day=DAY)
            self.assertEqual(result["status"],"NOT_ARCHIVE_READY")
            self.assertFalse(result["archive_deployed"])
            build.assert_not_called()
            receipt=json.loads((state/"latest-finalization.json").read_text())
            self.assertEqual(receipt["state"],"REPAIR_NEEDED")

    def test_complete_day_builds_package_without_deploy(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path,state=self._config(Path(tmp),deploy=False)
            config=load_config(config_path)
            with patch("ptt_offline.daily_history_runtime.coverage_from_collector",
                       return_value={AID:complete_coverage()}), \
                 patch("ptt_offline.daily_history_runtime._daily_source_objects",
                       return_value=[source_object()]):
                result=run_closeout(config=config,day=DAY)
            self.assertEqual(result["status"],"READY_TO_DEPLOY")
            self.assertFalse(result["archive_deployed"])
            self.assertEqual(result["object_count"],1)
            self.assertTrue(Path(result["package"]).is_file())
            public=state/"static-public"
            self.assertTrue((public/"_headers").is_file())
            package=json.loads(Path(result["package"]).read_text())
            self.assertTrue((public/package["manifest"]["key"]).is_file())
            self.assertTrue((public/package["objects"][0]["key"]).is_file())

    def test_deploy_then_full_readback_writes_verified_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path,state=self._config(Path(tmp),deploy=True)
            config=load_config(config_path)

            def local_fetcher(_base_url,timeout=20):
                public=state/"static-public"
                return lambda key:(public/key).read_bytes()

            with patch("ptt_offline.daily_history_runtime.coverage_from_collector",
                       return_value={AID:complete_coverage()}), \
                 patch("ptt_offline.daily_history_runtime._daily_source_objects",
                       return_value=[source_object()]), \
                 patch("ptt_offline.daily_history_runtime._deploy_static_assets",
                       return_value={
                           "attempted_at":"2026-10-21T07:31:00+08:00",
                           "succeeded_at":"2026-10-21T07:31:05+08:00",
                           "version_id":"11111111-2222-3333-4444-555555555555",
                       }), \
                 patch("ptt_offline.daily_history_runtime._http_fetcher",
                       side_effect=local_fetcher):
                result=run_closeout(config=config,day=DAY)

            self.assertEqual(result["status"],"VERIFIED_COMPLETE_PUBLISHED")
            self.assertTrue(result["archive_deployed"])
            evidence=json.loads((state/"latest-archive-job.json").read_text())
            self.assertEqual(evidence["job_status"],"succeeded")
            self.assertTrue(evidence["job_verified"])
            self.assertEqual(evidence["coverage_summary"]["status"],"COMPLETE")
            self.assertEqual(evidence["expected_aid_completeness"]["status"],"COMPLETE")

            # Exact same source/package is a cheap no-op on the next run.
            with patch("ptt_offline.daily_history_runtime.coverage_from_collector",
                       return_value={AID:complete_coverage()}), \
                 patch("ptt_offline.daily_history_runtime._daily_source_objects",
                       return_value=[source_object()]), \
                 patch("ptt_offline.daily_history_runtime._deploy_static_assets") as deploy:
                second=run_closeout(config=config,day=DAY)
            self.assertEqual(second["status"],"ALREADY_VERIFIED")
            deploy.assert_not_called()


if __name__=="__main__":
    unittest.main()
