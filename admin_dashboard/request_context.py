"""Per-request server context for authenticated Admin reads.

The context is process/task local and is never serialized into browser payloads.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class AdminRequestContext:
    principal: str | None
    auth_method: str | None


_CURRENT = ContextVar("holoviewer_admin_request_context", default=AdminRequestContext(None, None))


def set_admin_request_context(principal: str | None, auth_method: str | None):
    return _CURRENT.set(AdminRequestContext(principal, auth_method))


def reset_admin_request_context(token) -> None:
    _CURRENT.reset(token)


def current_admin_request_context() -> AdminRequestContext:
    return _CURRENT.get()
