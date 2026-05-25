#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from typing import Any

from rich.console import Console


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wikispeedrun import WikiClient, solve_auto

STATIC_DIR = ROOT / "web"


class NullConsole:
    def print(self, *args: Any, **kwargs: Any) -> None:
        return None


class SpeedrunHandler(BaseHTTPRequestHandler):
    server_version = "WikiSpeedrunWeb/0.1"

    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self.send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if self.path == "/styles.css":
            self.send_file(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
            return
        if self.path == "/app.js":
            self.send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/api/solve":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body or "{}")
            start = str(payload.get("start", "")).strip()
            target = str(payload.get("target", "")).strip()
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"ok": False, "error": f"Bad request: {exc}"}, HTTPStatus.BAD_REQUEST)
            return

        if not start or not target:
            self.send_json(
                {"ok": False, "error": "Both start and target articles are required."},
                HTTPStatus.BAD_REQUEST,
            )
            return

        client = WikiClient()
        client.clear_session()
        started = time.perf_counter()
        result, auto = solve_auto(
            client,
            start,
            target,
            console=NullConsole(),
        )
        elapsed = time.perf_counter() - started

        if result is None:
            self.send_json(
                {
                    "ok": True,
                    "found": False,
                    "elapsed": elapsed,
                    "fetches": client.network_fetches,
                    "auto": auto,
                }
            )
            return

        self.send_json(
            {
                "ok": True,
                "found": True,
                "path": [
                    {"title": title, "url": url}
                    for title, url in zip(result.path, result.urls, strict=False)
                ],
                "clicks": len(result.path) - 1,
                "elapsed": result.elapsed,
                "wallElapsed": elapsed,
                "fetches": client.network_fetches,
                "auto": auto,
            }
        )

    def send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        Console(stderr=True).print(f"[dim]{self.address_string()} - {format % args}[/dim]")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the Wikipedia Speedrun web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), SpeedrunHandler)
    Console().print(f"[bold]Wikipedia Speedrun UI[/bold] http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        Console().print("\n[yellow]Shutting down.[/yellow]")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
