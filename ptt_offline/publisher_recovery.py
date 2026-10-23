"""Durable exact-batch reconciliation for #48 resilient Publisher recovery.

This module never selects new Collector rows. It operates only on the exact
pending batch persisted before an ambiguous HTTP outcome.
"""
from __future__ import annotations

import time
from pathlib import Path

from .owner_http_transport import RemoteOutcomeUnknown, ReconcileUnavailable
from .publisher_cli import atomic_receipt
from .resumable_publisher import apply_ack, new_checkpoint
from .d1_transport_contract import execute_once
from .public_today_contract import ContractError

BACKOFF_SECONDS=(30,60,120,300)
MAX_RECOVERY_ATTEMPTS=8

def _delay(attempt):
    return BACKOFF_SECONDS[min(max(0,attempt-1),len(BACKOFF_SECONDS)-1)]

def _validate_pending(current):
    batch=current.get("pending_batch")
    updates=current.get("pending_accepted_updates")
    if current.get("status")!="REMOTE_UNCERTAIN":
        raise ContractError("recovery requires REMOTE_UNCERTAIN state")
    if not isinstance(batch,dict) or batch.get("batch_id")!=current.get("pending_batch_id"):
        raise ContractError("durable pending batch missing or mismatched")
    if not isinstance(updates,dict) or not updates:
        raise ContractError("durable pending accepted-update evidence missing")
    rows=batch.get("rows")
    if not isinstance(rows,list) or not rows:
        raise ContractError("durable pending rows missing")
    expected={row.get("source_record_key") for row in rows}
    if None in expected or expected!=set(updates):
        raise ContractError("pending accepted-update evidence does not match batch")
    return batch,updates

def _clean_success_state(current,batch,updates,*,remote_commit):
    accepted=dict(current.get("accepted") or {})
    accepted.update(updates)
    return {
        "status":"ACKED",
        "source_identity":current.get("source_identity"),
        "accepted":accepted,
        "last_batch_id":batch["batch_id"],
        "baseline_source_line":current.get("baseline_source_line"),
        "legacy_backlog_fence_v2":bool(current.get("legacy_backlog_fence_v2")),
        "reconciled_from_remote_commit":bool(remote_commit or current.get("reconciled_from_remote_commit")),
        "pending_count":current.get("pending_count",0),
        "recovery_attempts":0,
    }

def _wait_state(current,attempt,now,reason):
    updated=dict(current)
    updated["status"]="REMOTE_UNCERTAIN"
    updated["recovery_attempts"]=attempt
    updated["next_reconcile_at"]=now+_delay(attempt)
    updated["last_recovery_error"]=reason
    return updated

def recover_pending_state(state_path,*,reconcile_executor,publish_executor,clock=time.time,allow_replay=True):
    """Reconcile one durable pending batch.

    Outcomes:
      ALL_PRESENT -> local ACK without replay
      NONE_PRESENT -> exact same-batch replay once
      PARTIAL_OR_MISMATCH -> STOP_MANUAL for this source
      unavailable/ambiguous -> persisted bounded backoff
    """
    path=Path(state_path)
    if not path.exists():
        raise ContractError("recovery state missing")
    import json
    current=json.loads(path.read_text(encoding="utf-8"))
    if current.get("status")=="STOP_MANUAL":
        return {"status":"RECOVERY_QUARANTINED","aid":current.get("pending_aid"),"sent":0}
    try:
        batch,updates=_validate_pending(current)
    except ContractError:
        stopped=dict(current)
        stopped["status"]="STOP_MANUAL"
        stopped["recovery_reason"]="LEGACY_OR_INVALID_PENDING_ENVELOPE"
        atomic_receipt(path,stopped)
        return {"status":"RECOVERY_QUARANTINED","aid":current.get("pending_aid"),
                "sent":0,"recovery_reason":"LEGACY_OR_INVALID_PENDING_ENVELOPE"}
    now=float(clock())
    due=current.get("next_reconcile_at")
    if isinstance(due,(int,float)) and now<due:
        return {"status":"RECOVERY_WAIT","aid":current.get("pending_aid"),
                "retry_after_seconds":max(1,int(due-now)),"sent":0}

    attempt=int(current.get("recovery_attempts") or 0)+1
    if attempt>MAX_RECOVERY_ATTEMPTS:
        stopped=dict(current)
        stopped["status"]="STOP_MANUAL"
        stopped["recovery_reason"]="RECOVERY_ATTEMPTS_EXHAUSTED"
        atomic_receipt(path,stopped)
        return {"status":"RECOVERY_QUARANTINED","aid":current.get("pending_aid"),"sent":0}

    try:
        receipt=reconcile_executor(batch)
    except ReconcileUnavailable as exc:
        atomic_receipt(path,_wait_state(current,attempt,now,type(exc).__name__))
        return {"status":"RECOVERY_WAIT","aid":current.get("pending_aid"),
                "retry_after_seconds":_delay(attempt),"sent":0}

    if not isinstance(receipt,dict) or receipt.get("batch_id")!=batch.get("batch_id") or receipt.get("digest")!=batch.get("digest"):
        atomic_receipt(path,_wait_state(current,attempt,now,"RECONCILE_IDENTITY_MISMATCH"))
        return {"status":"RECOVERY_WAIT","aid":current.get("pending_aid"),
                "retry_after_seconds":_delay(attempt),"sent":0}

    outcome=receipt.get("outcome")
    if outcome=="ALL_PRESENT":
        atomic_receipt(path,_clean_success_state(current,batch,updates,remote_commit=True))
        rows=len(batch["rows"])
        return {"status":"RECOVERED_REMOTE_COMMIT","aid":current.get("pending_aid"),
                "sent":0,"batch_id":batch["batch_id"],"reconcile_reads":1,
                "budget_batches":1,"budget_rows":rows,
                "budget_modeled_writes":2+2*rows,
                "budget_modeled_queries":5+2*rows}

    if outcome=="NONE_PRESENT":
        if not allow_replay:
            atomic_receipt(path,_wait_state(current,attempt,now,"ADMISSION_BUDGET_BLOCKED"))
            return {"status":"RECOVERY_WAIT","aid":current.get("pending_aid"),
                    "retry_after_seconds":_delay(attempt),"sent":0,
                    "reconcile_reads":1,"budget_blocked":True}
        try:
            ack=execute_once(batch=batch,executor=publish_executor,
                max_rows=len(batch["rows"]),
                max_queries=min(150,2+5*len(batch["rows"])),
                max_written=min(80,2+2*len(batch["rows"])))
            aids=sorted({row["aid"] for row in batch["rows"]})
            checkpoint=new_checkpoint(source_identity=batch["source_identity"],day=batch["day"],aids=aids)
            apply_ack(checkpoint=checkpoint,batch=batch,ack=ack)
        except (RemoteOutcomeUnknown,ContractError) as exc:
            atomic_receipt(path,_wait_state(current,attempt,now,type(exc).__name__))
            return {"status":"RECOVERY_WAIT","aid":current.get("pending_aid"),
                    "retry_after_seconds":_delay(attempt),"sent":0,
                    "reconcile_reads":1}
        atomic_receipt(path,_clean_success_state(current,batch,updates,remote_commit=False))
        rows=len(batch["rows"])
        return {"status":"ACK","recovery_status":"RECOVERED_REPLAY",
                "aid":current.get("pending_aid"),
                "sent":rows,"batch_id":batch["batch_id"],
                "http_posts":1,"reconcile_reads":1,
                "budget_batches":1,"budget_rows":rows,
                "budget_modeled_writes":2+2*rows,
                "budget_modeled_queries":5+2*rows}

    stopped=dict(current)
    stopped["status"]="STOP_MANUAL"
    stopped["recovery_reason"]="PARTIAL_OR_MISMATCH"
    stopped["reconcile_receipt"]={
        "batch_id":receipt.get("batch_id"),
        "digest":receipt.get("digest"),
        "rows_checked":receipt.get("rows_checked"),
        "present":receipt.get("present"),
        "mismatched":receipt.get("mismatched"),
    }
    atomic_receipt(path,stopped)
    return {"status":"RECOVERY_QUARANTINED","aid":current.get("pending_aid"),
            "sent":0,"reconcile_reads":1}
