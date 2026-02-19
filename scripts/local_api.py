#!/usr/bin/env python3
"""Local HTTP API server wrapping the Lambda handler for frontend testing.

Usage:
    python scripts/local_api.py [--port 8090] [--host 127.0.0.1]

This serves the REAL RAG Ops API locally (not mock data), using your local
Postgres database and OpenAI key from .env. Point the frontend at this
server to get real answers with citations from onboarded repos.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# Ensure project root is on sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from services.api.app.handler import lambda_handler  # noqa: E402


class LocalAPIHandler(BaseHTTPRequestHandler):
    """Translates HTTP requests into Lambda events and returns the response."""

    server_version = "RagOpsLocal/1.0"

    def _build_event(self, method: str, body: str = "") -> dict[str, Any]:
        return {
            "httpMethod": method,
            "path": self.path,
            "rawPath": self.path,
            "headers": dict(self.headers),
            "body": body,
            "requestContext": {},
        }

    def _send_lambda_response(self, result: dict[str, Any]) -> None:
        status = result.get("statusCode", 200)
        body = result.get("body", "")
        headers = result.get("headers", {})

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for key, value in headers.items():
            if key.lower() not in {"content-type", "access-control-allow-origin"}:
                self.send_header(key, value)
        encoded = body.encode("utf-8") if isinstance(body, str) else body
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        event = self._build_event("GET")
        result = lambda_handler(event)
        self._send_lambda_response(result)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        event = self._build_event("POST", body)
        result = lambda_handler(event)
        self._send_lambda_response(result)

    def log_message(self, fmt: str, *args: Any) -> None:
        method = args[0] if args else ""
        status = args[1] if len(args) > 1 else ""
        print(f"  {method} → {status}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local HTTP server wrapping the RAG Ops Lambda handler"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    print("=" * 60)
    print("  RAG Ops Local API Server")
    print("=" * 60)
    print(f"  Listening on http://{args.host}:{args.port}")
    print(f"  Health:      http://{args.host}:{args.port}/health")
    print(f"  Chat:        POST http://{args.host}:{args.port}/v1/chat")
    print(f"  Onboard:     POST http://{args.host}:{args.port}/v1/repos/onboard")
    print("=" * 60)
    print("  Point your frontend API URL to this server for real answers.")
    print()

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((args.host, args.port), LocalAPIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
