"""Loopback-only fixture browser acceptance server for PR #147.

Never mount this helper as the production 8501 service.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from wsgiref.simple_server import make_server

from admin_dashboard.dashboard import DashboardController
from admin_dashboard.fixture_readers import FixtureReaders
from admin_dashboard.http import DashboardApplication
from admin_dashboard.isolated import AuthenticatedDashboard


def build_fixture_app(repo_root: Path):
    root = repo_root / "fixtures" / "data-lifecycle"
    fixture = json.loads((root / "admin-ui-coverage.sanitized.json").read_text(encoding="utf-8"))
    readers = FixtureReaders(
        root,
        days=fixture["days"],
        start_day=fixture["from_day"],
        end_day=fixture["through_day"],
    )
    app = DashboardApplication(DashboardController(readers.injected()))
    # Fixture-only acceptance seam. This is not production authentication proof.
    return AuthenticatedDashboard(app, lambda environ: environ.get("REMOTE_ADDR") in {"127.0.0.1", "::1"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8519)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    app = build_fixture_app(repo_root)
    with make_server("127.0.0.1", args.port, app) as httpd:
        print(f"fixture admin: http://127.0.0.1:{args.port}/admin/")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
