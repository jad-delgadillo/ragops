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
ONBOARD_JOBS: dict[str, dict[str, Any]] = {}


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
                    "routes": [
                        "POST /v1/chat",
                        "POST /v1/feedback",
                        "POST /v1/repos/onboard",
                    ],
                    "sessions": len(SESSIONS),
                    "feedback_count": len(FEEDBACK),
                    "onboard_jobs": len(ONBOARD_JOBS),
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
        if self.path.endswith("/v1/repos/onboard"):
            self._handle_repo_onboard(payload)
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

    def _handle_repo_onboard(self, payload: dict[str, Any]) -> None:
        action = str(payload.get("action", "")).strip().lower()
        if action == "status":
            job_id = str(payload.get("job_id", "")).strip()
            if not job_id:
                self._json(400, {"error": "Field 'job_id' is required for action=status"})
                return
            job = ONBOARD_JOBS.get(job_id)
            if not job:
                self._json(404, {"error": f"Repo onboarding job not found: {job_id}"})
                return
            # Simulate progression: queued → running → succeeded
            current = job["status"]
            if current == "queued":
                job["status"] = "running"
            elif current == "running":
                job["status"] = "succeeded"
                job["result"] = {
                    "collection": job["collection"] + "_code",
                    "manuals_collection": job["collection"] + "_manuals",
                    "name": job["collection"],
                    "ingest": {"indexed_docs": 42, "skipped_docs": 3, "total_chunks": 256},
                    "manual_ingest": {"indexed_docs": 5, "skipped_docs": 0, "total_chunks": 18},
                }
            response: dict[str, Any] = {
                "status": job["status"],
                "job_id": job_id,
                "collection": job["collection"],
            }
            if job.get("result"):
                response["result"] = job["result"]
            if job.get("error"):
                response["error"] = job["error"]
            self._json(200, response)
            return

        repo_url = str(payload.get("repo_url", "")).strip()
        if not repo_url:
            self._json(400, {"error": "Field 'repo_url' is required"})
            return

        collection = str(payload.get("collection", "")).strip() or "mock-repo"
        is_async = payload.get("async", False)

        if is_async:
            job_id = str(uuid4())
            ONBOARD_JOBS[job_id] = {
                "status": "queued",
                "collection": collection,
                "repo_url": repo_url,
                "result": None,
                "error": None,
            }
            self._json(202, {
                "status": "queued",
                "job_id": job_id,
                "collection": collection,
            })
        else:
            self._json(200, {
                "status": "ok",
                "collection": collection + "_code",
                "manuals_collection": collection + "_manuals",
                "name": collection,
                "ingest": {"indexed_docs": 42, "skipped_docs": 3, "total_chunks": 256},
                "manual_ingest": {"indexed_docs": 5, "skipped_docs": 0, "total_chunks": 18},
            })

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
