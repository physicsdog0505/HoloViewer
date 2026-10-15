import unittest
from unittest.mock import patch
from ptt_offline.activate_production_publisher import parse_table_names_output, ensure_schema, REQUIRED_TABLES

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


    def test_exact_legacy_schema_adds_only_gap_repairs(self):
        legacy = set(REQUIRED_TABLES) - {"ptt_gap_repairs"}
        calls = []
        with patch("ptt_offline.activate_production_publisher.d1_table_names",
                   side_effect=[legacy, set(REQUIRED_TABLES)]), \
             patch("ptt_offline.activate_production_publisher.run",
                   side_effect=lambda cmd, **kwargs: calls.append(cmd)):
            ensure_schema("/tmp/wrangler.json", __import__("pathlib").Path("/tmp/repo"))
        self.assertEqual(len(calls), 1)
        self.assertIn("--command", calls[0])
        self.assertIn("CREATE TABLE IF NOT EXISTS ptt_gap_repairs", calls[0][-1])
        self.assertNotIn("--file", calls[0])

    def test_unexpected_partial_schema_still_fails_closed(self):
        with patch("ptt_offline.activate_production_publisher.d1_table_names",
                   return_value={"ptt_threads"}):
            with self.assertRaises(SystemExit):
                ensure_schema("/tmp/wrangler.json", __import__("pathlib").Path("/tmp/repo"))

if __name__ == "__main__":
    unittest.main()
