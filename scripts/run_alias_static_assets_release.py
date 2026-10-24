#!/usr/bin/env python3
"""Owner-local #228 Alias Static Assets forward-only release.

Default mode is PREPARE: build and validate a complete candidate without mutation.
Production mutation requires explicit --execute plus the exact expected active Worker version.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from alias_static_assets_release_gate import (
    AliasReleaseGateError,
    sha256_bytes,
    validate_alias_contract,
    validate_alias_site_delta,
    validate_frontend_candidate_ownership,
)

CUSTOM_ORIGIN = "https://holodocchi.com"
WORKERS_ORIGIN = "https://holoviewer-public.singlebagel.workers.dev"
WORKER_NAME = "holoviewer-public"
WRANGLER_CONFIG = "cloudflare/wrangler.json"


def run(*args: str, capture: bool = False, cwd: Path | None = None) -> str:
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    return result.stdout.strip() if capture else ""


def fetch_bytes(url: str, *, allow_404: bool = False) -> bytes | None:
    request = Request(
        url,
        headers={
            "User-Agent": "HoloViewer-Alias-Owner-Release/1",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except HTTPError as exc:
        if allow_404 and exc.code == 404:
            return None
        raise


def git_bytes(repo: Path, revision: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=repo)


def production_url(origin: str, path: str, nonce: str) -> str:
    return f"{origin.rstrip('/')}/{path.lstrip('/')}?alias-release={nonce}"


def active_version(repo: Path) -> str:
    output = run(
        "npx", "--yes", "wrangler", "deployments", "status",
        "--config", WRANGLER_CONFIG, "--name", WORKER_NAME,
        capture=True, cwd=repo,
    )
    for line in output.splitlines():
        if "Version(s):" in line:
            fields = line.split()
            if fields:
                return fields[-1]
    raise AliasReleaseGateError("unable to determine active Worker version")


def candidate_from_production_baseline(
    repo: Path,
    production_site_base_sha: str,
    expected_head: str,
    target: Path,
    *,
    origin: str,
) -> dict:
    """Build candidate from accepted frontend-owned baseline + reviewed Alias delta only."""
    target.mkdir(parents=True, exist_ok=False)
    archive = subprocess.Popen(
        ["git", "archive", production_site_base_sha, "site"],
        cwd=repo,
        stdout=subprocess.PIPE,
    )
    assert archive.stdout is not None
    tar = subprocess.run(["tar", "-x", "-C", str(target)], stdin=archive.stdout, check=False)
    archive.stdout.close()
    archive_rc = archive.wait()
    if archive_rc or tar.returncode:
        raise AliasReleaseGateError("failed to materialize accepted Production site baseline")
    site = target / "site"
    if not site.is_dir():
        raise AliasReleaseGateError("materialized Production site baseline missing site/")

    # Overlay only the two reviewed Alias release paths from expected release SHA.
    delta = run(
        "git", "diff", "--name-status", production_site_base_sha, expected_head, "--", "site",
        capture=True, cwd=repo,
    ).splitlines()
    alias_delta = validate_alias_site_delta(delta)
    for rel in ("site/data/search/aliases/v1/latest.json", alias_delta["immutable_path"]):
        data = git_bytes(repo, expected_head, rel)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    alias_contract = validate_alias_contract(site)

    # Foreign-owner Static Assets must never be copied into holoviewer-public staging.
    ownership = validate_frontend_candidate_ownership(site)

    # Preserve the currently published Alias immutable object if it is distinct and not
    # already in the accepted source baseline, so a pointer rollback remains possible.
    nonce = f"preflight-{int(time.time())}-{os.getpid()}"
    current_alias_raw = fetch_bytes(
        production_url(origin, "/data/search/aliases/v1/latest.json", nonce),
        allow_404=True,
    )
    prior_alias = None
    if current_alias_raw is not None:
        try:
            current_alias = json.loads(current_alias_raw.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise AliasReleaseGateError("Production Alias pointer invalid") from exc
        prior_sha = str(current_alias.get("sha256") or "")
        prior_path = str(current_alias.get("asset_path") or "")
        if len(prior_sha) != 64 or prior_path != f"/data/search/aliases/v1/versions/{prior_sha}.json":
            raise AliasReleaseGateError("Production Alias pointer schema mismatch")
        prior_raw = fetch_bytes(production_url(origin, prior_path, nonce))
        assert prior_raw is not None
        if sha256_bytes(prior_raw) != prior_sha:
            raise AliasReleaseGateError("Production Alias immutable SHA mismatch")
        prior_dest = site / prior_path.lstrip("/")
        if not prior_dest.exists():
            prior_dest.parent.mkdir(parents=True, exist_ok=True)
            prior_dest.write_bytes(prior_raw)
        prior_alias = {"sha256": prior_sha, "asset_path": prior_path}

    ownership = validate_frontend_candidate_ownership(site)

    # Build a temporary Wrangler config that points at the staged full site but keeps
    # all other authoritative Worker settings unchanged.
    config_raw = git_bytes(repo, expected_head, WRANGLER_CONFIG)
    try:
        config = json.loads(config_raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise AliasReleaseGateError("Wrangler config invalid") from exc
    if config.get("name") != WORKER_NAME:
        raise AliasReleaseGateError("unexpected Worker name")
    assets = config.get("assets")
    if not isinstance(assets, dict):
        raise AliasReleaseGateError("Wrangler assets config missing")
    staged_config = dict(config)
    staged_config["assets"] = dict(assets)
    staged_config["assets"]["directory"] = str(site.resolve())
    config_path = target / "wrangler.alias-release.json"
    config_path.write_text(json.dumps(staged_config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "site": str(site),
        "config": str(config_path),
        "alias": alias_contract,
        "alias_delta": alias_delta,
        "ownership": ownership,
        "prior_alias": prior_alias,
    }


def verify_repo_owned_production_baseline(
    repo: Path,
    production_site_base_sha: str,
    *,
    origin: str,
) -> dict:
    """Verify every baseline site file except runtime-owned paths equals Production bytes."""
    paths = run(
        "git", "ls-tree", "-r", "--name-only", production_site_base_sha, "--", "site",
        capture=True, cwd=repo,
    ).splitlines()
    checked = 0
    nonce = f"baseline-{int(time.time())}-{os.getpid()}"
    for path in paths:
        if not path.startswith("site/"):
            continue
        rel = path[len("site/"):]
        if rel in {"_headers", "_redirects"}:
            continue
        if rel.startswith("youtube/v1/") or rel.startswith("ptt/v1/") or rel.startswith("data/search/aliases/v1/"):
            continue
        expected = git_bytes(repo, production_site_base_sha, path)
        actual = fetch_bytes(production_url(origin, "/" + rel, nonce))
        assert actual is not None
        if hashlib.sha256(actual).digest() != hashlib.sha256(expected).digest():
            raise AliasReleaseGateError(f"Production baseline drift at /{rel}")
        checked += 1
    if checked == 0:
        raise AliasReleaseGateError("no repo-owned Production baseline assets were checked")
    return {"checked_repo_owned_assets": checked, "status": "PASS"}


def readback_alias(origin: str, expected_sha: str) -> bool:
    nonce = f"readback-{int(time.time())}-{os.getpid()}"
    pointer_raw = fetch_bytes(production_url(origin, "/data/search/aliases/v1/latest.json", nonce))
    if pointer_raw is None:
        return False
    try:
        pointer = json.loads(pointer_raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        return False
    if pointer.get("sha256") != expected_sha:
        return False
    expected_path = f"/data/search/aliases/v1/versions/{expected_sha}.json"
    if pointer.get("asset_path") != expected_path:
        return False
    immutable = fetch_bytes(production_url(origin, expected_path, nonce))
    return immutable is not None and sha256_bytes(immutable) == expected_sha


def bounded_readback(check, delays=(0, 2, 4, 8, 12)) -> int:
    last_error = None
    for attempt, delay in enumerate(delays, start=1):
        if delay:
            time.sleep(delay)
        try:
            if check():
                return attempt
        except Exception as exc:
            last_error = exc
    if last_error:
        raise AliasReleaseGateError(f"readback did not converge: {last_error}") from last_error
    raise AliasReleaseGateError("readback did not converge")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("expected_release_sha")
    parser.add_argument("production_site_base_sha")
    parser.add_argument("--expected-active-version")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--evidence-dir")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    os.chdir(repo)
    try:
        run("git", "fetch", "origin", "main", cwd=repo)
        head = run("git", "rev-parse", "HEAD", capture=True, cwd=repo)
        if head != args.expected_release_sha:
            raise AliasReleaseGateError("checkout is not expected release SHA")
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", args.expected_release_sha, "origin/main"],
            cwd=repo,
        ).returncode:
            raise AliasReleaseGateError("expected release SHA is not contained in current origin/main")
        if run("git", "status", "--porcelain", "--untracked-files=all", capture=True, cwd=repo):
            raise AliasReleaseGateError("checkout is not clean")

        # Alias release must not change Worker config relative to accepted Production source.
        if subprocess.run(
            ["git", "diff", "--quiet", args.production_site_base_sha, args.expected_release_sha,
             "--", WRANGLER_CONFIG],
            cwd=repo,
        ).returncode:
            raise AliasReleaseGateError("Alias release unexpectedly changes Wrangler config")

        baseline_check = verify_repo_owned_production_baseline(
            repo, args.production_site_base_sha, origin=CUSTOM_ORIGIN
        )

        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        evidence = Path(args.evidence_dir).expanduser().resolve() if args.evidence_dir else (
            Path.home() / "Downloads" / "HoloViewer-deploy-evidence" / f"alias-{stamp}"
        )
        evidence.mkdir(parents=True, exist_ok=False)

        with tempfile.TemporaryDirectory(prefix="holoviewer-alias-release-") as tmp:
            candidate = candidate_from_production_baseline(
                repo,
                args.production_site_base_sha,
                args.expected_release_sha,
                Path(tmp) / "candidate",
                origin=CUSTOM_ORIGIN,
            )
            staged_site = Path(candidate["site"])
            local_alias_sha = candidate["alias"]["sha256"]
            baseline_version = active_version(repo)

            preflight = {
                "mode": "EXECUTE" if args.execute else "PREPARE_ONLY",
                "source_release_sha": args.expected_release_sha,
                "production_site_base_sha": args.production_site_base_sha,
                "baseline_active_version": baseline_version,
                "baseline_reconciliation": baseline_check,
                "candidate": candidate,
                "production_mutation": "NO" if not args.execute else "PENDING_EXPLICIT_EXECUTE",
                "rollback_target": baseline_version,
            }
            (evidence / "alias-release-preflight.json").write_text(
                json.dumps(preflight, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(preflight, indent=2, sort_keys=True))

            if not args.execute:
                print("ALIAS_RELEASE_PREFLIGHT=PASS")
                print("PRODUCTION_MUTATION=NO")
                print(f"EVIDENCE_DIR={evidence}")
                return 0

            if not args.expected_active_version:
                raise AliasReleaseGateError("--expected-active-version is mandatory with --execute")
            if baseline_version != args.expected_active_version:
                raise AliasReleaseGateError("Production active version changed since Owner approval")

            print("ALL_PREDEPLOY_GATES=PASS")
            print("OWNER_EXPLICIT_EXECUTE=YES")
            run(
                "npx", "--yes", "wrangler", "deploy",
                "--config", candidate["config"], "--name", WORKER_NAME,
                cwd=repo,
            )
            new_version = active_version(repo)
            if new_version == baseline_version:
                raise AliasReleaseGateError("Production active Worker version did not change")

            attempts = {}
            for label, origin in (("CUSTOM", CUSTOM_ORIGIN), ("WORKERS", WORKERS_ORIGIN)):
                attempts[label + "_ALIAS"] = bounded_readback(
                    lambda origin=origin: readback_alias(origin, local_alias_sha)
                )
                attempts[label + "_REPO_BASELINE"] = bounded_readback(
                    lambda origin=origin: bool(
                        verify_repo_owned_production_baseline(
                            repo,
                            args.production_site_base_sha,
                            origin=origin,
                        )
                    )
                )

            receipt = {
                "ALIAS_STATIC_ASSETS_RELEASE": "PASS",
                "SOURCE_RELEASE_SHA": args.expected_release_sha,
                "PRODUCTION_SITE_BASE_SHA": args.production_site_base_sha,
                "BASELINE_ACTIVE_VERSION": baseline_version,
                "NEW_ACTIVE_VERSION": new_version,
                "ALIAS_SHA256": local_alias_sha,
                "ALIAS_DELTA": [
                    candidate["alias"]["latest_path"],
                    candidate["alias"]["immutable_path"],
                ],
                "FOREIGN_OWNER_STATIC_ASSETS_EXCLUDED": "YES",
                "REPO_OWNED_BASELINE_PRESERVED": "YES",
                "DUAL_ORIGIN_READBACK": "PASS",
                "READBACK_ATTEMPTS": attempts,
                "PRODUCTION_D1_CHANGED": "NO",
                "PRODUCTION_API_WORKER_CHANGED": "NO",
                "R2_USED": "NO",
                "GITHUB_ACTIONS_DEPLOY_USED": "NO",
                "ROLLBACK_TARGET": baseline_version,
                "ROLLBACK_COMMAND": (
                    f"cd {repo} && npx --yes wrangler rollback {baseline_version} "
                    f"--config {WRANGLER_CONFIG} --name {WORKER_NAME}"
                ),
            }
            (evidence / "alias-release-receipt.json").write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(receipt, indent=2, sort_keys=True))
            print(f"EVIDENCE_DIR={evidence}")
            return 0
    except (
        AliasReleaseGateError,
        subprocess.CalledProcessError,
        OSError,
        ValueError,
        HTTPError,
    ) as exc:
        print(f"ALIAS_RELEASE=BLOCKED: {exc}", file=sys.stderr)
        print("NO_AUTOMATIC_REDEPLOY=YES", file=sys.stderr)
        print("NO_AUTOMATIC_ROLLBACK=YES", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
