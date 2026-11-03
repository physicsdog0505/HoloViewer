import copy
import io
import json
import os
import tempfile
from unittest.mock import patch
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.daily_digest_related_clips_runtime import (
    ARCHIVE_KIND,
    INDEX_KIND,
    RuntimeError334,
    build_due_jobs,
    build_month_archive,
    build_storage_index,
    digest_unchanged,
    discover_accepted_receipts,
    build_job_command_plan,
    execute_job,
    canonical_json_bytes,
    empty_state,
    month_compaction_eligible,
    pending_backfill_days,
    reconcile_publication,
    record_success,
    resolve_storage,
    atomic_write_json,
    load_json_or,
    main,
)


class DailyDigestRelatedClipsRuntimeTests(unittest.TestCase):
    def test_due_schedule_and_priority(self):
        state = empty_state()
        jobs = build_due_jobs(
            state,
            accepted_days={
                "2026-11-08": "sha8",
                "2026-11-07": "sha7",
                "2026-11-05": "sha5",
                "2026-11-01": "sha1",
            },
            today="2026-11-08",
        )
        self.assertEqual(
            [(row["priority"], row["stage"], row["target_day"]) for row in jobs],
            [
                (0, "initial", "2026-11-01"),
                (0, "initial", "2026-11-05"),
                (0, "initial", "2026-11-07"),
                (0, "initial", "2026-11-08"),
            ],
        )

        for day in ("2026-11-01", "2026-11-05", "2026-11-07"):
            record_success(
                state,
                target_day=day,
                stage="initial",
                succeeded_at="2026-11-08T00:00:00Z",
                clip_count=1,
                generated_sha256="a",
                live_sha256="a",
            )
        jobs = build_due_jobs(
            state,
            accepted_days={
                "2026-11-07": "sha7",
                "2026-11-05": "sha5",
                "2026-11-01": "sha1",
            },
            today="2026-11-08",
        )
        self.assertEqual(
            [(row["priority"], row["stage"], row["target_day"]) for row in jobs],
            [
                (1, "t1", "2026-11-01"),
                (1, "t1", "2026-11-05"),
                (1, "t1", "2026-11-07"),
            ],
        )

    def test_catchup_is_idempotent_and_advances_one_stage(self):
        state = empty_state()
        record_success(
            state,
            target_day="2026-11-01",
            stage="initial",
            succeeded_at="2026-11-01T00:00:00Z",
            clip_count=2,
            generated_sha256="a",
            live_sha256="a",
        )
        jobs = build_due_jobs(
            state,
            accepted_days={"2026-11-01": "sha1"},
            today="2026-11-08",
        )
        self.assertEqual(jobs[0]["stage"], "t1")
        record_success(
            state,
            target_day="2026-11-01",
            stage="t1",
            succeeded_at="2026-11-08T00:00:00Z",
            clip_count=3,
            generated_sha256="b",
            live_sha256="b",
        )
        jobs = build_due_jobs(
            state,
            accepted_days={"2026-11-01": "sha1"},
            today="2026-11-08",
        )
        self.assertEqual(jobs[0]["stage"], "t3")

    def test_terminal_backfill_day_does_not_reenter_refresh_queue(self):
        state = empty_state()
        record_success(
            state,
            target_day="2026-10-01",
            stage="backfill",
            succeeded_at="2026-11-03T00:00:00Z",
            clip_count=5,
            generated_sha256="same",
            live_sha256="same",
        )
        state["days"]["2026-10-01"]["digest_sha256"] = "digest"
        jobs = build_due_jobs(
            state,
            accepted_days={"2026-10-01": "digest"},
            today="2026-11-08",
        )
        self.assertEqual(jobs, [])

    def test_same_day_is_not_scheduled_for_refresh_and_backfill(self):
        state = empty_state()
        jobs = build_due_jobs(
            state,
            accepted_days={"2026-10-01": "digest"},
            today="2026-11-08",
            backfill_queue=["2026-10-01", "2026-10-02"],
            backfill_limit=5,
        )
        self.assertEqual(
            [(row["stage"], row["target_day"]) for row in jobs],
            [
                ("initial", "2026-10-01"),
                ("backfill", "2026-10-02"),
            ],
        )

    def test_t7_completion_removes_day_from_active_queue(self):
        state = empty_state()
        for stage in ("initial", "t1", "t3", "t7"):
            record_success(
                state,
                target_day="2026-11-01",
                stage=stage,
                succeeded_at="2026-11-08T00:00:00Z",
                clip_count=10,
                generated_sha256=stage,
                live_sha256=stage,
            )
        jobs = build_due_jobs(
            state,
            accepted_days={"2026-11-01": "sha1"},
            today="2026-11-09",
        )
        self.assertEqual(jobs, [])
        self.assertTrue(state["days"]["2026-11-01"]["terminal"])

    def test_changed_digest_identity_invalidates_refresh_completion(self):
        state = empty_state()
        record_success(
            state,
            target_day="2026-11-01",
            stage="initial",
            succeeded_at="2026-11-01T00:00:00Z",
            clip_count=1,
            generated_sha256="a",
            live_sha256="a",
        )
        state["days"]["2026-11-01"]["digest_sha256"] = "old"
        jobs = build_due_jobs(
            state,
            accepted_days={"2026-11-01": "new"},
            today="2026-11-08",
        )
        self.assertEqual(jobs[0]["stage"], "initial")
        self.assertFalse(state["days"]["2026-11-01"]["terminal"])

    def test_publication_requires_matching_live_readback(self):
        state = empty_state()
        with self.assertRaises(RuntimeError334):
            record_success(
                state,
                target_day="2026-11-01",
                stage="initial",
                succeeded_at="2026-11-01T00:00:00Z",
                clip_count=1,
                generated_sha256="candidate",
                live_sha256="different",
            )
        self.assertNotIn("2026-11-01", state["days"])

    def test_interruption_reconciliation_marks_success(self):
        state = empty_state()
        reconciled = reconcile_publication(
            state,
            target_day="2026-11-01",
            stage="t3",
            generated_sha256="same",
            live_sha256="same",
            clip_count=12,
            reconciled_at="2026-11-04T00:00:00Z",
        )
        self.assertTrue(reconciled)
        self.assertEqual(state["days"]["2026-11-01"]["stages"]["t3"], "complete")

    def test_failed_reconciliation_does_not_complete(self):
        state = empty_state()
        reconciled = reconcile_publication(
            state,
            target_day="2026-11-01",
            stage="t3",
            generated_sha256="candidate",
            live_sha256="other",
            clip_count=12,
            reconciled_at="2026-11-04T00:00:00Z",
        )
        self.assertFalse(reconciled)
        self.assertNotIn("2026-11-01", state["days"])

    def test_bounded_backfill_skips_completed(self):
        state = empty_state()
        record_success(
            state,
            target_day="2026-10-01",
            stage="backfill",
            succeeded_at="2026-11-03T00:00:00Z",
            clip_count=1,
            generated_sha256="x",
            live_sha256="x",
        )
        queue = {
            "schema_version": 1,
            "kind": "holodocchi.daily_digest.related_clips.backfill_queue",
            "days": [
                "2026-10-01",
                "2026-10-02",
                "2026-10-03",
                "2026-10-04",
            ],
        }
        self.assertEqual(
            pending_backfill_days(queue, state, limit=2),
            ["2026-10-02", "2026-10-03"],
        )

    def test_backfill_jobs_are_p4_and_bounded(self):
        state = empty_state()
        jobs = build_due_jobs(
            state,
            accepted_days={},
            today="2026-11-03",
            backfill_queue=[
                "2026-10-01",
                "2026-10-02",
                "2026-10-03",
            ],
            backfill_limit=2,
        )
        self.assertEqual(
            [(row["priority"], row["stage"], row["target_day"]) for row in jobs],
            [
                (4, "backfill", "2026-10-01"),
                (4, "backfill", "2026-10-02"),
            ],
        )

    def test_digest_immutability_helper(self):
        before = b'{"target_day":"2026-11-01"}\n'
        self.assertTrue(digest_unchanged(before, bytes(before)))
        self.assertFalse(digest_unchanged(before, before + b" "))

    def sidecar(self, target_day):
        return {
            "schema_version": 1,
            "kind": "holodocchi.daily_digest.related_clips",
            "target_day": target_day,
            "status": "ok",
            "stories": [],
            "sources": {},
        }

    def test_month_compaction_eligibility(self):
        state = empty_state()
        for day in ("2026-10-01", "2026-10-02"):
            record_success(
                state,
                target_day=day,
                stage="backfill",
                succeeded_at="2026-11-03T00:00:00Z",
                clip_count=1,
                generated_sha256=day,
                live_sha256=day,
            )
        self.assertTrue(
            month_compaction_eligible(
                state,
                month="2026-10",
                expected_days=["2026-10-01", "2026-10-02"],
            )
        )
        self.assertFalse(
            month_compaction_eligible(
                state,
                month="2026-10",
                expected_days=["2026-10-01", "2026-10-03"],
            )
        )

    def test_month_archive_is_deterministic_and_preserves_days(self):
        rows_a = {
            "2026-10-02": self.sidecar("2026-10-02"),
            "2026-10-01": self.sidecar("2026-10-01"),
        }
        rows_b = dict(reversed(list(rows_a.items())))
        archive_a = build_month_archive(month="2026-10", sidecars_by_day=rows_a)
        archive_b = build_month_archive(month="2026-10", sidecars_by_day=rows_b)
        self.assertEqual(archive_a, archive_b)
        self.assertEqual(archive_a["kind"], ARCHIVE_KIND)
        self.assertEqual(list(archive_a["days"]), ["2026-10-01", "2026-10-02"])

    def test_storage_index_prefers_hot_then_cold(self):
        index = build_storage_index(
            hot_days=["2026-11-01"],
            cold_months=["2026-10"],
        )
        self.assertEqual(index["kind"], INDEX_KIND)
        self.assertEqual(
            resolve_storage(index, "2026-11-01")["tier"],
            "hot",
        )
        self.assertEqual(
            resolve_storage(index, "2026-10-03")["tier"],
            "cold",
        )
        self.assertEqual(
            resolve_storage(index, "2026-09-30")["tier"],
            "missing",
        )

    def test_discovers_only_validated_accepted_receipts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            revision = root / "revision"
            revision.mkdir()
            candidate = revision / "2026-11-02.public-candidate.json"
            candidate.write_bytes(b'{"target_day":"2026-11-02"}\n')
            import hashlib
            candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
            (root / "2026-11-02.finalized.json").write_text(
                json.dumps({
                    "status": "validated_accepted",
                    "target_day": "2026-11-02",
                    "public_candidate_sha256": candidate_sha,
                    "revision_dir": str(revision),
                }),
                encoding="utf-8",
            )
            (root / "2026-11-01.finalized.json").write_text(
                json.dumps({
                    "status": "return_readback_complete",
                    "target_day": "2026-11-01",
                }),
                encoding="utf-8",
            )
            accepted, candidates = discover_accepted_receipts(root)
        self.assertEqual(accepted, {"2026-11-02": candidate_sha})
        self.assertEqual(candidates["2026-11-02"], str(candidate))

    def test_command_plan_reuses_private_exporter_and_public_resolver(self):
        job = {
            "target_day": "2026-11-02",
            "stage": "t1",
            "priority": 1,
        }
        plan = build_job_command_plan(
            job,
            candidate_path="/tmp/revision/2026-11-02.public-candidate.json",
            private_repo=Path("/private/repo"),
            corpus_root=Path("/private/corpus"),
            sidecar_root=Path("/public/daily-digest-static/data/daily-digest"),
            python_executable="/usr/bin/python3",
        )
        self.assertEqual(plan["stage"], "t1")
        self.assertIn(
            "/private/repo/scripts/export_daily_digest_source_languages.py",
            plan["commands"][0],
        )
        self.assertIn(
            "--corpus-root",
            plan["commands"][0],
        )
        self.assertTrue(
            plan["commands"][1][1].endswith(
                "scripts/daily_digest_related_clips.py"
            )
        )
        self.assertEqual(
            plan["sidecar"],
            "/public/daily-digest-static/data/daily-digest/2026-11/2026-11-02-related-clips.json",
        )
        self.assertEqual(
            plan["source_language_map"],
            str(
                Path.home()
                / ".holoviewer"
                / "daily-digest-related-clips"
                / "work"
                / "2026-11-02"
                / "2026-11-02.source-languages.json"
            ),
        )
        self.assertNotIn(
            "/public/daily-digest-static",
            plan["source_language_map"],
        )
        self.assertEqual(plan["provider_execution"], "NOT_EXECUTED_BY_PLAN")
        self.assertEqual(plan["static_deploy"], "NOT_EXECUTED_BY_PLAN")

    def test_execute_job_runs_export_resolve_publish_and_reconciles(self):
        state = empty_state()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = root / "2026-11-02.public-candidate.json"
            candidate_bytes = canonical_json_bytes({
                "schema_version": 1,
                "kind": "holodocchi.daily_digest",
                "target_day": "2026-11-02",
                "stories": [],
            })
            candidate.write_bytes(candidate_bytes)

            sidecar_root = root / "daily-digest-static" / "data" / "daily-digest"
            sidecar_path = (
                sidecar_root / "2026-11" / "2026-11-02-related-clips.json"
            )

            class Result:
                def __init__(self, code=0, stdout="", stderr=""):
                    self.returncode = code
                    self.stdout = stdout
                    self.stderr = stderr

            calls = []

            def runner(command, **kwargs):
                calls.append(command)
                if command[1].endswith("daily_digest_related_clips.py"):
                    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
                    sidecar_path.write_bytes(canonical_json_bytes({
                        "schema_version": 1,
                        "kind": "holodocchi.daily_digest.related_clips",
                        "target_day": "2026-11-02",
                        "status": "ok",
                        "stories": [{"clips": [{"video_id": "AAAAAAAAAAA"}]}],
                        "sources": {},
                    }))
                if len(command) >= 2 and command[1] == "prepare":
                    return Result(stdout="BASELINE_VERSION=version-1\n")
                return Result(stdout="PASS\n")

            live_bytes = canonical_json_bytes({
                "schema_version": 1,
                "kind": "holodocchi.daily_digest.related_clips",
                "target_day": "2026-11-02",
                "status": "ok",
                "stories": [{"clips": [{"video_id": "AAAAAAAAAAA"}]}],
                "sources": {},
            })

            job = {
                "target_day": "2026-11-02",
                "stage": "initial",
                "priority": 0,
                "digest_sha256": __import__("hashlib").sha256(
                    candidate_bytes
                ).hexdigest(),
            }
            with patch.dict(os.environ, {"HOLODEX_API_KEY": "test-key"}):
                result = execute_job(
                    state,
                    job=job,
                    candidate_path=str(candidate),
                    private_repo=root / "private",
                    corpus_root=root / "corpus",
                    sidecar_root=sidecar_root,
                    public_repo=root / "public",
                    public_expected_head="a" * 40,
                    python_executable="/usr/bin/python3",
                    execute=True,
                    runner=runner,
                    readback_fetcher=lambda path: live_bytes,
                    succeeded_at="2026-11-03T00:00:00Z",
                )

        self.assertEqual(result["production_mutation"], "YES")
        self.assertEqual(result["clip_count"], 1)
        self.assertEqual(result["static_baseline_version"], "version-1")
        self.assertEqual(
            state["days"]["2026-11-02"]["stages"]["initial"],
            "complete",
        )
        self.assertTrue(any(command[1] == "prepare" for command in calls))
        self.assertTrue(any(command[1] == "deploy" for command in calls))

    def test_execute_job_refuses_without_holodex_key(self):
        state = empty_state()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = root / "2026-11-02.public-candidate.json"
            payload = canonical_json_bytes({
                "target_day": "2026-11-02",
                "stories": [],
            })
            candidate.write_bytes(payload)
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(RuntimeError334):
                    execute_job(
                        state,
                        job={
                            "target_day": "2026-11-02",
                            "stage": "initial",
                            "digest_sha256": __import__("hashlib").sha256(
                                payload
                            ).hexdigest(),
                        },
                        candidate_path=str(candidate),
                        private_repo=root / "private",
                        corpus_root=root / "corpus",
                        sidecar_root=root / "sidecars",
                        public_repo=root / "public",
                        public_expected_head="a" * 40,
                        python_executable="/usr/bin/python3",
                        execute=True,
                        runner=lambda *args, **kwargs: None,
                        readback_fetcher=lambda path: b"",
                    )
        self.assertNotIn("2026-11-02", state["days"])

    def test_missing_local_candidate_is_not_execution_ready(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            revision = root / "missing-revision"
            (root / "2026-11-02.finalized.json").write_text(
                json.dumps({
                    "status": "validated_accepted",
                    "target_day": "2026-11-02",
                    "public_candidate_sha256": "a" * 64,
                    "revision_dir": str(revision),
                }),
                encoding="utf-8",
            )
            accepted, candidates = discover_accepted_receipts(root)
        self.assertEqual(accepted, {"2026-11-02": "a" * 64})
        self.assertEqual(candidates, {})

    def test_state_persists_and_resumes(self):
        state = empty_state()
        record_success(
            state,
            target_day="2026-11-01",
            stage="initial",
            succeeded_at="2026-11-01T00:00:00Z",
            clip_count=2,
            generated_sha256="a",
            live_sha256="a",
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            atomic_write_json(path, state)
            loaded = load_json_or(path, empty_state())
            jobs = build_due_jobs(
                loaded,
                accepted_days={"2026-11-01": "digest-sha"},
                today="2026-11-02",
            )
        self.assertEqual(jobs[0]["stage"], "t1")

    def test_cli_dry_run_never_calls_provider_or_deploy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            accepted = root / "accepted.json"
            accepted.write_text(
                json.dumps({"2026-11-03": "digest-sha"}),
                encoding="utf-8",
            )
            state = root / "state.json"
            output = io.StringIO()
            with redirect_stdout(output):
                code = main([
                    "--state", str(state),
                    "--accepted-days", str(accepted),
                    "--today", "2026-11-03",
                ])
        self.assertEqual(code, 0)
        text = output.getvalue()
        self.assertIn("MODE=DRY_RUN_PLAN", text)
        self.assertIn("DUE_JOBS=1", text)
        self.assertIn("JOB_1=0:initial:2026-11-03", text)
        self.assertIn("PROVIDER_CALLS=0", text)
        self.assertIn("STATIC_DEPLOY=NO", text)
        self.assertIn("FRONTEND_DEPLOY=NO", text)
        self.assertIn("GEMINI_EXECUTION=NO", text)

    def test_input_state_not_mutated_by_archive_builder(self):
        sidecars = {"2026-10-01": self.sidecar("2026-10-01")}
        before = copy.deepcopy(sidecars)
        build_month_archive(month="2026-10", sidecars_by_day=sidecars)
        self.assertEqual(sidecars, before)


if __name__ == "__main__":
    unittest.main()
