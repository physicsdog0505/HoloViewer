import unittest
from ptt_offline.activate_production_publisher import parse_table_names_output

class ActivationPreflightTests(unittest.TestCase):
    def test_parses_wrangler_human_table_marker(self):
        raw = """ ⛅️ wrangler 4.151.0
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ marker                                                                                                                               │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ PTT_TABLES=ptt_gap_repairs,ptt_provider_state,ptt_pushes,ptt_source_evidence,ptt_threads,public_ptt_schema_migrations                │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
"""
        self.assertEqual(parse_table_names_output(raw), {
            "ptt_gap_repairs","ptt_provider_state","ptt_pushes",
            "ptt_source_evidence","ptt_threads","public_ptt_schema_migrations"
        })

    def test_parses_empty_marker(self):
        raw = "│ PTT_TABLES= │"
        self.assertEqual(parse_table_names_output(raw), set())

    def test_missing_marker_fails_closed(self):
        with self.assertRaises(SystemExit):
            parse_table_names_output("wrangler failed before query output")

if __name__ == "__main__":
    unittest.main()
