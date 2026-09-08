# 02 — Evidence signals: what exists and what v1 uses

Status: open
Type: research

## Question

Survey the free evidence sources for Python libraries and propose the v1
signal set (+ weights / priority) for Luke's veto. Standing direction from
the map: GitHub stars are signal, license fit is a factor never a veto,
user reviews/comments/discussions are first-class evidence.

## Lines of inquiry

- GitHub REST (unauthenticated limits?), commit recency, issue counts, stars.
- PyPI JSON API, download counts (what's free and honest vs gameable).
- libraries.io, deps.dev — what they add.
- License detection (PyPI metadata vs GitHub license API).
- Review-ish sources: GitHub Discussions sentiment, Stack Overflow mentions,
  HN/Reddit threads, awesome-lists, blog comparisons — where they live and
  whether they're fetchable without keys.
- Docs/test presence heuristics computable from the repo itself.
- Fetch costs and rate limits: what a 10-run night actually costs in time.

## Done-criteria

Findings captured below; a concrete proposed v1 signal set with fetch method
per signal, ready for Luke's veto. No implementation — that belongs downstream.

## Research notes

Findings (research subagent, 2026-09-09 — for resolution, not resolved):

**GitHub REST**: unauth = 60 req/hr/IP; PAT = 5,000 req/hr. Search API is a
separate bucket (10 req/min unauth, 30 req/min authed). Current `evidence.py`
burns 1 repo call + 1 search call per candidate — unauth dies after ~30
candidates. Fix: require `GITHUB_TOKEN` for the loop, drop per-candidate search
calls. Stars, forks, pushed_at, open_issues_count, license SPDX all come from
one cheap `GET /repos/{o}/{r}`.

**PyPI JSON API**: free, no key, no published limit (version, upload times,
requires_python, classifiers, URLs). `downloads` field is always -1 — never use.
**pypistats `/recent`**: free, no key, IP-limited, daily; use last_month +
trend, never raw day counts (gameable).

**libraries.io**: needs key, maintenance mode — defer to v2.
**deps.dev v3**: free, NO key, 429+backoff only. GetVersion = SPDX + advisory
(OSV) ids; GetDependencies/Dependents = graph. Strong v1 include.

**License**: combine PyPI classifiers (honest) + GitHub license API (primary)
+ deps.dev normalization (tiebreak). Factor, never veto.

**Review-ish sources**: Stack Exchange API (300 req/day unauth, 10k with free
key — mention count + top score per library, cacheable); HN Algolia (free,
~10k/hr — story/comment counts + points); GitHub Discussions has no cheap REST
counter — proxy with issue/PR volume from the already-fetched payload;
awesome-lists via cached raw-fetch + grep. Reddit (OAuth) and blogs (no API)
deferred.

**Docs/test heuristics**: one git-tree call per candidate (same cheap bucket)
or sandbox listing: README/docs, tests/ dir, py.typed, CHANGELOG,
requires_python bound.

**10-run night cost**: ~40 candidates × ~5-6 calls ≈ 220 total. With PAT:
trivial (~10-15 min with politeness sleeps). Unauth: dead inside run 2.
Decision for architecture: PAT mandatory; per-candidate search-API calls banned.

**Proposed v1 set** (P0: stars/forks, pushed_at, open issues, license SPDX,
PyPI monthly downloads, release freshness + requires_python, known vulns via
deps.dev. P1: dep count, SO mentions+score, HN mentions+points, discussion
proxy, docs/tests/typing heuristics. P2: dependents, awesome-list hits.
Dropped: closed_issues exact, libraries.io, Reddit/blogs.)

**Open questions for Luke's veto**: (1) PAT acceptable, or must unauth work?
(2) log-scale dampening on download counts? (3) SO/HN live fetch vs nightly
cache? (4) CVE = negative factor or veto? (5) license-mismatch: numeric penalty
or prose flag?
