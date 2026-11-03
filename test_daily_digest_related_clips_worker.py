import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.daily_digest_related_clips_runtime import canonical_json_bytes
from scripts.daily_digest_related_clips_worker import run_cycle


class DailyDigestRelatedClipsWorkerTests(unittest.TestCase):
    def make_fixture(self, root: Path):
        receipts = root / "receipts"
        revision = root / "revision"
        receipts.mkdir()
        revision.mkdir()
        candidate = revision / "2026-11-01.public-candidate.json"
        candidate_bytes = canonical_json_bytes({
            "schema_version": 1,
            "kind": "holodocchi.daily_digest",
            "target_day": "2026-11-01",
            "stories": [],
        })
        candidate.write_bytes(candidate_bytes)
        candidate_sha = hashlib.sha256(candidate_bytes).hexdigest()
        (receipts / "2026-11-01.finalized.json").write_text(
            json.dumps({
                "status": "validated_accepted",
                "target_day": "2026-11-01",
                "public_candidate_sha256": candidate_sha,
                "revision_dir": str(revision),
            }),
            encoding="utf-8",
        )
        return receipts, candidate_sha

    def test_dry_run_cycle_plans_without_provider_or_static(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipts, _ = self.make_fixture(root)
            result = run_cycle(
                state_path=root / "state.json",
                accepted_receipts_dir=receipts,
                backfill_queue_path=None,
                private_repo=root / "private",
                corpus_root=root / "corpus",
                sidecar_root=root / "sidecars",
                public_repo=root / "public",
                public_expected_head="a" * 40,
                python_executable="/usr/bin/python3",
                today="2026-11-01",
                backfill_limit=5,
                execute=False,
            )
            state = json.loads((root / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(result["mode"], "DRY_RUN")
        self.assertEqual(result["due_jobs"], 1)
        self.assertEqual(result["results"][0]["status"], "planned")
        self.assertFalse(result["provider_calls_allowed"])
        self.assertFalse(result["static_deploy_allowed"])
        self.assertFalse(result["frontend_deploy"])
        self.assertFalse(result["gemini_execution"])
        self.assertEqual(
            state["days"]["2026-11-01"]["stages"]["initial"],
            "pending",
        )

    def test_missing_candidate_is_skipped_and_durable_error_written(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipts = root / "receipts"
            receipts.mkdir()
            (receipts / "2026-11-01.finalized.json").write_text(
                json.dumps({
                    "status": "validated_accepted",
                    "target_day": "2026-11-01",
                    "public_candidate_sha256": "a" * 64,
                    "revision_dir": str(root / "missing"),
                }),
                encoding="utf-8",
            )
            result = run_cycle(
                state_path=root / "state.json",
                accepted_receipts_dir=receipts,
                backfill_queue_path=None,
                private_repo=root / "private",
                corpus_root=root / "corpus",
                sidecar_root=root / "sidecars",
                public_repo=root / "public",
                public_expected_head="a" * 40,
                python_executable="/usr/bin/python3",
                today="2026-11-01",
                backfill_limit=5,
                execute=False,
            )
            state = json.loads((root / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(result["results"][0]["status"], "skipped")
        self.assertEqual(len(state["days"]["2026-11-01"]["errors"]), 1)

    def test_execute_failure_is_nonblocking_and_durable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipts, _ = self.make_fixture(root)
            with patch.dict(os.environ, {"HOLODEX_API_KEY": "test-key"}):
                result = run_cycle(
                    state_path=root / "state.json",
                    accepted_receipts_dir=receipts,
                    backfill_queue_path=None,
                    private_repo=root / "private",
                    corpus_root=root / "corpus",
                    sidecar_root=root / "sidecars",
                    public_repo=root / "public",
                    public_expected_head="a" * 40,
                    python_executable="/usr/bin/python3",
                    today="2026-11-01",
                    backfill_limit=5,
                    execute=True,
                    readback_fetcher=lambda path: b"",
                )
            state = json.loads((root / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(result["results"][0]["status"], "error")
        self.assertEqual(
            state["days"]["2026-11-01"]["stages"]["initial"],
            "pending",
        )
        self.assertTrue(state["days"]["2026-11-01"]["errors"])


if __name__ == "__main__":
    unittest.main()
