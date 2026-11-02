#!/usr/bin/env python3
"""Promote one accepted Daily Digest return candidate into the local public artifact path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


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


def evaluate_publish(*, receipt_path: Path, candidate_path: Path, output_path: Path, execute: bool) -> dict[str, str]:
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"invalid return receipt: {exc}") from exc
    if not isinstance(receipt, dict) or receipt.get("status") != "READY_FOR_PUBLICATION":
        raise PublishError("return receipt is not READY_FOR_PUBLICATION")

    target_day = str(receipt.get("target_day") or "").strip()
    if not target_day:
        raise PublishError("return receipt missing target_day")
    expected_name = f"{target_day}.json"
    if output_path.name != expected_name:
        raise PublishError(f"public output filename must be {expected_name!r}")

    candidate_bytes = candidate_path.read_bytes()
    actual_sha = sha256_bytes(candidate_bytes)
    expected_sha = str(receipt.get("public_candidate_sha256") or "")
    if actual_sha != expected_sha:
        raise PublishError("public candidate SHA does not match return receipt")

    if output_path.exists():
        existing = output_path.read_bytes()
        if existing == candidate_bytes:
            return {
                "status": "ALREADY_PUBLISHED",
                "target_day": target_day,
                "candidate_sha256": actual_sha,
                "output": str(output_path.resolve()),
            }
        if not execute:
            return {
                "status": "READY_TO_PUBLISH",
                "target_day": target_day,
                "candidate_sha256": actual_sha,
                "existing_sha256": sha256_bytes(existing),
                "output": str(output_path.resolve()),
            }

    if not execute:
        return {
            "status": "READY_TO_PUBLISH",
            "target_day": target_day,
            "candidate_sha256": actual_sha,
            "existing_sha256": "",
            "output": str(output_path.resolve()),
        }

    atomic_write(output_path, candidate_bytes)
    return {
        "status": "PUBLISHED_LOCAL",
        "target_day": target_day,
        "candidate_sha256": actual_sha,
        "output_sha256": sha256_bytes(output_path.read_bytes()),
        "output": str(output_path.resolve()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--execute", action="store_true", help="atomically update the local public artifact; does not deploy")
    args = parser.parse_args(argv)
    try:
        result = evaluate_publish(
            receipt_path=args.receipt.resolve(),
            candidate_path=args.candidate.resolve(),
            output_path=args.output.resolve(),
            execute=args.execute,
        )
    except (PublishError, OSError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1
    for key, value in result.items():
        print(f"{key.upper()}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
