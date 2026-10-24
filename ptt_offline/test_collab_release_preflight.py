import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ptt_offline.collab_release_preflight import (
    inspect_artifact,
    inspect_import_sql,
    validate_config,
    validate_schema,
)


class CollabReleasePreflightTests(unittest.TestCase):
    def config(self):
        return {
            "name": "holoviewer-public-api",
            "compatibility_date": "2026-10-14",
            "d1_databases": [{
                "binding": "DB",
                "database_name": "holoviewer-public-v1",
                "database_id": "64e1a0ee-1455-4377-9640-3922e8f4d061",
            }],
            "triggers": {"crons": ["* * * * *"]},
            "vars": {
                "ALLOWED_ORIGIN": "https://holoviewer-public.singlebagel.workers.dev,https://holodocchi.com",
                "PTT_PUBLISH_ENABLED": "false",
            },
        }

    def artifact(self):
        event = {
            "event_id": "holoserver-hide-and-seek:5680e7ec7c29074a",
            "event_key": "holoserver-hide-and-seek",
            "label": "#ホロ鯖かくれんぼ",
            "confidence": "explicit-event",
            "event_date": "2026-10-22",
            "event_start_at": "2026-10-22T10:00:00+00:00",
            "event_end_at": "2026-10-22T11:15:00+00:00",
            "streams": [
                {"video_id": "bB5HkHSQWkI"},
                {"video_id": "ihKbojqvGAk"},
            ],
        }
        row = {
            "event_id": event["event_id"],
            "event_key": event["event_key"],
            "label": event["label"],
            "confidence": event["confidence"],
            "event_date": event["event_date"],
            "start_at": event["event_start_at"],
            "end_at": event["event_end_at"],
            "review_status": "approved",
            "live_scope": True,
            "payload": event,
        }
        doc = {
            "schema_version": "public-collab-projection-v1",
            "projection_key": "live",
            "source_revision": "sha256:" + "a" * 64,
            "generated_at": "2026-10-22T17:00:00+00:00",
            "source_event_count": 1,
            "effective_event_count": 1,
            "source": {
                "detection_version": "collab-event-v1",
                "range_start": "2026-10-21T16:00:00+00:00",
                "range_end": "2026-10-22T16:00:00+00:00",
            },
            "events": [row],
        }
        return doc

    def test_config_accepts_expected_production_identity(self):
        receipt = validate_config(self.config())
        self.assertEqual(receipt["worker"], "holoviewer-public-api")
        self.assertEqual(receipt["db_name"], "holoviewer-public-v1")
        self.assertEqual(receipt["compatibility_date"], "2026-10-14")
        self.assertEqual(receipt["cron"], "* * * * *")

    def test_config_rejects_wrong_db_or_cron_or_publish_enable(self):
        for mutate in (
            lambda x: x["d1_databases"][0].update(database_id="wrong"),
            lambda x: x["triggers"].update(crons=["*/5 * * * *"]),
            lambda x: x["vars"].update(PTT_PUBLISH_ENABLED="true"),
        ):
            cfg = self.config()
            mutate(cfg)
            with self.assertRaises(ValueError):
                validate_config(cfg)

    def test_schema_is_additive_only(self):
        schema = Path(__file__).with_name("worker_host").joinpath(
            "today", "0006_canonical_collab_projection.PROPOSED.sql"
        ).read_text(encoding="utf-8")
        receipt = validate_schema(schema)
        self.assertEqual(receipt["tables"], 2)
        self.assertEqual(receipt["indexes"], 3)
        self.assertFalse(receipt["destructive_sql"])

    def test_live_sql_count_formula(self):
        doc = self.artifact()
        art = inspect_artifact(doc)
        sql = """BEGIN TRANSACTION;
UPDATE public_collab_events SET live_scope=0 WHERE is_current=1 AND live_scope=1;
INSERT INTO public_collab_events(event_id) VALUES('x') ON CONFLICT(event_id) DO NOTHING;
INSERT INTO public_collab_projection_meta(projection_key) VALUES('live') ON CONFLICT(projection_key) DO NOTHING;
COMMIT;
"""
        receipt = inspect_import_sql(sql, art["event_count"], art["projection_key"])
        self.assertEqual(receipt["dml_statements"], 3)
        self.assertEqual(receipt["total_statements_including_transaction_markers"], 5)

    def test_rejects_destructive_schema_or_import(self):
        with self.assertRaises(ValueError):
            validate_schema("DROP TABLE public_history;")
        with self.assertRaises(ValueError):
            inspect_import_sql("DELETE FROM public_collab_events;", 0, "live")


if __name__ == "__main__":
    unittest.main()
