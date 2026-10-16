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
