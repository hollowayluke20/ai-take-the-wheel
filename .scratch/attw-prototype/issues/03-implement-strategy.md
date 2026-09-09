# 03 — Implement strategy: getting the wheel into the copy

Status: resolved

## Answer

Implement spec decided (`## Proposal`, lines 93–175): full strategy matrix
with per-cell defaults; manifest order pyproject → setup.cfg → setup.py-parse
→ requirements with `>=low,<high` pins; deletion outright in sandbox with
manifest-diff + deleted-paths + snapshot record; thin-adapter rules with no
LOC cap (3 critic proportionality criteria); tidy = ruff enforced,
typecheck advisory; sandbox protocol (mkdtemp, prefix assert, 1 venv/run);
exact failure strings, all downstream-only. Critic: PASS.
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

## Rulings (Luke, 2026-09-09, pre-build review)

- 2 fallbacks to next-ranked wheels, then stop.
- Deletion allowed outright: sandbox copy anyway, Luke keeps originals. No
  adapter-wrap-first requirement — delete replaced modules directly.
- GPL-family: dep-swap-or-skip, never vendor. Confirmed.
- Verify harness owns baseline capture; implement calls it.
- NO adapter LOC cap — blanket rule rejected. Critic judges adapter
  proportionality per case.

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

## Proposal (implement spec)

DECIDED — resolves all 5 open questions above per Luke's 2026-09-09 rulings.
Architecture ticket consumes this as-is; remaining gaps are §6 only.

### 1. Strategy matrix (defaults, not options)

| | Well-maintained lib | Small + unmaintained (dead AND small AND pure-Python) | API-mismatched lib |
|---|---|---|---|
| **Addition** | dep-swap direct: add pin, import at call-site, no adapter | vendor+attribute: copy to `_vendored/<wheel>/`, rewrite imports, add ATTRIBUTION + version pin | dep-swap + thin adapter (one `_attw_<wheel>_adapter.py`) |
| **Substitution** | dep-swap + delete + prune orphans | vendor+attribute replacing in place | adapter-first: keep old module until adapter + tests green, then delete old body |

Rules: doubt → addition, never substitution. Never vendor C-extension wheels.
Never rewrite build backend. Default is dep-swap unless all three vendor
conditions hold. Detect replace-worthy: stdlib-only util modules, duplicated
helpers, wheel-shaped names (slugify/retry/deep_merge), untested edge cases.
Leave-alone: business logic, framework-coupled code, perf-tuned paths,
extensively tested bespoke code.

Manifest edit order (first present wins, record diff): `pyproject.toml`
(PEP 621) → `setup.cfg` → `setup.py` (parse only, never execute/run) →
`requirements*.txt`. Pin form `name>=low,<high` from evidence.

Deletion authority (Luke ruling): deletion allowed outright in sandbox — no
adapter-wrap-first requirement. Deletes: replaced hand-rolled modules +
orphaned dep entries. Record kept: manifest diff + deleted paths list +
revert snapshot; original target outside sandbox never touched.

### 2. Adapter rules

Single file per wheel: `_attw_<wheel>_adapter.py` at target root (or beside
replaced module if target is a package). May contain only: old-signature
functions delegating to the wheel, import rewrites, minimal arg/kwarg
mapping, and wheel exception translation. No business logic, no new
features, call-site churn minimal, fully revertible (delete adapter +
restore snapshot).

NO LOC cap per Luke ruling. Critic judges proportionality instead:
(a) adapter exposes only signatures the target already called,
(b) each wrapper is thin delegation (no reimplemented wheel logic),
(c) deletion of old body allowed only if adapter + full test suite green,
else keep-yours. Oversized/non-delegating adapter = `implement: api-mismatch`.

### 3. Tidy bar

Enforced gate on touched files only: `python -m ruff check <touched>` and
`python -m ruff format --check <touched>` must both exit 0. Typecheck
advisory-only: `pyright` (fallback `mypy`) run on touched files only;
stdout recorded in run record, never a gate — arbitrary targets are
half-untyped, so type errors warn but do not fail.

### 4. Sandbox protocol

`tempfile.mkdtemp(prefix="attw-")` throwaway copy; every write asserts the
resolved path is prefixed by the sandbox root; original target mounted
read-only conceptually (never written). One venv per run: `uv venv` then
fallback `python -m venv`; install target editable + winner wheel into
sandbox venv only. Network-for-installs-only (PyPI/GitHub fetch +
`pip install`); no other egress. Never: write outside sandbox, touch
original, push/publish, exfiltrate creds/secrets, run `setup.py` directly.
Snapshot sandbox before mutation for revert.

### 5. Failure mapping (downstream-only per map; never silently edit target tests)

- Bad install → try next-ranked wheel, max 2 fallbacks, else record
`implement: failed-install`, stop that component.
- API-mismatch after one adapter attempt → revert to snapshot, record
`implement: api-mismatch`, keep ranking as evidence.
- Regressions vs verify-owned baseline → revert snapshot, record
`implement: regression` (keep-yours evidence). Implement calls verify's
baseline capture; it never owns it.
- GPL-family wheel → dep-swap-or-skip only, never vendor; mismatch with
target license = prose warning, never veto unless GPL-vendor case, then skip.

### 6. Residual open questions (for architecture ticket)

1. Where does the per-run record (manifest diff, adapter path, tidy/typecheck
outputs, failure string) live — `database/` run JSON extension or separate
implement receipt?
2. Who invokes the snapshot/revert primitive — shared sandbox helper owned by
implement or verify?
3. Adapter placement convention for src-layout vs flat-layout targets
(root file vs inside package)?
