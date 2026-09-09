# 05 — Pipeline architecture

Status: resolved

## Answer

Architecture decided with per-decision citations to 02/03/04; code skeleton
reflects it (failures.py, verify.py, implement.py, rewired cli.py, skeleton
tests). 1 critic reject (banned search call survived in evidence.py) → fixed
(call deleted per 02 spec, regression test added) → re-critic PASS → verifier:
`verified` (gate 26 passed + ruff clean, CLI + dry-run exercised). All map
tickets resolved — the way to the build wave is clear.
Type: task
Blocked by: 02, 03, 04

## Question

Turn the research findings into the v1 pipeline shape: module layout (keep the
5 stages, add implement + verify?), CLI shape, per-run outputs, report
rendering, failure records. Unblocked only when 02/03/04 have resolved —
deciding architecture on unresearched ground is how prototypes grow a second,
contradictory brain.

## Decisions to make

- Module layout under `src/attw/`: new `implement.py` + `verify.py` stages?
  What changes in the existing five (esp. `understand` gaining the
  decompose-into-components front end for both input kinds).
- CLI: `attw analyze <repo-url | idea-text>` end-to-end plus per-stage
  entry points for debugging; where sandbox copies live; flags for
  addition-only / substitution-only / dry-run (report without implement).
- Per-run outputs in `database/`: what one JSON file holds (stage outputs,
  evidence cells with source links, verdict, implement diff summary,
  before/after results, failure records with reasons).
- Report rendering: comparison table + verdict (map bar: every claim cites a
  cell), output format(s) and where the file lands.
- Failure records: schema for "stage X failed because Y" so the loop's
  downstream-only rule has something to read.
- idea-text decomposition: prompt/shape of the component list, quality bar.

## Done-criteria

Architecture recorded here and reflected in code skeleton; critic + tests
green per the loop contract. Must cite 02/03/04 resolutions per decision.

## Decision (architecture)

Skeleton built in `src/attw/` + `tests/test_skeleton.py`; stage bodies raise
`NotImplementedError (ticket 05)` except pure schema/helpers (failure
records, `verify.diff_results`/`decide_verdict`, answer-key loader,
`choose_manifest`, `adapter_path`, `classify_input`), fully implemented.

- D1 Module layout: keep `understand/find/evidence/rank/report`, add
  `implement.py` + `verify.py` + `failures.py`. `understand` gains
  `decompose() -> list[Component]` front end for both input kinds
  (`profile()` stays as compat shim). `evidence` gains `collect_evidence()`
  + `refresh_weekly_cache()`; `verify` owns baseline capture + `check()` +
  answer-key loader; `implement` owns snapshot/revert. Cites: 04 Prop
  L105-111 (harness owns capture); 03 Prop L179-183 (record/snapshot Qs);
  02 Prop L202-208 (refresh-job Q).
- D2 CLI: `analyze` end-to-end + per-stage `understand/find/evidence/rank/
  report/implement/verify` + `refresh-cache` (separate command, evidence
  owns it — answers 02 L204 residual). `analyze` flags: `--dry-run`
  (report without implement), `--mode auto|addition-only|
  substitution-only` (03 matrix L108-114), `--sandbox-dir`, `--out-dir`.
- D3 Sandbox: `tempfile.mkdtemp(prefix="attw-")` default under system temp,
  `--sandbox-dir` override; prefix-assert every write; original read-only;
  one venv per run; network-for-installs-only (03 Prop L154-163).
- D4 `database/`: one flat JSON `database/<stamp>-<slug>.json` (extended
  run record: `input{kind,value}`, components, stage outputs, evidence
  cells with source links + `as_of`/`stale`, verdict, implement receipt
  {manifest_diff, deleted_paths, adapter_path, tidy, typecheck}, verify
  block, `failures[]`) + sidecar `<stem>.report.md`. Norms are
  per-component-relative, no cross-component compare (02 L172-188);
  confidence is display-only (02 L202-208 Q3). Full copies inline, never
  pointers (sandbox temp is reaped) — answers 04 L149-153 Q2. Cites: 04
  Prop L109-110; 03 Prop L177-183 Q1.
- D5 Report: comparison table + prose verdict, every claim cites an
  evidence cell; Markdown to stdout + sidecar file. Verdict carries
  `license_warning` prose string (02 Prop L130-132, zero numeric effect)
  and dissent for hard runs; `verify.json` nodeids cited per gain (04
  Prop L119-126).
- D6 Failure schema: `{stage, code, reason, detail, run_id, component,
  ts}` (`failures.FailureRecord`); canonical codes = implement trio
  `failed-install/api-mismatch/regression` (03 Prop L165-175) + evidence
  reasons `no_pat_unauth_capped/quota_hit/source_down/stale_cache/
  deferred_source/not_applicable` (02 Prop L190-200) + `skeleton/stalled`.
  Downstream-only, never silently edit target tests.
- D7 Idea decomposition: `Component{name, description, kind:
  addition|substitution|unknown, call_sites[], confidence}`. Quality bar:
  matches the recorded human profile (map bar); doubt -> addition, never
  substitution; leave-alone list = business logic, framework-coupled,
  perf-tuned, well-tested bespoke (03 Prop L115-120).
- D8 Regress-label (04 critic nit): `pass->fail/error/skip` ALL regressed,
  absolute zero-regressed gate (04 Prop L113-117, L119-122). No soft skip
  bucket — a skipped-after-pass hides breakage until proven otherwise.
- D9 Coverage (04 critic nit): no coverage gate in v1; advisory-only, same
  status as typecheck (precedent 03 Prop L146-152: arbitrary targets are
  half-untyped). Revisit with calibration data, never a gate by default.
- D10 Copy-vs-pointer (04 critic nit): full copies (D4). Pointers into
  sandbox temp rot on reap; run JSON must stay checkable standalone.
- D11 Adapter placement (03 critic overlap): flat-layout -> repo-root
  `_attw_<wheel>_adapter.py`; src-layout -> inside the package
  `src/<pkg>/_attw_<wheel>_adapter.py` (`implement.adapter_path`).
  One file per wheel, thin delegation only, no LOC cap — critic judges
  proportionality per 03 Prop L131-144.
- D12 GPL gloss (03 critic overlap): dep-swap-or-skip, never vendor
  (03 Prop L174-175); target-license mismatch = `license_warning` prose,
  never veto, unless the GPL-vendor case, then skip the candidate.
