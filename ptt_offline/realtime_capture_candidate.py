"""Strict Collector near-live time candidate; not independent event-year proof.

The Collector UTC first-seen timestamp is OBSERVATION, never source event time.
Only records whose parsed PTT minute and first-seen UTC agree to <=180s are
eligible for separately owner-authorized realtime timestamp policy.
"""
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from .public_today_contract import ContractError

TAIPEI=ZoneInfo("Asia/Taipei")
MAX_CAPTURE_DELAY_SECONDS=180

def near_capture_candidate(row):
    try:
        raw=row["collected_at"]
        observed=datetime.fromisoformat(raw.replace("Z","+00:00"))
        occurred=datetime.fromisoformat(row["occurred_at"].replace("Z","+00:00"))
        if observed.tzinfo is None or occurred.tzinfo is None:
            return False
        observed=observed.astimezone(timezone.utc)
        occurred=occurred.astimezone(timezone.utc)
        delta=(observed-occurred).total_seconds()
        ptt_local=occurred.astimezone(TAIPEI)
        return (0<=delta<=MAX_CAPTURE_DELAY_SECONDS and
                row.get("ptt_date")==ptt_local.strftime("%m/%d") and
                row.get("ptt_time")==ptt_local.strftime("%H:%M") and
                type(row.get("source_line")) is int and row["source_line"]>0)
    except (ValueError,TypeError,AttributeError,KeyError,OverflowError):
        return False
