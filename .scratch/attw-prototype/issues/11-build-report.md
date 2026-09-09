# 11 — Build: report stage

Status: open
Type: task
Blocked by: 10

## Question

Implement the report renderer: comparison table + prose verdict where every
claim cites an evidence cell, plus the `.report.md` sidecar.

## Spec

Per ticket 05's `## Decision` and the map's bar: table (wheel × criteria,
cells cite evidence with source links); short prose verdict stating
addition vs substitution per component; `license_warning` prose where
applicable; gains cited by pytest node id; an UNCITED CLAIM IS A REPORT BUG
(render fails the piece if any claim lacks a cell cite — enforce in code
where checkable). Outputs: `database/<stamp>-<slug>.json` run record +
`.report.md` sidecar. `analyze --dry-run` renders without implement/verify.
Tests: fixture run-records → assert table/verdict contents, cite presence,
keep-yours rendering, failure-record sections.

## Done-criteria

`report.py` fully implemented; unit tests over fixtures; gate green; blind
critic + verifier per LOOP.md.
