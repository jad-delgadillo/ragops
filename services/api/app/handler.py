"""Lambda handler for Query API (query/chat/feedback + health)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from uuid import uuid4

try:
    import boto3
except Exception:  # pragma: no cover - boto3 exists in Lambda runtime
    boto3 = None

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
    create_repo_onboarding_job,
    ensure_feedback_table,
    ensure_repo_onboarding_jobs_table,
    get_connection,
    get_repo_onboarding_job,
    health_check,
    insert_feedback,
    mark_repo_onboarding_job_failed,
    mark_repo_onboarding_job_running,
    mark_repo_onboarding_job_succeeded,
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

try:
    from services.api.app.repo_onboarding import onboard_github_repo, onboard_github_repo_lazy
except Exception:  # pragma: no cover - lazy fallback when optional deps are absent
    onboard_github_repo = None
    onboard_github_repo_lazy = None


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """AWS Lambda entry point for query API.

    Routes:
        POST /v1/query  → query handler
        POST /v1/chat   → conversational query handler
        POST /v1/feedback → answer quality feedback
        POST /v1/repos/onboard → clone/index GitHub repo into collections
        GET  /health    → health check
    """
    settings = get_settings()
    setup_logging(settings.log_level)
    set_request_id(event.get("requestContext", {}).get("requestId"))

    if event.get("internal_action") == "repo_onboard_job":
        return _handle_repo_onboard_job_event(event)

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
                        "repo_onboard": "POST /v1/repos/onboard",
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
    if method == "POST" and "/v1/repos/onboard" in path:
        return _with_cors(_handle_repo_onboard(event))

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


def _as_bool(value: Any, *, default: bool = False) -> bool:
    """Normalize booleans from JSON payload values."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _handle_repo_onboard(event: dict[str, Any]) -> dict[str, Any]:
    """Handle POST /v1/repos/onboard."""
    settings = get_settings()
    if not settings.repo_onboarding_enabled:
        return {
            "statusCode": 403,
            "body": json.dumps(
                {
                    "error": (
                        "Repo onboarding endpoint is disabled. "
                        "Set REPO_ONBOARDING_ENABLED=true."
                    ),
                }
            ),
        }
    if not settings.api_auth_enabled and settings.environment.lower() not in {"local"}:
        return {
            "statusCode": 403,
            "body": json.dumps(
                {
                    "error": (
                        "Repo onboarding requires API key auth outside local mode. "
                        "Set API_AUTH_ENABLED=true and provide X-API-Key."
                    ),
                }
            ),
        }

    try:
        body = json.loads(event.get("body", "{}")) if isinstance(event.get("body"), str) else event
        action = str(body.get("action", "")).strip().lower()
        if action == "status":
            return _handle_repo_onboard_status(event, body, settings)

        repo_url = str(body.get("repo_url", "")).strip()
        if not repo_url:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Field 'repo_url' is required"}),
            }
        if len(repo_url) > 500:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Field 'repo_url' exceeds 500 characters"}),
            }

        collection = str(body.get("collection", "")).strip() or "default"
        decision = _authorize(event, action="repo_manage", collection=collection)
        if not decision.allowed:
            return _forbidden(decision)

        lazy_mode = _as_bool(body.get("lazy"), default=True)
        request_payload = {
            "repo_url": repo_url,
            "ref": str(body.get("ref", "")).strip() or None,
            "name": str(body.get("name", "")).strip() or None,
            "collection": collection,
            "manuals_collection": str(body.get("manuals_collection", "")).strip() or None,
            "generate_manuals": _as_bool(body.get("generate_manuals"), default=True),
            "reset_code_collection": _as_bool(body.get("reset_code_collection"), default=True),
            "reset_manuals_collection": _as_bool(
                body.get("reset_manuals_collection"),
                default=True,
            ),
            "lazy": lazy_mode,
        }
        async_requested = _as_bool(
            body.get("async"),
            default=settings.environment.lower() not in {"local"},
        )
        if async_requested:
            requested_job_id = str(body.get("job_id", "")).strip()
            if requested_job_id and len(requested_job_id) > 64:
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": "Field 'job_id' exceeds 64 characters"}),
                }
            job_id = requested_job_id or str(uuid4())
            conn = get_connection(settings)
            try:
                ensure_repo_onboarding_jobs_table(conn)
                create_repo_onboarding_job(
                    conn,
                    job_id=job_id,
                    collection=collection,
                    principal=decision.principal,
                    request_payload=request_payload,
                )
            finally:
                conn.close()

            dispatched = _dispatch_repo_onboard_job(job_id=job_id, settings=settings)
            if not dispatched:
                if settings.environment.lower() not in {"local"}:
                    return {
                        "statusCode": 500,
                        "body": json.dumps(
                            {
                                "error": (
                                    "Failed to dispatch onboarding worker. "
                                    "Check Lambda invoke permissions and worker function name."
                                )
                            }
                        ),
                    }
                outcome = _run_repo_onboard_job(job_id=job_id, settings=settings)
                if outcome["status"] == "succeeded":
                    payload = dict(outcome.get("result", {}))
                    payload.update(
                        {
                            "status": "ok",
                            "principal": decision.principal,
                            "job_id": job_id,
                        }
                    )
                    return {
                        "statusCode": 200,
                        "body": json.dumps(payload),
                    }
                return {
                    "statusCode": 500,
                    "body": json.dumps({"error": outcome.get("error", "Onboarding failed")}),
                }

            return {
                "statusCode": 202,
                "body": json.dumps(
                    {
                        "status": "queued",
                        "job_id": job_id,
                        "collection": collection,
                        "principal": decision.principal,
                    }
                ),
            }

        result = _execute_repo_onboard(request_payload=request_payload, settings=settings)
        payload = result.to_dict()
        payload.update({"status": "ok", "principal": decision.principal})
        return {"statusCode": 200, "body": json.dumps(payload)}
    except ValueError as exc:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": str(exc)}),
        }
    except Exception as exc:
        logger.exception("Repo onboarding handler error")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc)}),
        }


def _handle_repo_onboard_status(
    event: dict[str, Any],
    body: dict[str, Any],
    settings: Any,
) -> dict[str, Any]:
    """Handle POST /v1/repos/onboard with action=status."""
    job_id = str(body.get("job_id", "")).strip()
    if not job_id:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Field 'job_id' is required for action=status"}),
        }

    conn = get_connection(settings)
    try:
        ensure_repo_onboarding_jobs_table(conn)
        job = get_repo_onboarding_job(conn, job_id=job_id)
    finally:
        conn.close()

    if not job:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": f"Repo onboarding job not found: {job_id}"}),
        }

    collection = str(job.get("collection", "default") or "default")
    decision = _authorize(event, action="repo_manage", collection=collection)
    if not decision.allowed:
        return _forbidden(decision)

    payload: dict[str, Any] = {
        "status": str(job.get("status", "unknown")),
        "job_id": job_id,
        "collection": collection,
        "principal": decision.principal,
        "error": job.get("error"),
        "created_at": str(job.get("created_at")) if job.get("created_at") else None,
        "started_at": str(job.get("started_at")) if job.get("started_at") else None,
        "finished_at": str(job.get("finished_at")) if job.get("finished_at") else None,
    }
    result = job.get("result")
    if isinstance(result, dict) and result:
        payload["result"] = result
    return {
        "statusCode": 200,
        "body": json.dumps(payload),
    }


def _execute_repo_onboard(*, request_payload: dict[str, Any], settings: Any) -> Any:
    """Run repo onboarding synchronously and return result.

    Supports both lazy (file-tree-only) and full (clone + embed) modes.
    """
    lazy = bool(request_payload.get("lazy", True))

    if lazy:
        lazy_fn = onboard_github_repo_lazy
        if lazy_fn is None:
            from services.api.app.repo_onboarding import (
                onboard_github_repo_lazy as lazy_fn,
            )
        return lazy_fn(
            repo_url=str(request_payload.get("repo_url", "")).strip(),
            settings=settings,
            ref=request_payload.get("ref"),
            name=request_payload.get("name"),
            collection=request_payload.get("collection"),
        )

    onboard_fn = onboard_github_repo
    if onboard_fn is None:
        from services.api.app.repo_onboarding import onboard_github_repo as onboard_fn

    return onboard_fn(
        repo_url=str(request_payload.get("repo_url", "")).strip(),
        settings=settings,
        ref=request_payload.get("ref"),
        name=request_payload.get("name"),
        collection=request_payload.get("collection"),
        manuals_collection=request_payload.get("manuals_collection"),
        generate_manuals=bool(request_payload.get("generate_manuals", True)),
        reset_code_collection=bool(request_payload.get("reset_code_collection", True)),
        reset_manuals_collection=bool(request_payload.get("reset_manuals_collection", True)),
    )


def _resolve_repo_onboard_worker_function(settings: Any) -> str:
    """Resolve Lambda function name that should process onboarding jobs."""
    override = os.getenv("REPO_ONBOARDING_WORKER_FUNCTION", "").strip()
    if override:
        return override
    current = os.getenv("AWS_LAMBDA_FUNCTION_NAME", "").strip()
    if current.endswith("-query"):
        return f"{current[:-6]}-ingest"
    return ""


def _dispatch_repo_onboard_job(*, job_id: str, settings: Any) -> bool:
    """Dispatch onboarding job to worker Lambda asynchronously."""
    worker_function = _resolve_repo_onboard_worker_function(settings)
    if not worker_function or boto3 is None:
        return False
    try:
        client = boto3.client("lambda", region_name=settings.aws_region or None)
        client.invoke(
            FunctionName=worker_function,
            InvocationType="Event",
            Payload=json.dumps(
                {
                    "internal_action": "repo_onboard_job",
                    "job_id": job_id,
                }
            ).encode("utf-8"),
        )
        return True
    except Exception:
        logger.exception("Failed to dispatch repo onboarding job to worker Lambda")
        return False


def _run_repo_onboard_job(*, job_id: str, settings: Any) -> dict[str, Any]:
    """Execute an already queued repo onboarding job and persist status."""
    conn = get_connection(settings)
    try:
        ensure_repo_onboarding_jobs_table(conn)
        job = get_repo_onboarding_job(conn, job_id=job_id)
        if not job:
            return {"status": "failed", "error": f"Job not found: {job_id}", "job_id": job_id}
        status = str(job.get("status", ""))
        if status == "succeeded":
            return {"status": "succeeded", "job_id": job_id, "result": job.get("result")}
        if status == "running":
            return {"status": "running", "job_id": job_id}
        mark_repo_onboarding_job_running(conn, job_id=job_id)
        request_payload = job.get("request_payload")
    finally:
        conn.close()

    if not isinstance(request_payload, dict):
        error = "Stored request payload is invalid"
        conn = get_connection(settings)
        try:
            ensure_repo_onboarding_jobs_table(conn)
            mark_repo_onboarding_job_failed(conn, job_id=job_id, error=error)
        finally:
            conn.close()
        return {"status": "failed", "job_id": job_id, "error": error}

    try:
        result = _execute_repo_onboard(request_payload=request_payload, settings=settings)
        payload = result.to_dict()
        conn = get_connection(settings)
        try:
            ensure_repo_onboarding_jobs_table(conn)
            mark_repo_onboarding_job_succeeded(conn, job_id=job_id, result=payload)
        finally:
            conn.close()
        return {"status": "succeeded", "job_id": job_id, "result": payload}
    except Exception as exc:
        logger.exception("Repo onboarding job failed: %s", job_id)
        error = str(exc)
        conn = get_connection(settings)
        try:
            ensure_repo_onboarding_jobs_table(conn)
            mark_repo_onboarding_job_failed(conn, job_id=job_id, error=error)
        finally:
            conn.close()
        return {"status": "failed", "job_id": job_id, "error": error}


def _handle_repo_onboard_job_event(event: dict[str, Any]) -> dict[str, Any]:
    """Handle async worker invocation for repo onboarding job execution."""
    settings = get_settings()
    job_id = str(event.get("job_id", "")).strip()
    if not job_id:
        return {"statusCode": 400, "body": json.dumps({"error": "Missing job_id"})}
    result = _run_repo_onboard_job(job_id=job_id, settings=settings)
    status_code = 200 if result.get("status") == "succeeded" else 500
    return {"statusCode": status_code, "body": json.dumps(result)}


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
