"""Request-local live-rail HTML for Public Worker page rendering."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_CURRENT = ContextVar("holoviewer_live_rail_html", default=None)


def current_live_rail_html():
    return _CURRENT.get()


@contextmanager
def using_live_rail_html(html: str):
    token = _CURRENT.set(html)
    try:
        yield
    finally:
        _CURRENT.reset(token)
