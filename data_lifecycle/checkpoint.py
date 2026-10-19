from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from .common import STATES, content_hash


def new_checkpoint(job_id: str, identities: list[str], *, traffic_budget: int) -> dict:
    if not job_id or traffic_budget < 0 or len(identities) != len(set(identities)):
        raise ValueError("invalid checkpoint input")
    return {"schema_version": "holoviewer-checkpoint-v1", "job_id": job_id, "state": "collecting",
            "pending": list(identities), "completed": [], "attempts": {}, "traffic_used": 0,
            "traffic_budget": traffic_budget, "last_error": None}


def reserve(checkpoint: dict, identity_value: str, *, cost: int = 1) -> dict:
    if cost < 0 or checkpoint["traffic_used"] + cost > checkpoint["traffic_budget"]:
        raise RuntimeError("TRAFFIC_BUDGET_EXCEEDED")
    if identity_value not in checkpoint["pending"]:
        raise ValueError("identity is not pending")
    updated = deepcopy(checkpoint)
    updated["traffic_used"] += cost
    updated["state"] = "verifying"
    return updated


def acknowledge(checkpoint: dict, identity_value: str) -> dict:
    updated = deepcopy(checkpoint)
    if identity_value in updated["pending"]:
        updated["pending"].remove(identity_value)
        updated["completed"].append(identity_value)
    updated["state"] = "complete" if not updated["pending"] else "provisional"
    updated["checkpoint_hash"] = content_hash({k: v for k, v in updated.items() if k != "checkpoint_hash"})
    return updated


def fail(checkpoint: dict, identity_value: str, error: str, *, now: str, max_attempts: int = 3) -> dict:
    updated = deepcopy(checkpoint)
    attempt = updated["attempts"].get(identity_value, 0) + 1
    updated["attempts"][identity_value] = attempt
    updated["last_error"] = error
    updated["state"] = "failed" if attempt >= max_attempts else "retry_pending"
    wait = min(3600, 30 * (2 ** (attempt - 1)))
    updated["retry_after"] = (datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(timezone.utc) + timedelta(seconds=wait)).isoformat().replace("+00:00", "Z")
    assert updated["state"] in STATES
    return updated
