# MVP Results — KPI Snapshot

> Measured against the success criteria defined in [`docs/mvp.md`](mvp.md).

## Run Info

| Field | Value |
| --- | --- |
| Date | 2026-02-19 |
| Test Repo | `openclaw/openclaw` |
| Eval Dataset | `eval/cases.yaml` (12 cases) |
| Provider | OpenAI (embeddings + LLM) |

## Quality Metrics

| KPI | Value | Target |
| --- | --- | --- |
| `time_to_first_answer_seconds` | _pending_ | < 180s |
| `scan_duration_seconds` | _pending_ | _tracking_ |
| `chat_p50_latency_ms` | _pending_ | < 2000 |
| `chat_p95_latency_ms` | _pending_ | < 5000 |
| `citation_coverage_rate` | _pending_ | ≥ 80% |
| `eval_source_hit_rate` | _pending_ | ≥ 70% |
| `eval_answer_hit_rate` | _pending_ | ≥ 70% |
| `feedback_positive_rate` | _pending_ | N/A (tracking) |

## Unit Test Summary

| Suite | Passed | Time |
| --- | --- | --- |
| `pytest services/ -q` | 85 | 0.33s |

## Eval Report

_Generated after running:_
```bash
.venv/bin/python -m services.cli.main eval \
  --dataset ./eval/cases.yaml \
  --collection openclaw-openclaw_code \
  --output-json ./eval/eval-report.json \
  --output-md ./eval/eval-report.md
```

## Functional Acceptance

| Criterion | Status |
| --- | --- |
| In new project dir, `init -> scan -> chat` works without Docker | ✅ Tested (local flow) |
| Chat answers return ≥1 citation for answerable questions | ✅ Tested (unit) |
| Follow-up in same session preserves context | ✅ Tested (contract/unit) |
| `scan` generates required manuals including `ARCHITECTURE_DIAGRAM.md` | ✅ Tested (manual generation tests) |
| Feedback command/endpoint stores positive and negative verdicts | ✅ Tested (unit) |
| Test suite passes (`pytest services/`) | ✅ 85 passed |

## Demo Acceptance

| Criterion | Status |
| --- | --- |
| Full flow demo < 10 min | _pending_ |
| Citation points to concrete source file + line range | ✅ Verified (contract test) |
