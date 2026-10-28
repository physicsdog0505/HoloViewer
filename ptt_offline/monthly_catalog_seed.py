"""Owner-local, production-inert legacy -> monthly catalog seed builder.

This command does not deploy.  It requires a previously verified legacy
readback receipt, validates its manifest digest, and writes a deterministic
composite monthly catalog candidate for later owner-approved publication.
"""
from __future__ import annotations

import argparse
import json
import os
from hashlib import sha256
from pathlib import Path

from .monthly_catalog import MonthlyCatalogError, seed_verified_legacy


def _load_object(path: Path) -> dict:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise MonthlyCatalogError("JSON object required")
    return value


def build_legacy_seed(
    *,
    month: str,
    existing_catalog: Path | None,
    legacy_base: str,
    legacy_manifest_key: str,
    legacy_manifest: Path,
    readback_receipt: Path,
) -> dict:
    manifest_raw=legacy_manifest.read_bytes()
    receipt=_load_object(readback_receipt)
    if receipt.get("job_verified") is not True:
        raise MonthlyCatalogError("legacy readback receipt is not job_verified")
    manifest_verified=receipt.get("manifest_verified")
    if manifest_verified is None and isinstance(receipt.get("readback_receipt"),dict):
        manifest_verified=receipt["readback_receipt"].get("manifest_verified")
    if manifest_verified is not True:
        raise MonthlyCatalogError("legacy manifest readback is not verified")
    expected=receipt.get("manifest_digest")
    if expected is None and isinstance(receipt.get("manifest"),dict):
        expected=receipt["manifest"].get("digest")
    actual=sha256(manifest_raw).hexdigest()
    if expected is not None and expected!=actual:
        raise MonthlyCatalogError("legacy readback manifest digest mismatch")
    previous=existing_catalog.read_bytes() if existing_catalog and existing_catalog.is_file() else None
    return seed_verified_legacy(
        month=month,
        existing_catalog_raw=previous,
        base_url=legacy_base,
        manifest_key=legacy_manifest_key,
        manifest_raw=manifest_raw,
        legacy_readback_verified=True,
    )


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month",required=True)
    parser.add_argument("--existing-catalog",type=Path)
    parser.add_argument("--legacy-base",required=True)
    parser.add_argument("--legacy-manifest-key",required=True)
    parser.add_argument("--legacy-manifest",required=True,type=Path)
    parser.add_argument("--readback-receipt",required=True,type=Path)
    parser.add_argument("--out",required=True,type=Path)
    args=parser.parse_args(argv)
    result=build_legacy_seed(
        month=args.month,
        existing_catalog=args.existing_catalog,
        legacy_base=args.legacy_base,
        legacy_manifest_key=args.legacy_manifest_key,
        legacy_manifest=args.legacy_manifest,
        readback_receipt=args.readback_receipt,
    )
    args.out.parent.mkdir(parents=True,exist_ok=True)
    tmp=args.out.with_suffix(args.out.suffix+".tmp")
    tmp.write_bytes(result["raw"])
    os.replace(tmp,args.out)
    print(json.dumps({
        "status":"LEGACY_MONTHLY_CATALOG_SEED_READY",
        "key":result["key"],"sha256":result["sha256"],
        "complete_days":len(result["catalog"]["days"]),
        "production_mutation":False,
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
