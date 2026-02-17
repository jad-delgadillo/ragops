#!/usr/bin/env python3
"""Small mock API for frontend smoke testing (/v1/chat + /v1/feedback)."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

SESSIONS: dict[str, list[dict[str, Any]]] = {}
FEEDBACK: list[dict[str, Any]] = []


class Handler(BaseHTTPRequestHandler):
    server_version = "RagOpsMock/1.0"

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/" or self.path == "/health":
            self._json(
                200,
                {
                    "status": "ok",
                    "service": "mock-chat-api",
                    "routes": ["POST /v1/chat", "POST /v1/feedback"],
                    "sessions": len(SESSIONS),
                    "feedback_count": len(FEEDBACK),
                },
            )
            return
        self._json(404, {"error": f"Not found: {self.path}"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._json(400, {"error": "Invalid JSON"})
            return

        if self.path.endswith("/v1/chat"):
            self._handle_chat(payload)
            return
        if self.path.endswith("/v1/feedback"):
            self._handle_feedback(payload)
            return
        self._json(404, {"error": f"Not found: {self.path}"})

    def _handle_chat(self, payload: dict[str, Any]) -> None:
        question = str(payload.get("question", "")).strip()
        if not question:
            self._json(400, {"error": "Field 'question' is required"})
            return

        session_id = str(payload.get("session_id", "")).strip() or str(uuid4())
        collection = str(payload.get("collection", "default"))
        mode = str(payload.get("mode", "default"))
        turn_index = len(SESSIONS.get(session_id, [])) + 1

        answer = (
            f"Mock answer (mode={mode}) for collection '{collection}'.\n"
            f"Question: {question}\n\n"
            "Next onboarding step: open services/cli/main.py and trace cmd_chat()."
        )
        citations = [
            {
                "source": "services/cli/main.py",
                "line_start": 260,
                "line_end": 420,
                "similarity": 0.91,
            }
        ]

        SESSIONS.setdefault(session_id, []).append(
            {
                "question": question,
                "answer": answer,
                "mode": mode,
                "collection": collection,
            }
        )

        self._json(
            200,
            {
                "session_id": session_id,
                "answer": answer,
                "citations": citations,
                "latency_ms": 42.0,
                "retrieved": len(citations),
                "mode": mode,
                "turn_index": turn_index,
                "principal": "mock-client",
            },
        )

    def _handle_feedback(self, payload: dict[str, Any]) -> None:
        verdict = str(payload.get("verdict", "")).strip().lower()
        if verdict not in {"positive", "negative"}:
            self._json(400, {"error": "Field 'verdict' must be 'positive' or 'negative'"})
            return

        feedback_id = len(FEEDBACK) + 1
        row = dict(payload)
        row["id"] = feedback_id
        FEEDBACK.append(row)
        self._json(
            200,
            {
                "status": "ok",
                "feedback_id": feedback_id,
                "principal": "mock-client",
                "collection": payload.get("collection", "default"),
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock /v1/chat + /v1/feedback API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Mock API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
