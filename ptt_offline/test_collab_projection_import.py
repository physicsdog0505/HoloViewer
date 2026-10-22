import json
import unittest

from ptt_offline.collab_projection_import import render_sql, validate


class CollabProjectionImportTests(unittest.TestCase):
    def fixture(self):
        event_id="holoserver-hide-and-seek:5680e7ec7c29074a"
        payload={
            "event_id":event_id,
            "event_key":"holoserver-hide-and-seek",
            "label":"#ホロ鯖かくれんぼ",
            "confidence":"explicit-event",
            "streams":[
                {"video_id":"89kUA14-sCc"},
                {"video_id":"Uy-KPheZe7U"},
                {"video_id":"bB5HkHSQWkI"},
                {"video_id":"ihKbojqvGAk"},
                {"video_id":"mOeNtn8bn3A"},
            ],
        }
        return {
            "schema_version":"public-collab-projection-v1",
            "source_revision":"sha256:"+"a"*64,
            "generated_at":"2026-10-22T17:00:00+00:00",
            "source_event_count":1,
            "effective_event_count":1,
            "source":{
                "range_start":"2026-10-21T16:00:00+00:00",
                "range_end":"2026-10-22T16:00:00+00:00",
            },
            "events":[{
                "event_id":event_id,
                "event_key":"holoserver-hide-and-seek",
                "label":"#ホロ鯖かくれんぼ",
                "confidence":"explicit-event",
                "event_date":"2026-10-22",
                "start_at":"2026-10-22T10:00:00+00:00",
                "end_at":"2026-10-22T11:15:00+00:00",
                "review_status":"approved",
                "live_scope":True,
                "payload":payload,
            }],
        }

    def test_known_event_renders_canonical_upsert(self):
        doc=self.fixture()
        sql=render_sql(doc)
        self.assertIn("holoserver-hide-and-seek:5680e7ec7c29074a",sql)
        self.assertIn("public_collab_projection_meta",sql)
        self.assertNotIn("shared-topic:7Aq266GeNx8",sql)

    def test_rejected_event_fails_closed(self):
        doc=self.fixture()
        doc["events"][0]["review_status"]="rejected"
        with self.assertRaises(ValueError):
            validate(doc)

    def test_payload_identity_mismatch_fails_closed(self):
        doc=self.fixture()
        doc["events"][0]["payload"]["event_id"]="other:event"
        with self.assertRaises(ValueError):
            validate(doc)

    def test_duplicate_stream_id_fails_closed(self):
        doc=self.fixture()
        doc["events"][0]["payload"]["streams"][1]["video_id"]="89kUA14-sCc"
        with self.assertRaises(ValueError):
            validate(doc)


if __name__=="__main__":
    unittest.main()
