import copy
import unittest

from scripts.daily_digest_normalizer_v2 import (
    ContractError,
    GEMINI_V2_SCHEMA,
    normalize_digest,
)


def zh(seed: str, n: int) -> str:
    return (seed * (n // len(seed) + 1))[:n]


def v2_payload(hint="compact"):
    highlights = []
    stories = []
    for i in range(3):
        video_id = f"v{i:010d}"
        highlights.append({
            "title": f"第{i+1}個完整主題標題：跨頻道企劃與重要事件",
            "short_title": zh("重要主題", 16 + i),
            "summary": zh("這是可直接呈現在卡片上的摘要內容。", 60 + i),
            "video_ids": [video_id],
            "recommended_role": "lead_candidate" if i == 0 else "normal",
        })
        stories.append({
            "id": f"story_{i}",
            "title": f"第{i+1}個完整詳細故事標題，不得由前端截斷",
            "summary": zh("詳細故事摘要內容。", 120),
            "video_ids": [video_id],
            "editorial_signals": {"recommended_role": "lead_candidate" if i == 0 else "normal"},
        })
    return {
        "meta": {
            "schema_version": GEMINI_V2_SCHEMA,
            "target_day": "2026-10-25",
            "timezone": "Asia/Taipei",
        },
        "overview": {
            "public_summary": zh("今日主要脈絡涵蓋跨頻道大型企劃、遊戲連動與重要公告。", 320),
            "presentation_hint": hint,
            "highlights": highlights,
        },
        "stories": stories,
        "streams": [
            {
                "video_id": f"v{i:010d}",
                "summary": zh(f"第{i+1}支直播的 Gemini 詳細研究內容，包含具體事件與脈絡。", 260),
            }
            for i in range(3)
        ],
        "announcements": [{"title": "完整公告標題", "summary": "完整公告摘要", "video_ids": ["v0000000000"]}],
        "categories": [{"key": "x", "label": "分類", "video_ids": ["v0000000000", "v0000000000"]}],
    }


class DailyDigestNormalizerV2Tests(unittest.TestCase):
    def test_valid_v2_uses_authoritative_hint_and_structured_highlights(self):
        src = v2_payload("rail")
        result = normalize_digest(src)
        self.assertEqual(result.artifact["overview_layout"], "rail")
        self.assertEqual(result.artifact["schema_version"], 1)
        self.assertEqual(result.artifact["kind"], "holodocchi.daily_digest")
        self.assertEqual(result.artifact["target_day"], "2026-10-25")
        self.assertEqual(result.artifact["timezone"], "Asia/Taipei")
        self.assertEqual(result.artifact["producer_v2"]["source_schema"], GEMINI_V2_SCHEMA)
        self.assertIsInstance(result.artifact["overview"]["highlights"][0], dict)
        self.assertEqual(result.artifact["overview"]["highlights"][0]["video_ids"], ["v0000000000"])
        self.assertEqual(result.warnings, ())

    def test_story_without_editorial_summary_preserves_public_summary_only(self):
        src = v2_payload("compact")
        public_summary = zh("跨直播短摘要。", 90)
        src["stories"][0]["public_summary"] = public_summary
        result = normalize_digest(src)
        story = result.artifact["stories"][0]
        self.assertEqual(story["public_summary"], public_summary)
        self.assertEqual(story["editorial_summary"], public_summary)
        self.assertNotIn("Gemini 詳細研究內容", story["editorial_summary"])

    def test_explicit_story_editorial_summary_is_preserved(self):
        src = v2_payload("compact")
        explicit = zh("Gemini 已完成的完整跨直播編輯主文。", 420)
        src["stories"][0]["editorial_summary"] = explicit
        result = normalize_digest(src)
        self.assertEqual(result.artifact["stories"][0]["editorial_summary"], explicit)

    def test_stream_summary_does_not_duplicate_story_copy(self):
        src = v2_payload("compact")
        compact = "KoZMy 晚酌派對宣布原創曲與個唱來賓。"
        src["stories"][0]["public_summary"] = compact
        src["streams"][0]["summary"] = (
            "KoZMy 萬聖節 3D 晚酌派對中，博衣こより與 AZKi、雪花ラミィ一同品嚐日本酒，"
            "並宣布首支團體原創曲與 12 月個唱唯一來賓陣容。"
        )
        result = normalize_digest(src)
        self.assertEqual(result.artifact["stories"][0]["editorial_summary"], compact)

    def test_story_reader_mode_inline_is_preserved(self):
        src = v2_payload("compact")
        src["stories"][0]["reader_mode"] = "inline"
        result = normalize_digest(src)
        self.assertEqual(result.artifact["stories"][0]["reader_mode"], "inline")

    def test_story_reader_mode_defaults_to_summary_with_details(self):
        src = v2_payload("compact")
        result = normalize_digest(src)
        self.assertEqual(result.artifact["stories"][0]["reader_mode"], "summary_with_details")

    def test_invalid_story_reader_mode_falls_back_with_warning(self):
        src = v2_payload("compact")
        src["stories"][0]["reader_mode"] = "auto"
        result = normalize_digest(src)
        self.assertEqual(result.artifact["stories"][0]["reader_mode"], "summary_with_details")
        self.assertTrue(any("reader_mode='auto'" in w for w in result.warnings))

    def test_invalid_hint_has_deterministic_fallback(self):
        src = v2_payload("magazine")
        result = normalize_digest(src)
        self.assertEqual(result.artifact["overview_layout"], "compact")
        self.assertTrue(any("invalid overview presentation_hint" in w for w in result.warnings))

    def test_missing_hint_fallback_is_deterministic_and_idempotent(self):
        src = v2_payload("")
        a = normalize_digest(src)
        b = normalize_digest(src)
        self.assertEqual(a.artifact, b.artifact)
        self.assertEqual(a.source_sha256, b.source_sha256)

    def test_long_copy_is_bounded_without_mutating_source(self):
        src = v2_payload("compact")
        original = copy.deepcopy(src)
        src["overview"]["public_summary"] = zh("超長總覽內容。", 700)
        src["overview"]["highlights"][0]["summary"] = zh("超長重點摘要。", 180)
        result = normalize_digest(src)
        self.assertLessEqual(len(result.artifact["overview"]["public_summary"]), 520)
        self.assertLessEqual(len(result.artifact["overview"]["highlights"][0]["summary"]), 110)
        self.assertEqual(src["overview"]["highlights"][1], original["overview"]["highlights"][1])
        self.assertEqual(len(src["overview"]["highlights"][0]["summary"]), 180)

    def test_v2_rejects_too_short_summary_and_missing_evidence(self):
        src = v2_payload()
        src["overview"]["highlights"][0]["summary"] = "太短"
        with self.assertRaises(ContractError):
            normalize_digest(src)
        src = v2_payload()
        src["overview"]["highlights"][0]["video_ids"] = []
        with self.assertRaises(ContractError):
            normalize_digest(src)

    def test_legacy_v1_string_highlights_are_migrated(self):
        legacy = {
            "schema_version": 1,
            "kind": "holodocchi.daily_digest",
            "target_day": "2026-10-25",
            "timezone": "Asia/Taipei",
            "overview": {
                "summary": "舊版摘要。",
                "highlights": [
                    "大型企劃正式展開：多位成員跨台合作並公布後續安排。",
                    "遊戲連動持續進行：多個隊伍完成重要挑戰。",
                    "官方公告集中發布：活動與商品資訊同步公開。",
                ],
            },
            "stories": [
                {"title": "故事一", "summary": "摘要一", "video_ids": ["abcdefghijk"], "editorial_signals": {"recommended_role": "lead_candidate"}},
                {"title": "故事二", "summary": "摘要二", "video_ids": ["lmnopqrstuv"]},
                {"title": "故事三", "summary": "摘要三", "video_ids": ["12345678901"]},
            ],
        }
        result = normalize_digest(legacy)
        self.assertEqual(len(result.artifact["overview"]["highlights"]), 3)
        self.assertEqual(result.artifact["overview"]["highlights"][0]["video_ids"], ["abcdefghijk"])
        self.assertIn(result.artifact["overview_layout"], {"compact", "rail", "lead"})
        self.assertEqual(result.artifact["producer_v2"]["source_schema"], "legacy-v1")

    def test_source_hash_changes_only_when_source_changes(self):
        src = v2_payload()
        a = normalize_digest(src)
        b = normalize_digest(copy.deepcopy(src))
        self.assertEqual(a.source_sha256, b.source_sha256)
        src["overview"]["highlights"][0]["title"] += "改"
        c = normalize_digest(src)
        self.assertNotEqual(a.source_sha256, c.source_sha256)


if __name__ == "__main__":
    unittest.main()
