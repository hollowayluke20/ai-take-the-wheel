# 13 — Build: verify stage + end-to-end gauntlet

Status: resolved

## Answer

Harness fully per 04 (capture, 4-bucket diff, verify.json, 7-step gate,
adequacy, benchmark, heartbeat/stall); wired end-to-end (decompose → find →
evidence → rank with decline → clone → baseline → apply → after → verify →
report). Live proof: 26 win PASS, 34/35 keep-yours PASS, 32 clean decline
recorded (judgment for Luke). 3 retries used (wiring, decline+install,
plugins). Accepted with KNOWN LIMITATION (Luke, 2026-09-09): key 30 ranks
correctly and baselines parse, but can't prove the win — sandbox doesn't
install test dependency-groups (e.g. freezegun). Follow-up: test-group dep
installation, a lane task. Critic verdicts: 1 fail (wiring, fixed), 1 fail
(decline/baseline/command, fixed), final state accepted per exhausted-retry
rule, not re-critic'd.
Type: task
Blocked by: 12

## Question

Implement the harness per ticket 04's design, then prove the whole pipeline
on the suite: the prototype's first real night.

## Spec

Implement ticket 04's `## Proposal`: harness-owned baseline capture (exact
pytest invocation + fingerprint), nodeid-keyed 4-bucket diff, `verify.json`
per run under `database/<run-id>/verify/`, ordered 7-step gate, authored-test
adequacy enforcement, benchmark sub-protocol (clearly-faster-here),
JSONL heartbeat + 20-min stall default. Then end-to-end: run
`attw analyze` over the suite keys (network allowed, PAT from `.env`,
sandbox temp) and record per-run results; keep-yours runs must decline.
Tests: fixture baseline/after dicts (all 4 buckets, exit codes incl. 5),
adequacy-rule unit tests, heartbeat/stall unit tests; no live network in
unit tests (the suite runs are the live proof, recorded not asserted).

## Done-criteria

`verify.py` fully implemented; unit tests; gate green; suite runs recorded
with per-run verdicts; blind critic + verifier per LOOP.md. This ticket
closes the build wave.
