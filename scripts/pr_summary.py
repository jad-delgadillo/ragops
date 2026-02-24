#!/usr/bin/env python3
"""Build a heuristic PR summary for GitHub comment automation."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

COMMENT_MARKER = "<!-- ragops-pr-summary -->"


def _run_git(args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "git command failed"
        raise RuntimeError(detail)
    return proc.stdout


def changed_files(base: str, head: str) -> list[str]:
    """Return changed files for a PR range."""
    range_spec = f"{base}...{head}"
    try:
        output = _run_git(["diff", "--name-only", "--diff-filter=ACMRTUXB", range_spec])
    except RuntimeError:
        output = _run_git(["diff", "--name-only", "--diff-filter=ACMRTUXB", base, head])
    return [line.strip() for line in output.splitlines() if line.strip()]


def load_scan_payload(path: Path) -> dict[str, Any]:
    """Load optional scan output JSON when present."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def top_counts(counter: Counter[str], limit: int) -> list[tuple[str, int]]:
    items = [(k, v) for k, v in counter.items() if k]
    items.sort(key=lambda item: (-item[1], item[0]))
    return items[:limit]


def confidence_score(*, file_count: int, has_scan_metadata: bool, has_index_version: bool) -> float:
    """Return heuristic confidence score in [0, 1]."""
    if file_count <= 0:
        return 0.15

    score = 0.75
    if file_count > 80:
        score -= 0.35
    elif file_count > 40:
        score -= 0.20
    elif file_count > 20:
        score -= 0.08

    if has_scan_metadata:
        score += 0.08
    if has_index_version:
        score += 0.07

    return max(0.05, min(0.95, score))


def confidence_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.50:
        return "medium"
    return "low"


def render_summary(
    *,
    files: list[str],
    scan_payload: dict[str, Any],
    base: str,
    head: str,
) -> str:
    area_counter: Counter[str] = Counter()
    ext_counter: Counter[str] = Counter()

    for file_path in files:
        parts = Path(file_path).parts
        area = "/".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "unknown")
        area_counter[area] += 1
        ext = Path(file_path).suffix.lower() or "(no-ext)"
        ext_counter[ext] += 1

    index_metadata = scan_payload.get("index_metadata", {})
    has_scan_metadata = isinstance(index_metadata, dict) and bool(index_metadata)
    has_index_version = (
        isinstance(index_metadata, dict) and bool(index_metadata.get("index_version"))
    )

    score = confidence_score(
        file_count=len(files),
        has_scan_metadata=has_scan_metadata,
        has_index_version=has_index_version,
    )
    label = confidence_label(score)

    area_summary = ", ".join(f"`{k}` ({v})" for k, v in top_counts(area_counter, 5)) or "none"
    ext_summary = ", ".join(f"`{k}` ({v})" for k, v in top_counts(ext_counter, 5)) or "none"
    sample_files = "\n".join(f"- `{path}`" for path in files[:20]) or "- (none)"
    remainder = len(files) - min(len(files), 20)
    extra_line = f"- ... plus {remainder} more file(s)" if remainder > 0 else ""

    lines = [
        COMMENT_MARKER,
        "### RAGOps PR Summary (Heuristic)",
        f"- Diff range: `{base[:12]}...{head[:12]}`",
        f"- Changed files: **{len(files)}**",
        f"- Top areas: {area_summary}",
        f"- Top file types: {ext_summary}",
        f"- Retrieval confidence (heuristic): **{label}** ({score:.2f})",
    ]

    if has_scan_metadata:
        lines.extend(
            [
                "- Incremental scan metadata:",
                (
                    f"  - embedding: `{index_metadata.get('embedding_provider', 'unknown')}`/"
                    f"`{index_metadata.get('embedding_model', 'unknown')}`"
                ),
                f"  - index_version: `{index_metadata.get('index_version', 'n/a')}`",
                f"  - repo_commit: `{index_metadata.get('repo_commit', 'n/a')}`",
            ]
        )
    else:
        lines.append(
            "- Incremental scan metadata: unavailable "
            "(fallback summary generated without embeddings)."
        )

    lines.extend(["", "#### Changed Files (first 20)", sample_files])
    if extra_line:
        lines.append(extra_line)
    lines.extend(
        [
            "",
            "_Confidence is heuristic and indicates summary reliability, not correctness._",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate markdown PR summary for GitHub comments."
    )
    parser.add_argument("--base", required=True, help="Base commit SHA")
    parser.add_argument("--head", required=True, help="Head commit SHA")
    parser.add_argument("--scan-json", default="scan-output.json", help="Optional scan JSON path")
    parser.add_argument("--out", required=True, help="Output markdown path")
    args = parser.parse_args()

    files = changed_files(args.base, args.head)
    scan_payload = load_scan_payload(Path(args.scan_json))
    summary = render_summary(files=files, scan_payload=scan_payload, base=args.base, head=args.head)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(summary, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
