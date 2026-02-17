"""Lambda handler for the ingestion API (POST /v1/ingest)."""

from __future__ import annotations

import json
import logging
from typing import Any

from services.api.app.access import authorize
from services.core.config import get_settings
from services.core.logging import set_request_id, setup_logging
from services.core.providers import get_embedding_provider
from services.ingest.app.pipeline import ingest_local_directory

logger = logging.getLogger(__name__)


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """AWS Lambda entry point for ingest.

    Expected body: {"s3_prefix": "docs/", "collection": "default"}
    For local dev: {"local_dir": "./docs", "collection": "default"}
    """
    settings = get_settings()
    setup_logging(settings.log_level)
    set_request_id(event.get("requestContext", {}).get("requestId"))

    try:
        body = json.loads(event.get("body", "{}")) if isinstance(event.get("body"), str) else event
        collection = body.get("collection", "default")
        headers = event.get("headers", {}) if isinstance(event.get("headers"), dict) else {}
        decision = authorize(
            settings=settings,
            headers=headers,
            action="ingest",
            collection=collection,
        )
        if not decision.allowed:
            return {
                "statusCode": 403,
                "body": json.dumps({"error": decision.reason or "Forbidden"}),
            }

        # Local dev mode: ingest from local directory
        local_dir = body.get("local_dir")
        if local_dir:
            provider = get_embedding_provider(settings)
            stats = ingest_local_directory(
                directory=local_dir,
                embedding_provider=provider,
                collection=collection,
                settings=settings,
            )

            status_code = 200 if not stats.errors else 207
            return {
                "statusCode": status_code,
                "body": json.dumps(
                    {
                        "status": "ok" if not stats.errors else "partial",
                        "indexed_docs": stats.indexed_docs,
                        "skipped_docs": stats.skipped_docs,
                        "chunks": stats.total_chunks,
                        "elapsed_ms": round(stats.elapsed_ms, 1),
                        "errors": stats.errors[:10],  # Cap error list
                    }
                ),
            }

        # S3 mode (for AWS deployment)
        s3_prefix = body.get("s3_prefix")
        if not s3_prefix:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Provide 'local_dir' or 's3_prefix'"}),
            }

        # TODO: Implement S3 download + ingest pipeline
        msg = "S3 ingestion not yet implemented. Use local_dir."
        return {
            "statusCode": 501,
            "body": json.dumps({"error": msg}),
        }

    except Exception as exc:
        logger.exception("Ingest handler error")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc)}),
        }


# ---------------------------------------------------------------------------
# CLI entry point for local dev
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point: python -m services.ingest.app.handler"""
    import argparse

    from rich.console import Console
    from rich.panel import Panel

    parser = argparse.ArgumentParser(description="RAG Ops Ingest CLI")
    parser.add_argument("directory", help="Directory of documents to ingest")
    parser.add_argument("--collection", default="default", help="Collection name")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    settings = get_settings()

    # Suppress logs in CLI mode for cleaner output
    if not args.json:
        setup_logging("ERROR")
    else:
        setup_logging(settings.log_level)

    provider = get_embedding_provider(settings)

    # Execute ingestion with spinner (only in non-JSON mode)
    console = Console()
    if not args.json:
        with console.status(
            f"[bold cyan]Ingesting documents from {args.directory}...[/bold cyan]",
            spinner="dots",
        ):
            stats = ingest_local_directory(
                directory=args.directory,
                embedding_provider=provider,
                collection=args.collection,
                settings=settings,
            )
    else:
        stats = ingest_local_directory(
            directory=args.directory,
            embedding_provider=provider,
            collection=args.collection,
            settings=settings,
        )

    # Output results
    if args.json:
        print(
            json.dumps(
                {
                    "indexed_docs": stats.indexed_docs,
                    "skipped_docs": stats.skipped_docs,
                    "chunks": stats.total_chunks,
                    "elapsed_ms": round(stats.elapsed_ms, 1),
                    "errors": stats.errors,
                },
                indent=2,
            )
        )
    else:
        # Rich formatted output
        status_emoji = "✅" if not stats.errors else "⚠️"
        status_text = "Success" if not stats.errors else "Completed with errors"

        summary = f"""[bold green]{status_emoji} {status_text}[/bold green]

[cyan]Indexed:[/cyan] {stats.indexed_docs} documents
[cyan]Skipped:[/cyan] {stats.skipped_docs} documents
[cyan]Chunks:[/cyan] {stats.total_chunks} total
[cyan]Time:[/cyan] {stats.elapsed_ms / 1000:.1f}s"""

        if stats.errors:
            summary += "\n\n[yellow]Errors:[/yellow]\n" + "\n".join(
                f"  • {err}" for err in stats.errors[:5]
            )
            if len(stats.errors) > 5:
                summary += f"\n  ... and {len(stats.errors) - 5} more"

        console.print()
        console.print(Panel(summary, title="📥 Ingestion Complete", border_style="green"))
        console.print()


if __name__ == "__main__":
    main()
