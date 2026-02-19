"""GitHub Tree API: fetch file trees and individual file contents without cloning.

This module uses the GitHub REST API to:
1. Fetch the full file tree of a repo (recursive, single API call).
2. Fetch individual file contents on demand.
3. Filter files using the same extensions/ignore rules as the ingest pipeline.
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx

from services.ingest.app.pipeline import (
    IGNORE_DIR_SUFFIXES,
    IGNORE_DIRS,
    SUPPORTED_EXTENSIONS,
)

logger = logging.getLogger(__name__)

# GitHub API base
_GITHUB_API = "https://api.github.com"

# Maximum tree entries we'll accept (safety valve)
_MAX_TREE_ENTRIES = 50_000


class GitHubAPIError(Exception):
    """Raised when a GitHub API call fails."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"GitHub API error ({status_code}): {message}")


class GitHubRateLimitError(GitHubAPIError):
    """Raised when GitHub API rate limit is exceeded."""

    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(403, message)


def _github_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ragops-lazy-rag",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ---------------------------------------------------------------
# File tree
# ---------------------------------------------------------------


def fetch_file_tree(
    *,
    owner: str,
    repo: str,
    ref: str = "main",
    token: str | None = None,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """Fetch the full recursive file tree for a GitHub repo.

    Returns a list of dicts with keys: path, sha, size, type.
    Only includes 'blob' entries (files), not 'tree' entries (dirs).
    """
    ref_path = quote(ref, safe="")
    url = f"{_GITHUB_API}/repos/{owner}/{repo}/git/trees/{ref_path}?recursive=1"

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers=_github_headers(token))

    if response.status_code == 403 and "rate limit" in response.text.lower():
        raise GitHubRateLimitError(response.text[:300])
    if response.status_code == 404:
        raise GitHubAPIError(
            404, f"Repository {owner}/{repo} or ref '{ref}' not found."
        )
    if response.status_code >= 400:
        raise GitHubAPIError(response.status_code, response.text[:300])

    data = response.json()
    tree = data.get("tree", [])

    if len(tree) > _MAX_TREE_ENTRIES:
        logger.warning(
            "Repo %s/%s has %d tree entries (max %d). Truncating.",
            owner,
            repo,
            len(tree),
            _MAX_TREE_ENTRIES,
        )
        tree = tree[:_MAX_TREE_ENTRIES]

    # Filter to blobs (files) only
    return [
        {
            "path": entry["path"],
            "sha": entry.get("sha", ""),
            "size": entry.get("size", 0),
            "type": entry["type"],
        }
        for entry in tree
        if entry["type"] == "blob"
    ]


def filter_embeddable_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter file list to only those that should be embedded.

    Uses the same SUPPORTED_EXTENSIONS and IGNORE_DIRS as the ingest pipeline.
    """
    result = []
    for f in files:
        path = PurePosixPath(f["path"])
        # Check extension
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        # Check directory ignore rules
        parts = path.parts[:-1]  # parent directory parts
        skip = False
        for part in parts:
            if part in IGNORE_DIRS:
                skip = True
                break
            if any(part.endswith(suffix) for suffix in IGNORE_DIR_SUFFIXES):
                skip = True
                break
        if skip:
            continue
        result.append(f)
    return result


# ---------------------------------------------------------------
# File content
# ---------------------------------------------------------------


def fetch_file_content(
    *,
    owner: str,
    repo: str,
    path: str,
    ref: str = "main",
    token: str | None = None,
    timeout: int = 30,
) -> str:
    """Fetch the raw content of a single file from GitHub.

    Uses the raw content endpoint for efficiency (no base64 decode needed).
    """
    encoded_path = quote(path, safe="/")
    ref_path = quote(ref, safe="")
    url = f"{_GITHUB_API}/repos/{owner}/{repo}/contents/{encoded_path}?ref={ref_path}"

    headers = _github_headers(token)
    headers["Accept"] = "application/vnd.github.raw+json"

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers=headers)

    if response.status_code == 403 and "rate limit" in response.text.lower():
        raise GitHubRateLimitError(response.text[:300])
    if response.status_code == 404:
        raise GitHubAPIError(404, f"File not found: {path} (ref={ref})")
    if response.status_code >= 400:
        raise GitHubAPIError(response.status_code, response.text[:300])

    return response.text


def fetch_files_content(
    *,
    owner: str,
    repo: str,
    paths: list[str],
    ref: str = "main",
    token: str | None = None,
    timeout: int = 30,
) -> dict[str, str]:
    """Fetch content for multiple files. Returns {path: content} dict.

    Files that fail to fetch are logged and skipped.
    """
    results: dict[str, str] = {}
    for p in paths:
        try:
            content = fetch_file_content(
                owner=owner,
                repo=repo,
                path=p,
                ref=ref,
                token=token,
                timeout=timeout,
            )
            results[p] = content
        except GitHubAPIError as exc:
            logger.warning("Failed to fetch %s: %s", p, exc)
        except Exception as exc:
            logger.warning("Unexpected error fetching %s: %s", p, exc)
    return results
