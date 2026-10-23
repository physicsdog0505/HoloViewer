from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts import youtube_static_assets_preview as preview


def encode(payload):
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def entry(path, raw, **extra):
    return {
        "path": path,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        **extra,
    }


def build_tree(root: Path) -> Path:
    v1 = root / "youtube/v1"
    (v1 / "current").mkdir(parents=True)
    (v1 / "archive").mkdir(parents=True)
    (v1 / "index/channels").mkdir(parents=True)

    archive = encode({
        "schema_version": 1,
        "month": "2026-09",
        "videos": [{"video_id": "old"}],
    })
    current = encode({
        "schema_version": 1,
        "month": "2026-10",
        "videos": [{"video_id": "new"}],
    })
    index = encode({
        "schema_version": 1,
        "channel_id": "UCfixture",
        "months": {"2026-09": ["old"], "2026-10": ["new"]},
    })

    (v1 / "archive/2026-09.json").write_bytes(archive)
    (v1 / "current/2026-10.json").write_bytes(current)
    (v1 / "index/channels/UCfixture.json").write_bytes(index)

    manifest = {
        "schema_version": 1,
        "current_month": "2026-10",
        "months": [
            entry("youtube/v1/archive/2026-09.json", archive, count=1),
            entry("youtube/v1/current/2026-10.json", current, count=1),
        ],
        "channel_indexes": [
            entry(
                "youtube/v1/index/channels/UCfixture.json",
                index,
                channel_id="UCfixture",
                video_count=2,
            )
        ],
        "channel_index": "youtube/v1/index/channels/<channel_id>.json",
    }
    (v1 / "manifest.json").write_bytes(encode(manifest))
    return v1


class Response:
    def __init__(self, raw):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.raw


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.v1 = build_tree(self.root / "source")
        self.site = self.root / "site"
        self.site.mkdir()
        (self.site / "index.html").write_text("<html>fixture</html>")

    def tearDown(self):
        self.temp.cleanup()

    def test_local_tree_contract(self):
        result = preview.verify_local_tree(self.v1)
        self.assertEqual("PASS", result["local_readback"])
        self.assertEqual(2, result["months"])
        self.assertEqual(1, result["channel_indexes"])
        self.assertEqual(2, result["videos"])

    def test_stage_site_preserves_existing_site_and_adds_youtube_tree(self):
        target = self.root / "staged"
        result = preview.stage_site(self.site, self.v1, target)

        self.assertEqual("PASS", result["local_readback"])
        self.assertEqual("<html>fixture</html>", (target / "index.html").read_text())
        self.assertEqual(
            (self.v1 / "manifest.json").read_bytes(),
            (target / "youtube/v1/manifest.json").read_bytes(),
        )

    def test_write_preview_config_preserves_real_worker_shape(self):
        source_config = self.root / "wrangler.json"
        payload = {
            "name": "holoviewer-public",
            "compatibility_date": "2026-10-16",
            "workers_dev": True,
            "routes": [{"pattern": "holodocchi.com", "custom_domain": True}],
            "assets": {
                "directory": "../site",
                "not_found_handling": "single-page-application",
            },
        }
        source_config.write_text(json.dumps(payload))
        output = self.root / "preview-wrangler.json"
        staged = self.root / "staged-site"
        staged.mkdir()

        result = preview.write_preview_config(
            source_config, output, staged
        )

        self.assertEqual("holoviewer-public", result["name"])
        self.assertEqual(payload["routes"], result["routes"])
        self.assertTrue(result["workers_dev"])
        self.assertEqual(str(staged.resolve()), result["assets"]["directory"])
        self.assertEqual(
            "single-page-application",
            result["assets"]["not_found_handling"],
        )

    def test_http_readback_verifies_all_declared_objects(self):
        objects = {}
        for path in self.v1.rglob("*.json"):
            logical = "youtube/v1/" + path.relative_to(self.v1).as_posix()
            objects[logical] = path.read_bytes()
        requested = []

        def opener(request, timeout):
            url = request.full_url
            requested.append(url)
            path = url.split("https://preview.example/", 1)[1].split("?", 1)[0]
            return Response(objects[path])

        result = preview.verify_http_tree(
            "https://preview.example",
            self.v1,
            nonce="fixture",
            opener=opener,
        )

        self.assertEqual("PASS", result["manifest_http_readback"])
        self.assertEqual("PASS", result["month_objects_http_readback"])
        self.assertEqual("PASS", result["channel_index_http_readback"])
        self.assertEqual(4, len(requested))
        self.assertTrue(all("issue448=fixture" in url for url in requested))

    def test_http_readback_rejects_wrong_index_channel(self):
        objects = {}
        for path in self.v1.rglob("*.json"):
            logical = "youtube/v1/" + path.relative_to(self.v1).as_posix()
            objects[logical] = path.read_bytes()

        index_key = "youtube/v1/index/channels/UCfixture.json"
        bad = encode({
            "schema_version": 1,
            "channel_id": "UCwrong",
            "months": {"2026-09": ["old"], "2026-10": ["new"]},
        })
        objects[index_key] = bad

        # Update manifest bytes/hash so this specifically exercises semantic
        # channel_id enforcement rather than digest enforcement.
        manifest = json.loads(objects["youtube/v1/manifest.json"])
        item = manifest["channel_indexes"][0]
        item["bytes"] = len(bad)
        item["sha256"] = hashlib.sha256(bad).hexdigest()
        objects["youtube/v1/manifest.json"] = encode(manifest)

        local_manifest = self.v1 / "manifest.json"
        local_manifest.write_bytes(objects["youtube/v1/manifest.json"])

        def opener(request, timeout):
            path = request.full_url.split(
                "https://preview.example/", 1
            )[1].split("?", 1)[0]
            return Response(objects[path])

        with self.assertRaisesRegex(preview.PreviewError, "channel_id mismatch"):
            preview.verify_http_tree(
                "https://preview.example",
                self.v1,
                opener=opener,
            )

    def test_local_tree_rejects_undeclared_channel_index(self):
        extra = self.v1 / "index/channels/UCextra.json"
        shutil.copyfile(
            self.v1 / "index/channels/UCfixture.json",
            extra,
        )
        with self.assertRaisesRegex(
            preview.PreviewError, "channel index inventory mismatch"
        ):
            preview.verify_local_tree(self.v1)


if __name__ == "__main__":
    unittest.main()
