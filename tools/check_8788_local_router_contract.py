#!/usr/bin/env python3
"""Consume the *owner-owned* local canonical API router, never implement one.

Read-only canary for the existing holoviewer-public-api shell when #47/#48
publish it. Only accepts loopback URLs; no production calls, writes or D1.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from platform_adapter.public_api import PublicAPI, PublicAPIUnavailable, preloaded_public_reads
from platform_adapter.product_bindings import bind_home_reader
from platform_adapter.ptt_consumer_contract import validate_ptt_consumer_envelope


def checked_local_origin(value: str) -> str:
    url = urlsplit(value)
    if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost"}
            or url.username or url.password or url.path not in ("", "/")
            or url.query or url.fragment or url.port is None):
        raise ValueError("Only explicit local disposable HTTP router origin permitted")
    return value.rstrip("/")


def read_json(base: str, path: str) -> tuple[int, dict]:
    req = Request(base + path, method="GET", headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=5) as response:
            status = response.status
            payload = response.read(512_001)
            content_type = response.headers.get_content_type()
    except HTTPError as exc:
        status = exc.code
        payload = exc.read(512_001)
        content_type = exc.headers.get_content_type()
    if len(payload) > 512_000 or content_type != "application/json":
        raise PublicAPIUnavailable("Local router returned oversized/non-JSON response")
    try:
        obj = json.loads(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise PublicAPIUnavailable("Local router invalid JSON") from exc
    if not isinstance(obj, dict):
        raise PublicAPIUnavailable("Expected local router JSON object")
    return status, obj


def consumer_receipt(origin: str, *, ptt_day: str | None = None) -> dict:
    base = checked_local_origin(origin)
    status, today = read_json(base, "/v1/catalog/today")
    if status != 200:
        raise PublicAPIUnavailable("Owner #47 canonical Today route not mounted")
    if today.get("schema_version") != "public-consumer-v1":
        raise PublicAPIUnavailable("Owner #47 Today schema absent")
    if not isinstance(today.get("freshness"), dict) or not isinstance(today.get("streams"), list):
        raise PublicAPIUnavailable("Owner #47 Today consumer envelope missing")
    # Use the *actual* #68 consumer type mapping, not a parallel parser.
    from dataclasses import dataclass
    @dataclass
    class Card:
        video_id: str
        title: str
        channel_title: str
        start_label: str
        state: str
        source_label: str = ""
        channel_id: str = ""
        avatar_url: str = ""
        group: str = "unknown"
        start_at: object = None

    with preloaded_public_reads({("/v1/catalog/today", ()): today}):
        groups = bind_home_reader(PublicAPI(), Card)()
    result = {
        "api_shell": "owner-supplied existing holoviewer-public-api",
        "origin_kind": "loopback-only",
        "canonical_today": {
            "status": status,
            "schema_version": today["schema_version"],
            "freshness": today["freshness"].get("status"),
            "stream_count": len(today["streams"]),
            "visible_groups": [len(group) for group in groups],
            "envelope_sha256": hashlib.sha256(
                json.dumps(today, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        },
        "ptt_mount_checked": ptt_day is not None,
        "production_deployment": False,
        "d1_write_count": 0,
    }
    if ptt_day is not None:
        if date.fromisoformat(ptt_day).isoformat() != ptt_day:
            raise ValueError("PTT day must be YYYY-MM-DD")
        route = "/v1/ptt/today?" + urlencode({"day": ptt_day})
        status, body = read_json(base, route)
        if status != 200:
            raise PublicAPIUnavailable("Owner #48 PTT route not mounted")
        validate_ptt_consumer_envelope(body, day=ptt_day)
        result["canonical_ptt"] = {
            "status": status,
            "schema_version": body["schema_version"],
            "day": body["day"],
            "push_count": len(body["pushes"]),
            "freshness": body["freshness"]["status"],
            "gap": body["completeness"]["gap"],
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", required=True, help="local #47/#48 owner router only")
    parser.add_argument("--ptt-day", help="opt-in only after reviewed #48 mount")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = consumer_receipt(args.api_base, ptt_day=args.ptt_day)
    text = json.dumps(receipt, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
