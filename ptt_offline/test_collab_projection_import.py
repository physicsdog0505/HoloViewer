import hashlib
import json
from pathlib import Path
import sqlite3
import unittest

from ptt_offline.collab_projection_import import render_sql, validate


class CollabProjectionImportTests(unittest.TestCase):
    def rehash(self,doc):
        return self.rehash(doc)

    def fixture(self):
        event_id="holoserver-hide-and-seek:5680e7ec7c29074a"
        payload={
            "event_id":event_id,
            "event_key":"holoserver-hide-and-seek",
            "label":"#ホロ鯖かくれんぼ",
            "confidence":"explicit-event",
            "event_date":"2026-10-22",
            "event_start_at":"2026-10-22T10:00:00+00:00",
            "event_end_at":"2026-10-22T11:15:00+00:00",
            "streams":[
                {"video_id":"89kUA14-sCc"},
                {"video_id":"Uy-KPheZe7U"},
                {"video_id":"bB5HkHSQWkI"},
                {"video_id":"ihKbojqvGAk"},
                {"video_id":"mOeNtn8bn3A"},
            ],
        }
        doc={
            "schema_version":"public-collab-projection-v1",
            "projection_key":"live",
            "source_revision":"",
            "generated_at":"2026-10-22T17:00:00+00:00",
            "source_event_count":1,
            "effective_event_count":1,
            "source":{
                "detection_version":"collab-event-v1",
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
        basis={
            "projection_key":doc["projection_key"],
            "range_start":doc["source"]["range_start"],
            "range_end":doc["source"]["range_end"],
            "detection_version":doc["source"]["detection_version"],
            "events":doc["events"],
        }
        canonical=json.dumps(basis,ensure_ascii=False,sort_keys=True,separators=(",",":"))
        doc["source_revision"]="sha256:"+hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return doc

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

    def test_tampered_payload_fails_revision_check(self):
        doc=self.fixture()
        doc["events"][0]["payload"]["streams"][0]["video_id"]="AAAAAAAAAAA"
        with self.assertRaisesRegex(ValueError,"source_revision mismatch"):
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

    def local_db(self):
        db=sqlite3.connect(":memory:")
        schema=Path(__file__).with_name("worker_host").joinpath(
            "today","0006_canonical_collab_projection.PROPOSED.sql"
        ).read_text(encoding="utf-8")
        db.executescript(schema)
        return db

    def test_next_live_projection_clears_prior_day_live_scope_without_retiring_history(self):
        db=self.local_db()
        first=self.fixture()
        db.executescript(render_sql(first))
        before=db.execute(
            "SELECT live_scope,is_current FROM public_collab_events WHERE event_id=?",
            ("holoserver-hide-and-seek:5680e7ec7c29074a",),
        ).fetchone()
        self.assertEqual(before,(1,1))

        next_live=self.fixture()
        next_live["source"]["range_start"]="2026-10-22T16:00:00+00:00"
        next_live["source"]["range_end"]="2026-10-23T16:00:00+00:00"
        next_live["generated_at"]="2026-10-23T17:00:00+00:00"
        next_live["events"]=[]
        next_live["source_event_count"]=0
        next_live["effective_event_count"]=0
        self.rehash(next_live)
        db.executescript(render_sql(next_live))

        after=db.execute(
            "SELECT live_scope,is_current FROM public_collab_events WHERE event_id=?",
            ("holoserver-hide-and-seek:5680e7ec7c29074a",),
        ).fetchone()
        self.assertEqual(after,(0,1))

    def test_history_backfill_cannot_clear_current_live_membership(self):
        db=self.local_db()
        live=self.fixture()
        db.executescript(render_sql(live))

        history=self.fixture()
        history["projection_key"]="history:2026-10-22:2026-10-23"
        history["events"][0]["live_scope"]=False
        self.rehash(history)
        db.executescript(render_sql(history))

        row=db.execute(
            "SELECT live_scope,is_current FROM public_collab_events WHERE event_id=?",
            ("holoserver-hide-and-seek:5680e7ec7c29074a",),
        ).fetchone()
        self.assertEqual(row,(1,1))

    def test_history_projection_claiming_live_scope_fails_closed(self):
        doc=self.fixture()
        doc["projection_key"]="history:2026-10-22:2026-10-23"
        self.rehash(doc)
        with self.assertRaisesRegex(ValueError,"history projection cannot claim live_scope"):
            validate(doc)


if __name__=="__main__":
    unittest.main()
