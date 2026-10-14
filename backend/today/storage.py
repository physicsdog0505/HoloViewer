"""Offline SQLite D1-analog writer for migration and replay tests only.

Not a production D1 connector. D1 SQL migration is separately reviewed.
"""
import sqlite3
from .engine import apply_observation, utc
import json

def init_offline(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS today_observations (
      video_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, observed_at TEXT NOT NULL,
      lifecycle_state TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS today_run_ledger (
      run_id TEXT PRIMARY KEY, attempted_at TEXT NOT NULL, outcome TEXT NOT NULL);
    """)

def write_offline(conn, record):
    video_id = record["video_id"]
    with conn:
        row = conn.execute("SELECT payload FROM today_observations WHERE video_id=?", (video_id,)).fetchone()
        selected = apply_observation(json.loads(row[0]) if row else None, record)
        if row and json.loads(row[0]) == selected:
            return False
        conn.execute("""INSERT INTO today_observations(video_id,channel_id,observed_at,lifecycle_state,payload)
            VALUES (?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET channel_id=excluded.channel_id,
            observed_at=excluded.observed_at,lifecycle_state=excluded.lifecycle_state,payload=excluded.payload""",
            (video_id, selected["channel_id"], selected["observed_at"],
             selected["lifecycle_state"], json.dumps(selected, sort_keys=True)))
        return True
