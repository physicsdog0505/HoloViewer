#!/usr/bin/env python3
"""Dependency-free test of the Public Watchalong export integrity policy."""
import importlib.util
from pathlib import Path
import unittest

MODULE=Path(__file__).with_name("export-watchalong-events.py")
spec=importlib.util.spec_from_file_location("watchalong_exporter",MODULE)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def event(event_id="watch:123",video_id="U2o13h1Oib4"):
    return {"event_id":event_id,"source_url":"https://www.ptt.cc/bbs/C_Chat/M.123.A.ABC.html",
            "streams":[{"video_id":video_id,"label":"host"}]}

class ProjectionGateTests(unittest.TestCase):
    def test_refresh_fail_closed_on_fetch_errors(self):
        stats={"targets":58,"already_cached":13,"fetched":0,
               "errors":[{"stage":"fetch","error":"missing playwright"}]}
        self.assertFalse(module.refresh_coverage_ok(stats))
    def test_refresh_fail_closed_on_unaccounted_targets(self):
        self.assertFalse(module.refresh_coverage_ok({"targets":58,"already_cached":13,
                     "fetched":42,"errors":[]}))
    def test_refresh_complete_if_all_cached(self):
        self.assertTrue(module.refresh_coverage_ok({"targets":13,"already_cached":13,
                     "fetched":0,"errors":[]}))
    def test_refresh_complete_if_all_fetched(self):
        self.assertTrue(module.refresh_coverage_ok({"targets":3,"already_cached":0,
                     "fetched":3,"errors":[]}))
    def test_integrity_reports_reasons_without_body(self):
        wrong=event(video_id="bad")
        wrong["aid"]="sample"
        wrong["day"]="2026-10-15"
        wrong["body_text"]="PRIVATE"
        issues=module.projection_issues([wrong])
        self.assertEqual(issues[0]["reasons"],["invalid_host_video_id"])
        self.assertNotIn("PRIVATE",str(issues))
    def test_duplicate_diagnostic(self):
        issues=module.projection_issues([event(),event()])
        self.assertEqual(issues[0]["reasons"],["duplicate_event_id"])
    def test_valid(self):
        self.assertTrue(module.validate_projection([event(),event("watch:456","8pF4qHcshDc")]))
    def test_duplicate_events_fail(self):
        self.assertFalse(module.validate_projection([event(),event()]))
    def test_missing_hosts_fail(self):
        x=event();x["streams"]=[]
        self.assertFalse(module.validate_projection([x]))
    def test_malformed_video_fail(self):
        self.assertFalse(module.validate_projection([event(video_id="bad")]))
    def test_private_source_url_fail(self):
        x=event();x["source_url"]="file:///private/ptt"
        self.assertFalse(module.validate_projection([x]))

if __name__=="__main__":
    unittest.main()
