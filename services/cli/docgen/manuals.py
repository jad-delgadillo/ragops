"""Deterministic onboarding manual generation for codebase, API, and database."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg import sql

from services.cli.docgen.analyzer import Analyzer, CodeContext
from services.core.config import Settings
from services.core.database import get_chunks_embedding_dimension, get_connection


@dataclass
class ManualPackResult:
    """Result of a manual-pack generation run."""

    files: list[Path]
    db_status: str  # ok | degraded | skipped
    db_error: str | None = None


class ManualPackGenerator:
    """Generates onboarding manuals from project structure and runtime metadata."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir.resolve()
        self.analyzer = Analyzer(self.root_dir)

    def generate(
        self,
        output_dir: Path,
        *,
        include_db: bool = True,
        settings: Settings | None = None,
    ) -> ManualPackResult:
        """Generate the manual pack and write Markdown files to disk."""
        output_dir.mkdir(parents=True, exist_ok=True)
        ctx = self.analyzer.analyze()
        api_snapshot = self._collect_api_snapshot()

        db_status = "skipped"
        db_error: str | None = None
        db_snapshot: dict[str, Any] | None = None

        if include_db:
            if settings is None:
                raise ValueError("settings is required when include_db=True")
            db_snapshot, db_error = self._collect_database_snapshot(settings)
            db_status = "ok" if db_snapshot is not None else "degraded"

        files = {
            "CODEBASE_MANUAL.md": self._render_codebase_manual(ctx),
            "API_MANUAL.md": self._render_api_manual(api_snapshot),
            "DATABASE_MANUAL.md": self._render_database_manual(
                db_snapshot=db_snapshot,
                db_error=db_error,
                include_db=include_db,
            ),
        }

        written: list[Path] = []
        for filename, content in files.items():
            path = output_dir / filename
            path.write_text(content)
            written.append(path)

        return ManualPackResult(files=written, db_status=db_status, db_error=db_error)

    def _collect_api_snapshot(self) -> dict[str, Any]:
        """Collect API and CLI-facing contract details from known entrypoints."""
        query_handler = self.root_dir / "services" / "api" / "app" / "handler.py"
        ingest_handler = self.root_dir / "services" / "ingest" / "app" / "handler.py"

        api_entries: list[dict[str, str]] = []
        if query_handler.exists():
            api_entries.extend(
                [
                    {
                        "method": "GET",
                        "path": "/",
                        "summary": "Service root and endpoint discovery",
                        "source": "services/api/app/handler.py",
                    },
                    {
                        "method": "GET",
                        "path": "/health",
                        "summary": "Database and embedding health check",
                        "source": "services/api/app/handler.py",
                    },
                    {
                        "method": "POST",
                        "path": "/v1/query",
                        "summary": "Retrieve and optionally generate grounded answer",
                        "source": "services/api/app/handler.py",
                    },
                    {
                        "method": "POST",
                        "path": "/v1/chat",
                        "summary": "Conversational RAG with session memory and chat modes",
                        "source": "services/api/app/handler.py",
                    },
                    {
                        "method": "POST",
                        "path": "/v1/feedback",
                        "summary": "Capture user feedback for answer quality analytics",
                        "source": "services/api/app/handler.py",
                    },
                ]
            )
        if ingest_handler.exists():
            api_entries.append(
                {
                    "method": "POST",
                    "path": "/v1/ingest",
                    "summary": "Ingest local directory; s3_prefix currently returns 501",
                    "source": "services/ingest/app/handler.py",
                }
            )

        cli_entries = [
            {"command": "ragops init", "summary": "Initialize ragops project config"},
            {"command": "ragops ingest", "summary": "Index docs/code into vector store"},
            {"command": "ragops query", "summary": "Ask grounded questions"},
            {
                "command": "ragops generate-docs",
                "summary": "Generate LLM-written docs from code context",
            },
            {
                "command": "ragops generate-manuals",
                "summary": "Generate deterministic onboarding manuals",
            },
            {"command": "ragops feedback", "summary": "Store answer quality feedback"},
            {"command": "ragops eval", "summary": "Run dataset-driven quality evaluation"},
            {"command": "ragops providers", "summary": "Show provider support and active config"},
        ]

        return {"api": api_entries, "cli": cli_entries}

    def _collect_database_snapshot(
        self,
        settings: Settings,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Collect database data dictionary and index metadata."""
        conn = None
        try:
            conn = get_connection(settings)
            column_rows = conn.execute(
                """
                SELECT
                    c.table_name,
                    c.column_name,
                    c.data_type,
                    c.udt_name,
                    c.is_nullable,
                    c.column_default,
                    format_type(a.atttypid, a.atttypmod) AS formatted_type
                FROM information_schema.columns c
                LEFT JOIN pg_class cls ON cls.relname = c.table_name
                LEFT JOIN pg_namespace nsp
                    ON nsp.oid = cls.relnamespace
                   AND nsp.nspname = c.table_schema
                LEFT JOIN pg_attribute a
                    ON a.attrelid = cls.oid
                   AND a.attname = c.column_name
                   AND NOT a.attisdropped
                WHERE c.table_schema = 'public'
                ORDER BY c.table_name, c.ordinal_position
                """
            ).fetchall()

            index_rows = conn.execute(
                """
                SELECT
                    tablename,
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                ORDER BY tablename, indexname
                """
            ).fetchall()

            tables: dict[str, dict[str, Any]] = {}
            for row in column_rows:
                table_name = row["table_name"]
                if table_name not in tables:
                    tables[table_name] = {
                        "row_count": 0,
                        "columns": [],
                        "indexes": [],
                    }

                col_type = row["formatted_type"] or row["data_type"]
                nullable = row["is_nullable"] == "YES"
                tables[table_name]["columns"].append(
                    {
                        "name": row["column_name"],
                        "type": col_type,
                        "nullable": nullable,
                        "default": row["column_default"] or "",
                        "udt_name": row["udt_name"],
                    }
                )

            for table_name in tables:
                count_row = conn.execute(
                    sql.SQL("SELECT COUNT(*) AS row_count FROM {}").format(
                        sql.Identifier(table_name)
                    )
                ).fetchone()
                tables[table_name]["row_count"] = int(count_row["row_count"])

            for row in index_rows:
                table_name = row["tablename"]
                if table_name in tables:
                    tables[table_name]["indexes"].append(
                        {
                            "name": row["indexname"],
                            "definition": row["indexdef"],
                        }
                    )

            embedding_dimension = get_chunks_embedding_dimension(conn)
            db_source = (
                settings.database_url
                or settings.neon_connection_string
                or f"{settings.db_host}:{settings.db_port}/{settings.db_name}"
            )

            return {
                "database_source": db_source,
                "embedding_dimension": embedding_dimension,
                "tables": tables,
            }, None
        except Exception as exc:  # pragma: no cover - integration failure path
            return None, str(exc)
        finally:
            if conn is not None:
                conn.close()

    def _render_codebase_manual(self, ctx: CodeContext) -> str:
        """Render CODEBASE_MANUAL.md."""
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
        tech_stack = ", ".join(ctx.tech_stack) if ctx.tech_stack else "Unknown"
        files_preview = "\n".join(f"- `{f}`" for f in ctx.file_tree[:80]) or "- None detected"
        if len(ctx.file_tree) > 80:
            files_preview += f"\n- ... and {len(ctx.file_tree) - 80} more files"

        symbol_lines: list[str] = []
        for file_path, data in ctx.key_symbols.items():
            symbol_lines.append(f"### `{file_path}`")
            for cls in data.get("classes", []):
                methods = ", ".join(cls.get("methods", [])) or "no methods"
                symbol_lines.append(f"- Class `{cls['name']}` ({methods})")
            for func in data.get("functions", []):
                symbol_lines.append(f"- Function `{func['name']}`")
            if not data.get("classes") and not data.get("functions"):
                symbol_lines.append("- No top-level classes/functions extracted")
        symbols = "\n".join(symbol_lines) or "No key symbols extracted."

        return f"""# Codebase Manual

Generated at: {generated_at}

## Project
- Name: `{ctx.project_name}`
- Tech stack: {tech_stack}
- Analyzer scope: file tree (depth <= 3), key entrypoints, Python AST symbols

## File Map (Preview)
{files_preview}

## Key Symbols
{symbols}

## Onboarding Notes
1. Start with `services/cli/main.py` to understand developer workflow.
2. Review `services/ingest` for indexing pipeline behavior.
3. Review `services/api` for runtime query behavior and response contract.
4. Review `services/core` for provider, config, and database abstractions.
"""

    def _render_api_manual(self, snapshot: dict[str, Any]) -> str:
        """Render API_MANUAL.md."""
        api_rows = snapshot.get("api", [])
        cli_rows = snapshot.get("cli", [])

        api_table = "\n".join(
            f"| {row['method']} | `{row['path']}` | {row['summary']} | `{row['source']}` |"
            for row in api_rows
        )
        if not api_table:
            api_table = "| - | - | No API endpoints discovered | - |"

        cli_table = "\n".join(
            f"| `{row['command']}` | {row['summary']} |"
            for row in cli_rows
        )

        return f"""# API Manual

## HTTP Endpoints
| Method | Path | Summary | Source |
| --- | --- | --- | --- |
{api_table}

## Request Examples
### Query
```json
{{
  "question": "How does ingestion work?",
  "collection": "default"
}}
```

### Ingest (Local Directory)
```json
{{
  "local_dir": "./docs",
  "collection": "default"
}}
```

## CLI Interface
| Command | Summary |
| --- | --- |
{cli_table}

## Current Constraints
1. `POST /v1/ingest` with `s3_prefix` is not implemented yet.
2. `POST /v1/query` enforces a 2000-character limit on `question`.
3. Retrieval quality depends on chunking config and embedding/provider compatibility.
"""

    def _render_database_manual(
        self,
        *,
        db_snapshot: dict[str, Any] | None,
        db_error: str | None,
        include_db: bool,
    ) -> str:
        """Render DATABASE_MANUAL.md."""
        if not include_db:
            return """# Database Manual

Database introspection was skipped (`--no-db`).
"""

        if db_snapshot is None:
            error_text = db_error or "Unknown database error"
            return f"""# Database Manual

Database introspection failed.

Error:
```
{error_text}
```
"""

        source = db_snapshot["database_source"]
        embedding_dimension = db_snapshot.get("embedding_dimension")
        tables = db_snapshot.get("tables", {})

        summary_rows = []
        for table_name, table_data in sorted(tables.items()):
            summary_rows.append(
                f"| `{table_name}` | {table_data['row_count']} | {len(table_data['columns'])} |"
            )
        summary_table = "\n".join(summary_rows) or "| - | 0 | 0 |"

        sections: list[str] = []
        for table_name, table_data in sorted(tables.items()):
            sections.append(f"## `{table_name}`")
            sections.append(f"Rows: {table_data['row_count']}")
            sections.append("")
            sections.append("| Column | Type | Nullable | Default |")
            sections.append("| --- | --- | --- | --- |")
            for col in table_data["columns"]:
                nullable = str(col["nullable"]).lower()
                sections.append(
                    f"| `{col['name']}` | `{col['type']}` | `{nullable}` | `{col['default']}` |"
                )
            sections.append("")
            sections.append("Indexes:")
            if table_data["indexes"]:
                for idx in table_data["indexes"]:
                    sections.append(f"- `{idx['name']}`: `{idx['definition']}`")
            else:
                sections.append("- None")
            sections.append("")

        dim_line = (
            str(embedding_dimension)
            if embedding_dimension is not None
            else "not fixed (vector column without explicit dimension)"
        )
        detail_section = "\n".join(sections) if sections else "No public tables discovered."

        return f"""# Database Manual

## Connection Snapshot
- Source: `{source}`
- `chunks.embedding` dimension: {dim_line}

## Table Summary
| Table | Rows | Columns |
| --- | --- | --- |
{summary_table}

{detail_section}
"""
