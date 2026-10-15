#!/usr/bin/env python3
"""Local-only Pyodide -> exact combined #47/#48 Router -> mock-D1 proof.

Mutates only a disposable Worker bundle produced by build_python_worker_bundle.py.
No Cloudflare account, production URL, real D1, Publisher, Cron, secret or deploy.
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

PINNED = "a144bb378a8bdd772faa867d608c1e7491253883"
ISSUE47 = "149a80361654b06377dbae580e1d8da2e5010cf0"
ISSUE48 = "b96d0902a504bc26019efd693a1b3586cfb3d3d2"
DAY = "2026-10-15"


def _read_json(url: str, timeout: float = 5) -> tuple[int, dict]:
    try:
        response = urllib.request.urlopen(url, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        status = response.status
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise RuntimeError("oversized local proof response")
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("local proof returned non-JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("local proof returned non-object JSON")
    return status, data


def _wait_json(url: str, process: subprocess.Popen, timeout: float = 60) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"process exited before ready: {process.returncode}")
        try:
            status, data = _read_json(url, timeout=2)
            if status == 200:
                return data
        except (OSError, RuntimeError):
            time.sleep(0.5)
    raise TimeoutError("local proof process did not become ready")


def _head(path: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()


def _prepare_bundle(bundle: Path, api_port: int) -> None:
    receipt_path = bundle / "bundle-provenance.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("pinned_source") != PINNED or receipt.get("deployed") is not False:
        raise RuntimeError("Only fresh pinned nondeployed bundle is accepted")
    config_path = bundle / "wrangler.jsonc"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("main") != "entry.py":
        raise RuntimeError("Disposable bundle already modified")

    local_api = f"http://127.0.0.1:{api_port}"
    entry = f'''"""LOCAL #68 E2E ONLY — never deploy."""
import platform_adapter.cloudflare_entry as worker
from platform_adapter.public_api import DEFAULT_API, PublicAPIUnavailable
from pyodide.http import pyfetch

LOCAL_API = {local_api!r}

async def local_owner_router_json(url):
    if not url.startswith(DEFAULT_API + "/"):
        raise PublicAPIUnavailable("noncanonical request in local E2E")
    target = LOCAL_API + url[len(DEFAULT_API):]
    try:
        response = await pyfetch(target, method="GET", headers={{"Accept":"application/json"}})
        if response.status != 200:
            raise PublicAPIUnavailable("local combined Router HTTP error")
        data = await response.json()
    except PublicAPIUnavailable:
        raise
    except Exception as exc:
        raise PublicAPIUnavailable("local combined Router fetch failed") from exc
    if not isinstance(data, dict):
        raise PublicAPIUnavailable("local combined Router returned non-object")
    return data

worker.fetch_canonical_json = local_owner_router_json
Default = worker.Default
'''
    (bundle / "entry_router_e2e.py").write_text(entry, encoding="utf-8")
    config["main"] = "entry_router_e2e.py"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    receipt["local_combined_router_e2e_only"] = True
    receipt["local_combined_router_api_port"] = api_port
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def run(bundle: Path, owner47: Path, owner48: Path, *, api_port: int, worker_port: int) -> dict:
    bundle = bundle.resolve()
    owner47, owner48 = owner47.resolve(), owner48.resolve()
    if _head(owner47) != ISSUE47 or _head(owner48) != ISSUE48:
        raise RuntimeError("owner source HEAD mismatch")
    _prepare_bundle(bundle, api_port)

    root = Path(__file__).resolve().parents[1]
    router_log = bundle.parent / "combined-router-e2e.log"
    worker_log = bundle.parent / "pyodide-combined-router-e2e.log"
    router_cmd = [
        "node", str(root / "tools" / "serve_8788_owner_api_mock.mjs"),
        str(owner47), str(owner48), str(api_port),
    ]
    worker_cmd = [
        "uvx", "--from", "workers-py", "pywrangler", "dev", "--local",
        "--ip", "127.0.0.1", "--port", str(worker_port),
    ]
    env = {**os.environ, "CI": "1", "NO_COLOR": "1"}

    with router_log.open("w", encoding="utf-8") as rlog:
        router = subprocess.Popen(router_cmd, cwd=root, stdout=rlog, stderr=subprocess.STDOUT, env=env)
        try:
            router_ready = _wait_json(
                f"http://127.0.0.1:{api_port}/__proof", router, timeout=30
            )
            with worker_log.open("w", encoding="utf-8") as wlog:
                worker = subprocess.Popen(
                    worker_cmd, cwd=bundle, stdout=wlog, stderr=subprocess.STDOUT, env=env
                )
                try:
                    deadline = time.monotonic() + 120
                    home_status = None
                    home = None
                    while time.monotonic() < deadline:
                        if worker.poll() is not None:
                            raise RuntimeError(f"Pyodide Worker exited before ready: {worker.returncode}")
                        try:
                            home_status, home = _read_json(
                                f"http://127.0.0.1:{worker_port}/api/home", timeout=5
                            )
                            if home_status == 200 and isinstance(home.get("html"), str):
                                break
                        except (OSError, RuntimeError):
                            time.sleep(1)
                    else:
                        raise TimeoutError("Pyodide Worker did not complete /api/home through owner Router")

                    ptt_status, ptt = _read_json(
                        f"http://127.0.0.1:{api_port}/v1/ptt/today?day={DAY}", timeout=5
                    )
                    proof_status, proof = _read_json(
                        f"http://127.0.0.1:{api_port}/__proof", timeout=5
                    )
                    if ptt_status != 200 or ptt.get("schema_version") != "public-consumer-v1":
                        raise RuntimeError("combined #48 PTT mount is not active in local Router proof")
                    if proof_status != 200 or int(proof.get("db_reads", 0)) < 1:
                        raise RuntimeError("mock D1 read path was not exercised")
                    result = {
                        "status": "PASS",
                        "chain": "Pyodide fetch -> exact #47+#48 combined Router -> mock D1",
                        "issue47_sha": ISSUE47,
                        "issue48_sha": ISSUE48,
                        "accepted_4174_sha": PINNED,
                        "worker_route": "/api/home",
                        "worker_status": home_status,
                        "accepted_html_present": isinstance(home.get("html"), str),
                        "combined_ptt_mount_status": ptt_status,
                        "combined_ptt_schema": ptt.get("schema_version"),
                        "mock_d1_reads": proof.get("db_reads"),
                        "router_ready": router_ready.get("status") == "ready",
                        "production_deployment": False,
                        "production_d1": False,
                        "ptt_product_enabled": False,
                        "logs": {
                            "router": str(router_log),
                            "worker": str(worker_log),
                        },
                    }
                    return result
                finally:
                    worker.terminate()
                    try:
                        worker.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        worker.kill()
                        worker.wait(timeout=5)
        finally:
            router.terminate()
            try:
                router.wait(timeout=10)
            except subprocess.TimeoutExpired:
                router.kill()
                router.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--owner47", type=Path, required=True)
    parser.add_argument("--owner48", type=Path, required=True)
    parser.add_argument("--api-port", type=int, default=8790)
    parser.add_argument("--worker-port", type=int, default=8788)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(
        args.bundle, args.owner47, args.owner48,
        api_port=args.api_port, worker_port=args.worker_port,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
