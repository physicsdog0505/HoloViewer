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
    validate_frontend_candidate_ownership,
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

    def test_frontend_candidate_rejects_youtube_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            site = Path(temp)
            target = site / "youtube/v1/current/2026-10.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}")
            with self.assertRaisesRegex(AliasReleaseGateError, "foreign-owner Static Assets"):
                validate_frontend_candidate_ownership(site)

    def test_frontend_candidate_rejects_ptt_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            site = Path(temp)
            target = site / "ptt/v1/manifests/static-assets-full-2026-10.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}")
            with self.assertRaisesRegex(AliasReleaseGateError, "foreign-owner Static Assets"):
                validate_frontend_candidate_ownership(site)

    def test_frontend_candidate_allows_frontend_and_alias_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            site = Path(temp)
            (site / "assets").mkdir(parents=True)
            (site / "assets/app.js").write_text("ok")
            (site / "data/search/aliases/v1").mkdir(parents=True)
            (site / "data/search/aliases/v1/latest.json").write_text("{}")
            result = validate_frontend_candidate_ownership(site)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["forbidden_foreign_owner_asset_count"], 0)


if __name__ == "__main__":
    unittest.main()
