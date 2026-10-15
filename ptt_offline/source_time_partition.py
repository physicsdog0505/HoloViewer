"""Conservative source-date candidate classification; never publication authority.

PTT push lines contain MM/DD HH:MM, while collected_at is an observation
timestamp, NOT event time. Observation bounds only constrain possible years.
A unique matching year is INFERRED, never independently VERIFIED; ambiguous,
malformed, stale or contradictory values remain PENDING with raw fields intact.
This is a per-row nonblocking partition and does not publish to D1.
"""
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
import re
from .public_today_contract import ContractError
from .ptt_aid_identity import identity_receipt

TPE=ZoneInfo("Asia/Taipei")
_DATE=re.compile(r"^(\d\d)/(\d\d)$")
_TIME=re.compile(r"^(\d\d):(\d\d)$")

def partition_candidate_rows(*,board,aid,url,rows,timezone_evidence=False,max_rows=50000):
    evidence=identity_receipt(board,aid,url)
    if not isinstance(rows,list) or len(rows)>max_rows:
        raise ContractError("bounded explicit push rows required")
    epoch=int(re.search(r"/M\.(\d+)\.A\.",url).group(1))
    article=datetime.fromtimestamp(epoch,tz=timezone.utc)
    output={"identity":evidence,"inferred":[],"pending":[],"verified":[]}
    last=0
    for row in rows:
        src=dict(row)
        line=src.get("source_line")
        if type(line) is not int or line<=last:
            raise ContractError("nonmonotonic source-line identity")
        last=line
        date=_DATE.fullmatch(src.get("ptt_date") or "")
        tm=_TIME.fullmatch(src.get("ptt_time") or "")
        pending_reason=None
        if not timezone_evidence:
            pending_reason="ptt-display-timezone-unverified"
        if not date or not tm:
            pending_reason="invalid-source-calendar"
        observed=None
        if pending_reason is None:
            try:
                observed=datetime.fromisoformat(src.get("collected_at","").replace("Z","+00:00"))
                if observed.tzinfo is None:
                    pending_reason="unverified-observation-time"
                else:
                    observed=observed.astimezone(timezone.utc)
            except (ValueError,TypeError,AttributeError):
                pending_reason="unverified-observation-time"
        candidates=[]
        if pending_reason is None:
            mm,dd=map(int,date.groups())
            hh,minute=map(int,tm.groups())
            if observed < article:
                pending_reason="observation-predates-article"
            elif observed.year-article.year > 30:
                pending_reason="unbounded-source-lifetime"
            else:
                for year in range(article.astimezone(TPE).year, observed.astimezone(TPE).year+1):
                    try:
                        possible=datetime(year,mm,dd,hh,minute,tzinfo=TPE).astimezone(timezone.utc)
                    except ValueError:
                        continue
                    if article-timedelta(minutes=1)<=possible<=observed:
                        candidates.append(possible)
                if len(candidates)!=1:
                    pending_reason="multiple-possible-years" if candidates else "no-valid-year"
        if pending_reason:
            output["pending"].append({"source_line":line,"reason":pending_reason,
                "ptt_date":src.get("ptt_date"),"ptt_time":src.get("ptt_time")})
        else:
            output["inferred"].append({"source_line":line,
                "occurred_at":candidates[0].isoformat(timespec="seconds").replace("+00:00","Z"),
                "classification":"INFERRED_NOT_VERIFIED"})
    return output
