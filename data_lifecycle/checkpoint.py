from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from .common import STATES, content_hash


def new_checkpoint(job_id: str, identities: list[str], *, traffic_budget: int) -> dict:
    if not job_id or traffic_budget < 0 or len(identities) != len(set(identities)):
        raise ValueError("invalid checkpoint input")
    return {"schema_version": "holoviewer-checkpoint-v1", "job_id": job_id, "state": "collecting",
            "pending": list(identities), "completed": [], "attempts": {}, "traffic_used": 0,
            "traffic_budget": traffic_budget, "last_error": None, "in_flight": None}


def reserve(checkpoint: dict, identity_value: str, *, payload_hash: str, cost: int = 1) -> dict:
    if not isinstance(payload_hash, str) or len(payload_hash) != 64:
        raise ValueError("SHA-256 payload hash required")
    current = checkpoint.get("in_flight")
    if current:
        if (current.get("identity") == identity_value and current.get("cost") == cost
                and current.get("payload_hash") == payload_hash):
            return deepcopy(checkpoint)
        raise RuntimeError("CHECKPOINT_HAS_IN_FLIGHT_RESERVATION")
    if cost < 0 or checkpoint["traffic_used"] + cost > checkpoint["traffic_budget"]:
        raise RuntimeError("TRAFFIC_BUDGET_EXCEEDED")
    if identity_value not in checkpoint["pending"]:
        raise ValueError("identity is not pending")
    updated = deepcopy(checkpoint)
    updated["traffic_used"] += cost
    updated["state"] = "verifying"
    reservation = {"identity": identity_value, "cost": cost, "job_id": updated["job_id"],
                   "payload_hash": payload_hash}
    reservation["digest"] = content_hash(reservation)
    updated["in_flight"] = reservation
    return updated


def acknowledge(checkpoint: dict, identity_value: str, ack: dict) -> dict:
    updated = deepcopy(checkpoint)
    reserved = updated.get("in_flight")
    expected = {"status": "ACK", "identity": identity_value,
                "reservation_digest": reserved.get("digest") if isinstance(reserved, dict) else None}
    if not reserved or reserved.get("identity") != identity_value or any(ack.get(k) != v for k, v in expected.items()):
        raise ValueError("exact reservation ACK required")
    if identity_value in updated["pending"]:
        updated["pending"].remove(identity_value)
        updated["completed"].append(identity_value)
    updated["in_flight"] = None
    updated["state"] = "complete" if not updated["pending"] else "provisional"
    updated["checkpoint_hash"] = content_hash({k: v for k, v in updated.items() if k != "checkpoint_hash"})
    return updated


def fail(checkpoint: dict, identity_value: str, error: str, *, now: str, max_attempts: int = 3) -> dict:
    updated = deepcopy(checkpoint)
    reserved = updated.get("in_flight")
    if not reserved or reserved.get("identity") != identity_value:
        raise ValueError("failure must match in-flight reservation")
    attempt = updated["attempts"].get(identity_value, 0) + 1
    updated["attempts"][identity_value] = attempt
    updated["last_error"] = error
    updated["state"] = "failed" if attempt >= max_attempts else "retry_pending"
    updated["in_flight"] = None
    wait = min(3600, 30 * (2 ** (attempt - 1)))
    updated["retry_after"] = (datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(timezone.utc) + timedelta(seconds=wait)).isoformat().replace("+00:00", "Z")
    assert updated["state"] in STATES
    return updated
