# 19 — Find: library-ness gate (QUEUED)

Status: open
Type: task
File claim: `src/attw/find.py` + its tests (plus shared find tests).
Blocked by: none.

## Question

How does the find stage stop returning *applications* when asked for
*wheels* (libraries)?

## Context (dogfood evidence, 2026-09-09)

Three dry-runs — `database/2026-09-09-181613-*-ai-portf`,
`database/2026-09-09-182529-*-daily-br`,
`database/2026-09-09-183316-*-requests-git` — show the same failure:
a single GitHub keyword query (`cli framework language:python`,
`csv parser language:python`, …) returns repos that *mention* the
keyword, not libraries that *are* the wheel. Observed winners:
`yt-dlp`, `sherlock`, `aider` ranked as "CLI frameworks";
`countries-states-cities-database` (a JSON data dump, no PyPI release)
ranked #1 as a "CSV parser" on all three runs; `locust` (a load-testing
tool) ranked #1 as an "HTTP client" twice.

## Spec

- A candidate must clear a library-ness bar before it can win: present
  on PyPI (PyPI JSON 200 for the pinned version) OR an explicit,
  recorded exception with reason (e.g. stdlib-adjacent single-file
  tools). A candidate with `Released: n/a (not_applicable)` can appear
  in the table but is ineligible for #1.
- `ineligible_for_win` + reason surfaces in the run record and the
  report table (new column or marker), so a reader can see *why* the
  popular-but-ineligible entry didn't win.
- Per LOOP.md: builder → critic → verifier, max 3 retries. Verifier
  extends the suite or adds unit tests proving a data-dump repo can no
  longer win "CSV parser" and an app can no longer win "CLI framework".

## Done-criteria

Re-running the three dogfood targets shows no non-library winner in any
table; the fixed 10-run suite (keys 26–35) still passes with no
verdict-vs-expected regressions. Checker = critic + verifier per
LOOP.md §§3–4. Merge via integrator trickle.
