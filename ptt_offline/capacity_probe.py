"""Offline SQLite-compatible D1 storage budget experiment for #48.

1000 generated representative-format records are CAPACITY LOAD ONLY, never
presented as true PTT evidence or accepted for product data tests. No network.
"""
import json
import sqlite3
import tempfile
from pathlib import Path
from .d1_publisher import UPSERT_PUSH

SQL=Path(__file__).with_name("d1_migrations")/"0001_canonical_ptt.sql"
FREE_DB_BYTES=500_000_000
HEADROOM_BYTES=400_000_000

def probe(*,count=1000):
    if type(count) is not int or not 1<=count<=10000:
        raise ValueError("capacity test record cap exceeded")
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/"capacity.sqlite3"
        db=sqlite3.connect(path)
        try:
            db.executescript(SQL.read_text())
            def storage():
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                return (db.execute("PRAGMA page_count").fetchone()[0]*
                        db.execute("PRAGMA page_size").fetchone()[0])
            before=storage()
            db.execute("INSERT INTO ptt_threads(day,aid,source_url) VALUES (?,?,?)",
                       ("2026-10-15","1gepPtNy","https://www.ptt.cc/bbs/C_Chat/M.1789081207.A.5FC.html"))
            for line in range(1,count+1):
                push_id="ptt:v1:"+format(line,"064x")
                source_key=f"1gepPtNy:{line}"
                db.execute(UPSERT_PUSH,(push_id,"1gepPtNy","2026-10-15",line,
                    "推","sampleuser",f"capacity-only 中文與English message {line:06d}",
                    "2026-10-15T10:00:00Z",None,
                    "https://www.ptt.cc/bbs/C_Chat/M.1789081207.A.5FC.html",
                    10,source_key))
                db.execute("INSERT INTO ptt_source_evidence(day,aid,source_record_key,push_id,source_line) VALUES (?,?,?,?,?)",
                    ("2026-10-15","1gepPtNy",source_key,push_id,line))
            db.commit()
            after=storage()
            delta=after-before
            return {"mode":"SYNTHETIC_CAPACITY_ONLY","rows":count,
                    "page_count_bytes_before":before,
                    "page_count_bytes_after":after,
                    "net_allocated_bytes":delta,
                    "bytes_per_1000_rows":round(delta*1000/count),
                    "free_database_limit_bytes":FREE_DB_BYTES,
                    "headroom_budget_bytes":HEADROOM_BYTES,
                    "real_data_acceptance":False}
        finally:
            db.close()

if __name__=="__main__":
    print(json.dumps(probe(),sort_keys=True,indent=2))
