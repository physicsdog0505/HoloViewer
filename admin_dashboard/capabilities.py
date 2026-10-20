"""Capability-based Production evidence reader contracts.

Phase 1 defines interfaces, scopes, fake readers and disabled defaults only.
No Production client is implemented here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


SOURCES = ("d1", "archive", "api_semantic", "publisher", "collector")


@dataclass(frozen=True)
class D1ReadScope:
    day: str
    aids: tuple[str, ...]
    page_size: int = 100
    max_pages: int = 5
    query_groups: int = 3
    verification_mode: str = "bounded_sample"

    def __post_init__(self):
        if not self.day or len(self.day) != 10:
            raise ValueError("invalid day")
        if len(self.aids) > 100 or any(not aid or len(aid) > 64 for aid in self.aids):
            raise ValueError("invalid aid scope")
        if not (1 <= self.page_size <= 100):
            raise ValueError("page_size out of bounds")
        if not (1 <= self.max_pages <= 5):
            raise ValueError("max_pages out of bounds")
        if not (1 <= self.query_groups <= 3):
            raise ValueError("query_groups out of bounds")
        if self.page_size * self.max_pages > 500:
            raise ValueError("row budget exceeded")
        if self.verification_mode not in {"bounded_sample", "full_partition"}:
            raise ValueError("invalid verification mode")


@dataclass(frozen=True)
class ArchiveReadScope:
    from_day: str
    through_day: str

    def __post_init__(self):
        if len(self.from_day) != 10 or len(self.through_day) != 10:
            raise ValueError("invalid archive day scope")
        if self.from_day > self.through_day:
            raise ValueError("invalid archive range")


@dataclass(frozen=True)
class ReaderTimeouts:
    connect_seconds: float = 2.0
    read_seconds: float = 5.0
    admission_seconds: float = 2.0


@dataclass(frozen=True)
class SourceGate:
    enabled: bool = False
    credential_required: bool = True


@dataclass(frozen=True)
class ProductionReaderConfig:
    d1: SourceGate = field(default_factory=SourceGate)
    archive: SourceGate = field(default_factory=SourceGate)
    api_semantic: SourceGate = field(default_factory=SourceGate)
    publisher: SourceGate = field(default_factory=lambda: SourceGate(False, False))
    collector: SourceGate = field(default_factory=lambda: SourceGate(False, False))
    timeouts: ReaderTimeouts = field(default_factory=ReaderTimeouts)


class ServerCredentialProvider(Protocol):
    """Returns opaque server-only availability; never exposes credential material."""

    def available(self, source: str) -> bool:
        ...


class NoProductionCredentials:
    def available(self, source: str) -> bool:
        return False


class ProductionEvidenceReader(Protocol):
    """Narrow read-only capability surface. No SQL/URL/path arguments exist."""

    def read_d1_snapshot(self, scope: D1ReadScope) -> dict:
        ...

    def read_archive_delivery_evidence(self, scope: ArchiveReadScope) -> dict:
        ...

    def read_api_semantic_health(self) -> dict:
        ...

    def read_publisher_evidence(self) -> dict:
        ...

    def read_collector_evidence(self) -> dict:
        ...


class DeniedProductionEvidenceReader:
    """Default implementation: every Production capability is unavailable."""

    def _deny(self):
        raise RuntimeError("source_disabled")

    def read_d1_snapshot(self, scope: D1ReadScope) -> dict:
        return self._deny()

    def read_archive_delivery_evidence(self, scope: ArchiveReadScope) -> dict:
        return self._deny()

    def read_api_semantic_health(self) -> dict:
        return self._deny()

    def read_publisher_evidence(self) -> dict:
        return self._deny()

    def read_collector_evidence(self) -> dict:
        return self._deny()


class FakeProductionEvidenceReader:
    """Test-only fake. Data is injected by trusted test code, never request input."""

    def __init__(self, *, d1=None, archive=None, api=None, publisher=None, collector=None,
                 failures=None):
        self._values = {
            "d1": d1, "archive": archive, "api_semantic": api,
            "publisher": publisher, "collector": collector,
        }
        self._failures = dict(failures or {})
        self.calls: list[str] = []

    def _read(self, source: str):
        self.calls.append(source)
        if source in self._failures:
            raise RuntimeError(self._failures[source])
        return self._values.get(source)

    def read_d1_snapshot(self, scope: D1ReadScope) -> dict:
        return self._read("d1")

    def read_archive_delivery_evidence(self, scope: ArchiveReadScope) -> dict:
        return self._read("archive")

    def read_api_semantic_health(self) -> dict:
        return self._read("api_semantic")

    def read_publisher_evidence(self) -> dict:
        return self._read("publisher")

    def read_collector_evidence(self) -> dict:
        return self._read("collector")
