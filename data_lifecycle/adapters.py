"""Read-only adapters for sanitized #47/#48 JSON contract exports.

These functions never open SQLite, D1, R2, or the network. They deliberately do
not promote branch-owned completeness flags into independent authority.
"""
from __future__ import annotations

from .common import validate_day

YOUTUBE_FIELDS = {"video_id", "channel_id", "title", "channel_name", "lifecycle_state",
                  "observed_at", "scheduled_start", "actual_start", "actual_end",
                  "source_revision", "published_at", "metadata_complete", "revision",
                  "verified", "content_hash"}
PTT_FIELDS = {"day", "aid", "source_line", "push_id", "source_record_key", "author",
              "content", "occurred_at", "revision", "verified", "content_hash"}


def _select(row: dict, fields: set[str]) -> dict:
    return {key: value for key, value in row.items() if key in fields}


def _authority(raw: object, day: str, verifier) -> dict | None:
    if not isinstance(raw, dict):
        return None
    if not callable(verifier) or verifier(raw) is not True:
        return None
    if raw.get("verified") is not True or raw.get("day") != day:
        return None
    version = raw.get("version")
    if not isinstance(version, str) or not version:
        return None
    return {"verified": True, "day": day, "version": version,
            "issuer": raw.get("issuer"), "evidence_hash": raw.get("evidence_hash")}


def adapt_youtube_contract(day: str, export: dict, *, authority_verifier=None) -> dict:
    """Adapt #47 roster/Today/history exports without inventing expected videos."""
    validate_day(day)
    roster = export.get("roster")
    today = export.get("today")
    history = export.get("history")
    if not isinstance(roster, dict) or not isinstance(roster.get("version"), str):
        raise ValueError("#47 versioned roster export required")
    channels = roster.get("channels")
    if not isinstance(channels, list) or any(not isinstance(x, dict) or not isinstance(x.get("id"), str) for x in channels):
        raise ValueError("#47 roster channels required")
    allowed = {x["id"] for x in channels}
    rows = []
    if isinstance(today, dict):
        if today.get("schema_version") not in {"public-consumer-v1", "public-today-v1"}:
            raise ValueError("unsupported #47 Today schema")
        for raw in today.get("streams", []):
            if not isinstance(raw, dict) or raw.get("channel_id") not in allowed:
                continue
            row = _select(raw, YOUTUBE_FIELDS)
            row.setdefault("observed_at", today.get("as_of"))
            row.setdefault("revision", 0)
            row.setdefault("verified", today.get("completeness", {}).get("status") == "complete")
            rows.append(row)
    if isinstance(history, dict):
        if history.get("schema_version") != "public-history-import-preview-v1":
            raise ValueError("unsupported #47 History schema")
        for raw in history.get("rows", []):
            if not isinstance(raw, dict) or raw.get("taipei_day") != day or raw.get("channel_id") not in allowed:
                continue
            row = _select(raw, YOUTUBE_FIELDS)
            row["lifecycle_state"] = "ended"
            row["observed_at"] = row.get("published_at")
            row["metadata_complete"] = bool(row.get("actual_start") and row.get("actual_end"))
            row["revision"] = 0
            row["verified"] = row["metadata_complete"]
            rows.append(row)
    # Neither #47 Today nor history preview currently proves the full daily video set.
    authority = _authority(export.get("expected_authority"), day, authority_verifier)
    expected = export.get("expected_video_ids") if authority else None
    if authority and (not isinstance(expected, list) or any(not isinstance(x, str) for x in expected)):
        raise ValueError("verified YouTube expected set required")
    return {"available": export.get("available") is True, "expected_ids": expected,
            "expected_authority": authority, "rows": rows,
            "target_rows": adapt_target_snapshot("youtube", export.get("target")),
            "last_updated_at": export.get("exported_at"),
            "source_version": f"#47:{roster['version']}:{history.get('source_revision') if isinstance(history, dict) else 'today'}",
            "contract_gaps": [] if authority else ["#47-does-not-prove-complete-daily-video-expected-set"]}


def adapt_ptt_contract(day: str, export: dict, *, authority_verifier=None) -> dict:
    """Adapt #48 staged rows, R2 manifest and publisher checkpoint."""
    validate_day(day)
    stage = export.get("day_stage")
    if not isinstance(stage, dict) or stage.get("day") != day or not isinstance(stage.get("rows"), list):
        raise ValueError("#48 day_stage export required")
    rows = []
    for raw in stage["rows"]:
        if not isinstance(raw, dict) or raw.get("day") != day:
            raise ValueError("PTT staged row outside requested day")
        row = _select(raw, PTT_FIELDS)
        row.setdefault("revision", 0)
        row.setdefault("verified", True)
        rows.append(row)
    manifest = export.get("manifest")
    if manifest is not None and (not isinstance(manifest, dict) or manifest.get("schema_version") != "ptt-r2-archive-v1"):
        raise ValueError("unsupported #48 R2 manifest")
    authority = _authority(export.get("expected_authority"), day, authority_verifier)
    expected = export.get("expected_aids") if authority else None
    if authority and (not isinstance(expected, list) or any(not isinstance(x, str) for x in expected)):
        raise ValueError("verified PTT expected AIDs required")
    coverage = export.get("coverage") if isinstance(export.get("coverage"), dict) else {}
    return {"available": export.get("available") is True, "expected_aids": expected,
            "expected_authority": authority, "rows": rows, "coverage": coverage,
            "manifest": manifest, "checkpoint": sanitize_checkpoint(export.get("checkpoint")),
            "target_rows": adapt_target_snapshot("ptt", export.get("target")),
            "last_updated_at": export.get("exported_at"),
            "source_version": "#48:canonical-ptt-v1+ptt-r2-archive-v1",
            "contract_gaps": [] if authority else ["#48-export-does-not-independently-prove-expected-AID-set"]}


def sanitize_checkpoint(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    allowed = ("schema_version", "job_id", "state", "day", "source_identity",
               "last_batch_id", "traffic_used", "traffic_budget")
    return {key: raw.get(key) for key in allowed if key in raw}


def adapt_target_snapshot(source: str, raw: object) -> list[dict]:
    """Strip target exports to fields needed for identity/revision/hash comparison."""
    if raw is None:
        return []
    if not isinstance(raw, dict) or raw.get("sanitized") is not True or not isinstance(raw.get("rows"), list):
        raise ValueError("explicit sanitized target snapshot required")
    common = {"revision", "observed_at", "updated_at", "content_hash", "verified", "completeness_status"}
    identity_fields = {"youtube": {"video_id"}, "ptt": {"day", "aid", "source_line", "push_id", "source_record_key"}}
    if source not in identity_fields:
        raise ValueError("unsupported target source")
    return [{key: value for key, value in row.items() if key in common | identity_fields[source]}
            for row in raw["rows"] if isinstance(row, dict)]


def adapt_contract_snapshot(day: str, raw: dict, *, authority_verifier=None) -> dict:
    return {"youtube": adapt_youtube_contract(day, raw.get("youtube", {}),
                                               authority_verifier=authority_verifier),
            "ptt": adapt_ptt_contract(day, raw.get("ptt", {}),
                                       authority_verifier=authority_verifier)}
