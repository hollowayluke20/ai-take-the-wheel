# testdata/known_answers/

Ground-truth cases. One JSON file per problem: `NN-slug.json` (e.g.
`01-csv-parsing.json`).

Fields (see `SCHEMA.md` once Task 6 lands):

- `problem`: one sentence.
- `accepted_answers`: list of `{name, why}`.
- `sources`: 2–3 URLs.
- `researched_on`: date (YYYY-MM-DD).
- `notes`: caveats, e.g. "consensus is weak here".
