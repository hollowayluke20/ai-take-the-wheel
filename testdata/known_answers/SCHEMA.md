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

No other top-level fields are allowed (keeps the set uniform and checkable).

## Validation

`scripts/validate_answers.py` enforces all of the above and exits non-zero
on any failure. CI runs it (see `.github/workflows/ci.yml`).
