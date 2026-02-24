"""Remote query helpers for the CLI."""

from typing import Any

import httpx

from services.api.app.chat import ChatResult
from services.api.app.retriever import QueryResult


def _query_remote(question: str, url: str, collection: str) -> Any:
    """Query a remote API and return a QueryResult-like object."""
    # Ensure URL ends with /v1/query if only base URL provided
    if not url.endswith("/v1/query"):
        url = url.rstrip("/") + "/v1/query"

    try:
        resp = httpx.post(
            url,
            json={"question": question, "collection": collection},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()

        return QueryResult(
            answer=data.get("answer", ""),
            citations=data.get("citations", []),
            retrieved=data.get("retrieved", 0),
            latency_ms=data.get("latency_ms", 0.0),
            mode=data.get("mode", "retrieval"),
            retrieval_confidence=float(data.get("retrieval_confidence", 0.0)),
            retrieval_confidence_label=str(
                data.get("retrieval_confidence_label", "low")
            ),
        )
    except Exception as exc:
        return QueryResult(
            answer=f"**Error querying remote API:** {exc}",
            mode="error",
        )


def _query_remote_with_auth(
    question: str,
    url: str,
    collection: str,
    *,
    api_key: str | None = None,
) -> Any:
    """Query remote API and include optional API key header."""
    if not url.endswith("/v1/query"):
        url = url.rstrip("/") + "/v1/query"

    headers = {"x-api-key": api_key} if api_key else None
    try:
        resp = httpx.post(
            url,
            json={"question": question, "collection": collection},
            headers=headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return QueryResult(
            answer=data.get("answer", ""),
            citations=data.get("citations", []),
            retrieved=data.get("retrieved", 0),
            latency_ms=data.get("latency_ms", 0.0),
            mode=data.get("mode", "retrieval"),
            retrieval_confidence=float(data.get("retrieval_confidence", 0.0)),
            retrieval_confidence_label=str(
                data.get("retrieval_confidence_label", "low")
            ),
        )
    except Exception as exc:
        return QueryResult(
            answer=f"**Error querying remote API:** {exc}",
            mode="error",
        )


def _chat_remote(
    question: str,
    url: str,
    collection: str,
    *,
    session_id: str | None = None,
    mode: str = "default",
    answer_style: str = "concise",
    top_k: int = 5,
    include_context: bool = False,
    include_ranking_signals: bool = False,
    api_key: str | None = None,
) -> Any:
    """Query remote chat endpoint and return a ChatResult-like object."""
    if not url.endswith("/v1/chat"):
        url = url.rstrip("/") + "/v1/chat"

    payload: dict[str, Any] = {
        "question": question,
        "collection": collection,
        "mode": mode,
        "answer_style": answer_style,
        "top_k": top_k,
        "include_context": include_context,
        "include_ranking_signals": include_ranking_signals,
    }
    if session_id:
        payload["session_id"] = session_id

    try:
        headers = {"x-api-key": api_key} if api_key else None
        resp = httpx.post(url, json=payload, headers=headers, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()

        return ChatResult(
            session_id=data.get("session_id", session_id or ""),
            answer=data.get("answer", ""),
            citations=data.get("citations", []),
            retrieved=data.get("retrieved", 0),
            latency_ms=data.get("latency_ms", 0.0),
            mode=data.get("mode", mode),
            turn_index=data.get("turn_index", 0),
            answer_style=data.get("answer_style", answer_style),
            context_snippets=data.get("context_snippets", []),
        )
    except Exception as exc:
        return ChatResult(
            session_id=session_id or "",
            answer=f"**Error querying remote chat API:** {exc}",
            mode="error",
            turn_index=0,
        )


def _feedback_remote(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Submit feedback to remote endpoint and return JSON response."""
    if not url.endswith("/v1/feedback"):
        url = url.rstrip("/") + "/v1/feedback"
    headers = {"x-api-key": api_key} if api_key else None
    resp = httpx.post(url, json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    return resp.json()
