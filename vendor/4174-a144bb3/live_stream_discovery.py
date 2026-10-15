"""Current-thread PTT stream discovery with a rebuildable local sidecar cache.

This module is deliberately isolated from the Collector database. It converts
an existing ``thread_discovery.ArticleTarget`` into the corresponding pttweb.cc
article URL, fetches only the article body through an injected fetcher, parses
YouTube links with ``ptt_stream_discovery``, and stores a small rebuildable JSON
sidecar. Network failures never mutate Collector state and may fall back to a
clearly marked stale cached snapshot.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse, urlunparse

from frontend_time import thread_date
from ptt_stream_discovery import DiscoveredStream, discover_streams
from discovery_evidence_runtime import ShadowDiscoveryEvidenceCapture
from thread_discovery import ArticleTarget


CACHE_VERSION = 1
DEFAULT_CACHE_PATH = Path(__file__).resolve().parent / ".ptt_stream_discovery_cache.json"
BodyFetcher = Callable[[str], str]


@dataclass(frozen=True)
class LiveThreadSnapshot:
    aid: str
    title: str
    period: str
    calendar_day: str
    source_url: str
    body_url: str
    article_timestamp: int
    fetched_at: str
    body_text: str
    streams: tuple[DiscoveredStream, ...]


@dataclass(frozen=True)
class LiveDiscoveryResult:
    snapshot: LiveThreadSnapshot | None
    fresh: bool
    stale: bool
    error: str | None

    @property
    def available(self) -> bool:
        return self.snapshot is not None


def pttweb_url_for_target(target: ArticleTarget) -> str:
    """Map a canonical www.ptt.cc article URL to the same pttweb.cc article."""
    parsed = urlparse(target.url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in {
        "ptt.cc",
        "www.ptt.cc",
    }:
        raise ValueError("ArticleTarget URL is not a supported https://www.ptt.cc article")
    if not parsed.path.startswith("/bbs/") or "/M." not in parsed.path:
        raise ValueError("ArticleTarget URL is not a recognizable PTT article path")
    return urlunparse(("https", "www.pttweb.cc", parsed.path, "", "", ""))


def build_snapshot(
    target: ArticleTarget,
    body_text: str,
    *,
    fetched_at: datetime | None = None,
) -> LiveThreadSnapshot:
    """Build one immutable discovery snapshot from already-fetched body text."""
    if not body_text.strip():
        raise ValueError("article body is empty")
    timestamp = fetched_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    return LiveThreadSnapshot(
        aid=target.aid,
        title=target.title,
        period=target.period,
        calendar_day=thread_date(target.title, target.url).isoformat(),
        source_url=target.url,
        body_url=pttweb_url_for_target(target),
        article_timestamp=target.timestamp,
        fetched_at=timestamp.astimezone(timezone.utc).isoformat(timespec="seconds"),
        body_text=body_text,
        streams=discover_streams(body_text),
    )


def _snapshot_to_json(snapshot: LiveThreadSnapshot) -> dict[str, object]:
    return {
        "aid": snapshot.aid,
        "title": snapshot.title,
        "period": snapshot.period,
        "calendar_day": snapshot.calendar_day,
        "source_url": snapshot.source_url,
        "body_url": snapshot.body_url,
        "article_timestamp": snapshot.article_timestamp,
        "fetched_at": snapshot.fetched_at,
        "body_text": snapshot.body_text,
        "streams": [asdict(stream) for stream in snapshot.streams],
    }


def _snapshot_from_json(value: dict[str, object]) -> LiveThreadSnapshot:
    raw_streams = value.get("streams")
    if not isinstance(raw_streams, list):
        raise ValueError("cached snapshot streams must be a list")
    streams: list[DiscoveredStream] = []
    for item in raw_streams:
        if not isinstance(item, dict):
            raise ValueError("cached stream entry must be an object")
        streams.append(
            DiscoveredStream(
                video_id=str(item["video_id"]),
                url=str(item["url"]),
                first_line=int(item["first_line"]),
                occurrence_count=int(item["occurrence_count"]),
            )
        )
    return LiveThreadSnapshot(
        aid=str(value["aid"]),
        title=str(value["title"]),
        period=str(value["period"]),
        calendar_day=str(value["calendar_day"]),
        source_url=str(value["source_url"]),
        body_url=str(value["body_url"]),
        article_timestamp=int(value["article_timestamp"]),
        fetched_at=str(value["fetched_at"]),
        body_text=str(value["body_text"]),
        streams=tuple(streams),
    )


class LiveDiscoveryCache:
    """Small rebuildable JSON cache keyed by PTT AID."""

    def __init__(self, path: str | Path = DEFAULT_CACHE_PATH) -> None:
        self.path = Path(path)

    @staticmethod
    def _empty_payload() -> dict[str, object]:
        return {"version": CACHE_VERSION, "articles": {}}

    def _read_payload(self) -> dict[str, object]:
        if not self.path.exists():
            return self._empty_payload()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid live discovery cache: {self.path}") from exc
        if not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION:
            raise ValueError("unsupported live discovery cache version")
        articles = payload.get("articles")
        if not isinstance(articles, dict):
            raise ValueError("live discovery cache articles must be an object")
        return payload

    def get(self, aid: str) -> LiveThreadSnapshot | None:
        articles = self._read_payload()["articles"]
        raw = articles.get(aid)
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValueError("cached article snapshot must be an object")
        return _snapshot_from_json(raw)

    def for_day(self, calendar_day: str) -> tuple[LiveThreadSnapshot, ...]:
        articles = self._read_payload()["articles"]
        snapshots = [
            _snapshot_from_json(raw)
            for raw in articles.values()
            if isinstance(raw, dict) and str(raw.get("calendar_day")) == calendar_day
        ]
        return tuple(sorted(snapshots, key=lambda item: item.article_timestamp))

    def put(self, snapshot: LiveThreadSnapshot) -> None:
        try:
            payload = self._read_payload()
        except ValueError:
            # This cache is explicitly derived/rebuildable. A successful body
            # refresh is authoritative for the entry being written, so a corrupt
            # or old-version sidecar must not block recovery.
            payload = self._empty_payload()
        articles = dict(payload["articles"])
        articles[snapshot.aid] = _snapshot_to_json(snapshot)
        payload = {"version": CACHE_VERSION, "articles": articles}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def refresh_target(
    target: ArticleTarget,
    *,
    fetch_body: BodyFetcher,
    cache: LiveDiscoveryCache,
    evidence_capture: ShadowDiscoveryEvidenceCapture | None = None,
) -> LiveDiscoveryResult:
    """Refresh one target without allowing fetch failures to escape into Collector flow."""
    body_url = pttweb_url_for_target(target)
    try:
        body_text = fetch_body(body_url)
        snapshot = build_snapshot(target, body_text)
        cache.put(snapshot)
        if evidence_capture is not None:
            evidence_capture.ptt_body(
                aid=target.aid, source_provenance=target.url,
                body_text=body_text, extracted_at=snapshot.fetched_at,
            )
        return LiveDiscoveryResult(snapshot=snapshot, fresh=True, stale=False, error=None)
    except Exception as exc:  # network/browser/parser boundary; caller gets explicit state
        try:
            cached = cache.get(target.aid)
        except ValueError:
            cached = None
        return LiveDiscoveryResult(
            snapshot=cached,
            fresh=False,
            stale=cached is not None,
            error=str(exc),
        )


def cached_day_streams(
    cache: LiveDiscoveryCache,
    calendar_day: str,
) -> tuple[tuple[DiscoveredStream, tuple[str, ...]], ...]:
    """Deduplicate one day's cached streams while preserving source AID provenance."""
    grouped: dict[str, tuple[DiscoveredStream, list[str]]] = {}
    order: list[str] = []
    for snapshot in cache.for_day(calendar_day):
        for stream in snapshot.streams:
            if stream.video_id not in grouped:
                grouped[stream.video_id] = (stream, [])
                order.append(stream.video_id)
            grouped[stream.video_id][1].append(snapshot.aid)
    return tuple(
        (grouped[video_id][0], tuple(grouped[video_id][1])) for video_id in order
    )


def fetch_body_via_pttweb(body_url: str) -> str:
    """Production adapter that reuses the existing body-only pttweb fetcher.

    Import is intentionally lazy so normal Viewer/Collector startup does not require
    Playwright unless live discovery is explicitly refreshed.
    """
    from web_backfill import PttWebClient

    with PttWebClient() as client:
        return client.fetch_body(body_url)
