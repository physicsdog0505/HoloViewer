"""Read-only exact Collector line eligibility receipt for #48 owner acceptance.

Never publishes, writes source SQLite, displays push content or accesses secrets.
"""
import argparse
import json
from .collector_source_preview import open_source
from .live_capture_publisher import inspect_latest_article

def audit(source, aid, source_line):
    if not isinstance(aid,str) or not aid or type(source_line) is not int or source_line < 1:
        raise ValueError("explicit AID and positive source_line required")
    db=open_source(source)
    try:
        match=db.execute("SELECT id FROM articles WHERE board='C_Chat' AND aid=? ORDER BY id DESC LIMIT 1",(aid.lstrip('#'),)).fetchone()
        if not match:
            return {"status":"ARTICLE_NOT_FOUND","aid":aid,"source_line":source_line}
        plan=inspect_latest_article(db,article_id=match[0])
        item=next((r for r in plan.get("candidate_rows",[]) if r["source_line"]==source_line),None)
        return {
            "status":"ELIGIBLE" if item else "PENDING" if source_line in plan.get("pending_source_lines",[]) else "LINE_NOT_IN_SCAN",
            "aid":plan.get("aid"),"source_line":source_line,
            "occurred_at":item["occurred_at"] if item else None,
            "day":item["day"] if item else None,
            "scan_truncated":plan.get("scan_truncated"),
            "checked_source_rows":plan.get("checked_source_rows"),
            "publish_attempted":False,"remote_queries":0,"remote_writes":0
        }
    finally:
        db.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",required=True)
    p.add_argument("--aid",required=True)
    p.add_argument("--source-line",type=int,required=True)
    args=p.parse_args()
    print(json.dumps(audit(args.source,args.aid,args.source_line),ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
