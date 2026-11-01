import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.daily_digest_publish_candidate_v2 import PublishError, evaluate_publish


class DailyDigestPublishCandidateV2Tests(unittest.TestCase):
    def prepare(self, root: Path):
        candidate = root / "2026-10-31.public-candidate.json"
        candidate.write_bytes(b'{"schema_version":1}\n')
        sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
        receipt = root / "return.receipt.json"
        receipt.write_text(json.dumps({
            "status": "READY_FOR_PUBLICATION",
            "target_day": "2026-10-31",
            "public_candidate_sha256": sha,
        }), encoding="utf-8")
        output = root / "site" / "data" / "daily-digest" / "2026-10-31.json"
        return receipt, candidate, output

    def test_dry_run_does_not_mutate_output(self):
        with tempfile.TemporaryDirectory() as td:
            receipt, candidate, output = self.prepare(Path(td))
            result = evaluate_publish(
                receipt_path=receipt,
                candidate_path=candidate,
                output_path=output,
                execute=False,
            )
            self.assertEqual(result["status"], "READY_TO_PUBLISH")
            self.assertFalse(output.exists())

    def test_execute_publishes_exact_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            receipt, candidate, output = self.prepare(Path(td))
            result = evaluate_publish(
                receipt_path=receipt,
                candidate_path=candidate,
                output_path=output,
                execute=True,
            )
            self.assertEqual(result["status"], "PUBLISHED_LOCAL")
            self.assertEqual(output.read_bytes(), candidate.read_bytes())
            self.assertEqual(result["candidate_sha256"], result["output_sha256"])

    def test_identical_existing_output_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            receipt, candidate, output = self.prepare(Path(td))
            output.parent.mkdir(parents=True)
            output.write_bytes(candidate.read_bytes())
            result = evaluate_publish(
                receipt_path=receipt,
                candidate_path=candidate,
                output_path=output,
                execute=False,
            )
            self.assertEqual(result["status"], "ALREADY_PUBLISHED")

    def test_rejects_candidate_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            receipt, candidate, output = self.prepare(Path(td))
            candidate.write_bytes(b'{"changed":true}\n')
            with self.assertRaises(PublishError):
                evaluate_publish(
                    receipt_path=receipt,
                    candidate_path=candidate,
                    output_path=output,
                    execute=True,
                )

    def test_rejects_wrong_output_day(self):
        with tempfile.TemporaryDirectory() as td:
            receipt, candidate, _ = self.prepare(Path(td))
            with self.assertRaises(PublishError):
                evaluate_publish(
                    receipt_path=receipt,
                    candidate_path=candidate,
                    output_path=Path(td) / "2026-11-01.json",
                    execute=False,
                )


if __name__ == "__main__":
    unittest.main()
