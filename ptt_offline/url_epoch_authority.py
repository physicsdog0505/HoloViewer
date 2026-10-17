"""Offline URL-epoch anchored PTT event chronology; no Collector observation-time fallback.

This is a deliberately conservative source-only candidate. The canonical
C_Chat article URL carries article creation epoch, not a timestamp for every
push. Every MM/DD HH:MM is validated against that anchor in source-line order.
Unobserved long intervals/year rollovers fail closed instead of guessing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re

from .public_today_contract import ContractError, normalize_public_aid, taipei_day

TAIPEI=ZoneInfo("Asia/Taipei")
URL=re.compile(r"^https://www\.ptt\.cc/bbs/C_Chat/M\.([0-9]{9,11})\.A\.([0-9A-Fa-f]+)\.html$")
DATE=re.compile(r"^(\d{2})/(\d{2})$")
TIME=re.compile(r"^(\d{2}):(\d{2})$")
MAX_UNOBSERVED_DAYS=45


def article_epoch(*,board:str,aid:str,url:str,identity_verifier=None) -> datetime:
    if board != "C_Chat":
        raise ContractError("unverified board")
    aid=normalize_public_aid(aid)
    m=URL.fullmatch(url or "")
    if not m:
        raise ContractError("unverified canonical article URL")
    if not callable(identity_verifier):
        raise ContractError("independent article AID/URL identity receipt required")
    try:
        verified=identity_verifier(board,aid,url)
    except Exception as exc:
        raise ContractError("article identity verifier unavailable") from exc
    if verified is not True:
        raise ContractError("independent article AID/URL identity receipt required")
    try:
        posted=datetime.fromtimestamp(int(m.group(1)),tz=timezone.utc).astimezone(TAIPEI)
    except (OverflowError,OSError,ValueError) as exc:
        raise ContractError("invalid article URL epoch") from exc
    if not 1995 <= posted.year <= 2100:
        raise ContractError("invalid article epoch year")
    return posted


def reconstruct_events(*,board:str,aid:str,url:str,pushes:list[dict],
                       identity_verifier=None,
                       reviewed_chronology_exceptions:bool=False) -> list[dict]:
    """Return UTC second events; require strict chronological source-line evidence.

    This intentionally does not use collected_at or captured_at. A first push
    may occur in January after a December article. Any unobserved >45 day gap
    is held for separate positive evidence; this avoids silently assigning an
    unknown year to an old thread with sparse pushes.
    """
    anchor=article_epoch(board=board,aid=aid,url=url,
                         identity_verifier=identity_verifier)
    canonical=normalize_public_aid(aid)
    output=[]
    # PTT exposes only minute precision. Comparing a displayed HH:MM value to
    # URL epoch seconds would manufacture an ordering distinction the source
    # cannot express, so anchor chronology at the containing minute.
    previous=anchor.replace(second=0,microsecond=0)
    last_line=0
    for row in pushes:
        line=row.get("source_line")
        if type(line) is not int or line <= last_line:
            raise ContractError("source lines must be strictly increasing")
        last_line=line
        md=DATE.fullmatch(row.get("ptt_date") or "")
        tm=TIME.fullmatch(row.get("ptt_time") or "")
        if not md or not tm:
            raise ContractError("invalid source PTT timestamp text")
        month,day=map(int,md.groups())
        hour,minute=map(int,tm.groups())
        try:
            event=datetime(previous.year,month,day,hour,minute,tzinfo=TAIPEI)
        except ValueError as exc:
            raise ContractError("invalid source PTT calendar date") from exc
        # The only permitted rollover is observed Dec -> Jan, including first
        # push after a December URL-epoch article. Other regression is rejected.
        time_quality="source-minute"
        chronology_note=None
        reviewed_regression=False
        if event < previous:
            if previous.month != 12 or month != 1:
                if not reviewed_chronology_exceptions:
                    raise ContractError("unobserved or regressive source chronology")
                time_quality="source-minute-regression"
                reviewed_regression=True
                chronology_note=(
                    f"reviewed source chronology exception: line {line} "
                    f"{event.strftime('%m/%d %H:%M')} precedes prior source minute "
                    f"{previous.strftime('%m/%d %H:%M')}"
                )
            else:
                try:
                    event=event.replace(year=previous.year+1)
                except ValueError as exc:
                    raise ContractError("invalid year rollover") from exc
        if event < previous - timedelta(minutes=1) and not reviewed_regression:
            raise ContractError("push predates article or preceding push")
        if event - previous > timedelta(days=MAX_UNOBSERVED_DAYS):
            raise ContractError("unobserved interval requires separate time authority")
        # Collector text has only minute precision; treat equal-minute rows
        # as ordered by canonical source_line, not manufactured seconds.
        occurred=event.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
        output.append({**row,"aid":canonical,"occurred_at":occurred,
                       "day":taipei_day(occurred),
                       "source_record_key":f"{canonical}:{line}",
                       "time_quality":time_quality,
                       **({"chronology_note":chronology_note} if chronology_note else {})})
        previous=event
    return output
