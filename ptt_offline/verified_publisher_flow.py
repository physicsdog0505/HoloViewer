"""Fail-closed #48 bounded Publisher orchestration (offline and injection-only).

The single writer obtains selected rows from a caller's read-only Collector DB,
but does NOT publish inferred times. An explicit positive per-line time authority
must approve every row before a simulated D1 executor can be invoked. All
remaining rows are retained as pending; no implicit skip of earlier lines.
"""
from pathlib import Path
from .collector_day_stage import stage_verified_day
from .publisher_session import load_checkpoint, run_synthetic_one
from .public_today_contract import ContractError, normalize_public_aid
from .publisher_cli import exclusive_lock


def prepare_verified_batch(db, *, day, aid, checkpoint_path, time_verifier):
    """Validate source identity, prefix and all timestamp authority before write."""
    if not callable(time_verifier):
        raise ContractError("independent per-row timestamp verifier required")
    aid=normalize_public_aid(aid)
    # Read checkpoint only to find cursor. run_synthetic_one will independently
    # re-open it with an exclusive lock and fail closed on mismatch.
    initial=stage_verified_day(db,day=day,aid=aid,limit=5)
    cp=load_checkpoint(Path(checkpoint_path),source_identity=initial["source_identity"],
                       day=day,aids=[aid])
    stage=stage_verified_day(db,day=day,aid=aid,limit=5,
                            after_source_line=cp["aids"][aid])
    verified=[]
    pending=[]
    for row in stage["rows"]:
        try:
            approved=time_verifier(row)
        except Exception:
            approved=False
        if approved is not True:
            pending.append({"source_line":row["source_line"],
                            "reason":"timestamp-authority-not-verified"})
        elif not pending:
            verified.append(dict(row))
        else:
            pending.append({"source_line":row["source_line"],
                            "reason":"blocked-behind-pending-source-line"})
    return {"stage":stage,"verified_prefix":verified,"pending":pending,
            "checkpoint":cp}


def run_verified_offline_one(db, *, day, aid, checkpoint_path, time_verifier, executor):
    """One injected simulated transport call only; never a production D1 client."""
    if not callable(executor):
        raise ContractError("injected executor required")
    # Run the preparation and the downstream call under one separate session
    # lock, so two orchestration callers cannot race to stage the same source.
    outer=Path(checkpoint_path+".session.lock")
    with exclusive_lock(outer):
        plan=prepare_verified_batch(db,day=day,aid=aid,
                checkpoint_path=checkpoint_path,time_verifier=time_verifier)
        if not plan["verified_prefix"]:
            return {"status":"PENDING_AUTHORITY" if plan["pending"] else "NO_NEW_ROWS",
                    "pending":plan["pending"]}
        stage=plan["stage"]
        target=plan["verified_prefix"][-1]["source_line"]
        # next_prefix_digest from the full staged selection cannot be used
        # if approval stops mid-batch. Obtain canonical prefix digest exactly
        # through the accepted line by re-staging with a source cursor.
        # The source prefix is calculated by staged source data, never caller input.
        from .collector_day_stage import stage_verified_day as stage_again
        approved_stage=stage_again(db,day=day,aid=aid,
                    after_source_line=target,limit=5)
        next_digest=approved_stage["acked_prefix_digest"]
        result=run_synthetic_one(checkpoint_path=checkpoint_path,
                    source_identity=stage["source_identity"],day=day,aids=[aid],
                    rows=plan["verified_prefix"],executor=executor,
                    source_prefix_digest=stage["acked_prefix_digest"],
                    next_prefix_digest=next_digest)
        result["pending"]=plan["pending"]
        return result
