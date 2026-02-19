# RAG Ops MVP Execution Plan (CLI-First)

## Objective

Ship the MVP defined in `docs/mvp.md`: a CLI codebase copilot centered on:
1. `ragops init`
2. `ragops scan`
3. `ragops chat`

The output must be citation-grounded, session-aware, and measurable via KPI snapshots.

## Scope Lock

In scope:
- Local-first CLI workflow (`init`, `scan`, `chat`)
- Scan manual generation and ingest
- Citation-grounded chat with session continuity
- Feedback capture (`ragops feedback` / `/v1/feedback`)
- Eval harness and KPI tracking in `docs/mvp-results.md`
- Optional repo and frontend demos as secondary surfaces

Out of scope for MVP:
- `s3_prefix` ingestion implementation in `/v1/ingest` (currently `501`)
- Bedrock production path
- Billing and tenant management
- Enterprise auth model expansion
- Full observability stack

## Current Baseline (as of 2026-02-19)

- Latest recorded unit tests: `85 passed` (`.venv/bin/python -m pytest services/ -q`)
- Manual generation includes `ARCHITECTURE_DIAGRAM.md`
- KPI table exists but values are still mostly pending in `docs/mvp-results.md`

## Execution Rules

1. Execute phases in order and do not skip gates.
2. Prioritize CLI flow quality before secondary surfaces.
3. Make minimal, test-backed changes.
4. Keep evidence artifacts in-repo (`docs/`, `eval/`).
5. If a gate fails, fix before moving to next phase.

## Phase 0: Environment and Baseline

### Task 0.1: Local runtime setup
- [ ] Configure local env (`OPENAI_API_KEY`, `LLM_ENABLED=true`).
- [ ] Run `ragops init` in a fresh test project directory.
- [ ] Confirm storage defaults are local and usable (`sqlite` path valid).

### Task 0.2: Baseline health checks
- [ ] Run service tests:
```bash
.venv/bin/python -m pytest services/ -q
```
- [ ] Run config diagnostics:
```bash
ragops config doctor
```

### Phase 0 Exit Criteria
- [ ] Tests pass.
- [ ] Local config is valid for chat-capable runs.
- [ ] Team can execute MVP commands without Docker.

## Phase 1: Golden Path Reliability (`init -> scan -> chat`)

### Task 1.1: Validate first-run flow
- [ ] In a clean project directory, run:
```bash
ragops init
ragops scan
ragops chat "How should I start learning this codebase?"
```
- [ ] Confirm scan and first answer complete in one pass.

### Task 1.2: Validate scan outputs and ingest
- [ ] Verify required manuals are generated:
  - `PROJECT_OVERVIEW.md`
  - `ARCHITECTURE_MAP.md`
  - `CODEBASE_MANUAL.md`
  - `API_MANUAL.md`
  - `ARCHITECTURE_DIAGRAM.md`
  - `OPERATIONS_RUNBOOK.md`
  - `UNKNOWNS_AND_GAPS.md`
  - `DATABASE_MANUAL.md`
  - `SCAN_INDEX.json`
- [ ] Verify chat can cite manual content right after scan.
- [ ] Confirm architecture diagram renders in Mermaid-capable viewers.

### Task 1.3: Improve error handling
- [ ] Ensure actionable errors for:
  - missing/invalid API key
  - provider mismatch
  - bad collection selection
  - scan/manual generation failures

### Phase 1 Exit Criteria
- [ ] First-run local workflow is reliable and repeatable.
- [ ] Required manual set is always present.
- [ ] Users can recover quickly from common setup failures.

## Phase 2: Chat Quality and Citation Guarantees

### Task 2.1: Contract verification
- [ ] Verify chat responses include:
  - `session_id`
  - `answer`
  - `citations` with source and line range
  - `mode`
  - `answer_style`
  - `turn_index`
- [ ] Verify follow-up turns preserve context in same session.

### Task 2.2: Quality guardrails
- [ ] Add/adjust tests to prevent raw code-dump behavior when explanatory mode is requested.
- [ ] Validate `mode` and `answer_style` handling for valid/invalid values.
- [ ] Confirm answerable broad prompts return at least one citation.

### Phase 2 Exit Criteria
- [ ] Session continuity is verified.
- [ ] Citation presence is stable on answerable prompts.
- [ ] Answer style remains project-focused and grounded.

## Phase 3: Feedback, Eval, and KPI Evidence

### Task 3.1: Eval dataset quality
- [ ] Expand project-focused eval cases:
  - architecture discovery
  - first files to read
  - run/test flow
  - API behavior
  - repo indexing behavior

### Task 3.2: Generate reports
- [ ] Run eval and publish:
  - `eval/eval-report.json`
  - `eval/eval-report.md`

### Task 3.3: Record MVP KPIs
- [ ] Update `docs/mvp-results.md` with:
  - `time_to_first_answer_seconds`
  - `scan_duration_seconds`
  - `chat_p50_latency_ms`
  - `chat_p95_latency_ms`
  - `citation_coverage_rate`
  - `eval_source_hit_rate`
  - `eval_answer_hit_rate`
  - `feedback_positive_rate`

### Phase 3 Exit Criteria
- [ ] Eval reports are reproducible.
- [ ] KPI snapshot is complete for at least one full run.

## Phase 4: Secondary Surfaces (Repo and Frontend)

### Task 4.1: Repo indexing validation
- [ ] Validate `ragops repo add` and `ragops repo sync` against a public repo.
- [ ] Confirm code/manual collection behavior and citations.
- [ ] Validate async `/v1/repos/onboard` status polling flow.

### Task 4.2: Frontend hardening (optional for MVP demo)
- [ ] Validate repo indexing + chat + feedback loop in browser flow.
- [ ] Improve error/loading states where needed.

### Phase 4 Exit Criteria
- [ ] Secondary surfaces are demo-safe.
- [ ] CLI remains the primary and strongest path.

## Phase 5: Final Demo and Doc Consistency

### Task 5.1: Demo script finalization (< 10 min)
- [ ] Demo order:
  1. run `ragops init`
  2. run `ragops scan`
  3. ask first question
  4. ask follow-up in same session
  5. submit feedback
  6. show citation with concrete source and line range

### Task 5.2: Documentation alignment
- [ ] Confirm consistency across:
  - `README.md`
  - `docs/mvp.md`
  - `docs/scan-output-spec.md`
  - `docs/roadmap.md`
  - `docs/user-guide.md`
  - `docs/mvp-results.md`

### Task 5.3: Final quality gate
- [ ] Run:
```bash
.venv/bin/python -m pytest services/ -q
```
- [ ] Re-run eval and update KPI snapshot.

### Phase 5 Exit Criteria
- [ ] Functional acceptance criteria in `docs/mvp.md` are satisfied.
- [ ] Demo acceptance criteria in `docs/mvp.md` are satisfied.
- [ ] Evidence artifacts are ready to share.

## Required Artifacts Before MVP Complete

- [ ] `eval/eval-report.json`
- [ ] `eval/eval-report.md`
- [ ] `docs/mvp-results.md`
- [ ] Updated docs listed in Phase 5.2

## Suggested Commit Sequence

1. `feat(cli): harden init-scan-chat golden path reliability`
2. `feat(scan): improve manual generation quality and scan diagnostics`
3. `feat(chat): tighten citation guarantees and session continuity`
4. `test(eval): expand codebase-understanding dataset and publish reports`
5. `docs(mvp): align roadmap, execution plan, and KPI evidence`
