"""ragops — CLI entrypoint for the RAG Ops Platform."""

from __future__ import annotations

import argparse
import getpass
import importlib.metadata
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console()


def _read_env_value(env_path: Path, key: str) -> str:
    """Read simple KEY=VALUE pair from .env file."""
    if not env_path.exists():
        return ""
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key.strip() == key:
            return value.strip()
    return ""


def _upsert_env_values(env_path: Path, updates: dict[str, str]) -> None:
    """Upsert env vars while preserving unrelated lines."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    index_by_key: dict[str, int] = {}
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw:
            continue
        key = raw.split("=", 1)[0].strip()
        if key and key not in index_by_key:
            index_by_key[key] = idx

    for key, value in updates.items():
        rendered = f"{key}={value}"
        if key in index_by_key:
            lines[index_by_key[key]] = rendered
        else:
            lines.append(rendered)

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _apply_user_profile_defaults() -> None:
    """Apply ~/.ragops/config.yaml defaults into env when keys are missing."""
    from services.cli.user_config import load_user_config

    profile = load_user_config()
    if not profile:
        return

    candidates = {
        "OPENAI_API_KEY": str(profile.get("openai_api_key", "")).strip(),
        "LLM_ENABLED": str(profile.get("llm_enabled", "")).strip(),
        "STORAGE_BACKEND": str(profile.get("storage_backend", "")).strip(),
        "LOCAL_DB_PATH": str(profile.get("local_db_path", "")).strip(),
    }
    for key, value in candidates.items():
        if value and not os.getenv(key):
            os.environ[key] = value


def _coerce_bool(value: object, default: bool = False) -> bool:
    """Coerce mixed config values into bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _run_git(root: Path, args: list[str]) -> str:
    """Run a git command and return stdout or raise RuntimeError."""
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "git command failed"
        raise RuntimeError(detail)
    return proc.stdout


def _git_changed_paths(root: Path, *, base_ref: str = "HEAD") -> tuple[set[str], str]:
    """Return changed and untracked file paths relative to repo root."""
    try:
        inside = _run_git(root, ["rev-parse", "--is-inside-work-tree"]).strip().lower()
        if inside != "true":
            return set(), "not_git_repo"
    except Exception:
        return set(), "not_git_repo"

    changed: set[str] = set()
    mode = f"diff:{base_ref}"

    try:
        diff_out = _run_git(root, ["diff", "--name-only", "--diff-filter=ACMRTUXB", base_ref, "--"])
        changed.update(line.strip() for line in diff_out.splitlines() if line.strip())
    except RuntimeError as exc:
        msg = str(exc).lower()
        if "unknown revision" in msg or "bad revision" in msg or "ambiguous argument" in msg:
            tracked_out = _run_git(root, ["ls-files"])
            changed.update(line.strip() for line in tracked_out.splitlines() if line.strip())
            mode = "ls-files"
        else:
            raise

    untracked_out = _run_git(root, ["ls-files", "--others", "--exclude-standard"])
    changed.update(line.strip() for line in untracked_out.splitlines() if line.strip())

    rel_files: set[str] = set()
    for rel in changed:
        rel_norm = rel.replace("\\", "/").lstrip("./")
        candidate = (root / rel_norm).resolve()
        if candidate.is_file():
            rel_files.add(rel_norm)
    return rel_files, mode


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
    from services.cli.user_config import load_user_config, save_user_config, user_config_path
    from services.core.config import Settings
    from services.core.storage import resolve_storage_backend

    project_dir = Path(args.path).resolve()
    if not project_dir.exists():
        console.print(f"[red]Error:[/red] Directory '{args.path}' does not exist")
        sys.exit(1)

    # Detect or use provided name
    name = args.name or detect_project_name(project_dir)

    config = ProjectConfig(name=name)
    config_path = save_config(config, project_dir)
    env_path = project_dir / ".env"
    profile = load_user_config()
    profile_key = str(profile.get("openai_api_key", "")).strip()

    existing_key = _read_env_value(env_path, "OPENAI_API_KEY")
    openai_key = (
        (args.openai_api_key or "").strip()
        or existing_key
        or os.getenv("OPENAI_API_KEY", "").strip()
        or profile_key
    )
    if not openai_key and not args.no_prompt and sys.stdin.isatty():
        openai_key = getpass.getpass("OPENAI_API_KEY (optional, press Enter to skip): ").strip()

    env_updates = {
        "STORAGE_BACKEND": args.storage_backend,
        "LOCAL_DB_PATH": args.local_db_path,
    }
    if args.llm_enabled is not None:
        env_updates["LLM_ENABLED"] = args.llm_enabled
    elif openai_key:
        env_updates["LLM_ENABLED"] = "true"
    if openai_key:
        env_updates["OPENAI_API_KEY"] = openai_key
    _upsert_env_values(env_path, env_updates)

    user_cfg_path = user_config_path()
    profile_action = "unchanged"
    if openai_key and not args.no_global_config:
        save_user_config(
            {
                "openai_api_key": openai_key,
                "llm_enabled": True,
                "storage_backend": args.storage_backend,
                "local_db_path": args.local_db_path,
            }
        )
        profile_action = "updated"

    resolved_backend = resolve_storage_backend(
        Settings(
            _env_file=None,
            STORAGE_BACKEND=args.storage_backend,
            DATABASE_URL="",
            NEON_CONNECTION_STRING="",
            ENVIRONMENT="local",
        )
    )
    key_status = "set" if bool(openai_key) else "not set"

    console.print()
    console.print(
        Panel(
            f"[bold green]✅ Initialized ragops[/bold green]\n\n"
            f"[cyan]Project:[/cyan] {name}\n"
            f"[cyan]Config:[/cyan] {config_path.relative_to(project_dir)}\n\n"
            f"[cyan]Env:[/cyan] {env_path.relative_to(project_dir)}\n"
            f"[cyan]Global config:[/cyan] {user_cfg_path} ({profile_action})\n"
            f"[cyan]Storage:[/cyan] {resolved_backend}\n"
            f"[cyan]OPENAI_API_KEY:[/cyan] {key_status}\n\n"
            f"[dim]Next steps:[/dim]\n"
            f"  ragops scan     — index this project (plus manuals)\n"
            f"  ragops chat     — ask questions (interactive if no question)",
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
# scan
# ---------------------------------------------------------------------------


def cmd_scan(args: argparse.Namespace) -> None:
    """One-command local indexing workflow for best CLI onboarding UX."""
    from services.cli.docgen.manuals import ManualPackGenerator
    from services.cli.project import find_project_root, load_config
    from services.core.config import get_settings
    from services.core.logging import setup_logging
    from services.core.providers import get_embedding_provider
    from services.ingest.app.pipeline import ingest_local_directory

    root = find_project_root() or Path.cwd()
    config = load_config(root)
    collection = args.collection or config.name or root.name

    settings = get_settings()
    setup_logging("ERROR")
    provider = get_embedding_provider(settings)

    manuals_output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else (root / ".ragops" / "manuals").resolve()
    )
    manuals_output.mkdir(parents=True, exist_ok=True)

    changed_paths: set[str] | None = None
    incremental_mode = "full"
    incremental_warning = ""
    if args.incremental:
        try:
            rel_paths, mode = _git_changed_paths(root, base_ref=args.base_ref)
            incremental_mode = mode
            if mode == "not_git_repo":
                changed_paths = None
                incremental_warning = "No git repository detected; running full scan."
            else:
                changed_paths = rel_paths
        except Exception as exc:
            changed_paths = None
            incremental_mode = "fallback-full"
            incremental_warning = str(exc)

    with console.status("[bold cyan]Scanning project and indexing...[/bold cyan]", spinner="dots"):
        code_stats = ingest_local_directory(
            directory=str(root),
            embedding_provider=provider,
            collection=collection,
            settings=settings,
            extra_ignore_dirs={"manuals"},
            include_paths=changed_paths,
        )
        manuals_stats = None
        manual_files: list[str] = []
        if not args.skip_manuals:
            manual_result = ManualPackGenerator(root).generate(
                output_dir=manuals_output,
                include_db=False,
                settings=None,
            )
            manual_files = [path.name for path in manual_result.files]
            manuals_stats = ingest_local_directory(
                directory=str(manuals_output),
                embedding_provider=provider,
                collection=collection,
                settings=settings,
            )

    if args.json:
        import json

        payload: dict[str, object] = {
            "status": "ok",
            "collection": collection,
            "manuals_output": str(manuals_output),
            "scan_mode": "incremental" if args.incremental else "full",
            "incremental_mode": incremental_mode,
            "changed_files": sorted(changed_paths) if changed_paths is not None else [],
            "code_ingest": {
                "indexed_docs": code_stats.indexed_docs,
                "skipped_docs": code_stats.skipped_docs,
                "total_chunks": code_stats.total_chunks,
            },
            "manual_files": manual_files,
        }
        if manuals_stats:
            payload["manual_ingest"] = {
                "indexed_docs": manuals_stats.indexed_docs,
                "skipped_docs": manuals_stats.skipped_docs,
                "total_chunks": manuals_stats.total_chunks,
            }
        print(json.dumps(payload, indent=2))
        return

    lines = [
        "[bold green]Scan complete[/bold green]",
        "",
        f"[cyan]Collection:[/cyan] {collection}",
        f"[cyan]Scan mode:[/cyan] {'incremental' if args.incremental else 'full'} ({incremental_mode})",
        f"[cyan]Code ingest:[/cyan] {code_stats.indexed_docs} indexed, "
        f"{code_stats.skipped_docs} skipped, {code_stats.total_chunks} chunks",
        f"[cyan]Manuals output:[/cyan] {manuals_output}",
    ]
    if args.incremental and changed_paths is not None:
        lines.append(f"[cyan]Changed files considered:[/cyan] {len(changed_paths)}")
    if incremental_warning:
        lines.append(f"[yellow]Incremental fallback reason:[/yellow] {incremental_warning}")
    if manuals_stats:
        lines.append(
            f"[cyan]Manual ingest:[/cyan] {manuals_stats.indexed_docs} indexed, "
            f"{manuals_stats.skipped_docs} skipped, {manuals_stats.total_chunks} chunks"
        )
    if manual_files:
        lines.append(f"[cyan]Manual files:[/cyan] {', '.join(manual_files)}")
    lines.extend(
        [
            "",
            "[dim]Next:[/dim]",
            f"  ragops chat --collection {collection}",
        ]
    )
    console.print()
    console.print(Panel("\n".join(lines), title="🔎 ragops scan", border_style="green"))
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


@dataclass
class _ChatShellTurn:
    """Single rendered interactive chat turn."""

    question: str
    answer: str
    citations: list[dict[str, object]]
    latency_ms: float
    retrieved: int
    turn_index: int


CHAT_SHELL_MODES = (
    "default",
    "explain_like_junior",
    "show_where_in_code",
    "step_by_step",
)
CHAT_SHELL_STYLES = ("concise", "detailed")


def _ragops_version() -> str:
    """Return installed ragops package version, fallback to project version."""
    try:
        return importlib.metadata.version("ragops")
    except importlib.metadata.PackageNotFoundError:
        return "2.0.0"


def _shell_clock() -> str:
    """Render compact local time for shell header line."""
    return datetime.now().strftime("%H:%M:%S")


def _format_chat_provider_label(settings: object, api_url: str | None) -> str:
    """Build a compact model/provider label for the interactive shell header."""
    if api_url:
        normalized = api_url.removeprefix("https://").removeprefix("http://")
        return f"remote/{normalized}"

    llm_enabled = bool(getattr(settings, "llm_enabled", False))
    if not llm_enabled:
        return "retrieval-only"

    provider = str(getattr(settings, "llm_provider", "openai")).strip().lower() or "openai"
    if provider == "ollama":
        model = str(getattr(settings, "ollama_llm_model", "llama3")).strip() or "llama3"
        return f"{provider}/{model}"
    return provider


def _shorten_home(path: Path) -> str:
    """Render $HOME paths with ~ for compact CLI headers."""
    home = Path.home()
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(home)
        return f"~/{rel}" if str(rel) != "." else "~"
    except ValueError:
        return str(resolved)


def _citation_summary(citations: list[dict[str, object]], *, limit: int = 3) -> str:
    """Create one-line source summary for inline chat transcript rendering."""
    if not citations:
        return ""
    chunks: list[str] = []
    for cite in citations[:limit]:
        source = str(cite.get("source", "unknown")).split("/")[-1]
        line_start = cite.get("line_start", "?")
        line_end = cite.get("line_end", "?")
        chunks.append(f"{source}:L{line_start}-{line_end}")
    remaining = len(citations) - min(len(citations), limit)
    suffix = f" (+{remaining} more)" if remaining > 0 else ""
    return ", ".join(chunks) + suffix


def _citation_signal_summary(
    citations: list[dict[str, object]],
    *,
    source_limit: int = 2,
    signal_limit: int = 3,
) -> str:
    """Create one-line ranking signal summary for shell-mode transcript."""
    if not citations:
        return ""
    pieces: list[str] = []
    for cite in citations[:source_limit]:
        source = str(cite.get("source", "unknown")).split("/")[-1]
        signals = cite.get("ranking_signals", [])
        normalized = [str(s) for s in signals][:signal_limit]
        if not normalized:
            continue
        pieces.append(f"{source}({', '.join(normalized)})")
    if not pieces:
        return ""
    remaining = len(citations) - min(len(citations), source_limit)
    suffix = f" (+{remaining} more sources)" if remaining > 0 else ""
    return "; ".join(pieces) + suffix


def _parse_chat_shell_command(raw: str) -> tuple[str, str]:
    """Parse `/command arg` input. Empty command returns ('', '')."""
    text = raw.strip()
    if not text.startswith("/"):
        return "", ""
    command, _, arg = text[1:].partition(" ")
    return command.strip().lower(), arg.strip()


def _render_chat_shell(
    *,
    root: Path,
    collection: str,
    mode: str,
    answer_style: str,
    session_id: str | None,
    provider_label: str,
    turns: list[_ChatShellTurn],
    show_ranking_signals: bool = False,
    status_message: str = "",
) -> None:
    """Render codex-like chat shell screen for interactive mode."""
    console.clear()
    session_label = session_id or "(new session)"
    console.print(
        f"[cyan]{_shorten_home(root)}[/cyan] [green]{collection}[/green] "
        f"[bright_black]{_shell_clock()}[/bright_black]"
    )
    header = [
        f"[bold]>_ OpenAI ragops[/bold] [dim](v{_ragops_version()})[/dim]",
        "",
        f"[cyan]model:[/cyan] {provider_label}    [dim]/model to change[/dim]",
        f"[cyan]directory:[/cyan] {_shorten_home(root)}",
        f"[cyan]collection:[/cyan] {collection}",
        f"[cyan]session:[/cyan] {session_label}",
        f"[cyan]mode:[/cyan] {mode}    [dim]/model {mode}[/dim]",
        f"[cyan]style:[/cyan] {answer_style}    [dim]/style {answer_style}[/dim]",
        f"[cyan]ranking signals:[/cyan] {'on' if show_ranking_signals else 'off'}",
    ]
    console.print(Panel("\n".join(header), border_style="bright_blue"))
    console.print(
        "Tip: Ask about files, architecture, or flows. Use `/help` for controls."
    )
    console.print()

    recent_turns = turns[-4:]
    if not recent_turns:
        console.print(
            Panel(
                "[dim]No messages yet. Ask anything about this codebase to start.[/dim]",
                border_style="dim",
            )
        )
    else:
        for turn in recent_turns:
            console.print(Panel(Markdown(turn.question), title="you", border_style="green"))
            subtitle = (
                f"turn {turn.turn_index} • {turn.retrieved} chunks • {turn.latency_ms:.0f}ms"
            )
            console.print(
                Panel(
                    Markdown(turn.answer),
                    title="assistant",
                    subtitle=subtitle,
                    border_style="cyan",
                )
            )
            sources = _citation_summary(turn.citations)
            if sources:
                console.print(f"[dim]Sources: {sources}[/dim]")
            if show_ranking_signals:
                signal_summary = _citation_signal_summary(turn.citations)
                if signal_summary:
                    console.print(f"[dim]Signals: {signal_summary}[/dim]")
            console.print()

    if status_message:
        console.print(f"[yellow]{status_message}[/yellow]")
    console.print(
        Panel(
            "[dim]Write question for @filename[/dim]",
            border_style="bright_black",
        )
    )


def cmd_chat(args: argparse.Namespace) -> None:
    """Multi-turn chat with session memory."""
    from services.api.app.chat import chat
    from services.cli.project import find_project_root, load_config
    from services.cli.remote import _chat_remote
    from services.cli.user_config import load_user_config
    from services.core.config import get_settings
    from services.core.logging import setup_logging
    from services.core.providers import get_embedding_provider, get_llm_provider

    root = find_project_root() or Path.cwd()
    config = load_config(root)
    project_name = args.project or config.name or root.name
    collection_name = args.collection or project_name

    settings = get_settings()
    setup_logging("ERROR")
    profile = load_user_config()
    config_show_ranking = _coerce_bool(profile.get("show_ranking_signals"), default=False)
    show_ranking_signals = (
        config_show_ranking
        if args.show_ranking_signals is None
        else bool(args.show_ranking_signals)
    )

    embed_provider = get_embedding_provider(settings)
    llm_provider = get_llm_provider(settings)

    def run_turn(
        question: str,
        session_id: str | None,
        *,
        mode: str,
        answer_style: str,
    ) -> object:
        if not args.json:
            from rich.console import Console

            local_console = Console()
            with local_console.status(
                "[bold cyan]Processing chat turn...[/bold cyan]",
                spinner="dots",
            ):
                if args.api_url:
                    return _chat_remote(
                        question,
                        args.api_url,
                        collection_name,
                        session_id=session_id,
                        mode=mode,
                        answer_style=answer_style,
                        top_k=args.top_k,
                        include_context=args.show_context,
                        include_ranking_signals=show_ranking_signals,
                        api_key=args.api_key,
                    )
                return chat(
                    question=question,
                    embedding_provider=embed_provider,
                    llm_provider=llm_provider,
                    session_id=session_id,
                    mode=mode,
                    answer_style=answer_style,
                    collection=collection_name,
                    top_k=args.top_k,
                    include_ranking_signals=show_ranking_signals,
                    settings=settings,
                )

        if args.api_url:
            return _chat_remote(
                question,
                args.api_url,
                collection_name,
                session_id=session_id,
                mode=mode,
                answer_style=answer_style,
                top_k=args.top_k,
                include_context=args.show_context,
                include_ranking_signals=show_ranking_signals,
                api_key=args.api_key,
            )
        return chat(
            question=question,
            embedding_provider=embed_provider,
            llm_provider=llm_provider,
            session_id=session_id,
            mode=mode,
            answer_style=answer_style,
            collection=collection_name,
            top_k=args.top_k,
            include_ranking_signals=show_ranking_signals,
            settings=settings,
        )

    def render_turn(result: object) -> None:
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
                        "show_ranking_signals": show_ranking_signals,
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
            if show_ranking_signals:
                table.add_column("Signals", style="magenta", min_width=20, max_width=40)
            for i, cite in enumerate(result.citations, 1):
                source = cite.get("source", "unknown")
                source_short = source.split("/")[-1] if "/" in source else source
                lines = f"{cite.get('line_start', '?')}-{cite.get('line_end', '?')}"
                score = f"{cite.get('similarity', 0):.1%}"
                signals = cite.get("ranking_signals", [])
                signal_text = ", ".join(str(s) for s in signals) if signals else "-"
                if show_ranking_signals:
                    table.add_row(str(i), source_short, lines, score, signal_text)
                else:
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

    if args.question:
        render_turn(
            run_turn(
                args.question,
                args.session_id,
                mode=args.mode,
                answer_style=args.answer_style,
            )
        )
        return

    if args.json:
        console.print("[red]Error:[/red] Interactive chat mode does not support --json.")
        sys.exit(1)

    active_session = args.session_id
    current_mode = args.mode
    current_style = args.answer_style
    use_shell_ui = (
        sys.stdin.isatty()
        and sys.stdout.isatty()
        and not args.show_context
    )
    provider_label = _format_chat_provider_label(settings, args.api_url)
    turns: list[_ChatShellTurn] = []
    status_message = ""

    if not use_shell_ui:
        console.print()
        console.print(
            Panel(
                "[bold green]Interactive chat mode[/bold green]\n\n"
                "Type a question and press Enter.\n"
                "Use `exit`, `quit`, or `:q` to finish.",
                title="ragops chat",
                border_style="green",
            )
        )
        console.print()

    while True:
        if use_shell_ui:
            _render_chat_shell(
                root=root,
                collection=collection_name,
                mode=current_mode,
                answer_style=current_style,
                session_id=active_session,
                provider_label=provider_label,
                turns=turns,
                show_ranking_signals=show_ranking_signals,
                status_message=status_message,
            )
            status_message = ""

        try:
            question = (
                console.input("[bold bright_cyan]› [/bold bright_cyan]")
                if use_shell_ui
                else input("you> ")
            ).strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not question:
            continue
        if question.lower() in {"exit", "quit", ":q"}:
            break

        if use_shell_ui:
            command, _arg = _parse_chat_shell_command(question)
            if command:
                if command in {"exit", "quit", "q"}:
                    break
                if command == "clear":
                    turns.clear()
                    status_message = "Transcript cleared."
                    continue
                if command == "new":
                    active_session = None
                    turns.clear()
                    status_message = "Started a new session."
                    continue
                if command == "help":
                    status_message = (
                        "Commands: /help, /clear, /new, /exit, "
                        "/model <mode>, /style <concise|detailed>"
                    )
                    continue
                if command in {"model", "mode"}:
                    next_mode = _arg.strip().lower()
                    if not next_mode:
                        status_message = f"Current mode: {current_mode}"
                        continue
                    if next_mode not in CHAT_SHELL_MODES:
                        status_message = f"Unsupported mode: {next_mode}"
                        continue
                    current_mode = next_mode
                    status_message = f"Mode set to {current_mode}."
                    continue
                if command == "style":
                    next_style = _arg.strip().lower()
                    if not next_style:
                        status_message = f"Current style: {current_style}"
                        continue
                    if next_style not in CHAT_SHELL_STYLES:
                        status_message = f"Unsupported style: {next_style}"
                        continue
                    current_style = next_style
                    status_message = f"Style set to {current_style}."
                    continue
                status_message = f"Unknown command '/{command}'. Try /help."
                continue

        result = run_turn(
            question,
            active_session,
            mode=current_mode,
            answer_style=current_style,
        )
        active_session = result.session_id
        if use_shell_ui:
            turns.append(
                _ChatShellTurn(
                    question=question,
                    answer=result.answer,
                    citations=result.citations,
                    latency_ms=result.latency_ms,
                    retrieved=result.retrieved,
                    turn_index=result.turn_index,
                )
            )
            continue
        render_turn(result)


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------


def cmd_feedback(args: argparse.Namespace) -> None:
    """Record answer quality feedback."""
    from services.cli.remote import _feedback_remote
    from services.core.config import get_settings
    from services.core.logging import setup_logging
    from services.core.storage import ensure_feedback_table, get_connection, insert_feedback

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
    manuals_collection: str | None,
    manuals_output: str | None,
    reset_code_collection: bool = False,
    reset_manuals_collection: bool = False,
) -> tuple[object | None, object | None, Path | None, str | None]:
    """Optionally ingest repo and generate manuals."""
    from services.cli.docgen.manuals import ManualPackGenerator
    from services.core.providers import get_embedding_provider
    from services.core.storage import get_connection, purge_collection_documents
    from services.ingest.app.pipeline import ingest_local_directory

    ingest_stats = None
    manual_ingest_stats = None
    manual_output_dir: Path | None = None
    resolved_manuals_collection: str | None = None

    if not skip_ingest:
        if reset_code_collection:
            conn = get_connection(settings)
            try:
                purge_collection_documents(conn, collection=collection)
            finally:
                conn.close()
        provider = get_embedding_provider(settings)
        ingest_stats = ingest_local_directory(
            directory=str(repo_dir),
            embedding_provider=provider,
            collection=collection,
            settings=settings,
            extra_ignore_dirs={"manuals"},
        )

    if generate_manuals:
        resolved_manuals_collection = manuals_collection or f"{collection}_manuals"
        manual_output_dir = (
            Path(manuals_output).expanduser().resolve()
            if manuals_output
            else project_root / "manuals" / repo_dir.name
        )
        manual_output_dir.mkdir(parents=True, exist_ok=True)
        generator = ManualPackGenerator(repo_dir)
        generator.generate(output_dir=manual_output_dir, include_db=False, settings=None)

        if not skip_ingest:
            if reset_manuals_collection:
                conn = get_connection(settings)
                try:
                    purge_collection_documents(conn, collection=resolved_manuals_collection)
                finally:
                    conn.close()
            provider = get_embedding_provider(settings)
            manual_ingest_stats = ingest_local_directory(
                directory=str(manual_output_dir),
                embedding_provider=provider,
                collection=resolved_manuals_collection,
                settings=settings,
            )

    return ingest_stats, manual_ingest_stats, manual_output_dir, resolved_manuals_collection


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
        resolve_collection_pair,
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
    base_collection = args.collection or repo_name
    collection, manuals_collection = resolve_collection_pair(
        collection=base_collection,
        manuals_collection=args.manuals_collection,
    )
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

        (
            ingest_stats,
            manual_ingest_stats,
            manual_output_dir,
            resolved_manuals_collection,
        ) = _repo_ingest_and_manuals(
            repo_dir=repo_dir,
            collection=collection,
            project_root=project_root,
            settings=settings,
            skip_ingest=args.skip_ingest,
            generate_manuals=args.generate_manuals,
            manuals_collection=manuals_collection,
            manuals_output=args.manuals_output,
            reset_code_collection=args.reset_code_collection,
            reset_manuals_collection=args.reset_manuals_collection,
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
        manuals_collection=resolved_manuals_collection if args.generate_manuals else None,
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
                "collection": resolved_manuals_collection,
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
        f"[cyan]Manuals collection:[/cyan] {resolved_manuals_collection or 'n/a'}",
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
            f"{manual_ingest_stats.skipped_docs} skipped, "
            f"{manual_ingest_stats.total_chunks} chunks "
            f"into '{resolved_manuals_collection}'"
        )
    console.print()
    console.print(Panel("\n".join(lines), title="ragops repo add", border_style="green"))
    console.print()


def cmd_repo_add_lazy(args: argparse.Namespace) -> None:
    """Lazy-onboard a GitHub repo: index file tree only, embed content on-demand."""
    import os
    import time

    from services.api.app.repo_onboarding import onboard_github_repo_lazy
    from services.cli.project import find_project_root
    from services.cli.repositories import (
        RepoRecord,
        default_repo_name,
        load_repo_registry,
        now_utc_iso,
        parse_github_repo_url,
        resolve_collection_pair,
        save_repo_registry,
    )
    from services.core.config import get_settings
    from services.core.logging import setup_logging

    project_root = find_project_root() or Path.cwd()
    settings = get_settings()
    setup_logging("ERROR")

    canonical_url, owner, repo = parse_github_repo_url(args.repo_url)
    repo_name = args.name or default_repo_name(owner, repo)
    base_collection = args.collection or repo_name
    collection, _ = resolve_collection_pair(collection=base_collection, manuals_collection=None)
    token = args.github_token or os.getenv("GITHUB_TOKEN")

    repos = load_repo_registry(project_root)
    if repo_name in repos and not args.force:
        console.print(
            f"[red]Error:[/red] Repository '{repo_name}' already exists. "
            f"Use [bold]--force[/bold] to overwrite."
        )
        sys.exit(1)

    # Override github_token in settings if provided
    if token:
        settings.github_token = token

    start = time.perf_counter()
    with console.status(
        f"[bold cyan]Lazy onboarding {owner}/{repo}...[/bold cyan]",
        spinner="dots",
    ):
        result = onboard_github_repo_lazy(
            repo_url=args.repo_url,
            settings=settings,
            ref=args.ref,
            name=args.name,
            collection=args.collection,
        )
    elapsed = time.perf_counter() - start

    timestamp = now_utc_iso()
    previous = repos.get(repo_name)
    repos[repo_name] = RepoRecord(
        name=result.name,
        url=result.url,
        collection=result.collection,
        local_path="(lazy — no local clone)",
        ref=result.ref,
        manuals_enabled=False,
        manuals_collection=None,
        manuals_output=None,
        added_at=previous.added_at if previous and previous.added_at else timestamp,
        last_sync_at=timestamp,
    )
    registry_file = save_repo_registry(project_root, repos)

    if args.json:
        import json

        payload = result.to_dict()
        payload.update({
            "status": "ok",
            "elapsed_seconds": round(elapsed, 2),
            "registry": str(registry_file),
        })
        print(json.dumps(payload, indent=2))
        return

    console.print()
    console.print(
        Panel(
            "[bold green]⚡ Lazy onboarding complete[/bold green]\n\n"
            f"[cyan]Name:[/cyan] {result.name}\n"
            f"[cyan]URL:[/cyan] {result.url}\n"
            f"[cyan]Ref:[/cyan] {result.ref}\n"
            f"[cyan]Collection:[/cyan] {result.collection}\n"
            f"[cyan]Tree collection:[/cyan] {result.tree_collection}\n"
            f"[cyan]Total files:[/cyan] {result.total_files}\n"
            f"[cyan]Embeddable files:[/cyan] {result.embeddable_files}\n"
            f"[cyan]Time:[/cyan] {elapsed:.1f}s\n"
            f"[cyan]Registry:[/cyan] {registry_file}\n\n"
            f"[dim]File content will be embedded on-demand when you ask questions.[/dim]\n"
            f"[dim]Try: ragops chat --collection {result.collection}[/dim]",
            title="⚡ ragops repo add-lazy",
            border_style="green",
        )
    )
    console.print()



def cmd_repo_sync(args: argparse.Namespace) -> None:
    """Pull one or all registered repositories and refresh index/manuals."""
    from services.cli.project import find_project_root
    from services.cli.repositories import (
        RepoRecord,
        load_repo_registry,
        now_utc_iso,
        resolve_collection_pair,
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
            collection, manuals_collection = resolve_collection_pair(
                collection=record.collection,
                manuals_collection=args.manuals_collection or record.manuals_collection,
            )

            (
                ingest_stats,
                manual_ingest_stats,
                manual_output_dir,
                resolved_manuals_collection,
            ) = _repo_ingest_and_manuals(
                repo_dir=repo_dir,
                collection=collection,
                project_root=project_root,
                settings=settings,
                skip_ingest=args.skip_ingest,
                generate_manuals=generate_manuals,
                manuals_collection=manuals_collection,
                manuals_output=manuals_output,
                reset_code_collection=args.reset_code_collection,
                reset_manuals_collection=args.reset_manuals_collection,
            )

            updated = RepoRecord(
                name=record.name,
                url=record.url,
                collection=collection,
                local_path=record.local_path,
                ref=args.ref or record.ref,
                manuals_enabled=generate_manuals,
                manuals_collection=resolved_manuals_collection if generate_manuals else None,
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
                    "manuals_collection": resolved_manuals_collection,
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
                            "collection": row["manuals_collection"],
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
        if manual_ingest_stats and row.get("manuals_collection"):
            manuals_text = f"{manuals_text} -> {row['manuals_collection']}"
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
    table.add_column("Manuals Collection", style="yellow")
    table.add_column("Last Sync", style="magenta")
    for name, record in sorted(repos.items()):
        table.add_row(
            name,
            record.collection,
            record.ref or "default",
            record.local_path,
            record.manuals_collection or "n/a",
            record.last_sync_at or "never",
        )

    console.print()
    console.print(table)
    console.print()


def cmd_repo_migrate_collections(args: argparse.Namespace) -> None:
    """Migrate tracked repos to split code/manual collection names."""
    from services.cli.project import find_project_root
    from services.cli.repositories import (
        RepoRecord,
        load_repo_registry,
        now_utc_iso,
        resolve_collection_pair,
        save_repo_registry,
    )
    from services.core.config import get_settings
    from services.core.logging import setup_logging
    from services.core.storage import get_connection, purge_collection_documents

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

    plans: list[dict[str, object]] = []
    for name in target_names:
        record = repos[name]
        new_code, new_manuals = resolve_collection_pair(
            collection=record.collection,
            manuals_collection=args.manuals_collection or record.manuals_collection,
        )
        plans.append(
            {
                "name": name,
                "old_code": record.collection,
                "new_code": new_code,
                "old_manuals": record.manuals_collection,
                "new_manuals": new_manuals,
                "changed": (record.collection != new_code)
                or (record.manuals_collection != new_manuals),
            }
        )

    if not args.apply:
        table = Table(
            title="🧭 Collection Migration Plan (dry-run)",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Repo", style="cyan")
        table.add_column("Current Code", style="yellow")
        table.add_column("Target Code", style="green")
        table.add_column("Current Manuals", style="yellow")
        table.add_column("Target Manuals", style="green")
        table.add_column("Change", style="magenta")
        for row in plans:
            table.add_row(
                str(row["name"]),
                str(row["old_code"]),
                str(row["new_code"]),
                str(row["old_manuals"] or "n/a"),
                str(row["new_manuals"]),
                "yes" if row["changed"] else "no",
            )
        console.print()
        console.print(table)
        console.print(
            "\n[dim]Run with --apply to execute migration."
            " Add --purge-old to remove old mixed collection data.[/dim]\n"
        )
        return

    results: list[dict[str, object]] = []
    with console.status("[bold cyan]Migrating collections...[/bold cyan]", spinner="dots"):
        for row in plans:
            name = str(row["name"])
            record = repos[name]
            old_code = str(row["old_code"])
            new_code = str(row["new_code"])
            new_manuals = str(row["new_manuals"])
            repo_dir = Path(record.local_path).expanduser().resolve()

            generate_manuals = bool(args.generate_manuals or record.manuals_enabled)
            manuals_output = args.manuals_output or record.manuals_output

            ingest_stats = None
            manual_ingest_stats = None
            manual_output_dir = None
            resolved_manuals_collection = record.manuals_collection

            if bool(row["changed"]) or args.reindex:
                (
                    ingest_stats,
                    manual_ingest_stats,
                    manual_output_dir,
                    resolved_manuals_collection,
                ) = _repo_ingest_and_manuals(
                    repo_dir=repo_dir,
                    collection=new_code,
                    project_root=project_root,
                    settings=settings,
                    skip_ingest=False,
                    generate_manuals=generate_manuals,
                    manuals_collection=new_manuals,
                    manuals_output=manuals_output,
                    reset_code_collection=args.reset_code_collection,
                    reset_manuals_collection=args.reset_manuals_collection,
                )

            purged: list[dict[str, object]] = []
            if args.purge_old and old_code != new_code:
                conn = get_connection(settings)
                try:
                    summary = purge_collection_documents(conn, collection=old_code)
                    purged.append({"collection": old_code, **summary})
                finally:
                    conn.close()

            updated = RepoRecord(
                name=record.name,
                url=record.url,
                collection=new_code,
                local_path=record.local_path,
                ref=record.ref,
                manuals_enabled=generate_manuals,
                manuals_collection=resolved_manuals_collection if generate_manuals else None,
                manuals_output=str(manual_output_dir) if manual_output_dir else manuals_output,
                added_at=record.added_at,
                last_sync_at=now_utc_iso(),
            )
            repos[name] = updated
            results.append(
                {
                    "name": name,
                    "old_code": old_code,
                    "new_code": new_code,
                    "new_manuals": resolved_manuals_collection,
                    "ingest_stats": ingest_stats,
                    "manual_ingest_stats": manual_ingest_stats,
                    "purged": purged,
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
                    "old_code": row["old_code"],
                    "new_code": row["new_code"],
                    "new_manuals": row["new_manuals"],
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
                    "purged": row["purged"],
                }
                for row in results
            ],
        }
        print(json.dumps(payload, indent=2))
        return

    table = Table(title="✅ Collection Migration", show_header=True, header_style="bold cyan")
    table.add_column("Repo", style="cyan")
    table.add_column("Code Collection", style="green")
    table.add_column("Manuals Collection", style="yellow")
    table.add_column("Ingest", style="magenta")
    table.add_column("Purged", style="red")
    for row in results:
        ingest_stats = row["ingest_stats"]
        manual_ingest_stats = row["manual_ingest_stats"]
        ingest_text_parts: list[str] = []
        if ingest_stats:
            ingest_text_parts.append(
                f"code: {ingest_stats.indexed_docs} idx/{ingest_stats.total_chunks} chunks"
            )
        if manual_ingest_stats:
            ingest_text_parts.append(
                f"manuals: {manual_ingest_stats.indexed_docs} idx/"
                f"{manual_ingest_stats.total_chunks} chunks"
            )
        ingest_text = " | ".join(ingest_text_parts) if ingest_text_parts else "skipped"
        purged_rows = row["purged"]
        if purged_rows:
            purged_text = ", ".join(
                f"{p['collection']} ({p['documents_deleted']} docs/{p['chunks_deleted']} chunks)"
                for p in purged_rows
            )
        else:
            purged_text = "none"
        table.add_row(
            str(row["name"]),
            str(row["new_code"]),
            str(row["new_manuals"] or "n/a"),
            ingest_text,
            purged_text,
        )

    console.print()
    console.print(table)
    console.print(f"[dim]Registry updated: {registry_file}[/dim]")
    console.print()


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def _mask_secret(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if len(text) <= 6:
        return "*" * len(text)
    return f"{text[:3]}...{text[-2:]}"


def cmd_config_show(args: argparse.Namespace) -> None:
    """Show current user-level ragops config (~/.ragops/config.yaml)."""
    from services.cli.user_config import load_user_config, user_config_path

    cfg = load_user_config()
    path = user_config_path()
    if not cfg:
        if args.json:
            import json

            print(json.dumps({"path": str(path), "config": {}}, indent=2))
            return
        console.print()
        console.print(
            Panel(
                "[yellow]No global config found.[/yellow]\n\n"
                "Run `ragops init` or `ragops config set` to create one.",
                title=f"ragops config ({path})",
                border_style="yellow",
            )
        )
        console.print()
        return

    output = dict(cfg)
    secret = str(output.get("openai_api_key", "")).strip()
    if secret and not args.reveal_secrets:
        output["openai_api_key"] = _mask_secret(secret)

    if args.json:
        import json

        print(json.dumps({"path": str(path), "config": output}, indent=2))
        return

    lines = [
        f"[cyan]Path:[/cyan] {path}",
        f"[cyan]openai_api_key:[/cyan] {output.get('openai_api_key', '(not set)')}",
        f"[cyan]llm_enabled:[/cyan] {output.get('llm_enabled', '(not set)')}",
        f"[cyan]storage_backend:[/cyan] {output.get('storage_backend', '(not set)')}",
        f"[cyan]local_db_path:[/cyan] {output.get('local_db_path', '(not set)')}",
        f"[cyan]show_ranking_signals:[/cyan] {output.get('show_ranking_signals', '(not set)')}",
        f"[cyan]updated_at:[/cyan] {output.get('updated_at', '(unknown)')}",
    ]
    console.print()
    console.print(Panel("\n".join(lines), title="ragops config", border_style="green"))
    console.print()


def cmd_config_set(args: argparse.Namespace) -> None:
    """Set user-level ragops config values (~/.ragops/config.yaml)."""
    from services.cli.user_config import save_user_config

    updates: dict[str, object] = {}
    if args.openai_api_key is not None:
        updates["openai_api_key"] = args.openai_api_key.strip()
    if args.storage_backend is not None:
        updates["storage_backend"] = args.storage_backend
    if args.local_db_path is not None:
        updates["local_db_path"] = args.local_db_path.strip()
    if args.llm_enabled is not None:
        updates["llm_enabled"] = args.llm_enabled == "true"
    raw_show_ranking = getattr(args, "show_ranking_signals", None)
    if raw_show_ranking is not None:
        updates["show_ranking_signals"] = _coerce_bool(raw_show_ranking)

    if args.unset_openai_api_key:
        updates["openai_api_key"] = ""

    if not updates:
        console.print("[red]Error:[/red] No values provided. Use --help for options.")
        sys.exit(1)

    path = save_user_config(updates)
    masked_key = _mask_secret(str(updates.get("openai_api_key", "")).strip())
    if args.json:
        import json

        print(
            json.dumps(
                {
                    "status": "ok",
                    "path": str(path),
                    "updated": {
                        "openai_api_key": masked_key,
                        "llm_enabled": updates.get("llm_enabled"),
                        "storage_backend": updates.get("storage_backend"),
                        "local_db_path": updates.get("local_db_path"),
                        "show_ranking_signals": updates.get("show_ranking_signals"),
                    },
                },
                indent=2,
            )
        )
        return

    lines = [f"[cyan]Path:[/cyan] {path}", "[cyan]Updated:[/cyan]"]
    if "openai_api_key" in updates:
        lines.append(f"  - openai_api_key: {masked_key or '(cleared)'}")
    if "llm_enabled" in updates:
        lines.append(f"  - llm_enabled: {updates['llm_enabled']}")
    if "storage_backend" in updates:
        lines.append(f"  - storage_backend: {updates['storage_backend']}")
    if "local_db_path" in updates:
        lines.append(f"  - local_db_path: {updates['local_db_path']}")
    if "show_ranking_signals" in updates:
        lines.append(f"  - show_ranking_signals: {updates['show_ranking_signals']}")

    console.print()
    console.print(Panel("\n".join(lines), title="ragops config set", border_style="green"))
    console.print()


def cmd_config_doctor(args: argparse.Namespace) -> None:
    """Run config diagnostics across global config, project env, and storage backend."""
    from services.cli.project import find_project_root
    from services.cli.user_config import load_user_config, user_config_path
    from services.core.config import get_settings
    from services.core.storage import get_connection, health_check, resolve_storage_backend

    project_root = find_project_root() or Path.cwd()
    project_env_path = project_root / ".env"
    global_cfg = load_user_config()
    global_cfg_path = user_config_path()
    fixes_applied: list[str] = []

    if args.fix:
        updates: dict[str, str] = {}
        global_key = str(global_cfg.get("openai_api_key", "")).strip()
        global_backend = str(global_cfg.get("storage_backend", "")).strip()
        global_local_db = str(global_cfg.get("local_db_path", "")).strip()
        raw_llm_enabled = str(global_cfg.get("llm_enabled", "")).strip().lower()

        if not _read_env_value(project_env_path, "STORAGE_BACKEND"):
            updates["STORAGE_BACKEND"] = global_backend or "sqlite"
        if not _read_env_value(project_env_path, "LOCAL_DB_PATH"):
            updates["LOCAL_DB_PATH"] = global_local_db or ".ragops/ragops.db"
        if not _read_env_value(project_env_path, "LLM_ENABLED"):
            if raw_llm_enabled in {"1", "true", "yes", "on"}:
                updates["LLM_ENABLED"] = "true"
            elif raw_llm_enabled in {"0", "false", "no", "off"}:
                updates["LLM_ENABLED"] = "false"
            else:
                updates["LLM_ENABLED"] = "false"
        if not _read_env_value(project_env_path, "OPENAI_API_KEY") and global_key:
            updates["OPENAI_API_KEY"] = global_key

        if updates:
            _upsert_env_values(project_env_path, updates)
            for key, value in updates.items():
                if key == "OPENAI_API_KEY":
                    fixes_applied.append(f"{key}={_mask_secret(value)}")
                else:
                    fixes_applied.append(f"{key}={value}")

    settings = get_settings()

    project_env_key = _read_env_value(project_env_path, "OPENAI_API_KEY")
    runtime_env_key = os.getenv("OPENAI_API_KEY", "").strip()
    global_key = str(global_cfg.get("openai_api_key", "")).strip()
    effective_key = runtime_env_key or project_env_key or global_key
    if runtime_env_key and project_env_key and runtime_env_key == project_env_key:
        key_source = "project_env"
    elif runtime_env_key and global_key and runtime_env_key == global_key and not project_env_key:
        key_source = "global_config"
    elif runtime_env_key:
        key_source = "environment"
    elif project_env_key:
        key_source = "project_env"
    elif global_key:
        key_source = "global_config"
    else:
        key_source = "missing"

    backend = resolve_storage_backend(settings)
    storage_ok = False
    storage_error = ""
    try:
        conn = get_connection(settings)
        try:
            db_health = health_check(conn)
            storage_ok = db_health.get("db") == "ok"
            storage_error = "" if storage_ok else str(db_health.get("db", "unknown error"))
        finally:
            conn.close()
    except Exception as exc:
        storage_ok = False
        storage_error = str(exc)

    checks = [
        {
            "name": "global_config",
            "status": "ok" if bool(global_cfg) else "warn",
            "message": (
                str(global_cfg_path)
                if bool(global_cfg)
                else "missing ~/.ragops/config.yaml"
            ),
        },
        {
            "name": "project_env",
            "status": "ok" if project_env_path.exists() else "warn",
            "message": (
                str(project_env_path)
                if project_env_path.exists()
                else "missing project .env"
            ),
        },
        {
            "name": "api_key",
            "status": "ok" if bool(effective_key) else "warn",
            "message": (
                f"OPENAI_API_KEY resolved from {key_source}"
                if effective_key
                else "OPENAI_API_KEY not found (env, project .env, or global config)"
            ),
        },
        {
            "name": "storage_backend",
            "status": "ok",
            "message": backend,
        },
        {
            "name": "storage_health",
            "status": "ok" if storage_ok else "error",
            "message": "storage connection ok" if storage_ok else storage_error,
        },
    ]

    has_error = any(c["status"] == "error" for c in checks)
    has_warn = any(c["status"] == "warn" for c in checks)
    overall_status = "error" if has_error else ("warn" if has_warn else "ok")

    payload = {
        "status": overall_status,
        "project_root": str(project_root),
        "project_env": str(project_env_path),
        "global_config": str(global_cfg_path),
        "fix": {
            "requested": bool(args.fix),
            "applied": fixes_applied,
        },
        "effective": {
            "storage_backend": backend,
            "storage_backend_configured": settings.storage_backend,
            "local_db_path": settings.local_db_path,
            "llm_enabled": settings.llm_enabled,
            "openai_api_key_set": bool(effective_key),
            "openai_api_key_source": key_source,
        },
        "checks": checks,
    }

    if args.json:
        import json

        print(json.dumps(payload, indent=2))
        return

    icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}
    lines = [
        f"[cyan]Project root:[/cyan] {project_root}",
        f"[cyan]Global config:[/cyan] {global_cfg_path}",
        f"[cyan]Resolved backend:[/cyan] {backend}",
        f"[cyan]LLM enabled:[/cyan] {settings.llm_enabled}",
        f"[cyan]OPENAI_API_KEY source:[/cyan] {key_source}",
    ]
    if args.fix:
        if fixes_applied:
            lines.append(f"[cyan]Fix applied:[/cyan] {', '.join(fixes_applied)}")
        else:
            lines.append("[cyan]Fix applied:[/cyan] none (nothing missing)")
    lines.extend(["", "[cyan]Checks:[/cyan]"])
    for check in checks:
        symbol = icon.get(str(check["status"]), "•")
        lines.append(f"{symbol} {check['name']}: {check['message']}")

    border = (
        "green"
        if overall_status == "ok"
        else ("yellow" if overall_status == "warn" else "red")
    )
    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            title=f"ragops config doctor ({overall_status})",
            border_style=border,
        )
    )
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
    p_init.add_argument("--openai-api-key", help="Set OPENAI_API_KEY in project .env")
    p_init.add_argument(
        "--storage-backend",
        default="sqlite",
        choices=["sqlite", "postgres", "auto"],
        help="Default storage backend written to .env",
    )
    p_init.add_argument(
        "--local-db-path",
        default=".ragops/ragops.db",
        help="SQLite file path for local mode",
    )
    p_init.add_argument(
        "--llm-enabled",
        choices=["true", "false"],
        help="Explicit LLM_ENABLED value written to .env",
    )
    p_init.add_argument(
        "--no-prompt",
        action="store_true",
        help="Disable interactive prompt for missing API key",
    )
    p_init.add_argument(
        "--no-global-config",
        action="store_true",
        help="Do not write OPENAI_API_KEY/defaults to ~/.ragops/config.yaml",
    )
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

    # --- scan ---
    p_scan = sub.add_parser(
        "scan",
        help="One-command scan: ingest project + generate manuals + ingest manuals",
    )
    p_scan.add_argument(
        "--collection",
        help="Collection name (defaults to detected project name)",
    )
    p_scan.add_argument(
        "--output",
        default="./.ragops/manuals",
        help="Manuals output directory (default: ./.ragops/manuals)",
    )
    p_scan.add_argument(
        "--skip-manuals",
        action="store_true",
        help="Only ingest project files; skip manual generation/ingest",
    )
    p_scan.add_argument(
        "--incremental",
        action="store_true",
        help="Ingest only changed/untracked files from git diff, then regenerate manuals",
    )
    p_scan.add_argument(
        "--base-ref",
        default="HEAD",
        help="Git base ref used with --incremental (default: HEAD)",
    )
    p_scan.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON",
    )
    p_scan.set_defaults(func=cmd_scan)

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
    p_chat.add_argument(
        "question",
        nargs="?",
        help="Your question (omit for interactive chat mode)",
    )
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
    ranking_group = p_chat.add_mutually_exclusive_group()
    ranking_group.add_argument(
        "--show-ranking-signals",
        dest="show_ranking_signals",
        action="store_true",
        default=None,
        help="Show ranking debug signals for each citation source",
    )
    ranking_group.add_argument(
        "--hide-ranking-signals",
        dest="show_ranking_signals",
        action="store_false",
        help="Hide ranking debug signals for this command run",
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

    # --- config ---
    p_config = sub.add_parser("config", help="Manage global ragops config (~/.ragops/config.yaml)")
    config_sub = p_config.add_subparsers(dest="config_command", help="Config commands")
    config_sub.required = True

    p_config_show = config_sub.add_parser("show", help="Show current global config")
    p_config_show.add_argument(
        "--reveal-secrets",
        action="store_true",
        help="Show full secret values (default masks secrets)",
    )
    p_config_show.add_argument("--json", action="store_true", help="Output raw JSON")
    p_config_show.set_defaults(func=cmd_config_show)

    p_config_set = config_sub.add_parser("set", help="Set global config values")
    p_config_set.add_argument("--openai-api-key", help="Set OPENAI_API_KEY in global config")
    p_config_set.add_argument(
        "--unset-openai-api-key",
        action="store_true",
        help="Clear OPENAI_API_KEY in global config",
    )
    p_config_set.add_argument(
        "--llm-enabled",
        choices=["true", "false"],
        help="Set default llm_enabled in global config",
    )
    p_config_set.add_argument(
        "--storage-backend",
        choices=["sqlite", "postgres", "auto"],
        help="Set default storage backend in global config",
    )
    p_config_set.add_argument(
        "--local-db-path",
        help="Set default local SQLite DB path in global config",
    )
    p_config_set.add_argument(
        "--show-ranking-signals",
        choices=["true", "false"],
        help="Set default ranking signal visibility for chat output",
    )
    p_config_set.add_argument("--json", action="store_true", help="Output raw JSON")
    p_config_set.set_defaults(func=cmd_config_set)

    p_config_doctor = config_sub.add_parser(
        "doctor",
        help="Diagnose effective config, key source, and storage health",
    )
    p_config_doctor.add_argument(
        "--fix",
        action="store_true",
        help="Write missing local defaults into project .env (non-destructive)",
    )
    p_config_doctor.add_argument("--json", action="store_true", help="Output raw JSON")
    p_config_doctor.set_defaults(func=cmd_config_doctor)

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
        "--reset-code-collection",
        action="store_true",
        help="Purge target code collection before ingesting",
    )
    p_repo_add.add_argument(
        "--reset-manuals-collection",
        action="store_true",
        help="Purge target manuals collection before ingesting manuals",
    )
    p_repo_add.add_argument(
        "--generate-manuals",
        action="store_true",
        help="Generate onboarding manuals after clone/sync",
    )
    p_repo_add.add_argument(
        "--manuals-collection",
        help="Collection for generated manuals (default: <collection>_manuals)",
    )
    p_repo_add.add_argument("--manuals-output", help="Manuals output directory")
    p_repo_add.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing registry entry for this repo key",
    )
    p_repo_add.add_argument("--json", action="store_true", help="Output raw JSON")
    p_repo_add.set_defaults(func=cmd_repo_add)

    p_repo_add_lazy = repo_sub.add_parser(
        "add-lazy",
        help="⚡ Lazy-onboard a GitHub repo (file tree only, ~2-5s, content embedded on-demand)",
    )
    p_repo_add_lazy.add_argument(
        "repo_url", help="GitHub URL (https://github.com/org/repo)"
    )
    p_repo_add_lazy.add_argument("--name", help="Local repo key (default: owner-repo)")
    p_repo_add_lazy.add_argument("--collection", help="Collection name (default: repo key)")
    p_repo_add_lazy.add_argument("--ref", help="Branch or tag (default: HEAD)")
    p_repo_add_lazy.add_argument(
        "--github-token", help="GitHub token (defaults to GITHUB_TOKEN env)"
    )
    p_repo_add_lazy.add_argument(
        "--force", action="store_true", help="Overwrite existing registry entry"
    )
    p_repo_add_lazy.add_argument("--json", action="store_true", help="Output raw JSON")
    p_repo_add_lazy.set_defaults(func=cmd_repo_add_lazy)

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
        "--reset-code-collection",
        action="store_true",
        help="Purge target code collection before ingesting",
    )
    p_repo_sync.add_argument(
        "--reset-manuals-collection",
        action="store_true",
        help="Purge target manuals collection before ingesting manuals",
    )
    p_repo_sync.add_argument(
        "--generate-manuals",
        action="store_true",
        help="Generate manuals during sync",
    )
    p_repo_sync.add_argument(
        "--manuals-collection",
        help="Collection for generated manuals (default: stored value or <collection>_manuals)",
    )
    p_repo_sync.add_argument("--manuals-output", help="Manuals output directory")
    p_repo_sync.add_argument("--json", action="store_true", help="Output raw JSON")
    p_repo_sync.set_defaults(func=cmd_repo_sync)

    p_repo_migrate = repo_sub.add_parser(
        "migrate-collections",
        help="Split existing tracked repos into <collection>_code and <collection>_manuals",
    )
    p_repo_migrate.add_argument("name", nargs="?", help="Repo key from registry")
    p_repo_migrate.add_argument("--all", action="store_true", help="Migrate all repositories")
    p_repo_migrate.add_argument(
        "--manuals-collection",
        help="Override manuals collection for target repo(s)",
    )
    p_repo_migrate.add_argument(
        "--manuals-output",
        help="Manuals output directory used during migration reindex",
    )
    p_repo_migrate.add_argument(
        "--generate-manuals",
        action="store_true",
        help="Force manuals generation during migration",
    )
    p_repo_migrate.add_argument(
        "--reindex",
        action="store_true",
        help="Reindex even when names are already normalized",
    )
    p_repo_migrate.add_argument(
        "--purge-old",
        action="store_true",
        help="Delete old collection documents/chunks after successful migration",
    )
    p_repo_migrate.add_argument(
        "--reset-code-collection",
        action="store_true",
        help="Purge target code collection before reindexing",
    )
    p_repo_migrate.add_argument(
        "--reset-manuals-collection",
        action="store_true",
        help="Purge target manuals collection before reindexing manuals",
    )
    p_repo_migrate.add_argument(
        "--apply",
        action="store_true",
        help="Execute migration (default is dry-run)",
    )
    p_repo_migrate.add_argument("--json", action="store_true", help="Output raw JSON")
    p_repo_migrate.set_defaults(func=cmd_repo_migrate_collections)

    p_repo_list = repo_sub.add_parser("list", help="List registered repositories")
    p_repo_list.add_argument("--json", action="store_true", help="Output raw JSON")
    p_repo_list.set_defaults(func=cmd_repo_list)

    return parser


def main() -> None:
    """CLI entrypoint."""
    _apply_user_profile_defaults()
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
