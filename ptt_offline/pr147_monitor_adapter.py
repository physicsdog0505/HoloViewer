"""Pure projections from #48 sanitized evidence into PR #147 reader inputs.

No database/network/process access. Missing fields stay null/UNKNOWN through the
consumer; this module does not promote presence into success.
"""
from __future__ import annotations

from typing import Any


CHECKPOINT_KEYS=(
    "schema_version","job_id","state","day","source_identity",
    "last_batch_id","traffic_used","traffic_budget",
)


def build_pr147_sync_monitor_evidence(
    *,
    publisher_checkpoint: dict[str,Any] | None,
    job_telemetry: dict[str,Any] | None,
    publisher_observed_at: str | None=None,
    publisher_last_progress_at: str | None=None,
    r2_manifest: dict[str,Any] | None=None,
    d1_snapshot: dict[str,Any] | None=None,
) -> dict[str,Any]:
    checkpoint=None
    if isinstance(publisher_checkpoint,dict):
        checkpoint={key:publisher_checkpoint.get(key)
                    for key in CHECKPOINT_KEYS if key in publisher_checkpoint}

    telemetry=job_telemetry if isinstance(job_telemetry,dict) else None
    contract_gaps=[]
    if checkpoint is None:
        contract_gaps.append("publisher-checkpoint-unavailable")
    if telemetry is None:
        contract_gaps.append("publisher-job-telemetry-unavailable")
    if r2_manifest is None:
        contract_gaps.append("r2-manifest-unavailable")
    if d1_snapshot is None:
        contract_gaps.append("sanitized-d1-snapshot-unavailable")

    return {
        "schema_version":"holoviewer-ptt-pr147-sync-input-v1",
        "sanitized":True,
        "publisher_checkpoint":checkpoint,
        "publisher_observed_at":publisher_observed_at,
        "publisher_last_progress_at":publisher_last_progress_at,
        "job_telemetry":telemetry,
        "r2_manifest":r2_manifest,
        "d1_snapshot":d1_snapshot,
        "contract_gaps":contract_gaps,
    }


def build_pr147_system_health_evidence(
    *,
    collector: dict[str,Any] | None,
    publisher: dict[str,Any] | None=None,
    archive: dict[str,Any] | None=None,
    production_api: dict[str,Any] | None=None,
) -> dict[str,Any]:
    components={}
    for name,value in (
        ("Collector",collector),
        ("Publisher",publisher),
        ("Archive",archive),
        ("Production API",production_api),
    ):
        if isinstance(value,dict):
            components[name]=value
    return {
        "schema_version":"holoviewer-ptt-pr147-health-input-v1",
        "sanitized":True,
        "components":components,
        "contract_gaps":[
            f"{name.lower().replace(' ','-')}-health-evidence-unavailable"
            for name,value in (
                ("Publisher",publisher),
                ("Archive",archive),
                ("Production API",production_api),
            )
            if not isinstance(value,dict)
        ],
    }
