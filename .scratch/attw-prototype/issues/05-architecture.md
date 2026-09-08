# 05 — Pipeline architecture

Status: open
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
