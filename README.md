# AI_TAKE_THE_WHEEL

A tool that, given a code repo URL or a plain-text project idea, finds how the
same problems have already been solved elsewhere and ranks the options by
real-world evidence.

> TODO (Task 1 placeholder): paste the authoritative "Shape — two layers" and
> pipeline description here. Left as a placeholder so nothing is invented.

## Pipeline (stub summary — full text TBD)

1. `understand` — profile the input repo/idea into a list of problems.
2. `find` — find existing solutions for each problem.
3. `evidence` — fetch real-world evidence (GitHub, PyPI, npm).
4. `rank` — rank options by evidence.
5. `report` — render a readable report.

Each stage lives in `src/attw/<stage>.py`. All stages are currently stubs
except `evidence.py` (free fetchers, Task 3).

## Layout

- `src/attw/` — package code
- `testdata/known_answers/` — 25 ground-truth cases (see its README)
- `database/` — one JSON file per analysis (see its README)
- `tests/` — pytest suite
- `scripts/` — helper scripts (e.g. `validate_answers.py`)
