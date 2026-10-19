from __future__ import annotations

from .common import content_hash, identity, parse_time


def _rev(row: dict) -> tuple:
    revision = row.get("revision", 0)
    if type(revision) is not int or revision < 0:
        raise ValueError("revision must be a non-negative integer")
    timestamp = row.get("observed_at") or row.get("updated_at")
    instant = parse_time(timestamp).timestamp() if timestamp else 0.0
    return (revision, instant)


def _index(source: str, rows: list[dict]) -> tuple[dict[str, dict], set[str]]:
    indexed, duplicates = {}, set()
    for row in rows:
        key = identity(source, row)
        if key in indexed:
            duplicates.add(key)
        else:
            indexed[key] = row
    return indexed, duplicates


def build_sync_plan(source: str, source_rows: list[dict], target_rows: list[dict], *, upstream_available: bool = True) -> dict:
    if source not in {"youtube", "ptt"}:
        raise ValueError("unsupported source")
    if not upstream_available:
        return {"schema_version": "holoviewer-sync-plan-v1", "source": source, "dry_run": True,
                "status": "UPSTREAM_UNAVAILABLE", "actions": [], "external_writes": 0}
    targets, target_duplicates = _index(source, target_rows)
    actions = []
    seen = set()
    for row in source_rows:
        key = identity(source, row)
        if key in target_duplicates:
            actions.append({"identity": key, "action": "CONFLICT", "reason": "duplicate-target-identity"})
            continue
        if key in seen:
            actions.append({"identity": key, "action": "CONFLICT", "reason": "duplicate-source-identity"})
            continue
        seen.add(key)
        target = targets.get(key)
        source_hash = row.get("content_hash") or content_hash(row.get("content", row))
        if target is not None and source == "ptt":
            for field in ("push_id", "source_record_key"):
                left, right = row.get(field), target.get(field)
                if left and right and left != right:
                    actions.append({"identity": key, "action": "CONFLICT", "reason": f"{field}-mismatch"})
                    break
            else:
                pass
            if actions and actions[-1]["identity"] == key and actions[-1]["reason"].endswith("-mismatch"):
                continue
        if target is None:
            action, reason = "INSERT", "target-missing"
        else:
            target_hash = target.get("content_hash") or content_hash(target.get("content", target))
            if source_hash == target_hash:
                action, reason = "NOOP", "same-content"
            elif _rev(row) > _rev(target):
                action, reason = "UPDATE", "newer-source-revision"
            elif _rev(row) < _rev(target):
                action, reason = "CONFLICT", "target-newer-than-source"
            else:
                action, reason = "CONFLICT", "equal-revision-different-content"
        if row.get("verified") is False or row.get("completeness_status") in {"UNKNOWN", "PARTIAL"}:
            action, reason = "REPAIR_NEEDED", "source-not-verified"
        actions.append({"identity": key, "action": action, "reason": reason,
                        "source_revision": row.get("revision"), "target_revision": target.get("revision") if target else None})
    plan = {"schema_version": "holoviewer-sync-plan-v1", "source": source, "dry_run": True,
            "status": "PLANNED", "actions": actions, "external_writes": 0}
    plan["plan_hash"] = content_hash(plan)
    return plan
