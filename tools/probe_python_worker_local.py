#!/usr/bin/env python3
"""Run *local-only* Cloudflare Python Worker compatibility smoke proof.

Never uses deploy/remote, secrets, production D1 bindings or live writers.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request



def compare_accepted_fixture(worker_base: str, *, port: int = 58085) -> dict:
    """Run the SHA-pinned product locally and reuse existing DOM/JSON comparator."""
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from tools.check_4174_http_parity import compare_one, fetch

    with tempfile.TemporaryDirectory(prefix="hv-accepted-parity-") as runtime:
        vendor = root / "vendor" / "4174-a144bb3"
        log_path = Path(runtime) / "accepted-4174.log"
        env = {**os.environ,
               "PTT_CLIENT_DISABLE_TODAY_REFRESH": "1",
               "PTT_CLIENT_RUNTIME_ROOT": runtime,
               "PYTHONDONTWRITEBYTECODE": "1"}
        command = [
            sys.executable, "-B", str(vendor / "client_app.py"),
            "--host", "127.0.0.1", "--port", str(port),
            "--runtime-root", runtime,
        ]
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=vendor, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                baseline = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 45
                ready = False
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    try:
                        response = fetch(baseline, "/history?date=invalid")
                        if response[0] == 400:
                            ready = True
                            break
                    except (OSError, RuntimeError):
                        time.sleep(0.5)
                if not ready:
                    log.flush()
                    raise RuntimeError(
                        "accepted 4174 parity process unavailable: "
                        + log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                    )

                receipts = []
                for route, kind in (
                    ("/", "page"),
                    ("/api/home", "api"),
                    ("/history", "page"),
                    ("/history?date=invalid", "page"),
                ):
                    row = compare_one(baseline, worker_base, route, kind)
                    okay = (
                        row.baseline_status == row.candidate_status
                        and row.baseline_content_type == row.candidate_content_type
                        and row.structural_equal
                    )
                    print(("PASS" if okay else "FAIL") +
                          ": accepted-vs-Pyodide " + route + " " + row.note,
                          flush=True)
                    receipts.append({"pass": okay, **asdict(row)})
                if not all(r["pass"] for r in receipts):
                    raise RuntimeError("Accepted 4174 vs Worker DOM/JSON parity failed")
                from playwright.sync_api import sync_playwright
                from tools.check_4174_browser_state_parity import general_page
                browser_rows = []
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    try:
                        for width in (1440, 760, 390):
                            for route in ("/", "/history"):
                                original = general_page(browser, baseline, width, route)
                                worker = general_page(browser, worker_base, width, route)
                                passed = original == worker
                                browser_rows.append({
                                    "path": route, "width": width, "pass": passed,
                                    "baseline": original, "candidate": worker,
                                })
                                print(("PASS" if passed else "FAIL") +
                                      ": accepted-vs-Pyodide browser " +
                                      route + " " + str(width) + "px", flush=True)
                    finally:
                        browser.close()
                if not all(row["pass"] for row in browser_rows):
                    raise RuntimeError("Accepted 4174 vs Worker browser geometry parity failed")
                return {"accepted_source": "a144bb378a8bdd772faa867d608c1e7491253883",
                        "routes": receipts, "browser": browser_rows, "status": "PASS"}
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def probe(bundle: Path, *, port: int = 8787, timeout: int = 120) -> dict:
    if not (bundle / "bundle-provenance.json").is_file():
        raise RuntimeError("Missing pinned Worker bundle evidence")
    base = f"http://127.0.0.1:{port}"
    log_path = bundle.parent / "worker-local-proof.log"
    command = ["uvx", "--from", "workers-py", "pywrangler", "dev", "--local",
               "--ip", "127.0.0.1", "--port", str(port)]
    env = {**os.environ, "CI": "1", "NO_COLOR": "1"}
    bundle_evidence = json.loads((bundle / "bundle-provenance.json").read_text())
    fixture_mode = bundle_evidence.get("local_fixture_only") is True
    results = []
    parity = None
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=bundle, stdout=log,
                                   stderr=subprocess.STDOUT, env=env)
        try:
            deadline = time.monotonic() + timeout
            ready = False
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    log.flush()
                    details = log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
                    raise RuntimeError(
                        "Pyodide workerd exited before ready (exit "
                        + str(process.returncode) + "):\\n" + details
                    )
                try:
                    request = urllib.request.Request(base + "/history?date=invalid")
                    with urllib.request.urlopen(request, timeout=2):
                        ready = True
                        break
                except urllib.error.HTTPError as exc:
                    if exc.code in (400, 500, 503):
                        ready = True
                        break
                except (OSError, TimeoutError):
                    time.sleep(2)
            if not ready:
                log.flush()
                details = log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
                raise TimeoutError("Local Python Worker did not start:\\n" + details)

            expected_routes = [
                ("/history?date=invalid", 400),
                ("/ptt-today", 503),
            ]
            if fixture_mode:
                expected_routes = [
                    ("/", 200), ("/api/home", 200), ("/history", 200),
                    *expected_routes,
                ]
            for target, expected in expected_routes:
                try:
                    response = urllib.request.urlopen(base + target, timeout=15)
                except urllib.error.HTTPError as exc:
                    response = exc
                with response:
                    status = response.status
                    media_type = response.headers.get("Content-Type", "").split(";", 1)[0]
                    payload = response.read(1024 * 1024)
                okay = status == expected
                if target == "/api/home" and okay:
                    try:
                        document = json.loads(payload)
                        okay = isinstance(document.get("html"), str)
                    except (UnicodeDecodeError, ValueError):
                        okay = False
                if target == "/" and okay:
                    okay = b"<html" in payload.lower()
                results.append({"path": target, "status": status,
                                "expected_status": expected,
                                "content_type": media_type, "pass": okay,
                                "body_size": len(payload)})
                print(("PASS" if okay else "FAIL") + " " + target + " " + str(status))
            if not all(result["pass"] for result in results):
                log.flush()
                details = log_path.read_text(encoding="utf-8", errors="replace")[-12000:]
                print("=== LOCAL PYODIDE ERROR LOG ===", flush=True)
                print(details, flush=True)
                print("=== END PYODIDE ERROR LOG ===", flush=True)
                raise RuntimeError("Local Python Worker HTTP proof failed")
            if fixture_mode:
                parity = compare_accepted_fixture(base)
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    return {"runtime": "local Python Workers/Pyodide workerd",
            "bundle": json.loads((bundle / "bundle-provenance.json").read_text()),
            "checks": results, "accepted_parity": parity, "production_deployment": False,
            "log": str(log_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    receipt = probe(args.bundle.resolve(), port=args.port)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
