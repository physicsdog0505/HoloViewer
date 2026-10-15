"""Failure-isolated runtime writer for the durable Stream Catalog.

Raw discovery evidence remains owned by DiscoveryEvidenceStore. This module writes
only selected/verified channel + stream registry projections and source presence.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Callable, Iterable, Mapping, TYPE_CHECKING

from stream_catalog import StreamCatalog
from today_stream_status import stream_state

if TYPE_CHECKING:
    from channel_push_discovery import ChannelPushRecord


ENVIRONMENT_VARIABLE = "PTT_VIEWER_STREAM_CATALOG_DB"


def _diagnostic(event: str, **details: object) -> None:
    print(
        json.dumps(
            {"component": "stream_catalog_runtime", "event": event, **details},
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _lifecycle(record: "ChannelPushRecord", *, now: datetime) -> str:
    video = record.video
    if video.actual_end is not None:
        return "ended"
    state = stream_state(video, now=now)
    if state == "live":
        return "live"
    if state in {"waiting", "upcoming"}:
        return "upcoming"
    return "unknown"


class StreamCatalogRuntimeWriter:
    """Opt-in, failure-isolated Stream Catalog sink safe for threaded callers.

    No SQLite connection is shared across threads. Configuration is validated once,
    then each write opens its own short-lived StreamCatalog connection.
    """

    def __init__(
        self,
        path: Path | None,
        *,
        opener: Callable[[Path], StreamCatalog] = StreamCatalog,
        healthy: bool | None = None,
    ) -> None:
        self.path = path
        self._opener = opener
        self._healthy = bool(path) if healthy is None else bool(healthy)

    @property
    def enabled(self) -> bool:
        return self._healthy and self.path is not None

    @classmethod
    def disabled(cls) -> "StreamCatalogRuntimeWriter":
        return cls(None, healthy=False)

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        forbidden_paths: Iterable[str | Path] = (),
    ) -> "StreamCatalogRuntimeWriter":
        values = os.environ if environment is None else environment
        raw = values.get(ENVIRONMENT_VARIABLE, "").strip()
        if not raw:
            return cls.disabled()

        path = Path(raw)
        if not path.is_absolute():
            _diagnostic("disabled", reason="catalog_path_must_be_absolute")
            return cls.disabled()

        resolved = path.resolve(strict=False)
        forbidden = {Path(item).resolve(strict=False) for item in forbidden_paths}
        aliases_forbidden = resolved in forbidden or (
            resolved.exists()
            and any(
                item.exists() and resolved.samefile(item)
                for item in forbidden
            )
        )
        if aliases_forbidden:
            _diagnostic(
                "disabled",
                reason="catalog_path_aliases_runtime_source",
                path=str(resolved),
            )
            return cls.disabled()

        try:
            catalog = StreamCatalog(resolved)
            catalog.close()
        except Exception as exc:
            _diagnostic(
                "disabled",
                reason="initialization_failed",
                error=type(exc).__name__,
                path=str(resolved),
            )
            return cls.disabled()

        _diagnostic("enabled", path=str(resolved))
        return cls(resolved)

    def close(self) -> None:
        """Compatibility hook; writes use short-lived connections."""
        self._healthy = False

    def _write(self, operation) -> None:
        if not self.enabled or self.path is None:
            return
        catalog: StreamCatalog | None = None
        try:
            catalog = self._opener(self.path)
            operation(catalog)
        except Exception as exc:
            self._healthy = False
            _diagnostic(
                "write_disabled",
                error=type(exc).__name__,
                path=str(self.path),
            )
        finally:
            if catalog is not None:
                try:
                    catalog.close()
                except Exception:
                    pass

    def verified_channel_profiles(
        self,
        profiles: Mapping[str, object],
        *,
        received_at: datetime | None = None,
    ) -> None:
        """Persist verified channel title/avatar metadata without inventing stream evidence."""

        if not profiles:
            return
        received = _utc(received_at)

        def write(catalog: StreamCatalog) -> None:
            for channel_id, profile in profiles.items():
                if not channel_id or getattr(profile, "channel_id", "") != channel_id:
                    continue
                checked_at = _utc(getattr(profile, "checked_at", None) or received)
                catalog.upsert_channel(
                    channel_id,
                    channel_name=getattr(profile, "channel_name", "") or "",
                    avatar_url=getattr(profile, "avatar_url", "") or "",
                    seen_at=received,
                    profile_checked_at=checked_at,
                )

        self._write(write)

    def verified_statuses(
        self,
        statuses: Mapping[str, object],
        *,
        received_at: datetime | None = None,
    ) -> None:
        """Persist verified lifecycle refreshes without inventing channel/source evidence."""

        if not statuses:
            return
        received = _utc(received_at)

        def write(catalog: StreamCatalog) -> None:
            for video_id, video in statuses.items():
                if not video_id or getattr(video, "video_id", "") != video_id:
                    continue
                projection_at = _utc(getattr(video, "checked_at", None) or received)
                actual_end = getattr(video, "actual_end", None)
                if actual_end is not None:
                    lifecycle = "ended"
                else:
                    state = stream_state(video, now=projection_at)
                    if state == "live":
                        lifecycle = "live"
                    elif state in {"waiting", "upcoming"}:
                        lifecycle = "upcoming"
                    else:
                        lifecycle = "unknown"
                catalog.upsert_stream(
                    video_id,
                    title=getattr(video, "title", "") or "",
                    scheduled_start=getattr(video, "scheduled_start", None),
                    actual_start=getattr(video, "actual_start", None),
                    actual_end=actual_end,
                    lifecycle_state=lifecycle,
                    seen_at=received,
                    projection_observed_at=projection_at,
                    last_checked_at=getattr(video, "checked_at", None),
                    is_livestream=True,
                )

        self._write(write)

    def verified_records(
        self,
        records: Iterable["ChannelPushRecord"],
        *,
        source_type: str,
        received_at: datetime | None = None,
    ) -> None:
        """Persist already-verified livestream records without owning raw evidence."""

        if source_type not in {"websub", "channel_feed"}:
            raise ValueError("unsupported stream catalog runtime source")
        record_list = tuple(records)
        if not record_list:
            return
        received = _utc(received_at)

        def write(catalog: StreamCatalog) -> None:
            for record in record_list:
                video = record.video
                projection_at = _utc(video.checked_at or received)
                event_received = _utc(record.received_at or received)
                catalog.upsert_channel(
                    record.event.channel_id,
                    channel_name=video.channel_title,
                    seen_at=event_received,
                    profile_checked_at=projection_at,
                )
                catalog.upsert_stream(
                    record.event.video_id,
                    channel_id=record.event.channel_id,
                    title=video.title or record.event.title,
                    scheduled_start=video.scheduled_start,
                    actual_start=video.actual_start,
                    actual_end=video.actual_end,
                    lifecycle_state=_lifecycle(record, now=projection_at),
                    seen_at=event_received,
                    projection_observed_at=projection_at,
                    last_checked_at=video.checked_at,
                    is_livestream=True,
                )
                catalog.record_source(
                    record.event.video_id,
                    source_type,
                    source_ref=record.event.channel_id,
                    seen_at=event_received,
                )

        self._write(write)
