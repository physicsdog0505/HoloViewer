"""Single-attempt offline Publisher session with atomic local ACK checkpoint.

This module contains no production connector. The caller supplies synthetic
rows and an injected executor. A failure before exact ACK never advances
durable progress; a successful ACK atomically persists only redacted metadata.
"""
from __future__ import annotations

import json
from pathlib import Path

from .public_today_contract import ContractError, normalize_public_aid
from .publisher_cli import atomic_receipt, exclusive_lock
from .resumable_publisher import new_checkpoint, make_batch, apply_ack
from .d1_transport_contract import execute_once


def load_checkpoint(path: Path, *, source_identity: str, day: str, aids) -> dict:
    expected=new_checkpoint(source_identity=source_identity,day=day,aids=aids)
    if not path.exists():
        return expected
    try:
        current=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc:
        raise ContractError("unreadable checkpoint") from exc
    if not isinstance(current,dict):
        raise ContractError("malformed checkpoint")
    if (current.get("version") != 1 or
        current.get("source_identity") != expected["source_identity"] or
        current.get("day") != expected["day"] or
        set(current.get("aids",{})) != set(expected["aids"])):
        raise ContractError("checkpoint scope/source identity mismatch")
    if any(type(v) is not int or v < 0 for v in current["aids"].values()):
        raise ContractError("invalid persisted source checkpoint")
    last=current.get("last_batch_id")
    if last is not None and (not isinstance(last,str) or not last.startswith("ptt48:")):
        raise ContractError("invalid persisted batch identity")
    return current


def run_synthetic_one(*, checkpoint_path: str, source_identity: str,
                      day: str, aids, rows: list[dict], executor) -> dict:
    """One locked batch; only an exact ACK permits advancing local checkpoint."""
    path=Path(checkpoint_path).expanduser().resolve()
    path.parent.mkdir(parents=True,exist_ok=True)
    with exclusive_lock(path.with_suffix(path.suffix+".lock")):
        checkpoint=load_checkpoint(path,source_identity=source_identity,
                                   day=day,aids=aids)
        batch=make_batch(checkpoint=checkpoint,rows=rows)
        if not batch["rows"]:
            return {"status":"NO_NEW_ROWS","checkpoint":checkpoint}
        ack=execute_once(batch=batch,executor=executor)  # one call, never retry
        updated=apply_ack(checkpoint=checkpoint,batch=batch,ack=ack)
        # No source content, secrets or per-push payload in persisted checkpoint.
        atomic_receipt(path,updated)
        return {"status":"ACK","checkpoint":updated,
                "batch_id":ack["batch_id"],
                "logical_rows_acked":ack["logical_rows_acked"],
                "d1_rows_written":ack["d1_rows_written"]}
