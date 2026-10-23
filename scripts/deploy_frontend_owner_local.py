#!/usr/bin/env python3
"""Issue #201 Owner-local frontend release entrypoint.

Production mutation is intentionally performed only from the Owner's local checkout.
GitHub Actions may provide passive evidence but must never call this mutation path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from frontend_release_gate import (
    ReleaseGateError,
    bounded_retry,
    validate_site_delta,
    validate_watchalong_addition,
    verify_lineage,
)

CUSTOM_ORIGIN = "https://holodocchi.com"
WORKERS_ORIGIN = "https://holoviewer-public.singlebagel.workers.dev"
WORKER_NAME = "holoviewer-public"
WRANGLER_CONFIG = "cloudflare/wrangler.json"
DEFAULT_SOURCE_ROOT = "/Users/hsuhsunshun/Downloads/Hololive-PTT-Viewer"


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    return result.stdout.strip() if capture else ""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "HoloViewer-owner-local-release"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def active_version() -> str:
    output = run(
        "npx", "--yes", "wrangler", "deployments", "status",
        "--config", WRANGLER_CONFIG, "--name", WORKER_NAME,
        capture=True,
    )
    print(output)
    for line in output.splitlines():
        if "Version(s):" in line:
            parts = line.split()
            if parts:
                return parts[-1]
    raise ReleaseGateError("unable to determine active Worker version")


def readback_once(origin: str, target: str, expected_manifest: str, expected_event: str) -> bool:
    nonce = f"{int(time.time())}-{os.getpid()}"
    manifest_raw = fetch_bytes(f"{origin}/data/watchalong/manifest.json?release={nonce}")
    event_raw = fetch_bytes(f"{origin}/data/watchalong/events/{target}.json?release={nonce}")
    viewer_raw = fetch_bytes(f"{origin}/watchalong-viewer/?watchalong_event={target}&release={nonce}")
    if hashlib.sha256(manifest_raw).hexdigest() != expected_manifest:
        return False
    if hashlib.sha256(event_raw).hexdigest() != expected_event:
        return False
    if b"/assets/watchalong-standalone.js" not in viewer_raw:
        return False
    payload = json.loads(manifest_raw)
    return any(
        row.get("event_id") == target
        for row in payload.get("events", [])
        if isinstance(row, dict)
    )


def deploy_data_watchalong(target: str, expected_main: str) -> None:
    repo = Path(__file__).resolve().parents[1]
    os.chdir(repo)

    print("=== ISSUE #201 OWNER-LOCAL DATA-WATCHALONG RELEASE ===")
    run("git", "fetch", "origin", "main")
    head = run("git", "rev-parse", "HEAD", capture=True)
    origin_main = run("git", "rev-parse", "origin/main", capture=True)
    verify_lineage(head, origin_main, expected_main)

    if run("git", "status", "--porcelain", "--untracked-files=all", capture=True):
        raise ReleaseGateError("dirty checkout; clean or commit local changes before deploy")

    source_root = os.environ.get("HOLOVIEWER_SOURCE_ROOT", DEFAULT_SOURCE_ROOT)
    run(
        sys.executable,
        "scripts/export_watchalong_assets.py",
        "--source-root", source_root,
        "--output-root", "site/data/watchalong",
        "--check",
    )
    run(
        sys.executable, "-B", "-m", "unittest", "-v",
        "test_watchalong_assets",
        "test_public_smoke",
        "test_viewing_timeline_core",
        "test_viewing_timeline_viewer_integration",
        "test_frontend_release_gate",
    )
    run("node", "--check", "site/assets/watchalong-standalone.js")

    event_path = Path(f"site/data/watchalong/events/{target}.json")
    manifest_path = Path("site/data/watchalong/manifest.json")
    if not event_path.is_file() or not manifest_path.is_file():
        raise ReleaseGateError("candidate Watchalong assets are missing")

    intro = run(
        "git", "log", "--diff-filter=A", "--format=%H", "--", str(event_path),
        capture=True,
    ).splitlines()
    if len(intro) != 1:
        raise ReleaseGateError("unable to identify exactly one target introduction commit")
    intro_commit = intro[0]
    base = run("git", "rev-parse", f"{intro_commit}^", capture=True)
    delta = run(
        "git", "diff", "--name-status", f"{base}..{expected_main}", "--", "site",
        capture=True,
    ).splitlines()
    validate_site_delta(delta, target)

    candidate_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    event_sha = sha256(event_path)
    manifest_sha = sha256(manifest_path)

    with tempfile.TemporaryDirectory(prefix="holoviewer-release-") as tmp:
        tmpdir = Path(tmp)
        baseline_raw = fetch_bytes(
            f"{CUSTOM_ORIGIN}/data/watchalong/manifest.json?predeploy={int(time.time())}"
        )
        baseline_path = tmpdir / "manifest-before.json"
        baseline_path.write_bytes(baseline_raw)
        production_manifest = json.loads(baseline_raw)
        preservation = validate_watchalong_addition(
            production_manifest, candidate_manifest, target
        )
        baseline_manifest_sha = hashlib.sha256(baseline_raw).hexdigest()
        baseline_version = active_version()

        backup_root = Path.home() / "Downloads" / "HoloViewer-deploy-backups"
        backup_dir = backup_root / f"issue201-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{baseline_version}"
        backup_dir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(baseline_path, backup_dir / "manifest-before.json")
        shutil.copy2(WRANGLER_CONFIG, backup_dir / "wrangler.json")
        (backup_dir / "release-receipt-before.json").write_text(
            json.dumps(
                {
                    "SOURCE_MAIN_SHA": expected_main,
                    "BASELINE_VERSION": baseline_version,
                    "MANIFEST_BEFORE_SHA": baseline_manifest_sha,
                    "MANIFEST_AFTER_EXPECTED_SHA": manifest_sha,
                    "NEW_EVENT": target,
                    "NEW_EVENT_SHA": event_sha,
                    **preservation,
                },
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )

        print("ALL_PREDEPLOY_GATES=PASS")
        print("PRODUCTION_MUTATION_STARTS_NOW")
        run(
            "npx", "--yes", "wrangler", "deploy",
            "--config", WRANGLER_CONFIG, "--name", WORKER_NAME,
        )
        new_version = active_version()
        if new_version == baseline_version:
            raise ReleaseGateError("Cloudflare did not activate a new version")

        origins = (("CUSTOM", CUSTOM_ORIGIN), ("WORKERS", WORKERS_ORIGIN))
        attempts: dict[str, int] = {}
        for label, origin in origins:
            attempts[label] = bounded_retry(
                lambda origin=origin: readback_once(
                    origin, target, manifest_sha, event_sha
                )
            )
            print(f"{label}_READBACK=PASS attempt={attempts[label]}")

        final_raw = fetch_bytes(
            f"{CUSTOM_ORIGIN}/data/watchalong/manifest.json?final={int(time.time())}"
        )
        final_manifest = json.loads(final_raw)
        final_sha = hashlib.sha256(final_raw).hexdigest()
        if final_sha != manifest_sha:
            raise ReleaseGateError("final custom-domain manifest hash mismatch")

        # Re-run preservation against the final bytes with the target removed as baseline truth.
        final_events = {
            row.get("event_id"): row
            for row in final_manifest.get("events", [])
            if isinstance(row, dict)
        }
        for old in production_manifest.get("events", []):
            old_id = old.get("event_id")
            if old_id not in final_events or final_events[old_id].get("sha256") != old.get("sha256"):
                raise ReleaseGateError(f"post-deploy existing event changed: {old_id}")

        receipt = {
            "SOURCE_MAIN_SHA": expected_main,
            "BASELINE_VERSION": baseline_version,
            "NEW_VERSION": new_version,
            "ASSET_DELTA": [
                "site/data/watchalong/manifest.json",
                f"site/data/watchalong/events/{target}.json",
            ],
            "MANIFEST_BEFORE_SHA": baseline_manifest_sha,
            "MANIFEST_AFTER_SHA": final_sha,
            "NEW_EVENT": target,
            "NEW_EVENT_SHA": event_sha,
            "OLD_ENTRIES_PRESERVED": "YES",
            "EXISTING_EVENT_CHANGED": "NO",
            "DUAL_ORIGIN_READBACK": "PASS",
            "READBACK_ATTEMPTS": attempts,
            "GITHUB_ACTIONS_USED": "NO",
            "CI_DEPLOY_USED": "NO",
            "OWNER_LOCAL_DEPLOY": "YES",
            "ROLLBACK_TARGET": baseline_version,
            "ROLLBACK_COMMAND": (
                f"cd {repo} && npx --yes wrangler rollback {baseline_version} "
                f"--config {WRANGLER_CONFIG} --name {WORKER_NAME}"
            ),
        }
        (backup_dir / "release-receipt-final.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print("ISSUE201_OWNER_LOCAL_RELEASE=PASS")
        for key, value in receipt.items():
            print(f"{key}={json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value}")
        print(f"BACKUP_DIR={backup_dir}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["data-watchalong"])
    parser.add_argument("event_id")
    parser.add_argument("expected_main_sha")
    args = parser.parse_args()
    try:
        if args.mode == "data-watchalong":
            deploy_data_watchalong(args.event_id, args.expected_main_sha)
    except (ReleaseGateError, subprocess.CalledProcessError, OSError, json.JSONDecodeError) as exc:
        print(f"OWNER_LOCAL_RELEASE=BLOCKED: {exc}", file=sys.stderr)
        print("NO_AUTOMATIC_REDEPLOY=YES", file=sys.stderr)
        print("NO_AUTOMATIC_ROLLBACK=YES", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
