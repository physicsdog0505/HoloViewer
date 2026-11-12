import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from ptt_offline.activate_production_publisher import (
    parse_table_names_output, ensure_schema, REQUIRED_TABLES, start_publisher,
)

class ActivationPreflightTests(unittest.TestCase):
    def test_parses_wrapped_wrangler_table_rows(self):
        raw = """ ⛅️ wrangler 4.151.0
┌──────────────────────────────┐
│ name                         │
├──────────────────────────────┤
│ ptt_gap_repairs              │
│ ptt_provider_state           │
│ ptt_pushes                   │
│ ptt_source_evidence          │
│ ptt_threads                  │
│ public_ptt_schema_migrations │
└──────────────────────────────┘
"""
        self.assertEqual(parse_table_names_output(raw), {
            "ptt_gap_repairs","ptt_provider_state","ptt_pushes",
            "ptt_source_evidence","ptt_threads","public_ptt_schema_migrations"
        })

    def test_parses_line_wrapped_names_anywhere_in_output(self):
        raw = "│ ptt_gap_\nrepairs │\n│ ptt_pushes │\n"
        # Exact identifiers are required; a split identifier must not be fabricated.
        self.assertEqual(parse_table_names_output(raw), {"ptt_pushes"})

    def test_parses_empty_schema_table(self):
        raw = "│ name │\n"
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

    def test_production_start_uses_continuous_iterations(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            secrets_path=root/".publisher-secrets.json"
            secrets_path.write_text(json.dumps({
                "PTT_PUBLISH_HMAC_SECRET":"h"*64,
                "PTT_TIME_AUTHORITY_SECRET":"t"*64,
            }),encoding="utf-8")
            process=Mock(pid=12345)
            process.poll.return_value=None
            with patch("ptt_offline.activate_production_publisher.run") as run, \
                 patch("ptt_offline.activate_production_publisher.subprocess.Popen",
                       return_value=process) as popen, \
                 patch("ptt_offline.activate_production_publisher.time.sleep"):
                result=start_publisher(Path("/tmp/repo"),"/tmp/source.sqlite3",root,secrets_path)

        dry_run_cmd=run.call_args_list[0].args[0]
        self.assertEqual(dry_run_cmd[dry_run_cmd.index("--iterations")+1],"1")
        live_cmd=popen.call_args.args[0]
        self.assertEqual(live_cmd[live_cmd.index("--iterations")+1],"0")
        self.assertIn("--send",live_cmd)
        self.assertEqual(result["pid"],12345)

if __name__ == "__main__":
    unittest.main()
