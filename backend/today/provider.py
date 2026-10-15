"""Consumer boundary: swap local and cloud readers without exposing storage internals."""
from dataclasses import dataclass
from typing import Protocol, Mapping
from datetime import datetime, timezone
from .engine import project

class TodayProvider(Protocol):
    def read_today(self, day: str, limit: int) -> Mapping: ...

def _resolve(rows, coverage, *, day, limit, now):
    datetime.strptime(day, "%Y-%m-%d")
    return project(tuple(rows),now=now,limit=limit,
        last_success_at=coverage.get("last_success_at"),
        expected_channels=coverage.get("expected_channels",66),
        scanned_channels=coverage.get("scanned_channels",0),
        gap=coverage.get("gap",True),
        completeness_evidence=coverage.get("completeness_evidence"),
        checkpoint=coverage.get("checkpoint"),
        roster_version=coverage.get("roster_version"))

@dataclass(frozen=True)
class LocalTodayProvider:
    observations: tuple
    coverage_record: Mapping
    now: datetime | None = None
    def read_today(self, day, limit=200):
        return _resolve(self.observations,self.coverage_record,day=day,limit=limit,
                        now=self.now or datetime.now(timezone.utc))

@dataclass(frozen=True)
class CloudflareTodayProvider:
    """Cloud transport callback injection; no Worker/D1/network implementation."""
    read_rows: object
    read_coverage: object
    now: datetime | None = None
    def read_today(self, day, limit=200):
        return _resolve(self.read_rows(),self.read_coverage(),day=day,limit=limit,
                        now=self.now or datetime.now(timezone.utc))

def today_contract(provider: TodayProvider, *, day=None, limit=200, now=None):
    # Compatibility helper only: injected clock supports former tests.
    if now is not None and isinstance(provider, LocalTodayProvider):
        provider = LocalTodayProvider(provider.observations, provider.coverage_record, now)
    if now is not None and isinstance(provider, CloudflareTodayProvider):
        provider = CloudflareTodayProvider(provider.read_rows, provider.read_coverage, now)
    ref = now or datetime.now(timezone.utc)
    return provider.read_today(day or ref.strftime("%Y-%m-%d"),limit)
