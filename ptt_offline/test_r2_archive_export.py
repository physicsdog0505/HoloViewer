from __future__ import annotations

import unittest

from ptt_offline.r2_archive_export import remove_provable_repair_overlap


def row(line,clock,content,collected):
    return {
        "source_line":line,"kind":"推","author":"user","content":content,
        "ptt_date":"11/07","ptt_time":clock,"collected_at":collected,
    }


class RepairOverlapTests(unittest.TestCase):
    def test_exact_later_batch_page_tail_overlap_is_removed(self):
        rows=[
            row(169,"18:48","a","2026-11-07T11:11:37+00:00"),
            row(170,"18:55","b","2026-11-07T11:11:41+00:00"),
            row(171,"18:57","c","2026-11-07T11:11:42+00:00"),
            row(172,"18:58","d","2026-11-07T11:11:43+00:00"),
            row(173,"19:02","e","2026-11-07T11:11:56+00:00"),
            row(174,"18:48","a","2026-11-07T23:31:28+00:00"),
            row(175,"18:55","b","2026-11-07T23:31:28+00:00"),
            row(176,"18:57","c","2026-11-07T23:31:29+00:00"),
            row(177,"18:58","d","2026-11-07T23:31:29+00:00"),
            row(178,"19:02","e","2026-11-07T23:31:29+00:00"),
            row(179,"19:02","new","2026-11-07T23:31:29+00:00"),
        ]

        cleaned,evidence=remove_provable_repair_overlap(rows)

        self.assertEqual([item["source_line"] for item in cleaned],
                         [169,170,171,172,173,179])
        self.assertEqual(evidence,[{
            "first_source_line":174,"last_source_line":178,"row_count":5,
            "reason":"exact-later-capture-page-tail-overlap"}])

    def test_single_repeated_comment_is_preserved(self):
        rows=[
            row(1,"18:48","same","2026-11-07T11:11:37+00:00"),
            row(2,"18:48","same","2026-11-07T23:31:28+00:00"),
        ]
        cleaned,evidence=remove_provable_repair_overlap(rows)
        self.assertEqual(cleaned,rows)
        self.assertEqual(evidence,[])

    def test_same_sequence_in_one_capture_batch_is_preserved(self):
        rows=[
            row(1,"18:48","a","2026-11-07T11:11:37+00:00"),
            row(2,"18:49","b","2026-11-07T11:11:38+00:00"),
            row(3,"18:48","a","2026-11-07T11:11:39+00:00"),
            row(4,"18:49","b","2026-11-07T11:11:40+00:00"),
        ]
        cleaned,evidence=remove_provable_repair_overlap(rows)
        self.assertEqual(cleaned,rows)
        self.assertEqual(evidence,[])


if __name__=="__main__":
    unittest.main()
