"""Offline 8501 pilot preparation: fail-closed auth boundary and shared fixture cache.

No production client, network access, secrets, filesystem path from request, or writer.
The host MUST supply a reviewed authenticator before mounting this application.
"""
from __future__ import annotations

from copy import deepcopy
from threading import Condition, Lock
from time import monotonic


class AuthenticatedDashboard:
    """Require an injected trusted server-side authentication decision first."""

    def __init__(self, app, authenticate):
        if not callable(authenticate):
            raise ValueError("server-side authenticator required")
        self._app = app
        self._authenticate = authenticate

    def __call__(self, environ, start_response):
        try:
            allowed = self._authenticate(environ) is True
        except Exception:
            allowed = False
        if not allowed:
            body = b'{"error":"unauthorized"}'
            start_response("401 Unauthorized", [
                ("Content-Type", "application/json"),
                ("Cache-Control", "no-store"),
                ("Content-Length", str(len(body))),
            ])
            return [body]
        return self._app(environ, start_response)


class SharedFixtureCache:
    """Single-process, per-key TTL and in-flight coalescing; no production query."""

    def __init__(self, *, ttl_seconds=60, clock=monotonic):
        if ttl_seconds < 60:
            raise ValueError("shared cache TTL must be >=60 seconds")
        self._ttl = ttl_seconds
        self._clock = clock
        self._condition = Condition(Lock())
        self._entries = {}
        self._inflight = set()

    def read(self, key, producer):
        if not isinstance(key, tuple) or len(key) != 5 or any(not isinstance(v, str) for v in key):
            raise ValueError("cache key must be (schema_version,target,scope,manifest_digest,verification_mode)")
        if not callable(producer):
            raise ValueError("reader required")
        with self._condition:
            while True:
                entry = self._entries.get(key)
                if entry and self._clock() - entry[0] < self._ttl:
                    return deepcopy(entry[1]), True
                if key not in self._inflight:
                    self._inflight.add(key)
                    break
                self._condition.wait()
        try:
            result = producer()
            with self._condition:
                self._entries[key] = (self._clock(), deepcopy(result))
            return deepcopy(result), False
        finally:
            with self._condition:
                self._inflight.discard(key)
                self._condition.notify_all()
