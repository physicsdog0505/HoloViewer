"""Offline, no-network checks for 8788's canonical API data boundary."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from platform_adapter.public_api import PublicAPI, PublicAPIUnavailable
from platform_adapter.product_bindings import bind_home_reader


@dataclass(frozen=True)
class FakeHomeStream:
    video_id: str
    title: str
    channel_title: str
    start_label: str
    state: str
    source_label: str = ""
    channel_id: str = ""
    avatar_url: str = ""
    group: str = "unknown"
    start_at: object = None


class ProviderBindingTest(unittest.TestCase):
    def test_only_canonical_https_origin(self):
        PublicAPI()
        for bad in ("http://example.org", "https://x.test", "https://x.test/evil",
                    "https://user:pass@x.test", "https://x.test?key=secret"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                PublicAPI(bad)

    def test_explicit_test_only_origin_does_not_relax_production(self):
        alternate = PublicAPI("https://mock.example.test", _test_only_allow_alternate_origin=True)
        self.assertEqual(alternate.origin, "https://mock.example.test")
        with self.assertRaises(ValueError):
            PublicAPI("https://mock.example.test")

    def test_home_reader_never_invents_live_state_or_group(self):
        class Stub:
            def read_today(self):
                return {"items": [
                    {"video_id": "dQw4w9WgXcQ", "lifecycle_state": "stale"},
                    {"video_id": "9bZkp7q19f0", "lifecycle_state": "waiting",
                     "group": "holostars"}
                ]}
        live, upcoming, ended, unknown = bind_home_reader(Stub(), FakeHomeStream)()
        self.assertEqual((len(live),len(upcoming),len(ended),len(unknown)), (0,1,0,1))
        self.assertEqual(unknown[0].group,"unknown")
        self.assertEqual(unknown[0].state,"stale")
        self.assertEqual(upcoming[0].state,"waiting")

    def test_live_requires_fresh_authoritative_feed(self):
        class Stub:
            def __init__(self, freshness):
                self.freshness=freshness
            def read_today(self):
                return {"freshness":self.freshness,"items":[
                    {"video_id":"dQw4w9WgXcQ","lifecycle_state":"live"}
                ]}
        for state in ("stale","unknown",None):
            live,_,_,unknown=bind_home_reader(Stub(state),FakeHomeStream)()
            self.assertEqual(len(live),0)
            self.assertEqual(len(unknown),1)
        live,_,_,_=bind_home_reader(Stub("fresh"),FakeHomeStream)()
        self.assertEqual(len(live),1)

    def test_missing_consumer_list_fails_closed(self):
        class Stub:
            def read_today(self):
                return {"state": "unknown"}
        with self.assertRaises(PublicAPIUnavailable):
            bind_home_reader(Stub(), FakeHomeStream)()

    def test_day_and_video_identity_bounded(self):
        api=PublicAPI()
        with self.assertRaises(ValueError):
            api.read_video("incorrect")
        with self.assertRaises(ValueError):
            api.read_day(date(2026,10,15),limit=1000)
