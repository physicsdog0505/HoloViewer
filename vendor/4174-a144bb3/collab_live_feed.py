"""Read-only localhost JSON feed for live multi-stream PTT updates.

The feed exists only inside the local Streamlit process, binds to 127.0.0.1,
and reads the existing SQLite databases without mutating them. It lets the
browser-side multi-stream component refresh chat without rebuilding YouTube
iframes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

from frontend_multistream_sync import _timeline_messages
from frontend_sync_query import load_sync_window


class _LoopbackThreadingHTTPServer(ThreadingHTTPServer):
    """Loopback feed server whose request threads never block interpreter shutdown."""

    daemon_threads = True
    block_on_close = False


@dataclass
class LiveFeedServer:
    server: ThreadingHTTPServer
    thread: Thread

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _bounded_loader(
    collector_path: str | Path,
    web_path: str | Path,
    start: datetime,
    end: datetime,
):
    """Use the same bounded DB path as the standalone sync page.

    Browser polling runs every few seconds, so it must not materialize unrelated
    history on every request.  Keep the feed payload contract unchanged and only
    swap the read implementation.
    """
    pushes, _timing = load_sync_window(collector_path, web_path, start, end)
    return pushes


def start_live_feed_server(
    collector_path: str | Path,
    web_path: str | Path,
    *,
    loader=None,
) -> LiveFeedServer:
    """Start one loopback-only server returning current PTT timeline messages."""

    collector = Path(collector_path)
    web = Path(web_path)
    read_pushes = loader or _bounded_loader

    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # The browser may cancel an in-flight polling request while Streamlit
                # is shutting down or navigating away. That is expected and must not
                # keep the process alive or spam a traceback.
                return

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urlparse(self.path)
            if parsed.path != "/pushes":
                self._json(404, {"error": "not found"})
                return

            raw_start = (parse_qs(parsed.query).get("start") or [""])[0]
            # application/x-www-form-urlencoded parsing treats '+' as a space.
            # ISO-8601 timezone offsets contain '+', so normalize that common form
            # before handing the value to datetime.fromisoformat().
            raw_start = raw_start.replace(" ", "+")
            try:
                session_start = datetime.fromisoformat(raw_start)
                if session_start.tzinfo is None:
                    raise ValueError("start must include timezone")
            except ValueError:
                self._json(400, {"error": "invalid start timestamp"})
                return

            now = datetime.now(session_start.tzinfo)
            end = max(now + timedelta(minutes=1), session_start + timedelta(minutes=1))
            # Clamp only the database read window. Message offsets must stay relative
            # to the original collab session start or the browser timeline will drift.
            query_start = max(session_start, end - timedelta(hours=24))

            try:
                pushes = read_pushes(collector, web, query_start, end)
                messages = _timeline_messages(pushes, session_start)
            except Exception as exc:  # keep browser polling resilient
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
                return

            self._json(
                200,
                {
                    "messages": messages,
                    "checked_at": datetime.now(session_start.tzinfo).isoformat(),
                },
            )

        def log_message(self, _format: str, *_args) -> None:
            return

    server = _LoopbackThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, name="collab-live-feed", daemon=True)
    thread.start()
    return LiveFeedServer(server=server, thread=thread)
