"""Serve the investigation UI on localhost — stdlib only, no dependencies.

Serves ONLY ``ui.html`` (which is fully self-contained — data is embedded) and
binds to 127.0.0.1, so nothing else in the project directory (e.g. ``.env``) is
ever exposed. Any other path returns 404.

Usage:
  python -m src.build_ui         # (re)generate ui.html from the on-disk answers
  python -m src.serve_ui         # then open http://localhost:8000/ui.html
  python -m src.serve_ui 8080    # custom port
"""
from __future__ import annotations

import http.server
import socketserver
import sys
from pathlib import Path

UI = Path("ui.html")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path not in ("/", "/ui.html"):
            self.send_error(404, "only /ui.html is served")
            return
        if not UI.exists():
            self.send_error(404, "ui.html not found — run: python -m src.build_ui")
            return
        body = UI.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):  # keep the console quiet
        pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        print(f"Investigation UI -> http://localhost:{port}/ui.html   (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")


if __name__ == "__main__":
    main()

