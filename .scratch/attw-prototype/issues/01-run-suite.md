# 01 — Finalise the 10-run suite

Status: resolved

## Answer

10-run suite hardened: `testdata/known_answers/26-*.json`–`35-*.json`
(6 win on real repos with green baselines recorded, 2 hard with dissent
recorded, 2 keep-yours). Validator extended for the new schema (incl.
new_capability empty-tests carve-out); `validate_answers.py` exits 0 over
all 35 files; repo gate green. Blind critic: PASS. Baselines: temp-venv
pytest runs recorded per file; 2 Windows-only failures documented as
unrelated. Swaps from proposal documented in notes. PAT still pending —
evidence runs use unauth/cached until Luke pastes it.
Type: task

## Question

Assemble the fixed 10-run suite the whole prototype is checkable against:
~6 wins, ~2 hard judgment calls, ~2 "keep yours". Each run needs a recorded
answer-key (input, expected wheel(s), run type, what "better" looks like).
Luke verifies the proposed spread below at morning review before the loop
builds on it.

## Proposed spread (Luke: veto/trim at review)

All Python, all with runnable pytest suites (to be verified while hardening).
"Expected wheel" is the hypothesis the prototype must reproduce or beat
with a cited argument.

Wins (substitution unless noted):

1. **urllib-soup → httpx/requests.** Target with hand-rolled `urllib` helpers.
   Expected: a modern HTTP client. Better: dep-swap, helpers deleted, suite green.
2. **sys.argv CLI → typer.** Target parsing argv by hand. Expected: typer.
   Better: CLI replaced, `--help` works, suite green.
3. **Hand-rolled retries → tenacity.** Target with copy-pasted retry loops.
   Expected: tenacity. Better: loops replaced by decorators, suite green.
4. **configparser soup → pydantic-settings** (addition/substitution mix).
   Expected: pydantic-settings. Better: typed settings, suite green.
5. **Hand-rolled validation → pydantic.** Target validating dicts by hand.
   Expected: pydantic v2. Better: models replace checks, suite green.
6. **No tests → pytest suite** (pure addition). Target component with no tests.
   Expected: attw authors a meaningful suite, all passing. Better: coverage of
   the component's real behaviour, critic judges tests non-tautological.

Hard calls (judgment runs — the argument matters more than the pick):

7. **black vs ruff-format.** Target needing formatting. Either verdict
   acceptable IF the table argues it with cited evidence.
8. **httpx vs aiohttp.** Target doing async HTTP. Debatable pick; the cited
   reasoning is the graded artifact.

Keep-yours (the ranker must prove it is not a yes-machine):

9. **Already on pydantic v2, well used.** Expected verdict: keep, no change.
   Any implementation here is a failure.
10. **Niche need with no good wheel.** Expected verdict: keep hand-rolled code
    with a written justification of what was surveyed and rejected.

## Hardening checklist (this ticket's done-criteria)

- [ ] Each run has a concrete input (repo URL; run 6 may be a repo + component pointer)
- [ ] Each input verified: cloneable, suite runs green at baseline (record commit hash)
- [ ] Answer-key recorded per run (extend `testdata/known_answers/` format — see ticket 06)
- [ ] Luke has vetoed/trimmed the spread at morning review

## Rulings (Luke, 2026-09-09, pre-build review)

- Spread APPROVED. Luke notes runs could be wackier (GitHub skills/plugins
  repos etc.) — hardener may swap in wilder equivalents, same 6/2/2 shape.
- Remote deferred: loop runs local tonight, push later. No token yet either —
  Luke will mint a GitHub PAT; until then evidence work uses unauth/cached mode.
