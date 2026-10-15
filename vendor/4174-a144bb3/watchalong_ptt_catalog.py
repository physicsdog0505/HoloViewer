"""Offline/read-only extraction of Watchalong events from stored PTT article bodies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import argparse
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
PTT_TS_RE = re.compile(r"/M\.(\d{9,10})\.")
TIME_RE = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})$")
URL_RE = re.compile(r"https?://[^\s<>'\"]+")
WATCHALONG_RE = re.compile(
    r"(同時視聽|同時視聴|同時觀看|同時鑑賞|鑑賞会|視聴会|"
    r"watch\s*along|watchalong|watch\s*party|ウォッチパーティー?|ウォッチアロング)",
    re.IGNORECASE,
)
MEMBER_ONLY_RE = re.compile(r"(會員限定|メンバー限定|member(?:s)?\s*only)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class WatchalongStream:
    label: str
    url: str
    video_id: str


@dataclass(frozen=True, slots=True)
class WatchalongEvent:
    aid: str
    article_title: str
    source_url: str
    article_datetime: str
    day: str
    scheduled_time: str
    description: str
    member_only: bool
    streams: tuple[WatchalongStream, ...]


def youtube_video_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host in {"youtu.be", "www.youtu.be"}:
        value = parsed.path.strip("/").split("/")[0]
        return value or None
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        for prefix in ("/live/", "/shorts/"):
            if parsed.path.startswith(prefix):
                value = parsed.path[len(prefix):].split("/")[0]
                return value or None
    return None


def article_datetime(source_url: str) -> datetime | None:
    match = PTT_TS_RE.search(source_url or "")
    if match is None:
        return None
    try:
        return datetime.fromtimestamp(int(match.group(1)), timezone.utc).astimezone(TAIPEI)
    except (OverflowError, OSError, ValueError):
        return None


def _clean_lines(body_text: str) -> list[str]:
    return [line.strip() for line in body_text.splitlines()]


def _next_nonempty(lines: list[str], start: int) -> tuple[int, str] | None:
    for index in range(start, len(lines)):
        if lines[index]:
            return index, lines[index]
    return None


def _previous_time(lines: list[str], index: int) -> str:
    checked = 0
    for cursor in range(index - 1, -1, -1):
        value = lines[cursor]
        if not value:
            continue
        checked += 1
        if checked > 4:
            break
        if TIME_RE.fullmatch(value):
            return value
        if youtube_video_id(value):
            break
    return ""


def _extract_youtube_urls(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for match in URL_RE.finditer(text):
        url = match.group(0).rstrip(").,，。;；:：!?！？]}>」』】")
        video_id = youtube_video_id(url)
        if video_id:
            found.append((url, video_id))
    return found


def _fallback_host_label(description: str) -> str:
    for marker in ("《", "「", "『", "【", "（", "("):
        if marker in description:
            prefix = description.split(marker, 1)[0].strip()
            if prefix:
                return prefix
    match = WATCHALONG_RE.search(description)
    if match:
        prefix = description[: match.start()].strip(" ：:")
        if prefix:
            return prefix
    return description


def _parse_direct_stream(lines: list[str], description_index: int, description: str) -> tuple[WatchalongStream, ...]:
    nxt = _next_nonempty(lines, description_index + 1)
    if nxt is None:
        return ()
    _index, value = nxt
    urls = _extract_youtube_urls(value)
    if not urls:
        return ()
    label = _fallback_host_label(description)
    return tuple(WatchalongStream(label=label, url=url, video_id=video_id) for url, video_id in urls)


def _parse_labeled_streams(lines: list[str], description_index: int) -> tuple[WatchalongStream, ...]:
    streams: list[WatchalongStream] = []
    cursor = description_index + 1
    while cursor < len(lines):
        nxt = _next_nonempty(lines, cursor)
        if nxt is None:
            break
        index, value = nxt

        if TIME_RE.fullmatch(value) or WATCHALONG_RE.search(value):
            break

        urls = _extract_youtube_urls(value)
        if urls:
            first_url = urls[0][0]
            label = value[: value.find(first_url)].strip().rstrip("：:")
            if not label:
                break
            streams.extend(
                WatchalongStream(label=label, url=url, video_id=video_id)
                for url, video_id in urls
            )
            cursor = index + 1
            continue

        following = _next_nonempty(lines, index + 1)
        if following is None:
            break
        following_index, following_value = following
        following_urls = _extract_youtube_urls(following_value)
        if not following_urls:
            break
        had_label_colon = value.rstrip().endswith(("：", ":"))
        label = value.rstrip("：:").strip()
        if not label:
            break
        # Label-on-one-line blocks in the PTT schedule use a bare channel/member
        # name followed by its URL. A trailing colon is an explicit host-label
        # marker and may legitimately contain spaces (for example "UNIT B官台：").
        # Otherwise, whitespace strongly indicates the next normal schedule
        # entry (member + stream title), so stop before consuming it.
        if any(char.isspace() for char in label) and not had_label_colon:
            break
        streams.extend(
            WatchalongStream(label=label, url=url, video_id=video_id)
            for url, video_id in following_urls
        )
        cursor = following_index + 1

    return tuple(streams)


def parse_watchalong_events(
    *,
    aid: str,
    article_title: str,
    source_url: str,
    body_text: str,
) -> tuple[WatchalongEvent, ...]:
    lines = _clean_lines(body_text)
    article_dt = article_datetime(source_url)
    events: list[WatchalongEvent] = []

    for index, description in enumerate(lines):
        if not description or not WATCHALONG_RE.search(description):
            continue

        nxt = _next_nonempty(lines, index + 1)
        if nxt is None:
            continue
        _next_index, next_value = nxt

        if _extract_youtube_urls(next_value) and not next_value.split("http", 1)[0].strip(" ：:"):
            streams = _parse_direct_stream(lines, index, description)
        else:
            streams = _parse_labeled_streams(lines, index)

        if not streams:
            continue

        unique: dict[str, WatchalongStream] = {}
        for stream in streams:
            unique.setdefault(stream.video_id, stream)

        events.append(
            WatchalongEvent(
                aid=aid,
                article_title=article_title,
                source_url=source_url,
                article_datetime=article_dt.isoformat(timespec="minutes") if article_dt else "",
                day=article_dt.date().isoformat() if article_dt else "",
                scheduled_time=_previous_time(lines, index),
                description=description,
                member_only=bool(MEMBER_ONLY_RE.search(description)),
                streams=tuple(unique.values()),
            )
        )

    return tuple(events)


def load_recent_events(
    database: str | Path,
    *,
    days: int = 30,
    now: datetime | None = None,
) -> tuple[WatchalongEvent, ...]:
    if days < 1:
        raise ValueError("days must be >= 1")
    db = Path(database).expanduser().resolve()
    if not db.is_file():
        raise FileNotFoundError(db)
    current = now or datetime.now(TAIPEI)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    cutoff = current.astimezone(TAIPEI) - timedelta(days=days)

    events: list[WatchalongEvent] = []
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not {"web_articles", "web_article_bodies"} <= tables:
            raise ValueError("database is missing web article body tables")
        rows = connection.execute(
            """
            SELECT a.aid, a.title, a.source_url, b.body_text
            FROM web_articles a
            JOIN web_article_bodies b ON b.web_article_id = a.id
            ORDER BY a.id DESC
            """
        )
        for aid, title, source_url, body_text in rows:
            dt = article_datetime(str(source_url))
            if dt is None or dt < cutoff:
                continue
            events.extend(
                parse_watchalong_events(
                    aid=str(aid),
                    article_title=str(title),
                    source_url=str(source_url),
                    body_text=str(body_text),
                )
            )

    ordered = sorted(
        events,
        key=lambda event: (event.article_datetime, event.scheduled_time, event.aid),
        reverse=True,
    )
    # The same scheduled Watchalong can appear in consecutive daily threads.
    # Keep the newest article's representation while preserving provenance on
    # that retained event. Event identity is the exact set of master video IDs,
    # which avoids duplicate cards without collapsing distinct multi-host sets.
    deduped: list[WatchalongEvent] = []
    seen_stream_sets: set[tuple[str, ...]] = set()
    for event in ordered:
        signature = tuple(sorted(stream.video_id for stream in event.streams))
        if signature in seen_stream_sets:
            continue
        seen_stream_sets.add(signature)
        deduped.append(event)
    return tuple(deduped)


def _event_to_json(event: WatchalongEvent) -> dict[str, object]:
    return {
        "aid": event.aid,
        "article_title": event.article_title,
        "source_url": event.source_url,
        "article_datetime": event.article_datetime,
        "day": event.day,
        "scheduled_time": event.scheduled_time,
        "description": event.description,
        "member_only": event.member_only,
        "streams": [
            {"label": stream.label, "url": stream.url, "video_id": stream.video_id}
            for stream in event.streams
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Watchalong parser for stored PTT article bodies")
    parser.add_argument("--database", required=True)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    events = load_recent_events(args.database, days=args.days)
    if args.json:
        print(json.dumps([_event_to_json(event) for event in events], ensure_ascii=False, indent=2))
        return 0

    print(f"watchalong_events={len(events)}")
    print(f"stream_candidates={sum(len(event.streams) for event in events)}")
    for index, event in enumerate(events, 1):
        suffix = " [members-only]" if event.member_only else ""
        print()
        print(f"[{index}] {event.day} {event.scheduled_time} {event.description}{suffix}")
        print(f"  source={event.aid} {event.source_url}")
        for stream in event.streams:
            print(f"  - {stream.label}: {stream.video_id} {stream.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
