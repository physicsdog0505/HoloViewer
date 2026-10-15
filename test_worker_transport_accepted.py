"""Exact accepted 4174 dispatcher fixture proof; never starts a socket/server.

The accepted ClientRequestHandler.do_GET is the one being executed. External
provider data and time-varying fields are patched at the existing data-entry
seams so this test remains deterministic and network-free.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

VENDOR = Path(__file__).resolve().parent / "vendor" / "4174-a144bb3"
sys.path.insert(0, str(VENDOR))

import client_app  # noqa: E402
from platform_adapter.worker_transport import dispatch_accepted_get  # noqa: E402


class AcceptedDispatcherProof(unittest.TestCase):
    def test_home_delegates_to_unchanged_4174_handler(self):
        with (
            patch.object(client_app, "load_home_streams", return_value=([], [], [], [])),
            patch.object(client_app, "build_home_html", return_value="<main>original accepted home</main>") as render,
        ):
            result = dispatch_accepted_get(client_app.ClientRequestHandler, target="/")
        self.assertEqual(result.status, 200)
        self.assertEqual(dict(result.headers)["Content-Type"], "text/html; charset=utf-8")
        self.assertIn(b"original accepted home", result.body)
        render.assert_called_once()

    def test_api_home_delegates_to_accepted_fragment(self):
        with (
            patch.object(client_app, "load_home_streams", return_value=([], [], [], [])),
            patch.object(client_app, "build_home_fragment", return_value="<p>accepted</p>") as render,
        ):
            result = dispatch_accepted_get(client_app.ClientRequestHandler, target="/api/home")
        self.assertEqual(result.status, 200)
        self.assertEqual(dict(result.headers)["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(json.loads(result.body)["html"], "<p>accepted</p>")
        render.assert_called_once()

    def test_history_query_and_rejected_date(self):
        # Invalid date is handled by the accepted renderer, including status.
        response = dispatch_accepted_get(
            client_app.ClientRequestHandler, target="/history?date=invalid"
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(dict(response.headers)["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("無效的歷史日期".encode(), response.body)

    def test_full_product_dispatcher_not_copied(self):
        self.assertIs(
            client_app.ClientRequestHandler.do_GET.__module__,
            client_app.ClientRequestHandler.__module__,
        )


if __name__ == "__main__":
    unittest.main()
