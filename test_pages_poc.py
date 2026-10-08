"""Safety and static-route PoC checks; no live backend required."""
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parent

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links=[]
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag in {"a","script","link","img","iframe"}:
            self.links.append((tag,d.get("href") or d.get("src") or ""))

class PagesPoC(unittest.TestCase):
    def test_routes_and_pages(self):
        for path in ("index.html","custom-view/index.html","custom-view/session/index.html","watchalong/index.html","ptt-today/index.html"):
            html=(ROOT/path).read_text(encoding="utf-8")
            self.assertIn("<!doctype html>",html.lower())
            self.assertIn("client-rail",html)
            self.assertIn("viewport",html)
            self.assertNotIn("hololive_ptt.sqlite3",html)
            self.assertNotIn("127.0.0.1",html)
            self.assertNotIn("AIza",html)
            parser=Links()
            parser.feed(html)
            for tag,link in parser.links:
                if tag=="a":
                    self.assertFalse(link.startswith("/"),(path,link))
                if tag in {"script","link"}:
                    self.assertFalse(link.startswith(("http:","https:","/")),(path,link))
    def test_custom_view_poc(self):
        form=(ROOT/"custom-view/index.html").read_text(encoding="utf-8")
        session=(ROOT/"custom-view/session/index.html").read_text(encoding="utf-8")
        self.assertIn("URLSearchParams",form)
        self.assertIn("session/?",form)
        client=(ROOT/"assets/cloud-client.js").read_text(encoding="utf-8")
        self.assertIn("youtube-nocookie.com/embed/",client)
        self.assertIn("URLSearchParams(location.search)",client)
        self.assertIn("assets/cloud-client.js",session)
        self.assertNotIn("fetch(",form)
    def test_home_uses_client_style(self):
        html=(ROOT/"index.html").read_text(encoding="utf-8")
        for item in ("home-wide","stream-filter","client-grid","stream-card","live-channel-rail","--rail-collapsed","--content","@media"):
            self.assertIn(item,html)
        self.assertIn("data:image/svg+xml",html)
        self.assertIn('data-cloud-page="home"',html)
        self.assertIn('id="homeDynamic"',html)
        self.assertIn("現在直播中",html)

    def test_cloud_data_contract_is_bounded_and_read_only(self):
        client=(ROOT/"assets/cloud-client.js").read_text(encoding="utf-8")
        for token in ('credentials: "omit"', "AbortController", "MAX_JSON_BYTES", "TextDecoder", 'cache: "no-store"'):
            self.assertIn(token,client)
        for forbidden in ("localStorage", "document.cookie", "Authorization", "POST", "PUT", "DELETE", "127.0.0.1", "localhost"):
            self.assertNotIn(forbidden,client)
        import json
        for path in ("public-data/config.json","public-data/demo/home.json","public-data/demo/ptt.json","public-data/demo/watchalong.json"):
            self.assertEqual(json.loads((ROOT/path).read_text(encoding="utf-8"))["schema_version"],1)

if __name__=="__main__":
    unittest.main()
