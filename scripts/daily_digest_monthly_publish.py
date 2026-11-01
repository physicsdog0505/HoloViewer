#!/usr/bin/env python3
"""Merge one accepted Daily Digest candidate into its month-sharded public asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


MONTH_KIND = "holodocchi.daily_digest_month"
DAY_KIND = "holodocchi.daily_digest"


class PublishError(RuntimeError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def month_path(root: Path, target_day: str) -> Path:
    return root / "data" / "daily-digest" / "months" / f"{target_day[:7]}.json"


def load_month(path: Path, month: str) -> dict:
    if not path.exists():
        return {"schema_version": 1, "kind": MONTH_KIND, "month": month, "days": {}}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"invalid existing month shard: {exc}") from exc
    if (
        not isinstance(obj, dict)
        or obj.get("schema_version") != 1
        or obj.get("kind") != MONTH_KIND
        or obj.get("month") != month
        or not isinstance(obj.get("days"), dict)
    ):
        raise PublishError("existing month shard contract mismatch")
    return obj


def evaluate_publish(*, receipt_path: Path, candidate_path: Path, asset_root: Path, execute: bool) -> dict[str, str]:
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        candidate_bytes = candidate_path.read_bytes()
        artifact = json.loads(candidate_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"invalid publish input: {exc}") from exc

    if not isinstance(receipt, dict) or receipt.get("status") != "READY_FOR_PUBLICATION":
        raise PublishError("return receipt is not READY_FOR_PUBLICATION")
    target_day = str(receipt.get("target_day") or "").strip()
    if len(target_day) != 10 or target_day[4] != "-" or target_day[7] != "-":
        raise PublishError("invalid target_day")

    actual_sha = sha256_bytes(candidate_bytes)
    if actual_sha != str(receipt.get("public_candidate_sha256") or ""):
        raise PublishError("public candidate SHA does not match return receipt")
    if (
        not isinstance(artifact, dict)
        or artifact.get("schema_version") != 1
        or artifact.get("kind") != DAY_KIND
        or artifact.get("target_day") != target_day
    ):
        raise PublishError("candidate day artifact contract mismatch")

    month = target_day[:7]
    output = month_path(asset_root, target_day)
    payload = load_month(output, month)
    existing = payload["days"].get(target_day)
    if existing == artifact:
        return {
            "status": "ALREADY_PUBLISHED",
            "target_day": target_day,
            "month": month,
            "candidate_sha256": actual_sha,
            "output": str(output.resolve()),
            "month_sha256": sha256_bytes(output.read_bytes()) if output.exists() else "",
        }

    payload["days"][target_day] = artifact
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    if not execute:
        return {
            "status": "READY_TO_PUBLISH",
            "target_day": target_day,
            "month": month,
            "candidate_sha256": actual_sha,
            "output": str(output.resolve()),
            "month_sha256": sha256_bytes(encoded),
        }

    atomic_write(output, encoded)
    return {
        "status": "PUBLISHED_LOCAL",
        "target_day": target_day,
        "month": month,
        "candidate_sha256": actual_sha,
        "output": str(output.resolve()),
        "month_sha256": sha256_bytes(output.read_bytes()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = evaluate_publish(
            receipt_path=args.receipt.resolve(),
            candidate_path=args.candidate.resolve(),
            asset_root=args.asset_root.resolve(),
            execute=args.execute,
        )
    except PublishError as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1
    for key, value in result.items():
        print(f"{key.upper()}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
