"""Owner-run real Collector SQLite source audit; no mutation/network/secret.

Run python3 -B -m ptt_offline.source_audit_cli --source /path/to/owner.db
    --day YYYY-MM-DD --aid '#XXXXXXXX'
Output contains source identities and classifications, never push bodies.
"""
import argparse
import json
from .collector_source_preview import open_source
from .source_audit_stage import audit_source_day


def audit(*,source,day,aid):
    with open_source(source) as db:
        evidence=audit_source_day(db,day=day,aid=aid)
    return {"mode":"SOURCE_READ_ONLY","day":evidence["day"],"aid":evidence["aid"],
        "identity":evidence["identity"],
        "source_rows_examined":evidence["source_rows_examined"],
        "inferred_count":len(evidence["inferred_day"]),
        "pending_count":len(evidence["pending"]),
        "pending_line_reasons":[{"source_line":r["source_line"],"reason":r["reason"]}
            for r in evidence["pending"][:20]],
        "checkpoint_blocked_at":evidence["checkpoint_blocked_at"],
        "publishable_count":0,
        "coverage":evidence["coverage"]}


def main(argv=None):
    p=argparse.ArgumentParser(description="Bounded real Collector read-only PTT audit")
    p.add_argument("--source",required=True)
    p.add_argument("--day",required=True)
    p.add_argument("--aid",required=True)
    args=p.parse_args(argv)
    print(json.dumps(audit(source=args.source,day=args.day,aid=args.aid),
                     ensure_ascii=False,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
