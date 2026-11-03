import unittest

from scripts.daily_digest_related_clips import (
    build_sidecar,
    clips_from_holodex_payload,
)


class DailyDigestRelatedClipsTests(unittest.TestCase):
    def digest(self):
        return {
            "target_day": "2026-11-02",
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
            "AAAAAAAAAAA": [clip_a, clip_b],
            "BBBBBBBBBBB": [clip_b],
        }

        result = build_sidecar(
            self.digest(),
            lookup=lambda video_id: mapping[video_id],
            generated_at="2026-11-03T00:00:00Z",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            result["source_video_ids"],
            ["AAAAAAAAAAA", "BBBBBBBBBBB"],
        )
        self.assertEqual(
            [clip["video_id"] for clip in result["stories"][0]["clips"]],
            ["CCCCCCCCCCC", "DDDDDDDDDDD"],
        )
        self.assertEqual(
            [clip["video_id"] for clip in result["stories"][1]["clips"]],
            ["DDDDDDDDDDD"],
        )

    def test_partial_provider_failure_is_nonblocking(self):
        def lookup(video_id):
            if video_id == "AAAAAAAAAAA":
                raise RuntimeError("provider unavailable")
            return []

        result = build_sidecar(
            self.digest(),
            lookup=lookup,
            generated_at="2026-11-03T00:00:00Z",
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sources"]["AAAAAAAAAAA"]["status"], "error")
        self.assertEqual(result["sources"]["BBBBBBBBBBB"]["status"], "ok")
        self.assertEqual(result["stories"][0]["clips"], [])

    def test_parse_holodex_clips(self):
        payload = [
            {
                "id": "AAAAAAAAAAA",
                "clips": [
                    {
                        "id": "CCCCCCCCCCC",
                        "title": "clip",
                        "lang": "en",
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

        clips = clips_from_holodex_payload(payload, "AAAAAAAAAAA")

        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["video_id"], "CCCCCCCCCCC")
        self.assertEqual(clips[0]["channel_name"], "Clipper")
        self.assertEqual(
            clips[0]["youtube_url"],
            "https://www.youtube.com/watch?v=CCCCCCCCCCC",
        )


if __name__ == "__main__":
    unittest.main()
