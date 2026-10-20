"""Read-only diagnosis for current-day Collector -> Publisher handoff.

Inspects Collector SQLite plus local Publisher checkpoints only. It never reads
secrets, contacts the network, mutates checkpoints, or publishes rows.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from .collector_source_preview import open_source
from .live_capture_publisher import active_article_ids, inspect_latest_article, state_for_source


def _load_state(path: Path) -> dict[str, Any]:
    try:
        body=json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return body if isinstance(body,dict) else {}


def diagnose(*, source: str, state_dir: str, max_articles: int = 4) -> dict[str, Any]:
    state_root=Path(state_dir)
    rows=[]
    with open_source(source) as db:
        article_ids=active_article_ids(db,limit=max_articles)
        for article_id in article_ids:
            plan=inspect_latest_article(db,article_id=article_id)
            if plan.get("status")!="READY":
                rows.append({"article_id":article_id,"status":plan.get("status")})
                continue

            state_path=Path(state_for_source(state_root,plan["source_identity"]))
            checkpoint=_load_state(state_path)
            baseline=checkpoint.get("baseline_source_line")
            accepted=checkpoint.get("accepted")
            accepted_count=len(accepted) if isinstance(accepted,dict) else 0

            candidates=plan.get("candidate_rows",[])
            pending=set(plan.get("pending_source_lines",[]))
            candidate_after=[
                row for row in candidates
                if not isinstance(baseline,int) or row.get("source_line",0)>baseline
            ]
            pending_after=sorted(
                line for line in pending
                if not isinstance(baseline,int) or line>baseline
            )
            days=Counter(row.get("day") for row in candidates if isinstance(row.get("day"),str))
            after_days=Counter(row.get("day") for row in candidate_after if isinstance(row.get("day"),str))
            latest_candidate=max((row.get("source_line",0) for row in candidates),default=None)
            latest_after=max((row.get("source_line",0) for row in candidate_after),default=None)

            rows.append({
                "article_id":article_id,
                "status":"READY",
                "aid":plan.get("aid"),
                "source_identity":plan.get("source_identity"),
                "checkpoint_exists":state_path.is_file(),
                "checkpoint_status":checkpoint.get("status"),
                "baseline_source_line":baseline,
                "accepted_count":accepted_count,
                "checked_source_rows":plan.get("checked_source_rows"),
                "latest_scanned_source_line":plan.get("latest_scanned_source_line"),
                "latest_candidate_source_line":latest_candidate,
                "candidate_count":len(candidates),
                "candidate_day_counts":dict(sorted(days.items())),
                "candidate_after_baseline_count":len(candidate_after),
                "candidate_after_baseline_day_counts":dict(sorted(after_days.items())),
                "latest_candidate_after_baseline":latest_after,
                "pending_count":len(pending),
                "pending_after_baseline_count":len(pending_after),
                "pending_after_baseline_first":pending_after[:10],
                "floor_authoritative":plan.get("floor_authoritative"),
                "scan_truncated":plan.get("scan_truncated"),
            })
    return {
        "schema_version":"ptt-current-day-handoff-diagnosis-v1",
        "read_only":True,
        "articles":rows,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Read-only Collector -> Publisher handoff diagnosis")
    p.add_argument("--source",required=True)
    p.add_argument("--state-dir",required=True)
    p.add_argument("--max-articles",type=int,default=4,choices=range(1,9))
    args=p.parse_args(argv)
    print(json.dumps(diagnose(source=args.source,state_dir=args.state_dir,
                              max_articles=args.max_articles),
                     ensure_ascii=False,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
