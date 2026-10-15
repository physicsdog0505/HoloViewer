"""Event-driven YouTube channel discovery for surprise livestreams.

This module is intentionally independent from the PTT Collector. Incoming YouTube
PubSubHubbub/WebSub Atom notifications are parsed, verified with the existing
quota-efficient ``videos.list`` seam, and stored in a rebuildable JSON sidecar.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Callable, Iterable, Mapping
import xml.etree.ElementTree as ET

from frontend_stream_discovery import DiscoveryCard
from frontend_time import TAIPEI
from today_stream_status import has_livestream_metadata
from youtube_metadata import YoutubeVideo


ATOM_NS = "http://www.w3.org/2005/Atom"
YT_NS = "http://www.youtube.com/xml/schemas/2015"
STATE_VERSION = 1
MAX_DIAGNOSTICS = 200


@dataclass(frozen=True)
class ChannelPushEvent:
    video_id: str
    channel_id: str
    title: str
    published: str | None
    updated: str | None


@dataclass(frozen=True)
class ChannelPushRecord:
    event: ChannelPushEvent
    received_at: datetime
    video: YoutubeVideo


StatusVerifier = Callable[[Iterable[str]], Mapping[str, YoutubeVideo]]


def parse_atom_events(payload: bytes | str) -> tuple[ChannelPushEvent, ...]:
    """Parse YouTube's Atom push payload into deterministic video/channel events."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    root = ET.fromstring(payload)
    events: list[ChannelPushEvent] = []
    seen: set[tuple[str, str]] = set()
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        video_id = (entry.findtext(f"{{{YT_NS}}}videoId") or "").strip()
        channel_id = (entry.findtext(f"{{{YT_NS}}}channelId") or "").strip()
        if not video_id or not channel_id:
            continue
        key = (video_id, channel_id)
        if key in seen:
            continue
        seen.add(key)
        events.append(
            ChannelPushEvent(
                video_id=video_id,
                channel_id=channel_id,
                title=(entry.findtext(f"{{{ATOM_NS}}}title") or "").strip(),
                published=(entry.findtext(f"{{{ATOM_NS}}}published") or "").strip() or None,
                updated=(entry.findtext(f"{{{ATOM_NS}}}updated") or "").strip() or None,
            )
        )
    return tuple(events)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _video_payload(video: YoutubeVideo) -> dict:
    return {
        "video_id": video.video_id,
        "title": video.title,
        "channel_title": video.channel_title,
        "live_state": video.live_state,
        "scheduled_start": video.scheduled_start.isoformat() if video.scheduled_start else None,
        "actual_start": video.actual_start.isoformat() if video.actual_start else None,
        "actual_end": video.actual_end.isoformat() if video.actual_end else None,
        "checked_at": video.checked_at.isoformat() if video.checked_at else None,
    }


def _video_from_payload(payload: Mapping[str, object]) -> YoutubeVideo:
    return YoutubeVideo(
        video_id=str(payload.get("video_id") or ""),
        title=str(payload.get("title") or ""),
        channel_title=str(payload.get("channel_title") or ""),
        live_state=str(payload.get("live_state") or ""),
        scheduled_start=_dt(payload.get("scheduled_start") if isinstance(payload.get("scheduled_start"), str) else None),
        actual_start=_dt(payload.get("actual_start") if isinstance(payload.get("actual_start"), str) else None),
        actual_end=_dt(payload.get("actual_end") if isinstance(payload.get("actual_end"), str) else None),
        checked_at=_dt(payload.get("checked_at") if isinstance(payload.get("checked_at"), str) else None),
    )


class ChannelPushStore:
    """Small rebuildable sidecar containing verified channel-push livestreams."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": STATE_VERSION, "videos": {}, "diagnostics": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("version") != STATE_VERSION:
            raise ValueError("unsupported channel-push state version")
        if not isinstance(payload.get("videos"), dict):
            raise ValueError("invalid channel-push videos state")
        payload.setdefault("diagnostics", [])
        return payload

    def _save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def _diag(payload: dict, *, kind: str, message: str, at: datetime) -> None:
        diagnostics = list(payload.get("diagnostics") or [])
        diagnostics.append({"at": at.isoformat(), "kind": kind, "message": message})
        payload["diagnostics"] = diagnostics[-MAX_DIAGNOSTICS:]

    def record_diagnostic(
        self,
        *,
        kind: str,
        message: str,
        at: datetime | None = None,
    ) -> None:
        """Persist one bounded diagnostic without changing discovered video state."""
        now = at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        payload = self._load()
        self._diag(payload, kind=kind, message=message, at=now)
        self._save(payload)

    def ingest_events(
        self,
        events: Iterable[ChannelPushEvent],
        *,
        verify: StatusVerifier,
        allowed_channels: set[str] | frozenset[str] | None = None,
        received_at: datetime | None = None,
        summary_kind: str = "delivery",
    ) -> tuple[ChannelPushRecord, ...]:
        """Verify candidate events once and persist only livestream lifecycle items."""
        now = received_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        event_list = tuple(events)
        payload = self._load()
        accepted_events = [
            event for event in event_list
            if allowed_channels is None or event.channel_id in allowed_channels
        ]
        rejected = len(event_list) - len(accepted_events)
        if rejected:
            self._diag(payload, kind="channel_rejected", message=f"rejected {rejected} unconfigured event(s)", at=now)
        if not accepted_events:
            self._save(payload)
            return ()

        try:
            statuses = dict(verify(event.video_id for event in accepted_events))
        except Exception as exc:
            self._diag(payload, kind="verify_error", message=f"{type(exc).__name__}: {exc}", at=now)
            self._save(payload)
            return ()

        videos = payload["videos"]
        records: list[ChannelPushRecord] = []
        for event in accepted_events:
            video = statuses.get(event.video_id)
            if video is None:
                self._diag(payload, kind="missing_status", message=event.video_id, at=now)
                continue
            if not has_livestream_metadata(video):
                self._diag(payload, kind="non_live", message=event.video_id, at=now)
                videos.pop(event.video_id, None)
                continue
            videos[event.video_id] = {
                "event": asdict(event),
                "received_at": now.astimezone(timezone.utc).isoformat(),
                "video": _video_payload(video),
            }
            records.append(ChannelPushRecord(event=event, received_at=now, video=video))
        self._diag(
            payload,
            kind=summary_kind,
            message=f"events={len(event_list)} accepted={len(records)}",
            at=now,
        )
        self._save(payload)
        return tuple(records)

    def ingest_atom(
        self,
        atom_payload: bytes | str,
        *,
        verify: StatusVerifier,
        allowed_channels: set[str] | frozenset[str] | None = None,
        received_at: datetime | None = None,
    ) -> tuple[ChannelPushRecord, ...]:
        """Ingest one push delivery and persist only verified livestream lifecycle items.

        Verification happens because a YouTube channel feed also announces ordinary
        uploads. One event therefore causes at most one bounded ``videos.list`` batch,
        rather than starting a periodic channel scan.
        """
        return self.ingest_events(
            parse_atom_events(atom_payload),
            verify=verify,
            allowed_channels=allowed_channels,
            received_at=received_at,
            summary_kind="delivery",
        )

    def records(self) -> tuple[ChannelPushRecord, ...]:
        payload = self._load()
        records: list[ChannelPushRecord] = []
        for raw in payload["videos"].values():
            event_raw = raw.get("event") or {}
            event = ChannelPushEvent(
                video_id=str(event_raw.get("video_id") or ""),
                channel_id=str(event_raw.get("channel_id") or ""),
                title=str(event_raw.get("title") or ""),
                published=event_raw.get("published") or None,
                updated=event_raw.get("updated") or None,
            )
            received = _dt(str(raw.get("received_at") or ""))
            video = _video_from_payload(raw.get("video") or {})
            if event.video_id and received is not None and video.video_id:
                records.append(ChannelPushRecord(event=event, received_at=received, video=video))
        return tuple(records)

    def diagnostics(self) -> tuple[dict, ...]:
        return tuple(self._load().get("diagnostics") or ())


def records_for_day(store: ChannelPushStore, selected_day: date) -> tuple[ChannelPushRecord, ...]:
    """Return verified channel events belonging to a Taipei calendar day."""
    result = []
    for record in store.records():
        anchor = record.video.preferred_start or record.received_at
        if anchor.astimezone(TAIPEI).date() == selected_day:
            result.append(record)
    result.sort(key=lambda record: (record.video.preferred_start or record.received_at, record.event.video_id))
    return tuple(result)


def cards_for_day(store: ChannelPushStore, selected_day: date) -> tuple[DiscoveryCard, ...]:
    cards = []
    for record in records_for_day(store, selected_day):
        start = record.video.preferred_start.astimezone(TAIPEI) if record.video.preferred_start else None
        cards.append(
            DiscoveryCard(
                video_id=record.event.video_id,
                url=f"https://www.youtube.com/watch?v={record.event.video_id}",
                label=record.video.title or record.event.title or "頻道即時直播",
                period="頻道即時",
                source_aids=(),
                ptt_start_minutes=(start.hour * 60 + start.minute) if start else None,
                ptt_start_label=start.strftime("%H:%M") if start else None,
            )
        )
    return tuple(cards)


def statuses_for_day(store: ChannelPushStore, selected_day: date) -> dict[str, YoutubeVideo]:
    return {record.event.video_id: record.video for record in records_for_day(store, selected_day)}


def merge_cards(
    ptt_cards: Iterable[DiscoveryCard],
    channel_cards: Iterable[DiscoveryCard],
) -> tuple[DiscoveryCard, ...]:
    """Merge by normalized video ID while preserving PTT provenance when present."""
    merged: dict[str, DiscoveryCard] = {card.video_id: card for card in ptt_cards}
    order = [card.video_id for card in ptt_cards]
    for incoming in channel_cards:
        current = merged.get(incoming.video_id)
        if current is None:
            merged[incoming.video_id] = incoming
            order.append(incoming.video_id)
            continue
        periods = [part.strip() for part in current.period.split("/") if part.strip()]
        if "頻道即時" not in periods:
            periods.append("頻道即時")
        merged[incoming.video_id] = DiscoveryCard(
            video_id=current.video_id,
            url=current.url,
            label=current.label or incoming.label,
            period=" / ".join(periods),
            source_aids=current.source_aids,
            ptt_start_minutes=current.ptt_start_minutes if current.ptt_start_minutes is not None else incoming.ptt_start_minutes,
            ptt_start_label=current.ptt_start_label or incoming.ptt_start_label,
        )
    return tuple(merged[video_id] for video_id in order)
