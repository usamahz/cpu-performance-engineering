"""A local preview server: dist/ over HTTP, rebuilt when a source changes.
GitHub Pages behaviour is mirrored where it matters: directory URLs serve
index.html and unknown paths get 404.html."""

from __future__ import annotations

import functools
import http.server
import threading
import time
from pathlib import Path

from . import SITE_ROOT

WATCH = ("templates", "static", "cpu_perf_site", "copy.toml", "site.toml", "charts.toml")


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8",
                      ".json": "application/json", ".js": "text/javascript", ".woff2": "font/woff2",
                      ".svg": "image/svg+xml"}

    def send_error(self, code, message=None, explain=None):
        if code == 404:
            page = Path(self.directory) / "404.html"
            if page.is_file():
                body = page.read_bytes()
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        super().send_error(code, message, explain)

    def log_message(self, fmt, *args):  # quiet
        pass


def _mtime() -> float:
    newest = 0.0
    for name in WATCH:
        path = SITE_ROOT / name
        files = [path] if path.is_file() else path.rglob("*") if path.exists() else []
        for f in files:
            if f.is_file():
                newest = max(newest, f.stat().st_mtime)
    return newest


def serve(dist: Path, port: int, rebuild=None) -> None:
    if rebuild is not None:
        def watch():
            seen = _mtime()
            while True:
                time.sleep(1)
                now = _mtime()
                if now != seen:
                    seen = now
                    try:
                        rebuild()
                        print("rebuilt")
                    except Exception as exc:  # keep serving the last good build
                        print(f"rebuild failed: {exc}")

        threading.Thread(target=watch, daemon=True).start()
    handler = functools.partial(Handler, directory=str(dist))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"serving {dist} at http://127.0.0.1:{port}/")
        httpd.serve_forever()
