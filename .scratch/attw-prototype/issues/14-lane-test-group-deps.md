# 14 — Lane: test-group deps in sandbox

Status: resolved

## Answer

Test-group mechanism real (dependency-groups + extras + requirements-test,
pre-baseline, exact failures); key-30 baseline fixed (383 nodes, 0 install
failures). Critic PASS (winner-drift ruled out of scope); verifier verified.
Merged via PR (trickle).
Type: task
Lane: 1 of 4. File claim: `src/attw/implement.py`, `src/attw/verify.py`, `tests/test_implement.py`, `tests/test_verify_harness.py`.

## Question

Close ticket 13's known limitation: install the target's TEST
dependency-groups (e.g. freezegun from `[dependency-groups] test`) into the
sandbox venv, so suites like key 30's can baseline.

## Spec

Extend the retry-3 plugin mechanism (addopts-implied) to test groups:
read `[dependency-groups]` (pyproject), `extras_require['test']`
(setup.py/cfg), and `requirements-test*.txt`/`requirements/test*.txt` where
present; install into the sandbox venv before baseline capture (installs-only
network); failures → exact failure records, downstream-only. Modest
allowlist instincts: install what's declared, no unbounded resolution.
Then re-run key 30 end-to-end and record verdict-vs-expected.

## Done-criteria

Mechanism implemented + unit tests (declared-group parsing, install wiring
mocked, failure records); key-30 re-run recorded; gate green; checker
(critic + verifier) happy before integrator. Then merge via PR, trickle.
