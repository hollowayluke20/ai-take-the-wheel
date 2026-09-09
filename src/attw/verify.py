"""Verify stage: before/after protocol proving improvement.

Harness design per ticket 04 ``## Proposal`` (harness-owned baseline capture,
nodeid-keyed 4-bucket diff, ``verify.json`` per run, ordered 7-step gate,
authored-test adequacy, benchmark sub-protocol, JSONL heartbeat + 20-min
stall default); paths/schema per ticket 05 Decision D4 (full copies under
``database/<run-id>/verify/``, never pointers).

Ownership boundary (04 Proposal L105-111): the harness OWNS the pytest
invocation. :func:`run_suite` is the only verdict-grade capture;
:mod:`attw.implement` calls it pre- and post-change and never runs its own
pytest for verdict purposes.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import platform
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from importlib import metadata as _metadata
from pathlib import Path

from attw.failures import make_failure

# ---------------------------------------------------------------------------
# Constants (04 Proposal sections 1/5/6).
# ---------------------------------------------------------------------------

#: Single global stall-silence default: no heartbeat line for 20 min means
#: the run is `stalled` — abort that run only, loop moves on.
STALL_SILENCE_S = 20 * 60

#: Per-session pytest cap so a hung suite trips before the 20-min watchdog.
#: Benchmark legs get a longer cap (15 min).
PYTEST_TIMEOUT_S = 10 * 60
BENCH_TIMEOUT_S = 15 * 60

#: Exact harness-owned flags appended to every capture invocation.
HARNESS_FLAGS = ("--json-report", "-p", "no:cacheprovider")

#: Heartbeat events, one JSONL line each (04 Proposal section 5).
HEARTBEAT_EVENTS = (
    "run_started",
    "understand_emitted",
    "find_candidate",
    "evidence_cell",
    "rank_done",
    "report_done",
    "implement_file",
    "test_node",
    "benchmark_round",
    "stage_finished",
    "run_finished",
)

#: Gate verdicts.
VERDICTS = ("better", "keep-yours", "fail", "stalled")

#: pytest-json-report outcomes treated as red.
_BAD = {"failed", "error"}
_PASS = "passed"

#: Exit-code semantics (04 Proposal section 1): 0 = all pass; 1 = tests
#: failed (valid verdict input); 2/3/4 = interrupted/usage/collection error
#: (verdict `fail`); 5 = no tests collected (harness failure — never a pass,
#: never keep-yours).
_EXIT_MEANING = {
    0: "ok",
    1: "tests-failed",
    2: "interrupted",
    3: "usage-error",
    4: "collection-error",
    5: "no-tests",
}


class VerifyError(Exception):
    """Harness failure carrying a ``failures.py`` record (downstream-only)."""

    def __init__(self, reason: str, *, code: str = "not_applicable",
                 detail: str = "", run_id: str = "",
                 component: str = "") -> None:
        super().__init__(f"verify: {code}: {reason}")
        self.failure = make_failure("verify", code, reason, detail=detail,
                                    run_id=run_id, component=component)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 04 Proposal section 2: nodeid-keyed 4-bucket diff.
# ---------------------------------------------------------------------------

def _normalize_nodeid(nodeid: str) -> str:
    """Strip sandbox-run prefixes so baseline/after nodeids join.

    ``pytest-json-report`` nodeids look like ``path/to/test_x.py::Test::t``;
    absolute sandbox prefixes (``C:/.../attw-abc/test_x.py::t``) would break
    the join, so the file segment is reduced to its basename.
    """
    node = str(nodeid).replace("\\", "/")
    if "::" in node:
        head, rest = node.split("::", 1)
        head = head.rsplit("/", 1)[-1]
        return f"{head}::{rest}"
    return node.rsplit("/", 1)[-1]


def diff_results(
    baseline: dict[str, str],
    after: dict[str, str],
    removed_reasons: dict[str, str] | None = None,
) -> dict:
    """Nodeid-keyed diff of {nodeid: outcome} maps into 4 buckets.

    fixed: fail/error -> pass. regressed: pass -> fail/error/skip
    (gate-killer, 04 Proposal L115). new: nodeid only in after.
    removed: nodeid only in baseline, each carrying a reason string
    (empty reason = unexplained = treated as hidden regression).
    """
    reasons = removed_reasons or {}
    base = {_normalize_nodeid(k): v for k, v in baseline.items()}
    aft = {_normalize_nodeid(k): v for k, v in after.items()}
    fixed: list[str] = []
    regressed: list[str] = []
    for node in set(base) & set(aft):
        before, now = base[node], aft[node]
        if before in _BAD and now == _PASS:
            fixed.append(node)
        elif before == _PASS and (now in _BAD or now == "skipped"):
            regressed.append(node)
    new = sorted(set(aft) - set(base))
    removed = sorted(set(base) - set(aft))
    return {
        "fixed": sorted(fixed),
        "regressed": sorted(regressed),
        "new": new,
        "removed": [
            {"nodeid": node, "reason": reasons.get(node, "")} for node in removed
        ],
    }


def decide_verdict(diff: dict, after_outcomes: dict[str, str]) -> str:
    """Ordered gate: fail | better | keep-yours (04 Proposal L119-126).

    Zero regressed, absolute; unexplained removed fails; improvement is
    >=1 fixed or >=1 passing new node (benchmark leg lands with the real
    harness — overlapping/no benchmark means no claim from that leg).
    """
    if diff["regressed"]:
        return "fail"
    if any(not entry["reason"] for entry in diff["removed"]):
        return "fail"
    new_gain = any(after_outcomes.get(n) == _PASS for n in diff["new"])
    if len(diff["fixed"]) >= 1 or new_gain:
        return "better"
    return "keep-yours"


# ---------------------------------------------------------------------------
# Answer-key loader (verify keys extend known_answers per 04 Rulings).
# ---------------------------------------------------------------------------

_RUN_TYPES = {"win", "hard", "keep-yours"}
_MODES = {"red_to_green", "new_capability", "measured_gain", "keep_yours"}
_BASE_REQUIRED = ("problem", "accepted_answers", "sources", "researched_on", "notes")
_EXT_REQUIRED = ("input", "expected_wheels", "run_type", "better_spec", "verify")


def load_answer_key(path: str | Path) -> dict:
    """Load and validate a known_answers JSON file (base + per-run extension).

    Base fields always required. Extension fields required as a group: if
    any is present, all five must be present and inner rules hold
    (run_type/mode enums; keep_yours needs tests == [] and benchmark null).
    Raises ValueError on any violation. No network, file read only.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in _BASE_REQUIRED:
        if key not in data or data[key] is None:
            raise ValueError(f"Answer key {path}: missing required field {key!r}")
    if not data["accepted_answers"]:
        raise ValueError(f"Answer key {path}: accepted_answers must be non-empty")
    for url in data["sources"]:
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"Answer key {path}: bad source URL {url!r}")
    present = [k for k in _EXT_REQUIRED if k in data]
    if present and len(present) != len(_EXT_REQUIRED):
        missing = sorted(set(_EXT_REQUIRED) - set(present))
        raise ValueError(f"Answer key {path}: partial extension, missing {missing}")
    if present:
        if data["input"]["kind"] not in ("repo_url", "idea_text"):
            raise ValueError(f"Answer key {path}: bad input.kind")
        if not data["input"]["value"]:
            raise ValueError(f"Answer key {path}: empty input.value")
        if data["run_type"] not in _RUN_TYPES:
            raise ValueError(f"Answer key {path}: bad run_type")
        spec = data["better_spec"]
        if spec["mode"] not in _MODES:
            raise ValueError(f"Answer key {path}: bad better_spec.mode")
        if spec["mode"] == "keep_yours" and (
            spec["tests"] != [] or spec["benchmark"] is not None
        ):
            raise ValueError(f"Answer key {path}: keep_yours needs tests [] + null")
        if not data["verify"]["test_command"]:
            raise ValueError(f"Answer key {path}: empty verify.test_command")
        if data["verify"]["zero_regressions"] is not True:
            raise ValueError(f"Answer key {path}: zero_regressions must be true")
    return data


# ---------------------------------------------------------------------------
# 04 Proposal section 1: harness-owned baseline capture.
# ---------------------------------------------------------------------------

def _extra_args(test_command: str) -> list[str]:
    """Target args recorded verbatim, minus any leading pytest invocation.

    Accepts ``"pytest -q tests"`` or ``"python -m pytest -q tests"``; the
    harness prepends its own interpreter + exact flags, so a leading
    ``pytest`` / ``python -m pytest`` is stripped. Harness-owned
    ``--json-report*`` flags in the input are dropped (the harness appends
    its own pointing at the run dir).
    """
    tokens = shlex.split(test_command or "")
    if tokens[:3] == ["python", "-m", "pytest"]:
        tokens = tokens[3:]
    elif tokens[:1] == ["pytest"]:
        tokens = tokens[1:]
    return [t for t in tokens
            if t != "--json-report" and not t.startswith("--json-report-file")]


def _sandbox_python(sandbox_dir: Path) -> str:
    """Sandbox venv python when present, else the current interpreter."""
    if (sandbox_dir / ".venv" / "Scripts" / "python.exe").is_file():
        return str(sandbox_dir / ".venv" / "Scripts" / "python.exe")
    if (sandbox_dir / ".venv" / "bin" / "python").is_file():
        return str(sandbox_dir / ".venv" / "bin" / "python")
    return sys.executable


def _ensure_json_report(python: str, sandbox_dir: Path) -> None:
    """Ensure ``pytest-json-report`` importable by the suite python.

    Allowed as a sandbox dependency (04 Rulings). Installs only when the
    import probe fails; raises VerifyError when the install fails.
    """
    probe = subprocess.run(
        [python, "-c", "import pytest_jsonreport"],
        capture_output=True, text=True, timeout=120,
    )
    if probe.returncode == 0:
        return
    proc = subprocess.run(
        [python, "-m", "pip", "install", "pytest-json-report"],
        cwd=str(sandbox_dir), capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        raise VerifyError(
            "could not install pytest-json-report into the sandbox",
            code="not_applicable",
            detail=(proc.stderr or "")[-2000:],
        )


def fingerprint(sandbox_dir: str | Path, test_command: str = "",
                authored_tests: list[str] | tuple[str, ...] = ()) -> dict:
    """Environment fingerprint stored in ``verify.json:fingerprint``."""
    root = Path(sandbox_dir)
    try:
        pytest_version = _metadata.version("pytest")
    except Exception:
        pytest_version = "unknown"
    try:
        freeze = subprocess.run(
            [_sandbox_python(root), "-m", "pip", "freeze"],
            capture_output=True, text=True, timeout=120,
        ).stdout
    except Exception:
        freeze = ""
    freeze_sha = (hashlib.sha256(freeze.encode("utf-8")).hexdigest()
                  if freeze else "unknown")
    try:
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=60,
        ).stdout.strip() or "unknown"
    except Exception:
        sha = "unknown"
    return {
        "python_version": platform.python_version(),
        "pytest_version": pytest_version,
        "pip_freeze_sha": freeze_sha,
        "platform": platform.platform(),
        "target_git_sha": sha,
        "authored_tests": list(authored_tests),
        "test_command": test_command,
    }


def parse_report(report_path: str | Path) -> dict:
    """Parse a ``pytest-json-report`` file into outcomes + summary.

    Returns ``{"outcomes": {nodeid: outcome}, "summary": {"passed",
    "failed", "total"}, "exit_code"}`` (``exit_code`` from the report's
    ``exitcode`` key when present, else None). Raises VerifyError when the
    file is missing or unparseable.
    """
    path = Path(report_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VerifyError(f"report not found: {path}",
                          code="not_applicable") from exc
    except (json.JSONDecodeError, OSError) as exc:
        raise VerifyError(f"report unparseable: {path}",
                          code="not_applicable",
                          detail=str(exc)[:1000]) from exc
    tests = data.get("tests", data.get("test_results", []))
    outcomes: dict[str, str] = {}
    if isinstance(tests, list):
        for entry in tests:
            if not isinstance(entry, dict):
                continue
            node = entry.get("nodeid") or entry.get("name")
            outcome = entry.get("outcome") or entry.get("status")
            if node and outcome:
                outcomes[_normalize_nodeid(str(node))] = str(outcome)
    elif isinstance(tests, dict):
        outcomes = {_normalize_nodeid(str(k)): str(v)
                    for k, v in tests.items()}
    summary = data.get("summary", {})
    if isinstance(summary, dict) and "total" not in summary:
        passed = int(summary.get("passed", 0))
        failed = int(summary.get("failed", 0))
        error = int(summary.get("error", 0))
        summary = {"passed": passed, "failed": failed + error,
                   "total": passed + failed + error}
    exit_code = data.get("exitcode", data.get("exit_code"))
    return {"outcomes": outcomes, "summary": summary, "exit_code": exit_code}


def classify_exit(exit_code: int) -> str:
    """Exit-code semantics: ok | tests-failed | interrupted | usage-error |
    collection-error | no-tests. Exit 5 (no tests) is a harness failure —
    never a pass, never keep-yours."""
    return _EXIT_MEANING.get(int(exit_code), "unknown")


def append_heartbeat(run_dir: str | Path, stage: str, event: str,
                     detail: str = "") -> Path:
    """Append one JSONL heartbeat line under ``<run_dir>/verify/``."""
    if event not in HEARTBEAT_EVENTS:
        raise ValueError(f"Unknown heartbeat event: {event!r} "
                         f"(expected one of {HEARTBEAT_EVENTS})")
    verify_dir = Path(run_dir) / "verify"
    verify_dir.mkdir(parents=True, exist_ok=True)
    path = verify_dir / "heartbeat.jsonl"
    line = {"ts": _utcnow(), "stage": str(stage), "event": event,
            "detail": str(detail)}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
    return path


def heartbeat_path(run_dir: str | Path) -> Path:
    """Path of the run's heartbeat file (may not exist yet)."""
    return Path(run_dir) / "verify" / "heartbeat.jsonl"


def is_stalled(run_dir: str | Path,
               timeout_s: int = STALL_SILENCE_S) -> dict:
    """Stall check over the heartbeat mtime.

    Missing heartbeat counts as stalled (gate step 1/7 fails it, never
    passes). Returns ``{"stalled", "silence_s", "reason"}``.
    """
    path = heartbeat_path(run_dir)
    if not path.is_file():
        return {"stalled": True, "silence_s": float(timeout_s),
                "reason": "no heartbeat.jsonl"}
    try:
        silence = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    except OSError as exc:
        return {"stalled": True, "silence_s": float(timeout_s),
                "reason": f"heartbeat unreadable: {exc}"}
    if silence > timeout_s:
        return {"stalled": True, "silence_s": silence,
                "reason": f"silent {silence:.0f}s > {timeout_s}s"}
    return {"stalled": False, "silence_s": silence, "reason": "live"}


def run_suite(
    sandbox_dir: str | Path, test_command: str = "pytest -q", label: str = "baseline",
    *, run_dir: str | Path | None = None, timeout_s: int = PYTEST_TIMEOUT_S,
) -> Path:
    """Run the target suite in the sandbox copy; return the JSON report path.

    The harness OWNS this invocation (04 Proposal L105-111): exact command
    is ``<suite-python> -m pytest --json-report
    --json-report-file=<run_dir>/verify/<label>.json -p no:cacheprovider
    <extra target args>``, run with cwd=sandbox. Exit 1 (tests failed) is
    valid verdict input and returns normally; exit 2/3/4 returns the path
    when a report exists (gate step 5 turns it into ``fail``). Missing
    sandbox, timeouts, and missing/unparseable reports raise VerifyError.
    Emits ``run_started`` + per-node ``test_node`` + ``stage_finished``
    heartbeat lines so silent runs trip ``is_stalled``, never pass silently.
    """
    root = Path(sandbox_dir)
    if not root.is_dir():
        raise VerifyError(f"sandbox not found: {sandbox_dir}",
                          code="not_applicable")
    dest_dir = Path(run_dir) if run_dir is not None else root / "verify"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{label}.json"
    python = _sandbox_python(root)
    _ensure_json_report(python, root)
    cmd = [python, "-m", "pytest", "--json-report",
           f"--json-report-file={dest}", "-p", "no:cacheprovider",
           *_extra_args(test_command)]
    base = dest_dir.parent  # run dir holding verify/
    append_heartbeat(base, "verify", "run_started",
                     f"{label}: {' '.join(cmd)}"[:2000])
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True,
                              text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        append_heartbeat(base, "verify", "stage_finished",
                         f"{label} timed out after {timeout_s}s")
        raise VerifyError(f"pytest timed out after {timeout_s}s ({label})",
                          code="not_applicable",
                          detail=str(exc)[:1000]) from exc
    except OSError as exc:
        raise VerifyError(f"pytest could not start ({label})",
                          code="not_applicable",
                          detail=str(exc)[:1000]) from exc
    try:
        parsed = parse_report(dest)
    except VerifyError as exc:
        append_heartbeat(base, "verify", "stage_finished",
                         f"{label} exit={proc.returncode} no report: "
                         f"{(proc.stderr or '')[-500:]}")
        raise VerifyError(f"{label} produced no parseable report "
                          f"(exit={proc.returncode})",
                          code="not_applicable",
                          detail=(proc.stderr or "")[-2000:]) from exc
    for nodeid, outcome in sorted(parsed["outcomes"].items()):
        append_heartbeat(base, "verify", "test_node", f"{nodeid} {outcome}")
    append_heartbeat(base, "verify", "stage_finished",
                     f"{label} exit={proc.returncode} "
                     f"total={parsed['summary'].get('total', '?')}")
    return dest


# ---------------------------------------------------------------------------
# 04 Proposal section 3-step 4: authored-test adequacy (mechanically checkable).
# ---------------------------------------------------------------------------

#: Name rule: authored tests live apart from the target suite.
AUTHORED_GLOB = "test_attw_*.py"

#: Determinism bans: network clients, wall clocks/sleeps, unseeded randomness.
_ADEQUACY_BANNED = ("urllib", "http.client", "socket", "requests.",
                    "httpx.", "time.time(", "time.sleep(")


def _adequacy_ast(source: str) -> list[str]:
    """AST adequacy checks; returns violation strings (empty = pass)."""
    problems: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"unparseable: {exc}"]
    imports = [n for n in ast.walk(tree)
               if isinstance(n, (ast.Import, ast.ImportFrom))]
    try:
        stdlib = set(sys.stdlib_module_names)
    except AttributeError:  # pragma: no cover - Python < 3.10
        stdlib = set()
    third_party = {n.names[0].name.split(".")[0] if isinstance(n, ast.Import)
                   else (n.module or "").split(".")[0] for n in imports}
    third_party -= {"pytest", "unittest", "unittest.mock", "mock"} | stdlib
    third_party.discard("")
    if imports and not third_party:
        problems.append("no target/wheel import (imports pytest/stdlib only)")
    elif not imports:
        problems.append("no imports at all (must import target/wheel)")
    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    if not asserts:
        problems.append("no assert statements")
    else:
        def _live(node: ast.AST) -> bool:
            return any(isinstance(c, (ast.Name, ast.Attribute, ast.Call,
                                      ast.Subscript))
                       for c in ast.walk(node))

        if not any(_live(a.test) for a in asserts):
            problems.append("asserts are constant-only "
                            "(AST-ban: assert True/literal)")
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            body = [s for s in node.body
                    if not (isinstance(s, ast.Expr)
                            and isinstance(s.value, ast.Constant))]
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                problems.append("try/except: pass swallows failures")
                break
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            func = dec.func if isinstance(dec, ast.Call) else dec
            dotted = ""
            if isinstance(func, ast.Attribute):
                val = func.value
                prefix = ""
                if isinstance(val, ast.Attribute):
                    prefix = f"{getattr(val.value, 'id', '')}." \
                             f"{val.attr}."
                elif isinstance(val, ast.Name):
                    prefix = f"{val.id}."
                dotted = f"{prefix}{func.attr}"
            elif isinstance(func, ast.Name):
                dotted = func.id
            short = dotted.split(".")[-1]
            if short in ("skip", "xfail"):
                if not isinstance(dec, ast.Call) or not dec.args \
                        or all(isinstance(a, ast.Constant) for a in dec.args):
                    problems.append(
                        f"unconditional {short} marker "
                        f"(line {getattr(dec, 'lineno', '?')})")
                    break
    return problems


def check_authored_tests(paths: list[str] | tuple[str, ...],
                         sandbox_dir: str | Path | None = None) -> dict:
    """Mechanically check attw-authored tests (04 Proposal step 4).

    Every path must match ``test_attw_*.py`` (separate from the target
    suite), import the target/wheel (never reimplement logic), carry ≥1
    assert with non-constant operands, avoid ``try/except: pass`` and
    unconditional skip/xfail, and stay deterministic (no network, wall
    clock, or unseeded randomness). Proven value (red→green or coverage of
    wheel-touched lines) is shown by gate step 3 legs, not file-static.
    Returns ``{"ok", "reasons", "checked"}``; empty paths = vacuously ok.
    """
    checked = [str(p) for p in (paths or [])]
    if not checked:
        return {"ok": True, "reasons": [], "checked": []}
    reasons: list[str] = []
    for rel in checked:
        path = (Path(sandbox_dir) / rel) if sandbox_dir else Path(rel)
        if fnmatch.fnmatch(path.name, AUTHORED_GLOB) is False:
            reasons.append(f"{rel}: must match {AUTHORED_GLOB} "
                           f"(separate from target suite)")
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            reasons.append(f"{rel}: unreadable: {exc}")
            continue
        reasons.extend(f"{rel}: {p}" for p in _adequacy_ast(source))
        if any(tok in source for tok in _ADEQUACY_BANNED):
            reasons.append(f"{rel}: non-deterministic/network token "
                           f"(urllib/socket/requests/httpx/wall-clock)")
        if "random." in source and "seed(" not in source:
            reasons.append(f"{rel}: unseeded randomness")
    return {"ok": not reasons, "reasons": reasons, "checked": checked}


# ---------------------------------------------------------------------------
# 04 Proposal section 4: benchmark sub-protocol (clearly-faster-here).
# ---------------------------------------------------------------------------

def evaluate_benchmark(benchmark: dict | None, mode: str = "red_to_green") -> dict:
    """Judge a benchmark leg. Claim ONLY from same-machine before/after
    distributions that do not overlap (``max(after) < min(before)`` for
    faster; mirrored ``min(after) > max(before)`` also claims, e.g. size
    gains recorded as larger-is-better). No fixed % threshold. Overlapping
    or missing benchmark → no claim (never a gate error by itself; gate
    step 3 then needs another leg). ``min_rounds >= 5`` + warmup required
    for any claim. Returns ``{"claim", "reason"}``.
    """
    if benchmark is None:
        return {"claim": False, "reason": "no benchmark leg"}
    if mode != "measured_gain":
        return {"claim": False,
                "reason": f"benchmark ignored: mode is {mode}, "
                          f"not measured_gain"}
    before = list(benchmark.get("before", []) or [])
    after = list(benchmark.get("after", []) or [])
    if not before or not after:
        return {"claim": False, "reason": "empty before/after distributions"}
    if int(benchmark.get("min_rounds", 0)) < 5:
        return {"claim": False, "reason": "min_rounds < 5"}
    if not benchmark.get("warmup", False):
        return {"claim": False, "reason": "warmup off"}
    if max(after) < min(before) or min(after) > max(before):
        return {"claim": True,
                "reason": f"non-overlapping: before "
                          f"[{min(before)}, {max(before)}] vs after "
                          f"[{min(after)}, {max(after)}]"}
    return {"claim": False, "reason": "distributions overlap — no claim"}


# ---------------------------------------------------------------------------
# verify.json assembly + ordered 7-step critic gate.
# ---------------------------------------------------------------------------

def check_sandbox_path(sandbox_dir: str | Path) -> bool:
    """Sandbox-only proxy: the path lives under the system temp dir or
    carries the ``attw-`` run prefix (05 D3: ``tempfile.mkdtemp`` default)."""
    text = str(sandbox_dir)
    try:
        tmp = str(Path(tempfile.gettempdir()).resolve())
        here = str(Path(text).resolve())
        if here == tmp or here.startswith(tmp.rstrip("\\/") + "\\") \
                or here.startswith(tmp.rstrip("/") + "/"):
            return True
    except OSError:
        pass
    return "attw-" in Path(text).parts[-1] if Path(text).parts else False


def build_verify(
    *,
    fingerprint: dict,
    baseline: dict,
    after: dict,
    removed_reasons: dict[str, str] | None = None,
    authored_paths: list[str] | tuple[str, ...] = (),
    adequacy: dict | None = None,
    benchmark: dict | None = None,
    mode: str = "red_to_green",
    sandbox_dir: str | Path = "",
    heartbeat: dict | None = None,
) -> dict:
    """Assemble a ``verify.json`` dict from capture artifacts (pure).

    ``baseline``/``after`` are ``parse_report`` dicts extended with
    ``path`` + ``exit_code`` (subprocess returncode wins over the report's
    ``exitcode`` key when both exist). Runs the adequacy check (unless an
    ``adequacy`` result is supplied), the benchmark judge, the 4-bucket
    diff, and the ordered gate; stores the gate verdict.
    """
    base_out = {str(k): str(v)
                for k, v in baseline.get("outcomes", {}).items()}
    aft_out = {str(k): str(v) for k, v in after.get("outcomes", {}).items()}
    diff = diff_results(base_out, aft_out, removed_reasons)
    bench = evaluate_benchmark(benchmark, mode)
    if adequacy is None:
        adequacy = (check_authored_tests(list(authored_paths))
                    if authored_paths
                    else {"ok": True, "reasons": [],
                          "checked": []})
    base_block = {"path": str(baseline.get("path", "")),
                  "exit_code": baseline.get("exit_code"),
                  "summary": baseline.get("summary", {})}
    after_block = {"path": str(after.get("path", "")),
                   "exit_code": after.get("exit_code"),
                   "summary": after.get("summary", {})}
    heart = dict(heartbeat or {"present": False, "stalled": True,
                               "reason": "no heartbeat attached"})
    data = {
        "fingerprint": fingerprint,
        "test_command": fingerprint.get("test_command", ""),
        "sandbox_dir": str(sandbox_dir),
        "baseline": base_block,
        "after": after_block,
        "diff": diff,
        "authored": {"paths": list(authored_paths), "adequacy": adequacy},
        "benchmark": ({"before": benchmark.get("before"),
                       "after": benchmark.get("after"),
                       "min_rounds": benchmark.get("min_rounds"),
                       "warmup": benchmark.get("warmup"),
                       **bench} if benchmark is not None else None),
        "heartbeat": heart,
        "mode": mode,
        "verdict": "fail",
        "gate": {},
    }
    gate = evaluate_gate(data)
    data["verdict"] = gate["verdict"]
    data["gate"] = gate
    return data


def evaluate_gate(data: dict) -> dict:
    """Ordered 7-step critic gate (04 Proposal section 3).

    Top-to-bottom, first failure decides. Returns ``{"verdict",
    "failed_step", "reasons"}``; ``failed_step`` is None on pass
    (``better``) or principled ``keep-yours``.
    """
    reasons: list[str] = []

    def _fail(step: int, verdict: str, why: str) -> dict:
        reasons.append(f"step {step}: {why}")
        return {"verdict": verdict, "failed_step": step, "reasons": reasons}

    # Step 1: verify.json + both raw reports + heartbeat present, parseable.
    for key in ("fingerprint", "baseline", "after", "diff", "heartbeat"):
        if key not in data or data[key] is None:
            return _fail(1, "fail", f"missing verify.json section {key!r}")
    for side in ("baseline", "after"):
        block = data[side] or {}
        if block.get("exit_code") is None or not isinstance(
                block.get("summary"), dict):
            return _fail(1, "fail", f"{side} report missing exit_code/summary")
    diff = data["diff"] or {}
    for key in ("fixed", "regressed", "new", "removed"):
        if key not in diff:
            return _fail(1, "fail", f"diff missing bucket {key!r}")

    # Step 2: zero regressed, absolute; removed must be explained.
    if diff["regressed"]:
        return _fail(2, "fail",
                     f"regressed (gate-killer): {sorted(diff['regressed'])}")
    unexplained = [e["nodeid"] for e in diff["removed"] if not e.get("reason")]
    if unexplained:
        return _fail(2, "fail",
                     f"unexplained removed (hidden regression): {unexplained}")

    # Step 3: improvement is exactly one leg, else keep-yours.
    after_outcomes: dict[str, str] = {}
    if isinstance(data.get("after"), dict):
        after_outcomes = {str(k): str(v) for k, v in
                          (data["after"].get("outcomes") or {}).items()}
    new_gain = [n for n in diff["new"] if after_outcomes.get(n) == _PASS]
    bench = data.get("benchmark") or {}
    bench_claim = bool(bench.get("claim")) and data.get("mode") == "measured_gain"
    mode = data.get("mode", "red_to_green")
    verdict = "better"
    if mode == "keep_yours":
        gains = diff["fixed"] or new_gain or bench_claim
        if gains or data.get("benchmark") is not None:
            return _fail(3, "fail",
                         "keep_yours mode with gains/benchmark present")
    elif not (diff["fixed"] or new_gain or bench_claim):
        # Provisional keep-yours, NOT an early return: exit-5, sandbox and
        # stall steps must still fire ("exit 5 never passes", "silent runs
        # never passed"). keep-yours is not a failure, so later failures
        # still decide first-failure-wins.
        verdict = "keep-yours"
        reasons.append("step 3: no improvement leg — keep-yours unless a "
                       "later step fails")

    # Step 4: authored-test adequacy when authored_tests non-empty.
    authored = data.get("authored") or {}
    adequacy = authored.get("adequacy") or {}
    if authored.get("paths") and not adequacy.get("ok", False):
        return _fail(4, "fail",
                     f"authored-test adequacy: {adequacy.get('reasons', [])}")

    # Step 5: exit-code semantics; exit 5 never passes.
    for side in ("baseline", "after"):
        code = (data[side] or {}).get("exit_code")
        meaning = classify_exit(code) if code is not None else "unknown"
        if meaning == "no-tests":
            return _fail(5, "fail",
                         f"{side} exit 5 (no tests collected) — harness "
                         f"failure, never a pass")
        if meaning not in ("ok", "tests-failed"):
            return _fail(5, "fail",
                         f"{side} exit={code} ({meaning}) — fail, "
                         f"stderr recorded")

    # Step 6: sandbox-only + gain claims cite verify.json cells.
    if not check_sandbox_path(data.get("sandbox_dir", "")):
        return _fail(6, "fail",
                     f"sandbox-only violated: {data.get('sandbox_dir', '')!r}")
    if verdict == "better" and not (data.get("test_command")):
        return _fail(6, "fail", "gain claim without recorded test_command")

    # Step 7: heartbeat attached; silent runs are stalled, never passed.
    heart = data.get("heartbeat") or {}
    if heart.get("stalled", True):
        return _fail(7, "stalled",
                     f"heartbeat: {heart.get('reason', 'stalled')}")
    reasons.append("steps 1-7 pass")
    return {"verdict": verdict, "failed_step": None, "reasons": reasons}


def write_verify_json(dest_dir: str | Path, data: dict) -> Path:
    """Write ``verify.json`` (full copy, 05 D4/D10) into ``dest_dir``."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "verify.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def check(verify_json_path: str | Path) -> str:
    """Standalone critic gate over a ``verify.json`` file.

    Returns a one-line ``"verify: <verdict> ..."`` string (read-only; never
    rewrites the file). Raises VerifyError when the file is missing or
    unparseable.
    """
    path = Path(verify_json_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VerifyError(f"verify.json not found: {path}",
                          code="not_applicable") from exc
    except (json.JSONDecodeError, OSError) as exc:
        raise VerifyError(f"verify.json unparseable: {path}",
                          code="not_applicable",
                          detail=str(exc)[:1000]) from exc
    if not isinstance(data, dict):
        raise VerifyError(f"verify.json must hold an object: {path}",
                          code="not_applicable")
    gate = evaluate_gate(data)
    verdict = gate["verdict"]
    detail = "; ".join(gate["reasons"])[:2000]
    diff = data.get("diff", {}) if isinstance(data.get("diff"), dict) else {}
    cells = (f"fixed={len(diff.get('fixed', []))} "
             f"regressed={len(diff.get('regressed', []))} "
             f"new={len(diff.get('new', []))} "
             f"removed={len(diff.get('removed', []))}")
    step = f"step {gate['failed_step']}" if gate["failed_step"] else "steps 1-7"
    return f"verify: {verdict} ({step}; {cells}; {detail})"
