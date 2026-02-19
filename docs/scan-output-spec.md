# Scan Output Specification

## Purpose

Define exactly what `ragops scan` should produce so onboarding quality is consistent across projects.

## Current `scan` Behavior

Command:

```bash
ragops scan
```

Current flow:
1. Ingest project files into the active collection.
2. Generate manuals under `./.ragops/manuals` (default).
3. Ingest generated manuals into the same collection.

## Required Manual Outputs

Every successful scan must generate these files:

1. `CODEBASE_MANUAL.md`
Purpose: project map, key modules, onboarding reading order.

2. `PROJECT_OVERVIEW.md`
Purpose: quick orientation, run flow, and key entrypoints.

3. `ARCHITECTURE_MAP.md`
Purpose: components, data flow, boundaries, and dependencies.

4. `API_MANUAL.md`
Purpose: API and CLI contract summary with concrete examples and constraints.

5. `ARCHITECTURE_DIAGRAM.md`
Purpose: architecture communication using generated Mermaid sequence diagrams.

6. `OPERATIONS_RUNBOOK.md`
Purpose: install, test, debug, and common failure handling.

7. `UNKNOWNS_AND_GAPS.md`
Purpose: what deterministic scan could not infer with high confidence.

8. `DATABASE_MANUAL.md`
Purpose: schema and index reference when DB introspection is enabled; explicit "skipped" state otherwise.

9. `SCAN_INDEX.json`
Purpose: machine-readable metadata for ranking, citations, and diagnostics.

## Detail and Quality Rules

All manuals should follow these rules:

1. Start with short, high-signal summaries before long details.
2. Prefer deterministic extraction from source files over speculative prose.
3. Include source pointers whenever claims depend on code facts.
4. Separate facts from inference. If inference is needed, label confidence as `high`, `medium`, or `low`.
5. Keep docs onboarding-focused: architecture, entrypoints, run/test flow, and operational gotchas.

## What to Add Next

For stronger onboarding outcomes, future scan iterations should enrich `SCAN_INDEX.json` with:

1. Ownership confidence drift signals.
2. Changed-file impact summaries.
3. Per-manual evidence coverage scores.
4. Context relevance hints for chat.

`SCAN_INDEX.json` currently includes:
- output file list
- generation timestamps
- detected stack and entrypoints
- confidence markers
- source references used per section

## Suggested Section Template for Each Manual

1. `Summary` (5-10 bullets max)
2. `How to Navigate`
3. `Key Facts with Sources`
4. `Operational Notes`
5. `Open Questions / Low-Confidence Areas`

## Verification Checklist

After each scan run, verify:

1. All required manual files exist.
2. Chat can cite manual content immediately.
3. Architecture diagram renders in markdown viewers with Mermaid support.
4. No section silently invents details without either source pointers or confidence labels.
