"""Tests for eval dataset parsing and expectation checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.cli.eval import load_eval_cases


def test_load_eval_cases_yaml(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.yaml"
    dataset.write_text(
        """
- id: c1
  question: "How does ingest work?"
  expected_source_contains: "pipeline.py"
- question: "Where is query handler?"
  expected_answer_contains:
    - "handler"
""".strip(),
        encoding="utf-8",
    )

    cases = load_eval_cases(dataset, default_collection="default")
    assert len(cases) == 2
    assert cases[0].case_id == "c1"
    assert cases[0].expected_source_contains == ["pipeline.py"]
    assert cases[1].case_id == "case-2"
    assert cases[1].expected_answer_contains == ["handler"]


def test_load_eval_cases_requires_question(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.json"
    dataset.write_text('[{"id":"c1"}]', encoding="utf-8")
    with pytest.raises(ValueError):
        load_eval_cases(dataset, default_collection="default")
