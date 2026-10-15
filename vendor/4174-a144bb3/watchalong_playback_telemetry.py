"""Local-only browser <-> Streamlit runtime bridge for Watchalong.

The embedded YouTube player cannot return a normal Python value through components.html.
This loopback-only bridge carries the master playhead into Python and lets Python expose
fresh subtitle payloads back to the already-mounted iframe without rebuilding players.

It binds only to 127.0.0.1, stores only in-memory state, and requires a random
process-local token on every request.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from typing import Callable, Mapping, Sequence
from urllib.parse import parse_qs, urlsplit


_PLAYBACK_PATH = "/watchalong/playback"
_SUBTITLE_PATH = "/watchalong/subtitles"
_MAX_BODY_BYTES = 4096
_MAX_SUBTITLE_ITEMS = 10000
_ALLOWED_PLAYER_STATES = {-1, 0, 1, 2, 3, 5}


@dataclass(frozen=True, slots=True)
class PlaybackTelemetrySnapshot:
    session_id: str
    master_seconds: float
    player_state: int
    received_monotonic: float


@dataclass(frozen=True, slots=True)
class SubtitleFeedSnapshot:
    session_id: str
    version: int
    subtitles: tuple[dict[str, object], ...]
    updated_monotonic: float


def _validate_session_id(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError("invalid session_id")
    return value


def _validated_snapshot(
    payload: Mapping[str, object],
    *,
    received_monotonic: float,
) -> PlaybackTelemetrySnapshot:
    session_id = _validate_session_id(payload.get("session_id"))
    raw_seconds = payload.get("master_seconds")
    if isinstance(raw_seconds, bool) or not isinstance(raw_seconds, (int, float)):
        raise ValueError("invalid master_seconds")
    master_seconds = float(raw_seconds)
    if not math.isfinite(master_seconds) or master_seconds < 0:
        raise ValueError("invalid master_seconds")

    raw_state = payload.get("player_state", -1)
    if isinstance(raw_state, bool) or not isinstance(raw_state, int):
        raise ValueError("invalid player_state")
    if raw_state not in _ALLOWED_PLAYER_STATES:
        raise ValueError("invalid player_state")

    return PlaybackTelemetrySnapshot(
        session_id=session_id,
        master_seconds=master_seconds,
        player_state=raw_state,
        received_monotonic=received_monotonic,
    )


def _validated_subtitles(
    subtitles: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    if len(subtitles) > _MAX_SUBTITLE_ITEMS:
        raise ValueError("too many subtitles")
    result: list[dict[str, object]] = []
    for item in subtitles:
        if not isinstance(item, Mapping):
            raise ValueError("subtitle must be an object")
        start = item.get("start")
        end = item.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
        ):
            raise ValueError("subtitle timestamps must be numeric")
        start_value = float(start)
        end_value = float(end)
        if (
            not math.isfinite(start_value)
            or not math.isfinite(end_value)
            or start_value < 0
            or end_value < start_value
        ):
            raise ValueError("invalid subtitle timestamps")
        text = item.get("text", "")
        translated = item.get("translated", "")
        if not isinstance(text, str) or not isinstance(translated, str):
            raise ValueError("subtitle text must be strings")
        result.append(
            {
                "start": start_value,
                "end": end_value,
                "text": text,
                "translated": translated,
            }
        )
    return tuple(result)


class PlaybackTelemetryReceiver:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        token: str | None = None,
    ) -> None:
        self._clock = clock
        self._token = token or secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self._snapshots: dict[str, PlaybackTelemetrySnapshot] = {}
        self._subtitle_feeds: dict[str, SubtitleFeedSnapshot] = {}
        self._server = self._make_server()
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="watchalong-playback-telemetry",
            daemon=True,
        )
        self._thread.start()

    @property
    def token(self) -> str:
        return self._token

    @property
    def endpoint(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}{_PLAYBACK_PATH}"

    @property
    def subtitle_endpoint(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}{_SUBTITLE_PATH}"

    def record(self, payload: Mapping[str, object]) -> PlaybackTelemetrySnapshot:
        snapshot = _validated_snapshot(
            payload,
            received_monotonic=self._clock(),
        )
        with self._lock:
            self._snapshots[snapshot.session_id] = snapshot
        return snapshot

    def snapshot(
        self,
        session_id: str,
        *,
        max_age_seconds: float = 5.0,
    ) -> PlaybackTelemetrySnapshot | None:
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must be >= 0")
        with self._lock:
            snapshot = self._snapshots.get(session_id)
        if snapshot is None:
            return None
        if self._clock() - snapshot.received_monotonic > max_age_seconds:
            return None
        return snapshot

    def set_subtitles(
        self,
        session_id: str,
        subtitles: Sequence[Mapping[str, object]],
    ) -> SubtitleFeedSnapshot:
        session = _validate_session_id(session_id)
        values = _validated_subtitles(subtitles)
        with self._lock:
            previous = self._subtitle_feeds.get(session)
            if previous is not None and previous.subtitles == values:
                return previous
            version = 1 if previous is None else previous.version + 1
            snapshot = SubtitleFeedSnapshot(
                session_id=session,
                version=version,
                subtitles=values,
                updated_monotonic=self._clock(),
            )
            self._subtitle_feeds[session] = snapshot
        return snapshot

    def subtitle_feed(self, session_id: str) -> SubtitleFeedSnapshot | None:
        session = _validate_session_id(session_id)
        with self._lock:
            return self._subtitle_feeds.get(session)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _make_server(self) -> ThreadingHTTPServer:
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def _cors(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Content-Type, X-Watchalong-Telemetry-Token",
                )
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Cache-Control", "no-store")

            def _authorized(self) -> bool:
                return (
                    self.headers.get("X-Watchalong-Telemetry-Token")
                    == receiver.token
                )

            def do_OPTIONS(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                if path not in {_PLAYBACK_PATH, _SUBTITLE_PATH}:
                    self.send_error(404)
                    return
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlsplit(self.path)
                if parsed.path != _SUBTITLE_PATH:
                    self.send_error(404)
                    return
                if not self._authorized():
                    self.send_response(403)
                    self._cors()
                    self.end_headers()
                    return
                session_values = parse_qs(parsed.query).get("session_id", [])
                try:
                    session_id = _validate_session_id(
                        session_values[0] if session_values else None
                    )
                except ValueError:
                    self.send_response(400)
                    self._cors()
                    self.end_headers()
                    return
                snapshot = receiver.subtitle_feed(session_id)
                if snapshot is None:
                    self.send_response(204)
                    self._cors()
                    self.end_headers()
                    return
                body = json.dumps(
                    {
                        "version": snapshot.version,
                        "subtitles": list(snapshot.subtitles),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlsplit(self.path)
                if parsed.path != _PLAYBACK_PATH:
                    self.send_error(404)
                    return
                if not self._authorized():
                    self.send_response(403)
                    self._cors()
                    self.end_headers()
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length <= 0 or length > _MAX_BODY_BYTES:
                    self.send_response(400)
                    self._cors()
                    self.end_headers()
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("payload must be an object")
                    receiver.record(payload)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
                    self.send_response(400)
                    self._cors()
                    self.end_headers()
                    return
                self.send_response(204)
                self._cors()
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def start_playback_telemetry_receiver() -> PlaybackTelemetryReceiver:
    return PlaybackTelemetryReceiver()
