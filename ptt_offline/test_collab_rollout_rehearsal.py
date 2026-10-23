import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ptt_offline.collab_rollout_rehearsal import run_rehearsal


class CollabRolloutRehearsalTests(unittest.TestCase):
    def artifact(self):
        event={
            "event_id":"holoserver-hide-and-seek:5680e7ec7c29074a",
            "event_key":"holoserver-hide-and-seek",
            "label":"#ホロ鯖かくれんぼ",
            "confidence":"explicit-event",
            "event_date":"2026-10-22",
            "event_start_at":"2026-10-22T10:00:00+00:00",
            "event_end_at":"2026-10-22T11:15:00+00:00",
            "participant_count":2,
            "pov_count":2,
            "streams":[
                {"video_id":"bB5HkHSQWkI"},
                {"video_id":"ihKbojqvGAk"},
            ],
        }
        row={
            "event_id":event["event_id"],
            "event_key":event["event_key"],
            "label":event["label"],
            "confidence":event["confidence"],
            "event_date":event["event_date"],
            "start_at":event["event_start_at"],
            "end_at":event["event_end_at"],
            "review_status":"approved",
            "live_scope":True,
            "payload":event,
        }
        doc={
            "schema_version":"public-collab-projection-v1",
            "projection_key":"live",
            "source_revision":"",
            "generated_at":"2026-10-22T17:00:00+00:00",
            "source_event_count":1,
            "effective_event_count":1,
            "source":{
                "store_schema":"collab-event-store-v2",
                "detection_version":"collab-event-v1",
                "range_start":"2026-10-21T16:00:00+00:00",
                "range_end":"2026-10-22T16:00:00+00:00",
            },
            "events":[row],
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

    def test_one_event_live_rehearsal_is_idempotent_and_cross_day_safe(self):
        schema=Path(__file__).with_name("worker_host").joinpath(
            "today","0006_canonical_collab_projection.PROPOSED.sql"
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact=Path(tmp)/"artifact.json"
            artifact.write_text(json.dumps(self.artifact()),encoding="utf-8")
            receipt=run_rehearsal(schema,artifact)

        self.assertTrue(receipt["pass"])
        self.assertEqual(receipt["artifact_event_count"],1)
        self.assertEqual(receipt["initial_current_event_rows"],1)
        self.assertEqual(receipt["initial_live_rows"],1)
        self.assertEqual(receipt["projection_meta_rows"],1)
        self.assertTrue(receipt["idempotent_replay"])
        self.assertEqual(receipt["sql_statement_count_including_begin_commit"],5)
        self.assertEqual(receipt["sql_dml_statement_count"],3)
        self.assertEqual(receipt["expected_dml_formula"],3)
        self.assertEqual(
            receipt["cross_day_live_replacement"],
            {"next_live_rows":0,"history_rows_preserved":1,"pass":True},
        )
        self.assertFalse(receipt["cloudflare_called"])
        self.assertFalse(receipt["production_mutated"])


if __name__=="__main__":
    unittest.main()
