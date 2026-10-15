#!/usr/bin/env python3
"""Enable a local-only canonical-consumer fixture in a disposable Worker bundle.

This never edits the accepted vendor source or the production Worker entrypoint.
Only the generated Worker test folder is adjusted. Do not deploy fixture mode.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PINNED = "a144bb378a8bdd772faa867d608c1e7491253883"


def enable_fixture(bundle: Path) -> None:
    bundle = bundle.resolve()
    receipt_path = bundle / "bundle-provenance.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("pinned_source") != PINNED or receipt.get("deployed") is not False:
        raise RuntimeError("Only an isolated pinned source-only bundle may use fixtures")
    config_path = bundle / "wrangler.jsonc"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("main") != "entry.py":
        raise RuntimeError("Cannot enable fixture on an already modified Worker bundle")

    fixture = '''"""LOCAL PROOF ONLY: fixture data at canonical transport seam."""
import platform_adapter.cloudflare_entry as worker
from platform_adapter.public_api import DEFAULT_API, PublicAPIUnavailable


async def fixture_public_json(url):
    if url == DEFAULT_API + "/v1/catalog/today":
        return {"freshness": {"status": "unknown"}, "streams": []}
    if url.startswith(DEFAULT_API + "/v1/history?"):
        return {"items": [], "has_more": False}
    raise PublicAPIUnavailable("No fixture for this canonical route")


worker.fetch_canonical_json = fixture_public_json

# Local fixture proof only: verify Pyodide can read the *original* packaged
# accepted 4174 static files. This endpoint never enters production source.
from workers import Response
from pathlib import Path
import hashlib
import json

class Default(worker.Default):
    async def fetch(self, request):
        if str(request.url).split("?", 1)[0].endswith("/__local_proof_assets"):
            names = (
                "public/ptt_timeline.js",
                "public/ptt_player_adapter.js",
                "public/ptt_worker_adapter.js",
                "hololive_channels.prototype.json",
            )
            root = Path(__file__).resolve().parent
            payload = {}
            for name in names:
                data = (root / name).read_bytes()
                payload[name] = hashlib.sha256(data).hexdigest()
            return Response(json.dumps(payload), headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            })
        return await super().fetch(request)
'''
    (bundle / "entry_fixture.py").write_text(fixture, encoding="utf-8")
    config["main"] = "entry_fixture.py"
    # Cloudflare Workers static-asset binding in the SAME local Worker.
    # Static requests must bypass the Python ClientRequestHandler altogether.
    config["assets"] = {
        "directory": "./public",
        "binding": "ASSETS",
        "run_worker_first": False,
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    receipt["local_fixture_only"] = True
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    args = parser.parse_args()
    enable_fixture(args.bundle)
