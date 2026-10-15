"""Offline checks of canonical Worker provider initialization and transport."""
import asyncio
import importlib
import sys
import types
import unittest
from unittest.mock import patch, AsyncMock

from platform_adapter.public_api import DEFAULT_API
from platform_adapter.worker_transport import TransportResponse


class FakeResponse:
    def __init__(self, body, *, status=200, headers=None):
        self.body, self.status, self.headers = body, status, headers or {}


class FakeRequest:
    url = "https://public.example.test/api/home"
    method = "GET"


class EntryPointBindingTest(unittest.TestCase):
    def setUp(self):
        fake_workers = types.ModuleType("workers")
        fake_workers.WorkerEntrypoint = type("WorkerEntrypoint", (), {})
        fake_workers.Response = FakeResponse
        fake_client_app = types.ModuleType("client_app")
        fake_client_app.ClientRequestHandler = type("AcceptedHandler", (), {})
        self.workers = patch.dict(sys.modules, {
            "workers": fake_workers, "client_app": fake_client_app
        })
        self.workers.start()
        sys.modules.pop("platform_adapter.cloudflare_entry", None)
        self.entry = importlib.import_module("platform_adapter.cloudflare_entry")

    def tearDown(self):
        sys.modules.pop("platform_adapter.cloudflare_entry", None)
        self.workers.stop()

    def test_binds_canonical_provider_once_before_original_dispatch(self):
        order = []
        def bind(app, *, api_base):
            self.assertEqual(api_base, DEFAULT_API)
            order.append("provider")
        def dispatch(handler, *, target, method):
            order.append("dispatch")
            self.assertEqual((target,method),("/api/home","GET"))
            return TransportResponse(200,(("Content-Type","application/json"),),b"{}")
        with (patch.object(self.entry, "bind_public_today", side_effect=bind),
              patch.object(self.entry, "preload_for_accepted_request", new_callable=AsyncMock, return_value={}),
              patch.object(self.entry, "dispatch_accepted_get", side_effect=dispatch)):
            response = asyncio.run(self.entry.Default().fetch(FakeRequest()))
            self.assertEqual(response.status,200)
            asyncio.run(self.entry.Default().fetch(FakeRequest()))
        self.assertEqual(order,["provider","dispatch","dispatch"])

    def test_binding_failure_keeps_runtime_unbound(self):
        with patch.object(self.entry, "bind_public_today", side_effect=ValueError("unavailable")):
            with self.assertRaises(ValueError):
                self.entry._accepted_handler()
        self.assertFalse(self.entry._bound)

    def test_unbound_ptt_route_returns_503_without_vendor_or_provider(self):
        class PttRequest:
            url = "https://public.example.test/ptt-today"
            method = "GET"
        with (patch.object(self.entry, "bind_public_today") as bind,
              patch.object(self.entry, "dispatch_accepted_get") as dispatch):
            response = asyncio.run(self.entry.Default().fetch(PttRequest()))
        self.assertEqual(response.status, 503)
        bind.assert_not_called()
        dispatch.assert_not_called()

    def test_handler_binding_never_selects_custom_provider(self):
        with patch.object(self.entry, "bind_public_today") as bind:
            self.entry._accepted_handler()
        self.assertEqual(bind.call_args.kwargs["api_base"], DEFAULT_API)


if __name__ == "__main__":
    unittest.main()
