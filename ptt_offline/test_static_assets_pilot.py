import gzip
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from ptt_offline.r2_archive_export import write_archive_rows
from ptt_offline.public_today_contract import ContractError
from ptt_offline.static_assets_pilot import (build_static_bundle,
    enrich_archive_floors, resolve_vod)


class _AssetHandler(SimpleHTTPRequestHandler):
    def guess_type(self,path):
        if path.endswith(".json.gz"):
            return "application/json"
        return super().guess_type(path)

    def end_headers(self):
        if self.path.endswith(".json.gz"):
            self.send_header("Content-Encoding","gzip")
            self.send_header("Cache-Control","public, max-age=0, must-revalidate")
        elif "/manifests/" in self.path:
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Cache-Control","no-cache")
        self.send_header("Access-Control-Allow-Origin","*")
        super().end_headers()

    def log_message(self,*_):
        pass


class StaticAssetsPilotTests(unittest.TestCase):
    def make_archive(self,root: Path):
        rows=[]
        for line,occurred,day,status,aid in [
            (10,"2026-10-01T23:59:00Z","2026-10-02","COMPLETE","A"),
            (30,"2026-10-02T00:00:00Z","2026-10-02","COMPLETE","A"),
            (50,"2026-10-02T01:01:00Z","2026-10-02","COMPLETE","B"),
            (70,"2026-10-02T16:01:00Z","2026-10-03","PARTIAL","B"),
        ]:
            rows.append({"occurred_at":occurred,"aid":aid,"source_line":line,
                "source_page":1,"kind":"push","author":"u","content":f"m{line}",
                "source_url":"https://example.invalid","source_path":"fixture",
                "source_record_key":f"{aid}:{line}","coverage_day":day,
                "time_quality":"source-minute","floor":{10:1,30:2,50:1,70:2}[line],
                "floor_quality":"per-thread-ordinal"})
        days=[
            {"day":"2026-10-02","coverage_status":"COMPLETE","finalized":True,"reason":"fixture"},
            {"day":"2026-10-03","coverage_status":"PARTIAL","finalized":False,"reason":"fixture"},
        ]
        return write_archive_rows(rows,from_day="2026-10-02",through_day="2026-10-03",
            out_dir=root,days=days,manifest_name="2026-10-pilot.json",
            generated_at="2026-10-03T00:00:00Z")

    def make_floor_source(self,path: Path,aid: str,lines: list[int]):
        db=sqlite3.connect(path)
        db.executescript("""
        CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT);
        CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER,source_line INTEGER,source_page INTEGER);
        CREATE TABLE article_screens(id INTEGER PRIMARY KEY,article_id INTEGER,start_line INTEGER);
        """)
        db.execute("INSERT INTO articles VALUES(1,'C_Chat',?)",(aid,))
        db.execute("INSERT INTO article_screens VALUES(1,1,1)")
        db.executemany("INSERT INTO pushes VALUES(?,1,?,1)",enumerate(lines,start=1))
        db.commit()
        db.close()

    def test_bundle_has_asset_only_config_headers_and_verified_subset(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            source=base/"source"
            manifest=self.make_archive(source)
            public=base/"package/public"
            keys=[item["key"] for item in manifest["objects"][:3]]
            receipt=build_static_bundle(archive_root=source,out_dir=public,object_keys=keys)
            config=json.loads((base/"package/wrangler.jsonc").read_text())
            self.assertNotIn("main",config)
            self.assertNotIn("bindings",json.dumps(config))
            self.assertEqual(receipt["worker_code"],False)
            self.assertEqual(receipt["d1_bindings"],0)
            pilot=json.loads(Path(receipt["manifest"]).read_text())
            self.assertEqual([item["key"] for item in pilot["objects"]],keys)
            self.assertEqual(pilot["source_manifest_sha256"],sha256(
                (source/"ptt/v1/manifests/2026-10-pilot.json").read_bytes()).hexdigest())
            headers=(public/"_headers").read_text()
            self.assertIn("Content-Encoding: gzip",headers)
            self.assertIn("must-revalidate",headers)
            self.assertIn("Cache-Control: no-cache",headers)

    def test_http_headers_and_gzip_json_readback(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            manifest=self.make_archive(root)
            handler=lambda *args,**kwargs:_AssetHandler(*args,directory=str(root),**kwargs)
            server=ThreadingHTTPServer(("127.0.0.1",0),handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                key=manifest["objects"][0]["key"]
                with urlopen(f"http://127.0.0.1:{server.server_port}/{key}") as response:
                    self.assertEqual(response.headers.get_content_type(),"application/json")
                    self.assertEqual(response.headers["Content-Encoding"],"gzip")
                    self.assertEqual(response.headers["Access-Control-Allow-Origin"],"*")
                    payload=json.loads(gzip.decompress(response.read()))
                self.assertGreater(len(payload["pushes"]),0)
            finally:
                server.shutdown()
                thread.join()
                server.server_close()

    def test_resolver_maps_cross_hour_and_utc_date_without_duplicates(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.make_archive(root)
            result=resolve_vod(archive_root=root,
                manifest_path=root/"ptt/v1/manifests/2026-10-pilot.json",
                actual_start="2026-10-01T23:58:30Z",actual_end="2026-10-02T01:02:00Z",
                anchor_source="youtube-liveStreamingDetails-actualStartTime")
            self.assertTrue(result["strict_complete"])
            self.assertEqual(result["push_count"],3)
            self.assertEqual([row["vod_minute"] for row in result["pushes"]],[0,1,62])
            self.assertEqual(result["duplicate_source_record_keys"],[])
            self.assertEqual(len(result["object_keys"]),3)

    def test_partial_day_never_claims_strict_complete(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.make_archive(root)
            result=resolve_vod(archive_root=root,
                manifest_path=root/"ptt/v1/manifests/2026-10-pilot.json",
                actual_start="2026-10-02T23:59:00Z",actual_end="2026-10-03T00:02:00Z",
                anchor_source="youtube-liveStreamingDetails-actualStartTime")
            self.assertEqual(result["coverage_status"],"PARTIAL")
            self.assertFalse(result["strict_complete"])

    def test_resolver_rejects_untrusted_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.make_archive(root)
            with self.assertRaisesRegex(ContractError,"authoritative YouTube actualStartTime"):
                resolve_vod(archive_root=root,
                    manifest_path=root/"ptt/v1/manifests/2026-10-pilot.json",
                    actual_start="2026-10-01T23:58:30Z",
                    actual_end="2026-10-02T01:02:00Z",
                    anchor_source="scheduledStartTime")

    def test_floor_enrichment_preserves_fixed_identity_set_and_uses_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            source=base/"archive"
            self.make_archive(source)
            # Remove fixture floors to model the original PR #135 archive.
            for path in (source/"ptt/v1/chunks").rglob("*.json.gz"):
                with gzip.open(path,"rt",encoding="utf-8") as handle:
                    payload=json.load(handle)
                for row in payload["pushes"]:
                    row.pop("floor",None)
                    row.pop("floor_quality",None)
                    row["source_path"]=("/tmp/issue403_missing.sqlite3"
                                        if row["aid"]=="A" else "/tmp/operational.sqlite3")
                raw=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode()
                with path.open("wb") as output:
                    with gzip.GzipFile(filename="",mode="wb",fileobj=output,mtime=0) as handle:
                        handle.write(raw)
            # Refresh source manifest hashes after modeling the old archive.
            manifest_path=source/"ptt/v1/manifests/2026-10-pilot.json"
            manifest=json.loads(manifest_path.read_text())
            for item in manifest["objects"]:
                with gzip.open(source/item["key"],"rb") as handle:
                    raw=handle.read()
                item["sha256"]=sha256(raw).hexdigest()
                item["bytes_gzip"]=(source/item["key"]).stat().st_size
            manifest_path.write_text(json.dumps(manifest))
            backfill=base/"backfill.sqlite3"
            operational=base/"operational.sqlite3"
            self.make_floor_source(backfill,"A",[10,30])
            self.make_floor_source(operational,"B",[50,70])
            audit=enrich_archive_floors(archive_root=source,out_dir=base/"output",
                                        source_paths=[backfill,operational])
            self.assertEqual(audit["status"],"PASS")
            self.assertEqual(audit["floor_unknown_rows"],0)
            self.assertTrue(audit["identity_set_preserved"])
            self.assertEqual(audit["duplicate_aid_floors"],0)


if __name__=="__main__":
    unittest.main()
