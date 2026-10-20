"""Issue #160 daily finalized PTT -> Workers Static Assets archive seam.

This module is deliberately production-inert.  It consumes only a sanitized
VERIFIED_COMPLETE daily finalization receipt, stages immutable canonical JSON
assets, prepares a delivery plan, verifies independently fetched HTTP bytes,
and emits the already-reviewed Archive evidence contracts.

It does not run wrangler, subprocesses, PTT login/repair, D1/R2 writers, or a
Production deployment.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import quote

from .archive_job_evidence import (
    ArchiveEvidenceError,
    build_archive_job_evidence,
    build_readback_receipt,
)

FINALIZATION_SCHEMA="holoviewer-ptt-daily-finalization-v1"
PACKAGE_SCHEMA="holoviewer-ptt-daily-static-package-v1"
DELIVERY_PLAN_SCHEMA="holoviewer-static-assets-delivery-plan-v1"
DAY_RE=re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEX64=re.compile(r"^[0-9a-f]{64}$")
SAFE_JOB_ID=re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


class DailyArchiveError(ValueError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,ensure_ascii=False,sort_keys=True,separators=(",",":")
    ).encode("utf-8")


def _digest_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _require_sha(value: object,name: str) -> str:
    if not isinstance(value,str) or not HEX64.fullmatch(value):
        raise DailyArchiveError(f"{name} must be lowercase SHA-256")
    return value


def _safe_relative_key(value: object) -> str:
    if not isinstance(value,str) or not value or value.startswith("/"):
        raise DailyArchiveError("relative object key required")
    parts=value.split("/")
    if any(part in {"","..","."} for part in parts):
        raise DailyArchiveError("unsafe relative object key")
    if not value.endswith(".json"):
        raise DailyArchiveError("Static Assets object must be canonical .json")
    return value


def validate_finalization_receipt(receipt: object) -> dict[str,Any]:
    if not isinstance(receipt,dict):
        raise DailyArchiveError("daily finalization receipt required")
    if receipt.get("schema_version")!=FINALIZATION_SCHEMA:
        raise DailyArchiveError("unsupported daily finalization schema")
    if receipt.get("sanitized") is not True:
        raise DailyArchiveError("sanitized daily finalization receipt required")
    day=receipt.get("day")
    if not isinstance(day,str) or not DAY_RE.fullmatch(day):
        raise DailyArchiveError("canonical Taipei day required")
    if receipt.get("state")!="VERIFIED_COMPLETE":
        raise DailyArchiveError("source day is not VERIFIED_COMPLETE")
    if receipt.get("archive_ready") is not True:
        raise DailyArchiveError("archive_ready=true required")

    expected=receipt.get("expected_set")
    if not isinstance(expected,dict):
        raise DailyArchiveError("expected-set binding required")
    aids=expected.get("expected_aids")
    if not isinstance(aids,list) or not aids or not all(
        isinstance(aid,str) and aid.strip("#") for aid in aids
    ):
        raise DailyArchiveError("non-empty expected AID set required")
    normalized=[aid.strip("#") for aid in aids]
    if len(normalized)!=len(set(normalized)):
        raise DailyArchiveError("duplicate expected AID")

    authority=expected.get("authority")
    if not isinstance(authority,dict) or authority.get("verified") is not True:
        raise DailyArchiveError("verified expected-AID authority required")
    if authority.get("day")!=day:
        raise DailyArchiveError("expected-AID authority day mismatch")
    evidence_digest=receipt.get("evidence_digest")
    _require_sha(evidence_digest,"finalization evidence_digest")
    return receipt


def _validate_payload(*,raw: bytes,day: str,expected_aids: set[str]) -> tuple[int,list[str]]:
    try:
        payload=json.loads(raw)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise DailyArchiveError("canonical object is not valid UTF-8 JSON") from exc
    if not isinstance(payload,dict) or not isinstance(payload.get("pushes"),list):
        raise DailyArchiveError("canonical object requires pushes list")
    identities=[]
    for row in payload["pushes"]:
        if not isinstance(row,dict):
            raise DailyArchiveError("invalid push row")
        aid=str(row.get("aid") or "").strip("#")
        if aid not in expected_aids:
            raise DailyArchiveError("object contains AID outside verified expected set")
        if row.get("coverage_day")!=day:
            raise DailyArchiveError("object contains row outside target Taipei day")
        identity=row.get("source_record_key")
        if not isinstance(identity,str) or not identity:
            raise DailyArchiveError("source_record_key required")
        identities.append(identity)
    return len(payload["pushes"]),identities


def compute_source_snapshot_hash(
    *,
    finalization_receipt: dict[str,Any],
    source_revision: str,
    source_objects: list[tuple[str,bytes]],
) -> str:
    """Hash the exact sanitized source snapshot bound to one finalization receipt."""
    receipt=validate_finalization_receipt(finalization_receipt)
    if not isinstance(source_revision,str) or not source_revision:
        raise DailyArchiveError("source_revision required")
    if not isinstance(source_objects,list) or not source_objects:
        raise DailyArchiveError("at least one source object required")
    expected_aids={aid.strip("#") for aid in receipt["expected_set"]["expected_aids"]}
    rows=[]
    seen_keys=set()
    identities=[]
    for logical_key,raw in source_objects:
        logical_key=_safe_relative_key(logical_key)
        if logical_key in seen_keys:
            raise DailyArchiveError("duplicate logical object key")
        seen_keys.add(logical_key)
        if not isinstance(raw,(bytes,bytearray)):
            raise DailyArchiveError("canonical object bytes required")
        body=bytes(raw)
        pushes,row_ids=_validate_payload(
            raw=body,day=receipt["day"],expected_aids=expected_aids)
        identities.extend(row_ids)
        rows.append({
            "logical_key":logical_key,
            "sha256":_digest_bytes(body),
            "bytes":len(body),
            "pushes":pushes,
        })
    if len(identities)!=len(set(identities)):
        raise DailyArchiveError("duplicate source_record_key across daily objects")
    material={
        "taipei_day":receipt["day"],
        "source_revision":source_revision,
        "finalization_evidence_digest":receipt["evidence_digest"],
        "objects":rows,
    }
    return _digest_bytes(_canonical_bytes(material))


def build_daily_static_package(
    *,
    finalization_receipt: dict[str,Any],
    source_revision: str,
    source_hash: str,
    source_objects: list[tuple[str,bytes]],
    out_dir: Path,
) -> dict[str,Any]:
    """Stage one immutable daily package without touching unrelated days.

    source_objects are (logical_relative_key, canonical_json_bytes).  The
    resulting object URLs are content-bound by source_hash and the manifest is
    content-addressed by its exact canonical bytes.
    """
    receipt=validate_finalization_receipt(finalization_receipt)
    if not isinstance(source_revision,str) or not source_revision:
        raise DailyArchiveError("source_revision required")
    source_hash=_require_sha(source_hash,"source_hash")
    if not isinstance(source_objects,list) or not source_objects:
        raise DailyArchiveError("at least one source object required")
    calculated_source_hash=compute_source_snapshot_hash(
        finalization_receipt=receipt,
        source_revision=source_revision,
        source_objects=source_objects,
    )
    if source_hash!=calculated_source_hash:
        raise DailyArchiveError("source_hash does not bind exact source snapshot")

    day=receipt["day"]
    expected_aids={aid.strip("#") for aid in receipt["expected_set"]["expected_aids"]}
    seen_keys=set()
    identities=[]
    staged=[]
    base=f"ptt/v1/history/{day}/{source_hash[:20]}"
    for logical_key,raw in source_objects:
        logical_key=_safe_relative_key(logical_key)
        if logical_key in seen_keys:
            raise DailyArchiveError("duplicate logical object key")
        seen_keys.add(logical_key)
        if not isinstance(raw,(bytes,bytearray)):
            raise DailyArchiveError("canonical object bytes required")
        body=bytes(raw)
        pushes,row_ids=_validate_payload(
            raw=body,day=day,expected_aids=expected_aids)
        identities.extend(row_ids)
        object_key=f"{base}/{logical_key}"
        staged.append({
            "key":object_key,
            "logical_key":logical_key,
            "sha256":_digest_bytes(body),
            "bytes":len(body),
            "pushes":pushes,
            "_body":body,
        })
    if len(identities)!=len(set(identities)):
        raise DailyArchiveError("duplicate source_record_key across daily objects")

    object_rows=[
        {key:value for key,value in item.items() if key!="_body"}
        for item in staged
    ]
    manifest_body={
        "schema_version":PACKAGE_SCHEMA,
        "taipei_day":day,
        "source_revision":source_revision,
        "source_hash":source_hash,
        "finalization_evidence_digest":receipt["evidence_digest"],
        "expected_aids":sorted(expected_aids),
        "expected_aid_authority":receipt["expected_set"]["authority"],
        "total_objects":len(object_rows),
        "total_pushes":sum(item["pushes"] for item in object_rows),
        "objects":object_rows,
    }
    manifest_bytes=_canonical_bytes(manifest_body)
    manifest_digest=_digest_bytes(manifest_bytes)
    if manifest_digest==source_hash:
        raise DailyArchiveError("source_hash and manifest_digest must stay distinct")
    manifest_key=f"ptt/v1/manifests/daily/{day}/{manifest_digest}.json"

    writes=[(item["key"],item["_body"]) for item in staged]
    writes.append((manifest_key,manifest_bytes))
    for key,body in writes:
        target=out_dir/key
        if target.exists():
            if target.read_bytes()!=body:
                raise DailyArchiveError(f"immutable object collision: {key}")
            continue
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(body)

    return {
        "schema_version":PACKAGE_SCHEMA,
        "taipei_day":day,
        "source_revision":source_revision,
        "source_hash":source_hash,
        "finalization_evidence_digest":receipt["evidence_digest"],
        "expected_aids":sorted(expected_aids),
        "manifest":{
            "key":manifest_key,
            "digest":manifest_digest,
            "schema_version":PACKAGE_SCHEMA,
        },
        "objects":object_rows,
        "object_count":len(object_rows),
        "push_count":manifest_body["total_pushes"],
        "package_status":"COMPLETE",
        "immutable":True,
    }


def prepare_static_assets_delivery(
    *,package: dict[str,Any],job_id: str,target_identity: str | None=None
) -> dict[str,Any]:
    """Return a production-inert delivery plan; no deploy command is executed."""
    if not isinstance(job_id,str) or not SAFE_JOB_ID.fullmatch(job_id):
        raise DailyArchiveError("sanitized job_id required")
    manifest=package.get("manifest") if isinstance(package,dict) else None
    if not isinstance(manifest,dict):
        raise DailyArchiveError("built package required")
    _require_sha(manifest.get("digest"),"manifest digest")
    if job_id==manifest["digest"]:
        raise DailyArchiveError("job_id and manifest_digest must stay distinct")
    return {
        "schema_version":DELIVERY_PLAN_SCHEMA,
        "production_execution":False,
        "target":{"kind":"workers-static-assets","identity":target_identity},
        "job_id":job_id,
        "taipei_day":package["taipei_day"],
        "source_revision":package["source_revision"],
        "source_hash":package["source_hash"],
        "manifest":dict(manifest),
        "object_keys":[item["key"] for item in package["objects"]],
        "object_count":package["object_count"],
        "deploy_authorized":False,
    }


def verify_http_readback(
    *,
    package: dict[str,Any],
    job_id: str,
    fetch_bytes: Callable[[str],bytes],
    observed_at: str,
    target_identity: str | None=None,
) -> dict[str,Any]:
    """Independently fetch manifest/objects and produce reviewed readback receipt.

    fetch_bytes is the HTTP transport seam.  Production wiring may inject an
    actual HTTP client only after /45 approval; tests inject a deterministic
    fake remote.
    """
    manifest=package["manifest"]
    expected_objects=package["objects"]
    try:
        manifest_raw=fetch_bytes(manifest["key"])
    except Exception:
        manifest_raw=None
    manifest_digest_match=(
        isinstance(manifest_raw,(bytes,bytearray))
        and _digest_bytes(bytes(manifest_raw))==manifest["digest"]
    )
    manifest_verified=False
    remote_manifest=None
    if manifest_digest_match:
        try:
            remote_manifest=json.loads(bytes(manifest_raw))
            manifest_verified=(
                isinstance(remote_manifest,dict)
                and remote_manifest.get("schema_version")==PACKAGE_SCHEMA
                and remote_manifest.get("taipei_day")==package["taipei_day"]
                and remote_manifest.get("source_revision")==package["source_revision"]
                and remote_manifest.get("source_hash")==package["source_hash"]
            )
        except (UnicodeDecodeError,json.JSONDecodeError):
            manifest_verified=False

    checked=0
    verified=0
    content_hash_match=True
    unresolved=0
    if manifest_verified:
        remote_objects=remote_manifest.get("objects")
        object_count_match=(
            isinstance(remote_objects,list)
            and len(remote_objects)==len(expected_objects)
            and [item.get("key") for item in remote_objects]
                ==[item["key"] for item in expected_objects]
        )
        if object_count_match:
            for expected in expected_objects:
                checked+=1
                try:
                    raw=fetch_bytes(expected["key"])
                except Exception:
                    unresolved+=1
                    content_hash_match=False
                    continue
                if not isinstance(raw,(bytes,bytearray)):
                    unresolved+=1
                    content_hash_match=False
                    continue
                digest=_digest_bytes(bytes(raw))
                if digest==expected["sha256"] and len(raw)==expected["bytes"]:
                    verified+=1
                else:
                    content_hash_match=False
        else:
            content_hash_match=False
            unresolved=len(expected_objects)
    else:
        object_count_match=False
        content_hash_match=False
        unresolved=len(expected_objects)

    target={"kind":"workers-static-assets","identity":target_identity}
    scope={
        "from_day":package["taipei_day"],
        "through_day":package["taipei_day"],
        "object_count":package["object_count"],
        "thread_scope":package["expected_aids"],
        "thread_scope_authoritative":True,
    }
    return build_readback_receipt(
        target=target,
        job_id=job_id,
        manifest_digest=manifest["digest"],
        source_revision=package["source_revision"],
        scope=scope,
        objects_expected=package["object_count"],
        objects_checked=checked,
        objects_verified=verified,
        manifest_verified=manifest_verified,
        content_hash_match=content_hash_match,
        coverage_scope_match=manifest_verified,
        verification_mode="full_partition",
        observed_at=observed_at,
        manifest_digest_match=manifest_digest_match,
        object_count_match=object_count_match,
        unresolved_objects=unresolved,
        pagination_complete=True,
    )


def build_archive_delivery_evidence(
    *,
    package: dict[str,Any],
    finalization_receipt: dict[str,Any],
    job_id: str,
    job_status: str,
    attempted_at: str | None,
    succeeded_at: str | None,
    attempt_count: int,
    uploaded_count: int | None,
    readback_receipt: dict[str,Any] | None,
    error_code: str | None=None,
    target_identity: str | None=None,
) -> dict[str,Any]:
    """Map one /55 receipt + /160 package/job into the existing v1 evidence."""
    receipt=validate_finalization_receipt(finalization_receipt)
    if receipt["day"]!=package.get("taipei_day"):
        raise DailyArchiveError("finalization/package day mismatch")
    expected={
        "status":"COMPLETE",
        "authority":receipt["expected_set"]["authority"],
        "expected_aids":list(package["expected_aids"]),
        "evidence_digest":receipt["expected_set"].get("evidence_digest"),
        "contract_gaps":[],
    }
    scope={
        "from_day":package["taipei_day"],
        "through_day":package["taipei_day"],
        "object_count":package["object_count"],
        "thread_scope":package["expected_aids"],
        "thread_scope_authoritative":True,
    }
    verified_count=(
        readback_receipt.get("objects_verified")
        if isinstance(readback_receipt,dict) else None
    )
    return build_archive_job_evidence(
        job_id=job_id,
        target={"kind":"workers-static-assets","identity":target_identity},
        source_revision=package["source_revision"],
        source_hash=package["source_hash"],
        manifest=package["manifest"],
        scope=scope,
        attempted_at=attempted_at,
        succeeded_at=succeeded_at,
        attempt_count=attempt_count,
        retry_after=None,
        backoff_seconds=None,
        error_code=error_code,
        uploaded_count=uploaded_count,
        independently_verified_count=verified_count,
        readback_receipt=readback_receipt,
        coverage_days=[{
            "day":package["taipei_day"],
            "coverage_status":"COMPLETE",
        }],
        job_status=job_status,
        expected_aid_completeness=expected,
    )


def http_asset_url(base_url: str,object_key: str) -> str:
    """Small deterministic URL seam for an approved future HTTP transport."""
    if not isinstance(base_url,str) or not base_url.startswith(("https://","http://")):
        raise DailyArchiveError("HTTP base URL required")
    key=_safe_relative_key(object_key)
    return base_url.rstrip("/")+"/"+"/".join(quote(part,safe="") for part in key.split("/"))
