# LOOP — overnight operating contract (attw prototype)

You are an overnight build agent with **no memory of any prior session**.
This file is your complete operating contract. Follow it literally.
If this file conflicts with anything else, this file wins.

## 0. What you are building

`attw analyze` takes **a repo URL or an idea-text**, decomposes it into
**components**, and per component finds candidate wheels, gathers evidence,
ranks them, and argues the winner in a **comparison table + prose verdict
where every claim cites an evidence cell**. It then integrates the winner
into a throwaway copy of the target and proves improvement with before/after
tests. The full pipeline runs on a **fixed 10-run suite** (~6 wins, ~2 hard
calls, ~2 "keep yours"), each run checkable against a recorded answer-key.

Ground truth (the bar): `testdata/known_answers/NN-slug.json`, format in
`testdata/known_answers/SCHEMA.md` (per-run key fields: §8 below).
Per-run outputs go in `database/` (one JSON file per analysis).
Source code lives in `src/attw/`. Python only. CLI only.

## 1. Claim / work / resolve mechanics

Issue files live at `.scratch/attw-prototype/issues/NN-<slug>.md`.
Each file has, near the top, `Status:` and `Type:` lines, and optionally a
`Blocked by: NN, NN` line. Statuses in use: `open`, `claimed`, `resolved`.

1. **Frontier**: scan `.scratch/attw-prototype/issues/` for files that are
   open, unblocked (every ticket in its `Blocked by:` line is `resolved`),
   and unclaimed. Lowest number wins.
2. **Claim**: set its `Status:` line to `claimed` and save **before** doing
   any other work. One ticket per session — never claim a second ticket,
   never work an unclaimed ticket.
3. **Work**: build only what that ticket's done-criteria ask. Touch only
   files the ticket names. Do not touch source outside the ticket's scope,
   other tickets, `map.md`, or `IN-PROGRESS.md`.
4. **Resolve**: append your answer under an `## Answer` heading at the
   bottom of the issue file (create it if absent; never rewrite other
   sections), set `Status: resolved`, save.
5. **Comments**: append discussion/history under a `## Comments` heading
   (create it if absent). Never edit another agent's signed comment; add
   your own dated entry instead.

## 2. Sequential loop — one ticket per session

- Sessions run **sequentially, one ticket per session**. You do exactly one
  ticket, then stop.
- **Permissionless**: never wait on an approval prompt. If a command needs
  approval, find the non-interactive flag (e.g. `--yes`, `-y`, `--non-
  interactive`, `PIP_NO_INPUT=1`) or record the blocker in your `## Answer`
  and move on to the log step (§7), then stop.
- Do not commit or push unless the ticket explicitly says to.

## 3. Builder → blind critic → verifier flow

Every built piece passes three roles **in order**. You play builder first;
the critic and verifier passes run as separate fresh-memory checks (a new
session, or a deliberate fresh read with builder notes closed).

1. **Builder (you)**: implement the ticket's done-criteria. Run the
   automated gate (§4) yourself before handing off.
2. **Critic (fresh memory, blind)**: checks the piece output against the
   bar (§8 + ticket's bar). Verdict is `pass`, or `reject + the single
   biggest gap` (exactly one gap, the most load-bearing, stated with the
   bar line it violates). Harsh on gaps, silent on effort. Never invent a
   bar: if no bar covers the piece, verdict is `blocked — no bar`, and the
   piece is flagged for Luke (§6), not rebuilt.
3. **Verifier (fresh memory, after critic pass)**: runs §4 gate commands
    from a clean checkout state, exercises the piece as a user would (happy
    path + obvious edge cases), and confirms it does what the bar actually
    asked (intent check). Verdict is `verified`, or `failed + single biggest
    bug with reproduction` (concrete command/input, not a theory).

Scope-check rule (lesson, 2026-09-09): the critic checks scope by CONTENT
(did proposal/code leak outside the ticket's files), never by `git status`
— the tree always carries other tickets' legitimate work, and status-based
scope fails are invalid on their face.
4. A reject/fail goes back to the builder with the failing evidence; the
   piece re-enters at the critic. Keep the best version; only replace it on
   a head-to-head win against the bar.

## 4. Automated gate (verified working in this repo)

Run from the repo root (`C:\Users\hollo\OneDrive - University of Warwick\Documents\Default Project`).
Verified 2026-09-09 (`pytest 8.4.2`, `ruff 0.16.6`):

- `python -m pytest -q` — must exit 0. (Result on 2026-09-09: **10 passed**.)
- `python -m ruff check .` — must exit 0, "All checks passed!".
  (Bare `ruff` is NOT on PATH in this repo — always use the `python -m`
  form.)

A piece is gate-green only if **both** commands exit 0 **and** (where the
ticket names one) the answer-key match it requires holds. Gate-red stops
only the dependent ticket; everything else continues. Unrelated pre-existing
failures are recorded in the ticket's `## Answer`, never fixed as drive-bys.

## 5. Retry accounting (max 3)

- The retry count lives in the ticket file: each builder retry appends a
  dated `## Comments` entry starting `Retry N/3:` (N = 1, 2, 3).
- A retry request contains exactly: (a) the critic/verifier verdict quoted,
  (b) the single biggest gap or bug, (c) the bar line it violates, (d) the
  failing reproduction command where applicable. One gap per retry.
- After the 3rd retry still fails (3 `Retry N/3` entries, critic/verifier
  still red), stop rebuilding and flag for Luke (§6). Never attempt Retry 4.

## 6. Flagging for Luke

Flagging = file + comment + log line, all three:

1. In the ticket file, append a `## Comments` entry starting with the
   literal line `NEEDS-LUKE:` followed by: ticket number, best-version
   location, the 3 retry gaps (one line each), and the exact blocker or
   question. Leave `Status: claimed` (do NOT mark `resolved`).
2. Append a RUNLOG line (§7) with verdict `needs-luke` and the one-line
   reason in the gap column.
3. Stop. Do not claim another ticket this session.

Failure policy: a failure records its reason and stops only what depended
on it; everything else continues. **3 consecutive `fail`/`needs-luke`
RUNLOG lines = red flag for morning review** (next agent adds a
`## Comments` entry `MORNING-FLAG: 3 consecutive failures` to the newest
failed ticket), not a halt — the loop keeps working the frontier.

## 7. RUNLOG

File: `.scratch/attw-prototype/RUNLOG.md` (this tracker's home for the log —
not `.wayfinder/`). One line per piece/session, appended immediately after
the verdict is known. Exact format (header row + rows):

`| Date (UTC) | Ticket | Piece | Verdict | Biggest gap / note | Retries used |`

- `Date (UTC)`: `YYYY-MM-DD`.
- `Ticket`: `NN-slug` matching the issue file.
- `Piece`: short name of what was built.
- `Verdict`: exactly one of `pass` | `fail` | `needs-luke` | `stalled`.
- `Biggest gap / note`: the single biggest gap, bug + reproduction, or
  `—` on a clean pass.
- `Retries used`: `0`–`3`.

Create the file with the header row plus the separator row if missing; never
rewrite existing rows.

## 8. Answer-key schema extension (per-run keys)

The bar for the 10-run suite is recorded in `testdata/known_answers/` per
`testdata/known_answers/SCHEMA.md`. The base fields (`problem`,
`accepted_answers`, `sources`, `researched_on`, `notes`) stay required.
Per-run answer-key fields below are **required for suite-run files**
(the ~10 files forming the fixed suite) and **optional otherwise**, so the
existing research files keep validating. Ticket 01's hardening enforces this
section; full field spec lives in `SCHEMA.md`, summarized here:

- `input`: object `{"kind": "repo_url" | "idea_text", "value": <string>}` —
  the exact pipeline input for the run. Non-empty `value`.
- `expected_wheels`: list of strings, non-empty for `win`/`hard` runs
  (rank-#1 winner must be element 0; element 0 is the expected winner,
  the rest are acceptable alternates). Empty list `[]` for `keep-yours`
  runs (no wheel should win; the incumbent stands).
- `run_type`: exactly one of `win` (pipeline should find and integrate a
  clearly-better wheel) | `hard` (judgment call; winner argued, dissent
  recorded) | `keep-yours` (ranker must decline; an always-recommends
  ranker fails these).
- `better_spec`: object proving "better" per the map's bar —
  `{"mode": "red_to_green" | "new_capability" | "measured_gain" |
  "keep_yours", "tests": [<pytest node ids>], "benchmark": <object|null>}`.
  `tests` is non-empty unless mode is `measured_gain` with a benchmark
  object (same-machine before/after, non-overlapping distributions —
  clearly-faster-here, no fixed percentage) or mode is `new_capability`
  (tests authored at build time, adequacy critic-enforced). `keep_yours`
  requires `tests: []` and `benchmark: null`.
- `verify`: object grounding the verify harness (ticket 04 rulings) —
  `{"test_command": <string, e.g. "pytest -q">, "baseline": {"captured":
  <bool>, "tool": "pytest-json-report"}, "authored_tests":
  <list of paths, may be []>, "zero_regressions": true}`.
  `zero_regressions` is always `true`: any `pass→fail` node is a
  gate-killer. `removed` test nodes must be explained in `notes`.

Critic check against this bar: `find` passes if element 0 (or an alternate)
of `expected_wheels` is in candidates; `rank` passes only if element 0 is
ranked #1 (or the field is `[]` and the verdict is keep-yours); `report`
passes only if every claim cites an evidence cell; `verify` passes only if
`better_spec`/`verify` conditions hold with zero regressions.

## 9. Sandbox, stall, and evidence rules (non-negotiable)

- **Sandbox**: integrate winners into a throwaway copy of the target under
  the system temp dir only. The original target is never touched. Network
  allowed for installs. Never push anywhere. Deletion inside the sandbox is
  allowed outright.
- **Stall-detection**: a run with no progress output for **20 min** is
  recorded as `stalled` in RUNLOG and the loop moves on (abandon that run
  only). First real night calibrates per-stage thresholds; until then the
  single 20-min default stands.
- **Evidence honesty**: every number links to a real source. A fabricated
  number is a bug, not a gap. License mismatch = prose warning, never a
  veto. CVE history marks down, never vetoes. GitHub stars are signal;
  user reviews/comments/discussions are first-class evidence.
- **The bar (do not invent one)**: the critic checks real output against
  the recorded answer-key. If no bar covers the piece, stop and flag for
  Luke (§6). Do not invent a bar.

## 10. Session checklist (do this every session)

1. Read this file and the ticket file. Nothing else is context you need.
2. Claim (§1). One ticket. If the frontier is empty, log nothing and stop.
3. Build → gate (§4) → critic → verifier (§3).
4. Retries per §5 (max 3), flag per §6 when exhausted.
5. Resolve the ticket file (§1). Append the RUNLOG line (§7).
6. Stop. Report: files changed, gate results, deviation from the ticket.
