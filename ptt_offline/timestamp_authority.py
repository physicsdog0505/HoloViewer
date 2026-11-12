"""Fail-closed timestamp authority for #48 Publisher preparation.

Canonical Collector rows store only MM/DD + HH:MM. They do not contain year
or timezone. This module therefore accepts timestamps only when an explicit,
reviewable source-evidence record supplies both. collected_at/captured_at may
bound or identify evidence, but are never substituted as event time.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import re

from .public_today_contract import ContractError

TAIPEI = ZoneInfo("Asia/Taipei")
MMDD = re.compile(r"^(\d{2})/(\d{2})$")
HHMM = re.compile(r"^(\d{2}):(\d{2})$")
ALLOWED_AUTHORITIES = {
    "verified_ptt_screen_calendar",
    "verified_archive_calendar",
}


def resolve_source_timestamp(*, ptt_date: str, ptt_time: str,
                             evidence: dict) -> str:
    """Resolve one canonical event timestamp from positive calendar evidence.

    Evidence must bind the exact source line/AID outside this helper and must
    explicitly assert the event year and PTT display timezone. This helper
    intentionally has no fallback to collected_at, captured_at or current year.
    """
    if not isinstance(evidence, dict):
        raise ContractError("timestamp evidence required")
    if evidence.get("authority") not in ALLOWED_AUTHORITIES:
        raise ContractError("unapproved timestamp authority")
    if evidence.get("timezone") != "Asia/Taipei":
        raise ContractError("PTT event timezone not verified as Asia/Taipei")
    year=evidence.get("year")
    if type(year) is not int or year < 1995 or year > 2100:
        raise ContractError("verified event year required")
    source_ref=evidence.get("source_ref")
    if not isinstance(source_ref,str) or not source_ref.strip():
        raise ContractError("timestamp source_ref required")

    md=MMDD.fullmatch(ptt_date or "")
    tm=HHMM.fullmatch(ptt_time or "")
    if not md or not tm:
        raise ContractError("invalid PTT date/time")
    month,day=map(int,md.groups())
    hour,minute=map(int,tm.groups())
    try:
        event=datetime(year,month,day,hour,minute,tzinfo=TAIPEI)
    except ValueError as exc:
        raise ContractError("invalid verified PTT calendar timestamp") from exc
    return event.isoformat(timespec="minutes")


def selected_taipei_day(timestamp: str) -> str:
    try:
        dt=datetime.fromisoformat(timestamp)
    except (TypeError,ValueError) as exc:
        raise ContractError("invalid resolved timestamp") from exc
    if dt.tzinfo is None:
        raise ContractError("resolved timestamp must be timezone-aware")
    return dt.astimezone(TAIPEI).date().isoformat()
