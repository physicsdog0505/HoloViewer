from __future__ import annotations

from datetime import datetime, timezone
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
from ptt_offline.expected_aid_discovery_adapter import expected_aids_from_discovery
from ptt_offline.daily_ptt_finalization import finalize_day
from ptt_offline.daily_history_runtime import (
    CONFIG_SCHEMA,
    DailyHistoryRuntimeError,
    _build_taipei_day_source_object,
    _validate_expected_contract_digest,
    load_config,
    make_repair_executor,
    run_closeout,
    run_packaging_acceptance,
)


DAY="2026-10-20"
AID="1fixture"
TPE=ZoneInfo("Asia/Taipei")
EXPECTED_EPOCH=datetime.fromtimestamp(1792450800,tz=timezone.utc)


def expected_contract():
    return build_expected_aid_contract(
        day=DAY,
        entries=[{
            "period":"all_day","part":1,"aid":AID,
            "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792450800.A.111.html",
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


def finalized_receipt():
    return finalize_day(
        day=DAY,
        expected_contract=expected_contract(),
        coverage_by_aid={AID:complete_coverage()},
        repair_executor=None,
        observed_at="2026-10-21T07:30:00+08:00",
    )


def day_source_object():
    payload={
        "schema_version":"holoviewer-ptt-history-day-v1",
        "precision":"minute",
        "timezone":"Asia/Taipei",
        "partition_kind":"taipei-day",
        "partition_start":"2026-10-19T16:00:00Z",
        "partition_end":"2026-10-20T16:00:00Z",
        "coverage_day":DAY,
        "coverage_status":"COMPLETE",
        "finalized":True,
        "membership":{
            "rule":"taipei-day-expected-plus-direct-predecessor-v1",
            "expected_aids":[AID],
            "direct_predecessor_aid":None,
            "first_expected_thread_start":"2026-10-20T00:20:00Z",
            "cross_midnight_carry_in_pushes":0,
            "excluded_aids":[],
            "silent_drop":False,
        },
        "pushes":[{
            "aid":AID,
            "coverage_day":DAY,
            "source_line":2,
            "source_record_key":f"{DAY}:{AID}:2",
            "floor":1,
            "floor_quality":"per-thread-ordinal",
            "occurred_at":"2026-10-20T01:01:00Z",
            "day_membership":"expected-thread",
            "content":"",
        }],
    }
    return ("day.json",
            json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode())


class DailyHistoryRuntimeTests(unittest.TestCase):
    def test_hourly_export_payloads_collapse_to_one_taipei_day_object(self):
        first={
            "pushes":[{
                "aid":AID,
                "source_line":2,
                "source_record_key":f"{DAY}:{AID}:2",
                "floor":1,
                "floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-19T16:01:00Z",
                "content":"a",
            }],
        }
        second={
            "pushes":[{
                "aid":AID,
                "source_line":3,
                "source_record_key":f"{DAY}:{AID}:3",
                "floor":2,
                "floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-20T15:59:00Z",
                "content":"b",
            }],
        }
        logical,raw=_build_taipei_day_source_object(
            day=DAY,payloads=[second,first],expected_aids={AID},expected_thread_epochs={AID:EXPECTED_EPOCH})
        self.assertEqual(logical,"day.json")
        payload=json.loads(raw)
        self.assertEqual(payload["schema_version"],"holoviewer-ptt-history-day-v1")
        self.assertEqual(payload["partition_kind"],"taipei-day")
        self.assertEqual(payload["partition_start"],"2026-10-19T16:00:00Z")
        self.assertEqual(payload["partition_end"],"2026-10-20T16:00:00Z")
        self.assertEqual(len(payload["pushes"]),2)
        self.assertEqual(
            [row["source_record_key"] for row in payload["pushes"]],
            [f"{DAY}:{AID}:2",f"{DAY}:{AID}:3"])
        self.assertTrue(all(row["coverage_status"]=="COMPLETE" for row in payload["pushes"]))

    def test_daily_membership_includes_expected_day_and_night_threads(self):
        day_aid="1day"
        night_aid="1night"
        payload={"pushes":[
            {
                "aid":night_aid,"source_line":20,"source_record_key":"night:20",
                "floor":2,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-20T14:30:00Z",
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792501200.A.222.html",
                "content":"night",
            },
            {
                "aid":day_aid,"source_line":10,"source_record_key":"day:10",
                "floor":1,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-20T00:30:00Z",
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792450800.A.111.html",
                "content":"day",
            },
        ]}
        _,raw=_build_taipei_day_source_object(
            day=DAY,payloads=[payload],expected_aids={day_aid,night_aid},expected_thread_epochs={
                day_aid:datetime.fromtimestamp(1792450800,tz=timezone.utc),
                night_aid:datetime.fromtimestamp(1792501200,tz=timezone.utc),
            })
        body=json.loads(raw)
        self.assertEqual([row["aid"] for row in body["pushes"]],[day_aid,night_aid])
        self.assertTrue(all(row["day_membership"]=="expected-thread"
                            for row in body["pushes"]))
        self.assertEqual(body["membership"]["cross_midnight_carry_in_pushes"],0)

    def test_daily_membership_keeps_direct_predecessor_cross_midnight_and_excludes_adjacent(self):
        carry="1priorNight"
        older="1older"
        day_aid="1day"
        adjacent="1adjacent"
        payload={"pushes":[
            {
                "aid":older,"source_line":1,"source_record_key":"older:1",
                "floor":1,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-19T16:05:00Z",
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792400000.A.010.html",
                "content":"old predecessor",
            },
            {
                "aid":carry,"source_line":50,"source_record_key":"carry:50",
                "floor":50,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-19T17:30:00Z",
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792430000.A.020.html",
                "content":"cross midnight",
            },
            {
                "aid":day_aid,"source_line":2,"source_record_key":"day:2",
                "floor":1,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-20T00:30:00Z",
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792450800.A.111.html",
                "content":"expected day",
            },
            {
                "aid":carry,"source_line":51,"source_record_key":"carry:51",
                "floor":51,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-20T01:30:00Z",
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792430000.A.020.html",
                "content":"late but still same direct predecessor",
            },
            {
                "aid":adjacent,"source_line":3,"source_record_key":"adjacent:3",
                "floor":1,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-20T03:00:00Z",
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792461600.A.333.html",
                "content":"unrelated",
            },
        ]}
        _,raw=_build_taipei_day_source_object(
            day=DAY,payloads=[payload],expected_aids={day_aid},expected_thread_epochs={
                day_aid:datetime.fromtimestamp(1792450800,tz=timezone.utc),
            })
        body=json.loads(raw)
        self.assertEqual(
            [row["source_record_key"] for row in body["pushes"]],
            ["carry:50","day:2","carry:51"],
        )
        self.assertEqual(body["pushes"][0]["day_membership"],
                         "direct-predecessor-cross-midnight")
        self.assertEqual(body["membership"]["direct_predecessor_aid"],carry)
        self.assertEqual(body["membership"]["cross_midnight_carry_in_pushes"],2)
        excluded={row["aid"]:row["reason"] for row in body["membership"]["excluded_aids"]}
        self.assertEqual(excluded[older],"superseded-predecessor")
        self.assertEqual(excluded[adjacent],"outside-authoritative-expected-thread-set")
        self.assertFalse(body["membership"]["silent_drop"])

    def test_zero_push_earliest_expected_thread_still_anchors_predecessor_boundary(self):
        earliest="1early"
        later="1later"
        between="1between"
        predecessor="1prior"
        payload={"pushes":[
            {
                "aid":predecessor,"source_line":10,"source_record_key":"prior:10",
                "floor":10,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-19T17:00:00Z",
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792430000.A.010.html",
                "content":"legal predecessor",
            },
            {
                "aid":between,"source_line":11,"source_record_key":"between:11",
                "floor":1,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-20T00:10:00Z",
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792454400.A.020.html",
                "content":"must not become predecessor",
            },
            {
                "aid":later,"source_line":12,"source_record_key":"later:12",
                "floor":1,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-20T02:00:00Z",
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792461600.A.030.html",
                "content":"later expected",
            },
        ]}
        _,raw=_build_taipei_day_source_object(
            day=DAY,payloads=[payload],expected_aids={earliest,later},
            expected_thread_epochs={
                earliest:datetime.fromtimestamp(1792450800,tz=timezone.utc),
                later:datetime.fromtimestamp(1792461600,tz=timezone.utc),
            })
        body=json.loads(raw)
        self.assertEqual(body["membership"]["direct_predecessor_aid"],predecessor)
        self.assertEqual(
            [row["source_record_key"] for row in body["pushes"]],
            ["prior:10","later:12"],
        )
        excluded={row["aid"]:row["reason"] for row in body["membership"]["excluded_aids"]}
        self.assertEqual(
            excluded[between],"outside-authoritative-expected-thread-set")

    def test_unexpected_row_without_thread_epoch_fails_closed_not_silent_drop(self):
        payload={"pushes":[
            {
                "aid":AID,"source_line":2,"source_record_key":"expected:2",
                "floor":1,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-20T01:01:00Z",
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792450800.A.111.html",
                "content":"expected",
            },
            {
                "aid":"1unknown","source_line":9,"source_record_key":"unknown:9",
                "floor":1,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-20T01:02:00Z",
                "content":"cannot classify",
            },
        ]}
        with self.assertRaisesRegex(
                DailyHistoryRuntimeError,"without source thread epoch"):
            _build_taipei_day_source_object(
                day=DAY,payloads=[payload],expected_aids={AID},expected_thread_epochs={AID:EXPECTED_EPOCH})

    def test_cross_midnight_predecessor_sort_and_floor_are_preserved(self):
        payload={"pushes":[
            {
                "aid":AID,"source_line":2,"source_record_key":"expected:2",
                "floor":1,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-20T00:30:00Z",
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792450800.A.111.html",
                "content":"expected",
            },
            {
                "aid":"1prior","source_line":91,"source_record_key":"prior:91",
                "floor":91,"floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-19T16:20:00Z",
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792430000.A.020.html",
                "content":"carry",
            },
        ]}
        _,raw=_build_taipei_day_source_object(
            day=DAY,payloads=[payload],expected_aids={AID},expected_thread_epochs={AID:EXPECTED_EPOCH})
        body=json.loads(raw)
        self.assertEqual([row["source_record_key"] for row in body["pushes"]],
                         ["prior:91","expected:2"])
        self.assertEqual(body["pushes"][0]["floor"],91)
        self.assertEqual(body["pushes"][0]["floor_quality"],"per-thread-ordinal")

    def test_daily_object_rejects_duplicate_source_identity(self):
        payload={
            "pushes":[{
                "aid":AID,
                "source_line":2,
                "source_record_key":f"{DAY}:{AID}:2",
                "floor":1,
                "floor_quality":"per-thread-ordinal",
                "occurred_at":"2026-10-20T01:01:00Z",
                "content":"",
            }],
        }
        with self.assertRaisesRegex(DailyHistoryRuntimeError,"duplicate source_record_key"):
            _build_taipei_day_source_object(
                day=DAY,payloads=[payload,payload],expected_aids={AID},expected_thread_epochs={AID:EXPECTED_EPOCH})

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
            "lifecycle_v2_cutover_day":DAY,
            "deploy":deploy,
            "wrangler_command":["npx","wrangler"],
        }),encoding="utf-8")
        return config,state



    def test_pre_cutover_day_is_immutable_and_skips_all_runtime_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path,_=self._config(Path(tmp),deploy=False)
            body=json.loads(config_path.read_text(encoding="utf-8"))
            body["lifecycle_v2_cutover_day"]="2026-10-23"
            config_path.write_text(json.dumps(body),encoding="utf-8")
            config=load_config(config_path)

            with patch("ptt_offline.daily_history_runtime.load_expected_contract") as expected, \
                 patch("ptt_offline.daily_history_runtime.coverage_from_collector") as coverage, \
                 patch("ptt_offline.daily_history_runtime._daily_source_objects") as build, \
                 patch("ptt_offline.daily_history_runtime._deploy_static_assets") as deploy:
                result=run_closeout(config=config,day="2026-10-22")

            self.assertEqual(result["status"],"PRE_CUTOVER_IMMUTABLE")
            self.assertEqual(result["day"],"2026-10-22")
            self.assertEqual(result["cutover_day"],"2026-10-23")
            self.assertFalse(result["archive_deployed"])
            expected.assert_not_called()
            coverage.assert_not_called()
            build.assert_not_called()
            deploy.assert_not_called()

    def test_cutover_day_is_allowed_to_enter_pure_v2_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path,_=self._config(Path(tmp),deploy=False)
            body=json.loads(config_path.read_text(encoding="utf-8"))
            body["lifecycle_v2_cutover_day"]="2026-10-23"
            config_path.write_text(json.dumps(body),encoding="utf-8")
            config=load_config(config_path)

            with patch("ptt_offline.daily_history_runtime.load_expected_contract",
                       side_effect=DailyHistoryRuntimeError("cutover-entered")):
                with self.assertRaisesRegex(DailyHistoryRuntimeError,"cutover-entered"):
                    run_closeout(config=config,day="2026-10-23")

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

    def test_expected_contract_accepts_external_authority_evidence_hash(self):
        contract=build_expected_aid_contract(
            day=DAY,
            entries=[{
                "period":"all_day","part":1,"aid":AID,
                "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792450800.A.111.html",
                "authority_record_id":"fixture:external-authority",
            }],
            authority={
                "kind":"ptt-public-index-discovery",
                "evidence_id":"fixture-external-authority",
                "observed_at":"2026-10-21T00:00:00Z",
                "verified":True,
                "version":"thread-discovery-v1",
                "issuer":"fixture",
                "evidence_hash":"f"*64,
            },
        )
        self.assertEqual(contract["authority"]["evidence_hash"],"f"*64)
        self.assertNotEqual(
            contract["authority"]["evidence_hash"],contract["evidence_digest"])
        _validate_expected_contract_digest(contract)

        tampered=json.loads(json.dumps(contract))
        tampered["authority"]["evidence_hash"]="e"*64
        with self.assertRaisesRegex(
                DailyHistoryRuntimeError,"evidence_digest mismatch"):
            _validate_expected_contract_digest(tampered)

    def test_discovery_adapter_contract_validates_builder_digest_scope(self):
        contract=expected_aids_from_discovery(
            day=DAY,
            targets=[{
                "aid":AID,
                "url":"https://www.ptt.cc/bbs/C_Chat/M.1792450800.A.111.html",
                "period":"本日",
                "timestamp":1792450800,
            }],
            authority={
                "kind":"ptt-public-index-discovery",
                "evidence_id":"fixture-discovery",
                "observed_at":"2026-10-21T00:00:00Z",
                "verified":True,
                "version":"thread-discovery-v1",
                "issuer":"fixture",
                "evidence_hash":"f"*64,
            },
        )
        self.assertEqual(contract["source_kind"],"sanitized-collector-discovery")
        self.assertEqual(contract["discovery_target_count"],1)
        _validate_expected_contract_digest(contract)

        tampered=json.loads(json.dumps(contract))
        tampered["expected"][0]["aid"]="1tampered"
        with self.assertRaisesRegex(
                DailyHistoryRuntimeError,"evidence_digest mismatch"):
            _validate_expected_contract_digest(tampered)

        bad_count=json.loads(json.dumps(contract))
        bad_count["discovery_target_count"]=2
        with self.assertRaisesRegex(
                DailyHistoryRuntimeError,"discovery target count mismatch"):
            _validate_expected_contract_digest(bad_count)

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

    def test_packaging_acceptance_consumes_fresh_receipt_without_recomputing_completeness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            config_path,state=self._config(root,deploy=False)
            config=load_config(config_path)
            finalization_path=root/"fresh-finalization.json"
            expected_path=root/"fresh-expected.json"
            finalization=finalized_receipt()
            finalization_path.write_text(json.dumps(finalization),encoding="utf-8")
            expected_path.write_text(json.dumps(expected_contract()),encoding="utf-8")

            with patch("ptt_offline.daily_history_runtime.coverage_from_collector") as coverage, \
                 patch("ptt_offline.daily_history_runtime.finalize_day") as finalize, \
                 patch("ptt_offline.daily_history_runtime.make_repair_executor") as repair, \
                 patch("ptt_offline.daily_history_runtime._daily_source_objects",
                       return_value=[day_source_object()]):
                result=run_packaging_acceptance(
                    config=config,
                    day=DAY,
                    finalization_path=finalization_path,
                    expected_contract_path=expected_path,
                )

            coverage.assert_not_called()
            finalize.assert_not_called()
            repair.assert_not_called()
            self.assertEqual(result["status"],"READY_TO_DEPLOY")
            self.assertEqual(result["finalization_digest"],finalization["evidence_digest"])
            self.assertEqual(result["expected_aids"],[AID])
            self.assertEqual(result["packaged_aids"],[AID])
            self.assertEqual(result["unexpected_aids"],[])
            self.assertEqual(result["package_validation"],"PASS")
            self.assertFalse(result["repair_enabled"])
            self.assertFalse(result["deploy"])
            self.assertFalse(result["archive_deployed"])
            self.assertTrue(Path(result["day_json"]).is_file())
            self.assertTrue(Path(result["package"]).is_file())

    def test_packaging_acceptance_refuses_mutation_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            config_path,_=self._config(root,deploy=True)
            config=load_config(config_path)
            finalization_path=root/"fresh-finalization.json"
            expected_path=root/"fresh-expected.json"
            finalization_path.write_text(json.dumps(finalized_receipt()),encoding="utf-8")
            expected_path.write_text(json.dumps(expected_contract()),encoding="utf-8")
            with self.assertRaisesRegex(
                    DailyHistoryRuntimeError,"requires deploy=false"):
                run_packaging_acceptance(
                    config=config,day=DAY,
                    finalization_path=finalization_path,
                    expected_contract_path=expected_path,
                )

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

    def test_reobserved_expected_authority_reuses_verified_finalization_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path,state=self._config(Path(tmp),deploy=False)
            config=load_config(config_path)

            with patch("ptt_offline.daily_history_runtime.coverage_from_collector",
                       return_value={AID:complete_coverage()}), \
                 patch("ptt_offline.daily_history_runtime._daily_source_objects",
                       return_value=[source_object()]):
                first=run_closeout(config=config,day=DAY)

            self.assertEqual(first["status"],"READY_TO_DEPLOY")
            first_package=json.loads(Path(first["package"]).read_text())
            first_receipt=json.loads((state/"finalization"/f"{DAY}.json").read_text())

            # Re-observe the exact same authoritative day/AID set later. The
            # expected-AID contract gets a new observed_at/evidence digest, but
            # this must not create another immutable historical revision.
            path=Path(config["expected_contract_path"])
            later=expected_contract()
            later["authority"]["observed_at"]="2026-10-21T01:00:00Z"
            from ptt_offline.data_lifecycle_evidence import build_expected_aid_contract
            later=build_expected_aid_contract(
                day=DAY,
                entries=[{
                    "period":"all_day","part":1,"aid":AID,
                    "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792450800.A.111.html",
                    "authority_record_id":"fixture:all_day:1",
                }],
                authority={
                    "kind":"collector-discovery-receipt",
                    "evidence_id":"fixture-authority",
                    "observed_at":"2026-10-21T01:00:00Z",
                    "verified":True,
                    "version":"fixture-v1",
                    "issuer":"collector-discovery",
                },
            )
            path.write_text(json.dumps(later),encoding="utf-8")

            with patch("ptt_offline.daily_history_runtime.coverage_from_collector",
                       return_value={AID:complete_coverage()}), \
                 patch("ptt_offline.daily_history_runtime._daily_source_objects",
                       return_value=[source_object()]):
                second=run_closeout(config=config,day=DAY)

            self.assertEqual(second["status"],"READY_TO_DEPLOY")
            second_package=json.loads(Path(second["package"]).read_text())
            second_receipt=json.loads((state/"finalization"/f"{DAY}.json").read_text())
            self.assertEqual(first_package["manifest"]["digest"],
                             second_package["manifest"]["digest"])
            self.assertEqual(first_package["source_hash"],second_package["source_hash"])
            self.assertEqual(first_receipt["evidence_digest"],
                             second_receipt["evidence_digest"])

    def test_succeeded_unverified_prior_recovers_readback_without_redeploy(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path,state=self._config(Path(tmp),deploy=True)
            config=load_config(config_path)
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
                       return_value=lambda _key:b"not-yet-propagated"):
                with self.assertRaises(DailyHistoryRuntimeError):
                    run_closeout(config=config,day=DAY)

            prior=json.loads((state/"latest-archive-job.json").read_text())
            package=json.loads((state/"archive"/DAY/"package.json").read_text())
            self.assertEqual(prior["manifest"]["digest"],package["manifest"]["digest"])
            (state/"archive"/DAY/"archive-job.json").write_text(json.dumps(prior))
            (state/"latest-archive-job.json").write_text(json.dumps(prior))

            public=state/"static-public"
            def local_fetcher(_base_url,timeout=20):
                return lambda key:(public/key).read_bytes()

            with patch("ptt_offline.daily_history_runtime.coverage_from_collector",
                       return_value={AID:complete_coverage()}), \
                 patch("ptt_offline.daily_history_runtime._daily_source_objects",
                       return_value=[source_object()]), \
                 patch("ptt_offline.daily_history_runtime._http_fetcher",
                       side_effect=local_fetcher), \
                 patch("ptt_offline.daily_history_runtime._deploy_static_assets") as deploy:
                result=run_closeout(config=config,day=DAY)

            self.assertEqual(result["status"],"VERIFIED_COMPLETE_PUBLISHED")
            self.assertTrue(result["readback_recovered"])
            self.assertFalse(result["archive_deployed"])
            deploy.assert_not_called()
            evidence=json.loads((state/"latest-archive-job.json").read_text())
            self.assertTrue(evidence["job_verified"])
            self.assertEqual(evidence["attempt_count"],1)

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
