"""Opt-in, failure-isolated runtime mirror for discovery evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from channel_push_discovery import ChannelPushEvent, ChannelPushRecord
    from discovery_evidence import DiscoveryEvidenceStore
    from youtube_metadata import YoutubeVideo


ENVIRONMENT_VARIABLE = "PTT_VIEWER_DISCOVERY_EVIDENCE_DB"
_UNDATED_OBSERVED_AT = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _diagnostic(event: str, **details: object) -> None:
    print(json.dumps({"component": "discovery_evidence_shadow", "event": event, **details}, sort_keys=True), flush=True)


def _event_time(event: object) -> datetime:
    for value in (getattr(event, "updated", None), getattr(event, "published", None)):
        if value:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc)
    return _UNDATED_OBSERVED_AT


class ShadowDiscoveryEvidenceCapture:
    """A non-authoritative evidence sink that disables itself after one failure."""

    def __init__(self, path: Path | None, store: Any | None = None) -> None:
        self.path = path
        self._store = store
        self._healthy = store is not None

    @property
    def enabled(self) -> bool:
        return self._healthy and self._store is not None

    @classmethod
    def disabled(cls) -> "ShadowDiscoveryEvidenceCapture":
        return cls(None)

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        forbidden_paths: Iterable[str | Path] = (),
    ) -> "ShadowDiscoveryEvidenceCapture":
        values = os.environ if environment is None else environment
        value = values.get(ENVIRONMENT_VARIABLE, "").strip()
        if not value:
            return cls.disabled()
        path = Path(value)
        if not path.is_absolute():
            _diagnostic("disabled", reason="evidence_path_must_be_absolute")
            return cls.disabled()
        resolved = path.resolve(strict=False)
        forbidden = {Path(item).resolve(strict=False) for item in forbidden_paths}
        aliases_forbidden = resolved in forbidden or (
            resolved.exists() and any(item.exists() and resolved.samefile(item) for item in forbidden)
        )
        if aliases_forbidden:
            _diagnostic("disabled", reason="evidence_path_aliases_runtime_source", path=str(resolved))
            return cls.disabled()
        try:
            from discovery_evidence import DiscoveryEvidenceStore

            store = DiscoveryEvidenceStore(resolved)
            store.initialize()
        except Exception as exc:
            _diagnostic("disabled", reason="initialization_failed", error=type(exc).__name__, path=str(resolved))
            return cls.disabled()
        _diagnostic("enabled", path=str(resolved))
        return cls(resolved, store)

    def _write(self, operation) -> None:
        if not self.enabled:
            return
        try:
            operation(self._store)
        except Exception as exc:
            self._healthy = False
            _diagnostic("write_disabled", error=type(exc).__name__, path=str(self.path))

    def websub_delivery(
        self,
        *,
        raw_payload: bytes,
        events: Iterable["ChannelPushEvent"],
        records: Iterable["ChannelPushRecord"],
        diagnostics: Iterable[Mapping[str, object]],
        allowed_channels: frozenset[str],
        received_at: datetime,
    ) -> None:
        event_list = tuple(events)
        accepted = {record.event.video_id: record.video for record in records}
        diagnostic_rows = tuple(diagnostics)
        missing = {str(row.get("message")) for row in diagnostic_rows if row.get("kind") == "missing_status"}
        verify_error = next((row for row in diagnostic_rows if row.get("kind") == "verify_error"), None)
        non_live = {str(row.get("message")) for row in diagnostic_rows if row.get("kind") == "non_live"}

        def write(store: "DiscoveryEvidenceStore") -> None:
            from discovery_evidence import record_websub_event

            for event in event_list:
                video = accepted.get(event.video_id)
                if video is not None:
                    kind, state, reason = "accepted_discovery", f"verified_{video.live_state}", None
                elif event.channel_id not in allowed_channels:
                    kind, state, reason = "rejected", "rejected_unconfigured_channel", "unconfigured channel"
                elif verify_error is not None:
                    kind, state, reason = "verification_failure", "verification_failed", str(verify_error.get("message") or "verification failed")
                elif event.video_id in missing:
                    kind, state, reason = "missing", "verified_missing", "provider status missing"
                elif event.video_id in non_live:
                    kind, state, reason = "rejected", "verified_non_livestream", "not livestream metadata"
                else:
                    kind, state, reason = "rejected", "not_accepted", "not accepted by primary discovery"
                topic = f"https://www.youtube.com/feeds/videos.xml?channel_id={event.channel_id}"
                record_websub_event(
                    store, event, raw_payload=raw_payload, topic=topic,
                    received_at=received_at, observed_at=_event_time(event),
                    event_kind=kind, verification_state=state, video=video, reason=reason,
                    delivery_identity=f"runtime-websub:{received_at.astimezone(timezone.utc).isoformat()}:{topic}",
                )

        self._write(write)

    def feed_poll(
        self,
        *,
        raw_payloads: Mapping[str, bytes],
        events: Iterable["ChannelPushEvent"],
        statuses: Mapping[str, "YoutubeVideo"],
        verification_error: str | None,
        received_at: datetime,
    ) -> None:
        event_list = tuple(events)

        def write(store: "DiscoveryEvidenceStore") -> None:
            from discovery_evidence import derive_feed_poll_id, feed_source_key, record_feed_event

            for channel_id, payload in sorted(raw_payloads.items()):
                digest = hashlib.sha256(payload).hexdigest()
                poll_id = derive_feed_poll_id(channel_id=channel_id, raw_feed_payload=payload)
                channel_events = [event for event in event_list if event.channel_id == channel_id]
                snapshot_observed_at = max((_event_time(event) for event in channel_events), default=_UNDATED_OBSERVED_AT)
                store.record_source_snapshot(
                    source_kind="channel_feed", source_key=feed_source_key(channel_id),
                    snapshot_id=poll_id, observed_at=snapshot_observed_at, payload_hash=digest,
                    metadata={"channel_id": channel_id, "parser": "youtube-channel-feed-v1"},
                )
            for event in event_list:
                payload = raw_payloads[event.channel_id]
                video = statuses.get(event.video_id)
                if verification_error:
                    kind, state, reason = "verification_failure", "verification_failed", verification_error
                elif video is None:
                    kind, state, reason = "missing", "verified_missing", "provider status missing"
                elif video.live_state in {"live", "upcoming"} or video.actual_start is not None:
                    kind, state, reason = "accepted_discovery", f"verified_{video.live_state}", None
                else:
                    kind, state, reason = "rejected", "verified_non_livestream", "not livestream metadata"
                record_feed_event(
                    store, event, raw_feed_payload=payload, received_at=received_at,
                    observed_at=_event_time(event), event_kind=kind, verification_state=state,
                    video=video, reason=reason,
                    delivery_identity=f"runtime-feed:{received_at.astimezone(timezone.utc).isoformat()}:{event.channel_id}",
                )

        self._write(write)

    def ptt_body(
        self, *, aid: str, source_provenance: str, body_text: str,
        extracted_at: str | datetime,
    ) -> None:
        def write(store: "DiscoveryEvidenceStore") -> None:
            from discovery_evidence import record_ptt_body
            from urllib.parse import urlparse

            parsed = urlparse(source_provenance)
            parts = parsed.path.split("/")
            board = parts[2] if len(parts) > 2 else ""
            timestamp = (
                extracted_at if isinstance(extracted_at, datetime)
                else datetime.fromisoformat(extracted_at)
            )

            record_ptt_body(
                store, board=board, aid=aid, source_provenance=source_provenance,
                body_text=body_text, extracted_at=timestamp,
            )

        self._write(write)


def evidence_status(path: str | Path) -> dict[str, object]:
    from discovery_evidence import SCHEMA_VERSION

    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError("evidence path must be absolute")
    resolved = candidate.resolve(strict=True)
    uri = f"file:{resolved.as_posix()}?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as conn:
        if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise ValueError("unsupported discovery evidence schema version")
        metadata_version = conn.execute(
            "SELECT value FROM evidence_metadata WHERE key='schema_version'"
        ).fetchone()
        if metadata_version is None or metadata_version[0] != str(SCHEMA_VERSION):
            raise ValueError("unsupported discovery evidence metadata version")
        counts = {
            "observations": conn.execute("SELECT COUNT(*) FROM discovery_observations").fetchone()[0],
            "receipts": conn.execute("SELECT COUNT(*) FROM observation_receipts").fetchone()[0],
            "ptt_evidence": conn.execute("SELECT COUNT(*) FROM ptt_stream_evidence").fetchone()[0],
            "source_snapshots": conn.execute("SELECT COUNT(*) FROM source_snapshots").fetchone()[0],
        }
    return {"enabled": True, "path": str(resolved), **counts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only shadow discovery evidence status")
    parser.add_argument("--status", required=True, metavar="ABSOLUTE_DB_PATH")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(evidence_status(args.status), sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"enabled": False, "error": type(exc).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
