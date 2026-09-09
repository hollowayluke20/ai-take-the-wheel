# 09 — Build: evidence stage

Status: resolved

## Answer

`collect_evidence` real for all P0/P1/P2: single GET /repos, PyPI JSON,
pypistats trend, deps.dev, weekly mention cache (miss/store/stale exact),
heuristics via one git-tree call; search-API per-candidate calls absent;
cells sourced with as_of; null+reason failures; CVE/license prose-only.
Cache dir gitignored (lead fix). Critic PASS; verifier `verified` (73
passed, live run 22 sourced cells, cache reuse confirmed).
Type: task
Blocked by: 08

## Question

Implement `collect_evidence` per ticket 02's decided v1 spec: every P0/P1/P2
signal fetched for real, every cell sourced, failures as null+reason.

## Spec

Implement ticket 02's `## Proposal` exactly: PAT-mandatory (`GITHUB_TOKEN`
from `.env`, never printed/committed) with unauth/cache-only fallback; P0 =
repo payload + PyPI JSON + pypistats last_month+trend + deps.dev; weekly
cache at `database/cache/mentions_<week_id>.json`; per-candidate search-API
calls BANNED (closed_issues deleted); CVE markdown (never veto); license
prose-only; failures emit null+reason enum, never zero-filled, never
fabricated. Evidence cells carry source links + as_of/stale marking per
ticket 05's run-record shape. Tests use mocked HTTP fixtures; no live
network in tests. Verify live-fetch works with a manual (non-test) run
before handoff, recorded in the report-back.

## Done-criteria

`evidence.py` fully implemented; unit tests over mocked payloads incl.
quota-hit/source-down/degraded paths; gate green; blind critic + verifier
per LOOP.md.
