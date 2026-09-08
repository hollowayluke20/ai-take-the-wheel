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
  reconciled with this tracker's paths in ticket 06.

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
