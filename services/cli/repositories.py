"""GitHub repository helpers for clone/sync + local registry."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

import yaml

REGISTRY_FILE = "repos.yaml"


@dataclass
class RepoRecord:
    """Tracked repository metadata."""

    name: str
    url: str
    collection: str
    local_path: str
    ref: str | None = None
    manuals_enabled: bool = False
    manuals_collection: str | None = None
    manuals_output: str | None = None
    added_at: str = ""
    last_sync_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "url": self.url,
            "collection": self.collection,
            "local_path": self.local_path,
            "ref": self.ref,
            "manuals_enabled": self.manuals_enabled,
            "manuals_collection": self.manuals_collection,
            "manuals_output": self.manuals_output,
            "added_at": self.added_at,
            "last_sync_at": self.last_sync_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> RepoRecord:
        return cls(
            name=str(data.get("name", "")),
            url=str(data.get("url", "")),
            collection=str(data.get("collection", "")),
            local_path=str(data.get("local_path", "")),
            ref=str(data["ref"]) if data.get("ref") else None,
            manuals_enabled=bool(data.get("manuals_enabled", False)),
            manuals_collection=(
                str(data["manuals_collection"]) if data.get("manuals_collection") else None
            ),
            manuals_output=str(data["manuals_output"]) if data.get("manuals_output") else None,
            added_at=str(data.get("added_at", "")),
            last_sync_at=str(data.get("last_sync_at", "")),
        )


def now_utc_iso() -> str:
    """Return ISO-8601 UTC timestamp."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def default_repo_cache_dir(project_root: Path) -> Path:
    """Default cache directory for cloned repositories."""
    return project_root / ".ragops" / "repos"


def registry_path(project_root: Path) -> Path:
    """Registry YAML path under .ragops."""
    return project_root / ".ragops" / REGISTRY_FILE


def load_repo_registry(project_root: Path) -> dict[str, RepoRecord]:
    """Load repo registry from disk."""
    path = registry_path(project_root)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    rows = data.get("repos", [])
    records: dict[str, RepoRecord] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                record = RepoRecord.from_dict(row)
                if record.name:
                    records[record.name] = record
    return records


def save_repo_registry(project_root: Path, records: dict[str, RepoRecord]) -> Path:
    """Persist repo registry to disk."""
    path = registry_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"repos": [records[name].to_dict() for name in sorted(records)]}
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    return path


def parse_github_repo_url(url: str) -> tuple[str, str, str]:
    """Parse GitHub URL and return canonical https clone URL + owner/repo."""
    raw = url.strip()
    if not raw:
        raise ValueError("Repository URL is required")

    repo_path: str
    if raw.startswith("git@github.com:"):
        repo_path = raw.split(":", 1)[1]
    else:
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Use a GitHub URL like https://github.com/org/repo")
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            raise ValueError("Only github.com repositories are supported in this command")
        repo_path = parsed.path.lstrip("/")

    parts = [part for part in repo_path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("GitHub URL must include owner and repository name")

    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise ValueError("Could not parse owner/repository from GitHub URL")

    canonical_url = f"https://github.com/{owner}/{repo}.git"
    return canonical_url, owner, repo


def default_repo_name(owner: str, repo: str) -> str:
    """Build default registry key for a repository."""
    return f"{owner}-{repo}".lower()


def resolve_collection_pair(
    *,
    collection: str,
    manuals_collection: str | None = None,
) -> tuple[str, str]:
    """Return normalized code/manual collections for repo onboarding."""
    normalized_collection = collection.strip()
    if not normalized_collection:
        raise ValueError("Collection name cannot be empty")

    if normalized_collection.endswith("_code"):
        code_collection = normalized_collection
        base = normalized_collection[: -len("_code")]
    else:
        code_collection = f"{normalized_collection}_code"
        base = normalized_collection

    normalized_manuals = (manuals_collection or "").strip()
    if normalized_manuals:
        manual_collection = normalized_manuals
    else:
        manual_collection = f"{base}_manuals"

    return code_collection, manual_collection


def build_authenticated_clone_url(canonical_url: str, token: str | None) -> str:
    """Build clone URL optionally embedding token credentials."""
    if not token:
        return canonical_url
    parsed = urlparse(canonical_url)
    quoted_token = quote(token, safe="")
    netloc = f"x-access-token:{quoted_token}@{parsed.netloc}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


def run_git(args: list[str], *, cwd: Path | None = None) -> str:
    """Run git command and return stdout; raise RuntimeError on failure."""
    command = ["git", *args]
    proc = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip() or "unknown git error"
        raise RuntimeError(err)
    return proc.stdout.strip()


def clone_repo(
    *,
    clone_url: str,
    destination: Path,
    ref: str | None = None,
) -> None:
    """Clone a repository into destination."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not (destination / ".git").exists():
        if any(destination.iterdir()):
            raise ValueError(
                f"Destination '{destination}' exists and is not an empty git repository path"
            )

    args = ["clone"]
    if ref:
        args.extend(["--branch", ref, "--single-branch"])
    args.extend([clone_url, str(destination)])
    run_git(args)


def sync_repo(*, destination: Path, ref: str | None = None) -> str:
    """Sync an already-cloned repository and return active branch."""
    git_dir = destination / ".git"
    if not git_dir.exists():
        raise ValueError(f"Repository path is not a git clone: {destination}")

    run_git(["fetch", "--all", "--prune"], cwd=destination)
    if ref:
        run_git(["checkout", ref], cwd=destination)
        run_git(["pull", "--ff-only", "origin", ref], cwd=destination)
        return ref

    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=destination)
    run_git(["pull", "--ff-only"], cwd=destination)
    return branch
