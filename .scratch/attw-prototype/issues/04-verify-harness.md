# 04 — Verify harness: proving improvement before/after

Status: resolved

## Answer

Harness design decided (`## Proposal`, lines 92–143): harness-owned baseline
capture (exact pytest invocation + fingerprint fields), nodeid-keyed 4-bucket
diff with `verify.json` schema, ordered 7-step critic gate, adequacy rules,
benchmark sub-protocol (clearly-faster-here), JSONL heartbeat + 20-min stall
default, night budget table. Critic: PASS (3 nits deferred to architecture:
regress-label reconcile, coverage tool/threshold, copy-vs-pointer).
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

## Rulings (Luke, 2026-09-09, pre-build review)

- Verify keys EXTEND the `testdata/known_answers/` schema. One bar.
- `pytest-json-report` allowed as a sandbox dependency.
- Benchmark bar = clearly-faster-here (same-machine, non-overlapping
  distributions), no fixed percentage.
- Single 20-min stall-silence default; calibrate after first real night.

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

## Proposal (harness design)

DECIDED (2026-09-09; implements Rulings + Research notes above; matches `testdata/known_answers/SCHEMA.md` `verify` keys). No implementation.

### 1. Baseline capture protocol (harness OWNS; implement calls it)
- Owner: harness function `capture/run_suite()` OWNS invocation. Implement/integrate code NEVER runs its own pytest for verdict purposes; it calls the harness pre- and post-change and receives artifact paths.
- Exact invocation (both runs, inside sandbox copy only): `pytest --json-report --json-report-file=<run_dir>/verify/baseline.json -p no:cacheprovider` pre-change; identical with `after.json` post-change. Extra target args recorded verbatim in `verify.test_command` (e.g. `"pytest -q"`); the `--json-report` flags are always appended by the harness.
- Artifact format: `pytest-json-report` JSON (nodeid → outcome + exit code). No `-v` parsing fallback (Ruling: tool allowed as sandbox dep).
- Env fingerprint fields (stored in `verify.json:fingerprint`): `python_version`, `pytest_version`, `pip_freeze_sha` (+ full `pip_freeze.txt` alongside), `platform`, `target_git_sha`, `authored_tests` (list of paths), `test_command`.
- Artifact location per run: `<run_dir>/verify/{baseline.json, after.json, verify.json, heartbeat.jsonl, pip_freeze.txt}` under the sandbox run dir, then copied to `database/<run-id>/verify/` alongside the per-run report JSON. Original target never touched.
- Exit-code semantics: `0` = all pass; `1` = tests failed (valid verdict input); `2/3/4` = interrupted/usage/collection error → verdict `fail`, harness records stderr; `5` = no tests collected → **harness failure** (never a pass, never keep-yours; run is `fail`, retried or flagged).

### 2. Comparison algorithm + `verify.json` schema
- Diff key: pytest nodeid. Normalise by stripping sandbox-run prefix so baseline/after nodeids join.
- 4 buckets: `fixed` (fail→pass, incl. error→pass); `regressed` (pass→fail, pass→error/skip counts as regressed — gate-killer); `new` (nodeid only in after; must be passing to count as gain); `removed` (nodeid only in baseline).
- `verify.json` per run: `{"fingerprint": {...}, "baseline": {"path": str, "exit_code": int, "summary": {"passed": int, "failed": int, "total": int}}, "after": {...same}, "diff": {"fixed": [nodeid], "regressed": [nodeid], "new": [nodeid], "removed": [{"nodeid": str, "reason": str}]}, "verdict": "better" | "keep-yours" | "fail" | "stalled"}`. `verify` answer-key object (`test_command`, `baseline.captured/tool`, `authored_tests`, `zero_regressions: true`) is derived from this file.
- Removed-must-be-explained: every `removed` entry carries a one-line `reason` (e.g. `deleted-by-wheel`, `renamed-to:<nodeid>`), mirrored in answer-key `notes`/report. Any unexplained `removed` → critic rejects (treated as hidden regression).

### 3. "Better" gate (ordered checklist, critic enforces top-to-bottom, first failure decides)
1. `verify.json` + both raw JSON reports + heartbeat present and parseable.
2. **Zero regressed, absolute**: `diff.regressed == []`. Any entry → verdict `fail`, no exceptions.
3. **Improvement is exactly one of**: (a) `len(fixed) >= 1` (red→green); (b) `>= 1 new` node passing from `authored_tests` (new capability); (c) benchmark gain per §4 (measured gain). Else verdict = `keep-yours` (also required when `better_spec.mode == keep_yours`: `fixed/new` empty, benchmark null).
4. **Authored-test adequacy** (mechanically checkable, all must hold when `authored_tests` non-empty): path matches `test_attw_*.py`, separate from target suite; imports target/wheel (never reimplements logic); ≥1 `assert` with non-constant operands (AST-ban `assert True/literal`); no `try/except: pass`, no unconditional `skip/xfail`; deterministic (no network, wall-clock, or unseeded randomness); proven value — red→green shown by pre-run fail + post-run pass, or coverage of wheel-touched new lines.
5. Exit-code semantics respected (§1); exit 5 never passes.
6. Sandbox-only (paths under temp run dir) + every gain claim cites a `verify.json` cell/nodeid.
7. Heartbeat attached; silent runs marked `stalled`, never passed.

### 4. Benchmark sub-protocol
- When: ONLY when the wheel's claim is perf/size (`better_spec.mode == measured_gain`). Default: no benchmark. Never a single wall-clock run as a claim.
- Tool/settings: `pytest-benchmark`, `min_rounds >= 5`, warmup on (`warmup=true` / `--benchmark-warmup=on`), same sandbox machine back-to-back, pinned deps between runs.
- Claim rule (Ruling): same-machine before/after distributions must be **non-overlapping** (`max(after) < min(before)` for faster; mirrored for size) — "clearly-faster-here". No fixed % threshold. Report carries both distributions + rounds/warmup settings; overlapping → no claim → `keep-yours` unless another §3 leg holds.

### 5. Stall-detection implementation
- Mechanism: harness appends JSONL heartbeat (`heartbeat.jsonl`); independent watchdog polls file mtime. Silence = no new line for **20 min** (single global default) → record run `stalled` in RUNLOG, **abort that run only**, loop moves on.
- Exact events (one line each `{"ts": iso, "stage": str, "event": str, "detail": str}`): `run_started`, `understand_emitted`, `find_candidate`, `evidence_cell`, `rank_done`, `report_done`, `implement_file`, `test_node`, `benchmark_round`, `stage_finished`, `run_finished`. Per-stage progress = at least one of its events (`understand`: `understand_emitted`; `find`: each `find_candidate`; `evidence`: each `evidence_cell`; `rank/report`: `*_done`; `implement`: each `implement_file`; `verify`: each `test_node`/`benchmark_round`). Stages emit `stage_finished` on completion.
- Calibration (first real night): log per-stage durations for every run; compute p95 per stage; set per-stage thresholds = `p95 × 2`, keeping the 20-min global ceiling (per-stage never exceeds 20 min until Luke approves). Architecture ticket wires thresholds as config.

### 6. Night budget (10 sequential runs, ~8h window) + pytest-timeout guidance
| Stage | Per-run (research) | 10-run total | Note |
|---|---|---|---|
| understand | <1 min | <10 min | negligible |
| find | 1–3 min | 10–30 min | — |
| evidence | 5–15 min | 50–150 min | dominant; weekly cache trims repeats |
| rank/report | 1–2 min | 10–20 min | — |
| implement+verify | 5–20 min | 50–200 min | dominant |
| **Total** | **≈12–35 min/run** | **≈2.5–6h** | remainder = retry/stalled headroom |
- Guidance: set `pytest-timeout` (or harness alarm) to 10 min per test session so a hung suite trips before the 20-min watchdog; benchmark legs get 15 min cap; timeouts recorded as `fail` (with event log), never silent.

### 7. Residual open questions (for architecture, max 3)
1. Where does per-stage duration logging live (heartbeat event payload vs separate timing log) so calibration is a one-line query?
2. Should `database/<run-id>/verify/` hold full copies or pointers to sandbox artifacts once sandbox temp is reaped?
3. Does the architecture ticket put the critic gate (§3) as a standalone `verify --check` CLI or a library function the loop imports?
