# 22 — Understand: per-repo specificity (QUEUED)

Status: open
Type: task
File claim: `src/attw/understand.py` + its tests (plus shared
understand tests). Do NOT touch `find.py` / `rank.py`.
Blocked by: none.

## Question

How does understand produce components specific to *this* repo instead
of the same five generic templates on every target?

## Context (dogfood evidence, 2026-09-09)

ai-portfolio, daily-brief, and `psf/requests` all received
near-identical component lists (CLI parsing / retry-sleep / isinstance
validation / ad-hoc config / string-split CSV). `requests` — *the*
HTTP client library, built on urllib3 — was flagged for "HTTP fetching
with hand-rolled urllib helpers" and told to adopt `locust`. Every repo
got a "CSV parsing" component whether it parses CSV or not. The stage
matches fixed hand-rolled-pattern templates; it does not profile the
repo in front of it. Generic components downstream guarantee generic
winners.

## Spec

- Positive-evidence rule: a component is emitted only with the
  call-sites that triggered it (already recorded) *and* a
  repo-specificity check — e.g. the pattern appears in ≥2 distinct
  modules, or touches a public entry point; single incidental matches
  (one stray `urllib` import in a test helper) don't become components.
- Incumbent recognition: when the repo itself provides the capability
  the template looks for (shipped library whose README/PyPI topic
  matches the component domain — requests *is* an HTTP client),
  suppress the component with reason `incumbent-is-the-wheel` rather
  than emitting a self-replacement.
- Negative control: `psf/requests` must decompose to ≤2 components
  (down from 5), each with ≥2-module call-site evidence; ai-portfolio
  and daily-brief keep only components with multi-module evidence.
- Per LOOP.md: builder → critic → verifier, max 3 retries. Verifier
  adds the requests negative-control case (and keeps the 40 existing
  understand tests green).

## Done-criteria

Decompose of `psf/requests` yields ≤2 components with recorded
call-sites; no component whose domain the target repo itself fills;
fixed suite understand expectations (keys 26–35) unchanged. Checker =
critic + verifier per LOOP.md §§3–4. Merge via integrator trickle.
