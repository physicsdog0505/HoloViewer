#!/usr/bin/env python3
"""Run *local-only* Cloudflare Python Worker compatibility smoke proof.

Never uses deploy/remote, secrets, production D1 bindings or live writers.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request


def probe(bundle: Path, *, port: int = 8787, timeout: int = 120) -> dict:
    if not (bundle / "bundle-provenance.json").is_file():
        raise RuntimeError("Missing pinned Worker bundle evidence")
    base = f"http://127.0.0.1:{port}"
    log_path = bundle.parent / "worker-local-proof.log"
    command = ["uvx", "--from", "workers-py", "pywrangler", "dev", "--local",
               "--ip", "127.0.0.1", "--port", str(port)]
    env = {**os.environ, "CI": "1", "NO_COLOR": "1"}
    results = []
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

            for target, expected in (
                ("/history?date=invalid", 400),
                ("/ptt-today", 503),
            ):
                try:
                    response = urllib.request.urlopen(base + target, timeout=15)
                except urllib.error.HTTPError as exc:
                    response = exc
                with response:
                    status = response.status
                    media_type = response.headers.get("Content-Type", "").split(";", 1)[0]
                    payload = response.read(1024 * 1024)
                okay = status == expected
                results.append({"path": target, "status": status,
                                "expected_status": expected,
                                "content_type": media_type, "pass": okay,
                                "body_size": len(payload)})
                print(("PASS" if okay else "FAIL") + " " + target + " " + str(status))
            if not all(result["pass"] for result in results):
                raise RuntimeError("Local Python Worker HTTP proof failed")
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    return {"runtime": "local Python Workers/Pyodide workerd",
            "bundle": json.loads((bundle / "bundle-provenance.json").read_text()),
            "checks": results, "production_deployment": False,
            "log": str(log_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = probe(args.bundle.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
