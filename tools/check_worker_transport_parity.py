#!/usr/bin/env python3
"""Compare the accepted localhost HTTP handler against socketless Worker transport.

Use only for a local, isolated 4174 baseline with equivalent disposable data.
The tested adapter delegates into ClientRequestHandler.do_GET, not a copied
renderer or route dispatcher.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "4174-a144bb3"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(VENDOR))

from client_app import ClientRequestHandler  # noqa: E402
from platform_adapter.worker_transport import dispatch_accepted_get  # noqa: E402

PROOF_ROUTES = ("/", "/api/home", "/history?date=invalid")


def normalize(content_type):
    return content_type.split(";", 1)[0].lower().strip()


def live_http(base, target):
    try:
        response = urlopen(base.rstrip("/") + target, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        return response.status, normalize(response.headers.get("Content-Type", "")), response.read()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--output", default="provenance/4174-worker-transport-receipt.json")
    args=parser.parse_args()
    results=[]
    for target in PROOF_ROUTES:
        expected_status, expected_type, expected_body = live_http(args.baseline, target)
        actual=dispatch_accepted_get(ClientRequestHandler, target=target)
        actual_type=normalize(dict(actual.headers).get("Content-Type",""))
        if expected_type=="application/json":
            body_equal=json.loads(expected_body)==json.loads(actual.body)
        else:
            from html.parser import HTMLParser
            # Existing browser/DOM harness owns full geometry; this comparison
            # retains exact HTML bytes for the minimal transport proof.
            body_equal=expected_body==actual.body
        passed=(expected_status==actual.status and expected_type==actual_type and body_equal)
        results.append({"path":target,"pass":passed,"baseline_status":expected_status,
                        "candidate_status":actual.status,"baseline_content_type":expected_type,
                        "candidate_content_type":actual_type,"body_equal":body_equal})
        print(("PASS" if passed else "FAIL")+": Worker transport "+target)
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({"routes":results,"status":"PASS" if all(r["pass"] for r in results) else "FAIL"},indent=2)+"\n")
    return 0 if all(r["pass"] for r in results) else 1


if __name__=="__main__":
    raise SystemExit(main())
