"""Read-only baseline/checkpoint audit for one PTT AID.

Compares Collector SQLite, Publisher checkpoint, and an optional JSON export of
remote D1 source lines. This module never sends, mutates SQLite/checkpoints, or
writes Cloudflare state. The only optional write is an explicit local JSON
report path chosen by the operator.
"""
import argparse
import json
from pathlib import Path

from .collector_source_preview import open_source
from .live_capture_publisher import inspect_latest_article
from .public_today_contract import ContractError


def _norm_aid(value):
    return str(value or "").lstrip("#")


def _collect_source_lines(value, out):
    if isinstance(value, dict):
        line=value.get("source_line")
        if type(line) is int and line>0:
            out.add(line)
        for child in value.values():
            _collect_source_lines(child,out)
    elif isinstance(value, list):
        for child in value:
            _collect_source_lines(child,out)


def load_remote_lines(path):
    if path is None:
        return None
    body=json.loads(Path(path).read_text(encoding="utf-8"))
    found=set()
    _collect_source_lines(body,found)
    return found


def audit(*, source, state, aid, remote_json=None, known_baseline_source_line=None):
    state_path=Path(state)
    checkpoint=json.loads(state_path.read_text(encoding="utf-8"))
    accepted=checkpoint.get("accepted",{})
    if not isinstance(accepted,dict):
        raise ContractError("checkpoint accepted must be an object")
    checkpoint_baseline=checkpoint.get("baseline_source_line")
    if checkpoint_baseline is not None and (type(checkpoint_baseline) is not int or checkpoint_baseline<0):
        raise ContractError("invalid baseline_source_line")
    if known_baseline_source_line is not None and (
        type(known_baseline_source_line) is not int or known_baseline_source_line<0
    ):
        raise ContractError("invalid known baseline source-line frontier")
    baseline=(checkpoint_baseline if checkpoint_baseline is not None
              else known_baseline_source_line)
    baseline_source=("checkpoint" if checkpoint_baseline is not None
                     else ("operator_evidence" if known_baseline_source_line is not None else None))

    wanted=_norm_aid(aid)
    with open_source(source) as db:
        matches=[]
        for row in db.execute(
            "SELECT id,aid,url FROM articles WHERE board='C_Chat' ORDER BY id DESC"
        ).fetchall():
            if _norm_aid(row[1])==wanted:
                matches.append(row)
        if not matches:
            raise ContractError("AID not found in Collector source")
        article_id,raw_aid,url=matches[0]
        plan=inspect_latest_article(db,article_id=article_id)
        raw_lines=[r[0] for r in db.execute(
            "SELECT source_line FROM pushes WHERE article_id=? ORDER BY source_line",
            (article_id,),
        ).fetchall()]

    accepted_lines=set()
    for key in accepted:
        prefix,sep,line=str(key).rpartition(":")
        if sep and _norm_aid(prefix)==wanted:
            try:
                number=int(line)
            except ValueError:
                continue
            if number>0:
                accepted_lines.add(number)

    ready_lines={row["source_line"] for row in plan.get("candidate_rows",[])}
    pending_lines=set(plan.get("pending_source_lines",[]))
    remote_lines=load_remote_lines(remote_json)

    rows=[]
    counts={}
    for line in raw_lines:
        remote_present=(line in remote_lines) if remote_lines is not None else None
        accepted_present=line in accepted_lines
        ready=line in ready_lines
        pending=line in pending_lines

        if remote_present is True:
            classification="REMOTE_ACKED"
        elif accepted_present and baseline is not None and line<=baseline:
            classification="BASELINE_ACCEPTED_LOCAL_ONLY"
        elif accepted_present:
            classification=("CHECKPOINT_ACCEPTED_REMOTE_UNPROVEN"
                            if remote_lines is None else "CHECKPOINT_REMOTE_MISSING")
        elif baseline is not None and line<=baseline:
            classification=("BASELINE_SKIPPED_PENDING" if pending
                            else "BASELINE_SKIPPED_READY")
        else:
            classification=("UNPUBLISHED_PENDING" if pending
                            else "UNPUBLISHED_READY")
        counts[classification]=counts.get(classification,0)+1
        rows.append({
            "source_line":line,
            "classification":classification,
            "accepted_in_checkpoint":accepted_present,
            "remote_present":remote_present,
            "ready_now":ready,
            "pending_now":pending,
        })

    unpublished=[
        row for row in rows
        if row["remote_present"] is False
    ] if remote_lines is not None else [
        row for row in rows
        if row["classification"] in {
            "BASELINE_ACCEPTED_LOCAL_ONLY","CHECKPOINT_ACCEPTED_REMOTE_UNPROVEN",
            "BASELINE_SKIPPED_PENDING","BASELINE_SKIPPED_READY",
            "UNPUBLISHED_PENDING","UNPUBLISHED_READY",
        }
    ]

    return {
        "status":"READ_ONLY",
        "aid":wanted,
        "collector_rows":len(raw_lines),
        "collector_min_source_line":min(raw_lines,default=None),
        "collector_max_source_line":max(raw_lines,default=None),
        "checkpoint_status":checkpoint.get("status"),
        "checkpoint_accepted":len(accepted_lines),
        "baseline_source_line":baseline,
        "baseline_source":baseline_source,
        "checkpoint_baseline_source_line":checkpoint_baseline,
        "ready_now":len(ready_lines),
        "pending_now":len(pending_lines),
        "remote_comparison_supplied":remote_lines is not None,
        "remote_source_lines":len(remote_lines) if remote_lines is not None else None,
        "counts":counts,
        "unpublished_source_lines":[row["source_line"] for row in unpublished],
        "rows":rows,
        "safety":{
            "remote_writes":0,
            "checkpoint_mutations":0,
            "collector_mutations":0,
            "publisher_process_changes":0,
        },
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Read-only PTT baseline/checkpoint audit")
    p.add_argument("--source",required=True)
    p.add_argument("--state",required=True)
    p.add_argument("--aid",required=True)
    p.add_argument("--remote-json")
    p.add_argument("--known-baseline-source-line",type=int)
    p.add_argument("--output")
    args=p.parse_args(argv)
    result=audit(source=args.source,state=args.state,aid=args.aid,
                 remote_json=args.remote_json,
                 known_baseline_source_line=args.known_baseline_source_line)
    encoded=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)
    if args.output:
        Path(args.output).write_text(encoded+"\n",encoding="utf-8")
    print(encoded)


if __name__=="__main__":
    main()
