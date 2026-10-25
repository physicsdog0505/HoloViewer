#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

CUSTOM_ORIGIN = "https://holodocchi.com"
WORKERS_ORIGIN = "https://holoviewer-public.singlebagel.workers.dev"
WORKER_NAME = "holoviewer-public"
WRANGLER_CONFIG = "cloudflare/wrangler.json"
FOREIGN_PREFIXES = ("youtube/v1/", "ptt/v1/")
SKIP_REMOTE = {"_headers", "_redirects"}


class ReleaseBlocked(RuntimeError):
    pass


def run(*args: str, cwd: Path, capture: bool = False) -> str:
    r = subprocess.run(
        args,
        cwd=str(cwd),
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    return r.stdout.strip() if capture else ""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(origin: str, rel: str, *, allow_404: bool = False) -> bytes | None:
    nonce = f"frontend-release-{int(time.time())}-{os.getpid()}"
    url = f"{origin.rstrip('/')}/{rel.lstrip('/')}?release-audit={nonce}"
    req = Request(url, headers={
        "User-Agent": "HoloViewer-Frontend-Owner-Release/2",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    try:
        with urlopen(req, timeout=30) as r:
            return r.read()
    except HTTPError as exc:
        if allow_404 and exc.code == 404:
            return None
        raise


def git_bytes(repo: Path, rev: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{rev}:{path}"], cwd=repo)


def site_tree(repo: Path, rev: str) -> list[str]:
    out = run("git", "ls-tree", "-r", "--name-only", rev, "--", "site", cwd=repo, capture=True)
    return [p for p in out.splitlines() if p.startswith("site/")]


def diff_site(repo: Path, base: str, head: str) -> dict[str, str]:
    out = run("git", "diff", "--name-status", base, head, "--", "site", cwd=repo, capture=True)
    result: dict[str, str] = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        path = parts[-1]
        result[path] = status
    return result


def is_foreign_rel(rel: str) -> bool:
    return rel.startswith(FOREIGN_PREFIXES)


def active_version(repo: Path) -> str:
    out = run(
        "npx", "--yes", "wrangler", "deployments", "status",
        "--config", WRANGLER_CONFIG, "--name", WORKER_NAME,
        cwd=repo, capture=True,
    )
    for line in out.splitlines():
        if "Version(s):" in line:
            fields = line.split()
            if fields:
                return fields[-1]
    raise ReleaseBlocked("unable to determine active Worker version")


def parse_frontend_config(repo: Path) -> tuple[str, list[tuple[str, str]]]:
    text = (repo / "site/assets/config.js").read_text()
    marker = 'youtubeStaticBase: "'
    if marker not in text:
        raise ReleaseBlocked("youtubeStaticBase missing from frontend config")
    youtube = text.split(marker, 1)[1].split('"', 1)[0]
    if youtube != "https://holoviewer-youtube-static-assets.singlebagel.workers.dev":
        raise ReleaseBlocked("frontend YouTube consumer is not pointed at dedicated target")

    pairs: list[tuple[str, str]] = []
    for block in text.split("base: ")[1:]:
        try:
            base = block.split('"', 2)[1]
            manifest = block.split("manifest: ", 1)[1].split('"', 2)[1]
        except (IndexError, ValueError):
            continue
        if not manifest.startswith("/ptt/v1/"):
            raise ReleaseBlocked("PTT manifest path is outside ptt/v1")
        if "holoviewer-public.singlebagel.workers.dev" in base or base.rstrip("/") == CUSTOM_ORIGIN:
            raise ReleaseBlocked("frontend PTT consumer still points at frontend Worker")
        pairs.append((base, manifest))
    if not pairs:
        raise ReleaseBlocked("no dedicated PTT archive targets found in frontend config")
    return youtube, pairs


def dedicated_health(repo: Path) -> dict:
    youtube, ptt = parse_frontend_config(repo)
    y = fetch(youtube, "/youtube/v1/manifest.json")
    if not y:
        raise ReleaseBlocked("dedicated YouTube manifest readback is empty")
    try:
        json.loads(y)
    except ValueError as exc:
        raise ReleaseBlocked("dedicated YouTube manifest is not JSON") from exc

    checked = []
    for base, manifest in ptt:
        raw = fetch(base, manifest)
        if not raw:
            raise ReleaseBlocked(f"dedicated PTT manifest empty: {base}{manifest}")
        try:
            json.loads(raw)
        except ValueError as exc:
            raise ReleaseBlocked(f"dedicated PTT manifest is not JSON: {base}{manifest}") from exc
        checked.append(base + manifest)
    return {"youtube": youtube + "/youtube/v1/manifest.json", "ptt": checked, "status": "PASS"}


def ownership_gate(repo: Path) -> dict:
    forbidden = []
    for p in (repo / "site").rglob("*"):
        if p.is_file():
            rel = p.relative_to(repo / "site").as_posix()
            if is_foreign_rel(rel):
                forbidden.append(rel)
    if forbidden:
        raise ReleaseBlocked("foreign-owner assets in candidate: " + ", ".join(forbidden[:20]))
    if not (repo / "site/data/watchalong/manifest.json").is_file():
        raise ReleaseBlocked("Watchalong manifest missing")
    return {"forbidden_count": 0, "status": "PASS"}


CF_BEACON_RE = re.compile(
    rb'<script(?=[^>]*\\bsrc="https://static\\.cloudflareinsights\\.com/beacon\\.min\\.js/[^"]+")'
    rb'(?=[^>]*\\bdata-cf-beacon=)[^>]*></script>'
)


def normalize_custom_html_edge(data: bytes) -> bytes:
    matches = list(CF_BEACON_RE.finditer(data))
    if len(matches) > 1:
        raise ReleaseBlocked("multiple Cloudflare Insights beacon injections in custom-domain HTML")
    if not matches:
        return data
    match = matches[0]
    return data[:match.start()] + data[match.end():]


def verify_bytes(origin: str, rel: str, expected: bytes, label: str) -> None:
    actual = fetch(origin, "/" + rel)
    if actual is None:
        raise ReleaseBlocked(f"{label} byte mismatch at /{rel}")
    if origin == CUSTOM_ORIGIN and rel.endswith(".html"):
        actual = normalize_custom_html_edge(actual)
    if actual != expected:
        raise ReleaseBlocked(f"{label} byte mismatch at /{rel}")


def reconcile_baseline(repo: Path, base: str, head: str) -> dict:
    changed = diff_site(repo, base, head)
    checked = 0
    skipped_changed = 0
    for path in site_tree(repo, base):
        rel = path[len("site/"):]
        if rel in SKIP_REMOTE or is_foreign_rel(rel):
            continue
        if path in changed:
            skipped_changed += 1
            continue
        expected = git_bytes(repo, base, path)
        verify_bytes(CUSTOM_ORIGIN, rel, expected, "custom Production baseline")
        verify_bytes(WORKERS_ORIGIN, rel, expected, "workers.dev Production baseline")
        checked += 1
    if checked == 0:
        raise ReleaseBlocked("no unchanged frontend-owned baseline assets reconciled")
    return {"checked_unchanged_assets": checked, "reviewed_changed_assets": len(changed), "status": "PASS"}


def reconcile_runtime(repo: Path, base: str, head: str) -> dict:
    changed = diff_site(repo, base, head)
    candidate = repo / "site"
    protected = []

    # Current Production Watchalong inventory is manifest-declared.
    manifest_rel = "data/watchalong/manifest.json"
    raw = fetch(CUSTOM_ORIGIN, "/" + manifest_rel)
    raw_workers = fetch(WORKERS_ORIGIN, "/" + manifest_rel)
    if raw != raw_workers:
        raise ReleaseBlocked("Watchalong manifest differs between Production origins")
    if raw:
        try:
            obj = json.loads(raw)
        except ValueError as exc:
            raise ReleaseBlocked("Production Watchalong manifest invalid") from exc
        paths = [manifest_rel]
        for event in obj.get("events", []):
            p = str(event.get("path") or "").lstrip("/")
            if p:
                paths.append(p)
        for rel in paths:
            repo_path = "site/" + rel
            if changed.get(repo_path, "").startswith("D"):
                continue
            local = candidate / rel
            if not local.is_file():
                raise ReleaseBlocked(f"current Production Watchalong asset missing from candidate: /{rel}")
            prod = fetch(CUSTOM_ORIGIN, "/" + rel)
            if repo_path not in changed and local.read_bytes() != prod:
                raise ReleaseBlocked(f"unreviewed Watchalong drift at /{rel}")
            protected.append(rel)

    # Current Production Alias immutable must not disappear from a generic frontend release.
    alias_latest_rel = "data/search/aliases/v1/latest.json"
    alias_raw = fetch(CUSTOM_ORIGIN, "/" + alias_latest_rel, allow_404=True)
    alias_workers = fetch(WORKERS_ORIGIN, "/" + alias_latest_rel, allow_404=True)
    if alias_raw != alias_workers:
        raise ReleaseBlocked("Alias latest differs between Production origins")
    if alias_raw:
        try:
            pointer = json.loads(alias_raw)
        except ValueError as exc:
            # Static Assets SPA fallback returns index.html with HTTP 200 for a missing path.
            if alias_raw.lstrip().lower().startswith(b"<!doctype html"):
                pointer = None
                alias_raw = None
            else:
                raise ReleaseBlocked("Production Alias latest invalid") from exc
        if pointer is None:
            return {"protected_runtime_assets": sorted(set(protected)), "status": "PASS"}
        immutable_rel = str(pointer.get("asset_path") or "").lstrip("/")
        if not immutable_rel.startswith("data/search/aliases/v1/versions/"):
            raise ReleaseBlocked("Production Alias immutable path invalid")
        immutable_raw = fetch(CUSTOM_ORIGIN, "/" + immutable_rel)
        immutable_workers = fetch(WORKERS_ORIGIN, "/" + immutable_rel)
        if immutable_raw != immutable_workers:
            raise ReleaseBlocked("Alias immutable differs between Production origins")
        for rel, prod in ((alias_latest_rel, alias_raw), (immutable_rel, immutable_raw)):
            repo_path = "site/" + rel
            if changed.get(repo_path, "").startswith("D"):
                continue
            local = candidate / rel
            if not local.is_file():
                raise ReleaseBlocked(f"current Production Alias asset missing from candidate: /{rel}")
            if rel == immutable_rel and local.read_bytes() != prod:
                raise ReleaseBlocked(f"current Production Alias immutable not preserved: /{rel}")
            if repo_path not in changed and local.read_bytes() != prod:
                raise ReleaseBlocked(f"unreviewed Alias drift at /{rel}")
            protected.append(rel)

    return {"protected_runtime_assets": sorted(set(protected)), "status": "PASS"}


def enumerate_first_run_foreign(repo: Path) -> dict:
    paths = {"youtube": [], "ptt": []}
    yraw = fetch(CUSTOM_ORIGIN, "/youtube/v1/manifest.json", allow_404=True)
    if yraw:
        paths["youtube"].append("/youtube/v1/manifest.json")
        try:
            obj = json.loads(yraw)
            def walk(v):
                if isinstance(v, dict):
                    for x in v.values():
                        walk(x)
                elif isinstance(v, list):
                    for x in v:
                        walk(x)
                elif isinstance(v, str):
                    if v.startswith("http://") or v.startswith("https://"):
                        return
                    p = "/" + v.lstrip("/")
                    if p.startswith("/youtube/v1/"):
                        paths["youtube"].append(p)
                    elif p.endswith(".json"):
                        paths["youtube"].append("/youtube/v1/" + p.lstrip("/"))
            walk(obj)
        except ValueError:
            raise ReleaseBlocked("legacy frontend YouTube manifest is not JSON")

    _, ptt = parse_frontend_config(repo)
    for _, manifest in ptt:
        raw = fetch(CUSTOM_ORIGIN, manifest, allow_404=True)
        if raw:
            try:
                json.loads(raw)
            except ValueError:
                continue
            paths["ptt"].append(manifest)

    paths["youtube"] = sorted(set(paths["youtube"]))
    paths["ptt"] = sorted(set(paths["ptt"]))
    return {
        "youtube_paths": paths["youtube"],
        "ptt_manifest_paths": paths["ptt"],
        "youtube_count": len(paths["youtube"]),
        "ptt_manifest_count": len(paths["ptt"]),
    }


def post_deploy_readback(repo: Path) -> dict:
    checked = 0
    for p in sorted((repo / "site").rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(repo / "site").as_posix()
        if rel in SKIP_REMOTE or is_foreign_rel(rel):
            continue
        expected = p.read_bytes()
        verify_bytes(CUSTOM_ORIGIN, rel, expected, "custom post-deploy")
        verify_bytes(WORKERS_ORIGIN, rel, expected, "workers.dev post-deploy")
        checked += 1
    if checked == 0:
        raise ReleaseBlocked("no candidate assets read back")
    return {"dual_origin_assets_checked": checked, "status": "PASS"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("expected_release_sha")
    ap.add_argument("accepted_production_source_sha")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--expected-active-version")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parents[1]
    os.chdir(repo)

    try:
        run("git", "fetch", "origin", "main", cwd=repo)
        head = run("git", "rev-parse", "HEAD", cwd=repo, capture=True)
        if head != args.expected_release_sha:
            raise ReleaseBlocked("checkout is not expected release SHA")
        if subprocess.run(["git", "merge-base", "--is-ancestor", head, "origin/main"], cwd=repo).returncode:
            raise ReleaseBlocked("release SHA is not contained in origin/main")
        if run("git", "status", "--porcelain", "--untracked-files=all", cwd=repo, capture=True):
            raise ReleaseBlocked("checkout is not clean")
        subprocess.run(["git", "cat-file", "-e", f"{args.accepted_production_source_sha}^{{commit}}"], cwd=repo, check=True)

        ownership = ownership_gate(repo)
        dedicated = dedicated_health(repo)
        baseline = reconcile_baseline(repo, args.accepted_production_source_sha, head)
        runtime = reconcile_runtime(repo, args.accepted_production_source_sha, head)
        foreign = enumerate_first_run_foreign(repo)
        baseline_version = active_version(repo)

        result = {
            "mode": "EXECUTE" if args.execute else "PREPARE_ONLY",
            "source_release_sha": head,
            "accepted_production_source_sha": args.accepted_production_source_sha,
            "baseline_active_version": baseline_version,
            "ownership": ownership,
            "dedicated_target_health": dedicated,
            "production_frontend_reconciliation": baseline,
            "runtime_reconciliation": runtime,
            "first_run_foreign_inventory": foreign,
            "production_mutation": "PENDING_EXPLICIT_EXECUTE" if args.execute else "NO",
        }
        print(json.dumps(result, indent=2, sort_keys=True))

        if not args.execute:
            print("PUBLIC_FRONTEND_RELEASE_PREPARE=PASS")
            print("FULL_FORWARD_ONLY_RECONCILIATION=PASS")
            print("PRODUCTION_MUTATION=NO")
            print("DEPLOY=NO")
            return 0

        if not args.expected_active_version:
            raise ReleaseBlocked("--expected-active-version is required with --execute")
        if baseline_version != args.expected_active_version:
            raise ReleaseBlocked("active Worker version changed since Owner approval")

        print("ALL_PREDEPLOY_GATES=PASS")
        print("OWNER_EXPLICIT_EXECUTE=YES")
        run("npx", "--yes", "wrangler", "deploy", "--config", WRANGLER_CONFIG, "--name", WORKER_NAME, cwd=repo)

        new_version = active_version(repo)
        if new_version == baseline_version:
            raise ReleaseBlocked("active Worker version did not change")

        readback = post_deploy_readback(repo)
        dedicated_after = dedicated_health(repo)

        receipt = {
            "PUBLIC_FRONTEND_RELEASE": "PASS",
            "SOURCE_RELEASE_SHA": head,
            "BASELINE_ACTIVE_VERSION": baseline_version,
            "NEW_ACTIVE_VERSION": new_version,
            "DUAL_ORIGIN_READBACK": readback,
            "DEDICATED_TARGET_HEALTH_AFTER": dedicated_after,
            "FOREIGN_OWNER_STATIC_ASSETS_EXCLUDED": "YES",
            "PRODUCTION_D1_CHANGED": "NO",
            "PRODUCTION_API_WORKER_CHANGED": "NO",
            "GITHUB_ACTIONS_DEPLOY_USED": "NO",
            "AUTOMATIC_ROLLBACK": "NO",
            "ROLLBACK_TARGET": baseline_version,
        }
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except (ReleaseBlocked, subprocess.CalledProcessError, OSError, ValueError, HTTPError) as exc:
        print(f"PUBLIC_FRONTEND_RELEASE=BLOCKED: {exc}", file=sys.stderr)
        print("NO_AUTOMATIC_REDEPLOY=YES", file=sys.stderr)
        print("NO_AUTOMATIC_ROLLBACK=YES", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
