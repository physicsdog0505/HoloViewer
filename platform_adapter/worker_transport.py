"""Worker-style transport into the *original* accepted 4174 GET dispatcher.

No route dispatch, product rendering, or player behavior is copied here.
This is a local feasibility seam: actual Cloudflare Python Worker imports and
fetch/urllib interoperability must be established before production claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Callable


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


def dispatch_accepted_get(
    handler_cls: type,
    *,
    target: str,
    method: str = "GET",
) -> TransportResponse:
    """Drive the accepted BaseHTTPRequestHandler.do_GET without sockets/threads.

    The vendor's full route dispatcher runs unchanged. Only request transport,
    header buffering, and BytesIO response capture are adapted.
    """
    if method != "GET":
        return TransportResponse(
            405,
            (("Content-Type", "text/plain; charset=utf-8"), ("Allow", "GET")),
            b"Method Not Allowed",
        )
    if not isinstance(target, str) or not target.startswith("/") or target.startswith("//"):
        raise ValueError("request target must be an origin-form absolute path")
    if "\r" in target or "\n" in target or len(target) > 8192:
        raise ValueError("invalid request target")

    class WorkerTransportHandler(handler_cls):
        # The accepted do_GET/_html/_json methods remain the implementations.
        def log_request(self, code="-", size="-"):
            return None

        def log_message(self, format, *args):
            return None

    handler = WorkerTransportHandler.__new__(WorkerTransportHandler)
    handler.path = target
    handler.command = "GET"
    handler.request_version = "HTTP/1.1"
    handler.protocol_version = "HTTP/1.1"
    handler.wfile = BytesIO()
    handler._headers_buffer = []
    handler.close_connection = True
    handler.client_address = ("127.0.0.1", 0)
    handler.headers = {}
    handler.do_GET()

    raw = handler.wfile.getvalue()
    split = raw.find(b"\r\n\r\n")
    if split < 0:
        raise RuntimeError("accepted handler did not complete HTTP headers")
    header_blob, body = raw[:split], raw[split + 4 :]
    lines = header_blob.decode("iso-8859-1").split("\r\n")
    try:
        status = int(lines[0].split(" ", 2)[1])
    except (IndexError, ValueError) as exc:
        raise RuntimeError("invalid accepted HTTP status") from exc
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line:
            raise RuntimeError("invalid accepted HTTP header")
        name, value = line.split(":", 1)
        headers.append((name.strip(), value.strip()))
    return TransportResponse(status, tuple(headers), body)
