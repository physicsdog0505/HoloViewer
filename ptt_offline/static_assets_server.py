"""Local-only HTTP emulator for the asset pilot's declarative headers."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class StaticAssetHandler(SimpleHTTPRequestHandler):
    def guess_type(self,path):
        if path.endswith(".json"):
            return "application/json"
        return super().guess_type(path)

    def end_headers(self):
        if "/chunks/" in self.path and self.path.endswith(".json"):
            self.send_header("Cache-Control","public, max-age=0, must-revalidate")
        elif "/manifests/" in self.path:
            self.send_header("Cache-Control","no-cache")
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("X-Content-Type-Options","nosniff")
        super().end_headers()


def main(argv=None):
    parser=argparse.ArgumentParser(description="Offline Static Assets header emulator")
    parser.add_argument("--root",required=True,type=Path)
    parser.add_argument("--port",required=True,type=int)
    args=parser.parse_args(argv)
    handler=partial(StaticAssetHandler,directory=str(args.root.resolve()))
    server=ThreadingHTTPServer(("127.0.0.1",args.port),handler)
    print(f"http://127.0.0.1:{server.server_port}",flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=="__main__":
    main()
