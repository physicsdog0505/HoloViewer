"""Offline bounded scheduler policy. Cloud Cron adapter intentionally absent."""
from dataclasses import dataclass
from datetime import timedelta

@dataclass(frozen=True)
class Budget:
    daily_units: int = 10000
    reserved_units: int = 1500
    scan_minutes: int = 30
    active_minutes: int = 10
    max_retries: int = 3
    max_overlap_pages: int = 2
    max_candidates: int = 200
    def __post_init__(self):
        if self.daily_units < 1 or self.reserved_units < 0 or self.reserved_units >= self.daily_units:
            raise ValueError("invalid quota budget")
        if self.scan_minutes < 10 or self.active_minutes < 5 or self.max_retries not in range(1, 6):
            raise ValueError("unsafe schedule")
        if self.max_overlap_pages not in range(1, 4) or self.max_candidates not in range(1, 201):
            raise ValueError("unbounded discovery")
    def permits(self, used, cost):
        return 0 <= used and 0 < cost and used + cost <= self.daily_units - self.reserved_units
    def retry_seconds(self, attempt):
        if attempt < 1:
            raise ValueError("invalid attempt")
        return min(3600, 60 * 2 ** min(attempt - 1, self.max_retries))
    def requests_per_day_estimate(self, channel_count=66, video_batches=72):
        return channel_count * (1440 // self.scan_minutes) + video_batches
