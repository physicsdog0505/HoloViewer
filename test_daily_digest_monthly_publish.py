import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.daily_digest_monthly_publish import PublishError, evaluate_publish


def make_input(root: Path, day: str, marker: str = ""):
    root.mkdir(parents=True, exist_ok=True)
    artifact = {
        "schema_version": 1,
        "kind": "holodocchi.daily_digest",
        "target_day": day,
        "timezone": "Asia/Taipei",
        "coverage": {"complete": True},
        "overview": {"public_summary": marker},
    }
    candidate = root / f"{day}.candidate.json"
    candidate.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
    sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    receipt = root / f"{day}.receipt.json"
    receipt.write_text(json.dumps({
        "status": "READY_FOR_PUBLICATION",
        "target_day": day,
        "public_candidate_sha256": sha,
    }), encoding="utf-8")
    return receipt, candidate, artifact


class DailyDigestMonthlyPublishTests(unittest.TestCase):
    def test_dry_run_does_not_mutate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipt, candidate, _ = make_input(root / "input", "2026-11-01")
            assets = root / "assets"
            result = evaluate_publish(receipt_path=receipt, candidate_path=candidate, asset_root=assets, execute=False)
            self.assertEqual(result["status"], "READY_TO_PUBLISH")
            self.assertFalse(Path(result["output"]).exists())

    def test_execute_writes_month_shard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipt, candidate, artifact = make_input(root / "input", "2026-11-01")
            assets = root / "assets"
            result = evaluate_publish(receipt_path=receipt, candidate_path=candidate, asset_root=assets, execute=True)
            obj = json.loads(Path(result["output"]).read_text(encoding="utf-8"))
            self.assertEqual(obj["kind"], "holodocchi.daily_digest_month")
            self.assertEqual(obj["month"], "2026-11")
            self.assertEqual(obj["days"]["2026-11-01"], artifact)

    def test_second_day_preserves_first_day(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets"
            r1, c1, a1 = make_input(root / "one", "2026-11-01", "one")
            r2, c2, a2 = make_input(root / "two", "2026-11-02", "two")
            evaluate_publish(receipt_path=r1, candidate_path=c1, asset_root=assets, execute=True)
            result = evaluate_publish(receipt_path=r2, candidate_path=c2, asset_root=assets, execute=True)
            obj = json.loads(Path(result["output"]).read_text(encoding="utf-8"))
            self.assertEqual(obj["days"]["2026-11-01"], a1)
            self.assertEqual(obj["days"]["2026-11-02"], a2)

    def test_cross_month_uses_separate_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets"
            r1, c1, _ = make_input(root / "one", "2026-11-30")
            r2, c2, _ = make_input(root / "two", "2026-12-01")
            one = evaluate_publish(receipt_path=r1, candidate_path=c1, asset_root=assets, execute=True)
            two = evaluate_publish(receipt_path=r2, candidate_path=c2, asset_root=assets, execute=True)
            self.assertNotEqual(one["output"], two["output"])
            self.assertTrue(one["output"].endswith("2026-11.json"))
            self.assertTrue(two["output"].endswith("2026-12.json"))

    def test_identical_rerun_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets"
            receipt, candidate, _ = make_input(root / "input", "2026-11-01")
            first = evaluate_publish(receipt_path=receipt, candidate_path=candidate, asset_root=assets, execute=True)
            second = evaluate_publish(receipt_path=receipt, candidate_path=candidate, asset_root=assets, execute=False)
            self.assertEqual(second["status"], "ALREADY_PUBLISHED")
            self.assertEqual(first["month_sha256"], second["month_sha256"])

    def test_rejects_candidate_sha_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipt, candidate, _ = make_input(root / "input", "2026-11-01")
            candidate.write_text('{"changed":true}', encoding="utf-8")
            with self.assertRaises(PublishError):
                evaluate_publish(receipt_path=receipt, candidate_path=candidate, asset_root=root / "assets", execute=True)

    def test_rejects_invalid_existing_month_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assets = root / "assets"
            month = assets / "data/daily-digest/months/2026-11.json"
            month.parent.mkdir(parents=True)
            month.write_text('{"kind":"wrong"}', encoding="utf-8")
            receipt, candidate, _ = make_input(root / "input", "2026-11-01")
            with self.assertRaises(PublishError):
                evaluate_publish(receipt_path=receipt, candidate_path=candidate, asset_root=assets, execute=True)


if __name__ == "__main__":
    unittest.main()
