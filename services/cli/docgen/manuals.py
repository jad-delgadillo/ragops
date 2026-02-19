"""Deterministic onboarding manual generation for codebase, API, and database."""

from __future__ import annotations

import json
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

        files: dict[str, str] = {
            "PROJECT_OVERVIEW.md": self._render_project_overview(ctx),
            "ARCHITECTURE_MAP.md": self._render_architecture_map(ctx),
            "CODEBASE_MANUAL.md": self._render_codebase_manual(ctx),
            "API_MANUAL.md": self._render_api_manual(api_snapshot),
            "ARCHITECTURE_DIAGRAM.md": self._render_architecture_diagram_manual(ctx),
            "OPERATIONS_RUNBOOK.md": self._render_operations_runbook(ctx),
            "UNKNOWNS_AND_GAPS.md": self._render_unknowns_and_gaps(ctx),
            "DATABASE_MANUAL.md": self._render_database_manual(
                db_snapshot=db_snapshot,
                db_error=db_error,
                include_db=include_db,
            ),
        }

        scan_index = self._build_scan_index(
            ctx=ctx,
            api_snapshot=api_snapshot,
            include_db=include_db,
            db_status=db_status,
            db_error=db_error,
            markdown_files=sorted(files.keys()),
        )

        written: list[Path] = []
        for filename, content in files.items():
            path = output_dir / filename
            path.write_text(content, encoding="utf-8")
            written.append(path)

        scan_index_path = output_dir / "SCAN_INDEX.json"
        scan_index_path.write_text(json.dumps(scan_index, indent=2, ensure_ascii=True), encoding="utf-8")
        written.append(scan_index_path)

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
            {
                "command": "ragops scan",
                "summary": "One-command local scan (ingest code + manuals)",
            },
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

    def _source_pointer(
        self,
        relative_path: str,
        *,
        contains: str | None = None,
        default_line: int = 1,
    ) -> str:
        """Return `path:line` pointer for evidence-backed claims."""
        target = self.root_dir / relative_path
        line_no = default_line
        if target.exists():
            if contains:
                for idx, line in enumerate(
                    target.read_text(encoding="utf-8", errors="replace").splitlines(),
                    1,
                ):
                    if contains in line:
                        line_no = idx
                        break
            return f"{relative_path}:{line_no}"
        return f"{relative_path}:{default_line}"

    def _claim(self, text: str, *, source: str, confidence: str = "high") -> str:
        """Render a normalized claim line with source pointer and confidence."""
        return f"- [{confidence}] {text} Source: `{source}`"

    def _format_entrypoints(self, ctx: CodeContext) -> str:
        """Render entrypoint bullets with confidence and source pointers."""
        if not ctx.entrypoints:
            return "- [low] No deterministic entrypoints were detected. Source: `.:1`"
        lines: list[str] = []
        for item in ctx.entrypoints[:12]:
            path = item.get("path", "unknown")
            pointer = self._source_pointer(path)
            reason = item.get("reason", "entrypoint candidate")
            confidence = item.get("confidence", "medium")
            lines.append(
                self._claim(
                    f"`{path}` is an entrypoint candidate ({reason}).",
                    source=pointer,
                    confidence=confidence,
                )
            )
        return "\n".join(lines)

    def _build_scan_index(
        self,
        *,
        ctx: CodeContext,
        api_snapshot: dict[str, Any],
        include_db: bool,
        db_status: str,
        db_error: str | None,
        markdown_files: list[str],
    ) -> dict[str, Any]:
        """Build machine-readable scan metadata for ranking and diagnostics."""
        generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "generated_at": generated_at,
            "project": ctx.project_name,
            "scan_contract_version": "1.0",
            "quality_bar": {
                "deterministic_extraction_preferred": True,
                "requires_source_pointers": True,
                "requires_confidence_labels_for_inference": True,
            },
            "manuals": markdown_files,
            "artifacts": markdown_files + ["SCAN_INDEX.json"],
            "tech_stack": ctx.tech_stack,
            "framework_signals": ctx.framework_signals,
            "entrypoints": ctx.entrypoints,
            "ownership_map": ctx.ownership_map,
            "gaps": ctx.gaps,
            "summary": ctx.summary,
            "api_counts": {
                "http_endpoints": len(api_snapshot.get("api", [])),
                "cli_commands": len(api_snapshot.get("cli", [])),
            },
            "database_snapshot": {
                "enabled": include_db,
                "status": db_status,
                "error": db_error or "",
            },
            "source_pointers": {
                "cli_scan": self._source_pointer("services/cli/main.py", contains='sub.add_parser("scan"'),
                "manual_generator": self._source_pointer(
                    "services/cli/docgen/manuals.py",
                    contains="class ManualPackGenerator",
                ),
                "api_handler": self._source_pointer("services/api/app/handler.py"),
                "ingest_pipeline": self._source_pointer(
                    "services/ingest/app/pipeline.py",
                    contains="def ingest_local_directory",
                ),
            },
        }

    def _render_project_overview(self, ctx: CodeContext) -> str:
        """Render PROJECT_OVERVIEW.md."""
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
        tech_stack = ", ".join(ctx.tech_stack) if ctx.tech_stack else "Unknown"
        stack_claims = (
            "\n".join(
                self._claim(
                    f"Framework signal `{item.get('name', 'unknown')}` detected via `{item.get('signal', 'n/a')}`.",
                    source=self._source_pointer(str(item.get("source", "."))),
                    confidence=item.get("confidence", "medium"),
                )
                for item in ctx.framework_signals[:8]
            )
            if ctx.framework_signals
            else self._claim(
                "No strong framework markers were detected.",
                source=".:1",
                confidence="low",
            )
        )

        return f"""# Project Overview

Generated at: {generated_at}

## Summary
{self._claim("This project exposes a CLI-first onboarding workflow (`ragops init`, `ragops scan`, `ragops chat`).", source=self._source_pointer("services/cli/main.py", contains='sub.add_parser("scan"'))}
{self._claim("Scan generates deterministic manuals and can ingest them for retrieval.", source=self._source_pointer("services/cli/main.py", contains="ManualPackGenerator"))}

## What This Repo Does
{self._claim("The repository includes ingestion, query/chat, and documentation-generation modules.", source=self._source_pointer("services/cli/main.py"))}
{self._claim("Primary language/tooling stack detected: {tech_stack}.", source=self._source_pointer("pyproject.toml"), confidence="medium")}

## How To Run
1. `ragops init`
2. `ragops scan`
3. `ragops chat`

## Key Entrypoints
{self._format_entrypoints(ctx)}

## Framework Signals
{stack_claims}
"""

    def _render_architecture_map(self, ctx: CodeContext) -> str:
        """Render ARCHITECTURE_MAP.md."""
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
        components: list[str] = []
        if "services/cli/main.py" in ctx.file_tree:
            components.append(
                self._claim(
                    "CLI orchestrates init/scan/chat command flows.",
                    source=self._source_pointer("services/cli/main.py"),
                )
            )
        if "services/ingest/app/pipeline.py" in ctx.file_tree:
            components.append(
                self._claim(
                    "Ingest pipeline handles file collection, chunking, embeddings, and storage upsert.",
                    source=self._source_pointer(
                        "services/ingest/app/pipeline.py",
                        contains="def ingest_local_directory",
                    ),
                )
            )
        if "services/api/app/chat.py" in ctx.file_tree:
            components.append(
                self._claim(
                    "Chat service performs reranking, prompt assembly, and session persistence.",
                    source=self._source_pointer("services/api/app/chat.py", contains="def chat("),
                )
            )
        if "services/api/app/retriever.py" in ctx.file_tree:
            components.append(
                self._claim(
                    "Retriever handles vector retrieval and query reranking.",
                    source=self._source_pointer("services/api/app/retriever.py", contains="def retrieve("),
                )
            )
        if "services/core/storage.py" in ctx.file_tree:
            components.append(
                self._claim(
                    "Storage layer manages collections, vectors, chat history, and feedback records.",
                    source=self._source_pointer("services/core/storage.py"),
                )
            )
        if not components:
            components.append(self._claim("No known architecture components detected in standard paths.", source=".:1", confidence="low"))

        boundaries = [
            self._claim(
                "Collection boundaries separate code and manual corpora during repo onboarding.",
                source=self._source_pointer("services/cli/main.py", contains="resolve_collection_pair"),
                confidence="medium",
            ),
            self._claim(
                "Low-value generated/cache sources are demoted during retrieval reranking.",
                source=self._source_pointer("services/api/app/chat.py", contains="LOW_VALUE_PATH_HINTS"),
            ),
        ]

        return f"""# Architecture Map

Generated at: {generated_at}

## Components
{chr(10).join(components)}

## Data Flow
1. `scan` ingests repository files into vector storage.
2. Manual pack generation adds high-level onboarding context.
3. `chat` embeds the question, retrieves ranked chunks, and returns citations.

## Boundaries and Dependencies
{chr(10).join(boundaries)}
"""

    def _render_operations_runbook(self, ctx: CodeContext) -> str:
        """Render OPERATIONS_RUNBOOK.md."""
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
        test_cmd = ".venv/bin/python -m pytest services/ -q"
        return f"""# Operations Runbook

Generated at: {generated_at}

## Install
{self._claim("Install as a package and initialize per-project configuration.", source=self._source_pointer("README.md", contains="pip install ragops"), confidence="medium")}

```bash
pip install ragops
ragops init
```

## Scan and Chat
```bash
ragops scan
ragops chat
```

## Test
{self._claim("Service tests run with pytest over `services/`.", source=self._source_pointer("README.md", contains="pytest services"), confidence="medium")}
```bash
{test_cmd}
```

## Debug Checklist
1. Run `ragops config doctor`.
2. Re-run `ragops scan` for stale collections.
3. Confirm provider/API key configuration and embedding compatibility.
4. Use `ragops chat --show-context` to inspect retrieved snippets.
"""

    def _render_unknowns_and_gaps(self, ctx: CodeContext) -> str:
        """Render UNKNOWNS_AND_GAPS.md."""
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
        if ctx.gaps:
            gap_lines = "\n".join(
                self._claim(
                    item.get("detail", "gap detected"),
                    source=item.get("source", ".:1"),
                    confidence=item.get("confidence", "medium"),
                )
                for item in ctx.gaps
            )
        else:
            gap_lines = self._claim(
                "No significant structural gaps were detected by deterministic scan heuristics.",
                source=".:1",
                confidence="medium",
            )

        return f"""# Unknowns and Gaps

Generated at: {generated_at}

## Detected Gaps
{gap_lines}

## Confidence Policy
- `high`: direct marker found in source files.
- `medium`: strong heuristic inferred from file layout.
- `low`: fallback inference with limited direct evidence.
"""

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
                line = cls.get("line", "1")
                symbol_lines.append(
                    self._claim(
                        f"Class `{cls['name']}` ({methods})",
                        source=f"{file_path}:{line}",
                        confidence="high",
                    )
                )
            for func in data.get("functions", []):
                line = func.get("line", "1")
                symbol_lines.append(
                    self._claim(
                        f"Function `{func['name']}`",
                        source=f"{file_path}:{line}",
                        confidence="high",
                    )
                )
            if not data.get("classes") and not data.get("functions"):
                symbol_lines.append(
                    self._claim(
                        "No top-level classes/functions extracted.",
                        source=f"{file_path}:1",
                        confidence="medium",
                    )
                )
        symbols = "\n".join(symbol_lines) or "No key symbols extracted."

        return f"""# Codebase Manual

Generated at: {generated_at}

## Project
{self._claim(f"Project name resolved as `{ctx.project_name}`.", source=".:1")}
{self._claim(f"Detected stack includes: {tech_stack}.", source=self._source_pointer("pyproject.toml"), confidence="medium")}
{self._claim("Analyzer scope includes file map, entrypoint detection, ownership hints, and Python AST symbols.", source=self._source_pointer("services/cli/docgen/analyzer.py", contains="def analyze("))}

## Entrypoints
{self._format_entrypoints(ctx)}

## Ownership Map
{chr(10).join(self._claim(f"Area `{item.get('area', 'unknown')}` owned by `{item.get('owner', 'unassigned')}`.", source=item.get("source", ".:1"), confidence=item.get("confidence", "medium")) for item in ctx.ownership_map[:10]) if ctx.ownership_map else self._claim("No ownership map entries were detected.", source=".:1", confidence="low")}

## File Map (Preview)
{files_preview}

## Key Symbols
{symbols}

## Onboarding Notes
1. Start with `services/cli/main.py`.
2. Review `services/ingest/app/pipeline.py`.
3. Review `services/api/app/chat.py` and `services/api/app/retriever.py`.
4. Review `services/core/storage.py` and `services/core/config.py`.
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

        cli_table = "\n".join(f"| `{row['command']}` | {row['summary']} |" for row in cli_rows)

        return f"""# API Manual

## Claims
{self._claim("API contract is derived from handler entrypoints and known request routes.", source=self._source_pointer("services/api/app/handler.py"))}
{self._claim("CLI command surface is sourced from parser registrations in `services/cli/main.py`.", source=self._source_pointer("services/cli/main.py", contains="sub.add_parser"), confidence="high")}

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

## Confidence
- `high`: endpoint/command surfaced from deterministic files.
- `medium`: inferred from naming conventions and module presence.
"""

    def _render_architecture_diagram_manual(self, ctx: CodeContext) -> str:
        """Render ARCHITECTURE_DIAGRAM.md with Mermaid diagrams."""
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
        file_set = set(ctx.file_tree)

        has_lazy_onboarding = "services/api/app/repo_onboarding.py" in file_set
        has_lazy_retrieval = "services/api/app/retriever.py" in file_set
        has_github_tree = "services/core/github_tree.py" in file_set
        has_database = (
            "services/core/database.py" in file_set or "services/core/schema.sql" in file_set
        )
        has_embedding_provider = any(
            path.startswith("services/core/") and path.endswith("_provider.py") for path in file_set
        )

        participants = [
            ("U", "User"),
            ("C", "CLI / API"),
        ]
        if has_github_tree:
            participants.append(("G", "GitHub Trees API"))
        if has_database:
            participants.append(("D", "PostgreSQL"))
        if has_embedding_provider:
            participants.append(("E", "Embedding Provider"))

        participant_lines = [f"    participant {pid} as {label}" for pid, label in participants]
        participant_ids = {pid for pid, _ in participants}
        rightmost = participants[-1][0]

        def _note(title: str) -> str:
            if rightmost == "U":
                return f"    note over U: {title}"
            return f"    note over U,{rightmost}: {title}"

        if has_lazy_onboarding and has_lazy_retrieval and has_github_tree:
            phase_one_lines = [
                "    rect rgb(55, 55, 55)",
                _note("Phase 1: Instant Onboarding"),
                "    U->>C: ragops repo add-lazy <url>",
                "    C->>G: Fetch file tree (1 API call)",
                "    G-->>C: File paths + metadata",
            ]
            if "E" in participant_ids:
                phase_one_lines.append("    C->>E: Embed file paths only")
            if "D" in participant_ids:
                phase_one_lines.append("    C->>D: Store in {collection}_tree + repo_files")
            phase_one_lines.extend(
                [
                    "    C-->>U: Ready! (N embeddable files)",
                    "    end",
                ]
            )
            phase_two_lines = [
                "    rect rgb(55, 55, 55)",
                _note("Phase 2: On-demand per Query"),
                '    U->>C: ragops chat --collection <col> "question"',
            ]
            if "D" in participant_ids:
                phase_two_lines.extend(
                    [
                        "    C->>D: Search {collection}_tree for relevant paths",
                        "    D-->>C: Top matching file paths",
                    ]
                )
            else:
                phase_two_lines.append(
                    "    C-->>U: Tree collection unavailable in this project shape"
                )
            phase_two_lines.extend(
                [
                    "    C->>G: Fetch only those file contents",
                ]
            )
            if "E" in participant_ids:
                phase_two_lines.append("    C->>E: Embed + cache file contents")
            if "D" in participant_ids:
                phase_two_lines.extend(
                    [
                        "    C->>D: Search {collection} for answer chunks",
                        "    D-->>C: Grounded chunks + citations",
                    ]
                )
            phase_two_lines.extend(
                [
                    "    C-->>U: Answer with citations",
                    "    end",
                ]
            )
            flow_name = "Lazy Repo Onboarding + On-demand Retrieval"
        else:
            phase_one_lines = [
                "    rect rgb(55, 55, 55)",
                _note("Phase 1: Project Scan"),
                "    U->>C: ragops scan",
            ]
            if "E" in participant_ids:
                phase_one_lines.append("    C->>E: Embed project files")
            if "D" in participant_ids:
                phase_one_lines.append("    C->>D: Store chunks in {collection}")
            phase_one_lines.extend(
                [
                    "    C-->>U: Ready for questions",
                    "    end",
                ]
            )
            phase_two_lines = [
                "    rect rgb(55, 55, 55)",
                _note("Phase 2: Query"),
                '    U->>C: ragops query "question"',
            ]
            if "E" in participant_ids:
                phase_two_lines.append("    C->>E: Embed question")
            if "D" in participant_ids:
                phase_two_lines.extend(
                    [
                        "    C->>D: Vector search in {collection}",
                        "    D-->>C: Top chunks + citations",
                    ]
                )
            phase_two_lines.extend(
                [
                    "    C-->>U: Answer with citations",
                    "    end",
                ]
            )
            flow_name = "Local Scan + Retrieval"

        mermaid_body = "\n".join(
            [
                "sequenceDiagram",
                *participant_lines,
                "",
                *phase_one_lines,
                "",
                *phase_two_lines,
            ]
        )

        detected_components = []
        detected_components.append("- CLI/API orchestration")
        if has_github_tree:
            detected_components.append("- GitHub Trees API integration")
        if has_database:
            detected_components.append("- PostgreSQL-backed vector + metadata storage")
        if has_embedding_provider:
            detected_components.append("- Pluggable embedding providers")
        components_block = "\n".join(detected_components)

        return f"""# Architecture Diagram Manual

Generated at: {generated_at}

## Flow Type
{flow_name}

## Claims
{self._claim("Architecture flow type is selected from detected module shape.", source=self._source_pointer("services/cli/docgen/manuals.py", contains="def _render_architecture_diagram_manual"))}
{self._claim("Mermaid sequence blocks are generated deterministically from file presence signals.", source=self._source_pointer("services/cli/docgen/manuals.py", contains="sequenceDiagram"))}

## Detected Components
{components_block}

## Sequence Diagram (Mermaid)
```mermaid
{mermaid_body}
```

## Notes
1. This diagram is generated deterministically from detected project modules.
2. It is intended for onboarding and architecture communication.
3. Render in GitHub/Markdown viewer with Mermaid support.
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

## Claims
{self._claim("Database snapshot is produced from information_schema and pg_indexes queries.", source=self._source_pointer("services/cli/docgen/manuals.py", contains="FROM information_schema.columns"))}
{self._claim("Embedding dimension is read from `chunks.embedding` metadata.", source=self._source_pointer("services/cli/docgen/manuals.py", contains="get_chunks_embedding_dimension"))}

## Connection Snapshot
- Source: `{source}`
- `chunks.embedding` dimension: {dim_line}

## Table Summary
| Table | Rows | Columns |
| --- | --- | --- |
{summary_table}

{detail_section}
"""
