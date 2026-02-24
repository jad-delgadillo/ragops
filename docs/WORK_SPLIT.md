# RAGOps Parallel Build Split (Codex Desktop)

This doc is the working contract for running multiple Codex sessions in parallel without stepping on each other.

## Team Topology

Use 4 sessions total:

1. Coordinator (you)
2. Builder A (Model + index contracts)
3. Builder B (Container/runtime)
4. Builder C (Observability + CI PR summary)

## Branch Strategy

Create these branches:

- `codex/integration` (coordinator-owned)
- `codex/model-core` (Builder A)
- `codex/runtime` (Builder B)
- `codex/ops-ci` (Builder C)

Merge flow:

1. Builders open PRs into `codex/integration` (not `main`).
2. Coordinator validates integration and fixes conflicts.
3. Coordinator opens final PR from `codex/integration` to `main`.

## File Ownership (Conflict Avoidance)

Coordinator:

- `docs/WORK_SPLIT.md`
- cross-cutting conflict resolution only

Builder A (`codex/model-core`):

- `services/core/providers.py`
- `services/core/config.py`
- `services/core/storage.py` (index metadata/version keys)
- `services/core/tests/test_providers.py`
- `services/core/tests/test_storage.py`
- provider-specific files in `services/core/*_provider.py` as needed

Builder B (`codex/runtime`):

- `Dockerfile`
- `docker-compose.yml`
- `Makefile` (only container targets)
- `README.md` (container run examples only)
- `docs/local-testing.md` (container workflow only)

Builder C (`codex/ops-ci`):

- `services/core/logging.py`
- `services/ingest/app/pipeline.py` (latency instrumentation only)
- `services/api/app/retriever.py` (confidence/reporting fields if needed)
- `.github/workflows/ci.yml` (extend) or add `.github/workflows/pr-summary.yml`
- `docs/runbooks.md` (ops + CI behavior)

Hard rule: if a change needs a file owned by another builder, open an issue note in PR and let coordinator cherry-pick or handle in `codex/integration`.

## Shared Contracts (Freeze First)

Before feature work, align on these exact contracts:

1. `index_metadata` keys:
- `repo_commit`
- `embedding_provider`
- `embedding_model`
- `chunk_size`
- `chunk_overlap`
- `index_version`
- `created_at`

2. Log schema minimum:
- `event`
- `collection`
- `latency_ms`
- `provider`
- `model`
- `request_id`
- `confidence` (nullable; heuristic)

3. CI PR summary behavior:
- Incremental scan only (`ragops scan --incremental --base-ref <target> --json`)
- If confidence too low, post fallback comment (no confident summary)
- Never comment full files; summarize changed areas only

## Work Waves

Wave 1 (foundation):

1. Builder A: provider abstraction cleanup + index metadata persistence.
2. Builder B: container UX (`docker run ... scan`, `docker run ... chat`) and docs.
3. Builder C: JSON logging + latency metrics + first PR-summary workflow draft.

Wave 2 (hardening):

1. Builder A: cache keys + index versioning behavior.
2. Builder B: build caching optimization and slimmer image.
3. Builder C: CI guardrails, retries, and confidence fallback tuning.

## PR Size and Cadence

- Target <= 300 LOC per PR.
- Ship at least one PR per builder every 3-4 hours of work.
- Rebase each branch on `codex/integration` before opening PR.

## Definition of Done (Per Builder PR)

1. Focused scope (single capability).
2. Tests added or updated.
3. Docs updated for behavior changes.
4. Command examples verified locally.
5. Risk note included in PR description.

## Coordinator Checklist

1. Merge order: A -> C -> B (usually least conflict this way).
2. Run:
- `ruff check services/`
- `pytest services/ -v --tb=short`
3. Smoke test:
- `ragops scan --json`
- `ragops chat "What changed?"` (or equivalent question)
4. Verify CI workflow on a test PR branch before merging to `main`.

## Kickoff Prompts (Paste into 3 Codex Builder Sessions)

### Prompt for Coordinator (Integration Owner)

You are the Coordinator on branch `codex/integration` for `/Users/jorgedelgadillo/Developer/ragops`.

Role:
1. Own integration quality and merge order across builder branches:
- `codex/model-core` (Builder A)
- `codex/runtime` (Builder B)
- `codex/ops-ci` (Builder C)
2. Do not implement major feature work first; prioritize review, merge, conflict resolution, and end-to-end validation.

Operating rules:
1. Enforce file ownership defined in `docs/WORK_SPLIT.md`.
2. Merge order default: A -> C -> B.
3. Require each builder PR to include tests run + risks.
4. If cross-branch conflict appears, resolve in `codex/integration` and document the resolution in PR notes.

Validation checklist after each merge:
1. `ruff check services/`
2. `pytest services/ -v --tb=short`
3. Smoke test:
- `ragops scan --json`
- `ragops chat "What changed?"`
4. Confirm CI workflows are still green and PR-summary workflow is failure-safe.

Final deliverable:
1. Clean integration branch ready for `main`.
2. Final PR summary including:
- merged PR list
- test evidence
- known residual risks
3. If any scope is deferred, list it explicitly as follow-up tasks.

### Prompt for Builder A (Model + Index Metadata)

You are Builder A on branch `codex/model-core` for `/Users/jorgedelgadillo/Developer/ragops`.

Goal:
1. Strengthen provider-agnostic model selection for embeddings/LLM in `services/core/providers.py` and related config.
2. Implement index metadata/version persistence in storage layer (`services/core/storage.py`) with keys: `repo_commit`, `embedding_provider`, `embedding_model`, `chunk_size`, `chunk_overlap`, `index_version`, `created_at`.
3. Add tests for provider selection and metadata persistence in `services/core/tests/`.

Constraints:
1. Do not edit Docker/workflow files.
2. Keep PR <= 300 LOC if possible; split into multiple PRs if needed.
3. Keep backward compatibility with current CLI commands.

Validation:
1. Run `ruff check services/`.
2. Run targeted tests first, then `pytest services/core/tests -v --tb=short`.

Deliverable:
1. Commit(s) on `codex/model-core`.
2. A short PR summary with: what changed, tests run, open risks.

### Prompt for Builder B (Container Runtime)

You are Builder B on branch `codex/runtime` for `/Users/jorgedelgadillo/Developer/ragops`.

Goal:
1. Ensure container-first usage is smooth for:
- `docker run ragops scan .`
- `docker run ragops chat`
2. Improve `Dockerfile` and `docker-compose.yml` for reproducible local runs.
3. Add/adjust `Makefile` targets and docs in `README.md` + `docs/local-testing.md` for container workflows.

Constraints:
1. Do not modify provider logic or CI workflows.
2. Keep runtime defaults safe for local development.
3. Avoid breaking existing non-container CLI flow.

Validation:
1. Build image locally.
2. Run smoke commands for `scan` and `chat`.
3. Run `pytest services/cli/tests -v --tb=short` if your changes affect CLI runtime behavior.

Deliverable:
1. Commit(s) on `codex/runtime`.
2. PR summary with exact commands used to validate container flow.

### Prompt for Builder C (Observability + CI PR Summary)

You are Builder C on branch `codex/ops-ci` for `/Users/jorgedelgadillo/Developer/ragops`.

Goal:
1. Extend structured logging and timing metrics:
- JSON logs include event/provider/model/request_id/latency.
- Track embedding latency in ingest/retrieval paths.
2. Implement PR-summary CI workflow:
- Trigger on pull requests.
- Run incremental scan against base ref.
- Generate grounded summary and post PR comment.
- Add confidence guardrail with fallback comment when confidence is low.

Suggested files:
1. `services/core/logging.py`
2. `services/ingest/app/pipeline.py`
3. `services/api/app/retriever.py` (if confidence surfaced there)
4. `.github/workflows/pr-summary.yml` (or extend `ci.yml`)
5. `docs/runbooks.md`

Constraints:
1. Confidence must be labeled heuristic (not truth).
2. Keep CI failure-safe: no hard failure if summary generation fails.
3. Do not touch container files.

Validation:
1. Run `ruff check services/`.
2. Run relevant tests.
3. Validate workflow syntax and include expected env/secret names in docs.

Deliverable:
1. Commit(s) on `codex/ops-ci`.
2. PR summary with fallback behavior and failure modes documented.
