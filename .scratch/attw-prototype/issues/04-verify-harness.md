# 04 — Verify harness: proving improvement before/after

Status: open
Type: research

## Question

Design the before/after protocol that lets attw claim "better" with evidence.
Standing bar from the map: zero regressions gate; improvement = red→green,
new capability with new passing tests, or measured gain — all recorded.

## Lines of inquiry

- Baseline capture: run target suite pre-change, record per-test results,
  environment fingerprint (python version, dep pins).
- Post-change comparison: what diff format proves no-regressions + gain.
- Benchmark hooks: when timing/size claims are appropriate, how to measure
  without noise (repeat runs, warmup, what not to claim).
- Attw-authored tests (pure-addition runs): adequacy rules the critic can
  check mechanically — non-tautological, behaviour-covering, failing
  pre-change where that makes sense.
- Stall-detection mechanics: progress-output heartbeat, what counts as
  progress per stage, the 20-min default and how the first real night
  should recalibrate it.
- Time expectations per stage so the loop can plan a 10-run night.

## Done-criteria

Findings captured below; a harness design + the exact "better" gate the
critic will enforce, ready to drive the architecture ticket. No implementation.

## Research notes

Findings (research subagent, 2026-09-09 — for resolution, not resolved):

**Current state**: `src/attw/` is stubs; `known_answers/` schema has no verify
fields (no recorded test command, no expected red→green). Harness has no
ground truth yet — ticket 01/06 must add it.

**Baseline**: run suite pre-change in sandbox:
`pytest --json-report --json-report-file=baseline.json -p no:cacheprovider`;
record per-test nodeid→outcome + exit code (5 = no tests = harness failure).
Adopt `pytest-json-report` artifact format. Fingerprint alongside: python +
pytest versions, pip freeze, platform, target git SHA, attw-authored test list.

**Comparison**: `after.json` same format; nodeid-keyed diff in 4 buckets:
`fixed` (fail→pass), `regressed` (pass→fail — gate-killer), `new`,
`removed` (must be explained, never silently OK). One `verify.json` per run:
{fingerprint, baseline, after, diff, verdict}, referenced from the report.

**Benchmarks**: `pytest-benchmark`, min_rounds≥5, warmup on; claim gain ONLY
from same-machine before/after compare with non-overlapping distributions.
Single wall-clock runs are never a claim. Default: no benchmark unless the
wheel's claim is perf/size.

**Authored-test adequacy (mechanically checkable)**: live in `test_attw_*.py`,
separate from target suite; import target/wheel, never reimplement logic;
≥1 assertion with non-constant operands (AST-ban `assert True`); no
`try/except: pass`, no unconditional skip/xfail; prove value (red→green or
coverage of new lines); deterministic (no network/time randomness).

**Stall-detection**: append-only JSONL heartbeat + watchdog on mtime; progress
per stage defined (profile emitted / per-candidate / per-cell / per-file /
per-test-node). 20 min silence → record `stalled`, abort that run only.
First real night logs per-stage durations → recalibrate to per-stage
thresholds (p95×2), keep 20 min global ceiling.

**Night budget (~8h)**: understand <1 min; find 1-3 min; evidence 5-15 min
(dominant); rank/report 1-2 min; implement+verify 5-20 min (dominant).
Per-run ≈ 12-35 min → 10 sequential runs ≈ 2.5-6h, fits with retry headroom.

**Proposed critic gate**: verify.json present; zero regressed; removed
explained; improvement is exactly one of (≥1 fixed / ≥1 new passing /
non-overlapping benchmark gain) else verdict = keep-yours; exit-code semantics
respected; authored tests pass adequacy + confirmed red→green by re-run;
sandbox-only with cited claims; heartbeat attached, silent runs marked
stalled never passed.

**Open**: (1) verify fields in known_answers schema or separate file?
(2) pytest-json-report as sandbox dep, or parse `-v` to avoid installs?
(3) benchmark bar fixed (≥5%) or wheel-relative? (4) per-stage stall
thresholds now, or single 20-min default until calibration data?
