# 21 — Keep-yours calibration on mature repos (QUEUED)

Status: open
Type: task
File claim: `src/attw/rank.py` + its tests (shared with ticket 20 —
coordinate or serialize; do NOT touch `find.py` / `understand.py`).
Blocked by: 20.

## Question

When the target already *is* the wheel (or a mature, well-built
project), how does attw say "keep yours" instead of crowning a
nonsense challenger?

## Context (dogfood evidence, 2026-09-09)

`psf/requests` — the mature HTTP library — came back with five
substitution verdicts: rebuild validation with `instructor`, HTTP with
`locust`, CSV with `countries-states-cities-database`. No component
declined, none kept. The suite already has keep-yours runs (34, 35) and
lane 15 built a decline-weak floor, but the floor evidently doesn't
trigger when the *component itself* is misfired at a project that has
no such gap. A yes-machine that always finds five things to replace
will never be trusted on a dead project, let alone a live one.

## Spec

- Define the keep-yours bar explicitly: a challenger wins only if it
  beats a "keep yours" baseline candidate scored from the target's own
  evidence (incumbent present, maintained, depended-upon). Record the
  baseline row in every table so the reader sees what the challenger
  beat — or failed to beat.
- Calibrate on `psf/requests`: after this ticket, a dry-run on
  requests must keep/decline a majority of components, with per-item
  reasons (incumbent-strong, challenger-unfit, evidence-degraded).
- Degraded-evidence rule: when quota hits null out discriminating
  cells (e.g. `DL/mo n/a` for the top two), the component declines
  with reason `evidence-degraded` instead of crowning on partial
  vitals (extends lane 15's floor to the throttled case).
- Per LOOP.md: builder → critic → verifier, max 3 retries.

## Done-criteria

Dry-run on `psf/requests` keeps/declines ≥3 of 5 components with
recorded reasons; suite keep-yours runs (34, 35) still pass; no
verdict-vs-expected regressions on keys 26–35. Checker = critic +
verifier per LOOP.md §§3–4. Merge via integrator trickle, serialized
after ticket 20 (shared file claim).
