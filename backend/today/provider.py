"""Storage-neutral read contract for both 8788 and future Cloudflare adapters."""
from dataclasses import dataclass
from typing import Protocol, Iterable, Mapping
from .engine import project

class TodayProvider(Protocol):
    def read_observations(self) -> Iterable[Mapping]: ...
    def coverage(self) -> Mapping: ...

@dataclass(frozen=True)
class LocalTodayProvider:
    observations: tuple
    coverage_record: Mapping
    def read_observations(self):
        return iter(self.observations)
    def coverage(self):
        return self.coverage_record

@dataclass(frozen=True)
class CloudflareTodayProvider:
    """Callback adapter only: no Worker, API or D1 calls are implemented here."""
    read_rows: object
    read_coverage: object
    def read_observations(self):
        return iter(self.read_rows())
    def coverage(self):
        return self.read_coverage()

def today_contract(provider: TodayProvider, *, now):
    coverage = provider.coverage()
    return project(tuple(provider.read_observations()), now=now,
        last_success_at=coverage.get("last_success_at"),
        expected_channels=coverage.get("expected_channels", 66),
        scanned_channels=coverage.get("scanned_channels", 0),
        gap=coverage.get("gap", True))
