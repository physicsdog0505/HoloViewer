import unittest

from scripts.daily_digest_related_clips import (
    build_sidecar,
    clips_from_holodex_payload,
    normalize_language,
    source_from_holodex_payload,
)


class DailyDigestRelatedClipsTests(unittest.TestCase):
    def digest(self):
        return {
            "target_day": "2026-11-02",
            "locale": "zh-TW",
            "stories": [
                {
                    "id": "s1",
                    "title": "A",
                    "video_ids": ["AAAAAAAAAAA", "BBBBBBBBBBB"],
                },
                {
                    "id": "s2",
                    "title": "B",
                    "video_ids": ["BBBBBBBBBBB"],
                },
            ],
        }

    def test_exact_source_mapping_and_dedupe(self):
        clip_a = {
            "video_id": "CCCCCCCCCCC",
            "title": "clip a",
            "lang": "en",
            "youtube_url": "https://www.youtube.com/watch?v=CCCCCCCCCCC",
        }
        clip_b = {
            "video_id": "DDDDDDDDDDD",
            "title": "clip b",
            "lang": "zh",
            "youtube_url": "https://www.youtube.com/watch?v=DDDDDDDDDDD",
        }
        mapping = {
            "AAAAAAAAAAA": {"source_language": "en", "clips": [clip_a, clip_b]},
            "BBBBBBBBBBB": {"source_language": "ja", "clips": [clip_b]},
        }

        result = build_sidecar(
            self.digest(),
            lookup=lambda video_id: mapping[video_id],
            generated_at="2026-11-03T00:00:00Z",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["digest_locale"], "zh-TW")
        self.assertEqual(
            result["source_video_ids"],
            ["AAAAAAAAAAA", "BBBBBBBBBBB"],
        )
        self.assertEqual(
            [clip["video_id"] for clip in result["stories"][0]["clips"]],
            ["DDDDDDDDDDD", "CCCCCCCCCCC"],
        )
        self.assertEqual(result["stories"][0]["clips"][0]["language_tier"], 1)
        self.assertEqual(
            result["stories"][0]["clips"][0]["source_video_ids"],
            ["AAAAAAAAAAA", "BBBBBBBBBBB"],
        )

    def test_locale_then_source_then_other_then_unknown(self):
        mapping = {
            "AAAAAAAAAAA": {
                "source_language": "ja",
                "clips": [
                    {"video_id": "EEEEEEEEEEE", "lang": "ko", "title": "other"},
                    {"video_id": "FFFFFFFFFFF", "lang": "", "title": "unknown"},
                    {"video_id": "GGGGGGGGGGG", "lang": "ja-JP", "title": "source"},
                    {"video_id": "HHHHHHHHHHH", "lang": "zh-Hant", "title": "digest"},
                ],
            },
            "BBBBBBBBBBB": {"source_language": "en", "clips": []},
        }
        result = build_sidecar(
            self.digest(),
            lookup=lambda video_id: mapping[video_id],
            generated_at="2026-11-03T00:00:00Z",
        )
        story = result["stories"][0]
        self.assertEqual(
            [clip["video_id"] for clip in story["clips"]],
            ["HHHHHHHHHHH", "GGGGGGGGGGG", "EEEEEEEEEEE", "FFFFFFFFFFF"],
        )
        self.assertEqual(
            [clip["language_tier"] for clip in story["clips"]],
            [1, 2, 3, 4],
        )

    def test_future_digest_locale_changes_priority_without_refetch(self):
        mapping = {
            "AAAAAAAAAAA": {
                "source_language": "ja",
                "clips": [
                    {"video_id": "CCCCCCCCCCC", "lang": "zh", "title": "zh"},
                    {"video_id": "DDDDDDDDDDD", "lang": "en-US", "title": "en"},
                ],
            },
            "BBBBBBBBBBB": {"source_language": "ja", "clips": []},
        }
        result = build_sidecar(
            self.digest(),
            lookup=lambda video_id: mapping[video_id],
            generated_at="2026-11-03T00:00:00Z",
            digest_locale="en",
        )
        self.assertEqual(result["digest_locale"], "en")
        self.assertEqual(result["digest_locale_source"], "override")
        self.assertEqual(
            [clip["video_id"] for clip in result["stories"][0]["clips"]],
            ["DDDDDDDDDDD", "CCCCCCCCCCC"],
        )

    def test_partial_provider_failure_is_nonblocking(self):
        def lookup(video_id):
            if video_id == "AAAAAAAAAAA":
                raise RuntimeError("provider unavailable")
            return {"source_language": "ja", "clips": []}

        result = build_sidecar(
            self.digest(),
            lookup=lookup,
            generated_at="2026-11-03T00:00:00Z",
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sources"]["AAAAAAAAAAA"]["status"], "error")
        self.assertEqual(result["sources"]["BBBBBBBBBBB"]["status"], "ok")

    def test_parse_holodex_source_and_clips(self):
        payload = [
            {
                "id": "AAAAAAAAAAA",
                "lang": "ja",
                "clips": [
                    {
                        "id": "CCCCCCCCCCC",
                        "title": "clip",
                        "lang": "zh-TW",
                        "channel": {"id": "UC1", "name": "Clipper"},
                        "duration": 75,
                    },
                    {
                        "id": "CCCCCCCCCCC",
                        "title": "duplicate",
                    },
                ],
            }
        ]

        source = source_from_holodex_payload(payload, "AAAAAAAAAAA")
        clips = clips_from_holodex_payload(payload, "AAAAAAAAAAA")

        self.assertEqual(source["source_language"], "ja")
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["video_id"], "CCCCCCCCCCC")
        self.assertEqual(clips[0]["lang"], "zh-TW")
        self.assertEqual(clips[0]["channel_name"], "Clipper")

    def test_language_normalization(self):
        self.assertEqual(normalize_language("zh_hant"), "zh-Hant")
        self.assertEqual(normalize_language("EN-us"), "en-US")
        self.assertEqual(normalize_language("ja"), "ja")


if __name__ == "__main__":
    unittest.main()
