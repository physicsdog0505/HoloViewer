"""Time conversion helpers shared by the read-only frontend.

PTT push rows contain only month/day and local wall-clock time.  The article
filename contains a Unix timestamp, and Hololive thread titles normally contain
an ROC date marker (for example 1150924).  These helpers turn all three sources
into timezone-aware Asia/Taipei datetimes before the UI compares them.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
UTC = ZoneInfo("UTC")
ARTICLE_TIMESTAMP_RE = re.compile(
    r"/M\.(\d+)\.A\.[0-9A-Fa-f]{3}(?:\.html)?(?:[/?#]|$)"
)
ROC_DATE_RE = re.compile(r"(?<!\d)(1\d{6})(?!\d)")
_YOUTUBE_V_RE = re.compile(r"(?:[?&]|\b)v=([A-Za-z0-9_-]{6,20})(?:[&#\s]|$)", re.I)
_YOUTUBE_SHORT_RE = re.compile(r"youtu\.be/([A-Za-z0-9_-]{6,20})(?:[?&#/\s]|$)", re.I)
_YOUTUBE_PATH_RE = re.compile(r"youtube\.com/(?:live|shorts|embed)/([A-Za-z0-9_-]{6,20})(?:[?&#/\s]|$)", re.I)


def article_published_at(url: str) -> datetime:
    match = ARTICLE_TIMESTAMP_RE.search(url)
    if not match:
        raise ValueError("文章網址不含可辨識的 PTT 發布時間")
    return datetime.fromtimestamp(int(match.group(1)), tz=UTC).astimezone(TAIPEI)


def thread_date(title: str, url: str) -> date:
    """Return the Taiwan calendar date represented by a thread."""
    match = ROC_DATE_RE.search(title)
    if match:
        marker = match.group(1)
        year = int(marker[:3]) + 1911
        month = int(marker[3:5])
        day = int(marker[5:7])
        return date(year, month, day)
    return article_published_at(url).date()


def _normalized_push_candidate(
    year: int, month: int, day: int, hour: int, minute: int
) -> datetime:
    if not 1 <= month <= 12 or day < 1:
        raise ValueError("PTT 推文日期不合法")
    month_start = datetime(year, month, 1, hour, minute, tzinfo=TAIPEI)
    return month_start + timedelta(days=day - 1)


def push_datetime(
    ptt_date: str, ptt_time: str, *, article_title: str, article_url: str
) -> datetime:
    month, day = (int(value) for value in ptt_date.split("/"))
    hour, minute = (int(value) for value in ptt_time.split(":"))
    base_date = thread_date(article_title, article_url)
    published = article_published_at(article_url)
    candidates = [
        _normalized_push_candidate(year, month, day, hour, minute)
        for year in (base_date.year - 1, base_date.year, base_date.year + 1)
    ]
    return min(candidates, key=lambda candidate: abs(candidate - published))


def youtube_video_id(value: str) -> str | None:
    """Extract a YouTube video id without contacting YouTube.

    Besides normal URLs, tolerate copied URLs that contain surrounding text or
    playlist parameters.  Watch-along inputs often come from the browser address
    bar and may include ``&list=...`` or other suffixes.
    """
    value = value.strip()
    if not value:
        return None

    # Fast tolerant path first.  This also handles a valid YouTube URL embedded
    # in copied descriptive text without downgrading it to generic companion mode.
    for pattern in (_YOUTUBE_V_RE, _YOUTUBE_SHORT_RE, _YOUTUBE_PATH_RE):
        match = pattern.search(value)
        if match:
            return match.group(1)

    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower().split(":", 1)[0]
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/", 1)[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}:
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif len(parts) >= 2 and parts[0] in {"live", "shorts", "embed"}:
            candidate = parts[1]
        else:
            candidate = ""
    else:
        return None
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", candidate) else None


def relative_label(moment: datetime, stream_start: datetime) -> str:
    seconds = int((moment.astimezone(UTC) - stream_start.astimezone(UTC)).total_seconds())
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{sign}{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{sign}{minutes:02d}:{secs:02d}"
