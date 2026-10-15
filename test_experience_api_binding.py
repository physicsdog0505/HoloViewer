from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import unittest

from platform_adapter.public_api import PublicAPI, PublicAPIUnavailable, preloaded_public_reads
from platform_adapter.product_bindings import bind_collab_reader, bind_watchalong_reader


@dataclass(frozen=True)
class Home:
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


@dataclass(frozen=True)
class Host:
    label: str
    video_id: str
    channel_name: str = ""
    avatar_url: str = ""


@dataclass(frozen=True)
class Card:
    title: str
    day: str
    scheduled_time: str
    member_only: bool
    hosts: tuple


class ExperienceApiBindingTest(unittest.TestCase):
    def test_public_api_collab_preload_contract(self):
        payload={"events":[{"event_id":"ark:2026-10-15","streams":[]}]}
        with preloaded_public_reads({("/v1/collab/live", ()): payload}):
            self.assertIs(PublicAPI().read_collab_live(), payload)
        with self.assertRaises(ValueError):
            PublicAPI().read_collab_event("../bad")

    def test_public_api_watchalong_preload_contract(self):
        params=(("days","30"),("limit","60"))
        payload={"events":[]}
        with preloaded_public_reads({("/v1/watchalong/recent", params): payload}):
            self.assertIs(PublicAPI().read_watchalong_recent(), payload)
        with self.assertRaises(ValueError):
            PublicAPI().read_watchalong_event("watch:not-a-digest")

    def test_collab_binding_flattens_and_dedupes_existing_home_stream_shape(self):
        class Stub:
            def read_collab_live(self):
                return {"events":[
                    {"streams":[
                        {"video_id":"dQw4w9WgXcQ","title":"A","channel_id":"UC"+"A"*22,
                         "channel_name":"A","lifecycle_state":"live","actual_start":"2026-10-15T10:00:00Z"},
                        {"video_id":"9bZkp7q19f0","title":"B","channel_id":"UC"+"B"*22,
                         "channel_name":"B","lifecycle_state":"ended","actual_start":"2026-10-15T09:00:00Z"},
                    ]},
                    {"streams":[
                        {"video_id":"dQw4w9WgXcQ","title":"A","channel_id":"UC"+"A"*22,
                         "channel_name":"A","lifecycle_state":"live","actual_start":"2026-10-15T10:00:00Z"}
                    ]}
                ]}
        live,upcoming,ended=bind_collab_reader(Stub(),Home)()
        self.assertEqual([x.video_id for x in live],["dQw4w9WgXcQ"])
        self.assertEqual(upcoming,[])
        self.assertEqual([x.video_id for x in ended],["9bZkp7q19f0"])

    def test_watchalong_binding_exposes_minimal_cards_without_local_db(self):
        class Stub:
            def read_watchalong_recent(self, *, days=30, limit=60):
                self.args=(days,limit)
                return {"events":[{
                    "title":"Movie watchalong","day":"2026-10-15","scheduled_time":"20:00",
                    "member_only":True,
                    "hosts":[{"label":"Host A","video_id":"dQw4w9WgXcQ"}],
                    "source_mapping":None,
                    "capabilities":{"source_mapping":False,"translation":False,"telemetry":False}
                }]}
        stub=Stub()
        cards=bind_watchalong_reader(stub,Card,Host)(days=14,limit=20)
        self.assertEqual(stub.args,(14,20))
        self.assertEqual(len(cards),1)
        self.assertTrue(cards[0].member_only)
        self.assertEqual(cards[0].hosts[0].video_id,"dQw4w9WgXcQ")
        with self.assertRaises(ValueError):
            bind_watchalong_reader(stub,Card,Host)(database_path="/tmp/private.sqlite3")


if __name__ == "__main__":
    unittest.main()
