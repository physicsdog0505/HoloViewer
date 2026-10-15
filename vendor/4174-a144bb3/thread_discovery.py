"""Discover current Hololive day/night threads from the public PTT index."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from html.parser import HTMLParser
import re
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from collector_settings import DISCOVERY_MAX_PAGES


BASE_URL = "https://www.ptt.cc"
INDEX_URL = f"{BASE_URL}/bbs/C_Chat/index.html"
ARTICLE_RE = re.compile(r"/bbs/C_Chat/M\.(\d+)\.A\.([0-9A-Fa-f]{3})\.html")
PREV_RE = re.compile(r"/bbs/C_Chat/index\d+\.html")
AID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
EVENING_LABELS = ("晚間", "夜間", "晚串", "夜串")
DAY_LABELS = ("日間", "早間", "晨間", "日串", "早串", "晨串")
ALL_DAY_LABELS = ("本日", "全日", "全天")


@dataclass(frozen=True)
class ArticleTarget:
    aid: str
    url: str
    title: str
    timestamp: int
    period: str

    @property
    def markers(self) -> tuple[str, ...]:
        date_marker = re.search(r"\b1\d{6}\b", self.title)
        return ("Hololive", date_marker.group(0)) if date_marker else ("Hololive",)


class IndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.current_href: str | None = None
        self.current_text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "a":
            self.current_href = dict(attrs).get("href")
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.current_href is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current_href is not None:
            self.links.append((self.current_href, "".join(self.current_text).strip()))
            self.current_href = None
            self.current_text = []


def filename_to_aid(timestamp: int, suffix: int) -> str:
    value = (timestamp << 12) | suffix
    return "#" + "".join(
        AID_ALPHABET[(value >> shift) & 0x3F] for shift in range(42, -1, -6)
    )


def parse_index(html: str) -> tuple[list[ArticleTarget], str | None]:
    parser = IndexParser()
    parser.feed(html)
    articles: list[ArticleTarget] = []
    previous: str | None = None
    for href, title in parser.links:
        if "上頁" in title and (
            PREV_RE.fullmatch(href) or href.startswith("/bbs/C_Chat/search?")
        ):
            previous = urljoin(BASE_URL, href)
        match = ARTICLE_RE.fullmatch(href)
        if not match or "Hololive" not in title:
            continue
        if any(label in title for label in EVENING_LABELS):
            period = "晚間"
        elif any(label in title for label in DAY_LABELS):
            period = "日間"
        elif any(label in title for label in ALL_DAY_LABELS):
            period = "本日"
        else:
            continue
        timestamp = int(match.group(1))
        articles.append(
            ArticleTarget(
                aid=filename_to_aid(timestamp, int(match.group(2), 16)),
                url=urljoin(BASE_URL, href),
                title=title,
                timestamp=timestamp,
                period=period,
            )
        )
    return articles, previous


def fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={"Cookie": "over18=1", "User-Agent": "Hololive-PTT-collector/14"},
    )
    with urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8", errors="replace")


def discover_latest(max_pages: int = DISCOVERY_MAX_PAGES) -> ArticleTarget:
    url: str | None = INDEX_URL
    found: list[ArticleTarget] = []
    for _ in range(max_pages):
        if url is None:
            break
        articles, url = parse_index(fetch_text(url))
        found.extend(articles)
        if found:
            break
    if not found:
        raise RuntimeError(f"最近 {max_pages} 頁找不到 Hololive 日間串或夜間串")
    return max(found, key=lambda item: item.timestamp)


def roc_date_marker(value: date) -> str:
    return f"{value.year - 1911:03d}{value.month:02d}{value.day:02d}"


def discover_for_date(value: date, max_pages: int = 10) -> list[ArticleTarget]:
    marker = roc_date_marker(value)
    url: str | None = f"{BASE_URL}/bbs/C_Chat/search?" + urlencode({"q": marker})
    found: dict[str, ArticleTarget] = {}
    for _ in range(max_pages):
        if url is None:
            break
        articles, url = parse_index(fetch_text(url))
        for article in articles:
            if marker in article.title:
                found[article.aid] = article

    if value == date.today():
        try:
            latest = discover_latest()
        except Exception:
            latest = None
        if latest is not None and marker in latest.title:
            found[latest.aid] = latest

    if not found:
        raise RuntimeError(f"找不到 {value.isoformat()} 的 Hololive 日間串或晚間串")
    return sorted(found.values(), key=lambda item: item.timestamp)


def _targets_for_active_day(
    value: date,
    latest: ArticleTarget,
    *,
    max_pages: int,
) -> list[ArticleTarget]:
    """Find all threads for an active day while always retaining the known latest target."""
    try:
        targets = discover_for_date(value, max_pages=max_pages)
    except Exception:
        targets = []
    found = {target.aid: target for target in targets}
    found[latest.aid] = latest
    return sorted(found.values(), key=lambda item: item.timestamp)


def discover_current_window(value: date, max_pages: int = 10) -> tuple[date, list[ArticleTarget], bool]:
    """Follow the board's latest active thread day across midnight.

    Around midnight the calendar has already changed while the active Hololive
    thread can still belong to the previous day. Use the same board-index latest
    signal as the live Collector to decide which calendar-day thread set remains
    active. Date search is then used only to fill in the other day/night thread(s)
    for that active day.
    """
    previous = value - timedelta(days=1)
    try:
        latest = discover_latest()
    except Exception:
        latest = None

    if latest is not None:
        if roc_date_marker(value) in latest.title:
            return value, _targets_for_active_day(value, latest, max_pages=max_pages), False
        if roc_date_marker(previous) in latest.title:
            return previous, _targets_for_active_day(previous, latest, max_pages=max_pages), True

    try:
        return value, discover_for_date(value, max_pages=max_pages), False
    except RuntimeError as today_error:
        try:
            return previous, discover_for_date(previous, max_pages=max_pages), True
        except RuntimeError:
            raise today_error
