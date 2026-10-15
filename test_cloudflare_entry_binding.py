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

    def test_non_get_never_preloads_or_dispatches(self):
        class PostRequest:
            url = "https://public.example.test/api/home"
            method = "POST"
        with (patch.object(self.entry, "preload_for_accepted_request") as preload,
              patch.object(self.entry, "dispatch_accepted_get") as dispatch):
            response = asyncio.run(self.entry.Default().fetch(PostRequest()))
        self.assertEqual(response.status, 405)
        preload.assert_not_called()
        dispatch.assert_not_called()

    def test_embedded_ptt_only_returns_blank_without_backend_fetch(self):
        class Embedded:
            url = "https://public.example.test/ptt-today?focus=1&embed=1"
            method = "GET"
        with (patch.object(self.entry, "preload_for_accepted_request") as preload,
              patch.object(self.entry, "dispatch_accepted_get") as dispatch):
            response = asyncio.run(self.entry.Default().fetch(Embedded()))
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, "")
        preload.assert_not_called()
        dispatch.assert_not_called()

    def test_custom_view_routes_use_canonical_preload_and_accepted_dispatch(self):
        for route in ("/custom-view", "/custom-view/session?stream=dQw4w9WgXcQ&ptt=live"):
            with self.subTest(route=route):
                class CustomRequest:
                    url = "https://public.example.test" + route
                    method = "GET"
                with (patch.object(self.entry, "bind_public_today") as bind,
                      patch.object(self.entry, "preload_for_accepted_request", new_callable=AsyncMock, return_value={}) as preload,
                      patch.object(self.entry, "dispatch_accepted_get", return_value=TransportResponse(
                          200, (("Content-Type", "text/html"),), b"<html></html>"
                      )) as dispatch):
                    response = asyncio.run(self.entry.Default().fetch(CustomRequest()))
                self.assertEqual(response.status, 200)
                self.assertEqual(bind.call_count, 1 if route == "/custom-view" else 0)
                self.assertEqual(preload.await_args.args[0], route)
                self.assertEqual(dispatch.call_args.kwargs["target"], route)

    def test_collab_routes_use_canonical_preload_and_accepted_dispatch(self):
        routes = (
            "/collab",
            "/collab/session?collab=ark&stream=dQw4w9WgXcQ",
            "/api/collab/live?collab=ark&stream=dQw4w9WgXcQ",
        )
        for route in routes:
            with self.subTest(route=route):
                class CollabRequest:
                    url = "https://public.example.test" + route
                    method = "GET"
                with (patch.object(self.entry, "preload_for_accepted_request", new_callable=AsyncMock, return_value={}) as preload,
                      patch.object(self.entry, "dispatch_accepted_get", return_value=TransportResponse(
                          200, (("Content-Type", "text/html"),), b"<html></html>"
                      )) as dispatch):
                    response = asyncio.run(self.entry.Default().fetch(CollabRequest()))
                self.assertEqual(response.status, 200)
                self.assertEqual(preload.await_args.args[0], route)
                self.assertEqual(dispatch.call_args.kwargs["target"], route)

    def test_page_only_routes_render_fallback_without_provider(self):
        for route in ("/ptt-today", "/watchalong", "/watchalong/session"):
            with self.subTest(route=route):
                class PageRequest:
                    url = "https://public.example.test" + route
                    method = "GET"
                with (patch.object(self.entry, "render_page_fallback", return_value=(200, "<html>fallback</html>")) as fallback,
                      patch.object(self.entry, "preload_for_accepted_request") as preload,
                      patch.object(self.entry, "dispatch_accepted_get") as dispatch):
                    response = asyncio.run(self.entry.Default().fetch(PageRequest()))
                self.assertEqual(response.status, 200)
                self.assertEqual(response.body, "<html>fallback</html>")
                fallback.assert_called_once_with(route)
                preload.assert_not_called()
                dispatch.assert_not_called()

    def test_connected_page_falls_back_to_4174_shell_when_provider_is_down(self):
        class HistoryRequest:
            url = "https://public.example.test/history?date=2026-10-15"
            method = "GET"
        with (patch.object(self.entry, "preload_for_accepted_request", new_callable=AsyncMock, side_effect=self.entry.PublicAPIUnavailable("down")),
              patch.object(self.entry, "render_page_fallback", return_value=(200, "<html>history-shell</html>")) as fallback,
              patch.object(self.entry, "dispatch_accepted_get") as dispatch):
            response = asyncio.run(self.entry.Default().fetch(HistoryRequest()))
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, "<html>history-shell</html>")
        fallback.assert_called_once()
        dispatch.assert_not_called()

    def test_page_exception_falls_back_instead_of_raising_1101(self):
        class HomeRequest:
            url = "https://public.example.test/"
            method = "GET"
        with (patch.object(self.entry, "preload_for_accepted_request", new_callable=AsyncMock, return_value={}),
              patch.object(self.entry, "dispatch_lightweight_home", side_effect=RuntimeError("boom")),
              patch.object(self.entry, "render_page_fallback", return_value=(200, "<html>safe-home</html>")) as fallback):
            response = asyncio.run(self.entry.Default().fetch(HomeRequest()))
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, "<html>safe-home</html>")
        fallback.assert_called_once_with("/")

    def test_page_and_fallback_exception_returns_owned_503_not_raise(self):
        class HomeRequest:
            url = "https://public.example.test/"
            method = "GET"
        with (patch.object(self.entry, "preload_for_accepted_request", new_callable=AsyncMock, return_value={}),
              patch.object(self.entry, "dispatch_lightweight_home", side_effect=RuntimeError("boom")),
              patch.object(self.entry, "render_page_fallback", side_effect=RuntimeError("fallback-boom"))):
            response = asyncio.run(self.entry.Default().fetch(HomeRequest()))
        self.assertEqual(response.status, 503)
        self.assertEqual(response.body, "Public page temporarily unavailable")

    def test_handler_binding_never_selects_custom_provider(self):
        with patch.object(self.entry, "bind_public_today") as bind:
            self.entry._accepted_handler()
        self.assertEqual(bind.call_args.kwargs["api_base"], DEFAULT_API)


if __name__ == "__main__":
    unittest.main()
