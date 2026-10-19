from __future__ import annotations

from .common import content_hash, identity


def _rev(row: dict) -> tuple:
    return (int(row.get("revision", 0)), str(row.get("observed_at") or row.get("updated_at") or ""))


def build_sync_plan(source: str, source_rows: list[dict], target_rows: list[dict], *, upstream_available: bool = True) -> dict:
    if source not in {"youtube", "ptt"}:
        raise ValueError("unsupported source")
    if not upstream_available:
        return {"schema_version": "holoviewer-sync-plan-v1", "source": source, "dry_run": True,
                "status": "UPSTREAM_UNAVAILABLE", "actions": [], "external_writes": 0}
    targets = {identity(source, row): row for row in target_rows}
    actions = []
    seen = set()
    for row in source_rows:
        key = identity(source, row)
        if key in seen:
            actions.append({"identity": key, "action": "CONFLICT", "reason": "duplicate-source-identity"})
            continue
        seen.add(key)
        target = targets.get(key)
        source_hash = row.get("content_hash") or content_hash(row.get("content", row))
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
