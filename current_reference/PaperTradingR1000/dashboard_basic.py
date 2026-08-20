"""Small local status dashboard."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import html
import json

from dashboard_v2_utils import get_dashboard_sections


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        sections = get_dashboard_sections()
        body = "".join(
            f"<h2>{html.escape(str(section['title']))}</h2><pre>{html.escape(json.dumps(section['content'], indent=2, default=str))}</pre>"
            for section in sections
        )
        payload = f"<html><head><title>TradingbotR1000</title></head><body><h1>TradingbotR1000</h1>{body}</body></html>"
        data = payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    server = HTTPServer(("127.0.0.1", 8088), Handler)
    print("TradingbotR1000 dashboard: http://127.0.0.1:8088")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
