"""CODEOWNERS-aware ranking helpers for chat and retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from fnmatch import fnmatch
from pathlib import Path

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,}")


@dataclass(frozen=True)
class CodeownersRule:
    """Parsed CODEOWNERS rule."""

    pattern: str
    owners: tuple[str, ...]
    owner_tokens: frozenset[str]
    area_tokens: frozenset[str]


def tokenize_question(question: str) -> set[str]:
    """Tokenize user question into normalized search tokens."""
    return {tok for tok in TOKEN_RE.findall(question.lower()) if len(tok) >= 3}


def ownership_bonus_for_source(source: str, *, question_tokens: set[str]) -> float:
    """Return ranking bonus based on CODEOWNERS owner/area token overlap."""
    bonus, _ = ownership_debug_signals_for_source(source, question_tokens=question_tokens)
    return bonus


def ownership_debug_signals_for_source(
    source: str,
    *,
    question_tokens: set[str],
) -> tuple[float, list[str]]:
    """Return ownership bonus and explainable debug signals."""
    if not question_tokens:
        return 0.0, []
    owner_tokens, area_tokens = _ownership_profile_for_source(source)
    if not owner_tokens and not area_tokens:
        return 0.0, []

    signals: list[str] = []
    bonus = 0.0

    owner_hits = sorted(owner_tokens.intersection(question_tokens))
    area_hits = sorted(area_tokens.intersection(question_tokens))

    if owner_hits:
        bonus += 0.18
        signals.append(f"ownership_owner_match:{','.join(owner_hits[:3])}")
    if area_hits:
        bonus += 0.10
        signals.append(f"ownership_area_match:{','.join(area_hits[:3])}")
    return bonus, signals


@lru_cache(maxsize=4096)
def _ownership_profile_for_source(source: str) -> tuple[frozenset[str], frozenset[str]]:
    """Resolve owner and area tokens for a source file from CODEOWNERS."""
    path = Path(source).expanduser()
    if not path.is_absolute() or not path.exists():
        return frozenset(), frozenset()

    root = _find_repo_root(path if path.is_dir() else path.parent)
    if root is None:
        return frozenset(), frozenset()

    rel = _relative_posix(path, root)
    if not rel:
        return frozenset(), frozenset()

    rules = _load_codeowners_rules(root)
    if not rules:
        return frozenset(), frozenset()

    matched: CodeownersRule | None = None
    for rule in rules:
        if _pattern_matches(rule.pattern, rel):
            matched = rule

    if matched is None:
        return frozenset(), frozenset()
    return matched.owner_tokens, matched.area_tokens


def _relative_posix(path: Path, root: Path) -> str:
    """Return POSIX relative path if possible."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return ""


def _find_repo_root(start: Path) -> Path | None:
    """Find nearest repo-like root for a source path."""
    cursor = start.resolve()
    while True:
        if (cursor / ".git").exists():
            return cursor
        if _find_codeowners_path(cursor) is not None:
            return cursor
        if cursor.parent == cursor:
            return None
        cursor = cursor.parent


def _find_codeowners_path(root: Path) -> Path | None:
    """Return first CODEOWNERS path found under a root."""
    candidates = (
        root / "CODEOWNERS",
        root / ".github" / "CODEOWNERS",
        root / "docs" / "CODEOWNERS",
    )
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


@lru_cache(maxsize=128)
def _load_codeowners_rules(root: Path) -> tuple[CodeownersRule, ...]:
    """Load and parse CODEOWNERS rules for a repository root."""
    path = _find_codeowners_path(root)
    if path is None:
        return tuple()

    rules: list[CodeownersRule] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern = parts[0]
        owners = tuple(parts[1:])
        owner_tokens = _owner_tokens(owners)
        area_tokens = _area_tokens(pattern)
        rules.append(
            CodeownersRule(
                pattern=pattern,
                owners=owners,
                owner_tokens=owner_tokens,
                area_tokens=area_tokens,
            )
        )
    return tuple(rules)


def _owner_tokens(owners: tuple[str, ...]) -> frozenset[str]:
    """Normalize @owner and @org/team handles into searchable tokens."""
    tokens: set[str] = set()
    for owner in owners:
        normalized = owner.lstrip("@").lower()
        for piece in re.split(r"[/._-]+", normalized):
            if len(piece) >= 3:
                tokens.add(piece)
    return frozenset(tokens)


def _area_tokens(pattern: str) -> frozenset[str]:
    """Extract coarse area hints from CODEOWNERS path pattern."""
    cleaned = pattern.strip().lstrip("/")
    pieces = [p for p in re.split(r"[/]+", cleaned) if p]
    tokens: set[str] = set()
    for piece in pieces:
        for part in re.split(r"[^a-zA-Z0-9_-]+", piece.lower()):
            if len(part) < 3:
                continue
            if any(ch in part for ch in "*?[]!"):
                continue
            tokens.add(part)
    return frozenset(tokens)


def _pattern_matches(pattern: str, rel_path: str) -> bool:
    """Approximate CODEOWNERS pattern matching for ranking hints."""
    pat = pattern.strip()
    if not pat:
        return False
    rel = rel_path.lstrip("./")

    # Directory rule.
    if pat.endswith("/"):
        prefix = pat.lstrip("/").rstrip("/")
        return rel == prefix or rel.startswith(prefix + "/")

    anchored = pat.startswith("/")
    normalized = pat.lstrip("/")

    if anchored:
        return fnmatch(rel, normalized)

    # Non-anchored path pattern with slash can match anywhere.
    if "/" in normalized:
        if fnmatch(rel, normalized):
            return True
        return rel.endswith("/" + normalized) or rel == normalized

    # Basename pattern.
    basename = Path(rel).name
    return fnmatch(basename, normalized)
