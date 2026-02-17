"""Lambda handler for Query API (query/chat/feedback + health)."""

from __future__ import annotations

import json
import logging
from typing import Any

from services.api.app.access import AccessDecision, authorize
from services.api.app.chat import (
    ChatResult,
    chat,
    normalize_answer_style,
    normalize_chat_mode,
)
from services.api.app.retriever import QueryResult, query
from services.core.config import get_settings
from services.core.database import (
    ensure_feedback_table,
    get_connection,
    health_check,
    insert_feedback,
    validate_embedding_dimension,
)
from services.core.logging import set_request_id, setup_logging
from services.core.providers import get_embedding_provider, get_llm_provider

logger = logging.getLogger(__name__)
COMMON_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, X-API-Key",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """AWS Lambda entry point for query API.

    Routes:
        POST /v1/query  → query handler
        POST /v1/chat   → conversational query handler
        POST /v1/feedback → answer quality feedback
        GET  /health    → health check
    """
    settings = get_settings()
    setup_logging(settings.log_level)
    set_request_id(event.get("requestContext", {}).get("requestId"))

    # Determine route
    path = event.get("path", event.get("rawPath", ""))
    request_ctx = event.get("requestContext", {})
    method = event.get("httpMethod", request_ctx.get("http", {}).get("method", ""))

    if method == "OPTIONS":
        return {
            "statusCode": 204,
            "headers": COMMON_CORS_HEADERS,
            "body": "",
        }

    if path == "/" or path == "":
        return _with_cors(
            {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Welcome to RAG Ops API!",
                    "endpoints": {
                        "health": "GET /health",
                        "query": "POST /v1/query",
                        "chat": "POST /v1/chat",
                        "feedback": "POST /v1/feedback",
                        "ingest": "POST /v1/ingest",
                    },
                    "documentation": "See USER_GUIDE.md for usage details.",
                }
            ),
        }
        )

    if path == "/health" or path.endswith("/health"):
        return _with_cors(_handle_health())

    if method == "POST" and ("/v1/query" in path or not path):
        return _with_cors(_handle_query(event))
    if method == "POST" and "/v1/chat" in path:
        return _with_cors(_handle_chat(event))
    if method == "POST" and "/v1/feedback" in path:
        return _with_cors(_handle_feedback(event))

    return _with_cors(
        {
        "statusCode": 404,
        "body": json.dumps({"error": f"Not found: {method} {path}"}),
    }
    )


def _handle_health() -> dict[str, Any]:
    """Health check endpoint."""
    settings = get_settings()
    result: dict[str, str] = {"status": "ok"}

    # DB check
    try:
        conn = get_connection(settings)
        db_health = health_check(conn)
        conn.close()
        result.update(db_health)
    except Exception as exc:
        result["db"] = f"error: {exc}"
        result["status"] = "degraded"

    # Embedding provider check (configuration + schema compatibility)
    try:
        provider = get_embedding_provider(settings)
        if result.get("db") == "ok":
            conn = get_connection(settings)
            try:
                validate_embedding_dimension(conn, provider.dimension)
            finally:
                conn.close()
        result["embed"] = "ok"
    except Exception as exc:
        result["embed"] = f"error: {exc}"
        result["status"] = "degraded"

    status_code = 200 if result["status"] == "ok" else 503
    return {
        "statusCode": status_code,
        "body": json.dumps(result),
    }


def _handle_query(event: dict[str, Any]) -> dict[str, Any]:
    """Handle POST /v1/query."""
    settings = get_settings()

    try:
        body = json.loads(event.get("body", "{}")) if isinstance(event.get("body"), str) else event
        question = body.get("question", "").strip()
        collection = body.get("collection", "default")

        if not question:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Field 'question' is required"}),
            }

        # Input validation
        if len(question) > 2000:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Question exceeds 2000 character limit"}),
            }

        decision = _authorize(event, action="query", collection=collection)
        if not decision.allowed:
            return _forbidden(decision)

        # Build providers
        embed_provider = get_embedding_provider(settings)
        llm_provider = get_llm_provider(settings)

        # Execute query
        result: QueryResult = query(
            question=question,
            embedding_provider=embed_provider,
            llm_provider=llm_provider,
            collection=collection,
            top_k=settings.top_k,
            settings=settings,
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "answer": result.answer,
                    "citations": result.citations,
                    "latency_ms": round(result.latency_ms, 1),
                    "retrieved": result.retrieved,
                    "mode": result.mode,
                    "principal": decision.principal,
                }
            ),
        }

    except Exception as exc:
        logger.exception("Query handler error")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc)}),
        }


def _handle_chat(event: dict[str, Any]) -> dict[str, Any]:
    """Handle POST /v1/chat."""
    settings = get_settings()

    try:
        body = json.loads(event.get("body", "{}")) if isinstance(event.get("body"), str) else event
        question = body.get("question", "").strip()
        collection = body.get("collection", "default")
        session_id = body.get("session_id")
        mode = body.get("mode", "default")
        answer_style = body.get("answer_style", "concise")
        include_context = bool(body.get("include_context", False))
        top_k = int(body.get("top_k", settings.top_k))

        if not question:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Field 'question' is required"}),
            }
        if len(question) > 2000:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Question exceeds 2000 character limit"}),
            }
        if top_k <= 0 or top_k > 50:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Field 'top_k' must be between 1 and 50"}),
            }

        decision = _authorize(event, action="chat", collection=collection)
        if not decision.allowed:
            return _forbidden(decision)

        selected_mode = normalize_chat_mode(mode)
        selected_answer_style = normalize_answer_style(answer_style)
        embed_provider = get_embedding_provider(settings)
        llm_provider = get_llm_provider(settings)

        result: ChatResult = chat(
            question=question,
            embedding_provider=embed_provider,
            llm_provider=llm_provider,
            session_id=session_id,
            mode=selected_mode,
            answer_style=selected_answer_style,
            collection=collection,
            top_k=top_k,
            settings=settings,
        )

        payload: dict[str, Any] = {
            "session_id": result.session_id,
            "answer": result.answer,
            "citations": result.citations,
            "latency_ms": round(result.latency_ms, 1),
            "retrieved": result.retrieved,
            "mode": result.mode,
            "answer_style": result.answer_style,
            "turn_index": result.turn_index,
            "principal": decision.principal,
        }
        if include_context:
            payload["context_snippets"] = result.context_snippets

        return {
            "statusCode": 200,
            "body": json.dumps(payload),
        }
    except ValueError as exc:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": str(exc)}),
        }
    except Exception as exc:
        logger.exception("Chat handler error")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc)}),
        }


def _handle_feedback(event: dict[str, Any]) -> dict[str, Any]:
    """Handle POST /v1/feedback."""
    settings = get_settings()
    try:
        body = json.loads(event.get("body", "{}")) if isinstance(event.get("body"), str) else event
        verdict = str(body.get("verdict", "")).strip().lower()
        collection = str(body.get("collection", "default")).strip() or "default"
        session_id = body.get("session_id")
        mode = str(body.get("mode", "default")).strip() or "default"
        question = body.get("question")
        answer = body.get("answer")
        comment = body.get("comment")
        citations = body.get("citations", [])
        metadata = body.get("metadata", {})

        if verdict not in {"positive", "negative"}:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Field 'verdict' must be 'positive' or 'negative'"}),
            }
        if comment is not None and len(str(comment)) > 4000:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Field 'comment' exceeds 4000 characters"}),
            }
        if question is not None and len(str(question)) > 4000:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Field 'question' exceeds 4000 characters"}),
            }
        if answer is not None and len(str(answer)) > 12000:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Field 'answer' exceeds 12000 characters"}),
            }

        decision = _authorize(event, action="feedback", collection=collection)
        if not decision.allowed:
            return _forbidden(decision)

        conn = get_connection(settings)
        try:
            ensure_feedback_table(conn)
            feedback_id = insert_feedback(
                conn,
                verdict=verdict,
                collection=collection,
                mode=mode,
                session_id=session_id,
                question=str(question) if question is not None else None,
                answer=str(answer) if answer is not None else None,
                comment=str(comment) if comment is not None else None,
                citations=citations if isinstance(citations, list) else [],
                metadata=metadata if isinstance(metadata, dict) else {},
            )
        finally:
            conn.close()

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "status": "ok",
                    "feedback_id": feedback_id,
                    "principal": decision.principal,
                    "collection": collection,
                }
            ),
        }
    except Exception as exc:
        logger.exception("Feedback handler error")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc)}),
        }


def _authorize(event: dict[str, Any], *, action: str, collection: str) -> AccessDecision:
    """Authorize request for action/collection."""
    settings = get_settings()
    headers = event.get("headers", {}) if isinstance(event.get("headers"), dict) else {}
    return authorize(
        settings=settings,
        headers=headers,
        action=action,
        collection=collection,
    )


def _forbidden(decision: AccessDecision) -> dict[str, Any]:
    """Build a 403 response from failed authorization decision."""
    return {
        "statusCode": 403,
        "body": json.dumps({"error": decision.reason or "Forbidden"}),
    }


def _with_cors(response: dict[str, Any]) -> dict[str, Any]:
    """Attach common CORS headers to response dict."""
    headers = dict(response.get("headers", {}))
    headers.update(COMMON_CORS_HEADERS)
    response["headers"] = headers
    return response


# ---------------------------------------------------------------------------
# CLI entry point for local dev
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point: python -m services.api.app.handler"""
    import argparse

    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table

    parser = argparse.ArgumentParser(description="RAG Ops Query CLI")
    parser.add_argument("question", help="Question to ask")
    parser.add_argument("--collection", default="default", help="Collection name")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    settings = get_settings()
    # Suppress JSON logs in CLI mode for cleaner output
    if not args.json:
        setup_logging("ERROR")
    else:
        setup_logging(settings.log_level)

    embed_provider = get_embedding_provider(settings)
    llm_provider = get_llm_provider(settings)

    # Execute query with loading spinner (only in non-JSON mode)
    if not args.json:
        from rich.console import Console

        console = Console()
        with console.status(
            "[bold cyan]Processing query...[/bold cyan]",
            spinner="dots",
        ):
            result = query(
                question=args.question,
                embedding_provider=embed_provider,
                llm_provider=llm_provider,
                collection=args.collection,
                top_k=args.top_k,
                settings=settings,
            )
    else:
        result = query(
            question=args.question,
            embedding_provider=embed_provider,
            llm_provider=llm_provider,
            collection=args.collection,
            top_k=args.top_k,
            settings=settings,
        )

    # JSON output mode
    if args.json:
        print(
            json.dumps(
                {
                    "answer": result.answer,
                    "citations": result.citations,
                    "latency_ms": round(result.latency_ms, 1),
                    "retrieved": result.retrieved,
                    "mode": result.mode,
                },
                indent=2,
            )
        )
        return

    # Rich formatted output
    console = Console()

    # Answer section
    console.print()
    console.print(
        Panel(
            Markdown(result.answer),
            title=f"[bold cyan]Answer[/bold cyan] [dim]({result.mode} mode)[/dim]",
            border_style="cyan",
        )
    )

    # Citations table
    if result.citations:
        console.print()

        # Use compact list format for narrow terminals
        if console.width < 80:
            console.print("[bold magenta]📚 Citations:[/bold magenta]")
            for i, cite in enumerate(result.citations, 1):
                source = cite.get("source", "unknown").split("/")[-1]
                line_range = f"{cite.get('line_start', '?')}-{cite.get('line_end', '?')}"
                similarity = f"{cite.get('similarity', 0):.1%}"
                console.print(
                    f"  [dim]{i}.[/dim] [cyan]{source}[/cyan] "
                    f"[yellow]L{line_range}[/yellow] [green]{similarity}[/green]"
                )
        else:
            # Full table for wider terminals
            table = Table(
                title="📚 Citations",
                show_header=True,
                header_style="bold magenta",
                expand=False,
            )
            table.add_column("#", style="dim", width=3, no_wrap=True)
            table.add_column("Source", style="cyan", min_width=15, max_width=30)
            table.add_column("Lines", justify="center", style="yellow", width=8, no_wrap=True)
            table.add_column("Score", justify="right", style="green", width=7, no_wrap=True)

            for i, cite in enumerate(result.citations, 1):
                source = cite.get("source", "unknown")
                source_short = source.split("/")[-1] if "/" in source else source
                line_range = f"{cite.get('line_start', '?')}-{cite.get('line_end', '?')}"
                similarity = f"{cite.get('similarity', 0):.1%}"
                table.add_row(str(i), source_short, line_range, similarity)

            console.print(table)

    # Metrics footer
    console.print()
    console.print(f"[dim]Retrieved {result.retrieved} chunks in {result.latency_ms:.0f}ms[/dim]")
    console.print()


if __name__ == "__main__":
    main()
