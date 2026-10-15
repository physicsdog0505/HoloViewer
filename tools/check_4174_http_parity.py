#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, build_opener, HTTPRedirectHandler


MATRIX = Path(__file__).resolve().parents[1] / "provenance" / "4174-parity-matrix.json"


def parity_routes() -> list[tuple[str, str]]:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    rows = [(item["path"], item["kind"]) for item in matrix["routes"]]
    if len(rows) != len(set(rows)):
        raise ValueError("duplicate route in accepted parity matrix")
    if not rows or any(kind not in {"api", "page"} for _, kind in rows):
        raise ValueError("invalid accepted parity route matrix")
    return rows


class StructuralHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple] = []

    def handle_starttag(self, tag, attrs):
        attrs = tuple(sorted((k, v or "") for k, v in attrs if k not in {"nonce"}))
        self.items.append(("start", tag, attrs))

    def handle_startendtag(self, tag, attrs):
        attrs = tuple(sorted((k, v or "") for k, v in attrs if k not in {"nonce"}))
        self.items.append(("empty", tag, attrs))

    def handle_endtag(self, tag):
        self.items.append(("end", tag))

    def handle_data(self, data):
        text = re.sub(r"\s+", " ", data).strip()
        if text:
            self.items.append(("text", text))


@dataclass
class Receipt:
    path: str
    kind: str
    baseline_status: int
    candidate_status: int
    baseline_content_type: str
    candidate_content_type: str
    baseline_location: str
    candidate_location: str
    baseline_sha256: str
    candidate_sha256: str
    structural_equal: bool
    body_equal: bool
    note: str = ""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = build_opener(NoRedirect)


def fetch(base: str, path: str) -> tuple[int, bytes, str, str]:
    url = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
    req = Request(url, headers={"User-Agent": "HoloViewer-4174-Parity/1"})
    try:
        with OPENER.open(req, timeout=15) as response:
            body = response.read()
            return (response.status, body,
                    response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower(),
                    response.headers.get("Location", ""))
    except HTTPError as exc:
        return (exc.code, exc.read(),
                exc.headers.get("Content-Type", "").split(";", 1)[0].strip().lower(),
                exc.headers.get("Location", ""))
    except URLError as exc:
        raise RuntimeError(f"cannot fetch {url}: {exc}") from exc


def canonical_json(body: bytes) -> bytes:
    parsed = json.loads(body.decode("utf-8"))
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def html_items(body: bytes) -> list[tuple]:
    parser = StructuralHTML()
    parser.feed(body.decode("utf-8", errors="replace"))
    return parser.items


def html_structure(body: bytes) -> bytes:
    return json.dumps(
        html_items(body),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def first_structure_diff(left: bytes, right: bytes) -> dict | None:
    a = html_items(left)
    b = html_items(right)
    limit = min(len(a), len(b))
    index = next((i for i in range(limit) if a[i] != b[i]), None)
    if index is None:
        if len(a) == len(b):
            return None
        index = limit
    lo = max(0, index - 3)
    hi = index + 4
    return {
        "index": index,
        "baseline_count": len(a),
        "candidate_count": len(b),
        "baseline_context": a[lo:hi],
        "candidate_context": b[lo:hi],
    }


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compare_one(baseline: str, candidate: str, path: str, kind: str) -> Receipt:
    bs, bb, bct, bloc = fetch(baseline, path)
    cs, cb, cct, cloc = fetch(candidate, path)

    if kind == "api":
        try:
            bn = canonical_json(bb)
            cn = canonical_json(cb)
            struct_equal = bn == cn
        except Exception:
            bn, cn = bb, cb
            struct_equal = False
    else:
        bn = html_structure(bb)
        cn = html_structure(cb)
        struct_equal = bn == cn

    body_equal = bb == cb
    note = ""
    if bs != cs:
        note = "status mismatch"
    elif bct != cct or (bs < 400 and bct != ("application/json" if kind == "api" else "text/html")):
        note = "Content-Type mismatch or invalid media type"
    elif bloc != cloc:
        note = "redirect Location mismatch"
    elif not struct_equal:
        note = "DOM/JSON structural mismatch"
        if kind == "page":
            detail = first_structure_diff(bb, cb)
            if detail is not None:
                note += " | " + json.dumps(detail, ensure_ascii=False)
    elif not body_equal:
        note = "structure equal; raw body differs"

    return Receipt(
        path=path,
        kind=kind,
        baseline_status=bs,
        candidate_status=cs,
        baseline_content_type=bct,
        candidate_content_type=cct,
        baseline_location=bloc,
        candidate_location=cloc,
        baseline_sha256=sha(bb),
        candidate_sha256=sha(cb),
        structural_equal=struct_equal,
        body_equal=body_equal,
        note=note,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare accepted 4174 and isolated 8788 HTTP/DOM behavior")
    parser.add_argument("--baseline", required=True, help="accepted 4174 base URL, e.g. http://127.0.0.1:4174")
    parser.add_argument("--candidate", required=True, help="isolated 8788 base URL, e.g. http://127.0.0.1:8788")
    parser.add_argument("--output", default="provenance/4174-http-parity-receipt.json")
    args = parser.parse_args()

    receipts: list[Receipt] = []
    failed = False
    for path, kind in parity_routes():
        receipt = compare_one(args.baseline, args.candidate, path, kind)
        receipts.append(receipt)
        status = "PASS" if receipt.baseline_status == receipt.candidate_status and receipt.baseline_content_type == receipt.candidate_content_type and (receipt.baseline_status >= 400 or receipt.baseline_content_type == ("application/json" if kind == "api" else "text/html")) and receipt.baseline_location == receipt.candidate_location and receipt.structural_equal else "FAIL"
        print(f"{status}: {path} baseline={receipt.baseline_status} candidate={receipt.candidate_status} {receipt.note}")
        if status == "FAIL":
            failed = True

    output = {
        "schema_version": 1,
        "baseline": args.baseline,
        "candidate": args.candidate,
        "routes": [r.__dict__ for r in receipts],
        "summary": {
            "count": len(receipts),
            "structural_pass": sum(
                1 for r in receipts
                if r.baseline_status == r.candidate_status and r.baseline_content_type == r.candidate_content_type and (r.baseline_status >= 400 or r.baseline_content_type == ("application/json" if r.kind == "api" else "text/html")) and r.baseline_location == r.candidate_location and r.structural_equal
            ),
            "raw_body_equal": sum(1 for r in receipts if r.body_equal),
        },
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"receipt: {out}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
