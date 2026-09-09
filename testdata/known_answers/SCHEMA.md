# known_answers schema

One JSON file per ground-truth case: `testdata/known_answers/NN-slug.json`
(`NN` = two digits, e.g. `01-csv-parsing.json`).

## Fields

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `problem` | string | yes | One sentence describing the reinvented problem. Non-empty. |
| `accepted_answers` | list of objects | yes | Non-empty list. Each item: `{"name": str, "why": str}`, both non-empty. `name` = library/product name, `why` = one-line justification. |
| `sources` | list of strings | yes | 2–3 URLs backing the consensus. Every URL must be well-formed (`http`/`https` with a host). |
| `researched_on` | string | yes | Date the consensus was researched, `YYYY-MM-DD`. |
| `notes` | string | yes | Caveats (e.g. `"consensus is weak here"`). Must be present; may be an empty string if there is genuinely nothing to caveat. |

No other top-level fields beyond this schema and the Extension below are
allowed (keeps the set uniform and checkable).

## Extension: per-run answer-key fields (loop contract, ticket 06)

Base fields above stay required for every file. The fields below are
**required for suite-run files** (the ~10 files forming the fixed 10-run
suite: ~6 `win`, ~2 `hard`, ~2 `keep-yours`) and **optional otherwise**, so
existing research files keep validating. Ticket 01's hardening enforces
this section. (`LOOP.md` §8 carries the summary; this file is normative.)

| Field | Type | Required for suite runs | Rules |
| --- | --- | --- | --- |
| `input` | object | yes | `{"kind": str, "value": str}`. `kind` is exactly `repo_url` or `idea_text`. `value` is the exact pipeline input, non-empty. |
| `expected_wheels` | list of strings | yes | Non-empty for `win`/`hard` runs: element 0 is the expected #1 winner, remaining elements are acceptable alternates. Empty list `[]` for `keep-yours` runs (no wheel should win; the incumbent stands). |
| `run_type` | string | yes | Exactly one of `win` \| `hard` \| `keep-yours`. `win` = pipeline should find and integrate a clearly-better wheel. `hard` = judgment call; winner argued, dissent recorded. `keep-yours` = ranker must decline; an always-recommends ranker fails these. |
| `better_spec` | object | yes | `{"mode": str, "tests": list of str, "benchmark": object\|null}`. `mode` is exactly `red_to_green` \| `new_capability` \| `measured_gain` \| `keep_yours`. `tests` = pytest node ids proving the gain; non-empty unless mode is `measured_gain` with a `benchmark` object, or mode is `new_capability` (the capability — and its tests — don't exist yet; node ids are authored at build time and the critic enforces adequacy). `benchmark` claims gain ONLY from same-machine before/after comparison with non-overlapping distributions (clearly-faster-here bar, no fixed percentage); otherwise `null`. `keep_yours` requires `tests: []` and `benchmark: null`. |
| `verify` | object | yes | `{"test_command": str, "baseline": object, "authored_tests": list of str, "zero_regressions": bool}`. `test_command` non-empty (e.g. `"pytest -q"`). `baseline` = `{"captured": bool, "tool": "pytest-json-report"}` (per-ticket-04 harness: nodeid-keyed baseline/after diff; exit code 5 = no tests = harness failure). `authored_tests` = paths of attw-authored tests, may be `[]`. `zero_regressions` is always `true`: any `pass→fail` node is a gate-killer; `removed` nodes must be explained in `notes`. |

### Example (win run)

```json
{
  "problem": "Parsing CSV files in Python with hand-rolled string splitting instead of a library.",
  "accepted_answers": [{"name": "csv (Python standard library)", "why": "Correct quoting/dialect handling with zero dependencies."}],
  "sources": ["https://docs.python.org/3/library/csv.html", "https://example.com/discussion"],
  "researched_on": "2026-09-09",
  "notes": "",
  "input": {"kind": "idea_text", "value": "Parse a CSV upload in my Flask app"},
  "expected_wheels": ["csv (Python standard library)"],
  "run_type": "win",
  "better_spec": {"mode": "red_to_green", "tests": ["tests/test_csv_parse.py::test_quoting"], "benchmark": null},
  "verify": {"test_command": "pytest -q", "baseline": {"captured": true, "tool": "pytest-json-report"}, "authored_tests": [], "zero_regressions": true}
}
```

## Validation

`scripts/validate_answers.py` enforces all of the above and exits non-zero
on any failure. CI runs it (see `.github/workflows/ci.yml`).
