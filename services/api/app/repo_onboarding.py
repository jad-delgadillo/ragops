"""Repo onboarding helpers for API-driven GitHub ingestion."""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from services.cli.project import find_project_root
from services.cli.repositories import (
    default_repo_name,
    parse_github_repo_url,
    resolve_collection_pair,
)
from services.core.config import Settings
from services.core.database import get_connection, purge_collection_documents
from services.core.providers import get_embedding_provider
from services.ingest.app.pipeline import ingest_local_directory

REPO_KEY_SANITIZE_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass
class RepoOnboardingResult:
    """Result payload for API repo onboarding."""

    name: str
    url: str
    ref: str
    local_path: str
    collection: str
    manuals_collection: str | None
    generate_manuals: bool
    ingest: dict[str, int]
    manual_ingest: dict[str, int] | None
    manuals_output: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "ref": self.ref,
            "local_path": self.local_path,
            "collection": self.collection,
            "manuals_collection": self.manuals_collection,
            "generate_manuals": self.generate_manuals,
            "ingest": self.ingest,
            "manual_ingest": self.manual_ingest,
            "manuals_output": self.manuals_output,
        }


def _sanitize_repo_key(value: str) -> str:
    candidate = REPO_KEY_SANITIZE_PATTERN.sub("-", value.strip().lower()).strip("-")
    if not candidate:
        raise ValueError("Repository name is invalid after sanitization")
    return candidate


def _bool_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _resolve_repo_cache_dir(settings: Settings) -> Path:
    raw = (settings.repo_cache_dir or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    if (settings.environment or "").lower() in {"local", "dev"}:
        project_root = find_project_root() or Path.cwd()
        return (project_root / ".ragops" / "repos").resolve()
    return Path("/tmp/ragops/repos").resolve()


def _resolve_manuals_output_root(settings: Settings) -> Path:
    raw = (settings.repo_manuals_dir or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    if (settings.environment or "").lower() in {"local", "dev"}:
        project_root = find_project_root() or Path.cwd()
        return (project_root / "manuals").resolve()
    return Path("/tmp/ragops/manuals").resolve()


def _download_repo_zip(
    *,
    owner: str,
    repo: str,
    ref: str,
    github_token: str | None,
    timeout_seconds: int,
    max_archive_mb: int,
) -> bytes:
    ref_path = quote(ref, safe="")
    url = f"https://api.github.com/repos/{owner}/{repo}/zipball/{ref_path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ragops-repo-onboard",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    with httpx.Client(timeout=max(timeout_seconds, 10), follow_redirects=True) as client:
        response = client.get(url, headers=headers)

    if response.status_code == 404:
        raise ValueError(
            "Repository or ref not found. For private repos, configure GITHUB_TOKEN in Lambda env."
        )
    if response.status_code >= 400:
        snippet = response.text[:300]
        raise RuntimeError(f"GitHub download failed ({response.status_code}): {snippet}")

    max_bytes = max(1, max_archive_mb) * 1024 * 1024
    content_length = response.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > max_bytes:
        raise ValueError(f"Repository archive too large (>{max_archive_mb} MB)")
    payload = response.content
    if len(payload) > max_bytes:
        raise ValueError(f"Repository archive too large (>{max_archive_mb} MB)")
    return payload


def _extract_repo_zip(*, archive_bytes: bytes, destination: Path) -> None:
    temp_root = destination.parent / f".tmp-{destination.name}"
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            archive.extractall(temp_root)
        extracted_roots = [entry for entry in temp_root.iterdir() if entry.is_dir()]
        if not extracted_roots:
            raise RuntimeError("Downloaded archive did not contain a repository directory")
        source_root = extracted_roots[0]

        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_root), str(destination))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def onboard_github_repo(
    *,
    repo_url: str,
    settings: Settings,
    ref: str | None = None,
    name: str | None = None,
    collection: str | None = None,
    manuals_collection: str | None = None,
    generate_manuals: bool = True,
    reset_code_collection: bool = True,
    reset_manuals_collection: bool = True,
) -> RepoOnboardingResult:
    """Download a GitHub repo archive and ingest it into code/manual collections."""
    canonical_url, owner, repo = parse_github_repo_url(repo_url)
    repo_name = _sanitize_repo_key(name or default_repo_name(owner, repo))
    code_collection, resolved_manuals_collection = resolve_collection_pair(
        collection=(collection or repo_name),
        manuals_collection=manuals_collection,
    )
    active_ref = (ref or "main").strip() or "main"
    include_manuals = _bool_value(generate_manuals, default=True)

    archive_bytes = _download_repo_zip(
        owner=owner,
        repo=repo,
        ref=active_ref,
        github_token=(settings.github_token or "").strip() or None,
        timeout_seconds=settings.repo_onboarding_timeout_seconds,
        max_archive_mb=settings.repo_archive_max_mb,
    )

    repo_cache_dir = _resolve_repo_cache_dir(settings)
    repo_cache_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = repo_cache_dir / repo_name
    _extract_repo_zip(archive_bytes=archive_bytes, destination=repo_dir)

    if reset_code_collection:
        conn = get_connection(settings)
        try:
            purge_collection_documents(conn, collection=code_collection)
        finally:
            conn.close()

    provider = get_embedding_provider(settings)
    ingest_stats = ingest_local_directory(
        directory=str(repo_dir),
        embedding_provider=provider,
        collection=code_collection,
        settings=settings,
        extra_ignore_dirs={"manuals"},
    )

    manual_ingest_stats = None
    manuals_output_path: Path | None = None
    if include_manuals:
        from services.cli.docgen.manuals import ManualPackGenerator

        manuals_root = _resolve_manuals_output_root(settings)
        manuals_output_path = manuals_root / repo_name
        manuals_output_path.mkdir(parents=True, exist_ok=True)

        generator = ManualPackGenerator(repo_dir)
        generator.generate(output_dir=manuals_output_path, include_db=False, settings=None)

        if reset_manuals_collection:
            conn = get_connection(settings)
            try:
                purge_collection_documents(conn, collection=resolved_manuals_collection)
            finally:
                conn.close()

        provider = get_embedding_provider(settings)
        manual_ingest_stats = ingest_local_directory(
            directory=str(manuals_output_path),
            embedding_provider=provider,
            collection=resolved_manuals_collection,
            settings=settings,
        )

    return RepoOnboardingResult(
        name=repo_name,
        url=canonical_url,
        ref=active_ref,
        local_path=str(repo_dir),
        collection=code_collection,
        manuals_collection=resolved_manuals_collection if include_manuals else None,
        generate_manuals=include_manuals,
        ingest={
            "indexed_docs": ingest_stats.indexed_docs,
            "skipped_docs": ingest_stats.skipped_docs,
            "total_chunks": ingest_stats.total_chunks,
        },
        manual_ingest=(
            {
                "indexed_docs": manual_ingest_stats.indexed_docs,
                "skipped_docs": manual_ingest_stats.skipped_docs,
                "total_chunks": manual_ingest_stats.total_chunks,
            }
            if manual_ingest_stats
            else None
        ),
        manuals_output=str(manuals_output_path) if manuals_output_path else None,
    )
