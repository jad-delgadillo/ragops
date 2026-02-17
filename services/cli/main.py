"""ragops — CLI entrypoint for the RAG Ops Platform."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize ragops in the current project."""
    from services.cli.project import (
        ProjectConfig,
        detect_project_name,
        save_config,
    )

    project_dir = Path(args.path).resolve()
    if not project_dir.exists():
        console.print(f"[red]Error:[/red] Directory '{args.path}' does not exist")
        sys.exit(1)

    # Detect or use provided name
    name = args.name or detect_project_name(project_dir)

    config = ProjectConfig(name=name)
    config_path = save_config(config, project_dir)

    console.print()
    console.print(
        Panel(
            f"[bold green]✅ Initialized ragops[/bold green]\n\n"
            f"[cyan]Project:[/cyan] {name}\n"
            f"[cyan]Config:[/cyan] {config_path.relative_to(project_dir)}\n\n"
            f"[dim]Next steps:[/dim]\n"
            f"  ragops ingest   — index your docs & code\n"
            f"  ragops query    — ask questions about your project",
            title="📦 ragops init",
            border_style="green",
        )
    )
    console.print()


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


def cmd_ingest(args: argparse.Namespace) -> None:
    """Ingest documents and code into the vector database."""
    from services.cli.project import find_project_root, load_config
    from services.core.config import get_settings
    from services.core.logging import setup_logging
    from services.core.providers import get_embedding_provider
    from services.ingest.app.pipeline import ingest_local_directory

    project_dir = Path(args.path).resolve() if args.path else None
    root = project_dir or find_project_root() or Path.cwd()
    config = load_config(root)

    project_name = args.project or config.name or root.name

    settings = get_settings()
    setup_logging("ERROR")  # suppress logs for clean CLI

    provider = get_embedding_provider(settings)

    # Determine directories to ingest
    if args.dir:
        dirs_to_ingest = [args.dir]
    else:
        # Use config doc_dirs + code_dirs, resolved from project root
        dirs_to_ingest = []
        for d in config.doc_dirs + config.code_dirs:
            full = root / d
            if full.exists() and str(full) not in [str(x) for x in dirs_to_ingest]:
                dirs_to_ingest.append(str(full))
        if not dirs_to_ingest:
            dirs_to_ingest = [str(root)]

    total_indexed = 0
    total_skipped = 0
    total_chunks = 0
    total_errors: list[str] = []
    elapsed = 0.0

    with console.status(
        f"[bold cyan]Ingesting {project_name}...[/bold cyan]",
        spinner="dots",
    ):
        for directory in dirs_to_ingest:
            stats = ingest_local_directory(
                directory=directory,
                embedding_provider=provider,
                collection=project_name,
                settings=settings,
            )
            total_indexed += stats.indexed_docs
            total_skipped += stats.skipped_docs
            total_chunks += stats.total_chunks
            total_errors.extend(stats.errors)
            elapsed += stats.elapsed_ms

    # Output
    status_emoji = "✅" if not total_errors else "⚠️"
    status_text = "Success" if not total_errors else "Completed with errors"

    summary = (
        f"[bold green]{status_emoji} {status_text}[/bold green]\n\n"
        f"[cyan]Project:[/cyan] {project_name}\n"
        f"[cyan]Indexed:[/cyan] {total_indexed} files\n"
        f"[cyan]Skipped:[/cyan] {total_skipped} files (unchanged)\n"
        f"[cyan]Chunks:[/cyan] {total_chunks} total\n"
        f"[cyan]Time:[/cyan] {elapsed / 1000:.1f}s"
    )

    if total_errors:
        summary += "\n\n[yellow]Errors:[/yellow]\n" + "\n".join(
            f"  • {err}" for err in total_errors[:5]
        )

    console.print()
    console.print(Panel(summary, title="📥 Ingestion Complete", border_style="green"))
    console.print()


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


def cmd_query(args: argparse.Namespace) -> None:
    """Query the indexed project."""
    from services.api.app.retriever import query
    from services.cli.project import find_project_root, load_config
    from services.cli.remote import _query_remote_with_auth
    from services.core.config import get_settings
    from services.core.logging import setup_logging
    from services.core.providers import get_embedding_provider, get_llm_provider

    root = find_project_root() or Path.cwd()
    config = load_config(root)
    project_name = args.project or config.name or root.name
    collection_name = args.collection or project_name

    settings = get_settings()
    setup_logging("ERROR")

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
            if args.api_url:
                result = _query_remote_with_auth(
                    args.question,
                    args.api_url,
                    collection_name,
                    api_key=args.api_key,
                )
            else:
                result = query(
                    question=args.question,
                    embedding_provider=embed_provider,
                    llm_provider=llm_provider,
                    collection=collection_name,
                    top_k=args.top_k,
                    settings=settings,
                )
    else:
        if args.api_url:
            result = _query_remote_with_auth(
                args.question,
                args.api_url,
                collection_name,
                api_key=args.api_key,
            )
        else:
            result = query(
                question=args.question,
                embedding_provider=embed_provider,
                llm_provider=llm_provider,
                collection=collection_name,
                top_k=args.top_k,
                settings=settings,
            )

    # JSON output
    if args.json:
        import json

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

    # Rich output
    console.print()
    console.print(
        Panel(
            Markdown(result.answer),
            title=f"[bold cyan]Answer[/bold cyan] [dim]({result.mode} mode)[/dim]",
            border_style="cyan",
        )
    )

    if result.citations:
        console.print()
        if console.width < 80:
            console.print("[bold magenta]📚 Citations:[/bold magenta]")
            for i, cite in enumerate(result.citations, 1):
                source = cite.get("source", "unknown").split("/")[-1]
                lines = f"{cite.get('line_start', '?')}-{cite.get('line_end', '?')}"
                score = f"{cite.get('similarity', 0):.1%}"
                console.print(
                    f"  [dim]{i}.[/dim] [cyan]{source}[/cyan] "
                    f"[yellow]L{lines}[/yellow] [green]{score}[/green]"
                )
        else:
            table = Table(
                title="📚 Citations",
                show_header=True,
                header_style="bold magenta",
                expand=False,
            )
            table.add_column("#", style="dim", width=3, no_wrap=True)
            table.add_column("Source", style="cyan", min_width=15, max_width=30)
            table.add_column("Lines", justify="center", style="yellow", width=8)
            table.add_column("Score", justify="right", style="green", width=7)

            for i, cite in enumerate(result.citations, 1):
                source = cite.get("source", "unknown").split("/")[-1]
                lines = f"{cite.get('line_start', '?')}-{cite.get('line_end', '?')}"
                score = f"{cite.get('similarity', 0):.1%}"
                table.add_row(str(i), source, lines, score)

            console.print(table)

    console.print()
    console.print(
        f"[dim]Retrieved {result.retrieved} chunks "
        f"from '{project_name}' in {result.latency_ms:.0f}ms[/dim]"
    )
    console.print()


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------


def cmd_chat(args: argparse.Namespace) -> None:
    """Multi-turn chat with session memory."""
    from services.api.app.chat import chat
    from services.cli.project import find_project_root, load_config
    from services.cli.remote import _chat_remote
    from services.core.config import get_settings
    from services.core.logging import setup_logging
    from services.core.providers import get_embedding_provider, get_llm_provider

    root = find_project_root() or Path.cwd()
    config = load_config(root)
    project_name = args.project or config.name or root.name
    collection_name = args.collection or project_name

    settings = get_settings()
    setup_logging("ERROR")

    embed_provider = get_embedding_provider(settings)
    llm_provider = get_llm_provider(settings)

    if not args.json:
        from rich.console import Console

        console = Console()
        with console.status(
            "[bold cyan]Processing chat turn...[/bold cyan]",
            spinner="dots",
        ):
            if args.api_url:
                result = _chat_remote(
                    args.question,
                    args.api_url,
                    collection_name,
                    session_id=args.session_id,
                    mode=args.mode,
                    answer_style=args.answer_style,
                    top_k=args.top_k,
                    include_context=args.show_context,
                    api_key=args.api_key,
                )
            else:
                result = chat(
                    question=args.question,
                    embedding_provider=embed_provider,
                    llm_provider=llm_provider,
                    session_id=args.session_id,
                    mode=args.mode,
                    answer_style=args.answer_style,
                    collection=collection_name,
                    top_k=args.top_k,
                    settings=settings,
                )
    else:
        if args.api_url:
            result = _chat_remote(
                args.question,
                args.api_url,
                collection_name,
                session_id=args.session_id,
                mode=args.mode,
                answer_style=args.answer_style,
                top_k=args.top_k,
                include_context=args.show_context,
                api_key=args.api_key,
            )
        else:
            result = chat(
                question=args.question,
                embedding_provider=embed_provider,
                llm_provider=llm_provider,
                session_id=args.session_id,
                mode=args.mode,
                answer_style=args.answer_style,
                collection=collection_name,
                top_k=args.top_k,
                settings=settings,
            )

    if args.json:
        import json

        print(
            json.dumps(
                {
                    "session_id": result.session_id,
                    "answer": result.answer,
                    "citations": result.citations,
                    "latency_ms": round(result.latency_ms, 1),
                    "retrieved": result.retrieved,
                    "mode": result.mode,
                    "answer_style": result.answer_style,
                    "turn_index": result.turn_index,
                    "context_snippets": result.context_snippets if args.show_context else [],
                },
                indent=2,
            )
        )
        return

    console.print()
    session_meta = (
        f"session={result.session_id} "
        f"turn={result.turn_index} "
        f"mode={result.mode} "
        f"style={result.answer_style}"
    )
    console.print(
        Panel(
            Markdown(result.answer),
            title=f"[bold cyan]Chat[/bold cyan] [dim]{session_meta}[/dim]",
            border_style="cyan",
        )
    )
    if result.citations:
        console.print()
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
            lines = f"{cite.get('line_start', '?')}-{cite.get('line_end', '?')}"
            score = f"{cite.get('similarity', 0):.1%}"
            table.add_row(str(i), source_short, lines, score)
        console.print(table)

    if args.show_context and result.context_snippets:
        console.print()
        console.print("[bold]Raw Context Snippets[/bold]")
        for i, snippet in enumerate(result.context_snippets, 1):
            source = snippet.get("source", "unknown")
            lines = f"{snippet.get('line_start', '?')}-{snippet.get('line_end', '?')}"
            content = snippet.get("content", "")
            console.print(f"[dim]{i}.[/dim] [cyan]{source}[/cyan] [yellow]L{lines}[/yellow]")
            console.print(Markdown(f"```\n{content}\n```"))

    console.print()
    console.print(
        f"[dim]Session {result.session_id} • turn {result.turn_index} • "
        f"{result.retrieved} chunks • {result.latency_ms:.0f}ms[/dim]"
    )
    console.print()


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------


def cmd_feedback(args: argparse.Namespace) -> None:
    """Record answer quality feedback."""
    from services.cli.remote import _feedback_remote
    from services.core.config import get_settings
    from services.core.database import ensure_feedback_table, get_connection, insert_feedback
    from services.core.logging import setup_logging

    settings = get_settings()
    setup_logging("ERROR")

    payload = {
        "verdict": args.verdict,
        "collection": args.collection or "default",
        "session_id": args.session_id,
        "mode": args.mode,
        "question": args.question,
        "answer": args.answer,
        "comment": args.comment,
        "citations": [],
        "metadata": {},
    }
    if args.citations_json:
        import json

        payload["citations"] = json.loads(args.citations_json)
    if args.metadata_json:
        import json

        payload["metadata"] = json.loads(args.metadata_json)

    if args.api_url:
        result = _feedback_remote(args.api_url, payload, api_key=args.api_key)
        feedback_id = result.get("feedback_id")
        principal = result.get("principal", "unknown")
    else:
        conn = get_connection(settings)
        try:
            ensure_feedback_table(conn)
            feedback_id = insert_feedback(
                conn,
                verdict=str(payload["verdict"]),
                collection=str(payload["collection"]),
                mode=str(payload["mode"]),
                session_id=str(payload["session_id"]) if payload["session_id"] else None,
                question=str(payload["question"]) if payload["question"] else None,
                answer=str(payload["answer"]) if payload["answer"] else None,
                comment=str(payload["comment"]) if payload["comment"] else None,
                citations=payload["citations"] if isinstance(payload["citations"], list) else [],
                metadata=payload["metadata"] if isinstance(payload["metadata"], dict) else {},
            )
        finally:
            conn.close()
        principal = "local_cli"

    if args.json:
        import json

        print(
            json.dumps(
                {"status": "ok", "feedback_id": feedback_id, "principal": principal},
                indent=2,
            )
        )
        return

    console.print()
    console.print(
        Panel(
            f"[bold green]Feedback recorded[/bold green]\n\n"
            f"[cyan]Feedback ID:[/cyan] {feedback_id}\n"
            f"[cyan]Verdict:[/cyan] {args.verdict}\n"
            f"[cyan]Collection:[/cyan] {payload['collection']}\n"
            f"[cyan]Principal:[/cyan] {principal}",
            title="ragops feedback",
            border_style="green",
        )
    )
    console.print()


# ---------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------


def cmd_eval(args: argparse.Namespace) -> None:
    """Run dataset-driven evaluation and emit reports."""
    from services.cli.eval import load_eval_cases, render_markdown_report, run_eval
    from services.cli.project import find_project_root, load_config
    from services.core.config import get_settings
    from services.core.logging import setup_logging
    from services.core.providers import get_embedding_provider, get_llm_provider

    root = find_project_root() or Path.cwd()
    config = load_config(root)
    default_collection = args.collection or config.name or root.name
    settings = get_settings()
    setup_logging("ERROR")

    dataset_path = Path(args.dataset).resolve()
    output_json = Path(args.output_json).resolve()
    output_md = Path(args.output_md).resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)

    embed_provider = get_embedding_provider(settings)
    llm_provider = None if args.retrieval_only else get_llm_provider(settings)

    with console.status("[bold cyan]Running evaluation...[/bold cyan]", spinner="dots"):
        cases = load_eval_cases(dataset_path, default_collection=default_collection)
        report = run_eval(
            cases=cases,
            embedding_provider=embed_provider,
            llm_provider=llm_provider,
            top_k=args.top_k,
            settings=settings,
        )

    import json

    output_json.write_text(json.dumps(report, indent=2))
    output_md.write_text(render_markdown_report(report))

    if args.json:
        print(json.dumps(report, indent=2))
        return

    summary = report["summary"]
    console.print()
    console.print(
        Panel(
            f"[bold green]Evaluation complete[/bold green]\n\n"
            f"[cyan]Cases:[/cyan] {summary['total_cases']}\n"
            f"[cyan]Source hit rate:[/cyan] {summary['source_hit_rate']:.2%}\n"
            f"[cyan]Answer hit rate:[/cyan] {summary['answer_hit_rate']:.2%}\n"
            f"[cyan]Passed-all rate:[/cyan] {summary['passed_all_rate']:.2%}\n"
            f"[cyan]Avg latency:[/cyan] {summary['avg_latency_ms']} ms\n\n"
            f"[cyan]JSON report:[/cyan] {output_json}\n"
            f"[cyan]Markdown report:[/cyan] {output_md}",
            title="ragops eval",
            border_style="green",
        )
    )
    console.print()


# ---------------------------------------------------------------------------
# generate-docs
# ---------------------------------------------------------------------------


def cmd_generate_docs(args: argparse.Namespace) -> None:
    """Generate documentation from project source code."""
    from services.cli.docgen.analyzer import Analyzer
    from services.cli.docgen.generator import DocGenerator
    from services.cli.project import find_project_root
    from services.core.config import get_settings
    from services.core.logging import setup_logging
    from services.core.providers import get_llm_provider

    root = find_project_root() or Path.cwd()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    setup_logging("ERROR")

    llm_provider = get_llm_provider(settings)
    if not llm_provider:
        console.print(
            "\n[red]Error:[/red] LLM is not enabled. "
            "Set [bold]LLM_ENABLED=true[/bold] and [bold]OPENAI_API_KEY[/bold] (or Ollama) in .env"
        )
        sys.exit(1)

    analyzer = Analyzer(root)
    generator = DocGenerator(llm_provider)

    with console.status(
        f"[bold cyan]Analyzing {root.name} and generating docs...[/bold cyan]",
        spinner="dots",
    ):
        # 1. Analyze code
        ctx = analyzer.analyze()

        # 2. Generate documents
        docs = {
            "README.md": generator.generate_readme(ctx),
            "ARCHITECTURE.md": generator.generate_architecture(ctx),
            "API.md": generator.generate_api(ctx),
        }

        # 3. Save files
        for filename, content in docs.items():
            path = output_dir / filename
            path.write_text(content)

    console.print()
    console.print(
        Panel(
            f"[bold green]✅ Documentation generated![/bold green]\n\n"
            f"[cyan]Output directory:[/cyan] {args.output}\n"
            f"[cyan]Files created:[/cyan]\n"
            f"  • README.md\n"
            f"  • ARCHITECTURE.md\n"
            f"  • API.md\n\n"
            f"[dim]Next step: ragops ingest --dir {args.output}[/dim]",
            title="📚 ragops generate-docs",
            border_style="green",
        )
    )
    console.print()


# ---------------------------------------------------------------------------
# generate-manuals
# ---------------------------------------------------------------------------


def cmd_generate_manuals(args: argparse.Namespace) -> None:
    """Generate deterministic onboarding manuals from code, API, and DB metadata."""
    from services.cli.docgen.manuals import ManualPackGenerator
    from services.cli.project import find_project_root, load_config
    from services.core.config import get_settings
    from services.core.logging import setup_logging

    root = find_project_root() or Path.cwd()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    setup_logging("ERROR")

    generator = ManualPackGenerator(root)
    include_db = not args.no_db

    with console.status(
        f"[bold cyan]Generating manuals for {root.name}...[/bold cyan]",
        spinner="dots",
    ):
        result = generator.generate(
            output_dir=output_dir,
            include_db=include_db,
            settings=settings if include_db else None,
        )

        ingest_summary = ""
        if args.ingest:
            from services.core.providers import get_embedding_provider
            from services.ingest.app.pipeline import ingest_local_directory

            config = load_config(root)
            collection = args.collection or config.name or root.name
            provider = get_embedding_provider(settings)
            stats = ingest_local_directory(
                directory=output_dir,
                embedding_provider=provider,
                collection=collection,
                settings=settings,
            )
            ingest_summary = (
                "\n\n[cyan]Manual ingestion:[/cyan] "
                f"{stats.indexed_docs} indexed, {stats.skipped_docs} skipped, "
                f"{stats.total_chunks} chunks into '{collection}'"
            )

    files_list = "\n".join(f"  • {path.name}" for path in result.files)
    db_line = {
        "ok": "[green]OK[/green]",
        "degraded": "[yellow]Degraded[/yellow]",
        "skipped": "[dim]Skipped[/dim]",
    }.get(result.db_status, result.db_status)

    summary = (
        "[bold green]Manual pack generated[/bold green]\n\n"
        f"[cyan]Project:[/cyan] {root.name}\n"
        f"[cyan]Output:[/cyan] {args.output}\n"
        f"[cyan]Database snapshot:[/cyan] {db_line}\n"
        f"[cyan]Files:[/cyan]\n{files_list}"
        f"{ingest_summary}"
    )
    if result.db_error:
        summary += f"\n\n[yellow]DB error:[/yellow] {result.db_error}"

    console.print()
    console.print(Panel(summary, title="ragops generate-manuals", border_style="green"))
    console.print()


# ---------------------------------------------------------------------------
# repo
# ---------------------------------------------------------------------------


def _repo_ingest_and_manuals(
    *,
    repo_dir: Path,
    collection: str,
    project_root: Path,
    settings: object,
    skip_ingest: bool,
    generate_manuals: bool,
    manuals_output: str | None,
) -> tuple[object | None, object | None, Path | None]:
    """Optionally ingest repo and generate manuals."""
    from services.cli.docgen.manuals import ManualPackGenerator
    from services.core.providers import get_embedding_provider
    from services.ingest.app.pipeline import ingest_local_directory

    ingest_stats = None
    manual_ingest_stats = None
    manual_output_dir: Path | None = None

    if not skip_ingest:
        provider = get_embedding_provider(settings)
        ingest_stats = ingest_local_directory(
            directory=str(repo_dir),
            embedding_provider=provider,
            collection=collection,
            settings=settings,
        )

    if generate_manuals:
        manual_output_dir = (
            Path(manuals_output).expanduser().resolve()
            if manuals_output
            else project_root / "manuals" / repo_dir.name
        )
        manual_output_dir.mkdir(parents=True, exist_ok=True)
        generator = ManualPackGenerator(repo_dir)
        generator.generate(output_dir=manual_output_dir, include_db=False, settings=None)

        if not skip_ingest:
            provider = get_embedding_provider(settings)
            manual_ingest_stats = ingest_local_directory(
                directory=str(manual_output_dir),
                embedding_provider=provider,
                collection=collection,
                settings=settings,
            )

    return ingest_stats, manual_ingest_stats, manual_output_dir


def cmd_repo_add(args: argparse.Namespace) -> None:
    """Clone a GitHub repo and register it for sync/query workflows."""
    import os

    from services.cli.project import find_project_root
    from services.cli.repositories import (
        RepoRecord,
        build_authenticated_clone_url,
        clone_repo,
        default_repo_cache_dir,
        default_repo_name,
        load_repo_registry,
        now_utc_iso,
        parse_github_repo_url,
        save_repo_registry,
        sync_repo,
    )
    from services.core.config import get_settings
    from services.core.logging import setup_logging

    project_root = find_project_root() or Path.cwd()
    settings = get_settings()
    setup_logging("ERROR")

    canonical_url, owner, repo = parse_github_repo_url(args.repo_url)
    repo_name = args.name or default_repo_name(owner, repo)
    collection = args.collection or repo_name
    token = args.github_token or os.getenv("GITHUB_TOKEN")

    cache_dir = (
        Path(args.cache_dir).expanduser().resolve()
        if args.cache_dir
        else default_repo_cache_dir(project_root)
    )
    repo_dir = cache_dir / repo_name
    repos = load_repo_registry(project_root)

    if repo_name in repos and not args.force:
        console.print(
            f"[red]Error:[/red] Repository '{repo_name}' already exists. "
            f"Use [bold]ragops repo sync {repo_name}[/bold] or pass [bold]--force[/bold]."
        )
        sys.exit(1)

    with console.status(
        f"[bold cyan]Preparing repo {repo_name}...[/bold cyan]",
        spinner="dots",
    ):
        if (repo_dir / ".git").exists():
            active_ref = sync_repo(destination=repo_dir, ref=args.ref)
        else:
            clone_url = build_authenticated_clone_url(canonical_url, token)
            clone_repo(clone_url=clone_url, destination=repo_dir, ref=args.ref)
            active_ref = args.ref or "default"

        ingest_stats, manual_ingest_stats, manual_output_dir = _repo_ingest_and_manuals(
            repo_dir=repo_dir,
            collection=collection,
            project_root=project_root,
            settings=settings,
            skip_ingest=args.skip_ingest,
            generate_manuals=args.generate_manuals,
            manuals_output=args.manuals_output,
        )

    timestamp = now_utc_iso()
    previous = repos.get(repo_name)
    repos[repo_name] = RepoRecord(
        name=repo_name,
        url=canonical_url,
        collection=collection,
        local_path=str(repo_dir),
        ref=args.ref or (previous.ref if previous else None),
        manuals_enabled=bool(args.generate_manuals),
        manuals_output=str(manual_output_dir) if manual_output_dir else None,
        added_at=previous.added_at if previous and previous.added_at else timestamp,
        last_sync_at=timestamp,
    )
    registry_file = save_repo_registry(project_root, repos)

    if args.json:
        import json

        payload: dict[str, object] = {
            "status": "ok",
            "name": repo_name,
            "url": canonical_url,
            "collection": collection,
            "local_path": str(repo_dir),
            "ref": active_ref,
            "registry": str(registry_file),
        }
        if ingest_stats:
            payload["ingest"] = {
                "indexed_docs": ingest_stats.indexed_docs,
                "skipped_docs": ingest_stats.skipped_docs,
                "total_chunks": ingest_stats.total_chunks,
            }
        if manual_ingest_stats:
            payload["manual_ingest"] = {
                "indexed_docs": manual_ingest_stats.indexed_docs,
                "skipped_docs": manual_ingest_stats.skipped_docs,
                "total_chunks": manual_ingest_stats.total_chunks,
            }
        print(json.dumps(payload, indent=2))
        return

    lines = [
        "[bold green]Repository ready[/bold green]",
        "",
        f"[cyan]Name:[/cyan] {repo_name}",
        f"[cyan]URL:[/cyan] {canonical_url}",
        f"[cyan]Local path:[/cyan] {repo_dir}",
        f"[cyan]Collection:[/cyan] {collection}",
        f"[cyan]Ref:[/cyan] {active_ref}",
        f"[cyan]Registry:[/cyan] {registry_file}",
    ]
    if ingest_stats:
        lines.append(
            f"[cyan]Ingest:[/cyan] {ingest_stats.indexed_docs} indexed, "
            f"{ingest_stats.skipped_docs} skipped, {ingest_stats.total_chunks} chunks"
        )
    if manual_ingest_stats:
        lines.append(
            f"[cyan]Manual ingest:[/cyan] {manual_ingest_stats.indexed_docs} indexed, "
            f"{manual_ingest_stats.skipped_docs} skipped, {manual_ingest_stats.total_chunks} chunks"
        )
    console.print()
    console.print(Panel("\n".join(lines), title="ragops repo add", border_style="green"))
    console.print()


def cmd_repo_sync(args: argparse.Namespace) -> None:
    """Pull one or all registered repositories and refresh index/manuals."""
    from services.cli.project import find_project_root
    from services.cli.repositories import (
        RepoRecord,
        load_repo_registry,
        now_utc_iso,
        save_repo_registry,
        sync_repo,
    )
    from services.core.config import get_settings
    from services.core.logging import setup_logging

    project_root = find_project_root() or Path.cwd()
    settings = get_settings()
    setup_logging("ERROR")

    repos = load_repo_registry(project_root)
    if not repos:
        console.print("[red]Error:[/red] No repos registered. Use [bold]ragops repo add[/bold].")
        sys.exit(1)

    if args.all:
        target_names = sorted(repos.keys())
    else:
        if not args.name:
            console.print("[red]Error:[/red] Provide repo name or use [bold]--all[/bold].")
            sys.exit(1)
        if args.name not in repos:
            console.print(f"[red]Error:[/red] Unknown repo '{args.name}'.")
            sys.exit(1)
        target_names = [args.name]

    results: list[dict[str, object]] = []
    with console.status("[bold cyan]Syncing repositories...[/bold cyan]", spinner="dots"):
        for name in target_names:
            record = repos[name]
            repo_dir = Path(record.local_path).expanduser().resolve()
            active_ref = sync_repo(destination=repo_dir, ref=args.ref or record.ref)
            generate_manuals = bool(args.generate_manuals or record.manuals_enabled)
            manuals_output = args.manuals_output or record.manuals_output

            ingest_stats, manual_ingest_stats, manual_output_dir = _repo_ingest_and_manuals(
                repo_dir=repo_dir,
                collection=record.collection,
                project_root=project_root,
                settings=settings,
                skip_ingest=args.skip_ingest,
                generate_manuals=generate_manuals,
                manuals_output=manuals_output,
            )

            updated = RepoRecord(
                name=record.name,
                url=record.url,
                collection=record.collection,
                local_path=record.local_path,
                ref=args.ref or record.ref,
                manuals_enabled=generate_manuals,
                manuals_output=str(manual_output_dir) if manual_output_dir else manuals_output,
                added_at=record.added_at,
                last_sync_at=now_utc_iso(),
            )
            repos[name] = updated
            results.append(
                {
                    "name": name,
                    "ref": active_ref,
                    "ingest_stats": ingest_stats,
                    "manual_ingest_stats": manual_ingest_stats,
                }
            )

    registry_file = save_repo_registry(project_root, repos)

    if args.json:
        import json

        payload = {
            "status": "ok",
            "registry": str(registry_file),
            "results": [
                {
                    "name": row["name"],
                    "ref": row["ref"],
                    "ingest": (
                        {
                            "indexed_docs": row["ingest_stats"].indexed_docs,
                            "skipped_docs": row["ingest_stats"].skipped_docs,
                            "total_chunks": row["ingest_stats"].total_chunks,
                        }
                        if row["ingest_stats"]
                        else None
                    ),
                    "manual_ingest": (
                        {
                            "indexed_docs": row["manual_ingest_stats"].indexed_docs,
                            "skipped_docs": row["manual_ingest_stats"].skipped_docs,
                            "total_chunks": row["manual_ingest_stats"].total_chunks,
                        }
                        if row["manual_ingest_stats"]
                        else None
                    ),
                }
                for row in results
            ],
        }
        print(json.dumps(payload, indent=2))
        return

    table = Table(title="🔄 Repo Sync", show_header=True, header_style="bold cyan")
    table.add_column("Repo", style="cyan")
    table.add_column("Ref", style="yellow")
    table.add_column("Ingest", style="green")
    table.add_column("Manuals", style="magenta")
    for row in results:
        ingest_stats = row["ingest_stats"]
        manual_ingest_stats = row["manual_ingest_stats"]
        ingest_text = (
            f"{ingest_stats.indexed_docs} idx / {ingest_stats.total_chunks} chunks"
            if ingest_stats
            else "skipped"
        )
        manuals_text = (
            f"{manual_ingest_stats.indexed_docs} idx / {manual_ingest_stats.total_chunks} chunks"
            if manual_ingest_stats
            else "skipped"
        )
        table.add_row(str(row["name"]), str(row["ref"]), ingest_text, manuals_text)

    console.print()
    console.print(table)
    console.print(f"[dim]Registry updated: {registry_file}[/dim]")
    console.print()


def cmd_repo_list(args: argparse.Namespace) -> None:
    """List tracked repositories."""
    from services.cli.project import find_project_root
    from services.cli.repositories import load_repo_registry

    project_root = find_project_root() or Path.cwd()
    repos = load_repo_registry(project_root)

    if args.json:
        import json

        print(
            json.dumps(
                {"repos": [record.to_dict() for _, record in sorted(repos.items())]},
                indent=2,
            )
        )
        return

    if not repos:
        console.print("\n[dim]No repos registered yet. Use `ragops repo add <github-url>`.[/dim]\n")
        return

    table = Table(title="📚 Tracked Repositories", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="cyan")
    table.add_column("Collection", style="green")
    table.add_column("Ref", style="yellow")
    table.add_column("Local Path", style="dim")
    table.add_column("Last Sync", style="magenta")
    for name, record in sorted(repos.items()):
        table.add_row(
            name,
            record.collection,
            record.ref or "default",
            record.local_path,
            record.last_sync_at or "never",
        )

    console.print()
    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------


def cmd_providers(args: argparse.Namespace) -> None:
    """Show available LLM and embedding providers."""
    from services.core.config import get_settings

    settings = get_settings()

    llm_providers = {
        "openai": {
            "name": "OpenAI",
            "models": "gpt-4o, gpt-4o-mini",
            "key": "OPENAI_API_KEY",
            "features": "LLM + Embed",
        },
        "gemini": {
            "name": "Google Gemini",
            "models": "gemini-2.0-flash",
            "key": "GEMINI_API_KEY",
            "features": "LLM + Embed",
        },
        "claude": {
            "name": "Anthropic Claude",
            "models": "claude-sonnet-4-20250514",
            "key": "ANTHROPIC_API_KEY",
            "features": "LLM only",
        },
        "groq": {
            "name": "Groq",
            "models": "llama-3.3-70b-versatile",
            "key": "GROQ_API_KEY",
            "features": "LLM only (fast)",
        },
        "ollama": {
            "name": "Ollama (Local)",
            "models": "llama3, mistral, etc.",
            "key": "(none)",
            "features": "LLM + Embed",
        },
    }

    table = Table(
        title="🔌 Available Providers",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("ID", style="bold", width=10)
    table.add_column("Provider", min_width=18)
    table.add_column("Models", min_width=20)
    table.add_column("Features", width=16)
    table.add_column("Key", style="dim", width=18)
    table.add_column("Active", justify="center", width=8)

    for pid, info in llm_providers.items():
        is_llm = settings.llm_provider == pid
        is_embed = settings.embedding_provider == pid
        active_parts = []
        if is_llm:
            active_parts.append("LLM")
        if is_embed:
            active_parts.append("Embed")
        active = (
            "[bold green]" + ", ".join(active_parts) + "[/bold green]"
            if active_parts
            else "[dim]—[/dim]"
        )

        table.add_row(
            pid, info["name"], info["models"],
            info["features"], info["key"], active,
        )


    console.print()
    console.print(table)
    console.print()
    console.print(
        "[dim]Configure in .env:[/dim]\n"
        "  LLM_PROVIDER=gemini\n"
        "  EMBEDDING_PROVIDER=openai\n"
        "  GEMINI_API_KEY=your-key-here"
    )
    console.print()


# ---------------------------------------------------------------------------
# main parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the ragops CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="ragops",
        description="RAG Ops — Query any codebase with AI",
    )
    parser.add_argument("--version", action="version", version="ragops 2.0.0")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # --- init ---
    p_init = sub.add_parser("init", help="Initialize ragops in a project")
    p_init.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Project directory (default: current dir)",
    )
    p_init.add_argument("--name", help="Project name (auto-detected if omitted)")
    p_init.set_defaults(func=cmd_init)

    # --- ingest ---
    p_ingest = sub.add_parser("ingest", help="Index docs and code")
    p_ingest.add_argument(
        "--dir",
        help="Specific directory to ingest (overrides config)",
    )
    p_ingest.add_argument(
        "--path",
        help="Project root (default: auto-detected)",
    )
    p_ingest.add_argument(
        "--project",
        help="Project name (overrides config)",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    # --- query ---
    p_query = sub.add_parser("query", help="Ask questions about your project")
    p_query.add_argument("question", help="Your question")
    p_query.add_argument(
        "--project",
        help="Project name (overrides config)",
    )
    p_query.add_argument(
        "--collection",
        help="Collection name (defaults to project name)",
    )
    p_query.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of results",
    )
    p_query.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON",
    )
    p_query.add_argument(
        "--api-url",
        help="Query a remote RAG Ops API (e.g. AWS endpoint)",
    )
    p_query.add_argument(
        "--api-key",
        help="API key header value for secured remote APIs",
    )
    p_query.set_defaults(func=cmd_query)

    # --- chat ---
    p_chat = sub.add_parser("chat", help="Multi-turn chat about your project")
    p_chat.add_argument("question", help="Your question")
    p_chat.add_argument(
        "--project",
        help="Project name (overrides config)",
    )
    p_chat.add_argument(
        "--collection",
        help="Collection name (defaults to project name)",
    )
    p_chat.add_argument(
        "--session-id",
        help="Session id to continue an existing chat",
    )
    p_chat.add_argument(
        "--mode",
        default="default",
        choices=["default", "explain_like_junior", "show_where_in_code", "step_by_step"],
        help="Response style mode",
    )
    p_chat.add_argument(
        "--answer-style",
        default="concise",
        choices=["concise", "detailed"],
        help="Answer verbosity/style profile",
    )
    p_chat.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of retrieval results",
    )
    p_chat.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON",
    )
    p_chat.add_argument(
        "--api-url",
        help="Chat against a remote RAG Ops API (base URL or /v1/chat endpoint)",
    )
    p_chat.add_argument(
        "--api-key",
        help="API key header value for secured remote APIs",
    )
    p_chat.add_argument(
        "--show-context",
        action="store_true",
        help="Request and print raw retrieved context snippets",
    )
    p_chat.set_defaults(func=cmd_chat)

    # --- feedback ---
    p_feedback = sub.add_parser("feedback", help="Submit answer quality feedback")
    p_feedback.add_argument(
        "--verdict",
        required=True,
        choices=["positive", "negative"],
        help="Feedback label",
    )
    p_feedback.add_argument(
        "--collection",
        default="default",
        help="Collection name",
    )
    p_feedback.add_argument(
        "--session-id",
        help="Chat session id (optional)",
    )
    p_feedback.add_argument(
        "--mode",
        default="default",
        help="Mode label for analytics",
    )
    p_feedback.add_argument(
        "--question",
        help="Question text (optional)",
    )
    p_feedback.add_argument(
        "--answer",
        help="Answer text (optional)",
    )
    p_feedback.add_argument(
        "--comment",
        help="Free-text comment (optional)",
    )
    p_feedback.add_argument(
        "--citations-json",
        help="JSON array of citations (optional)",
    )
    p_feedback.add_argument(
        "--metadata-json",
        help="JSON object of metadata (optional)",
    )
    p_feedback.add_argument(
        "--api-url",
        help="Remote API base URL or /v1/feedback endpoint",
    )
    p_feedback.add_argument(
        "--api-key",
        help="API key header value for secured remote APIs",
    )
    p_feedback.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON",
    )
    p_feedback.set_defaults(func=cmd_feedback)

    # --- eval ---
    p_eval = sub.add_parser("eval", help="Run dataset-based quality evaluation")
    p_eval.add_argument(
        "--dataset",
        required=True,
        help="Path to JSON or YAML eval dataset",
    )
    p_eval.add_argument(
        "--collection",
        help="Default collection for cases that omit collection",
    )
    p_eval.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Retrieval depth",
    )
    p_eval.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Disable LLM generation and evaluate retrieval-only mode",
    )
    p_eval.add_argument(
        "--output-json",
        default="./eval/eval-report.json",
        help="Path to JSON report",
    )
    p_eval.add_argument(
        "--output-md",
        default="./eval/eval-report.md",
        help="Path to markdown report",
    )
    p_eval.add_argument(
        "--json",
        action="store_true",
        help="Print JSON report to stdout",
    )
    p_eval.set_defaults(func=cmd_eval)

    # --- generate-docs ---
    p_docs = sub.add_parser("generate-docs", help="Auto-generate docs from source code")
    p_docs.add_argument(
        "--output",
        default="./docs",
        help="Output directory (default: ./docs)",
    )
    p_docs.set_defaults(func=cmd_generate_docs)

    # --- generate-manuals ---
    p_manuals = sub.add_parser(
        "generate-manuals",
        help="Generate onboarding manuals (codebase, API, database)",
    )
    p_manuals.add_argument(
        "--output",
        default="./manuals",
        help="Output directory (default: ./manuals)",
    )
    p_manuals.add_argument(
        "--no-db",
        action="store_true",
        help="Skip database schema introspection",
    )
    p_manuals.add_argument(
        "--ingest",
        action="store_true",
        help="Ingest generated manuals into the vector store",
    )
    p_manuals.add_argument(
        "--collection",
        help="Collection name used with --ingest (defaults to project name)",
    )
    p_manuals.set_defaults(func=cmd_generate_manuals)

    # --- providers ---
    p_providers = sub.add_parser("providers", help="Show available LLM/Embedding providers")
    p_providers.set_defaults(func=cmd_providers)

    # --- repo ---
    p_repo = sub.add_parser("repo", help="Manage GitHub repositories for indexing and chat")
    repo_sub = p_repo.add_subparsers(dest="repo_command", help="Repo commands")
    repo_sub.required = True

    p_repo_add = repo_sub.add_parser("add", help="Clone/register a GitHub repo and ingest it")
    p_repo_add.add_argument("repo_url", help="GitHub URL (https://github.com/org/repo or git@...)")
    p_repo_add.add_argument("--name", help="Local repo key (default: owner-repo)")
    p_repo_add.add_argument("--collection", help="Collection name (default: repo key)")
    p_repo_add.add_argument("--ref", help="Branch or tag to checkout")
    p_repo_add.add_argument("--cache-dir", help="Clone cache directory")
    p_repo_add.add_argument("--github-token", help="GitHub token (defaults to GITHUB_TOKEN env)")
    p_repo_add.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Register/clone repo without ingesting",
    )
    p_repo_add.add_argument(
        "--generate-manuals",
        action="store_true",
        help="Generate onboarding manuals after clone/sync",
    )
    p_repo_add.add_argument("--manuals-output", help="Manuals output directory")
    p_repo_add.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing registry entry for this repo key",
    )
    p_repo_add.add_argument("--json", action="store_true", help="Output raw JSON")
    p_repo_add.set_defaults(func=cmd_repo_add)

    p_repo_sync = repo_sub.add_parser("sync", help="Pull and refresh registered repositories")
    p_repo_sync.add_argument("name", nargs="?", help="Repo key from registry")
    p_repo_sync.add_argument("--all", action="store_true", help="Sync all repositories")
    p_repo_sync.add_argument("--ref", help="Override branch/tag for this sync run")
    p_repo_sync.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Update git clone but skip ingest",
    )
    p_repo_sync.add_argument(
        "--generate-manuals",
        action="store_true",
        help="Generate manuals during sync",
    )
    p_repo_sync.add_argument("--manuals-output", help="Manuals output directory")
    p_repo_sync.add_argument("--json", action="store_true", help="Output raw JSON")
    p_repo_sync.set_defaults(func=cmd_repo_sync)

    p_repo_list = repo_sub.add_parser("list", help="List registered repositories")
    p_repo_list.add_argument("--json", action="store_true", help="Output raw JSON")
    p_repo_list.set_defaults(func=cmd_repo_list)

    return parser


def main() -> None:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
