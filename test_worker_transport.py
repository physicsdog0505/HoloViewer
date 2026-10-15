"""No-network transport tests; production renderer itself remains vendored."""
import json
import unittest
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler

from platform_adapter.worker_transport import dispatch_accepted_get


class AcceptedStyleFixture(BaseHTTPRequestHandler):
    """Exercise the real BaseHTTPRequestHandler header/wfile contract."""
    def do_GET(self):
        if self.path == "/":
            payload = b"<html><body><h1>accepted</h1></body></html>"
            content_type = "text/html; charset=utf-8"
            status = HTTPStatus.OK
        elif self.path == "/api/home":
            payload = json.dumps({"today_label": "2026/10/15", "html": "<p>ok</p>"}).encode()
            content_type = "application/json; charset=utf-8"
            status = HTTPStatus.OK
        elif self.path == "/history?date=invalid":
            payload = "無效的歷史日期或頁數。".encode()
            content_type = "text/html; charset=utf-8"
            status = HTTPStatus.BAD_REQUEST
        else:
            payload = b"not found"
            content_type = "text/html; charset=utf-8"
            status = HTTPStatus.NOT_FOUND
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


class TransportTest(unittest.TestCase):
    def test_accepted_html_and_json_and_query_route(self):
        for path, status, content_type in [
            ("/", 200, "text/html; charset=utf-8"),
            ("/api/home", 200, "application/json; charset=utf-8"),
            ("/history?date=invalid", 400, "text/html; charset=utf-8"),
        ]:
            with self.subTest(path=path):
                result = dispatch_accepted_get(AcceptedStyleFixture, target=path)
                self.assertEqual(result.status, status)
                headers = dict(result.headers)
                self.assertEqual(headers["Content-Type"], content_type)
                self.assertEqual(int(headers["Content-Length"]), len(result.body))
        result = dispatch_accepted_get(AcceptedStyleFixture, target="/api/home")
        self.assertEqual(json.loads(result.body)["today_label"], "2026/10/15")

    def test_no_socket_or_server_constructor_required(self):
        # The stdlib handler __init__ requires a socket; this adapter bypasses
        # it and executes only the already accepted do_GET route dispatcher.
        response = dispatch_accepted_get(AcceptedStyleFixture, target="/")
        self.assertIn(b"<h1>accepted</h1>", response.body)

    def test_reject_bad_target_and_non_get(self):
        with self.assertRaises(ValueError):
            dispatch_accepted_get(AcceptedStyleFixture, target="//evil.test/")
        with self.assertRaises(ValueError):
            dispatch_accepted_get(AcceptedStyleFixture, target="/hi\r\nInjected: bad")
        result = dispatch_accepted_get(AcceptedStyleFixture, target="/", method="POST")
        self.assertEqual(result.status, 405)
        self.assertEqual(dict(result.headers)["Allow"], "GET")


if __name__ == "__main__":
    unittest.main()
