#!/usr/bin/env python3
"""Validate roster IDs and optionally resolve accessibility via official YouTube channels.list.

Reads JSON {channels:[{channel_id,...}]}; never changes roster, secrets or cloud state.
YOUTUBE_API_KEY is read from env and never printed.
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")

def validate(data):
    entries = data["channels"]
    ids = [row["channel_id"] for row in entries]
    if not all(isinstance(cid, str) and CHANNEL_ID.fullmatch(cid) for cid in ids):
        raise ValueError("invalid channel ID format")
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate channel ID")
    return ids

def check_api(ids, key):
    found = {}
    for offset in range(0, len(ids), 50):
        subset = ids[offset:offset + 50]
        params = urllib.parse.urlencode({"part": "snippet,status", "id": ",".join(subset), "maxResults": 50})
        req = urllib.request.Request(
            "https://www.googleapis.com/youtube/v3/channels?" + params,
            headers={"X-goog-api-key": key, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            result = json.load(response)
        for item in result.get("items", []):
            if item.get("id") in subset:
                found[item["id"]] = {
                    "title": item.get("snippet", {}).get("title"),
                    "custom_url": item.get("snippet", {}).get("customUrl"),
                }
    return found

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roster", type=Path)
    ap.add_argument("--live", action="store_true", help="Make bounded YouTube channels.list reads; uses YOUTUBE_API_KEY")
    ap.add_argument("--output", type=Path, help="Optional JSON receipt, with no secret")
    args = ap.parse_args()
    data = json.loads(args.roster.read_text(encoding="utf-8"))
    ids = validate(data)
    receipt = {"valid_format": True, "unique_count": len(ids), "live_checked": False}
    if args.live:
        key = os.environ.get("YOUTUBE_API_KEY")
        if not key:
            ap.error("YOUTUBE_API_KEY is required for --live")
        found = check_api(ids, key)
        receipt.update({
            "live_checked": True,
            "returned_count": len(found),
            "not_returned_ids": [cid for cid in ids if cid not in found],
            "channels": [{"channel_id": cid, **found[cid]} for cid in ids if cid in found],
        })
    if args.output:
        args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in receipt.items() if k != "channels"}, ensure_ascii=False))
    return 0 if not receipt.get("not_returned_ids") else 2

if __name__ == "__main__":
    sys.exit(main())
