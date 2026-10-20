"""Server-side authentication contracts for the internal 8501 Admin boundary."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True)
class AuthResult:
    authenticated: bool
    principal: str | None
    auth_method: str | None
    observed_at: str
    error_code: str | None = None

    @classmethod
    def deny(cls, error_code: str = "auth_required") -> "AuthResult":
        return cls(False, None, None, _now(), error_code)

    @classmethod
    def allow(cls, principal: str, auth_method: str) -> "AuthResult":
        if not principal or not auth_method:
            return cls.deny("auth_invalid")
        return cls(True, principal, auth_method, _now(), None)


class AdminAuthenticator(Protocol):
    """Host-owned authenticator. Credential material never enters AuthResult."""

    def authenticate(self, request_context: dict) -> AuthResult:
        ...


class FixtureAdminAuthenticator:
    """Test-only authenticator; never production authentication proof."""

    def __init__(self, *, principal: str = "fixture-admin", allow: bool = True):
        self._principal = principal
        self._allow = bool(allow)

    def authenticate(self, request_context: dict) -> AuthResult:
        return (AuthResult.allow(self._principal, "fixture")
                if self._allow else AuthResult.deny())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
