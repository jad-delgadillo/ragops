# RAG Ops MVP Execution Plan (LLM-Ready)

## Objective
Ship the MVP defined in `docs/mvp.md`: a GitHub repo onboarding copilot with citation-grounded chat, session continuity, feedback capture, async onboarding jobs, and measurable quality metrics.

## Scope Lock
In scope:
- `repo add` / `/v1/repos/onboard` onboarding flow (code + optional manuals).
- Chat with `session_id`, `mode`, `answer_style`, citations.
- Feedback capture (`positive` / `negative`).
- Evaluation harness and KPI tracking in `docs/mvp-results.md`.
- Local-first demo flow (CLI + optional frontend).

Out of scope for MVP:
- `s3_prefix` ingestion implementation in `/v1/ingest` (currently `501`).
- Bedrock production implementation (current classes are stubs).
- Billing, org-level multi-tenant controls, full observability stack.

## Current Baseline (as of 2026-02-19)
- Unit tests: `77 passed` (`.venv/bin/python -m pytest services/ -q`).
- Eval command requires reachable DB + indexed collection; current environment fails DB resolution.

## Recommended Public Test Repo
Use this repo as the default MVP validation target:
- `https://github.com/openclaw/openclaw`
- repo key / base collection: `openclaw-openclaw`
- expected collections:
  - `openclaw-openclaw_code`
  - `openclaw-openclaw_manuals`

If this repo is temporarily unavailable, switch to another public repo but keep the same collection naming pattern and document the replacement in `docs/mvp-results.md`.

## Execution Rules for the LLM
1. Execute phases in order. Do not skip a phase gate.
2. Before editing code, run the preflight checks in Phase 0.
3. For each task:
   - Make only the minimum required file edits.
   - Run targeted tests first, then broader tests.
   - Update this file checklist status.
4. If a gate fails, stop and fix before moving forward.
5. Keep all MVP evidence artifacts in repo (`eval/` and `docs/`), not external notes.

## Phase 0: Environment + Baseline Gates

### Task 0.1: Configure local runtime
- [ ] Copy env and set required values:
```bash
cp .env.example .env
```
- [ ] Set in `.env`:
  - `OPENAI_API_KEY=<key>`
  - `LLM_ENABLED=true`
  - `REPO_ONBOARDING_ENABLED=true`
  - `ENVIRONMENT=local`
- [ ] Start dependencies:
```bash
make dev
make install
```

### Task 0.2: Verify health and tests
- [ ] Run unit tests:
```bash
.venv/bin/python -m pytest services/ -q
```
- [ ] Health check (if API is running):
```bash
curl -sS http://localhost:8000/health
```

### Phase 0 Exit Criteria
- [ ] Tests pass.
- [ ] DB reachable from runtime.
- [ ] Required env toggles enabled for onboarding/chat.

## Phase 1: Repo Onboarding Reliability (CLI + API)

### Task 1.1: Validate onboarding golden paths
- [ ] CLI onboarding:
```bash
.venv/bin/python -m services.cli.main repo add https://github.com/openclaw/openclaw \
  --ref main \
  --generate-manuals
```
- [ ] API sync onboarding:
```bash
curl -sS -X POST http://localhost:8000/v1/repos/onboard \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/openclaw/openclaw","ref":"main","collection":"openclaw-openclaw","generate_manuals":true}'
```
- [ ] API async onboarding + polling:
```bash
curl -sS -X POST http://localhost:8000/v1/repos/onboard \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/openclaw/openclaw","collection":"openclaw-openclaw","async":true}'
```
Then poll:
```bash
curl -sS -X POST http://localhost:8000/v1/repos/onboard \
  -H "Content-Type: application/json" \
  -d '{"action":"status","job_id":"<job-id>"}'
```

### Task 1.2: Harden failure handling
- [ ] Ensure clear error responses for:
  - invalid `repo_url`
  - missing `job_id` on `action=status`
  - oversized archives/timeouts
  - auth-required non-local usage
- [ ] Add/adjust tests in:
  - `services/api/tests/test_chat.py`
  - `services/cli/tests/test_repositories.py`

### Phase 1 Exit Criteria
- [ ] Onboarding returns expected collection names (`<repo>_code`, `<repo>_manuals` when enabled).
- [ ] Async jobs reliably progress to terminal status.
- [ ] Error cases return actionable messages.

## Phase 2: Chat Quality + Citation Guarantees

### Task 2.1: Validate response contract
- [ ] Confirm `/v1/chat` returns:
  - `session_id`, `answer`, `citations`, `mode`, `answer_style`, `turn_index`.
- [ ] Confirm follow-up question in same session keeps continuity.
- [ ] Confirm onboarding-style prompts prioritize docs/manuals over raw dumps.

### Task 2.2: Add regression tests for answer quality
- [ ] Add/adjust tests in:
  - `services/api/tests/test_chat.py`
  - `services/api/tests/test_retriever.py`
- [ ] Cover:
  - invalid `mode` / `answer_style`
  - citation presence for answerable prompts
  - anti code-dump fallback behavior

### Phase 2 Exit Criteria
- [ ] Answerable onboarding questions return at least one citation.
- [ ] Session continuity verified across multiple turns.
- [ ] Chat responses remain concise and grounded.

## Phase 3: Feedback + Evaluation Evidence

### Task 3.1: Expand eval dataset for onboarding
- [ ] Grow `eval/cases.yaml` from smoke checks to onboarding-focused cases:
  - architecture discovery
  - first files to read
  - deploy/run flow
  - API/auth behavior
  - repo onboarding behavior
- [ ] Ensure each case includes:
  - `id`
  - `question`
  - `collection` (or default strategy)
  - `expected_source_contains`
  - `expected_answer_contains`

### Task 3.2: Generate repeatable reports
- [ ] Run eval:
```bash
.venv/bin/python -m services.cli.main eval \
  --dataset ./eval/cases.yaml \
  --collection openclaw-openclaw_code \
  --output-json ./eval/eval-report.json \
  --output-md ./eval/eval-report.md
```
- [ ] Record KPI snapshot in `docs/mvp-results.md`:
  - `onboarding_duration_seconds`
  - `chat_p50_latency_ms`
  - `chat_p95_latency_ms`
  - `citation_coverage_rate`
  - `eval_source_hit_rate`
  - `eval_answer_hit_rate`
  - `feedback_positive_rate`

### Phase 3 Exit Criteria
- [ ] Eval reports exist and are reproducible.
- [ ] `docs/mvp-results.md` contains at least one complete KPI run.

## Phase 4: Frontend MVP Flow Hardening

### Task 4.1: Validate UI onboarding loop
- [ ] Run:
```bash
make mock-api
make frontend
```
- [ ] Verify `frontend/app.js` flow:
  - async onboard starts and polls status
  - successful onboarding auto-selects code collection
  - chat works with preserved session
  - feedback submit path succeeds

### Task 4.2: Polish UX for demo reliability
- [ ] Improve status/error messaging for failed onboarding jobs.
- [ ] Ensure clear loading states for chat send + repo onboarding.
- [ ] Confirm mobile and desktop usability.

### Phase 4 Exit Criteria
- [ ] Browser demo works end-to-end without manual state surgery.
- [ ] Failures are visible and actionable in the UI.

## Phase 5: Demo, Docs, and Release Readiness

### Task 5.1: Finalize demo script (<=10 minutes)
- [ ] Script order:
  1. onboard repo
  2. ask first question
  3. ask follow-up in same `session_id`
  4. submit feedback
  5. show citation with concrete file + line range

### Task 5.2: Documentation alignment
- [ ] Ensure these docs are consistent and current:
  - `README.md`
  - `docs/mvp.md`
  - `docs/runbooks.md`
  - `docs/user-guide.md`
  - `docs/api-contract.md`
  - `docs/frontend-chat-manual.md`

### Task 5.3: Final quality gate
- [ ] Run:
```bash
.venv/bin/python -m pytest services/ -q
```
- [ ] Re-run eval and confirm KPI snapshot updated.

### Phase 5 Exit Criteria
- [ ] Functional acceptance criteria in `docs/mvp.md` are all satisfied.
- [ ] Demo acceptance criteria in `docs/mvp.md` are satisfied.
- [ ] Evidence artifacts committed.

## Required Artifacts Before Declaring MVP Complete
- [ ] `eval/eval-report.json`
- [ ] `eval/eval-report.md`
- [ ] `docs/mvp-results.md`
- [ ] Updated docs listed in Phase 5.2 (if behavior changed)

## Suggested Commit Sequence
1. `feat(onboarding): harden repo onboarding sync+async flows`
2. `feat(chat): tighten onboarding answer quality and citation guarantees`
3. `test(eval): expand onboarding evaluation dataset and reports`
4. `feat(frontend): improve onboarding status and chat reliability UX`
5. `docs(mvp): publish KPI evidence and final runbook updates`
