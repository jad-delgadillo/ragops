"""Project detection and configuration management."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = ".ragops"
CONFIG_FILE = "config.yaml"

# Files that indicate a project root
PROJECT_MARKERS = [
    "pyproject.toml",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    ".git",
]

DEFAULT_IGNORE = [
    "__pycache__",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    ".env",
    "dist",
    "build",
    ".next",
    ".pytest_cache",
    "*.pyc",
    "*.min.js",
    "*.min.css",
    "*.lock",
]

# File extensions supported for ingestion
CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".swift",
    ".c",
    ".cpp",
    ".h",
    ".cs",
    ".scala",
}

DOC_EXTENSIONS = {
    ".md",
    ".txt",
    ".rst",
    ".adoc",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
}

ALL_EXTENSIONS = CODE_EXTENSIONS | DOC_EXTENSIONS


@dataclass
class ProjectConfig:
    """Configuration for a ragops project."""

    name: str = ""
    doc_dirs: list[str] = field(default_factory=lambda: ["docs", "."])
    code_dirs: list[str] = field(default_factory=lambda: ["."])
    ignore_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE))
    extensions: list[str] = field(default_factory=lambda: sorted(ALL_EXTENSIONS))
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = 512
    chunk_overlap: int = 64

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "doc_dirs": self.doc_dirs,
            "code_dirs": self.code_dirs,
            "ignore_patterns": self.ignore_patterns,
            "extensions": self.extensions,
            "embedding_model": self.embedding_model,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectConfig:
        return cls(
            name=data.get("name", ""),
            doc_dirs=data.get("doc_dirs", ["docs", "."]),
            code_dirs=data.get("code_dirs", ["."]),
            ignore_patterns=data.get("ignore_patterns", list(DEFAULT_IGNORE)),
            extensions=data.get("extensions", sorted(ALL_EXTENSIONS)),
            embedding_model=data.get("embedding_model", "text-embedding-3-small"),
            chunk_size=data.get("chunk_size", 512),
            chunk_overlap=data.get("chunk_overlap", 64),
        )


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk up from start to find a directory with a project marker."""
    current = (start or Path.cwd()).resolve()
    for _ in range(20):  # safety limit
        for marker in PROJECT_MARKERS:
            if (current / marker).exists():
                return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def detect_project_name(root: Path) -> str:
    """Try to detect project name from project files."""
    # Try pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            import tomllib

            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            name = data.get("project", {}).get("name", "")
            if name:
                return name
        except Exception:
            pass

    # Try package.json
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            with open(pkg_json) as f:
                data = json.load(f)
            name = data.get("name", "")
            if name:
                return name
        except Exception:
            pass

    # Try go.mod
    go_mod = root / "go.mod"
    if go_mod.exists():
        try:
            first_line = go_mod.read_text().split("\n")[0]
            if first_line.startswith("module "):
                return first_line.split()[-1].split("/")[-1]
        except Exception:
            pass

    # Fallback to directory name
    return root.name


def load_config(project_dir: Path | None = None) -> ProjectConfig:
    """Load project config from .ragops/config.yaml."""
    root = project_dir or find_project_root() or Path.cwd()
    config_path = root / CONFIG_DIR / CONFIG_FILE

    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return ProjectConfig.from_dict(data)

    # Return defaults with detected name
    return ProjectConfig(name=detect_project_name(root))


def save_config(config: ProjectConfig, project_dir: Path) -> Path:
    """Save project config to .ragops/config.yaml."""
    config_dir = project_dir / CONFIG_DIR
    config_dir.mkdir(exist_ok=True)

    config_path = config_dir / CONFIG_FILE
    with open(config_path, "w") as f:
        yaml.dump(
            config.to_dict(),
            f,
            default_flow_style=False,
            sort_keys=False,
            indent=2,
        )

    # Add .ragops/ to gitignore if not present
    gitignore = project_dir / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if ".ragops/" not in content:
            with open(gitignore, "a") as f:
                f.write("\n# RAG Ops\n.ragops/\n")
    else:
        gitignore.write_text("# RAG Ops\n.ragops/\n")

    return config_path
