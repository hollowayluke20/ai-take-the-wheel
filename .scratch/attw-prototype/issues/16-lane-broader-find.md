# 16 — Lane: broader find queries

Status: resolved

## Answer

Multi-query real (≤3/component, merge/dedupe repo-keyed, recorded,
politeness + quota preserved, no fan-out); live smoke surfaced mainstream
libs. Critic PASS; verifier verified. Merged via PR (trickle).
Type: task
Lane: 3 of 4. File claim: `src/attw/find.py`, `tests/test_find.py`.

## Question

Fix demo lesson 3: one GitHub query, stars-ordered, misses the mainstream
answers. Broaden candidate discovery without breaking the one-query-per-
component cost rule's spirit.

## Spec

Within ticket 08's architecture (deterministic mapping, politeness, quota
paths, no per-candidate search fan-out): add up to 3 queries per component
(synonym/expansion rules + a topic-based query), merge + dedupe by repo,
keep stars-ordering for relevance. Record all queries issued per component
in the run record. Tests mocked (multi-query merge, dedupe, quota-hit
mid-sequence, empty-all-queries → no-candidates). Live smoke: ONE component,
record queries → candidates. Quality bar: the AI-humaniser component must
surface at least one candidate stronger than a 0-star repo (any mainstream
paraphrase/style library counts — record what it finds).

## Done-criteria

Multi-query implemented + unit tests; live smoke recorded; gate green;
checker happy before integrator. Then merge via PR, trickle.
