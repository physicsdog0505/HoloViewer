from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.alias_static_assets_release_gate import (
    AliasReleaseGateError,
    validate_alias_contract,
    validate_alias_site_delta,
    verify_declared_bytes,
    youtube_manifest_paths,
)


SHA = "a" * 64


class AliasStaticAssetsReleaseGateTests(unittest.TestCase):
    def test_alias_delta_allows_pointer_plus_one_new_immutable(self):
        result = validate_alias_site_delta([
            "M\tsite/data/search/aliases/v1/latest.json",
            f"A\tsite/data/search/aliases/v1/versions/{SHA}.json",
        ])
        self.assertEqual(result["immutable_sha256"], SHA)

    def test_alias_delta_rejects_unrelated_site_change(self):
        with self.assertRaises(AliasReleaseGateError):
            validate_alias_site_delta([
                "M\tsite/data/search/aliases/v1/latest.json",
                f"A\tsite/data/search/aliases/v1/versions/{SHA}.json",
                "M\tsite/assets/app.js",
            ])

    def test_alias_delta_rejects_mutating_immutable_object(self):
        with self.assertRaises(AliasReleaseGateError):
            validate_alias_site_delta([
                "M\tsite/data/search/aliases/v1/latest.json",
                f"M\tsite/data/search/aliases/v1/versions/{SHA}.json",
            ])

    def test_contract_verifies_exact_immutable_sha_and_public_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            site = Path(temp)
            payload = {
                "schema_version": 1,
                "dataset": "holodocchi-member-aliases-public-v1",
                "members": [{
                    "channel_id": "UC_test",
                    "canonical_name": "Test",
                    "status": "active",
                    "searchable": True,
                    "aliases": [{
                        "value": "Test",
                        "normalized_value": "test",
                        "strength": "strong",
                        "enabled": True,
                    }],
                }],
            }
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            digest = hashlib.sha256(raw).hexdigest()
            base = site / "data/search/aliases/v1"
            (base / "versions").mkdir(parents=True)
            (base / "versions" / f"{digest}.json").write_bytes(raw)
            (base / "latest.json").write_text(json.dumps({
                "schema_version": 1,
                "dataset": "holodocchi-member-aliases-public-v1",
                "sha256": digest,
                "asset_path": f"/data/search/aliases/v1/versions/{digest}.json",
            }))
            result = validate_alias_contract(site)
            self.assertEqual(result["sha256"], digest)
            self.assertEqual(result["member_count"], 1)
            self.assertEqual(result["alias_count"], 1)

    def test_contract_rejects_private_note_field(self):
        with tempfile.TemporaryDirectory() as temp:
            site = Path(temp)
            payload = {
                "schema_version": 1,
                "dataset": "holodocchi-member-aliases-public-v1",
                "members": [{
                    "channel_id": "UC_test",
                    "canonical_name": "Test",
                    "status": "active",
                    "searchable": True,
                    "aliases": [{
                        "value": "Test",
                        "normalized_value": "test",
                        "strength": "strong",
                        "enabled": True,
                        "note": "must stay private",
                    }],
                }],
            }
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            digest = hashlib.sha256(raw).hexdigest()
            base = site / "data/search/aliases/v1"
            (base / "versions").mkdir(parents=True)
            (base / "versions" / f"{digest}.json").write_bytes(raw)
            (base / "latest.json").write_text(json.dumps({
                "schema_version": 1,
                "dataset": "holodocchi-member-aliases-public-v1",
                "sha256": digest,
                "asset_path": f"/data/search/aliases/v1/versions/{digest}.json",
            }))
            with self.assertRaises(AliasReleaseGateError):
                validate_alias_contract(site)

    def test_contract_rejects_duplicate_channel_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            site = Path(temp)
            member = {
                "channel_id": "UC_shared",
                "canonical_name": "Shared",
                "status": "active",
                "searchable": True,
                "aliases": [],
            }
            payload = {
                "schema_version": 1,
                "dataset": "holodocchi-member-aliases-public-v1",
                "members": [member, dict(member)],
            }
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            digest = hashlib.sha256(raw).hexdigest()
            base = site / "data/search/aliases/v1"
            (base / "versions").mkdir(parents=True)
            (base / "versions" / f"{digest}.json").write_bytes(raw)
            (base / "latest.json").write_text(json.dumps({
                "schema_version": 1,
                "dataset": "holodocchi-member-aliases-public-v1",
                "sha256": digest,
                "asset_path": f"/data/search/aliases/v1/versions/{digest}.json",
            }))
            with self.assertRaisesRegex(AliasReleaseGateError, "duplicate channel_id"):
                validate_alias_contract(site)

    def test_youtube_manifest_inventory_is_bounded_to_declared_prefix(self):
        entries = youtube_manifest_paths({
            "schema_version": 1,
            "months": [{"path": "youtube/v1/current/2026-10.json", "bytes": 3, "sha256": SHA}],
            "channel_indexes": [{"path": "youtube/v1/index/channels/UC.json", "bytes": 4, "sha256": "b" * 64}],
        })
        self.assertEqual(len(entries), 2)

    def test_youtube_manifest_rejects_path_escape_or_wrong_prefix(self):
        for bad in ("../secret", "site/assets/app.js", "/youtube/v1/manifest.json"):
            with self.subTest(bad=bad):
                with self.assertRaises(AliasReleaseGateError):
                    youtube_manifest_paths({
                        "schema_version": 1,
                        "months": [{"path": bad, "bytes": 1, "sha256": SHA}],
                        "channel_indexes": [],
                    })

    def test_declared_youtube_bytes_must_match_hash_and_length(self):
        data = b"abc"
        entry = {
            "path": "youtube/v1/current/2026-10.json",
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        verify_declared_bytes(data, entry)
        with self.assertRaises(AliasReleaseGateError):
            verify_declared_bytes(b"abd", entry)


if __name__ == "__main__":
    unittest.main()
