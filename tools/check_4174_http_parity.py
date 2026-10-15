#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ROUTES = [
    ("/", "page"),
    ("/history", "page"),
    ("/ptt-today", "page"),
    ("/ptt-today?focus=1", "page"),
    ("/custom-view", "page"),
    ("/custom-view/session?stream=dQw4w9WgXcQ&layout=auto&primary=0&audio=0", "page"),
    ("/custom-view/session?stream=dQw4w9WgXcQ&stream=9bZkp7q19f0&layout=auto&primary=0&audio=0", "page"),
    ("/watchalong", "page"),
    ("/collab", "page"),
    ("/api/home", "api"),
    ("/api/ptt/today", "api"),
]


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
    baseline_sha256: str
    candidate_sha256: str
    structural_equal: bool
    body_equal: bool
    note: str = ""


def fetch(base: str, path: str) -> tuple[int, bytes, str]:
    url = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
    req = Request(url, headers={"User-Agent": "HoloViewer-4174-Parity/1"})
    try:
        with urlopen(req, timeout=15) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
            return response.status, body, content_type
    except HTTPError as exc:
        body = exc.read()
        return exc.code, body, exc.headers.get("Content-Type", "")
    except URLError as exc:
        raise RuntimeError(f"cannot fetch {url}: {exc}") from exc


def canonical_json(body: bytes) -> bytes:
    parsed = json.loads(body.decode("utf-8"))
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def html_structure(body: bytes) -> bytes:
    parser = StructuralHTML()
    parser.feed(body.decode("utf-8", errors="replace"))
    return json.dumps(parser.items, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compare_one(baseline: str, candidate: str, path: str, kind: str) -> Receipt:
    bs, bb, bct = fetch(baseline, path)
    cs, cb, cct = fetch(candidate, path)

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
    elif not struct_equal:
        note = "DOM/JSON structural mismatch"
    elif not body_equal:
        note = "structure equal; raw body differs"

    return Receipt(
        path=path,
        kind=kind,
        baseline_status=bs,
        candidate_status=cs,
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
    for path, kind in ROUTES:
        receipt = compare_one(args.baseline, args.candidate, path, kind)
        receipts.append(receipt)
        status = "PASS" if receipt.baseline_status == receipt.candidate_status and receipt.structural_equal else "FAIL"
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
                if r.baseline_status == r.candidate_status and r.structural_equal
            ),
            "raw_body_equal": sum(1 for r in receipts if r.body_equal),
        },
    }
    from pathlib import Path
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"receipt: {out}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
