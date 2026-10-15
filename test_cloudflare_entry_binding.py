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

    def test_home_uses_lightweight_dispatch_without_binding_full_client_app(self):
        with (patch.object(self.entry, "bind_public_today") as bind,
              patch.object(self.entry, "preload_for_accepted_request", new_callable=AsyncMock, return_value={}),
              patch.object(self.entry, "dispatch_lightweight_home", return_value=TransportResponse(
                  200, (("Content-Type", "application/json"),), b"{}"
              )) as dispatch,
              patch.object(self.entry, "dispatch_accepted_get") as accepted):
            response = asyncio.run(self.entry.Default().fetch(FakeRequest()))
            self.assertEqual(response.status, 200)
            asyncio.run(self.entry.Default().fetch(FakeRequest()))
        bind.assert_not_called()
        accepted.assert_not_called()
        self.assertEqual(dispatch.call_count, 2)

    def test_binding_failure_keeps_runtime_unbound(self):
        with patch.object(self.entry, "bind_public_today", side_effect=ValueError("unavailable")):
            with self.assertRaises(ValueError):
                self.entry._accepted_handler()
        self.assertFalse(self.entry._bound)

    def test_ptt_page_is_page_first_without_provider_or_dispatch(self):
        class PttRequest:
            url = "https://public.example.test/ptt-today"
            method = "GET"
        with (patch.object(self.entry, "bind_public_today") as bind,
              patch.object(self.entry, "render_page_fallback", return_value=(200, "<html>ptt-shell</html>")) as fallback,
              patch.object(self.entry, "dispatch_accepted_get") as dispatch,
              patch.object(self.entry, "preload_for_accepted_request") as preload):
            response = asyncio.run(self.entry.Default().fetch(PttRequest()))
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, "<html>ptt-shell</html>")
        fallback.assert_called_once_with("/ptt-today")
        bind.assert_not_called()
        dispatch.assert_not_called()
        preload.assert_not_called()

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

    def test_custom_view_landing_uses_canonical_preload_and_accepted_dispatch(self):
        for route in ("/custom-view",):
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

    def test_collab_data_routes_use_canonical_preload_and_accepted_dispatch(self):
        routes = (
            "/collab",
            "/api/collab/live?collab=ark&stream=dQw4w9WgXcQ",
        )
        fake_handler = type("AcceptedHandler", (), {})
        for route in routes:
            with self.subTest(route=route):
                class CollabRequest:
                    url = "https://public.example.test" + route
                    method = "GET"
                with (patch.object(self.entry, "preload_for_accepted_request", new_callable=AsyncMock, return_value={}) as preload,
                      patch.object(self.entry, "_accepted_handler", return_value=fake_handler) as accepted,
                      patch.object(self.entry, "dispatch_accepted_get", return_value=TransportResponse(
                          200, (("Content-Type", "text/html"),), b"<html></html>"
                      )) as dispatch):
                    response = asyncio.run(self.entry.Default().fetch(CollabRequest()))
                self.assertEqual(response.status, 200)
                self.assertEqual(preload.await_args.args[0], route)
                accepted.assert_called_once_with()
                self.assertEqual(dispatch.call_args.kwargs["target"], route)

    def test_page_only_routes_render_fallback_without_provider(self):
        for route in (
            "/ptt-today",
            "/watchalong",
            "/watchalong/session",
            "/custom-view/session?stream=dQw4w9WgXcQ&stream=abcdefghijk",
            "/collab/session?collab=shared-topic&stream=dQw4w9WgXcQ&stream=abcdefghijk",
        ):
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
        self.assertEqual(response.headers["X-HoloViewer-Recovered-Stage"], "home-render")
        fallback.assert_called_once_with("/")

    def test_response_build_exception_falls_back_instead_of_1101(self):
        class HomeRequest:
            url = "https://public.example.test/"
            method = "GET"

        original_response = self.entry.Response
        calls = {"n": 0}

        def flaky_response(body, *, status=200, headers=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TypeError("bridge failure")
            return original_response(body, status=status, headers=headers)

        with (patch.object(self.entry, "preload_for_accepted_request", new_callable=AsyncMock, return_value={}),
              patch.object(self.entry, "dispatch_lightweight_home", return_value=TransportResponse(
                  200, (("Content-Type", "text/html"),), b"<html>home</html>"
              )),
              patch.object(self.entry, "render_page_fallback", return_value=(200, "<html>safe-home</html>")),
              patch.object(self.entry, "Response", side_effect=flaky_response)):
            response = asyncio.run(self.entry.Default().fetch(HomeRequest()))

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, "<html>safe-home</html>")
        self.assertEqual(response.headers["X-HoloViewer-Recovered-Stage"], "response-build")

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
        self.assertEqual(response.headers["X-HoloViewer-Recovered-Stage"], "home-render")

    def test_handler_binding_never_selects_custom_provider(self):
        with patch.object(self.entry, "bind_public_today") as bind:
            self.entry._accepted_handler()
        self.assertEqual(bind.call_args.kwargs["api_base"], DEFAULT_API)


if __name__ == "__main__":
    unittest.main()
