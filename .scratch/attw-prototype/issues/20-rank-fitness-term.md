# 20 — Rank: fitness-to-component term + freshness gaming (QUEUED)

Status: open
Type: task
File claim: `src/attw/rank.py` + its tests (plus shared rank tests).
Blocked by: none.

## Question

How does the rank score reflect *fitness to the component*, not just
vital-sign popularity — and stop rewarding brand-new packages for being
new?

## Context (dogfood evidence, 2026-09-09)

- `tranq` (94 stars, PyPI release dated *the same day*, 2026-09-09) won
  retry on daily-brief on freshness/release recency over `tenacity`
  (8777 stars) and `backoff` (152M dl/mo).
- `instructor` (LLM structured-output lib) beat `pydantic` by 0.14 as a
  *data-validation* wheel on ai-portfolio and requests; `pydantic` won
  the same component on daily-brief. Same component, three runs, two
  different winners — the swing came from quota-degraded download
  evidence (`DL/mo n/a`), i.e. popularity signals decide fitness
  questions and collapse when throttled.
- Nothing in the score asks "does this library do the component's job";
  a TUI lib (`pytermgui`) can win "CLI framework" purely on vitals.

## Spec

- Add a fitness term to the exact formula: textual/functional match
  between the candidate (PyPI summary + keywords + README-topic
  presence) and the component description, with weight recorded in the
  run record per candidate (auditable, cited).
- Cap the freshness/release-recency contribution so a package younger
  than N days (propose N=90, Luke vetoes) cannot outscore an
  established wheel on recency alone; record the cap hit per candidate.
- Scores remain deterministic given identical evidence (no wall-clock
  in the formula except through recorded evidence cells).
- Per LOOP.md: builder → critic → verifier, max 3 retries. Verifier
  proves `tranq`-style newcomers can't win on newness and that
  identical evidence re-ranked gives identical order.

## Done-criteria

Dogfood re-runs: `pytermgui` no longer wins CLI, `instructor` no longer
wins plain validation, a same-day release cannot top an established
category; fixed suite keys 26–35 show no verdict-vs-expected
regressions. Checker = critic + verifier per LOOP.md §§3–4. Merge via
integrator trickle.
