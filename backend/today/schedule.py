"""Pure quota and retry decision policy; no scheduled trigger is registered."""
from dataclasses import dataclass
from math import ceil
@dataclass(frozen=True)
class Budget:
    daily_units:int=10000
    reserved_units:int=1500
    scan_minutes:int=30
    active_minutes:int=10
    max_retries:int=3
    max_overlap_pages:int=2
    max_candidates:int=200
    def __post_init__(self):
        if self.daily_units<1 or not 0<=self.reserved_units<self.daily_units:
            raise ValueError("unsafe quota")
        if self.scan_minutes<10 or self.active_minutes<5 or not 1<=self.max_retries<=5:
            raise ValueError("unsafe schedule")
        if not 1<=self.max_overlap_pages<=3 or not 1<=self.max_candidates<=200:
            raise ValueError("unsafe bounds")
    def permits(self,used,cost):
        return used>=0 and cost>0 and used+cost<=self.daily_units-self.reserved_units
    def permits_retry(self,attempt):
        return 1<=attempt<=self.max_retries
    def retry_seconds(self,attempt):
        if not self.permits_retry(attempt):
            return None
        return min(3600,60*2**(attempt-1))
    def requests_per_day_estimate(self,channel_count=66,video_batches=72):
        return channel_count*ceil(1440/self.scan_minutes)+video_batches
