from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from vod_subtitle_publisher import (
    GLOBAL_INDEX_PATH,
    MONTH_INDEX_DIR,
    VodSubtitlePublishError,
    build_candidate,
    stage_receipt,
    validate_candidate,
)


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class VodSubtitlePublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assets = self.root / "staged"
        self.receipts = self.root / "private-receipts"
        self.catalog = self.root / "catalog"
        self.candidate = self.root / "candidate"
        self._write_catalog({
            "2024-06": ["VzgiaEu59Uk", "AAAAAAAAAAA"],
            "2026-10": ["5cDfZaII0_0", "BBBBBBBBBBB"],
            "2026-09": ["CCCCCCCCCCC"],
        })

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _asset(self, video_id: str, marker: str = "a") -> bytes:
        source_hash = hashlib.sha256(("source-" + marker).encode()).hexdigest()
        artifact_id = hashlib.sha256(("artifact-" + marker).encode()).hexdigest()
        payload = {
            "schema_version": "holodocchi-vod-subtitle-v1",
            "video_id": video_id,
            "source_transcript_id": "transcript-" + marker,
            "source_content_hash": source_hash,
            "translation_artifact_id": artifact_id,
            "translation_identity": {"fixture": marker},
            "segment_count": 2,
            "cues": [
                {"id": 0, "start_ms": 0, "end_ms": 1000, "zh_tw": "第一段" + marker},
                {"id": 1, "start_ms": 1200, "end_ms": 2400, "zh_tw": "第二段" + marker},
            ],
        }
        raw = canonical(payload)
        path = self.assets / f"data/subtitles/videos/{video_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return raw

    def _stage(self, video_id: str, marker: str = "a", staged_at: str = "2026-10-31T01:00:00Z") -> None:
        self._asset(video_id, marker)
        stage_receipt(self.assets, self.receipts, video_id, staged_at)

    def _write_catalog(self, months: dict[str, list[str]]) -> None:
        month_entries = []
        for month, videos in sorted(months.items()):
            path = f"/youtube/v1/months/{month}.json"
            month_entries.append({"month": month, "path": path})
            target = self.catalog / path.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(canonical({
                "schema_version": 1,
                "month": month,
                "videos": [{"video_id": video_id, "title": "catalog metadata"} for video_id in videos],
            }))
        manifest = self.catalog / "youtube/v1/manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_bytes(canonical({"schema_version": 1, "months": month_entries}))

    def test_new_subtitle_automatically_updates_global_and_vod_month_indexes(self):
        self._stage("VzgiaEu59Uk", "first")
        result = build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        self.assertTrue(result["changed"])
        global_index = json.loads((self.candidate / GLOBAL_INDEX_PATH).read_text())
        month_index = json.loads((self.candidate / MONTH_INDEX_DIR / "2024-06.json").read_text())
        self.assertEqual([row["video_id"] for row in global_index["videos"]], ["VzgiaEu59Uk"])
        self.assertEqual([row["video_id"] for row in month_index["videos"]], ["VzgiaEu59Uk"])
        self.assertNotIn("title", global_index["videos"][0])


    def test_overlapping_ordered_cues_are_accepted(self):
        raw = self._asset("VzgiaEu59Uk", "overlap")
        path = self.assets / "data/subtitles/videos/VzgiaEu59Uk.json"
        value = json.loads(raw)
        value["cues"][0]["end_ms"] = 1800
        value["cues"][1]["start_ms"] = 1200
        path.write_bytes(canonical(value))
        stage_receipt(
            self.assets,
            self.receipts,
            "VzgiaEu59Uk",
            "2026-10-31T01:00:00Z",
        )
        result = build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        self.assertEqual(result["video_count"], 1)

    def test_old_vod_translated_later_uses_original_catalog_month(self):
        self._stage("VzgiaEu59Uk", "old", "2027-03-02T08:00:00Z")
        build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        self.assertTrue((self.candidate / MONTH_INDEX_DIR / "2024-06.json").is_file())
        self.assertFalse((self.candidate / MONTH_INDEX_DIR / "2027-03.json").exists())

    def test_one_off_and_batch_backfill_share_same_pipeline(self):
        self._stage("VzgiaEu59Uk", "one")
        self._stage("5cDfZaII0_0", "two")
        build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        global_index = json.loads((self.candidate / GLOBAL_INDEX_PATH).read_text())
        self.assertEqual(
            [row["video_id"] for row in global_index["videos"]],
            ["5cDfZaII0_0", "VzgiaEu59Uk"],
        )

    def test_other_month_projection_is_preserved_when_new_receipt_is_added(self):
        self._stage("CCCCCCCCCCC", "sep")
        build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        september = self.candidate / MONTH_INDEX_DIR / "2026-09.json"
        before = september.read_bytes()
        self._stage("5cDfZaII0_0", "oct")
        build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        self.assertEqual(before, september.read_bytes())
        self.assertTrue((self.candidate / MONTH_INDEX_DIR / "2026-10.json").is_file())

    def test_receipt_path_is_content_addressed_and_timestamp_is_immutable(self):
        raw = self._asset("VzgiaEu59Uk", "content-addressed")
        asset_sha = hashlib.sha256(raw).hexdigest()
        first = stage_receipt(
            self.assets, self.receipts, "VzgiaEu59Uk", "2026-10-31T01:00:00Z"
        )
        expected = self.receipts / "VzgiaEu59Uk" / f"{asset_sha}.json"
        self.assertEqual(Path(first["receipt_path"]), expected)
        before = expected.read_bytes()
        second = stage_receipt(
            self.assets, self.receipts, "VzgiaEu59Uk", "2099-01-01T00:00:00Z"
        )
        self.assertFalse(second["created"])
        self.assertEqual(before, expected.read_bytes())
        self.assertEqual(json.loads(before)["staged_at"], "2026-10-31T01:00:00Z")

    def test_same_video_and_asset_hash_with_different_binding_fails_closed(self):
        raw = self._asset("VzgiaEu59Uk", "conflict")
        asset_sha = hashlib.sha256(raw).hexdigest()
        stage_receipt(
            self.assets, self.receipts, "VzgiaEu59Uk", "2026-10-31T01:00:00Z"
        )
        receipt = self.receipts / "VzgiaEu59Uk" / f"{asset_sha}.json"
        value = json.loads(receipt.read_text())
        value["translation_artifact_id"] = "0" * 64
        receipt.write_bytes(canonical(value))
        with self.assertRaisesRegex(VodSubtitlePublishError, "immutable receipt conflict"):
            stage_receipt(
                self.assets, self.receipts, "VzgiaEu59Uk", "2026-10-31T01:00:00Z"
            )

    def test_multiple_receipts_for_same_video_fail_closed_without_supersession(self):
        self._stage("VzgiaEu59Uk", "first-version")
        self._asset("VzgiaEu59Uk", "second-version")
        stage_receipt(
            self.assets, self.receipts, "VzgiaEu59Uk", "2026-11-01T01:00:00Z"
        )
        with self.assertRaisesRegex(VodSubtitlePublishError, "explicit supersession"):
            build_candidate(self.assets, self.receipts, self.catalog, self.candidate)

    def test_identical_rerun_is_deterministic_and_idempotent(self):
        self._stage("VzgiaEu59Uk", "same")
        first = build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        second_receipt = stage_receipt(
            self.assets, self.receipts, "VzgiaEu59Uk", "2099-01-01T00:00:00Z"
        )
        second = build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        self.assertFalse(second_receipt["created"])
        self.assertFalse(second["changed"])
        self.assertEqual(first["tree_sha256"], second["tree_sha256"])

    def test_missing_or_invalid_receipt_fails_candidate_build(self):
        self._asset("VzgiaEu59Uk", "missing")
        with self.assertRaisesRegex(VodSubtitlePublishError, "no immutable publish receipts"):
            build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        invalid = self.receipts / "VzgiaEu59Uk" / ("0" * 64 + ".json")
        invalid.parent.mkdir(parents=True)
        invalid.write_text("{}")
        with self.assertRaisesRegex(VodSubtitlePublishError, "receipt contract"):
            build_candidate(self.assets, self.receipts, self.catalog, self.candidate)

    def test_catalog_month_lookup_failure_fails_closed_without_candidate(self):
        self._stage("DDDDDDDDDDD", "unknown")
        with self.assertRaisesRegex(VodSubtitlePublishError, "catalog month lookup failed"):
            build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        self.assertFalse(self.candidate.exists())

    def test_rebuild_from_receipts_is_reproducible(self):
        self._stage("VzgiaEu59Uk", "one")
        self._stage("5cDfZaII0_0", "two")
        first = build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        rebuilt = self.root / "rebuilt"
        second = build_candidate(self.assets, self.receipts, self.catalog, rebuilt)
        self.assertEqual(first["tree_sha256"], second["tree_sha256"])

    def test_public_candidate_never_exposes_private_receipts(self):
        self._stage("VzgiaEu59Uk", "private")
        build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        self.assertFalse((self.candidate / "data/subtitles/receipts").exists())
        self.assertFalse(any("receipt" in p.as_posix() for p in self.candidate.rglob("*")))

    def test_old_month_contract_is_rejected(self):
        self._stage("VzgiaEu59Uk", "old-path")
        build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        old = self.candidate / "data/subtitles/manifests/2024-06.json"
        old.write_bytes(canonical({"schema_version": 1}))
        with self.assertRaisesRegex(VodSubtitlePublishError, "old manifests"):
            validate_candidate(self.candidate, self.receipts, self.catalog)

    def test_validation_failure_does_not_mutate_separate_production_tree(self):
        production = self.root / "production"
        production.mkdir()
        sentinel = production / "known-good.txt"
        sentinel.write_text("unchanged")
        self._stage("VzgiaEu59Uk", "bad")
        receipt = next((self.receipts / "VzgiaEu59Uk").glob("*.json"))
        value = json.loads(receipt.read_text())
        value["asset_sha256"] = "0" * 64
        receipt.write_bytes(canonical(value))
        with self.assertRaisesRegex(VodSubtitlePublishError, "staged asset hash mismatch"):
            build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        self.assertEqual(sentinel.read_text(), "unchanged")

    def test_candidate_validation_requires_exact_asset_set(self):
        self._stage("VzgiaEu59Uk", "exact")
        build_candidate(self.assets, self.receipts, self.catalog, self.candidate)
        extra = self.candidate / "data/subtitles/videos/AAAAAAAAAAA.json"
        extra.write_bytes(self._asset("AAAAAAAAAAA", "extra"))
        with self.assertRaisesRegex(VodSubtitlePublishError, "asset set"):
            validate_candidate(self.candidate, self.receipts, self.catalog)


if __name__ == "__main__":
    unittest.main()
