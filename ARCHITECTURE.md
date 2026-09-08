# ARCHITECTURE

Context for the next work session — what exists, what is stub, what is open.
Not a spec to build from.

## Pipeline

`attw analyze <url-or-idea>` (`src/attw/cli.py`) runs five stages in order:

1. **understand** → list of problem strings
2. **find** → per problem, search queries / candidate solutions
3. **evidence** → per candidate, real-world vital signs
4. **rank** → per problem, ordered options
5. **report** → Markdown printed to stdout; results JSON saved to `database/`

## Module responsibilities (`src/attw/`)

| Module | Job | Status |
| --- | --- | --- |
| `understand.py` | Profile input into problems (`profile()`) | **Stub** — returns 2 fixture problems |
| `find.py` | Find existing solutions (`search()`) | **Stub** — returns 1 fixture query |
| `evidence.py` | Free fetchers: `github_repo()`, `pypi_package()`, `npm_package()` (stdlib urllib; `GITHUB_TOKEN` honoured) | **Real**, tested live |
| `github_search.py` | `search_repos()` via GitHub search API; vital signs mapped from search payload (`closed_issues=None`); sleeps on rate-limit exhaustion | **Real**, tested live |
| `webfetch.py` | `fetch_readable()` (trafilatura) + `classify_source()` with editable `SOURCE_TIERS` | **Real**, tested live |
| `rank.py` | Rank options (`rank()`) | **Stub** — one placeholder option |
| `report.py` | `render_markdown()` over the `testdata/example_results.json` shape | **Real**, fixture-tested |
| `cli.py` | `analyze()` wiring + `main()` arg parsing; saves `database/<stamp>-<slug>.json` | **Real** (wires stubs) |

Supporting pieces: `testdata/known_answers/` (25 ground-truth cases + `SCHEMA.md`),
`scripts/validate_answers.py` (CI-gated), `.github/workflows/ci.yml`
(ruff + pytest + validator), `justfile` (`install/test/lint/validate/check`).

## Open design questions (still to resolve)

- **Find-stage search strategy.** GitHub search alone, or also PyPI/npm keyword
  search + web search over docs/SO/Reddit? How are queries generated per
  problem, and how many candidates survive to evidence stage?
- **Ranking formula.** How to combine stars, freshness, downloads, issue ratios,
  and source tier into one ordering? What breaks ties, and how are weak/no
  consensus cases (e.g. `09-ai-humaniser`) surfaced rather than hidden?
- **Learning loop.** `database/` accumulates per-run JSON; nothing reads it back
  yet. Should past analyses feed ranking priors or known-answer calibration?
- **README placeholder.** The "Shape — two layers" text was never supplied;
  `README.md` still carries a TODO placeholder — do not invent it.
- **No remote configured.** All work is committed locally only; `git push` has
  never succeeded in this environment (no remote). Add one before reporting done.
