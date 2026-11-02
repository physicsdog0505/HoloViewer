import json
from pathlib import Path
import tempfile
import unittest

from scripts.daily_digest_return_ingest_v2 import ReturnIngestError, stage_return


def zh(seed: str, n: int) -> str:
    return (seed * (n // len(seed) + 1))[:n]


def payload(day="2026-10-31"):
    ids = ["vid00000001", "vid00000002", "vid00000003"]
    highlights = []
    stories = []
    streams = []
    for i, video_id in enumerate(ids):
        highlights.append({
            "title": f"完整主題 {i+1}",
            "short_title": zh("今日重點", 12),
            "summary": zh("這是有足夠資訊密度的重點摘要。", 60),
            "video_ids": [video_id],
            "recommended_role": "lead_candidate" if i == 0 else "normal",
        })
        stories.append({
            "id": f"story_{i+1}",
            "title": f"完整故事 {i+1}",
            "editorial_summary": zh("這是完整故事主文。", 360),
            "video_ids": [video_id],
            "reader_mode": "inline",
            "summary_depth": "standard",
        })
        streams.append({
            "input_index": i + 1,
            "video_id": video_id,
            "verification_status": "verified_content",
            "summary": "verified",
            "topics": [],
            "story_ids": [f"story_{i+1}"],
            "announcement_ids": [],
            "editorial_signals": {},
        })
    return {
        "meta": {
            "schema_version": "holodocchi.gemini.daily_digest.v2",
            "target_day": day,
            "timezone": "Asia/Taipei",
        },
        "audit_stats": {
            "total_streams": 3,
            "verified_content": 3,
            "metadata_only": 0,
            "unverified": 0,
        },
        "overview": {
            "public_summary": zh("今日主要脈絡與重要事件摘要。", 320),
            "presentation_hint": "compact",
            "highlights": highlights,
        },
        "stories": stories,
        "streams": streams,
        "announcements": [],
        "categories": [],
        "unverified": [],
    }


def manifest(json_name, md_name):
    return f"""# test
SCHEMA_VERSION=holodocchi.gemini.daily_digest.v2
GUIDELINE_FILE=Holodocchi-Daily-Digest-Guideline-v2.md
TARGET_DAY: 2026-10-31
TIMEZONE: Asia/Taipei

EXPECTED_OUTPUT_FILES:
- {json_name}
- {md_name}

## Stream List

### 001
- video_id: vid00000001
### 002
- video_id: vid00000002
### 003
- video_id: vid00000003
"""


class DailyDigestReturnIngestV2Tests(unittest.TestCase):
    def prepare(self, root: Path):
        json_name = "2026-10-31-holodocchi-gemini-digest-review.json"
        md_name = "2026-10-31-holodocchi-gemini-digest-review.md"
        manifest_path = root / "manifest.md"
        json_path = root / json_name
        md_path = root / md_name
        manifest_path.write_text(manifest(json_name, md_name), encoding="utf-8")
        json_path.write_text(json.dumps(payload(), ensure_ascii=False), encoding="utf-8")
        md_path.write_text("# readable sibling\n", encoding="utf-8")
        return manifest_path, json_path, md_path

    def test_stages_immutable_raw_siblings_and_public_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path, json_path, md_path = self.prepare(root)
            result = stage_return(
                manifest_path=manifest_path,
                gemini_json_path=json_path,
                gemini_markdown_path=md_path,
                staging_root=root / "staging",
            )
            revision = Path(result["revision_dir"])
            self.assertEqual(result["stage_status"], "CREATED")
            self.assertEqual(result["status"], "READY_FOR_PUBLICATION")
            self.assertEqual(result["stream_count"], 3)
            self.assertTrue((revision / json_path.name).is_file())
            self.assertTrue((revision / md_path.name).is_file())
            public = json.loads((revision / "2026-10-31.public-candidate.json").read_text(encoding="utf-8"))
            self.assertEqual(public["kind"], "holodocchi.daily_digest")
            self.assertEqual(public["target_day"], "2026-10-31")


    def test_accepts_canonical_output_filenames_without_review_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            json_name = "2026-10-31-holodocchi-gemini-digest.json"
            md_name = "2026-10-31-holodocchi-gemini-digest.md"
            manifest_path = root / "manifest.md"
            json_path = root / json_name
            md_path = root / md_name
            manifest_path.write_text(manifest(json_name, md_name), encoding="utf-8")
            json_path.write_text(json.dumps(payload(), ensure_ascii=False), encoding="utf-8")
            md_path.write_text("# readable canonical sibling\n", encoding="utf-8")

            result = stage_return(
                manifest_path=manifest_path,
                gemini_json_path=json_path,
                gemini_markdown_path=md_path,
                staging_root=root / "staging",
            )

            self.assertEqual(result["status"], "READY_FOR_PUBLICATION")
            self.assertEqual(result["gemini_json_file"], json_name)
            self.assertEqual(result["gemini_markdown_file"], md_name)

    def test_identical_return_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path, json_path, md_path = self.prepare(root)
            kwargs = dict(
                manifest_path=manifest_path,
                gemini_json_path=json_path,
                gemini_markdown_path=md_path,
                staging_root=root / "staging",
            )
            first = stage_return(**kwargs)
            second = stage_return(**kwargs)
            self.assertEqual(first["gemini_json_sha256"], second["gemini_json_sha256"])
            self.assertEqual(second["stage_status"], "NO_CHANGE")

    def test_rejects_sibling_filename_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path, json_path, md_path = self.prepare(root)
            renamed = root / "wrong.md"
            renamed.write_bytes(md_path.read_bytes())
            with self.assertRaises(ReturnIngestError):
                stage_return(
                    manifest_path=manifest_path,
                    gemini_json_path=json_path,
                    gemini_markdown_path=renamed,
                    staging_root=root / "staging",
                )

    def test_rejects_stream_order_or_coverage_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path, json_path, md_path = self.prepare(root)
            src = payload()
            src["streams"][0], src["streams"][1] = src["streams"][1], src["streams"][0]
            json_path.write_text(json.dumps(src, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ReturnIngestError):
                stage_return(
                    manifest_path=manifest_path,
                    gemini_json_path=json_path,
                    gemini_markdown_path=md_path,
                    staging_root=root / "staging",
                )

    def test_same_json_revision_cannot_silently_replace_changed_markdown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest_path, json_path, md_path = self.prepare(root)
            kwargs = dict(
                manifest_path=manifest_path,
                gemini_json_path=json_path,
                gemini_markdown_path=md_path,
                staging_root=root / "staging",
            )
            stage_return(**kwargs)
            md_path.write_text("# changed sibling\n", encoding="utf-8")
            with self.assertRaises(ReturnIngestError):
                stage_return(**kwargs)


if __name__ == "__main__":
    unittest.main()
