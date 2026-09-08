# AGENTS.md

## Project summary

AI_TAKE_THE_WHEEL (`attw`) takes a code repo URL or a plain-text project idea,
finds how the same problems have already been solved elsewhere, and ranks the
options by real-world evidence (GitHub vital signs, PyPI/npm stats, source
quality) — so builders stop reinventing solved problems.

## The 5-stage pipeline

1. **understand** (`src/attw/understand.py`) — profile the input into problems.
2. **find** (`src/attw/find.py`) — find existing solutions per problem.
3. **evidence** (`src/attw/evidence.py`) — fetch free evidence for candidates.
4. **rank** (`src/attw/rank.py`) — rank options by evidence.
5. **report** (`src/attw/report.py`) — render a readable ranked report.

Ground truth lives in `testdata/known_answers/` (NN-slug.json); per-run
outputs go in `database/` (one JSON file per analysis).

## Standing rule

**Push before you report done; leave IN-PROGRESS.md around any long batch of
work.** No batch of changes counts as finished until it is committed and
pushed, and if you stop mid-task, leave `IN-PROGRESS.md` at the repo root
saying where you got to.
