from __future__ import annotations


def build_reconciliation_report(inventory: dict, plans: list[dict]) -> dict:
    sources = inventory.get("sources", [])
    return {"schema_version": "holoviewer-reconciliation-report-v1", "date": inventory.get("date"),
            "missing_dates": [inventory.get("date") for item in sources if item.get("completeness_status") != "COMPLETE"],
            "missing_items": {item["source"]: item.get("missing_ids", []) for item in sources},
            "ptt_source_line_gaps": next((item.get("source_line_gaps", {}) for item in sources if item["source"] == "ptt"), {}),
            "duplicates": {item["source"]: item.get("duplicates", []) for item in sources},
            "revision_conflicts": [a for plan in plans for a in plan.get("actions", []) if a["action"] == "CONFLICT"],
            "unconfirmed": {item["source"]: item.get("unconfirmed_ids", []) for item in sources},
            "recommended_actions": [a for plan in plans for a in plan.get("actions", []) if a["action"] in {"INSERT", "UPDATE", "REPAIR_NEEDED"}],
            "production_writes": 0}


def render_markdown(report: dict) -> str:
    def line(label: str, value: object) -> str:
        import json
        return f"- **{label}:** `{json.dumps(value, ensure_ascii=False, sort_keys=True)}`"
    return "\n".join([f"# Reconciliation — {report['date']}", "", line("Missing dates", report["missing_dates"]),
        line("Missing items", report["missing_items"]), line("PTT source-line gaps", report["ptt_source_line_gaps"]),
        line("Duplicates", report["duplicates"]), line("Revision conflicts", report["revision_conflicts"]),
        line("Unconfirmed", report["unconfirmed"]), line("Recommended actions", report["recommended_actions"]), ""])
