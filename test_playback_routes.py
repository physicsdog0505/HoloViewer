"""Custom-view transport coverage without changing 4174 markup or using PTT APIs."""
import sys
import types
import unittest
from unittest.mock import patch

from platform_adapter.playback_routes import playback_handler


class Base:
    def _html(self, body, status=200):
        self.result = (body, int(status))

    def do_GET(self):
        self.result = ("delegated", 200)


class PlaybackRoutesTests(unittest.TestCase):
    def setUp(self):
        custom = types.ModuleType("client_custom_view")
        home = types.ModuleType("client_home")
        self.calls = []
        home.load_home_streams = lambda: ([], [], [], [])
        custom.build_custom_view_html = lambda **kwargs: "original-builder"
        custom.custom_view_session_from_query = lambda streams, **kwargs: (tuple(streams), kwargs)
        def render(session, **kwargs):
            self.calls.append((session, kwargs))
            return "original-session"
        custom.build_custom_view_session_html = render
        self.modules = patch.dict(sys.modules, {"client_custom_view": custom, "client_home": home})
        self.modules.start()
        self.handler = playback_handler(Base).__new__(playback_handler(Base))

    def tearDown(self):
        self.modules.stop()

    def test_builder_uses_accepted_renderer(self):
        self.handler.path = "/custom-view"
        self.handler.do_GET()
        self.assertEqual(self.handler.result, ("original-builder", 200))

    def test_session_uses_accepted_renderer_with_empty_ptt_data(self):
        self.handler.path = "/custom-view/session?stream=dQw4w9WgXcQ&layout=auto&ptt=live"
        self.handler.do_GET()
        self.assertEqual(self.handler.result, ("original-session", 200))
        self.assertEqual(self.calls[0][1], {"show_live_ptt": True})

    def test_ptt_external_binding_cannot_be_used_in_playback_only(self):
        self.handler.path = "/custom-view/session?stream=dQw4w9WgXcQ&ptt_aid=someaid"
        self.handler.do_GET()
        self.assertEqual(self.handler.result[1], 400)
        self.assertFalse(self.calls)

if __name__ == "__main__":
    unittest.main()
