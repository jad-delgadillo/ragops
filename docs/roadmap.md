# Product Roadmap

## Roadmap Goal

Ship a reliable CLI onboarding copilot first, then improve scan intelligence and answer trustworthiness in phases.

## Phase 0: MVP (Now)

Core promise:
- `ragops init -> ragops scan -> ragops chat` works in any local project.

Deliverables:
- Stable local defaults and setup
- Deterministic manual pack generation
- Citation-grounded multi-turn chat
- Feedback and eval commands

Exit criteria:
- New user can reach first grounded answer in under 10 minutes.
- Citation coverage is consistently strong on onboarding prompts.

## Phase 1: Scan Fidelity

Goal:
- Make generated docs more complete, less generic, and easier to trust.

Planned features:
1. Better entrypoint detection per framework and language.
2. Improved symbol extraction beyond Python.
3. Improve evidence coverage and confidence scoring inside generated manuals.
4. Expand `SCAN_INDEX.json` with per-section evidence quality metrics.
5. Add incremental scan mode using git-aware changed-file ingestion.
6. Add ownership and hot-path change impact hints.

Exit criteria:
- Generated docs explain run/test/onboarding flow without manual edits for common repos.
- Reduced low-confidence sections per scan.

## Phase 2: Chat Trust and Guidance

Goal:
- Improve answer quality and user trust for onboarding questions.

Planned features:
1. Retrieval weighting that prefers manuals first, code second.
2. "Why this answer" explanation with evidence trace.
3. Confidence scores at answer and citation levels.
4. Guardrails against raw code dump responses when explanatory answers are requested.
5. Follow-up suggestions: next files, next commands, next questions.

Exit criteria:
- Higher eval source-hit and answer-hit rates on onboarding datasets.
- Measurable reduction in ungrounded or low-confidence answers.

## Phase 3: Team Workflow

Goal:
- Move from single-user local value to repeatable team onboarding workflows.

Planned features:
1. Shared scan profiles and org-level conventions.
2. Repo portfolio mode (chat across multiple projects).
3. Persistent onboarding sessions and handoff summaries.
4. Better change-awareness (what changed since last scan).

Exit criteria:
- Teams can reuse scan outputs and onboarding playbooks across repos with low setup overhead.

## Prioritization Rules

Use these rules to decide what gets built next:

1. Improve time-to-first-trustworthy-answer before adding platform breadth.
2. Prefer deterministic, testable scan improvements over speculative generation.
3. Keep UX anchored to the three-command workflow.
4. Require measurable quality impact for each added feature.
