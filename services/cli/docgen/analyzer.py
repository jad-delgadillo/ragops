"""Source code analyzer for auto-generating documentation."""

from __future__ import annotations

import ast
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CodeContext:
    """Consolidated context about a project's source code."""

    project_name: str
    file_tree: list[str] = field(default_factory=list)
    top_level_modules: list[str] = field(default_factory=list)
    key_symbols: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    tech_stack: list[str] = field(default_factory=list)


class Analyzer:
    """Analyzes source code to extract structural context."""

    def __init__(self, root_dir: Path, ignore_patterns: list[str] | None = None):
        self.root_dir = root_dir.resolve()
        self.ignore_patterns = ignore_patterns or [
            "node_modules",
            "__pycache__",
            ".git",
            ".venv",
            "venv",
            "dist",
            "build",
        ]

    def analyze(self) -> CodeContext:
        """Scan project and return context for document generation."""
        ctx = CodeContext(project_name=self.root_dir.name)

        # 1. Walk the tree
        self._scan_structure(ctx)

        # 2. Detect Tech Stack
        self._detect_stack(ctx)

        # 3. Analyze Key Modules
        self._analyze_key_modules(ctx)

        return ctx

    def _scan_structure(self, ctx: CodeContext) -> None:
        """Build a high-level file tree."""
        tree = []
        for root, dirs, files in os.walk(self.root_dir):
            # Prune ignored directories
            dirs[:] = [d for d in dirs if d not in self.ignore_patterns]

            rel_path = Path(root).relative_to(self.root_dir)
            if rel_path == Path("."):
                depth = 0
            else:
                depth = len(rel_path.parts)

            # Only scan up to depth 3 for the high-level summary
            if depth > 3:
                continue

            for f in files:
                if any(f.endswith(ext) for ext in [".py", ".js", ".ts", ".tsx", ".go", ".java"]):
                    tree.append(str(rel_path / f))

        ctx.file_tree = sorted(tree)

    def _detect_stack(self, ctx: CodeContext) -> None:
        """Detect tech stack based on markers."""
        stack = []
        markers = {
            "package.json": "Node.js",
            "pyproject.toml": "Python",
            "requirements.txt": "Python",
            "go.mod": "Go",
            "Cargo.toml": "Rust",
            "tsconfig.json": "TypeScript",
            "docker-compose.yml": "Docker",
            "terraform": "Terraform",
            "next.config.js": "Next.js",
            "tailwind.config.js": "TailwindCSS",
        }

        for marker, tech in markers.items():
            if (self.root_dir / marker).exists() or any(marker in str(p) for p in ctx.file_tree):
                if tech not in stack:
                    stack.append(tech)

        ctx.tech_stack = stack

    def _analyze_key_modules(self, ctx: CodeContext) -> None:
        """Perform deeper analysis of key files (entrypoints, main logic)."""
        # Look for entry points
        candidates = [
            "main.py",
            "app.py",
            "index.js",
            "App.tsx",
            "handler.py",
            "main.go",
        ]

        found_candidates = []
        for f in ctx.file_tree:
            if any(cand in f for cand in candidates):
                found_candidates.append(f)

        # Limit to top 5 key files for analysis
        for f_path in found_candidates[:5]:
            full_path = self.root_dir / f_path
            if f_path.endswith(".py"):
                ctx.key_symbols[f_path] = self._parse_python(full_path)
            # Add JS/TS parsing here in next iteration

    def _parse_python(self, file_path: Path) -> dict[str, Any]:
        """Extract classes, functions, and docstrings from Python files."""
        try:
            tree = ast.parse(file_path.read_text(errors="replace"))
            data = {"classes": [], "functions": [], "docstring": ast.get_docstring(tree)}

            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    data["classes"].append({
                        "name": node.name,
                        "docstring": ast.get_docstring(node),
                        "methods": [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                    })
                elif isinstance(node, ast.FunctionDef):
                    data["functions"].append({
                        "name": node.name,
                        "docstring": ast.get_docstring(node),
                    })
            return data
        except Exception as e:
            logger.warning("Could not parse Python file %s: %s", file_path, e)
            return {"error": str(e)}
