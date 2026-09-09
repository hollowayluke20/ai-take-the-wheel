# 02 — Evidence signals: what exists and what v1 uses

Status: resolved

## Answer

v1 signal spec decided (`## Proposal`, lines 85–194): PAT-mandatory with
unauth/cache-only fallback; P0 = repo payload + PyPI JSON + pypistats
last_month+trend + deps.dev; P1/P2 = deps, SO/HN, proxies, heuristics,
dependents, awesome-lists; per-candidate search-API calls banned; weekly
cache at `database/cache/mentions_<week_id>.json` (stale >9d); score =
10·P0+3·P1+1·P2 with log-damp; CVE −2.0/−0.5 capped −4, never veto; license
prose-only; failures emit null+reason, never fabricated. Critic round 1 FAIL
overruled by lead: the cited gap (8 tracked modifications) was prior tickets'
legitimate work verified via git status, not this builder's scope breach —
builder touched only this ticket. Lesson recorded in LOOP.md: scope checks
must be content-based, not git-status-based.
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

## Rulings (Luke, 2026-09-09, pre-build review)

- Luke mints a GitHub PAT for the loop (pending — build proceeds unauth/cached until pasted).
- CVE = mark down, never veto. License mismatch = prose warning in verdict, not a numeric penalty.
- SO/HN mention counts + review sentiment cached WEEKLY (not nightly), reused across runs.

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

## Proposal (v1 signal spec)

DECIDED v1 spec — implements Rulings (2026-09-09). Open questions above are
superseded where decided here; §6 lists what survives for architecture.

### 1. Final signal table

Auth posture (all rows): PAT-mandatory for the loop (`GITHUB_TOKEN` required;
`evidence.py:_github_headers()` already sends it). Until Luke pastes the PAT:
unauth/cached fallback — `GET /repos` unauth (60 req/hr/IP, so max ~1 run then
stop), pypistats/PyPI/deps.dev unauth as normal, SO/HN served from weekly cache
only (no live fetch). Never burn search-API quota to compensate.

| Signal | Fetch method (exact) | Quota / fallback | Pri |
|---|---|---|---|
| stars, forks, pushed_at, open_issues_count, language | `GET /repos/{o}/{r}` via `github_repo()` (search call REMOVED) | PAT bucket 5,000/hr; unauth 60/hr → degrade per §5 | P0 |
| license SPDX | same payload `license.spdx_id` (primary) + PyPI `classifiers` (honest 2nd) + deps.dev SPDX (tiebreak) | piggybacked, no extra quota | P0 |
| PyPI version, release date, requires_python | `GET https://pypi.org/pypi/{name}/json` via `pypi_package()` | free, no key, no limit; fail → missing | P0 |
| downloads last_month + trend (last_week) | `GET https://pypistats.org/api/packages/pypi/recent/{name}` via `pypi_package()`; store `last_month` + `last_week/last_month` trend; IGNORE raw day counts and PyPI `downloads:-1` | free, IP-limited daily; 429 → backoff once, then missing | P0 |
| known vulns (OSV advisory ids + severity) | `GET https://api.deps.dev/v3/systems/PYPI/packages/{name}/versions/{v}` (GetVersion) | free, 429+backoff only; fail → `vulns_unknown:true` | P0 |
| dependency count (direct) | `GET .../versions/{v}:dependencies` (GetDependencies) | same bucket; skippable on 429 | P1 |
| SO mention count + top score | StackExchange `GET /2.3/search/advanced?site=stackoverflow&q=[lib]` — WEEKLY cache only, never live per-run | 300/day unauth; one weekly job, cache reused | P1 |
| HN story/comment count + points | HN Algolia `GET http://hn.algolia.com/api/v1/search?query={lib}` — WEEKLY cache only | ~10k/hr free; one weekly job, cache reused | P1 |
| discussion/activity proxy | piggybacked `open_issues_count` + `pushed_at` from `GET /repos` payload; NO Discussions API call | zero extra quota | P1 |
| docs/tests/typing heuristics (README, docs/, tests/, py.typed, CHANGELOG, requires_python bound) | `GET /repos/{o}/{r}/git/trees/{default_branch}?recursive=1` (same PAT bucket, 1 call) OR sandbox dir listing if repo already cloned; boolean flags only | 1 cheap call; skip on 403/429 → `heuristics_unknown` | P1 |
| dependents count | `GET .../packages/{name}:dependents` (GetDependents, first page count) | same bucket; skippable | P2 |
| awesome-list hits (count + list names) | cached raw-fetch of awesome-python + awesome lists + grep, WEEKLY job | zero per-run quota | P2 |
| DROPPED: closed_issues exact | was `GET /search/issues?q=repo:...` in `github_repo()` | reason: separate 10/min bucket; kills unauth after ~30 candidates; DELETE the call | — |
| DROPPED: libraries.io | needs key, maintenance mode | reason: key cost, dead source; revisit v2 | — |
| DROPPED: Reddit / blogs / GitHub Discussions native counts | Reddit needs OAuth; blogs have no API; Discussions has no cheap counter | reason: unfetchable without keys/scraping; proxy covers v1 | — |

Ruling compliance: CVE marks down never vetoes (§4 penalty, no threshold veto).
License mismatch = prose warning string in verdict (`license_warning`), zero
numeric effect. SO/HN/sentiment/awesome = WEEKLY cache, never live per-candidate.

### 2. Per-candidate fetch plan (exact sequence, search-API calls BANNED)

Per candidate, in order, max 5-6 network calls (all parallelizable per stage):

1. `GET /repos/{o}/{r}` → stars/forks/pushed_at/open_issues/language/license.
   Piggybacked: discussion proxy, license primary. Extra: none.
2. `GET /pypi/{name}/json` → version/release/requires_python/classifiers.
3. `GET /pypistats/.../recent/{name}` → last_month + trend.
4. `GET /deps.dev/.../versions/{v}` (GetVersion) → vulns + SPDX tiebreak.
5. `GET /deps.dev/...:dependencies` (P1; skip on any 429) → dep count.
6. `GET /git/trees/{sha}?recursive=1` (P1; skip if step 1 hit quota or on
   403/429) → docs/tests/typing flags. If sandbox clone exists, use local
   listing instead (0 calls).
7. Cache reads (SO/HN/awesome/dependents-weekly): LOCAL file read, 0 network.

BANNED: `GET /search/issues`, `GET /search/repositories`, any per-candidate
StackExchange/Algolia/Reddit live call. Weekly jobs (§3) are the ONLY callers
of those endpoints. Expected night cost: ~40 candidates × ~5 calls ≈ 200,
all in PAT/data buckets → ~10–15 min with 1s politeness sleep.

### 3. Weekly cache design

- **What (snapshot per normalized PyPI name):** `so_count`, `so_top_score`,
  `so_top_qids[3]`, `hn_count`, `hn_top_points`, `hn_top_ids[3]`,
  `sentiment_snippet` (top-3 SO titles + top-3 HN titles, raw strings ≤200ch
  each, NO computed sentiment score in v1 — rank reads counts + snippets),
  `awesome_hits` (count + list names), `fetched_at` (UTC ISO), `week_id`
  (`YYYY-Www` ISO).
- **Where:** `database/cache/mentions_<week_id>.json` (one file per ISO week,
  committed; current week symlinked/copied to `mentions_latest.json`).
- **Refresh rule:** evidence stage reads `mentions_latest.json`; if its
  `week_id != current ISO week`, ONE refresh job runs (SO + HN + awesome,
  sequential, ≤50 libs), writes new week file, then runs proceed. Nightly runs
  never refresh mid-night — first run of the new week refreshes, rest reuse.
- **Staleness marking:** every SO/HN/awesome evidence cell carries `as_of`
  (file's `fetched_at`) + `stale:true` if `fetched_at > 9 days old` or week
  file missing (then cells are `missing:stale_cache`, not zero).

### 4. Scoring/weighting (rank-stage implementable rule)

DECIDED: log-damp downloads YES. All features normalized 0–1 RELATIVE to the
per-component candidate set (max in set = 1), so absolute gaming can't dominate.

- `dl = log10(1 + last_month) / log10(1 + max_last_month_in_set)`.
- `stars_n`, `forks_n` = same log10-relative norm; `fresh_n` = 1/(1+days_since_push/180);
  `issues_n` = 1/(1+open_issues/100); `release_n` = 1/(1+days_since_release/180).
- `P0 = mean(stars_n, dl, fresh_n, release_n, issues_n)` (5 signals, equal).
- `P1 = mean(dep_n [1/(1+deps/20)], so_n [log-rel SO count], hn_n [log-rel HN
  count], docs_n [fraction of 5 heuristic flags true])`.
- `P2 = mean(dependents_n [log-rel], awesome_n [hits/3 capped 1])`.
- `score = 10*P0 + 3*P1 + 1*P2`, minus CVE penalty: −2.0 per HIGH/CRITICAL
  advisory, −0.5 per MEDIUM, cap −4.0 total. Missing cells = excluded from
  their mean (denominator shrinks) + `confidence` multiplier ×(complete_cells/
  total_cells) recorded alongside. License: +0/−0, emits `license_warning`
  string only.

### 5. Failure/degradation rules (never fabricate)

Evidence cell on failure = `{"value": null, "missing": "<reason>"}` with reason
from: `no_pat_unauth_capped`, `quota_hit`, `source_down`, `stale_cache`,
`deferred_source`, `not_applicable`. Rules: GitHub 403/429 without PAT →
`no_pat_unauth_capped`, run continues on cache only; with PAT 429 → backoff
60s once, then `quota_hit`, P1 extras skipped first; PyPI/pypistats/deps.dev
5xx/timeout → `source_down` (backoff once); SO/HN/awesome never fetched live —
absent cache → `stale_cache`; libraries.io/Reddit/blogs → `deferred_source`.
Zero-filling or inventing counts is a bug per LOOP §9. Rank must handle nulls
per §4 (shrink denominator, lower confidence), never treat null as 0 silently.

### 6. Residual open questions (for architecture ticket)

1. Where does the weekly refresh job live (evidence-stage preamble vs separate
   `attw refresh-cache` command) and who owns its PAT/scheduling?
2. Candidate-set-relative norms (chosen §4) vs global norms — does rank need
   cross-component comparability, or is per-component relative enough?
3. Confidence multiplier (§4) — display-only, or does it gate keep-yours calls?
