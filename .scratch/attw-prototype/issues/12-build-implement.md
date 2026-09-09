# 12 — Build: implement stage

Status: resolved

## Answer

Applier real across the matrix (dep-swap/vendor/adapter, manifest order,
pins, outright deletion with diff+paths+snapshot, delegation-only adapters
no LOC cap, in-sandbox ruff tidy, advisory typecheck). Sandbox airtight
(mkdtemp, prefix asserts, read-only original, mocked venv/installs, no
push). Exact failure strings with revert; 2 fallbacks; GPL dep-swap-or-skip.
1 critic reject (vendor planned-not-applied) → fixed with applied-tree
tests → re-critic PASS; verifier `verified` (126 passed, live sandbox trial
original untouched).
Type: task
Blocked by: 11

## Question

Implement the applier: winner goes into a sandbox copy per ticket 03's
matrix — dep-swap, vendor, or adapter — with revert on regression.

## Spec

Implement ticket 03's `## Proposal` exactly: manifest order
pyproject → setup.cfg → setup.py-parse-only → requirements with
`>=low,<high` pins; deletion outright in sandbox with manifest-diff +
deleted-paths + pre-change snapshot recorded; `_attw_<wheel>_adapter.py`
delegation-only, no LOC cap; tidy = `ruff check` + `ruff format` clean on
touched files (run them in-sandbox), typecheck advisory-only recorded;
sandbox = mkdtemp attw-, prefix-asserted writes, original read-only, 1
venv/run, installs-only network, never push/exfiltrate; 2 next-ranked
fallbacks then `implement: failed-install`; one adapter attempt then
`implement: api-mismatch` + revert; regressions → revert + `implement:
regression`; GPL-family = dep-swap-or-skip. Calls the verify harness's
baseline capture (ticket 04 boundary: implement calls, harness owns).
Tests: fixture sandbox repos (local, no network — mock installs) covering
dep-swap, delete, adapter, revert, and each failure string.

## Done-criteria

`implement.py` fully implemented; unit tests over fixture sandboxes; gate
green; blind critic + verifier per LOOP.md.
