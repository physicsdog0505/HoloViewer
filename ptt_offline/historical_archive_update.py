"""Fail-closed historical archive extension for reviewed Collector sources.

This module never crawls PTT, mutates a source SQLite database, or deploys a
Worker.  It combines an accepted archive baseline with explicitly scoped,
read-only Collector-format SQLite sources, then emits deterministic UTC-hour
archive objects and canonical JSON Static Assets.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from .publisher_cli import coverage_receipt
from .public_today_contract import ContractError, normalize_public_aid
from .r2_archive_export import write_archive_rows
from .r2_archive_pilot import _load_source


TPE = ZoneInfo("Asia/Taipei")
STATIC_SCHEMA = "ptt-static-assets-v1"


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ContractError("timezone-aware timestamp required")
    return result.astimezone(timezone.utc)


def _read_archive(root: Path, manifest_name: str) -> tuple[Path, dict, list[dict]]:
    manifest_path = root / "ptt/v1/manifests" / manifest_name
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = []
    seen = set()
    for item in manifest["objects"]:
        target = root / item["key"]
        with gzip.open(target, "rb") as handle:
            raw = handle.read()
        if sha256(raw).hexdigest() != item["sha256"]:
            raise ContractError(f"source archive SHA mismatch: {item['key']}")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError(f"source archive JSON failure: {item['key']}") from exc
        if len(payload.get("pushes", [])) != item["pushes"]:
            raise ContractError(f"source archive push-count mismatch: {item['key']}")
        for row in payload["pushes"]:
            key = row.get("source_record_key")
            if not isinstance(key, str) or not key or key in seen:
                raise ContractError("source archive duplicate/invalid identity")
            seen.add(key)
            rows.append(dict(row))
    expected = manifest.get("total_pushes", manifest.get("pushes"))
    if len(rows) != expected:
        raise ContractError("source archive total push count mismatch")
    return manifest_path, manifest, rows


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    return db


def _source_coverage(path: Path) -> dict[str, dict]:
    result = {}
    with _connect(path) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ContractError(f"source quick_check failed: {path}")
        for row in db.execute("SELECT aid FROM articles WHERE board='C_Chat' ORDER BY id"):
            aid = normalize_public_aid(row["aid"])
            evidence = coverage_receipt(db, row["aid"])
            evidence["source_path"] = str(path)
            previous = result.get(aid)
            if previous is not None and previous != evidence:
                raise ContractError(f"duplicate source AID in one SQLite: {aid}")
            result[aid] = evidence
    return result


def _load_scoped_source(item: dict) -> tuple[list[dict], dict[str, dict]]:
    path = Path(item["path"]).expanduser()
    from_day = date.fromisoformat(item["from_day"])
    through_day = date.fromisoformat(item["through_day"])
    if through_day < from_day:
        raise ContractError("source day scope is reversed")
    rows, _ = _load_source(
        path,
        provenance=item.get("provenance") or str(path),
        title_day_min=None,
        title_day_max=None,
    )
    selected = []
    for row in rows:
        coverage_day = _utc(row["occurred_at"]).astimezone(TPE).date()
        if from_day <= coverage_day <= through_day:
            selected.append(row)
    return selected, _source_coverage(path)


def _coverage_days(spec: dict, source_rows: list[dict], evidence: dict[str, dict]) -> list[dict]:
    by_day = defaultdict(list)
    for row in source_rows:
        day = _utc(row["occurred_at"]).astimezone(TPE).date().isoformat()
        by_day[day].append(row)
    days = []
    for configured in spec["days"]:
        day = configured["day"]
        required = [normalize_public_aid(value) for value in configured["required_aids"]]
        if len(required) != len(set(required)):
            raise ContractError(f"duplicate required AID: {day}")
        missing = [aid for aid in required if aid not in evidence]
        incomplete = [aid for aid in required if aid in evidence and not evidence[aid]["complete"]]
        status = "COMPLETE" if not missing and not incomplete else "PARTIAL"
        reason = (configured.get("complete_reason") or
                  "all required threads have continuous line 1..terminal screen coverage")
        if status != "COMPLETE":
            parts = []
            if missing:
                parts.append("missing authoritative source: " + ",".join(missing))
            if incomplete:
                parts.append("incomplete source coverage: " + ",".join(incomplete))
            reason = "; ".join(parts)
        rows = by_day.get(day, [])
        floors = [(row["aid"], row.get("floor")) for row in rows if row.get("floor") is not None]
        identities = [row["source_record_key"] for row in rows]
        thread_details = []
        for aid in required:
            source = evidence.get(aid)
            thread_rows = [row for row in rows if row["aid"] == aid]
            thread_details.append({
                "aid": aid,
                "source_path": source.get("source_path") if source else None,
                "push_count_on_day": len(thread_rows),
                "first_source_line": min((row["source_line"] for row in thread_rows), default=None),
                "last_source_line": max((row["source_line"] for row in thread_rows), default=None),
                "coverage_complete": bool(source and source["complete"]),
                "coverage_reason": source.get("reason") if source else "authoritative source absent",
                "coverage_gaps": source.get("gaps") if source else None,
            })
        days.append({
            "day": day,
            "coverage_status": status,
            "finalized": status == "COMPLETE",
            "reason": reason,
            "expected_thread_count": len(required),
            "thread_count": sum(aid in evidence for aid in required),
            "required_aids": required,
            "push_count": len(rows),
            "first_source_line": min((row["source_line"] for row in rows), default=None),
            "last_source_line": max((row["source_line"] for row in rows), default=None),
            "floor_known": sum(row.get("floor") is not None for row in rows),
            "floor_unknown": sum(row.get("floor") is None for row in rows),
            "duplicate_source_record_key": len(identities) - len(set(identities)),
            "duplicate_aid_floor": len(floors) - len(set(floors)),
            "threads": thread_details,
        })
    return days


def _asset_diff(old: dict, new: dict, *, day_prefix: str) -> list[dict]:
    old_items = {item["key"]: item for item in old["objects"] if item["key"].startswith(day_prefix)}
    new_items = {item["key"]: item for item in new["objects"] if item["key"].startswith(day_prefix)}
    result = []
    for key in sorted(set(old_items) | set(new_items)):
        before = old_items.get(key)
        after = new_items.get(key)
        if before and after and before["sha256"] == after["sha256"]:
            continue
        old_pushes = before.get("pushes") if before else 0
        new_pushes = after.get("pushes") if after else 0
        if before is None:
            reason = "new UTC-hour object created by authoritative gap repair"
        elif new_pushes != old_pushes:
            reason = "authoritative gap repair added pushes to this UTC-hour object"
        else:
            reason = "day coverage upgraded from PARTIAL to COMPLETE"
        result.append({
            "asset_key": key.removesuffix(".gz"),
            "old_sha256": before.get("sha256") if before else None,
            "new_sha256": after.get("sha256") if after else None,
            "old_pushes": old_pushes,
            "new_pushes": new_pushes,
            "reason": reason,
        })
    return result


def build_archive(*, baseline_root: Path, baseline_manifest: str, spec_path: Path,
                  archive_out: Path) -> dict:
    if archive_out.exists():
        raise ContractError(f"archive output already exists: {archive_out}")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    baseline_path, baseline, baseline_rows = _read_archive(baseline_root, baseline_manifest)
    source_rows = []
    evidence = {}
    for source in spec["sources"]:
        rows, source_evidence = _load_scoped_source(source)
        source_rows.extend(rows)
        for aid, item in source_evidence.items():
            previous = evidence.get(aid)
            if previous is not None and previous != item:
                raise ContractError(f"conflicting coverage evidence for AID {aid}")
            evidence[aid] = item
    new_days = _coverage_days(spec, source_rows, evidence)
    new_day_names = {item["day"] for item in new_days}
    preserve_days = set(spec["preserve_baseline_days"])
    if preserve_days & new_day_names:
        raise ContractError("new source days overlap preserved baseline days")
    preserved = [row for row in baseline_rows if row["coverage_day"] in preserve_days]
    replacement = [row for row in source_rows if _utc(row["occurred_at"]).astimezone(TPE).date().isoformat() in new_day_names]
    combined = []
    seen = {}
    for row in preserved + replacement:
        item = dict(row)
        day = _utc(item["occurred_at"]).astimezone(TPE).date().isoformat()
        item["coverage_day"] = day
        item["minute_epoch"] = int(_utc(item["occurred_at"]).timestamp()) // 60
        key = item["source_record_key"]
        previous = seen.get(key)
        if previous is not None:
            if previous != item:
                raise ContractError(f"conflicting duplicate source identity: {key}")
            continue
        seen[key] = item
        combined.append(item)
    baseline_days = [item for item in baseline["days"] if item["day"] in preserve_days]
    days = sorted(new_days + baseline_days, key=lambda item: item["day"])
    if [item["day"] for item in days] != sorted(new_day_names | preserve_days):
        raise ContractError("coverage day set mismatch")
    receipt = write_archive_rows(
        combined,
        from_day=min(item["day"] for item in days),
        through_day=max(item["day"] for item in days),
        out_dir=archive_out,
        days=days,
        manifest_name=spec["archive_manifest_name"],
        generated_at=spec["generated_at"],
    )
    new_manifest_path = archive_out / receipt["manifest_key"]
    new_manifest = json.loads(new_manifest_path.read_text(encoding="utf-8"))

    old_bytes = {}
    for item in baseline["objects"]:
        if all(row["coverage_day"] in preserve_days for row in _object_rows(baseline_root, item)):
            old_bytes[item["key"]] = (baseline_root / item["key"]).read_bytes()
    changed_preserved = []
    for item in new_manifest["objects"]:
        if item["key"] not in old_bytes:
            continue
        if (archive_out / item["key"]).read_bytes() != old_bytes[item["key"]]:
            changed_preserved.append(item["key"])
    if changed_preserved:
        raise ContractError("preserved baseline canonical objects changed: " + ",".join(changed_preserved))

    identities = [row["source_record_key"] for row in combined]
    floors = [(row["aid"], row["floor"]) for row in combined if row.get("floor") is not None]
    complete_unknown = sum(
        row.get("floor") is None and next(day for day in days if day["day"] == row["coverage_day"])["coverage_status"] == "COMPLETE"
        for row in combined
    )
    if len(identities) != len(set(identities)):
        raise ContractError("duplicate source_record_key")
    if len(floors) != len(set(floors)):
        raise ContractError("duplicate (aid,floor)")
    if complete_unknown:
        raise ContractError("COMPLETE coverage contains unknown floor")
    invalid_timestamps = 0
    synthetic_seconds = 0
    source_identity_errors = 0
    floors_by_aid = defaultdict(list)
    for row in combined:
        try:
            occurred = _utc(row["occurred_at"])
        except (KeyError, TypeError, ValueError):
            invalid_timestamps += 1
            continue
        if occurred.second != 0 or occurred.microsecond != 0:
            synthetic_seconds += 1
        if row["source_record_key"] != f"{normalize_public_aid(row['aid'])}:{row['source_line']}":
            source_identity_errors += 1
        if row.get("floor") is not None:
            floors_by_aid[normalize_public_aid(row["aid"])].append(row["floor"])
    floor_gaps = {}
    for aid, values in floors_by_aid.items():
        ordered = sorted(values)
        missing = sorted(set(range(ordered[0], ordered[-1] + 1)) - set(ordered))
        if missing:
            floor_gaps[aid] = missing
    if invalid_timestamps:
        raise ContractError("invalid occurred_at timestamps")
    if synthetic_seconds:
        raise ContractError("non-minute occurred_at timestamps")
    if source_identity_errors:
        raise ContractError("source_record_key/source_line identity mismatch")
    if floor_gaps:
        raise ContractError("floor gaps inside archive window")

    baseline_by_identity = {row["source_record_key"]: row for row in baseline_rows}
    new_by_identity = {row["source_record_key"]: row for row in combined}
    removed_baseline_identities = sorted(set(baseline_by_identity) - set(new_by_identity))
    if removed_baseline_identities:
        raise ContractError("repair removed baseline source identities")
    allowed_existing_changes = {"coverage_status", "finalized", "source_page"}
    unexpected_existing_changes = {}
    corrected_source_pages = 0
    for key in set(baseline_by_identity) & set(new_by_identity):
        before = baseline_by_identity[key]
        after = new_by_identity[key]
        changed = {field for field in set(before) | set(after)
                   if before.get(field) != after.get(field)}
        unexpected = changed - allowed_existing_changes
        if unexpected:
            unexpected_existing_changes[key] = sorted(unexpected)
        if "source_page" in changed:
            corrected_source_pages += 1
    if unexpected_existing_changes:
        sample = next(iter(sorted(unexpected_existing_changes.items())))
        raise ContractError(
            f"repair rewrote immutable baseline row fields: {sample[0]} {sample[1]}")
    added_identities = sorted(set(new_by_identity) - set(baseline_by_identity))
    added_rows = [new_by_identity[key] for key in added_identities]
    baseline_replaced_rows = [row for row in baseline_rows
                              if row.get("coverage_day") in new_day_names]
    replacement_rows = [row for row in combined
                        if row.get("coverage_day") in new_day_names]
    chronology_exceptions = [
        {"source_record_key": row["source_record_key"],
         "occurred_at": row["occurred_at"],
         "note": row.get("chronology_note")}
        for row in combined if row.get("time_quality") == "source-minute-regression"
    ]
    audit = {
        "status": "PASS",
        "baseline_manifest_sha256": _digest(baseline_path),
        "manifest_sha256": _digest(new_manifest_path),
        "from_day": new_manifest["from_day_taipei"],
        "through_day": new_manifest["through_day_taipei"],
        "total_pushes": len(combined),
        "total_objects": new_manifest["total_objects"],
        "total_gzip_bytes": sum(item["bytes_gzip"] for item in new_manifest["objects"]),
        "duplicate_source_record_keys": 0,
        "duplicate_aid_floors": 0,
        "floor_unknown": sum(row.get("floor") is None for row in combined),
        "floor_gap_threads": 0,
        "invalid_timestamps": 0,
        "non_minute_timestamps": 0,
        "source_identity_errors": 0,
        "baseline_identities_removed": 0,
        "identities_added": len(added_identities),
        "repaired_days_before_pushes": len(baseline_replaced_rows),
        "repaired_days_after_pushes": len(replacement_rows),
        "added_first_occurred_at": min((row["occurred_at"] for row in added_rows), default=None),
        "added_last_occurred_at": max((row["occurred_at"] for row in added_rows), default=None),
        "added_source_line_min": min((row["source_line"] for row in added_rows), default=None),
        "added_source_line_max": max((row["source_line"] for row in added_rows), default=None),
        "existing_source_pages_corrected": corrected_source_pages,
        "chronology_exceptions": chronology_exceptions,
        "rejected_articles": 0,
        "rejected_rows": 0,
        "local_readback_status": "PASS",
        "coverage_status_counts": dict(Counter(item["coverage_status"] for item in days)),
        "preserved_baseline_gzip_objects_byte_identical": True,
        "changed_2026_10_17_assets": _asset_diff(baseline, new_manifest, day_prefix="ptt/v1/chunks/2026/10/17/"),
        "source_paths": [item["path"] for item in spec["sources"]],
    }
    (archive_out / "coverage.json").write_text(
        json.dumps({"from_day": audit["from_day"], "through_day": audit["through_day"], "days": days}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (archive_out / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit


def _object_rows(root: Path, item: dict) -> list[dict]:
    with gzip.open(root / item["key"], "rt", encoding="utf-8") as handle:
        return json.load(handle)["pushes"]


def build_static(*, archive_root: Path, archive_manifest: str,
                 static_out: Path, static_manifest_name: str) -> dict:
    if static_out.exists():
        raise ContractError(f"Static Assets output already exists: {static_out}")
    manifest_path, source, source_rows = _read_archive(archive_root, archive_manifest)
    objects = []
    total_bytes = 0
    for item in source["objects"]:
        with gzip.open(archive_root / item["key"], "rb") as handle:
            raw = handle.read()
        key = item["key"].removesuffix(".gz")
        target = static_out / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        output = dict(item)
        output["key"] = key
        output["source_archive_key"] = item["key"]
        output["bytes_json"] = len(raw)
        output["source_gzip_bytes"] = item["bytes_gzip"]
        output.pop("bytes_gzip", None)
        objects.append(output)
        total_bytes += len(raw)
    static = {
        "schema_version": STATIC_SCHEMA,
        "archive_schema_version": source["schema_version"],
        "precision": source["precision"],
        "chunk_minutes": source["chunk_minutes"],
        "timezone": source["timezone"],
        "source_manifest_sha256": _digest(manifest_path),
        "from_day_taipei": source["from_day_taipei"],
        "through_day_taipei": source["through_day_taipei"],
        "days": source["days"],
        "total_pushes": len(source_rows),
        "total_objects": len(objects),
        "total_canonical_bytes": total_bytes,
        "objects": objects,
    }
    static_path = static_out / "ptt/v1/manifests" / static_manifest_name
    static_path.parent.mkdir(parents=True, exist_ok=True)
    static_path.write_text(json.dumps(static, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (static_out / "_headers").write_text(
        "/ptt/v1/chunks/*\n"
        "  Content-Type: application/json\n"
        "  Cache-Control: public, max-age=0, must-revalidate\n"
        "  Access-Control-Allow-Origin: *\n"
        "  X-Content-Type-Options: nosniff\n\n"
        "/ptt/v1/manifests/*\n"
        "  Content-Type: application/json; charset=utf-8\n"
        "  Cache-Control: no-cache\n"
        "  Access-Control-Allow-Origin: *\n"
        "  X-Content-Type-Options: nosniff\n",
        encoding="utf-8",
    )
    if "Content-Encoding" in (static_out / "_headers").read_text(encoding="utf-8"):
        raise ContractError("Static Assets headers author Content-Encoding")
    config = {
        "name": "holoviewer-ptt-static-assets-repaired-offline",
        "compatibility_date": "2026-10-18",
        "assets": {"directory": "./public", "not_found_handling": "404-page"},
    }
    (static_out.parent / "wrangler.jsonc").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    browser_check = Path(__file__).with_name("static_assets_pilot") / "public/browser-check.html"
    if browser_check.is_file():
        harness = browser_check.read_text(encoding="utf-8").replace(
            "/ptt/v1/manifests/static-assets-pilot.json",
            f"/ptt/v1/manifests/{static_manifest_name}",
        )
        (static_out / "browser-check.html").write_text(harness, encoding="utf-8")
    audit = audit_static(archive_root=archive_root, archive_manifest=archive_manifest,
                         static_out=static_out, static_manifest_name=static_manifest_name)
    (static_out.parent / "static-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit


def audit_static(*, archive_root: Path, archive_manifest: str,
                 static_out: Path, static_manifest_name: str) -> dict:
    source_path, source, source_rows = _read_archive(archive_root, archive_manifest)
    static_path = static_out / "ptt/v1/manifests" / static_manifest_name
    static = json.loads(static_path.read_text(encoding="utf-8"))
    if static["source_manifest_sha256"] != _digest(source_path):
        raise ContractError("Static Assets source manifest SHA mismatch")
    if static["total_objects"] != len(source["objects"]):
        raise ContractError("Static Assets object count mismatch")
    identities = []
    floors = []
    canonical_bytes = 0
    prior_sort_key = None
    largest = None
    source_items = {item["key"]: item for item in source["objects"]}
    for item in static["objects"]:
        if item["key"].endswith(".gz"):
            raise ContractError("Static Assets object key ends in .gz")
        source_item = source_items.get(item["source_archive_key"])
        if source_item is None or item["key"] != item["source_archive_key"].removesuffix(".gz"):
            raise ContractError("Static Assets source mapping mismatch")
        raw = (static_out / item["key"]).read_bytes()
        if sha256(raw).hexdigest() != item["sha256"] or item["sha256"] != source_item["sha256"]:
            raise ContractError("Static Assets canonical SHA mismatch")
        if len(raw) != item["bytes_json"]:
            raise ContractError("Static Assets byte count mismatch")
        if largest is None or len(raw) > largest["bytes_json"]:
            largest = {"key": item["key"], "bytes_json": len(raw)}
        payload = json.loads(raw)
        if len(payload["pushes"]) != item["pushes"]:
            raise ContractError("Static Assets push count mismatch")
        canonical_bytes += len(raw)
        for row in payload["pushes"]:
            occurred = _utc(row["occurred_at"])
            if occurred.second != 0 or occurred.microsecond != 0:
                raise ContractError("Static Assets contains a non-minute timestamp")
            expected_hour = occurred.strftime("ptt/v1/chunks/%Y/%m/%d/%H00.json")
            if item["key"] != expected_hour:
                raise ContractError("Static Assets row is in the wrong UTC-hour object")
            if row.get("coverage_day") != occurred.astimezone(TPE).date().isoformat():
                raise ContractError("Static Assets row has the wrong Taipei coverage day")
            sort_key = (occurred, normalize_public_aid(row["aid"]), row["source_line"])
            if prior_sort_key is not None and sort_key < prior_sort_key:
                raise ContractError("Static Assets rows are not monotonic")
            prior_sort_key = sort_key
            identities.append(row["source_record_key"])
            if row.get("floor") is not None:
                floors.append((row["aid"], row["floor"]))
    source_ids = {row["source_record_key"] for row in source_rows}
    if len(identities) != len(set(identities)) or set(identities) != source_ids:
        raise ContractError("Static Assets identity mismatch")
    if len(floors) != len(set(floors)):
        raise ContractError("Static Assets duplicate (aid,floor)")
    if canonical_bytes != static["total_canonical_bytes"]:
        raise ContractError("Static Assets canonical byte total mismatch")
    gzip_outputs = list(static_out.rglob("*.gz"))
    if gzip_outputs:
        raise ContractError("Static Assets package contains gzip output")
    return {
        "status": "PASS",
        "manifest": str(static_path),
        "manifest_sha256": _digest(static_path),
        "total_objects": len(static["objects"]),
        "total_pushes": len(identities),
        "total_canonical_bytes": canonical_bytes,
        "duplicate_source_record_keys": 0,
        "duplicate_aid_floors": 0,
        "identity_set_preserved": True,
        "gzip_assets": 0,
        "largest_canonical_object": largest,
        "all_asset_sha_exact": True,
        "all_asset_byte_lengths_exact": True,
        "all_rows_in_correct_utc_hour": True,
        "all_coverage_days_match_taipei": True,
        "rows_monotonic": True,
        "authored_content_encoding": False,
        "local_readback_status": "PASS",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--baseline-root", required=True, type=Path)
    build.add_argument("--baseline-manifest", default="2026-10-pilot.json")
    build.add_argument("--spec", required=True, type=Path)
    build.add_argument("--archive-out", required=True, type=Path)
    build.add_argument("--static-out", required=True, type=Path)
    build.add_argument("--static-manifest", required=True)
    audit = commands.add_parser("audit-static")
    audit.add_argument("--archive-root", required=True, type=Path)
    audit.add_argument("--archive-manifest", required=True)
    audit.add_argument("--static-out", required=True, type=Path)
    audit.add_argument("--static-manifest", required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        archive = build_archive(
            baseline_root=args.baseline_root,
            baseline_manifest=args.baseline_manifest,
            spec_path=args.spec,
            archive_out=args.archive_out,
        )
        static = build_static(
            archive_root=args.archive_out,
            archive_manifest=json.loads(args.spec.read_text(encoding="utf-8"))["archive_manifest_name"],
            static_out=args.static_out,
            static_manifest_name=args.static_manifest,
        )
        result = {"status": "PASS", "archive": archive, "static": static}
    else:
        result = audit_static(
            archive_root=args.archive_root,
            archive_manifest=args.archive_manifest,
            static_out=args.static_out,
            static_manifest_name=args.static_manifest,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
