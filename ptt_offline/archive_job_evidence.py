"""Pure sanitized Archive Delivery job/readback evidence contracts.

Target-agnostic between Workers Static Assets and R2. This module performs no
network, subprocess, filesystem, Cloudflare, D1, R2, Static Assets deploy, or
production writer action.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any

JOB_SCHEMA="holoviewer-archive-job-evidence-v1"
READBACK_SCHEMA="holoviewer-archive-readback-receipt-v1"
JOB_KIND="archive-delivery"
TARGET_KINDS={"workers-static-assets","r2"}
JOB_STATUSES={"pending","attempted","succeeded","failed","unknown"}
VERIFICATION_MODES={"bounded_sample","full_partition"}
COVERAGE_STATUSES={"COMPLETE","PARTIAL","UNKNOWN"}
HEX64=re.compile(r"^[0-9a-f]{64}$")
DAY_RE=re.compile(r"^\d{4}-\d{2}-\d{2}$")
SAFE_TARGET_ID=re.compile(r"^[A-Za-z0-9._:-]{1,120}$")

_FORBIDDEN_KEY_FRAGMENTS=(
    "authorization","api_token","apitoken","account_id","accountid",
    "hmac_secret","hmacsecret","secret","cookie","wrangler_credential",
    "credential","signed_url","signedurl","private_key","access_key",
)
_SIGNED_URL_MARKERS=(
    "x-amz-signature=","x-goog-signature=","signature=","sig=",
    "token=","x-amz-credential=","x-goog-credential=",
)
_ABS_PATH_PATTERNS=(
    re.compile(r"^/(?:Users|home|private|var|tmp|opt|etc|srv|mnt)/"),
    re.compile(r"^[A-Za-z]:\\"),
)


class ArchiveEvidenceError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,ensure_ascii=False,sort_keys=True,separators=(",",":")
    ).encode("utf-8")


def digest_canonical(value: Any) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def manifest_digest_from_bytes(raw: bytes) -> str:
    if not isinstance(raw,(bytes,bytearray)):
        raise TypeError("manifest bytes required")
    return sha256(bytes(raw)).hexdigest()


def archive_object_identity(*, manifest_digest: str, object_key: str,
                            canonical_sha256: str) -> str:
    _require_digest(manifest_digest,"manifest_digest")
    _require_digest(canonical_sha256,"canonical object SHA-256")
    if not isinstance(object_key,str) or not object_key or object_key.startswith("/"):
        raise ArchiveEvidenceError("sanitized relative object key required")
    if ".." in object_key.split("/"):
        raise ArchiveEvidenceError("object key traversal rejected")
    return f"{manifest_digest}:{object_key}:{canonical_sha256}"


def _require_digest(value: object, name: str) -> str:
    if not isinstance(value,str) or not HEX64.fullmatch(value):
        raise ArchiveEvidenceError(f"{name} must be lowercase SHA-256")
    return value


def _require_day(value: object, name: str) -> str:
    if not isinstance(value,str) or not DAY_RE.fullmatch(value):
        raise ArchiveEvidenceError(f"{name} must be canonical Taipei day")
    return value


def _walk_sensitive(value: Any, path: tuple[str,...]=()) -> list[str]:
    findings=[]
    if isinstance(value,dict):
        for key,item in value.items():
            key_s=str(key)
            norm=re.sub(r"[^a-z0-9]","",key_s.lower())
            if any(fragment.replace("_","") in norm for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                findings.append(".".join(path+(key_s,)))
            findings.extend(_walk_sensitive(item,path+(key_s,)))
    elif isinstance(value,list):
        for index,item in enumerate(value):
            findings.extend(_walk_sensitive(item,path+(str(index),)))
    elif isinstance(value,str):
        low=value.lower()
        if any(marker in low for marker in _SIGNED_URL_MARKERS):
            findings.append(".".join(path) or "<root>")
        if any(pattern.search(value) for pattern in _ABS_PATH_PATTERNS):
            findings.append(".".join(path) or "<root>")
        if low.startswith("authorization:") or low.startswith("bearer "):
            findings.append(".".join(path) or "<root>")
    return sorted(set(findings))


def reject_sensitive(value: Any) -> None:
    findings=_walk_sensitive(value)
    if findings:
        raise ArchiveEvidenceError(
            "sensitive field/value rejected: "+", ".join(findings[:8])
        )


def _target(value: object) -> dict[str,Any]:
    if not isinstance(value,dict):
        raise ArchiveEvidenceError("target mapping required")
    allowed={"kind","identity"}
    unknown=set(value)-allowed
    if unknown:
        raise ArchiveEvidenceError("unsupported target field: "+",".join(sorted(unknown)))
    kind=value.get("kind")
    if kind not in TARGET_KINDS:
        raise ArchiveEvidenceError("unsupported archive target kind")
    identity=value.get("identity")
    if identity is not None and (
        not isinstance(identity,str) or not SAFE_TARGET_ID.fullmatch(identity)
    ):
        raise ArchiveEvidenceError("sanitized target identity required")
    result={"kind":kind,"identity":identity}
    reject_sensitive(result)
    return result


def _coverage_summary(days: object) -> dict[str,Any]:
    if not isinstance(days,list):
        return {
            "status":"UNKNOWN","days_total":None,"days_complete":None,
            "days_partial":None,"days_unknown":None,"days":None,
            "contract_gaps":["archive-day-coverage-unavailable"],
        }
    normalized=[]
    gaps=[]
    for item in days:
        if not isinstance(item,dict):
            raise ArchiveEvidenceError("invalid archive day coverage")
        day=_require_day(item.get("day"),"coverage day")
        status=item.get("coverage_status")
        if status not in COVERAGE_STATUSES:
            raise ArchiveEvidenceError("invalid archive coverage status")
        normalized.append({"day":day,"coverage_status":status})
    counts={name:sum(1 for row in normalized if row["coverage_status"]==name)
            for name in COVERAGE_STATUSES}
    if counts["PARTIAL"]:
        overall="PARTIAL"
    elif counts["UNKNOWN"]:
        overall="UNKNOWN"
    elif normalized:
        overall="COMPLETE"
    else:
        overall="UNKNOWN"
        gaps.append("archive-day-coverage-empty")
    return {
        "status":overall,
        "days_total":len(normalized),
        "days_complete":counts["COMPLETE"],
        "days_partial":counts["PARTIAL"],
        "days_unknown":counts["UNKNOWN"],
        "days":normalized,
        "contract_gaps":gaps,
    }


def build_readback_receipt(*, target: dict[str,Any], job_id: str | None,
                           manifest_digest: str | None,
                           source_revision: str | None,
                           scope: dict[str,Any] | None,
                           objects_expected: int | None,
                           objects_checked: int | None,
                           objects_verified: int | None,
                           manifest_verified: bool | None,
                           content_hash_match: bool | None,
                           coverage_scope_match: bool | None,
                           verification_mode: str | None,
                           observed_at: str | None,
                           manifest_digest_match: bool | None=None,
                           object_count_match: bool | None=None,
                           unresolved_objects: int | None=None,
                           pagination_complete: bool | None=None,
                           snapshot_id: str | None=None) -> dict[str,Any]:
    target_s=_target(target)
    gaps=[]
    if job_id is None:gaps.append("archive-readback-job-id-unavailable")
    if manifest_digest is None:gaps.append("archive-readback-manifest-digest-unavailable")
    elif not HEX64.fullmatch(manifest_digest):
        raise ArchiveEvidenceError("readback manifest_digest must be lowercase SHA-256")
    if source_revision is None:gaps.append("archive-readback-source-revision-unavailable")
    if scope is None:gaps.append("archive-readback-scope-unavailable")
    if objects_expected is None:gaps.append("archive-readback-objects-expected-unavailable")
    if objects_checked is None:gaps.append("archive-readback-objects-checked-unavailable")
    if objects_verified is None:gaps.append("archive-readback-objects-verified-unavailable")
    if observed_at is None:gaps.append("archive-readback-observed-at-unavailable")
    if verification_mode not in VERIFICATION_MODES:
        if verification_mode is not None:
            raise ArchiveEvidenceError("unsupported archive verification mode")
        gaps.append("archive-readback-verification-mode-unavailable")
    for name,value in (
        ("manifest_verified",manifest_verified),
        ("content_hash_match",content_hash_match),
        ("coverage_scope_match",coverage_scope_match),
    ):
        if value is None:gaps.append(f"archive-readback-{name.replace('_','-')}-unavailable")

    if verification_mode=="full_partition":
        for name,value in (
            ("manifest_digest_match",manifest_digest_match),
            ("object_count_match",object_count_match),
            ("pagination_complete",pagination_complete),
        ):
            if value is None:gaps.append(f"archive-readback-{name.replace('_','-')}-unavailable")
        if unresolved_objects is None:
            gaps.append("archive-readback-unresolved-object-count-unavailable")

    full_checks=(
        verification_mode=="full_partition"
        and manifest_verified is True
        and manifest_digest_match is True
        and content_hash_match is True
        and coverage_scope_match is True
        and object_count_match is True
        and pagination_complete is True
        and isinstance(objects_expected,int) and objects_expected>=0
        and objects_checked==objects_expected
        and objects_verified==objects_expected
        and unresolved_objects==0
        and not gaps
    )
    job_verified=bool(full_checks)

    fail_codes=[]
    if manifest_digest_match is False or manifest_verified is False:
        fail_codes.append("manifest_digest_mismatch")
    if content_hash_match is False:
        fail_codes.append("object_hash_mismatch")
    if coverage_scope_match is False:
        fail_codes.append("coverage_scope_mismatch")
    if object_count_match is False:
        fail_codes.append("object_count_mismatch")
    if unresolved_objects not in (None,0):
        fail_codes.append("partial_verification")
    if pagination_complete is False:
        fail_codes.append("partial_verification")
    if verification_mode=="bounded_sample":
        gaps.append("bounded-sample-cannot-verify-whole-job")

    base={
        "schema_version":READBACK_SCHEMA,
        "sanitized":True,
        "snapshot_id":snapshot_id,
        "observed_at":observed_at,
        "target":target_s,
        "job_id":job_id,
        "manifest_digest":manifest_digest,
        "source_revision":source_revision,
        "scope":deepcopy(scope) if isinstance(scope,dict) else None,
        "objects_expected":objects_expected,
        "objects_checked":objects_checked,
        "objects_verified":objects_verified,
        "manifest_verified":manifest_verified,
        "manifest_digest_match":manifest_digest_match,
        "content_hash_match":content_hash_match,
        "coverage_scope_match":coverage_scope_match,
        "object_count_match":object_count_match,
        "unresolved_objects":unresolved_objects,
        "pagination_complete":pagination_complete,
        "verification_mode":verification_mode,
        "job_verified":job_verified,
        "error_code":fail_codes[0] if fail_codes else None,
        "contract_gaps":sorted(set(gaps)),
    }
    reject_sensitive(base)
    if snapshot_id is None:
        snapshot_material={k:v for k,v in base.items() if k!="snapshot_id"}
        base["snapshot_id"]=digest_canonical(snapshot_material)
    else:
        _require_digest(snapshot_id,"snapshot_id")
    if job_id is not None and (
        job_id==base["snapshot_id"] or job_id==manifest_digest
    ):
        raise ArchiveEvidenceError("job_id, manifest_digest and snapshot_id must be distinct")
    if manifest_digest is not None and manifest_digest==base["snapshot_id"]:
        raise ArchiveEvidenceError("job_id, manifest_digest and snapshot_id must be distinct")
    return base


def build_archive_job_evidence(*, job_id: str | None, target: dict[str,Any],
                               source_revision: str | None,
                               source_hash: str | None,
                               manifest: dict[str,Any] | None,
                               scope: dict[str,Any] | None,
                               attempted_at: str | None,
                               succeeded_at: str | None,
                               attempt_count: int | None,
                               retry_after: str | None,
                               backoff_seconds: int | None,
                               error_code: str | None,
                               uploaded_count: int | None,
                               independently_verified_count: int | None,
                               readback_receipt: dict[str,Any] | None,
                               coverage_days: list[dict[str,Any]] | None,
                               job_status: str | None,
                               expected_aid_completeness: dict[str,Any] | None=None
                               ) -> dict[str,Any]:
    target_s=_target(target)
    gaps=[]
    if job_id is None:gaps.append("archive-job-id-unavailable")
    if source_revision is None:gaps.append("archive-source-revision-unavailable")
    if source_hash is None:gaps.append("archive-source-hash-unavailable")
    elif not HEX64.fullmatch(source_hash):
        raise ArchiveEvidenceError("source_hash must be lowercase SHA-256")

    manifest_s=None
    manifest_digest=None
    if isinstance(manifest,dict):
        allowed={"key","digest","schema_version"}
        if set(manifest)-allowed:
            raise ArchiveEvidenceError("unsupported manifest identity field")
        manifest_digest=manifest.get("digest")
        if manifest_digest is not None:
            _require_digest(manifest_digest,"manifest.digest")
        manifest_s={
            "key":manifest.get("key"),
            "digest":manifest_digest,
            "schema_version":manifest.get("schema_version"),
        }
        if manifest_s["key"] is None:gaps.append("archive-manifest-key-unavailable")
        if manifest_s["digest"] is None:gaps.append("archive-manifest-digest-unavailable")
        if manifest_s["schema_version"] is None:gaps.append("archive-manifest-schema-unavailable")
    else:
        gaps.extend([
            "archive-manifest-key-unavailable",
            "archive-manifest-digest-unavailable",
            "archive-manifest-schema-unavailable",
        ])

    scope_s=None
    if isinstance(scope,dict):
        allowed={"from_day","through_day","object_count","thread_scope","thread_scope_authoritative"}
        if set(scope)-allowed:
            raise ArchiveEvidenceError("unsupported archive scope field")
        from_day=scope.get("from_day")
        through_day=scope.get("through_day")
        if from_day is not None:_require_day(from_day,"scope from_day")
        else:gaps.append("archive-scope-from-day-unavailable")
        if through_day is not None:_require_day(through_day,"scope through_day")
        else:gaps.append("archive-scope-through-day-unavailable")
        object_count=scope.get("object_count")
        if object_count is None:gaps.append("archive-scope-object-count-unavailable")
        thread_authority=scope.get("thread_scope_authoritative") is True
        thread_scope=deepcopy(scope.get("thread_scope")) if thread_authority else None
        if not thread_authority:
            gaps.append("archive-thread-scope-authority-unavailable")
        scope_s={
            "from_day":from_day,
            "through_day":through_day,
            "object_count":object_count,
            "thread_scope":thread_scope,
            "thread_scope_authoritative":thread_authority,
        }
    else:
        gaps.extend([
            "archive-scope-unavailable",
            "archive-thread-scope-authority-unavailable",
        ])

    for name,value in (
        ("attempted-at",attempted_at),
        ("attempt-count",attempt_count),
        ("retry-after",retry_after),
        ("backoff-seconds",backoff_seconds),
        ("uploaded-count",uploaded_count),
        ("independently-verified-count",independently_verified_count),
    ):
        if value is None:gaps.append(f"archive-{name}-unavailable")
    if job_status is None:
        status="unknown"
        gaps.append("archive-job-status-unavailable")
    elif job_status not in JOB_STATUSES:
        raise ArchiveEvidenceError("unsupported archive job status")
    else:
        status=job_status
    if status=="succeeded" and succeeded_at is None:
        gaps.append("archive-succeeded-at-unavailable")
    if status!="succeeded" and succeeded_at is not None:
        raise ArchiveEvidenceError("succeeded_at contradicts archive job status")

    readback=None
    if isinstance(readback_receipt,dict):
        if readback_receipt.get("schema_version")!=READBACK_SCHEMA:
            raise ArchiveEvidenceError("unsupported archive readback schema")
        readback=deepcopy(readback_receipt)
        if job_id is not None and readback.get("job_id")!=job_id:
            raise ArchiveEvidenceError("readback job_id mismatch")
        if manifest_digest is not None and readback.get("manifest_digest")!=manifest_digest:
            raise ArchiveEvidenceError("readback manifest digest mismatch")
        if source_revision is not None and readback.get("source_revision")!=source_revision:
            raise ArchiveEvidenceError("readback source revision mismatch")
        if readback.get("target")!=target_s:
            raise ArchiveEvidenceError("readback target mismatch")
    else:
        gaps.append("archive-readback-receipt-unavailable")

    coverage=_coverage_summary(coverage_days)
    gaps.extend(coverage.get("contract_gaps",[]))

    if expected_aid_completeness is None:
        expected_aid={
            "status":"UNKNOWN",
            "authority":None,
            "contract_gaps":["expected-aid-authority-unavailable"],
        }
    else:
        expected_aid=deepcopy(expected_aid_completeness)

    result={
        "schema_version":JOB_SCHEMA,
        "sanitized":True,
        "job_id":job_id,
        "job_kind":JOB_KIND,
        "target":target_s,
        "source_revision":source_revision,
        "source_hash":source_hash,
        "manifest":manifest_s,
        "scope":scope_s,
        "attempted_at":attempted_at,
        "succeeded_at":succeeded_at,
        "attempt_count":attempt_count,
        "retry_after":retry_after,
        "backoff_seconds":backoff_seconds,
        "error_code":error_code,
        "uploaded_count":uploaded_count,
        "independently_verified_count":independently_verified_count,
        "readback_receipt":readback,
        "readback_observed_at":readback.get("observed_at") if readback else None,
        "snapshot_id":readback.get("snapshot_id") if readback else None,
        "verification_mode":readback.get("verification_mode") if readback else None,
        "job_verified":readback.get("job_verified") if readback else False,
        "coverage_summary":coverage,
        "job_status":status,
        "expected_aid_completeness":expected_aid,
        "contract_gaps":sorted(set(gaps)),
    }
    reject_sensitive(result)
    if job_id is not None and manifest_digest is not None and job_id==manifest_digest:
        raise ArchiveEvidenceError("job_id and manifest_digest must be distinct")
    if result["snapshot_id"] is not None and (
        result["snapshot_id"]==job_id or result["snapshot_id"]==manifest_digest
    ):
        raise ArchiveEvidenceError("job_id, manifest_digest and snapshot_id must be distinct")
    return result


def validate_archive_job_evidence(value: dict[str,Any]) -> dict[str,Any]:
    if not isinstance(value,dict):
        raise ArchiveEvidenceError("archive evidence mapping required")
    reject_sensitive(value)
    if value.get("schema_version")!=JOB_SCHEMA or value.get("sanitized") is not True:
        raise ArchiveEvidenceError("unsupported/unsanitized archive job evidence")
    if value.get("job_kind")!=JOB_KIND:
        raise ArchiveEvidenceError("invalid archive job kind")
    _target(value.get("target"))
    manifest=value.get("manifest")
    if isinstance(manifest,dict) and manifest.get("digest") is not None:
        _require_digest(manifest["digest"],"manifest.digest")
    source_hash=value.get("source_hash")
    if source_hash is not None:_require_digest(source_hash,"source_hash")
    snapshot=value.get("snapshot_id")
    if snapshot is not None:_require_digest(snapshot,"snapshot_id")
    job=value.get("job_id")
    digest=manifest.get("digest") if isinstance(manifest,dict) else None
    ids=[x for x in (job,digest,snapshot) if x is not None]
    if len(ids)!=len(set(ids)):
        raise ArchiveEvidenceError("job_id, manifest_digest and snapshot_id must be distinct")
    return deepcopy(value)
