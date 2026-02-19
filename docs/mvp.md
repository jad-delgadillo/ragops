# MVP Specification: GitHub Repo Onboarding Copilot

## Product Statement

RAG Ops is a developer onboarding copilot that converts a GitHub repository into a citation-grounded Q&A assistant.

## Target User

- Primary: engineers joining a new codebase.
- Secondary: engineering managers and tech leads onboarding teammates.

## Core User Journey

1. User submits a GitHub repository URL.
2. System ingests source files into `<collection>_code`.
3. System optionally generates manuals and ingests them into `<collection>_manuals`.
4. User asks onboarding questions in chat mode.
5. System responds with concise grounded answers and citations.
6. User records feedback to improve quality tracking.

## In Scope (MVP)

- Repo onboarding via CLI and API:
  - Clone/download repo archive.
  - Ingest code into isolated code collection.
  - Optional manual generation and manual ingestion.
- Conversational onboarding chat:
  - Session continuity via `session_id`.
  - Answer modes (`default`, `explain_like_junior`, etc.).
  - Citation output (`source`, `line_start`, `line_end`, `similarity`).
- Feedback loop:
  - Positive/negative verdict.
  - Optional metadata/comment capture.
- Basic evaluation harness:
  - Dataset-driven checks for source-hit and answer-hit.
- Local-first setup:
  - Docker Postgres + pgvector.
  - CLI workflow for end-to-end validation.

## Out of Scope (Now)

- S3-prefix ingestion for `/v1/ingest` in cloud runtime.
- Bedrock provider production support.
- Enterprise auth models beyond API keys.
- Multi-tenant org/user management and billing.
- Full observability stack (dashboards/alerts/tracing backend).

## MVP Success Criteria

### Functional Acceptance

1. Given a valid public GitHub URL, onboarding completes and returns collection names.
2. Chat answers use indexed context and return at least one citation for answerable questions.
3. Feedback endpoint writes records for valid verdicts.
4. Async onboarding returns `202` + `job_id`, and status polling reaches terminal state.
5. Test suite passes locally (`pytest services/`).

### Demo Acceptance

1. Complete flow can be shown in under 10 minutes:
   - repo add/onboard
   - first question
   - follow-up question in same session
   - feedback submit
2. Demo includes at least one question where citation points to a concrete source file and line range.

## Quality Metrics

Track per run (store in `docs/mvp-results.md`):

- `onboarding_duration_seconds` (repo submit to ready).
- `chat_p50_latency_ms`.
- `chat_p95_latency_ms`.
- `citation_coverage_rate`:
  - percentage of non-empty answers that include >=1 citation.
- `eval_source_hit_rate`.
- `eval_answer_hit_rate`.
- `feedback_positive_rate`.

## Engineering Constraints

- Default provider path: OpenAI embeddings + OpenAI LLM.
- Database schema currently expects 1536-dim vectors.
- Chat quality guardrails should avoid raw code-dump answers when user asked for explanation.

## 2-Week Execution Plan

### Week 1: Scope and Proof

1. Freeze scope to onboarding copilot features only.
2. Rewrite README and docs around the MVP narrative.
3. Harden golden path demo script.
4. Expand eval dataset from smoke checks to onboarding-focused coverage.
5. Add/adjust tests for onboarding async states and chat response shape.

### Week 2: Reliability and Evidence

1. Tighten error messages and edge-case handling in onboarding/chat flows.
2. Improve frontend status UX for onboarding and session continuity.
3. Run repeated eval and collect KPI snapshots.
4. Publish `docs/mvp-results.md` with measured results.
5. Prepare short demo and final CV bullets backed by metrics.

## CV Positioning

Use this phrasing consistently:

"Built a GitHub Repo Onboarding Copilot that ingests code/manuals and delivers citation-grounded, session-aware codebase Q&A with measurable quality feedback loops."
