#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

WORKER = "holoviewer-public-api"
DB_NAME = "holoviewer-public-v1"
DB_ID = "64e1a0ee-1455-4377-9640-3922e8f4d061"
PTT_SECRET_NAMES = {
    "PTT_PUBLISH_HMAC_SECRET",
    "PTT_TIME_AUTHORITY_SECRET",
    "PTT_PUBLISH_ENABLED",
    "PTT_PUBLISH_MAX_ROWS",
    "PTT_PUBLISH_MAX_BYTES",
    "PTT_PUBLISH_MAX_QUERIES",
    "PTT_PUBLISH_MAX_WRITES",
}


def load_config(path: str) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if cfg.get("name") != WORKER:
        raise SystemExit("wrong Worker config")
    if cfg.get("assets"):
        raise SystemExit("frontend/assets config cannot be used as backend config")
    db = next((x for x in cfg.get("d1_databases", []) if x.get("binding") == "DB"), None)
    if not db or db.get("database_name") != DB_NAME or db.get("database_id") != DB_ID:
        raise SystemExit("wrong D1 binding")
    return cfg


def validated_support_colors(path: str) -> str:
    body = json.loads(Path(path).read_text(encoding="utf-8"))
    if body.get("schema_version") != 1 or body.get("fallback") != "neutral":
        raise SystemExit("invalid support-color export header")
    rows = body.get("channels")
    if not isinstance(rows, list) or len(rows) != 66:
        raise SystemExit("support-color export must contain exact legacy 66 rows")
    ids = [row.get("channel_id") for row in rows]
    if len(set(ids)) != 66 or any(not isinstance(x, str) or not x.startswith("UC") or len(x) != 24 for x in ids):
        raise SystemExit("invalid support-color channel identities")
    colored = neutral = dual = 0
    for row in rows:
        mode = row.get("display_mode")
        if mode == "dual_color":
            colors = row.get("color_hexes")
            if not isinstance(colors, list) or len(colors) != 2:
                raise SystemExit("invalid dual support-color row")
            if row.get("color_semantics") != "2025_6th_fes_penlight":
                raise SystemExit("invalid dual support-color semantics")
            dual += 1
            colored += 1
        elif mode == "solid":
            if not isinstance(row.get("color_hex"), str):
                raise SystemExit("invalid solid support-color row")
            colored += 1
        elif mode == "neutral":
            neutral += 1
        else:
            raise SystemExit("invalid support-color display mode")
    if (colored, neutral, dual) != (57, 9, 1):
        raise SystemExit("support-color receipt mismatch")
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def chunk_utf8(text: str, limit: int = 4000) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for ch in text:
        n = len(ch.encode("utf-8"))
        if current and size + n > limit:
            chunks.append("".join(current))
            current = []
            size = 0
        current.append(ch)
        size += n
    if current:
        chunks.append("".join(current))
    return chunks


def materialize(config_path: str, support_colors_path: str, output_path: str) -> dict:
    cfg = json.loads(json.dumps(load_config(config_path)))
    vars_map = dict(cfg.get("vars") or {})

    # These are Production secrets. A stale plaintext config value must never
    # overwrite the secret binding during an owner-local Worker release.
    for name in PTT_SECRET_NAMES:
        vars_map.pop(name, None)

    # Preserve all unrelated Production vars exactly, including ALLOWED_ORIGIN.
    for name in list(vars_map):
        if name == "TODAY_SUPPORT_COLORS_JSON" or name.startswith("TODAY_SUPPORT_COLORS_JSON_"):
            vars_map.pop(name, None)

    payload = validated_support_colors(support_colors_path)
    chunks = chunk_utf8(payload)
    for i, chunk in enumerate(chunks):
        vars_map[f"TODAY_SUPPORT_COLORS_JSON_{i}"] = chunk

    cfg["vars"] = vars_map
    out = Path(output_path)
    out.write_text(json.dumps(cfg, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    raw = out.read_bytes()
    return {
        "status": "MATERIALIZED",
        "worker": WORKER,
        "database": DB_NAME,
        "output": str(out),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "support_color_chunks": len(chunks),
        "support_color_receipt": {"rows": 66, "colored": 57, "neutral": 9, "dual": 1},
        "frontend_assets": False,
        "ptt_plaintext_secret_vars_removed": sorted(PTT_SECRET_NAMES),
        "allowed_origin_preserved": "ALLOWED_ORIGIN" in vars_map,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--support-colors-json", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    receipt = materialize(args.config, args.support_colors_json, args.output)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
