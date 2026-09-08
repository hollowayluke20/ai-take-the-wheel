# 03 — Implement strategy: getting the wheel into the copy

Status: open
Type: research

## Question

How does attw apply a winning wheel to a throwaway sandbox copy of the target,
for both additions and substitutions? Produce a strategy matrix, not code.

## Lines of inquiry

- Dependency swap: finding and rewriting manifests (`pyproject.toml`,
  `requirements*.txt`, setup.cfg), deleting replaced hand-rolled code.
- Vendoring: when the wheel is small or unmaintained — copy, attribute, isolate.
- Adapter/shim: attw-written glue between target call-sites and the wheel's API.
- Detecting hand-rolled code worth replacing (imports of stdlib-only helpers,
  duplicated patterns) vs code to leave alone.
- Tidy bar: formatted + lint-clean minimum; is typecheck (mypy/pyright)
  realistic as part of "tidy"?
- Safety rails inside the sandbox: install isolation (venv per run?),
  what the implementer may never do (touch original, push, exfiltrate).
- Failure modes: wheel doesn't install, API doesn't fit, tests break —
  what each maps to downstream (retry with next-ranked wheel? record?).

## Done-criteria

Findings captured below; a strategy matrix (addition vs substitution × wheel
shape) with the recommended default per cell, ready to drive the architecture
ticket. No implementation.

## Research notes

Findings (research subagent, 2026-09-09 — for resolution, not resolved):

**Dep-swap**: canonical target `pyproject.toml` (PEP 621) first; fallbacks
`setup.cfg` → `setup.py` (parse, don't execute) → `requirements*.txt`. Pin
`name>=low,<high` from evidence; never rewrite build backend. Substitution
also deletes replaced modules + prunes orphaned deps; record manifest diff.

**Vendoring**: anti-pattern for libraries; valid only for app targets or dead
wheels. When justified (small, pure-Python, unmaintained): copy to
`_vendored/<wheel>/`, rewrite imports, add ATTRIBUTION, pin version. Never
vendor C-extension wheels. Default: dep-swap wins unless dead AND small AND
pure-Python.

**Adapter/shim**: expected common case — one thin `_attw_<wheel>_adapter.py`
exposing old signatures, backed by the wheel. Minimal call-site churn,
revertible.

**Replace signals**: stdlib-only util modules, duplicated helpers,
wheel-shaped names (slugify, retry, deep_merge), untested edge cases.
**Leave-alone**: business logic, framework-coupled code, perf-tuned paths,
extensively tested bespoke code. Doubt → addition, not substitution.

**Tidy bar**: enforce `ruff check` + `ruff format --check` on touched files.
Typecheck (pyright/mypy) as gate: NO — arbitrary targets are half-untyped.
Optional advisory pyright on touched files only.

**Sandbox rails**: `tempfile.mkdtemp(prefix="attw-")`, assert path prefix on
every write; original read-only. One venv per run (`uv`, fallback venv);
install target editable + wheel into sandbox venv only. Never: write outside
sandbox, push/publish, exfiltrate creds, run setup.py directly.

**Failures → downstream**: bad install → try next-ranked wheel (max 2
fallbacks), else record `implement: failed-install`, stop that component.
API mismatch → one adapter attempt, else `implement: api-mismatch`, revert,
keep ranking as evidence. Regressions vs baseline → revert snapshot, record
`implement: regression` (keep-yours evidence). Never silently edit target
tests to fit.

**Strategy matrix**: Addition — maintained lib: dep-swap direct;
small/unmaintained: vendor + attribute; API-mismatched: dep-swap + thin
adapter. Substitution — maintained: dep-swap + delete + prune; vendored:
vendored copy replaces in place; mismatched: adapter-first, delete old body
only if adapter + tests green, else keep-yours.

**Open for architecture**: (1) fallback depth 2 or 1? (2) may implementer
delete old modules, or adapter-wrap and let verify/Luke confirm? (3) which
licenses force dep-swap-or-skip over vendoring? (4) who owns baseline capture,
implement or verify? (5) adapter LOC cap before it flips to api-mismatch?
