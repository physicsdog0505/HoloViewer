from __future__ import annotations

import argparse
import json
from pathlib import Path

from .inventory import build_inventory
from .planner import build_sync_plan
from .report import build_reconciliation_report, render_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline HoloViewer lifecycle audit (always dry-run)")
    parser.add_argument("--date", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--markdown-out", required=True)
    args = parser.parse_args()
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    inventory = build_inventory(args.date, snapshot)
    plans = []
    for source in ("youtube", "ptt"):
        data = snapshot.get(source, {})
        plans.append(build_sync_plan(source, data.get("rows", []), data.get("target_rows", []),
                                     upstream_available=data.get("available") is True))
    report = build_reconciliation_report(inventory, plans)
    payload = {"inventory": inventory, "plans": plans, "report": report}
    Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path(args.markdown_out).write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
