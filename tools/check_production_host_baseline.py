#!/usr/bin/env python3
"""Verify #68 inert host proposal against a read-only checkout of current main.

This performs no Cloudflare request and no mutation. It only compares repository
configuration files with the reviewed production-host wiring proposal.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CANONICAL_API = "https://holoviewer-public-api.singlebagel.workers.dev"


def verify(main_root: Path, spec_path: Path) -> dict:
    main_root = main_root.resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    baseline = spec["current_repository_baseline"]

    wrangler_path = main_root / baseline["wrangler_path"]
    wrangler = json.loads(wrangler_path.read_text(encoding="utf-8"))
    if wrangler.get("name") != baseline["worker_name"]:
        raise RuntimeError("main Worker name drift")
    if wrangler.get("compatibility_date") != baseline["compatibility_date"]:
        raise RuntimeError("main compatibility date drift")
    if wrangler.get("assets") != baseline["static_assets"]:
        raise RuntimeError("main static asset config drift")
    forbidden = {"main", "d1_databases", "kv_namespaces", "routes"}
    if forbidden.intersection(wrangler):
        raise RuntimeError("main baseline is no longer static-only")

    deploy = (main_root / baseline["deploy_workflow"]).read_text(encoding="utf-8")
    required_deploy_markers = (
        "workflow_dispatch:",
        "holoviewer-public production Worker",
        "BASELINE-CHECKED",
        "wrangler-action@v4",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
    )
    missing = [marker for marker in required_deploy_markers if marker not in deploy]
    if missing:
        raise RuntimeError("main deploy gate drift: " + ", ".join(missing))

    config_js = (main_root / "site" / "assets" / "config.js").read_text(encoding="utf-8")
    if CANONICAL_API not in config_js:
        raise RuntimeError("main public API origin drift")

    proposed = spec["public_host_worker"]
    if proposed["name"] != wrangler["name"]:
        raise RuntimeError("proposal changes existing Public Worker identity")
    if proposed["d1_bindings"]:
        raise RuntimeError("proposal must not bind D1 on Public host")
    if spec["canonical_api"]["origin"] != CANONICAL_API:
        raise RuntimeError("proposal canonical API origin drift")
    if spec["canonical_api"]["db_binding"]["database_name"] != "holoviewer-public-v1":
        raise RuntimeError("proposal canonical DB identity drift")
    if spec["ptt_product"]["enabled"] is not False:
        raise RuntimeError("normal product PTT must remain disabled")

    return {
        "status": "PASS",
        "main_worker_name": wrangler["name"],
        "main_static_only": True,
        "main_assets": wrangler["assets"],
        "main_api_origin": CANONICAL_API,
        "deploy_manual_gate_markers": len(required_deploy_markers),
        "proposed_python_worker": proposed["main"],
        "proposed_public_host_d1_bindings": len(proposed["d1_bindings"]),
        "production_runtime_contacted": False,
        "production_mutation": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-root", type=Path, required=True)
    parser.add_argument(
        "--spec", type=Path,
        default=Path("platform_adapter/production_host_wiring_spec.json"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.main_root, args.spec)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
