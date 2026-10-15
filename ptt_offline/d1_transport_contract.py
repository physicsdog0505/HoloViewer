"""No-live-write D1 transport preparation for #48.

The executor is injected by tests/integration. This module does not know a
Worker URL, binding, token, secret or account. It performs exactly one request
attempt and validates a bounded ACK receipt against the resumable batch digest.
"""
from __future__ import annotations

from .public_today_contract import ContractError

MAX_HTTP_REQUESTS = 1
MAX_D1_QUERIES = 150
MAX_LOGICAL_ROWS = 25
# First-window upper bound: 1 thread + 5 push upserts + 5 evidence upserts
# + 1 optional provider-state update = 12 mutations; allow 20 actual D1
# Rows Written under the frozen #48 canary cap. Treat as distinct accounting.
MAX_ROWS_WRITTEN = 80


def execute_once(*, batch: dict, executor, max_rows=5, max_queries=30, max_written=20) -> dict:
    if (type(max_rows) is not int or not 1<=max_rows<=MAX_LOGICAL_ROWS or
        type(max_queries) is not int or not 1<=max_queries<=MAX_D1_QUERIES or
        type(max_written) is not int or not 1<=max_written<=MAX_ROWS_WRITTEN):
        raise ContractError('invalid operator-approved transport caps')
    if not callable(executor):
        raise ContractError("explicit transport executor required")
    rows=batch.get("rows")
    if not isinstance(rows,list) or len(rows) > max_rows:
        raise ContractError("transport row cap exceeded")
    if batch.get("request_cap") != 1 or batch.get("retry_cap") != 0:
        raise ContractError("unsafe transport budget")
    # Exactly one injected call. No catch/retry loop by design.
    response=executor(batch)
    if not isinstance(response,dict):
        raise ContractError("invalid transport ACK")
    if response.get("batch_id") != batch.get("batch_id"):
        raise ContractError("transport ACK batch mismatch")
    if response.get("digest") != batch.get("digest"):
        raise ContractError("transport ACK digest mismatch")
    if response.get("status") != "ACK":
        raise ContractError("transport did not ACK")
    queries=response.get("d1_query_count")
    written=response.get("d1_rows_written")
    logical=response.get("logical_rows_acked")
    requests=response.get("http_requests")
    if (type(requests) is not int or requests < 0 or requests > MAX_HTTP_REQUESTS or
        type(queries) is not int or queries < 0 or queries > max_queries or
        type(written) is not int or written < 0 or written > max_written):
        raise ContractError("transport accounting cap exceeded")
    if type(logical) is not int or logical != len(rows):
        raise ContractError("partial logical push ACK")
    return {
        "status":"ACK",
        "batch_id":batch["batch_id"],
        "digest":batch["digest"],
        "rows_acked":logical,
        "logical_rows_acked":logical,
        "http_requests":requests,
        "d1_query_count":queries,
        "d1_rows_written":written,
    }
