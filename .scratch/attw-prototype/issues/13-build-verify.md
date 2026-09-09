# 13 — Build: verify stage + end-to-end gauntlet

Status: open
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
