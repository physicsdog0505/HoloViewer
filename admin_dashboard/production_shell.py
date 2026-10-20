"""Host-owned Production read-only integration shell.

Phase 1 has no Production implementation. All Production gates default disabled.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from time import monotonic

from .admission import AdmissionRequest
from .capabilities import (
    ArchiveReadScope, D1ReadScope, NoProductionCredentials, ProductionReaderConfig,
)


_ERROR_CODES = {
    "source_disabled", "credential_missing", "admission_denied", "budget_exceeded",
    "reader_timeout", "source_unavailable", "schema_mismatch", "sanitization_failed",
    "readback_incomplete", "admission_state_error", "coalesced_inflight",
}


class ProductionReadOnlyShell:
    """Applies source gates, admission, one bounded attempt and sanitized audit."""

    def __init__(self, reader, admission, *, config: ProductionReaderConfig | None = None,
                 credentials=None, principal: str | None = None):
        self._reader = reader
        self._admission = admission
        self._config = config or ProductionReaderConfig()
        self._credentials = credentials or NoProductionCredentials()
        self._principal = principal

    def _gate(self, source: str):
        return getattr(self._config, source)

    def _read(self, source: str, operation: str, scope: dict, mode: str, fn):
        try:
            gate = self._gate(source)
        except Exception:
            return self._unavailable(source, "source_disabled")
        if not gate.enabled:
            return self._unavailable(source, "source_disabled")
        if gate.credential_required:
            try:
                credential_available = self._credentials.available(source) is True
            except Exception:
                credential_available = False
            if not credential_available:
                return self._unavailable(source, "credential_missing")

        key_data = {"source": source, "scope": scope, "mode": mode, "operation": operation}
        coalesce_key = "sha256:" + hashlib.sha256(
            json.dumps(key_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        request = AdmissionRequest(
            source=source, scope=scope, verification_mode=mode,
            request_class=operation, cost_class="bounded_read", coalesce_key=coalesce_key,
        )
        try:
            receipt = self._admission.admit(request)
        except Exception:
            return self._unavailable(source, "admission_state_error")
        if not receipt.admitted:
            code = receipt.reason if receipt.reason in _ERROR_CODES else "admission_denied"
            self._safe_audit(source, operation, receipt.scope_hash, False, False,
                             "short", "denied", code)
            return self._unavailable(source, code, admission=asdict(receipt))

        started = monotonic()
        value = None
        error_code = None
        result_class = "error"
        try:
            # Exactly one attempt. Retry/scheduler behavior is intentionally absent.
            value = fn()
            result_class = "ok" if value is not None else "unavailable"
            if value is None:
                error_code = "source_unavailable"
        except Exception:
            error_code = "source_unavailable"
            result_class = "error"

        duration = monotonic() - started
        bucket = "short" if duration < 1 else "medium" if duration < 5 else "long"
        audit_ok = self._safe_audit(
            source, operation, receipt.scope_hash, True, receipt.cache_hit,
            bucket, result_class, error_code)
        self._admission.release(request.coalesce_key)
        if not audit_ok:
            return self._unavailable(source, "source_unavailable", admission=asdict(receipt))
        return {
            "available": value is not None and error_code is None,
            "value": value if error_code is None else None,
            "error_code": error_code,
            "admission": asdict(receipt),
        }

    def _safe_audit(self, source, operation, scope_hash, admitted, cache_hit,
                    duration_bucket, result_class, error_code):
        try:
            self._admission.audit(
                principal=self._principal, source=source, operation_class=operation,
                scope_hash=scope_hash, admitted=admitted, cache_hit=cache_hit,
                duration_bucket=duration_bucket, result_class=result_class,
                error_code=error_code,
            )
            return True
        except Exception:
            # Audit is sanitized local operational state. Never leak its exception.
            return False

    @staticmethod
    def _unavailable(source, error_code, *, admission=None):
        return {
            "available": False, "value": None, "source": source,
            "error_code": error_code, "admission": admission,
        }

    def read_d1(self, scope: D1ReadScope):
        return self._read("d1", "d1_snapshot", asdict(scope), scope.verification_mode,
                          lambda: self._reader.read_d1_snapshot(scope, timeouts=self._config.timeouts))

    def read_archive(self, scope: ArchiveReadScope):
        return self._read("archive", "archive_delivery", asdict(scope), "bounded_sample",
                          lambda: self._reader.read_archive_delivery_evidence(scope, timeouts=self._config.timeouts))

    def read_api_semantic(self):
        return self._read("api_semantic", "api_semantic_health", {}, "bounded_sample",
                          lambda: self._reader.read_api_semantic_health(timeouts=self._config.timeouts))

    def read_publisher(self):
        return self._read("publisher", "publisher_evidence", {}, "bounded_sample",
                          lambda: self._reader.read_publisher_evidence(timeouts=self._config.timeouts))

    def read_collector(self):
        return self._read("collector", "collector_evidence", {}, "bounded_sample",
                          lambda: self._reader.read_collector_evidence(timeouts=self._config.timeouts))


class EvidenceReaderSet:
    """Section readers built from independently isolated source capabilities."""

    def __init__(self, shell: ProductionReadOnlyShell, *, day: str = "2026-10-20",
                 aids: tuple[str, ...] = (), archive_from_day: str | None = None,
                 archive_through_day: str | None = None):
        self._shell = shell
        self._day = day
        self._aids = tuple(aids)
        self._archive_from = archive_from_day or day
        self._archive_through = archive_through_day or day

    def coverage(self):
        d1 = self._shell.read_d1(D1ReadScope(self._day, self._aids))
        # Expected-set/local coverage is a separate producer. Phase 1 never invents it.
        return {
            "schema_version": "holoviewer-admin-production-shell-coverage-v1",
            "days": [{"date": self._day, "status": "UNKNOWN",
                      "contract_gaps": ["production-local-coverage-reader-not-enabled"],
                      "target_evidence": d1["value"] if d1["available"] else None,
                      "source_error_code": d1["error_code"]}],
            "read_only": True,
        }

    def sync_monitor(self):
        d1 = self._shell.read_d1(D1ReadScope(self._day, self._aids))
        archive = self._shell.read_archive(
            ArchiveReadScope(self._archive_from, self._archive_through))
        publisher = self._shell.read_publisher()
        result = {
            "d1_snapshot": d1["value"] if d1["available"] else None,
            "archive_sync_job": archive["value"] if archive["available"] else None,
        }
        if publisher["available"] and isinstance(publisher["value"], dict):
            result.update(publisher["value"])
        result["shell_source_errors"] = {
            "d1": d1["error_code"], "archive": archive["error_code"],
            "publisher": publisher["error_code"],
        }
        return result

    def system_health(self):
        collector = self._shell.read_collector()
        publisher = self._shell.read_publisher()
        archive = self._shell.read_archive(
            ArchiveReadScope(self._archive_from, self._archive_through))
        api = self._shell.read_api_semantic()
        components = {}
        for name, outcome in (
            ("Collector", collector), ("Publisher", publisher),
            ("Archive", archive), ("Production API", api),
        ):
            if outcome["available"] and isinstance(outcome["value"], dict):
                value = outcome["value"]
                if name == "Production API" and isinstance(value.get("components"), dict):
                    components.update(value["components"])
                elif name in value:
                    components[name] = value[name]
                else:
                    components[name] = value
            else:
                components[name] = {
                    "semantic_check": {"status": "unavailable"},
                    "observed_at": None, "evidence_source": "production source disabled",
                    "error": outcome["error_code"],
                }
        return {"components": components}

    def injected(self):
        return {
            "data_coverage": self.coverage,
            "sync_monitor": self.sync_monitor,
            "system_health": self.system_health,
        }


def select_reader_provider(*, mode: str = "fixture", fixture_readers=None,
                           production_readers=None):
    """Explicit provider selection. No environment auto-detection is performed."""
    if mode == "fixture":
        if fixture_readers is None:
            raise RuntimeError("fixture_reader_required")
        return fixture_readers
    if mode == "production":
        if production_readers is None:
            raise RuntimeError("production_reader_unavailable")
        return production_readers
    raise RuntimeError("unsupported_reader_mode")
