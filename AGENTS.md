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

## Agent skills

### Issue tracker

Local markdown under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context. See `docs/agents/domain.md`.

<!-- graft:start -->
## Graft — repo context graph

This repo is indexed in `graft/`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run `graft map` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run `graft ask "<your question>" --source` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; `--full` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  `covers:` file:line spans and edit straight from `--source`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run `graft grep "<literal>"` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw `grep -rn` only for unindexed files.
- `graft skeleton <file>` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- `graft callers <symbol>` gives precomputed, exact edges — who calls this.
  Add `--direction out` for what it calls, or `--depth N` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: `graft/INDEX.md` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry `[scope/]` labels naming which one they're from. Narrow with
  `graft ask "<task>" --in <scope>/` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with `graft build` (deterministic,
no API key, $0).
<!-- graft:end -->
