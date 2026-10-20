"""Minimal offline WSGI surface. GET refreshes only injected read-only readers."""
from __future__ import annotations

import json
from urllib.parse import parse_qs

from .render import render_dashboard


class DashboardApplication:
    def __init__(self, controller):
        self.controller = controller

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/")
        if method != "GET":
            return self._reply(start_response, "405 Method Not Allowed", {"error": "read-only endpoint"})
        if path == "/admin/status":
            section = parse_qs(environ.get("QUERY_STRING", "")).get("section", [None])[0]
            try:
                return self._reply(start_response, "200 OK", self.controller.refresh(section))
            except ValueError as exc:
                return self._reply(start_response, "400 Bad Request", {"error": str(exc)})
        if path in {"/", "/admin/"}:
            body = render_dashboard().encode("utf-8")
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"),
                                      ("Cache-Control", "no-store"),
                                      ("Content-Length", str(len(body)))])
            return [body]
        return self._reply(start_response, "404 Not Found", {"error": "not found"})

    @staticmethod
    def _reply(start_response, status, value):
        body = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        start_response(status, [("Content-Type", "application/json"),
                                ("Cache-Control", "no-store"),
                                ("Content-Length", str(len(body)))])
        return [body]
