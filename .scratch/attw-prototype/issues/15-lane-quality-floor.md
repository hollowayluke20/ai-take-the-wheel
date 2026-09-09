# 15 — Lane: minimum-quality floor for additions

Status: resolved

## Answer

Floor real (score≥2.0 AND ≥2 signals else decline-weak; keep path bypasses);
demo case fixture declines; pinned test expectations updated by
behavior-owner rule. Critic PASS; verifier verified. Merged via PR
(trickle).
Type: task
Lane: 2 of 4. File claim: `src/attw/rank.py`, `tests/test_rank.py`.

## Question

Fix demo lesson 1: a single zero-signal candidate must not win by default.
Give the ranker a floor below which it declines, even with no incumbent.

## Spec

Decide and implement a minimum-quality rule for additions (no incumbent):
e.g. require minimum evidence strength (stars + downloads + recency composite
above a threshold) or ≥2 independent positive signals, else verdict
`decline-weak` (distinct from keep-yours: nothing to keep, nothing good
enough to add). The AI-humaniser demo (0 stars, no license, not on PyPI)
must decline under the new rule — encode that case as a fixture. Thresholds
as constants with a comment citing this ticket; Luke tunes later. Keep-yours
path untouched.

## Done-criteria

Rule implemented + unit tests (floor triggers, near-floor passes, demo case
fixture, keep path unchanged); gate green; checker happy before integrator.
Then merge via PR, trickle.
