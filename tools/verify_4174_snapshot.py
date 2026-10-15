#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "4174-a144bb3"
MANIFEST = ROOT / "provenance" / "4174-source-manifest.json"
MODULE_INDEX = ROOT / "provenance" / "4174-source-module-index.json"
CLOSURE = ROOT / "provenance" / "4174-dependency-closure.json"

EXPECTED_REPOSITORY = "physicsdog0505/Hololive-PTT-Viewer"
EXPECTED_SOURCE = "a144bb378a8bdd772faa867d608c1e7491253883"
FAILED_BRANCHES = {"dev/8788-parity", "dev/8788-clean-transplant"}

ROOT_FILES = {
    "client_app.py",
    "client_custom_view.py",
    "client_history.py",
    "client_home.py",
    "client_ptt_today.py",
    "client_ui_shell.py",
    "client_watchalong.py",
    "shared_viewing_core.py",
}
REQUIRED_STATIC = {
    "public/ptt_timeline.js",
    "public/ptt_player_adapter.js",
    "public/ptt_worker_adapter.js",
    "hololive_channels.prototype.json",
}
ALLOWED_ROLES = {
    "python_module",
    "js_asset",
    "json_asset",
    "launcher_support",
    "runtime_requirement_manifest",
    "runtime_asset",
}
REQUIRED_PHASE_C = {
    "scripts/start_8788_full_4174.sh",
    "tools/run_4174_snapshot.py",
}
BLOCKED_PHASE_E = {
    "cloudflare",
    "site",
}


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def fail(messages: list[str]) -> int:
    for message in messages:
        print("FAIL:", message, file=sys.stderr)
    return 1


def module_root(rel: str) -> str:
    p = Path(rel)
    return p.parts[0] if len(p.parts) > 1 else p.stem


def main() -> int:
    errors: list[str] = []

    if not VENDOR.is_dir():
        return fail([f"missing vendored snapshot: {VENDOR}"])

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    module_index = json.loads(MODULE_INDEX.read_text(encoding="utf-8"))
    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))

    if manifest.get("schema_version") != 2:
        errors.append("manifest schema_version must be 2")
    if manifest.get("source_repository") != EXPECTED_REPOSITORY:
        errors.append("manifest source repository is not the pinned private 4174 repo")
    if manifest.get("source_commit") != EXPECTED_SOURCE:
        errors.append("manifest source commit is not pinned a144bb3")
    if module_index.get("source_repository") != EXPECTED_REPOSITORY:
        errors.append("module index source repository is not the pinned private 4174 repo")
    if module_index.get("source_commit") != EXPECTED_SOURCE:
        errors.append("module index source commit is not pinned a144bb3")
    if closure.get("source_repository") != EXPECTED_REPOSITORY:
        errors.append("dependency closure source repository is not pinned 4174")
    if closure.get("source_commit") != EXPECTED_SOURCE:
        errors.append("dependency closure source commit is not pinned a144bb3")

    entries = manifest.get("product_files", [])
    if not isinstance(entries, list):
        entries = []
        errors.append("manifest product_files must be a list")

    expected: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("manifest contains a non-object product file entry")
            continue
        rel = entry.get("path")
        if not isinstance(rel, str) or not rel:
            errors.append("manifest entry has invalid path")
            continue
        if rel in expected:
            errors.append(f"duplicate manifest path: {rel}")
            continue
        expected[rel] = entry

        if entry.get("source_repository") != EXPECTED_REPOSITORY:
            errors.append(f"wrong source repository for {rel}")
        if entry.get("source_commit") != EXPECTED_SOURCE:
            errors.append(f"wrong source commit for {rel}")
        if entry.get("role") not in ALLOWED_ROLES:
            errors.append(f"invalid role for {rel}: {entry.get('role')!r}")
        blob_sha = entry.get("source_blob_sha")
        if not isinstance(blob_sha, str) or len(blob_sha) != 40:
            errors.append(f"invalid source blob SHA for {rel}")

    required = ROOT_FILES | REQUIRED_STATIC
    missing_required_manifest = sorted(required - set(expected))
    if missing_required_manifest:
        errors.append(
            "required 4174 roots/assets absent from manifest: "
            + ", ".join(missing_required_manifest)
        )

    actual = {
        str(path.relative_to(VENDOR))
        for path in VENDOR.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    }

    missing = sorted(set(expected) - actual)
    extra = sorted(actual - set(expected))
    if missing:
        errors.append("manifest files missing from snapshot: " + ", ".join(missing))
    if extra:
        errors.append("unmanifested product files inside snapshot: " + ", ".join(extra))

    for rel, entry in expected.items():
        path = VENDOR / rel
        if not path.is_file():
            continue
        observed = git_blob_sha(path.read_bytes())
        wanted = entry.get("source_blob_sha")
        if observed != wanted:
            errors.append(f"source blob mismatch {rel}: {observed} != {wanted}")

    source_python_paths = module_index.get("python_paths", [])
    if not isinstance(source_python_paths, list):
        source_python_paths = []
        errors.append("module index python_paths must be a list")

    source_roots = {module_root(rel) for rel in source_python_paths if isinstance(rel, str)}
    vendored_python = {
        rel for rel in actual
        if Path(rel).suffix == ".py"
    }
    vendored_roots = {module_root(rel) for rel in vendored_python}

    declared_python = set(closure.get("python_dependency_closure", []))
    if declared_python != vendored_python:
        missing_declared = sorted(vendored_python - declared_python)
        stale_declared = sorted(declared_python - vendored_python)
        if missing_declared:
            errors.append("vendored Python missing from dependency closure manifest: " + ", ".join(missing_declared))
        if stale_declared:
            errors.append("dependency closure manifest lists absent Python: " + ", ".join(stale_declared))

    declared_static = set(closure.get("required_static_assets", []))
    if declared_static != REQUIRED_STATIC:
        errors.append("dependency closure required_static_assets does not match accepted static contract")

    import_graph: dict[str, set[str]] = {}
    for rel in sorted(vendored_python):
        path = VENDOR / rel
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            errors.append(f"syntax error in {rel}: {exc}")
            continue

        local_needed: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".", 1)[0]]
            else:
                continue
            local_needed.update(name for name in names if name in source_roots)

        import_graph[rel] = local_needed
        absent = sorted(name for name in local_needed if name not in vendored_roots)
        if absent:
            errors.append(
                f"required local dependency absent for {rel}: "
                + ", ".join(absent)
            )

    # The eight accepted roots must themselves exist as byte-proven vendored files.
    for rel in sorted(ROOT_FILES):
        if rel not in vendored_python:
            errors.append(f"accepted root module missing: {rel}")

    # Static product assets explicitly referenced by accepted 4174 must resolve
    # under the vendored snapshot and be manifest-proven.
    for rel in sorted(REQUIRED_STATIC):
        path = (VENDOR / rel).resolve()
        try:
            path.relative_to(VENDOR.resolve())
        except ValueError:
            errors.append(f"static path escapes vendored snapshot: {rel}")
            continue
        if rel not in expected:
            errors.append(f"unmanifested required static asset: {rel}")
        elif not path.is_file():
            errors.append(f"required static asset missing: {rel}")

    # Checkpoint 2 requires the isolated launcher/runtime runner, while
    # Cloudflare/platform work remains blocked until later review.
    for rel in sorted(REQUIRED_PHASE_C):
        path = ROOT / rel
        if not path.is_file():
            errors.append(f"required Phase C isolation artifact missing: {rel}")

    for rel in sorted(BLOCKED_PHASE_E):
        try:
            tracked = subprocess.check_output(
                ["git", "-C", str(ROOT), "ls-files", "--", rel, rel + "/**"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).splitlines()
        except (OSError, subprocess.CalledProcessError):
            tracked = []
        tracked = [item for item in tracked if item.strip()]
        if tracked:
            errors.append(
                f"premature Phase E product/platform tree tracked in branch: {rel}: "
                + ", ".join(tracked)
            )

    # Explicitly reject legacy Public product residue.
    forbidden_files = [
        ROOT / "app.py",
        ROOT / "public_snapshot.py",
        ROOT / "scripts" / "start_public_local.sh",
    ]
    for path in forbidden_files:
        if path.exists():
            errors.append(f"legacy Public residue present: {path.relative_to(ROOT)}")

    try:
        branch = subprocess.check_output(
            ["git", "-C", str(ROOT), "branch", "--show-current"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if branch in FAILED_BRANCHES:
            errors.append(f"refusing failed migration branch: {branch}")
    except (OSError, subprocess.CalledProcessError):
        pass

    if errors:
        return fail(errors)

    print(f"PASS: source repository pinned to {EXPECTED_REPOSITORY}")
    print(f"PASS: source commit pinned to {EXPECTED_SOURCE}")
    print(f"PASS: {len(expected)} vendored product files match manifest blob provenance")
    print(f"PASS: {len(vendored_python)} vendored Python modules have closed local imports")
    print("PASS: required PTT/static assets resolve inside vendor/4174-a144bb3")
    print("PASS: no old Public or failed-branch product source is admitted")
    print("PASS: Phase C isolation artifacts are present")
    print("PASS: Phase E Cloudflare/static-shell artifacts remain absent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
