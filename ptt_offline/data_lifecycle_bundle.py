"""Build one sanitized #48 -> PR #147 handoff bundle from local evidence.

Input must already be sanitized. This tool performs no network/database access and
never starts or controls Collector/Publisher processes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .data_lifecycle_evidence import (
    build_collector_semantic_evidence,
    build_expected_aid_contract,
    build_source_coverage,
)
from .publisher_telemetry import update_publisher_telemetry


BUNDLE_SCHEMA="holoviewer-ptt-data-lifecycle-bundle-v1"


def build_bundle(raw: dict[str,Any], *, publisher_path: str | Path) -> dict[str,Any]:
    if not isinstance(raw,dict):
        raise TypeError("sanitized input mapping required")

    expected_raw=raw.get("expected_aids") if isinstance(raw.get("expected_aids"),dict) else {}
    coverage_raw=raw.get("coverage") if isinstance(raw.get("coverage"),dict) else {}
    publisher_raw=raw.get("publisher") if isinstance(raw.get("publisher"),dict) else {}
    collector_raw=raw.get("collector") if isinstance(raw.get("collector"),dict) else {}

    expected=build_expected_aid_contract(
        day=expected_raw.get("day"),
        entries=expected_raw.get("entries",[]),
        authority=expected_raw.get("authority",{}),
    )
    coverage=build_source_coverage(
        day=coverage_raw.get("day"),
        aid=coverage_raw.get("aid"),
        article_start_line=coverage_raw.get("article_start_line"),
        final_source_line=coverage_raw.get("final_source_line"),
        lines=coverage_raw.get("lines",[]),
    )
    publisher=update_publisher_telemetry(publisher_path,publisher_raw)
    collector=build_collector_semantic_evidence(
        observed_at=collector_raw.get("observed_at"),
        active_aid=collector_raw.get("active_aid"),
        watermark_source_line=collector_raw.get("watermark_source_line"),
        final_source_line=collector_raw.get("final_source_line"),
        source_line_gaps=collector_raw.get("source_line_gaps"),
        scan_truncated=collector_raw.get("scan_truncated"),
        process_alive=collector_raw.get("process_alive"),
    )

    contract_gaps=[]
    contract_gaps.extend(expected.get("contract_gaps",[]))
    contract_gaps.extend(coverage.get("contract_gaps",[]))
    contract_gaps.extend(
        publisher.get("components",{}).get("Publisher",{}).get("contract_gaps",[])
    )
    contract_gaps.extend(collector.get("contract_gaps",[]))

    return {
        "schema_version":BUNDLE_SCHEMA,
        "sanitized":True,
        "expected_aids":expected,
        "source_coverage":coverage,
        "job_telemetry":publisher,
        "system_health":{"components":{"Collector":collector}},
        "contract_gaps":sorted(set(contract_gaps)),
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Build sanitized PTT Data Lifecycle bundle")
    p.add_argument("--input",required=True)
    p.add_argument("--publisher-state",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args(argv)

    raw=json.loads(Path(args.input).read_text(encoding="utf-8"))
    bundle=build_bundle(raw,publisher_path=args.publisher_state)
    out=Path(args.out)
    with out.open("x",encoding="utf-8") as handle:
        json.dump(bundle,handle,ensure_ascii=False,sort_keys=True,indent=2)
        handle.write("\n")
    print(json.dumps({
        "schema_version":bundle["schema_version"],
        "out":str(out),
        "contract_gaps":bundle["contract_gaps"],
    },ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
