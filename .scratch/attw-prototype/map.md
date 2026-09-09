# Map — attw solid prototype

Charted 2026-09-09 with Luke (2 grilling rounds). Execution-carrying map: tickets
resolve into working, checked code, not decisions.

## Destination

`attw analyze` takes **a repo URL or an idea-text**, decomposes it into
**components** (code reading for repos, LLM decomposition up front for ideas —
then one identical pipeline), and per component: finds candidate wheels, gathers
evidence, ranks them, and argues the winner in a **comparison table + prose
verdict where every claim cites an evidence cell**. Then it goes further:
**implements the winner into a throwaway copy** of the target (addition *and*
substitution, inferred per component), tidies up, and **proves improvement with
before/after tests** — authoring tests itself where the wheel demands it.

Done = the full pipeline runs on a **fixed 10-run suite** (~6 wins, ~2 hard
calls, ~2 "keep yours"), each run checkable against a recorded answer-key, and
Luke judges the reports sensible.

## Notes

- Domain: Python only. This repo: attw CLI (`src/attw/`), `testdata/known_answers/`,
  per-run outputs in `database/`. Tracker conventions: `docs/agents/issue-tracker.md`.
- Standing preference (Luke): wayfinder maps carry execution. Tickets resolve into
  merged, checked pieces of the prototype. Decisions-only is never the default.
- **What "better" looks like (the bar)**:
  - understand: component list matches the recorded human profile for the input.
  - find: expected wheel(s) present in candidates (recorded per run).
  - evidence: every cell populated from a real source; every number links to it.
    A fabricated number is a bug, not a gap.
  - rank: expected winner ranked #1.
  - report: table + verdict, every claim cites an evidence cell; an uncited claim
    is a report bug. Luke judges sensible.
  - implement: sandboxed copy only; winner integrated with minimal diff; tidy
    (formatted, lint-clean); pre-existing tests pass at least as before.
  - verify: before/after test runs recorded; improvement = red→green, new
    capability with new passing tests, or measured gain — with zero regressions
    as the gate.
- **Evidence direction**: GitHub stars are signal; license fit is a factor, never
  a veto; user reviews/comments/discussions are first-class evidence.
- **Loop operating contract**: sequential, one ticket per session, claim
  (`Status: claimed`) before any work. Each built piece passes the automated gate
  (answer-key match + `pytest` + `ruff check` green) *and* a blind critic;
  auto-rebuild on reject, max 3 retries, then flag for Luke. Failures record
  their reason, stop only what depended on them, everything else continues;
  3 consecutive failures = red flag for morning review, not a halt.
- **Stall-detection (no hard time-boxes)**: a run showing no progress output for
  20 min is recorded as stalled and the loop moves on. First real night calibrates
  the threshold.
- **Permissions**: the loop runs permissionless. Nothing waits on an approval
  prompt overnight.
- **Sandbox**: throwaway copy of the target under temp. Original never touched.
  Network allowed for installs. Never pushes anywhere.
- Checker mechanics: gauntlet-loop skill (`.agents/skills/gauntlet-loop/SKILL.md`),
  reconciled with this tracker's paths in ticket 06; the resulting contract is
  [Loop contract](.scratch/attw-prototype/LOOP.md).

## Decisions so far

- **Both front doors**: repo URLs and idea-text both in
  scope; components are the common currency (grill round A, Q9).
- **Addition and substitution**: attw infers which per
  component and states the call in the report (Q10/Q21).
- **Better = tests + judgment**: no-regressions gate plus
  recorded gains; verify may author tests (Q11).
- **Sandbox = temp copy** (Q12).
- **Suite has keep-yours runs**: the ranker must prove it
  is not a yes-machine (Q13).
- **Stars signal, license soft, reviews gold** (Q19).
- **Table + verdict, cited**: report format (Q15).
- **Sequential loop**: one ticket per session (Q16).
- **Gauntlet from v1**: automated gate + blind critic,
  3 retries, then flag (Q17/Q22).
- **Downstream-only failure** (Q23).
- **No time-boxes, stall-detection instead** (Q24).
- **Permissionless overnight** (Q22 side-note).
- [Loop contract](.scratch/attw-prototype/issues/06-loop-contract.md): one bar
  (known_answers extended), RUNLOG under `.scratch/attw-prototype/`, blind
  critic + verifier per piece, 3 retries then NEEDS-LUKE flag.
- [10-run suite](.scratch/attw-prototype/issues/01-run-suite.md): keys 26–35
  hardened with green baselines; validator enforces the extended schema;
  critic PASS.
- [Evidence signals](.scratch/attw-prototype/issues/02-evidence-signals.md):
  v1 spec decided (PAT-mandatory, P0/P1/P2, weekly cache, CVE/license rules,
  null+reason failures); resolved with one overruled critic round.
- [Implement strategy](.scratch/attw-prototype/issues/03-implement-strategy.md):
  matrix + per-cell defaults, outright deletion in sandbox, adapter rules
  without LOC cap, sandbox protocol, exact failure strings; critic PASS.
- [Verify harness](.scratch/attw-prototype/issues/04-verify-harness.md):
  harness-owned capture, 4-bucket diff + verify.json, ordered critic gate,
  benchmark + stall protocols, night budget; critic PASS.
- [Pipeline architecture](.scratch/attw-prototype/issues/05-architecture.md):
  layout + CLI + run-record + report + failure schema decided and skeleted in
  code; 1 critic reject fixed; verifier `verified`. Map fully worked.

## Build wave (graduated 2026-09-09, Luke said build, PAT stored)

Linear gauntlet per stage, each blocked by the last: 07 understand → 08 find
→ 09 evidence → 10 rank → 11 report → 12 implement → 13 verify + end-to-end.
PAT live (5000/hr confirmed) in gitignored `.env`; builders load it, never
print/commit it.
- [07 understand](.scratch/attw-prototype/issues/07-build-understand.md):
  decompose() real for both kinds, exact failures, no API calls; critic PASS,
  verifier `verified` (40 passed).
- [08 find](.scratch/attw-prototype/issues/08-build-find.md): one query per
  component, token safe, politeness + quota paths; critic PASS, verifier
  `verified` (58 passed, live auth works).
- [09 evidence](.scratch/attw-prototype/issues/09-build-evidence.md): all
  signals real, weekly cache exact, null+reason failures; critic PASS,
  verifier `verified` (73 passed, 22 live sourced cells).
- [10 rank](.scratch/attw-prototype/issues/10-build-rank.md): exact formula,
  CVE capped never vetoes, license unscored, keep/decline real; critic PASS,
  verifier `verified` (80 passed).
- [11 report](.scratch/attw-prototype/issues/11-build-report.md): cited
  table + verdict, uncited-claim enforcement real, sidecars; critic PASS,
  verifier `verified` (98 passed).
- [12 implement](.scratch/attw-prototype/issues/12-build-implement.md):
  full matrix real incl. vendor application, airtight sandbox, exact
  failures with revert; 1 reject fixed; verifier `verified` (126 passed).
- [13 verify + end-to-end](.scratch/attw-prototype/issues/13-build-verify.md):
  harness real, pipeline wired end-to-end, live proof 26/34/35 PASS;
  accepted with known limitation (test-group deps, e.g. freezegun, not
  installed in sandbox — follow-up lane task). MAP COMPLETE.

## Lanes wave 1 (Alex structure, all checker-passed, merging trickle)

- [14 test-group deps](.scratch/attw-prototype/issues/14-lane-test-group-deps.md): PASS.
- [15 quality floor](.scratch/attw-prototype/issues/15-lane-quality-floor.md): PASS.
- [16 broader find](.scratch/attw-prototype/issues/16-lane-broader-find.md): PASS.
- [17 smarter decompose](.scratch/attw-prototype/issues/17-lane-smarter-decompose.md): PASS.
- [18 skipped keys](.scratch/attw-prototype/issues/18-lane-skipped-keys.md): claimed, running.
- **Pre-build rulings (Luke, 2026-09-09)**: suite spread approved, wackier
  targets allowed at same 6/2/2 shape; PAT pending (Luke mints it;
  unauth/cached until then); CVE marks down never vetoes; license mismatch =
  prose warning; mention/review sentiment cached weekly; 2 wheel fallbacks;
  deletion allowed outright in sandbox; GPL = dep-swap-or-skip; verify harness
  owns baseline capture; NO adapter LOC cap (critic judges per case); verify
  keys extend known_answers; pytest-json-report allowed; clearly-faster-here
  benchmark bar; single 20-min stall default; remote deferred, loop runs local.

## Not yet specified

- Full v1 evidence signal set + weights — ticket 02 proposes, Luke vetoes.
- Implement strategy matrix (dep-swap vs vendor vs adapter) — ticket 03.
- Verify harness design (baseline capture, authored-test adequacy rules) — ticket 04.
- idea-text decomposition quality bar (what a "good" component list looks like).
- "Tidy" thresholds beyond formatted + lint-clean (e.g. typecheck?).
- Stall-detection threshold calibration after the first real night.
- Critic blindness mechanics for generated code (what exactly the critic sees).

## Out of scope

- Non-Python ecosystems (npm, cargo, …). Prototype proves Python first.
- Opening pull requests on other people's repos. Throwaway copies only.
- Any website or hosted service. CLI only.
- Publishing improved wheels back upstream.

Scope returns only if the destination is redrawn, as a fresh effort.
