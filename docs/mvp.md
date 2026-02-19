# MVP Definition: CLI Codebase Copilot

## Product Statement

RAG Ops helps engineers understand unfamiliar codebases fast.

The MVP is a local CLI workflow:
1. `ragops init`
2. `ragops scan`
3. `ragops chat`

## User and Job To Be Done

Primary user:
- Engineer joining or revisiting a codebase.

Core job:
- "Get me from zero context to useful answers, with citations I can trust."

## MVP Scope

In scope:
- Project initialization with local defaults (`ragops init`)
- One-command indexing and manual generation (`ragops scan`)
- Multi-turn, citation-grounded Q and A (`ragops chat`)
- Session continuity across turns
- Feedback capture (`ragops feedback`)
- Repeatable quality checks (`ragops eval`)

Also in scope but secondary:
- GitHub repo indexing (`ragops repo add`, `/v1/repos/onboard`)
- Optional frontend demo flow

## Non-Goals for This MVP

- Billing and tenant management
- Enterprise auth and role models
- Full observability platform
- Bedrock production path
- `s3_prefix` ingestion implementation in `/v1/ingest`

## Scan Contract

`ragops scan` must:
1. Ingest project code into the selected collection.
2. Generate project manuals.
3. Ingest those manuals so chat can use them immediately.

Required manual set includes:
- `PROJECT_OVERVIEW.md`
- `ARCHITECTURE_MAP.md`
- `CODEBASE_MANUAL.md`
- `API_MANUAL.md`
- `ARCHITECTURE_DIAGRAM.md`
- `OPERATIONS_RUNBOOK.md`
- `UNKNOWNS_AND_GAPS.md`
- `DATABASE_MANUAL.md`
- `SCAN_INDEX.json`

Detailed spec: `docs/scan-output-spec.md`.

## Success Metrics

Track each run in `docs/mvp-results.md`.

- `time_to_first_answer_seconds`
- `scan_duration_seconds`
- `chat_p50_latency_ms`
- `chat_p95_latency_ms`
- `citation_coverage_rate`
- `eval_source_hit_rate`
- `eval_answer_hit_rate`
- `feedback_positive_rate`

Recommended initial targets:
- `time_to_first_answer_seconds < 180`
- `chat_p95_latency_ms < 5000`
- `citation_coverage_rate >= 80%`
- `eval_source_hit_rate >= 70%`
- `eval_answer_hit_rate >= 70%`

## Functional Acceptance Criteria

1. In a new project directory, `init -> scan -> chat` runs end to end without Docker.
2. Answerable chat questions include at least one citation with source and line range.
3. Follow-up questions in the same session preserve context.
4. `scan` generates the required manual set, including `ARCHITECTURE_DIAGRAM.md`.
5. `feedback` accepts positive and negative verdicts and stores records.
6. Service tests pass locally (`pytest services/`).

## Demo Acceptance Criteria

1. A first-time user can complete `init -> scan -> first answer` in under 10 minutes.
2. Demo includes at least one answer citing a concrete file and line interval.
3. Demo includes one follow-up question in the same session.

## Guardrails

- Prefer grounded explanations over raw code dumps.
- Keep manuals deterministic where possible and clearly mark inferred content.
- Default to OpenAI embeddings plus OpenAI LLM for the stable path.

## Positioning

Use this phrasing consistently:
"RAG Ops is a CLI codebase copilot that indexes any codebase and answers questions with citations."
