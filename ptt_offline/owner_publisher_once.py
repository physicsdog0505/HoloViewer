"""Owner one-shot PTT publisher from canonical Collector SQLite.

Default --inspect is read-only. --send requires the exact source identity,
external manually reviewed event-time evidence and HMAC secret environment.
Never retries remote errors or advances checkpoint before exact ACK.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from .collector_source_preview import open_source
from .collector_day_stage import stage_verified_day
from .source_audit_stage import audit_source_day
from .verified_publisher_flow import run_verified_offline_one
from .owner_http_transport import owner_signed_http_executor
from .public_today_contract import ContractError


def row_fingerprint(row):
    keys=("aid","source_line","source_record_key","occurred_at","kind",
          "author","content","source_url")
    raw=json.dumps({k:row.get(k) for k in keys},sort_keys=True,separators=(",",":"),
                   ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_manual_evidence(path, *, source_identity, day, aid):
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    if (data.get("source_identity")!=source_identity or data.get("day")!=day
        or data.get("aid")!=aid or data.get("authority")!="OWNER_REVIEWED_EXTERNAL"):
        raise ContractError("independent manual time evidence scope mismatch")
    entries=data.get("approved_rows")
    if not isinstance(entries,list) or len(entries)>5:
        raise ContractError("bounded positive approved time evidence required")
    approved={}
    for entry in entries:
        line=entry.get("source_line")
        fingerprint=entry.get("row_sha256")
        if (type(line) is not int or line<1 or not isinstance(fingerprint,str)
            or len(fingerprint)!=64 or line in approved):
            raise ContractError("invalid unique source time evidence")
        approved[line]=fingerprint
    return lambda row: approved.get(row["source_line"])==row_fingerprint(row)


def main(argv=None):
    p=argparse.ArgumentParser(description="Exactly one Collector-to-D1 Publisher attempt")
    p.add_argument("--source",required=True)
    p.add_argument("--day",required=True)
    p.add_argument("--aid",required=True)
    p.add_argument("--checkpoint",required=True)
    p.add_argument("--inspect",action="store_true")
    p.add_argument("--draft-evidence")
    p.add_argument("--send",action="store_true")
    p.add_argument("--approve-source")
    p.add_argument("--evidence")
    p.add_argument("--endpoint")
    args=p.parse_args(argv)
    if sum(bool(x) for x in (args.inspect,args.send,args.draft_evidence)) != 1:
        p.error("choose exactly one of --inspect, --draft-evidence or --send")
    with open_source(args.source) as db:
        if args.inspect:
            audit=audit_source_day(db,day=args.day,aid=args.aid)
            receipt={"mode":"READ_ONLY","source_identity":audit["identity"],
                     "day":args.day,"aid":audit["aid"],"source_rows_examined":audit["source_rows_examined"],
                     "candidate_rows":len(audit["inferred_day"]),"pending_rows":len(audit["pending"]),
                     "coverage":audit["coverage"],"d1_requests":0}
        else:
            initial=stage_verified_day(db,day=args.day,aid=args.aid,limit=5)
        if args.inspect:
            pass
        elif args.draft_evidence:
            proposal={"source_identity":initial["source_identity"],"day":args.day,
                      "aid":initial["aid"],"authority":"PENDING_REVIEW",
                      "approved_rows":[{"source_line":row["source_line"],
                        "row_sha256":row_fingerprint(row),
                        "displayed_time":str(row.get("ptt_date"))+" "+str(row.get("ptt_time")),
                        "candidate_utc":row["occurred_at"]} for row in initial["rows"]]}
            with open(args.draft_evidence,"x",encoding="utf-8") as output:
                json.dump(proposal,output,ensure_ascii=False,indent=2)
            receipt={"mode":"EVIDENCE_DRAFT_NOT_APPROVED","path":args.draft_evidence,
                     "rows":len(proposal["approved_rows"]),"d1_requests":0}
        else:
            if args.approve_source!=initial["source_identity"] or not args.evidence:
                raise ContractError("specific owner source approval and external evidence required")
            secret=os.environ.get("PTT_PUBLISH_HMAC_SECRET","")
            sender=owner_signed_http_executor(endpoint=args.endpoint or "",secret=secret,
                                               allow_write=True)
            verify=load_manual_evidence(args.evidence,
                    source_identity=initial["source_identity"],
                    day=args.day,aid=initial["aid"])
            receipt=run_verified_offline_one(db,day=args.day,aid=initial["aid"],
                checkpoint_path=args.checkpoint,time_verifier=verify,executor=sender)
    print(json.dumps(receipt,ensure_ascii=False,sort_keys=True,default=str))

if __name__=="__main__":
    main()
