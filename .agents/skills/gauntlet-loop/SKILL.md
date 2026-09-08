---
name: gauntlet-loop
description: Builder plus harsh critic loop per piece against a fixed bar. Use when the user says "gauntlet", "run the gauntlet", or wants a piece built then blind-checked against Wayfinder answer-keys or attw known-answers.
disable-model-invocation: true
---

# Gauntlet Loop

One piece at a time. A builder makes it, a separate harsh critic checks it against the bar, the best version survives.

## Roles

- **Lead (you)**: split the goal into pieces. One piece in play at a time.
- **Builder**: one agent builds the piece.
- **Critic**: one separate agent with fresh memory. It never sees builder notes, only the piece output plus the bar. Harsh on gaps, silent on effort.
- **Verifier**: one separate pass after the critic passes a piece. Fresh memory, no builder or critic notes — only the piece, the bar, and the repo. Checks for bugs and confirms it works as intended (see Verify stage).

## The bar (do not invent one)

- Prefer the `.wayfinder/` map plus its answer-key (pass/fail lines) from Wayfinder for the piece.
- For attw work, `testdata/known_answers/*.json` is the bar.
- The critic checks real output against that bar, blind where possible.
- If no bar covers the piece, **stop and ask the user**. Do not invent a bar.

## Loop

1. Builder makes the piece.
2. Critic names the single biggest gap vs the bar and sends it back.
3. When the critic passes, Verifier runs the Verify stage below. Any bug or behavior miss goes back to the builder with the failing evidence, then the piece re-enters at step 2.
4. Repeat with no fixed round count.
5. Keep the best version; only replace it on a head-to-head win against the bar.
6. Stop on verified pass, or when the user says stop.

## Verify (after critic pass, before done)

- Run `pytest` and `python -m ruff check` (use `ruff check` if the module form is unavailable). Fix failures before proceeding.
- Bug sweep: exercise the piece as a user would — happy path plus obvious edge cases. Reproduce any failure with a concrete command or input, not a theory.
- Intent check: confirm the piece does what the bar actually asked for, not just something shaped like it.
- Verdict is `verified` or `failed + single biggest bug with reproduction`. No partial credit.

## Log

Append to `.wayfinder/RUNLOG.md` after each piece, one line:

`| YYYY-MM-DD | <piece> | pass/fail | <biggest gap> |`

Create `.wayfinder/` and `RUNLOG.md` (with a header row) if missing.

## Safety

- After each piece: run `pytest` and `python -m ruff check` (use `ruff check` if the module form is unavailable).
- Fix failures before the next critic round.
- Do not commit or push unless the user says so.
