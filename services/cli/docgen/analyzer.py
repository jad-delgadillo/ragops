"""Source code analyzer for deterministic onboarding document generation."""

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
    framework_signals: list[dict[str, str]] = field(default_factory=list)
    entrypoints: list[dict[str, str]] = field(default_factory=list)
    ownership_map: list[dict[str, str]] = field(default_factory=list)
    gaps: list[dict[str, str]] = field(default_factory=list)


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

        # 1. Walk tree and basic shape metadata.
        self._scan_structure(ctx)

        # 2. Detect stack/frameworks.
        self._detect_stack(ctx)

        # 3. Discover entrypoints and ownership.
        self._discover_entrypoints(ctx)
        self._build_ownership_map(ctx)
        self._collect_gaps(ctx)

        # 4. Analyze key modules.
        self._analyze_key_modules(ctx)

        return ctx

    def _scan_structure(self, ctx: CodeContext) -> None:
        """Build a high-level file tree."""
        tree: list[str] = []
        ext_counts: dict[str, int] = {}
        top_level_counts: dict[str, int] = {}
        allowed_suffixes = {
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".go",
            ".java",
            ".md",
            ".txt",
            ".rst",
            ".yaml",
            ".yml",
            ".toml",
            ".json",
            ".sql",
        }
        marker_files = {
            "Dockerfile",
            "docker-compose.yml",
            "pyproject.toml",
            "requirements.txt",
            "package.json",
            "go.mod",
            "Cargo.toml",
            "CODEOWNERS",
        }
        for root, dirs, files in os.walk(self.root_dir):
            # Prune ignored directories
            dirs[:] = [d for d in dirs if d not in self.ignore_patterns]

            rel_path = Path(root).relative_to(self.root_dir)
            if rel_path == Path("."):
                depth = 0
            else:
                depth = len(rel_path.parts)

            # Keep summary bounded for speed while preserving useful context.
            if depth > 5:
                continue

            for f in files:
                rel = str(rel_path / f)
                suffix = Path(f).suffix.lower()
                if suffix in allowed_suffixes or f in marker_files:
                    tree.append(rel)
                    ext_counts[suffix or "<none>"] = ext_counts.get(suffix or "<none>", 0) + 1
                    root_part = rel.split("/", 1)[0] if "/" in rel else rel
                    top_level_counts[root_part] = top_level_counts.get(root_part, 0) + 1

        ctx.file_tree = sorted(tree)
        ctx.top_level_modules = [
            item
            for item, _ in sorted(top_level_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:12]
        ]
        ctx.summary = {
            "file_count": len(ctx.file_tree),
            "top_level_counts": top_level_counts,
            "ext_counts": dict(sorted(ext_counts.items(), key=lambda pair: (-pair[1], pair[0]))),
        }

    def _detect_stack(self, ctx: CodeContext) -> None:
        """Detect tech stack based on markers."""
        stack = []
        framework_signals: list[dict[str, str]] = []
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
            "services/api/app/handler.py": "AWS Lambda",
            "Dockerfile": "Docker",
            ".github/workflows": "GitHub Actions",
        }

        for marker, tech in markers.items():
            if (self.root_dir / marker).exists() or any(marker in str(p) for p in ctx.file_tree):
                if tech not in stack:
                    stack.append(tech)
                framework_signals.append(
                    {
                        "name": tech,
                        "signal": marker,
                        "source": marker if (self.root_dir / marker).exists() else self._first_match(ctx, marker),
                        "confidence": "high" if (self.root_dir / marker).exists() else "medium",
                    }
                )

        ctx.tech_stack = stack
        ctx.framework_signals = framework_signals

    def _discover_entrypoints(self, ctx: CodeContext) -> None:
        """Identify likely runtime entrypoints with deterministic confidence labels."""
        rules = [
            ("services/cli/main.py", "Primary CLI entrypoint", "high"),
            ("services/api/app/handler.py", "API Lambda/HTTP entrypoint", "high"),
            ("services/ingest/app/handler.py", "Ingest Lambda entrypoint", "high"),
            ("main.py", "Top-level Python entrypoint", "medium"),
            ("app.py", "Top-level app entrypoint", "medium"),
            ("manage.py", "Django/manage script", "medium"),
            ("index.js", "Node runtime entrypoint", "medium"),
            ("server.js", "Node server entrypoint", "medium"),
            ("src/main.ts", "TypeScript app entrypoint", "medium"),
            ("src/main.tsx", "Frontend TypeScript entrypoint", "medium"),
        ]
        discovered: list[dict[str, str]] = []
        available = set(ctx.file_tree)

        for path, reason, confidence in rules:
            if path in available:
                discovered.append(
                    {
                        "path": path,
                        "reason": reason,
                        "confidence": confidence,
                        "source": path,
                    }
                )

        # Heuristic fallback when explicit entrypoints are missing.
        if not discovered:
            for path in ctx.file_tree:
                if path.endswith(("/handler.py", "/main.py", "/app.py")):
                    discovered.append(
                        {
                            "path": path,
                            "reason": "Heuristic entrypoint candidate",
                            "confidence": "low",
                            "source": path,
                        }
                    )
                    if len(discovered) >= 5:
                        break

        ctx.entrypoints = discovered

    def _build_ownership_map(self, ctx: CodeContext) -> None:
        """Build ownership map from CODEOWNERS or deterministic folder fallback."""
        codeowners_candidates = [
            self.root_dir / "CODEOWNERS",
            self.root_dir / ".github" / "CODEOWNERS",
            self.root_dir / "docs" / "CODEOWNERS",
        ]
        for path in codeowners_candidates:
            if path.exists():
                entries: list[dict[str, str]] = []
                for idx, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    entries.append(
                        {
                            "area": parts[0],
                            "owner": ", ".join(parts[1:]),
                            "confidence": "high",
                            "source": f"{path.relative_to(self.root_dir)}:{idx}",
                        }
                    )
                if entries:
                    ctx.ownership_map = entries[:20]
                    return

        # Fallback: infer areas by top-level file distribution.
        inferred: list[dict[str, str]] = []
        counts = ctx.summary.get("top_level_counts", {})
        for area, count in sorted(counts.items(), key=lambda pair: (-int(pair[1]), str(pair[0])))[:10]:
            inferred.append(
                {
                    "area": str(area),
                    "owner": "unassigned",
                    "confidence": "low",
                    "source": self._first_source_in_area(ctx, str(area)),
                    "file_count": str(count),
                }
            )
        ctx.ownership_map = inferred

    def _collect_gaps(self, ctx: CodeContext) -> None:
        """List deterministic documentation/operational gaps discovered by scan."""
        files = set(ctx.file_tree)
        markdown_count = sum(1 for f in ctx.file_tree if f.endswith(".md"))
        has_tests = any("/tests/" in f or f.startswith("tests/") for f in ctx.file_tree)
        has_ci = any(f.startswith(".github/workflows/") for f in ctx.file_tree)
        has_readme = any(Path(f).name.lower() == "readme.md" for f in ctx.file_tree)

        gaps: list[dict[str, str]] = []
        if not has_readme:
            gaps.append(
                {
                    "name": "missing_readme",
                    "detail": "README.md was not found at repository root.",
                    "confidence": "high",
                    "source": ".",
                }
            )
        if not has_tests:
            gaps.append(
                {
                    "name": "limited_tests_visibility",
                    "detail": "No conventional tests directory pattern was detected.",
                    "confidence": "medium",
                    "source": ".",
                }
            )
        if not has_ci:
            gaps.append(
                {
                    "name": "missing_ci_workflow",
                    "detail": "No .github/workflows pipeline was detected.",
                    "confidence": "high",
                    "source": ".github/workflows",
                }
            )
        if markdown_count < 2:
            gaps.append(
                {
                    "name": "minimal_docs_surface",
                    "detail": "Very few markdown docs were detected; onboarding may rely on source code.",
                    "confidence": "medium",
                    "source": ".",
                }
            )
        if not ctx.entrypoints:
            gaps.append(
                {
                    "name": "entrypoints_unclear",
                    "detail": "No strong runtime entrypoint was detected.",
                    "confidence": "low",
                    "source": ".",
                }
            )
        if "services/api/app/handler.py" not in files and "services/ingest/app/handler.py" not in files:
            gaps.append(
                {
                    "name": "api_surface_unclear",
                    "detail": "No known API handler path was detected in standard locations.",
                    "confidence": "low",
                    "source": ".",
                }
            )
        ctx.gaps = gaps

    def _analyze_key_modules(self, ctx: CodeContext) -> None:
        """Perform deeper analysis of key files (entrypoints, main logic)."""
        found_candidates: list[str] = []
        for entry in ctx.entrypoints:
            path = entry.get("path", "")
            if path and path.endswith(".py") and path not in found_candidates:
                found_candidates.append(path)

        fallback_candidates = [
            "main.py",
            "app.py",
            "handler.py",
            "settings.py",
        ]
        for path in ctx.file_tree:
            if path.endswith(".py") and any(tag in path for tag in fallback_candidates):
                if path not in found_candidates:
                    found_candidates.append(path)
            if len(found_candidates) >= 10:
                break

        for f_path in found_candidates[:10]:
            full_path = self.root_dir / f_path
            if f_path.endswith(".py"):
                ctx.key_symbols[f_path] = self._parse_python(full_path)

    def _first_match(self, ctx: CodeContext, marker: str) -> str:
        """Return first file path matching marker, or marker itself if not present."""
        for path in ctx.file_tree:
            if marker in path:
                return path
        return marker

    def _first_source_in_area(self, ctx: CodeContext, area: str) -> str:
        """Return a deterministic source pointer for inferred area ownership."""
        prefix = f"{area}/"
        for path in ctx.file_tree:
            if path == area or path.startswith(prefix):
                return f"{path}:1"
        return f"{area}:1"

    def _parse_python(self, file_path: Path) -> dict[str, Any]:
        """Extract classes, functions, and docstrings from Python files."""
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8", errors="replace"))
            data = {"classes": [], "functions": [], "docstring": ast.get_docstring(tree)}

            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    data["classes"].append(
                        {
                            "name": node.name,
                            "docstring": ast.get_docstring(node),
                            "line": str(getattr(node, "lineno", 1)),
                            "methods": [n.name for n in node.body if isinstance(n, ast.FunctionDef)],
                        }
                    )
                elif isinstance(node, ast.FunctionDef):
                    data["functions"].append(
                        {
                            "name": node.name,
                            "docstring": ast.get_docstring(node),
                            "line": str(getattr(node, "lineno", 1)),
                        }
                    )
            return data
        except Exception as e:
            logger.warning("Could not parse Python file %s: %s", file_path, e)
            return {"error": str(e)}
