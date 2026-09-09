# 07 — Build: understand stage

Status: resolved

## Answer

`decompose()` real for both input kinds (idea splitter → addition comps;
temp shallow-clone + 6-pattern scan → substitution comps with call_sites);
exact failure records, downstream-only; no API calls; `analyze --dry-run` +
`understand` subcommand smoke-tested. Critic PASS (keep-yours precision
deferred to ranker, per ticket text); verifier `verified` (40 passed, ruff
clean). Note: stray `$schema` line in opencode.json is environment tooling,
not this piece — left alone, uncommitted.
Type: task

## Question

Implement the `understand` stage for real: `decompose()` turning a repo URL
or idea-text into the `Component` list the pipeline runs on.

## Spec

Follow ticket 05's `## Decision` (module layout, `Component`
`{name,description,kind,call_sites,confidence}`, doubt→addition, failure
schema from `failures.py`) and the map's bar: the component list must match
the recorded human profile for the input. `analyze --dry-run` and the
`understand` subcommand must work end-to-end on the suite keys
(`testdata/known_answers/26-35`, `input` field). No network beyond a
shallow clone to temp for repo inputs (no API calls in this stage); idea-text
follows the 05-decided decomposition shape. Stage failures emit the exact
failure records (downstream-only).

## Done-criteria

`understand.py` fully implemented (no NotImplementedError left in this
stage); unit tests with fixture inputs (a tiny local fixture repo + idea
strings, no network in tests); `python -m pytest -q` + `python -m ruff
check .` green; blind critic + verifier per LOOP.md.
