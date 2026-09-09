# 08 — Build: find stage

Status: resolved

## Answer

One search query per component (stars-ordered), deterministic mapping rule,
token from gitignored `.env` never printed/logged, 2s politeness spacing,
429→quota_hit failure, empty→no-candidates never invented. Live smoke:
expected wheels present (#1 requests, #5 httpx). Critic PASS; verifier
`verified` (58 passed, ruff clean, live auth works, one-query-per-component
confirmed).
Type: task
Blocked by: 07

## Question

Implement the `find` stage: per `Component`, search for candidate wheels and
return ranked-by-relevance candidates for evidence collection.

## Spec

Follow ticket 05's `## Decision` and the map's bar: the expected wheel(s)
from each suite key (`expected_wheels`, keys 26–35) must appear in the
candidates. Uses GitHub search API (authenticated via `GITHUB_TOKEN` from
`.env` — load it, never print/commit it; respect the 30 req/min authed
search bucket with politeness sleeps). Per-candidate search-API calls stay
banned per ticket 02 (search is for *finding*, one query per component, not
per candidate). No fabricated candidates: empty result = failure record
(`find: no-candidates`), never invented names. Tests use mocked HTTP
(recorded fixtures); no live network in tests.

## Done-criteria

`find.py` fully implemented; unit tests with mocked search responses incl.
empty-result and rate-limit paths; gate green; blind critic + verifier per
LOOP.md.
