"""Evaluation runner for retrieval and answer quality on a fixed dataset."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from services.api.app.retriever import query
from services.core.config import Settings
from services.core.providers import EmbeddingProvider, LLMProvider


@dataclass
class EvalCase:
    """Evaluation dataset case."""

    case_id: str
    question: str
    collection: str
    expected_source_contains: list[str]
    expected_answer_contains: list[str]


def _normalize_expectations(value: Any) -> list[str]:
    """Normalize expectation field into lowercase tokens."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip().lower()] if value.strip() else []
    if isinstance(value, list):
        return [str(v).strip().lower() for v in value if str(v).strip()]
    raise ValueError("Expected expectation field to be string or list")


def load_eval_cases(dataset_path: Path, default_collection: str) -> list[EvalCase]:
    """Load eval cases from JSON/YAML."""
    raw = dataset_path.read_text(encoding="utf-8")
    if dataset_path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(raw)
    else:
        data = json.loads(raw)

    if not isinstance(data, list):
        raise ValueError("Evaluation dataset must be a JSON/YAML array")

    cases: list[EvalCase] = []
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Case #{idx} must be an object")
        question = str(item.get("question", "")).strip()
        if not question:
            raise ValueError(f"Case #{idx} missing required field 'question'")

        case_id = str(item.get("id", f"case-{idx}"))
        collection = str(item.get("collection", default_collection)).strip() or default_collection
        expected_source = _normalize_expectations(item.get("expected_source_contains"))
        expected_answer = _normalize_expectations(item.get("expected_answer_contains"))
        cases.append(
            EvalCase(
                case_id=case_id,
                question=question,
                collection=collection,
                expected_source_contains=expected_source,
                expected_answer_contains=expected_answer,
            )
        )
    return cases


def _evaluate_source_hit(citations: list[dict[str, Any]], expected_tokens: list[str]) -> bool:
    """Whether expected source token appears in citation sources."""
    if not expected_tokens:
        return True
    haystack = " ".join(str(c.get("source", "")).lower() for c in citations)
    return any(token in haystack for token in expected_tokens)


def _evaluate_answer_hit(answer: str, expected_tokens: list[str]) -> bool:
    """Whether expected answer token appears in answer text."""
    if not expected_tokens:
        return True
    haystack = answer.lower()
    return all(token in haystack for token in expected_tokens)


def run_eval(
    *,
    cases: list[EvalCase],
    embedding_provider: EmbeddingProvider,
    llm_provider: LLMProvider | None,
    top_k: int,
    settings: Settings,
) -> dict[str, Any]:
    """Execute all eval cases and compute summary metrics."""
    results: list[dict[str, Any]] = []
    source_hits = 0
    answer_hits = 0
    latencies: list[float] = []

    for case in cases:
        qr = query(
            question=case.question,
            embedding_provider=embedding_provider,
            llm_provider=llm_provider,
            collection=case.collection,
            top_k=top_k,
            settings=settings,
        )
        source_hit = _evaluate_source_hit(qr.citations, case.expected_source_contains)
        answer_hit = _evaluate_answer_hit(qr.answer, case.expected_answer_contains)
        source_hits += int(source_hit)
        answer_hits += int(answer_hit)
        latencies.append(qr.latency_ms)
        results.append(
            {
                "id": case.case_id,
                "question": case.question,
                "collection": case.collection,
                "mode": qr.mode,
                "retrieved": qr.retrieved,
                "latency_ms": round(qr.latency_ms, 1),
                "source_hit": source_hit,
                "answer_hit": answer_hit,
                "citations": qr.citations,
                "answer": qr.answer,
            }
        )

    total = len(cases)
    avg_latency = sum(latencies) / total if total else 0.0
    summary = {
        "total_cases": total,
        "source_hit_rate": round(source_hits / total, 4) if total else 0.0,
        "answer_hit_rate": round(answer_hits / total, 4) if total else 0.0,
        "avg_latency_ms": round(avg_latency, 1),
        "passed_all_rate": round(
            sum(1 for r in results if r["source_hit"] and r["answer_hit"]) / total,
            4,
        )
        if total
        else 0.0,
    }

    return {"summary": summary, "results": results}


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render a markdown report from eval output."""
    summary = report["summary"]
    rows = []
    for row in report["results"]:
        rows.append(
            "| {id} | {mode} | {retrieved} | {latency_ms} | {source_hit} | {answer_hit} |".format(
                **row
            )
        )
    table_rows = "\n".join(rows) if rows else "| - | - | - | - | - | - |"

    return f"""# Evaluation Report

## Summary
- Total cases: {summary['total_cases']}
- Source hit rate: {summary['source_hit_rate']:.2%}
- Answer hit rate: {summary['answer_hit_rate']:.2%}
- Passed-all rate: {summary['passed_all_rate']:.2%}
- Average latency: {summary['avg_latency_ms']} ms

## Case Results
| Case | Mode | Retrieved | Latency (ms) | Source Hit | Answer Hit |
| --- | --- | --- | --- | --- | --- |
{table_rows}
"""
