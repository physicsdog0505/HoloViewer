"""Disabled-by-default #48 PTT read seam for the accepted 4174 consumer.

This is NOT an API router or PTT UI renderer. The reviewed #48 shell owns
/v1/ptt/today and /v1/ptt/history. Until its mount is proven locally, all
reads fail closed without invoking network, D1, SQLite or product fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from platform_adapter.public_api import DEFAULT_API, PublicAPIUnavailable
from platform_adapter.ptt_consumer_contract import validate_ptt_consumer_envelope


@dataclass(frozen=True)
class PttPublicReader:
    """Read only public envelopes from the canonical reviewed router."""
    enabled: bool = False

    async def read_today(self, day: str, get_json):
        return await self._read("today", day, get_json)

    async def read_history(self, day: str, get_json, *, checkpoint=None, limit=200):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("History page limit out of #48 reviewed bounds")
        if checkpoint is not None and (not isinstance(checkpoint, str) or not checkpoint):
            raise ValueError("History continuation must be an opaque nonempty string")
        return await self._read(
            "history", day, get_json, checkpoint=checkpoint, limit=limit,
        )

    async def _read(self, kind, day, get_json, *, checkpoint=None, limit=None):
        if not self.enabled:
            raise PublicAPIUnavailable("PTT public route is not mounted/verified")
        if kind not in ("today", "history"):
            raise ValueError("Unknown reviewed PTT route")
        from datetime import date
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError("Noncanonical date")
        except (TypeError, ValueError) as exc:
            raise ValueError("PTT day must be YYYY-MM-DD") from exc
        params = {"day": day}
        if limit is not None:
            params["limit"] = str(limit)
        if checkpoint is not None:
            # #48 public History wire contract uses after=<opaque push_id>.
            # Preserve consumer-facing checkpoint without parsing or rewriting it.
            params["after"] = checkpoint
        # get_json is the owner's async router transport, never an owned
        # backend implementation. The URL remains on the canonical origin.
        url = DEFAULT_API + "/v1/ptt/" + kind + "?" + urlencode(params)
        data = await get_json(url)
        return validate_ptt_consumer_envelope(
            data, day=day, history=(kind == "history"),
        )
