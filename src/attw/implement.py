"""Implement stage: integrate the winning wheel into a sandbox copy.

Strategy matrix, manifest order, deletion authority, adapter rules, tidy bar,
sandbox protocol and failure strings per 03 Proposal. Built by ticket 12.

Boundary (04/05): implement CALLS the verify harness baseline capture
(``verify.run_suite``); the harness owns it — implement never runs its own
pytest for verdict purposes.
"""

from __future__ import annotations

import ast
import difflib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from attw import verify
from attw.failures import make_failure

# Manifest edit order, first present wins (03 Proposal L122-124).
_MANIFEST_ORDER = ("pyproject.toml", "setup.cfg", "setup.py")


def choose_manifest(present: list[str]) -> str | None:
    """Pick the manifest to edit from files present in the target.

    Order: pyproject.toml -> setup.cfg -> setup.py (parse only, never
    execute) -> requirements*.txt. Returns None when no manifest found.
    """
    for name in _MANIFEST_ORDER:
        if name in present:
            return name
    reqs = sorted(
        p for p in present if p.startswith("requirements") and p.endswith(".txt")
    )
    return reqs[0] if reqs else None


def adapter_path(layout: str, wheel: str, package: str | None = None) -> str:
    """Adapter file location for one wheel (03 Decision D11).

    Flat-layout target: repo-root `_attw_<wheel>_adapter.py`. Src-layout:
    inside the package (`src/<package>/_attw_<wheel>_adapter.py`).
    """
    filename = f"_attw_{wheel}_adapter.py"
    if layout == "flat":
        return filename
    if layout == "src":
        if not package:
            raise ValueError("src layout needs a package name")
        return f"src/{package}/{filename}"
    raise ValueError(f"Unknown layout: {layout!r} (expected 'flat' or 'src')")


# ---------------------------------------------------------------------------
# Plan: matrix cell per 03 Proposal section 1.
# ---------------------------------------------------------------------------

_GPL_RE = re.compile(r"(^|[^a-z])(gpl|agpl|gnu general public license)", re.I)


def _is_gpl(license: str) -> bool:
    """True for GPL-family licenses (dep-swap-or-skip, never vendor)."""
    return bool(_GPL_RE.search(license or ""))


def _format_pin(wheel: str, low: str | None, high: str | None) -> str:
    """Pin form `name>=low,<high` from evidence (03 Proposal L122-126)."""
    if low and high:
        return f"{wheel}>={low},<{high}"
    if low:
        return f"{wheel}>={low}"
    if high:
        return f"{wheel}<{high}"
    return wheel


def plan(component: dict, winner: dict, mode: str = "auto") -> dict:
    """Choose the matrix cell (dep-swap / vendor / adapter) for a component.

    mode: auto | addition-only | substitution-only. Doubt -> addition, never
    substitution. Default is dep-swap unless all three vendor conditions
    hold (dead AND small AND pure-Python); never vendor C-extension wheels;
    never rewrite the build backend. GPL-family forces dep-swap-or-skip.
    """
    if mode not in ("auto", "addition-only", "substitution-only"):
        raise ValueError(f"Unknown mode: {mode!r}")
    comp = dict(component or {})
    win = dict(winner or {})
    kind = comp.get("kind", "unknown")
    if mode == "addition-only":
        kind = "addition"
    elif mode == "substitution-only":
        kind = "substitution"
    elif kind not in ("addition", "substitution"):
        kind = "addition"  # doubt -> addition, never substitution
    wheel = str(
        win.get("wheel") or win.get("name") or comp.get("component") or "unknown"
    )
    dead = bool(win.get("dead", False))
    small = bool(win.get("small", False))
    pure = bool(win.get("pure_python", True))
    cext = bool(win.get("c_extension", False))
    mismatch = bool(win.get("api_mismatch", win.get("adapter_needed", False)))
    license = str(win.get("license", ""))
    gpl = _is_gpl(license)
    vendor_ok = dead and small and pure and not cext
    license_warning = ""
    if mismatch:
        strategy = "adapter"
    elif vendor_ok and not gpl:
        strategy = "vendor"
    else:
        strategy = "dep-swap"
    if gpl and vendor_ok:
        license_warning = (
            f"GPL-family wheel {wheel!r}: dep-swap-or-skip, never vendor "
            "(03 Proposal). Target-license mismatch is a prose warning."
        )
    if strategy == "adapter" and gpl:
        license_warning = license_warning or (
            f"GPL-family wheel {wheel!r}: adapter over GPL code — "
            "dep-swap-or-skip; check target license compatibility."
        )
    low = win.get("version_low") or win.get("low")
    high = win.get("version_high") or win.get("high")
    pypi_url = win.get("pypi_url") or f"https://pypi.org/project/{wheel}/"
    fallbacks = list(win.get("fallbacks", []) or [])
    deletes = list(comp.get("replaces", []) or win.get("replaces", []) or [])
    return {
        "component": comp.get("component")
        or comp.get("name")
        or comp.get("problem", ""),
        "wheel": wheel,
        "import_name": win.get("import_name") or wheel.replace("-", "_"),
        "kind": kind,
        "strategy": strategy,
        "manifest": win.get("manifest"),  # None = first-present-wins at apply
        "pin": _format_pin(wheel, low, high),
        "version_low": low,
        "version_high": high,
        "fallbacks": fallbacks,  # next-ranked wheels; apply tries max 2
        "delete": deletes,  # replaced hand-rolled modules, sandbox only
        "adapter_funcs": win.get("adapter_funcs") or ["main"],
        "exception_map": dict(win.get("exception_map", {}) or {}),
        "adapter_valid": win.get("adapter_valid", True),
        "layout": win.get("layout", "flat"),
        "package": win.get("package"),
        "license": license,
        "pypi_url": pypi_url,
        "c_extension": cext,
        "pure_python": pure,
        "dead": dead,
        "small": small,
        "vendor_source": win.get("vendor_source"),
        "license_warning": license_warning,
        "mode": mode,
    }


# ---------------------------------------------------------------------------
# Sandbox protocol (03 Proposal section 4).
# ---------------------------------------------------------------------------


def make_sandbox(original: str | Path | None = None) -> str:
    """Create a throwaway sandbox copy under the system temp dir.

    `tempfile.mkdtemp(prefix="attw-")`; when `original` is given its tree
    is copied in. The original is never written, only read.
    """
    path = tempfile.mkdtemp(prefix="attw-")
    if original is not None:
        shutil.copytree(str(original), path, dirs_exist_ok=True)
    return path


def _inside(root: Path, rel: str) -> Path:
    """Resolve `rel` against `root`, asserting the sandbox prefix.

    Every write goes through here; paths escaping the sandbox raise
    ValueError and nothing is written.
    """
    target = (root / rel).resolve()
    resolved = root.resolve()
    if target != resolved and resolved not in target.parents:
        raise ValueError(f"write outside sandbox blocked: {rel!r}")
    return target


def _write_inside(root: Path, rel: str, content: str) -> Path:
    """Write a file inside the sandbox (prefix-asserted)."""
    target = _inside(root, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def snapshot(sandbox_dir: str) -> str:
    """Record a revert snapshot of the sandbox before mutation.

    Copies the tree (minus `.venv`) to a temp dir; returns its path as the
    snapshot id. The pre-change snapshot is the revert basis for
    api-mismatch / regression.
    """
    root = Path(sandbox_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"sandbox not found: {sandbox_dir}")
    snap = Path(tempfile.mkdtemp(prefix="attw-snap-"))
    shutil.copytree(
        root,
        snap,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".venv", "__pycache__"),
    )
    return str(snap)


def revert(sandbox_dir: str, snapshot_id: str) -> None:
    """Restore the sandbox to a snapshot (delete adapter + restore tree)."""
    root = Path(sandbox_dir)
    snap = Path(snapshot_id)
    if not snap.is_dir():
        raise FileNotFoundError(f"snapshot not found: {snapshot_id}")
    for child in root.iterdir():
        if child.name == ".venv":
            continue  # one venv per run; never churn it on revert
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in snap.iterdir():
        dest = root / child.name
        if child.is_dir():
            shutil.copytree(child, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(child, dest)


# ---------------------------------------------------------------------------
# Manifest editing (first present wins; setup.py parse-only, never execute).
# ---------------------------------------------------------------------------


def _edit_pyproject(text: str, wheel: str, pin: str) -> tuple[str, bool]:
    """Edit/replace a requirement in pyproject.toml dependency lists."""
    pat = re.compile(
        r"(dependencies\s*=\s*\[)(?P<body>.*?)(\])", re.DOTALL
    )
    tok = re.compile(r'(?P<q>["\'])(?P<name>[A-Za-z0-9_.\-]+)(?P<spec>[^"\']*)')

    m = pat.search(text)
    if m:
        found: list[bool] = []

        def _fix_repl(mm: re.Match) -> str:
            if mm.group("name").lower() == wheel.lower():
                found.append(True)
                return f'{mm.group("q")}{pin}{mm.group("q")}'
            return mm.group(0)

        new_body = tok.sub(_fix_repl, m.group("body"))
        if not found:
            if not new_body.strip():
                new_body = f'"{pin}"'
            else:
                sep = "" if new_body.rstrip().endswith(",") else ","
                new_body = new_body + f'{sep}\n    "{pin}",\n'
        return text[: m.start("body")] + new_body + text[m.end("body") :], True
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip() == "[project]":
            lines.insert(i + 1, f'dependencies = ["{pin}"]')
            return "\n".join(lines), True
    return text + f'\n[project]\ndependencies = ["{pin}"]\n', True


def _edit_setup_cfg(text: str, wheel: str, pin: str) -> tuple[str, bool]:
    """Edit install_requires in setup.cfg (text edit, no execution)."""
    lines = text.split("\n")
    section: str | None = None
    in_req = False
    req_idx: int | None = None
    opt_idx: int | None = None
    for i, line in enumerate(lines):
        m = re.match(r"\s*\[(.+)\]\s*$", line)
        if m:
            section = m.group(1).strip().lower()
            in_req = False
            if section == "options" and opt_idx is None:
                opt_idx = i
            continue
        if section != "options":
            continue
        if re.match(r"\s*install_requires\s*=", line):
            in_req = True
            req_idx = i
            rest = line.split("=", 1)[1].strip()
            if rest:
                name = re.split(r"[<>=!~\s;\[]", rest)[0]
                if name.lower() == wheel.lower():
                    lines[i] = line.split("=", 1)[0] + f"= {pin}"
                    return "\n".join(lines), True
            continue
        if in_req:
            if line.strip() == "" or re.match(r"\S", line):
                in_req = False
            else:
                name = re.split(r"[<>=!~\s;\[]", line.strip())[0]
                if name.lower() == wheel.lower():
                    indent = line[: len(line) - len(line.lstrip())]
                    lines[i] = f"{indent}{pin}"
                    return "\n".join(lines), True
    if req_idx is not None:
        lines.insert(req_idx + 1, f"    {pin}")
        return "\n".join(lines), True
    if opt_idx is not None:
        lines.insert(opt_idx + 1, f"install_requires =\n    {pin}")
        return "\n".join(lines), True
    return text + f"\n[options]\ninstall_requires =\n    {pin}\n", True


def _edit_setup_py(text: str, wheel: str, pin: str) -> tuple[str, bool]:
    """Parse-only edit of install_requires in setup.py; never executed."""
    m = re.search(r"install_requires\s*=\s*\[(?P<body>.*?)\]", text, re.DOTALL)
    if not m:
        m2 = re.search(r"setup\s*\(", text)
        if m2:
            ins = m2.end()
            return (
                text[:ins] + f'\n    install_requires=["{pin}"],' + text[ins:],
                True,
            )
        return text + f'\n# attw: install_requires=["{pin}"]\n', True
    body = m.group("body")
    tok = re.compile(r'(?P<q>["\'])(?P<name>[A-Za-z0-9_.\-]+)(?P<spec>[^"\']*)')
    found: list[bool] = []

    def _repl(mm: re.Match) -> str:
        if mm.group("name").lower() == wheel.lower():
            found.append(True)
            return f'{mm.group("q")}{pin}{mm.group("q")}'
        return mm.group(0)

    new_body = tok.sub(_repl, body)
    if not found:
        sep = "" if not body.strip() or body.rstrip().endswith(",") else ","
        new_body = body + f'{sep}\n    "{pin}",\n'
    return text[: m.start("body")] + new_body + text[m.end("body") :], True


def _edit_requirements(text: str, wheel: str, pin: str) -> tuple[str, bool]:
    """Replace-or-append a `name>=low,<high` line in requirements*.txt."""
    lines = text.split("\n")
    changed = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-")):
            continue
        name = re.split(r"[<>=!~\s;\[]", stripped)[0]
        if name.lower() == wheel.lower():
            comment = ""
            if "#" in line:
                comment = "  " + line[line.index("#") :]
            lines[i] = pin + comment
            changed = True
    if not changed:
        if lines and lines[-1].strip():
            lines.append(pin)
        else:
            lines.append(pin)
    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    return result, True


def _edit_manifest(name: str, text: str, wheel: str, pin: str) -> tuple[str, bool]:
    """Dispatch a manifest text edit by file name (never executes code)."""
    if name == "pyproject.toml":
        return _edit_pyproject(text, wheel, pin)
    if name == "setup.cfg":
        return _edit_setup_cfg(text, wheel, pin)
    if name == "setup.py":
        return _edit_setup_py(text, wheel, pin)
    return _edit_requirements(text, wheel, pin)


# ---------------------------------------------------------------------------
# Adapter: one thin delegation-only file per wheel (no LOC cap per ruling).
# ---------------------------------------------------------------------------


def _adapter_source(
    *,
    component: str,
    wheel: str,
    import_name: str,
    funcs: list,
    exception_map: dict[str, str],
) -> str:
    """Render the delegation-only adapter source."""
    for ident in [import_name, *exception_map.keys(), *exception_map.values()]:
        if not ident.isidentifier():
            raise ValueError(f"bad identifier in adapter plan: {ident!r}")
    norm: list[tuple[str, str]] = []
    for f in funcs or ["main"]:
        if isinstance(f, dict):
            old, new = f.get("as", f.get("calls", "main")), f.get("calls", "main")
        else:
            old, new = str(f), str(f)
        if not old.isidentifier() or not new.isidentifier():
            raise ValueError(f"bad adapter function: {old!r} -> {new!r}")
        norm.append((old, new))
    lines = [
        f'"""attw adapter: {component} now delegates to {wheel}."""',
        '"""Delegation-only; no business logic; delete to revert."""',
        "",
        f"import {import_name} as _wheel_mod",
        "",
    ]
    for old, new in norm:
        lines += [
            f"def {old}(*args, **kwargs):",
            f'    """Delegate to {wheel}.{new}."""',
            f"    return _wheel_mod.{new}(*args, **kwargs)",
            "",
        ]
    for old_exc, new_exc in exception_map.items():
        lines.append(f"{old_exc} = _wheel_mod.{new_exc}")
    return "\n".join(lines).rstrip("\n") + "\n"


def is_delegation_only(source: str) -> bool:
    """Check an adapter holds only delegation (imports/aliases/wrappers).

    Allowed: docstrings, imports, `Old = _mod.New` exception aliases, and
    functions whose body is a single `return <call>` (plus docstring).
    Anything else (business logic, new features) returns False.
    """
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Expr):
            if not (isinstance(node.value, ast.Constant) and
                    isinstance(node.value.value, str)):
                return False
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        elif isinstance(node, ast.Assign):
            if not isinstance(node.value, ast.Attribute):
                return False
        elif isinstance(node, ast.FunctionDef):
            body = [
                s for s in node.body
                if not (isinstance(s, ast.Expr)
                        and isinstance(s.value, ast.Constant))
            ]
            if len(body) != 1:
                return False
            ret = body[0]
            if not (isinstance(ret, ast.Return)
                    and isinstance(ret.value, ast.Call)):
                return False
        else:
            return False
    return True


# ---------------------------------------------------------------------------
# Install / venv / tidy / typecheck hooks (module-level for test mocking).
# ---------------------------------------------------------------------------


def _pip_install(pin: str, sandbox_dir: str) -> str:
    """Install one pin into the sandbox venv (network-for-installs-only).

    Uses the sandbox venv python when present, else the current
    interpreter (boundary: installs never touch the original target).
    ``pin`` may be a plain pin (``name>=low``) or an install-arg string
    (``-e .``, ``-r requirements.txt``) resolved with cwd=sandbox.

    Mocked in unit tests (no network there); real runs `pip install`.
    """
    root = Path(sandbox_dir)
    python = verify._sandbox_python(root)
    proc = subprocess.run(
        [python, "-m", "pip", "install", *shlex.split(pin)],
        cwd=sandbox_dir,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pip install {pin!r} failed: {proc.stderr[-2000:]}")
    return proc.stdout[-2000:]


def _ensure_venv(sandbox_dir: str) -> dict:
    """One venv per run: `uv venv` then fallback `python -m venv`."""
    root = Path(sandbox_dir)
    if (root / ".venv").is_dir():
        return {"tool": "existing", "path": ".venv"}
    if shutil.which("uv") is not None:
        try:
            subprocess.run(
                ["uv", "venv", ".venv"],
                cwd=sandbox_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            return {"tool": "uv", "path": ".venv"}
        except Exception:
            pass  # fall through to venv
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", ".venv"],
            cwd=sandbox_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return {"tool": "venv", "path": ".venv"}
    except Exception as exc:
        return {"tool": "unavailable", "detail": str(exc)}


def _detect_test_command(sandbox_dir: str) -> str:
    """Suite target for the harness: ``tests/`` (or ``test/``) when the
    target repo has one, else a bare collection.

    A bare ``pytest -q`` from the repo root lets the collector wander
    into docs/images dirs; scoping to the suite dir keeps baseline and
    after captures on the target's own tests.
    """
    root = Path(sandbox_dir)
    if (root / "tests").is_dir():
        return "pytest -q tests"
    if (root / "test").is_dir():
        return "pytest -q test"
    return "pytest -q"


# ---------------------------------------------------------------------------
# Pytest plugin deps implied by the target's own pytest config.
# ---------------------------------------------------------------------------


#: Allowlist: pytest plugin module -> pip package. Only these are ever
#: installed from `-p` / `--plugin` addopts tokens; unknown names are
#: skipped (never an unbounded installer from target config).
_PYTEST_PLUGIN_BY_MODULE = {
    "pytest_cov": "pytest-cov",
    "pytest_mock": "pytest-mock",
    "pytest_cookies": "pytest-cookies",
    "pytest_xdist": "pytest-xdist",
    "xdist": "pytest-xdist",
    "pytest_forked": "pytest-forked",
    "pytest_timeout": "pytest-timeout",
    "pytest_asyncio": "pytest-asyncio",
}


def _pytest_addopts_tokens(sandbox_dir: str | Path) -> list[str]:
    """Collect pytest `addopts` tokens from the sandbox target's config.

    Reads (first match wins per file, all files merged):
    ``pyproject.toml`` (``[tool.pytest.ini_options] addopts``, str or list),
    ``setup.cfg`` (``[tool:pytest]``), ``pytest.ini`` / ``tox.ini``
    (``[pytest]``). Missing/unparseable files yield no tokens. Read-only;
    never overrides the target's addopts.
    """
    import configparser

    root = Path(sandbox_dir)
    tokens: list[str] = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            try:
                import tomllib  # Python 3.11+
            except ImportError:  # pragma: no cover
                tomllib = None  # type: ignore[assignment]
            if tomllib is not None:
                data = tomllib.loads(
                    pyproject.read_text(encoding="utf-8", errors="replace")
                )
                raw = ((data.get("tool") or {}).get("pytest") or {}).get(
                    "ini_options", {}
                ).get("addopts", "")
                if isinstance(raw, list):
                    tokens.extend(shlex.split(" ".join(str(t) for t in raw)))
                elif isinstance(raw, str) and raw.strip():
                    tokens.extend(shlex.split(raw))
        except Exception:
            pass  # unparseable config -> no tokens, never a raise
    for name, section in (
        ("setup.cfg", "tool:pytest"),
        ("pytest.ini", "pytest"),
        ("tox.ini", "pytest"),
    ):
        path = root / name
        if not path.is_file():
            continue
        try:
            parser = configparser.ConfigParser()
            parser.read_string(path.read_text(encoding="utf-8", errors="replace"))
            if parser.has_option(section, "addopts"):
                raw = parser.get(section, "addopts", raw=True)
                tokens.extend(shlex.split(raw.replace("\n", " ")))
        except Exception:
            continue
    return tokens


def _pytest_plugin_pins(sandbox_dir: str | Path) -> list[str]:
    """Map target pytest `addopts` tokens to pip packages (allowlisted).

    ``--cov*`` flags imply ``pytest-cov``; ``-p`` / ``--plugin`` values are
    installed only when they hit :data:`_PYTEST_PLUGIN_BY_MODULE`
    (``no:`` disables and unknown names are skipped). Returns deduped
    package names, order-preserved.
    """
    pins: list[str] = []
    tokens = _pytest_addopts_tokens(sandbox_dir)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--cov" or tok.startswith("--cov=") or tok.startswith("--cov-"):
            pins.append("pytest-cov")
        elif tok == "--cov-report" or tok.startswith("--cov-report"):
            pins.append("pytest-cov")
        elif tok == "-p" or tok == "--plugin":
            if i + 1 < len(tokens):
                i += 1
                pins.append(tokens[i])
        elif tok.startswith("-p") and len(tok) > 2:
            pins.append(tok[2:].lstrip("="))
        elif tok.startswith("--plugin="):
            pins.append(tok.split("=", 1)[1])
        i += 1
    resolved: list[str] = []
    for name in pins:
        name = str(name).strip()
        if not name or name.startswith("no:"):
            continue
        key = name.replace("-", "_")
        pkg = _PYTEST_PLUGIN_BY_MODULE.get(key, "")
        if pkg and pkg not in resolved:
            resolved.append(pkg)
    # --cov flags appended "pytest-cov" directly (already a package name).
    return resolved


# ---------------------------------------------------------------------------
# Test dependency-groups implied by the target's own test config.
# ---------------------------------------------------------------------------


#: Group/extras names treated as TEST deps. Only these are ever installed;
#: `dev`/`docs`/`lint` groups are never pulled (modest allowlist: install
#: what's declared for tests, no unbounded resolution).
_TEST_GROUP_NAMES = ("test", "tests", "testing")


def _dep_groups_from_pyproject(root: Path) -> list[str]:
    """Collect TEST `[dependency-groups]` entries (PEP 735, strings only).

    Starts from groups named in :data:`_TEST_GROUP_NAMES` and follows
    ``{include-group = "..."}`` refs recursively (cycle-guarded); any other
    table entries are skipped. Missing/unparseable files yield [].
    Read-only; never executes target code.
    """
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return []
    try:
        import tomllib  # Python 3.11+
    except ImportError:  # pragma: no cover
        return []
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    groups = data.get("dependency-groups")
    if not isinstance(groups, dict):
        return []
    pins: list[str] = []
    visited: set[str] = set()

    def _visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        entries = groups.get(name)
        if not isinstance(entries, list):
            return
        for entry in entries:
            if isinstance(entry, str):
                if entry.strip() and entry.strip() not in pins:
                    pins.append(entry.strip())
            elif isinstance(entry, dict) and isinstance(
                entry.get("include-group"), str
            ):
                _visit(entry["include-group"])

    for name in _TEST_GROUP_NAMES:
        if name in groups:
            _visit(name)
    return pins


def _extras_from_setup_cfg(root: Path) -> list[str]:
    """Collect TEST extras from ``setup.cfg`` (``[options.extras_require]``).

    Keys matching :data:`_TEST_GROUP_NAMES` (case-insensitive); values split
    on newlines/commas, comments/empties skipped, markers kept verbatim.
    Missing/unparseable files yield [].
    """
    import configparser

    path = root / "setup.cfg"
    if not path.is_file():
        return []
    try:
        parser = configparser.ConfigParser()
        parser.read_string(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    section = "options.extras_require"
    if not parser.has_section(section):
        return []
    pins: list[str] = []
    for key in parser.options(section):
        if key.strip().lower() not in _TEST_GROUP_NAMES:
            continue
        try:
            raw = parser.get(section, key, raw=True)
        except Exception:
            continue
        for chunk in raw.replace(",", "\n").split("\n"):
            line = chunk.strip()
            if not line or line.startswith("#"):
                continue
            if line not in pins:
                pins.append(line)
    return pins


def _extras_from_setup_py(root: Path) -> list[str]:
    """Collect TEST extras from ``setup.py`` via AST (parse-only, never run).

    Reads literal ``setup(... extras_require={"test": [...]})`` string
    constants for keys in :data:`_TEST_GROUP_NAMES`; anything dynamic or
    unparseable yields []. Never executes the file.
    """
    path = root / "setup.py"
    if not path.is_file():
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    pins: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_setup = (isinstance(func, ast.Name) and func.id == "setup") or (
            isinstance(func, ast.Attribute) and func.attr == "setup"
        )
        if not is_setup:
            continue
        for kw in node.keywords:
            if kw.arg != "extras_require" or not isinstance(kw.value, ast.Dict):
                continue
            for k, v in zip(kw.value.keys, kw.value.values):
                if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                    continue
                if k.value.strip().lower() not in _TEST_GROUP_NAMES:
                    continue
                if not isinstance(v, (ast.List, ast.Tuple)):
                    continue
                for elt in v.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        entry = elt.value.strip()
                        if entry and entry not in pins:
                            pins.append(entry)
    return pins


def _test_requirements_files(root: Path) -> list[str]:
    """Install-arg refs for TEST requirements files (``-r <rel>``).

    Matches root ``requirements-test*.txt`` and ``requirements/test*.txt``
    (also ``requirement/test*.txt`` singular). Missing dirs yield [].
    Returned as ``-r`` args resolved with cwd=sandbox (same form as the
    existing root-requirements handling in :func:`_install_target_deps`).
    """
    refs: list[str] = []
    for path in sorted(root.glob("requirements-test*.txt")):
        if path.is_file() and path.name not in refs:
            refs.append(f"-r {path.name}")
    for dirname in ("requirements", "requirement"):
        sub = root / dirname
        if not sub.is_dir():
            continue
        for path in sorted(sub.glob("test*.txt")):
            if path.is_file():
                refs.append(f"-r {path.relative_to(root).as_posix()}")
    return refs


def _test_group_pins(sandbox_dir: str | Path) -> list[str]:
    """All declared TEST dep pins for the sandbox target (order-preserved).

    Merges pyproject ``[dependency-groups]`` TEST entries, setup.cfg/setup.py
    ``test`` extras, and TEST requirements-file refs. Deduped; install-arg
    (``-r ...``) refs kept verbatim. Never raises on bad config.
    """
    root = Path(sandbox_dir)
    pins: list[str] = []
    for pin in (
        _dep_groups_from_pyproject(root)
        + _extras_from_setup_cfg(root)
        + _extras_from_setup_py(root)
        + _test_requirements_files(root)
    ):
        if pin not in pins:
            pins.append(pin)
    return pins


def _install_target_deps(sandbox_dir: str, component: str = "") -> dict:
    """Install the target's own deps into the sandbox venv pre-baseline.

    Editable target (``-e .``) when a build manifest is present, plus
    every root ``requirements*.txt`` when present, plus pytest plugin
    deps implied by the target's pytest config (``_pytest_plugin_pins``,
    allowlisted), plus the target's TEST dependency-groups
    (``_test_group_pins``: pyproject ``[dependency-groups]`` TEST entries,
    ``test`` extras, TEST requirements files). Installs-only
    network; each attempt is recorded and failures become exact
    ``implement/failed-install`` records — never a raise, so a
    half-installable target still yields a baseline capture downstream.
    """
    root = Path(sandbox_dir)
    record: dict = {"attempts": [], "installed": [], "failures": []}
    pins: list[str] = []
    if any(
        (root / name).is_file()
        for name in ("pyproject.toml", "setup.py", "setup.cfg")
    ):
        pins.append("-e .")
    pins.extend(
        f"-r {path.name}"
        for path in sorted(root.glob("requirements*.txt"))
        if path.is_file()
    )
    # Pytest plugin deps implied by the target's own pytest config
    # (e.g. `--cov*` addopts needs pytest-cov or the harness baseline
    # capture dies with a usage error and no parseable report). The
    # target's addopts itself is never overridden. Failures record as
    # exact `implement/failed-install` rows, downstream-only.
    for pkg in _pytest_plugin_pins(root):
        if pkg not in pins:
            pins.append(pkg)
    # TEST dependency-groups (e.g. freezegun from `[dependency-groups]
    # test`): the suite must import the target's test helpers or the
    # baseline misfires on collection errors. Only what's declared for
    # tests is installed (never dev/docs/lint groups). Failures record
    # as exact `implement/failed-install` rows, downstream-only.
    for pin in _test_group_pins(root):
        if pin not in pins:
            pins.append(pin)
    for pin in pins:
        record["attempts"].append(pin)
        try:
            _pip_install(pin, str(root))
            record["installed"].append(pin)
        except Exception as exc:  # noqa: BLE001 — record, baseline still runs
            record["failures"].append(
                make_failure(
                    "implement",
                    "failed-install",
                    f"target-deps install failed for {pin!r}: "
                    f"{type(exc).__name__}: {exc}",
                    component=component,
                )
            )
    return record


def _run_tidy(sandbox_dir: str, touched_py: list[str]) -> dict:
    """Tidy gate on touched Python files: ruff check + ruff format.

    Module invocations (`python -m ruff`, Windows-safe), run in-sandbox.
    """
    if not touched_py:
        return {"ok": True, "note": "no python files touched"}
    steps: dict[str, dict] = {}
    for sub in ("check", "format"):
        proc = subprocess.run(
            [sys.executable, "-m", "ruff", sub, *touched_py],
            cwd=sandbox_dir,
            capture_output=True,
            text=True,
        )
        steps[sub] = {
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
        }
    final = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *touched_py],
        cwd=sandbox_dir,
        capture_output=True,
        text=True,
    )
    steps["check_after_format"] = {
        "returncode": final.returncode,
        "stdout": final.stdout[-2000:],
        "stderr": final.stderr[-2000:],
    }
    steps["ok"] = bool(final.returncode == 0)
    return steps


def _run_typecheck(sandbox_dir: str, touched_py: list[str]) -> dict:
    """Advisory-only typecheck on touched files; stdout recorded, never a gate.

    `pyright`, fallback `mypy`; arbitrary targets are half-untyped so type
    errors warn but never fail.
    """
    if not touched_py:
        return {"tool": "none", "note": "no python files touched", "ok": True}
    tool = None
    if shutil.which("pyright") is not None:
        tool = "pyright"
    elif shutil.which("mypy") is not None:
        tool = "mypy"
    if tool is None:
        return {"tool": "none", "note": "no typechecker installed", "ok": True}
    proc = subprocess.run(
        [tool, *touched_py],
        cwd=sandbox_dir,
        capture_output=True,
        text=True,
    )
    return {
        "tool": tool,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "ok": True,  # advisory-only, never a gate
    }


def _capture(
    sandbox_dir: str, label: str, test_command: str = "pytest -q"
) -> dict[str, str]:
    """Call the harness baseline capture (harness owns it) and parse outcomes.

    Returns {nodeid: outcome}; unparseable/missing reports yield {}.
    """
    report_path = verify.run_suite(
        sandbox_dir, test_command=test_command, label=label
    )
    try:
        data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    tests = data.get("tests", data.get("test_results", []))
    outcomes: dict[str, str] = {}
    if isinstance(tests, list):
        for entry in tests:
            if not isinstance(entry, dict):
                continue
            node = entry.get("nodeid") or entry.get("name")
            outcome = entry.get("outcome") or entry.get("status")
            if node and outcome:
                outcomes[str(node)] = str(outcome)
    elif isinstance(tests, dict):
        outcomes = {str(k): str(v) for k, v in tests.items()}
    return outcomes


# ---------------------------------------------------------------------------
# Vendor: copy to _vendored/<wheel>/ + import rewrite + ATTRIBUTION (03 §1).
# ---------------------------------------------------------------------------


def _wheel_snake(wheel: str) -> str:
    """Filesystem/import-safe wheel stem (`-` -> `_`)."""
    return re.sub(r"[^A-Za-z0-9_]", "_", wheel.replace("-", "_"))


def _pypi_url(wheel: str, plan: dict) -> str:
    url = str(plan.get("pypi_url") or "").strip()
    return url or f"https://pypi.org/project/{wheel}/"


def _rewrite_imports_for_vendor(
    text: str, import_name: str, snake: str
) -> tuple[str, int]:
    """Rewrite `import <name>` / `from <name>...` to `_vendored.<snake>`."""
    if not import_name:
        return text, 0
    namespaced = f"_vendored.{snake}"
    count = 0
    ident = r"[A-Za-z_][A-Za-z0-9_]*"

    def _fix_import(m: re.Match) -> str:
        nonlocal count
        count += 1
        alias = m.group("alias") or ""
        if alias:
            return f"{m.group('head')}import {namespaced} as {alias}"
        return f"{m.group('head')}import {namespaced} as {import_name}"

    text = re.sub(
        r"(?m)^(?P<head>\s*)import\s+"
        + re.escape(import_name)
        + rf"(?P<rest>\s+as\s+(?P<alias>{ident}))?(?P<tail>\s*(#.*)?)$",
        _fix_import,
        text,
    )

    def _fix_from(m: re.Match) -> str:
        nonlocal count
        count += 1
        sub = m.group("sub")
        what = m.group("what")
        return f"{m.group('head')}from {namespaced}{sub} import {what}"

    text = re.sub(
        r"(?m)^(?P<head>\s*)from\s+"
        + re.escape(import_name)
        + rf"(?P<sub>(?:\s*\.\s*{ident})*)\s+import\s+(?P<what>.+)$",
        _fix_from,
        text,
    )
    return text, count


def _vendor_attribution(
    *, wheel: str, pin: str, version: str, pypi_url: str, license: str, snake: str
) -> str:
    """Render the ATTRIBUTION file (name/version/PyPI URL/license + pin)."""
    return (
        f"{wheel} (vendored)\n"
        f"version: {version}\n"
        f"PyPI: {pypi_url}\n"
        f"license: {license or 'unknown'}\n"
        f"pin: {pin}\n"
        f"notes: vendored copy; imports rewritten to _vendored.{snake}; "
        f"pinned {pin}.\n"
    )


def _apply_vendor(root: Path, plan: dict, wheel: str, installed: str) -> dict:
    """Copy the wheel into `_vendored/<wheel>/`, rewrite imports, attribute."""
    import_name = str(plan.get("import_name") or _wheel_snake(wheel))
    snake = _wheel_snake(wheel)
    vendored_rel = f"_vendored/{wheel}"
    pin = str(plan.get("pin") or installed or wheel)
    version = str(
        plan.get("version_low") or plan.get("version_high") or installed or "unknown"
    )
    pypi_url = _pypi_url(wheel, plan)
    license = str(plan.get("license", "") or "")
    source = plan.get("vendor_source")
    files: dict[str, str] = {}
    if isinstance(source, dict):
        files = {str(k): str(v) for k, v in source.items()}
    elif isinstance(source, str) and source:
        src = Path(source)
        if src.is_dir():
            for child in sorted(src.rglob("*")):
                if child.is_file():
                    files[child.relative_to(src).as_posix()] = child.read_text(
                        encoding="utf-8", errors="replace"
                    )
    if not files:
        files = {
            "__init__.py": (
                f'"""Vendored {wheel!r} ({pin}). See ATTRIBUTION."""\n'
                f"\n__vendored_version__ = {version!r}\n"
            ),
        }
    written: list[str] = []
    rewritten = 0
    for rel, content in files.items():
        text = content
        if rel.endswith(".py"):
            text, n = _rewrite_imports_for_vendor(text, import_name, snake)
            rewritten += n
        _write_inside(root, f"{vendored_rel}/{rel}", text)
        written.append(f"{vendored_rel}/{rel}")
    attribution = _vendor_attribution(
        wheel=wheel, pin=pin, version=version,
        pypi_url=pypi_url, license=license, snake=snake,
    )
    _write_inside(root, f"{vendored_rel}/ATTRIBUTION", attribution)
    # Rewrite call-site imports outside _vendored/ to the namespaced path.
    touched = [p for p in written if p.endswith(".py")]
    for child in sorted(root.rglob("*.py")):
        rel_posix = child.relative_to(root).as_posix()
        if rel_posix.startswith("_vendored/") or ".venv" in child.parts:
            continue
        try:
            text = child.read_text(encoding="utf-8")
        except Exception:
            continue
        new_text, n = _rewrite_imports_for_vendor(text, import_name, snake)
        if n:
            _write_inside(root, rel_posix, new_text)
            rewritten += n
            touched.append(rel_posix)
    return {
        "dir": vendored_rel,
        "files": written,
        "attribution": f"{vendored_rel}/ATTRIBUTION",
        "pypi_url": pypi_url,
        "pin": pin,
        "rewritten": rewritten,
        "touched": touched,
    }


# ---------------------------------------------------------------------------
# Apply: the applier.
# ---------------------------------------------------------------------------


def _fail(
    code: str,
    reason: str,
    *,
    component: str = "",
    detail: str = "",
    receipt: dict | None = None,
) -> dict:
    """Build a failure receipt carrying the exact `implement: <code>` string."""
    base = dict(receipt or {})
    base.update(
        {
            "ok": False,
            "reverted": base.get("reverted", False),
            "failure": make_failure(
                "implement", code, reason, detail=detail, component=component
            ),
            "failure_string": f"implement: {code}",
        }
    )
    return base


def apply(plan: dict, sandbox_dir: str, test_command: str | None = None) -> dict:
    """Apply a plan inside the sandbox copy; return the implement receipt.

    Never touches the original target: every write is prefix-asserted to
    the sandbox; installs go to the sandbox venv only; nothing is pushed
    or exfiltrated. Regressions and api-mismatches revert to the
    pre-change snapshot. Returns a receipt dict (D4: manifest_diff,
    deleted_paths, adapter_path, tidy, typecheck) with `ok` True/False and
    the exact failure string on failure. ``test_command`` scopes the
    harness captures to the suite target (``tests/`` etc.); detected from
    the sandbox when omitted.
    """
    root = Path(sandbox_dir)
    wheel = str(plan.get("wheel", "unknown"))
    strategy = str(plan.get("strategy", "dep-swap"))
    component = str(plan.get("component", ""))
    receipt: dict = {
        "ok": True,
        "component": component,
        "wheel": wheel,
        "strategy": strategy,
        "sandbox": str(root),
        "manifest": None,
        "manifest_diff": "",
        "deleted_paths": [],
        "adapter_path": None,
        "tidy": {},
        "typecheck": {},
        "venv": {},
        "verdict": None,
        "license_warning": plan.get("license_warning", ""),
        "failure": None,
        "failure_string": "",
        "vendor": None,
        "vendored_dir": None,
        "vendored_files": [],
        "attribution_path": None,
        "notes": "",
    }
    if not root.is_dir():
        return _fail(
            "failed-install",
            f"sandbox not found: {sandbox_dir}",
            component=component,
            receipt=receipt,
        )
    snap = snapshot(str(root))
    receipt["snapshot"] = snap
    # GPL-family: dep-swap-or-skip, never vendor — re-asserted at apply time
    # even if a stale plan says vendor.
    if strategy == "vendor" and _is_gpl(str(plan.get("license", ""))):
        strategy = "dep-swap"
        receipt["strategy"] = strategy
        receipt["license_warning"] = (
            f"GPL-family wheel {wheel!r}: vendor skipped, dep-swap used."
        )
    # C-extension wheels: never vendor — dep-swap-or-skip (03 Proposal §1).
    if strategy == "vendor" and bool(plan.get("c_extension", False)):
        strategy = "dep-swap"
        receipt["strategy"] = strategy
        receipt["notes"] = (
            f"C-extension wheel {wheel!r}: vendor refused, dep-swap used."
        )
    # Venv first, then the target's own deps, THEN the harness baseline:
    # the suite must import the target's deps (editable target +
    # requirements file) or the baseline misfires on ModuleNotFoundError.
    # The suite python is the venv python from here on.
    receipt["venv"] = _ensure_venv(str(root))
    receipt["target_deps"] = _install_target_deps(str(root), component)
    command = test_command or _detect_test_command(str(root))
    receipt["test_command"] = command
    # Baseline via the harness (implement calls, harness owns).
    baseline = _capture(str(root), "baseline", command)
    receipt["baseline_nodes"] = len(baseline)
    # Install: winner + up to 2 next-ranked fallbacks, then failed-install.
    candidates = [plan.get("pin") or wheel]
    candidates += [str(f) for f in list(plan.get("fallbacks", []) or [])[:2]]
    attempts: list[str] = []
    installed: str | None = None
    for cand in candidates:
        try:
            _pip_install(cand, str(root))
            installed = cand
            break
        except Exception as exc:
            attempts.append(f"{cand}: {exc}")
    receipt["install_attempts"] = len(attempts) + (1 if installed else 0)
    receipt["installed"] = installed
    if installed is None:
        return _fail(
            "failed-install",
            f"pip install failed for {wheel} + {len(candidates) - 1} fallbacks",
            component=component,
            detail="; ".join(attempts)[:4000],
            receipt=receipt,
        )
    # Manifest edit (first present wins; setup.py parse-only).
    present = [p.name for p in root.iterdir() if p.is_file()]
    manifest = plan.get("manifest") or choose_manifest(present) or "requirements.txt"
    receipt["manifest"] = manifest
    target = _inside(root, manifest)
    before = target.read_text(encoding="utf-8") if target.exists() else ""
    after_text, _ = _edit_manifest(manifest, before, wheel, installed)
    _write_inside(root, manifest, after_text)
    receipt["manifest_diff"] = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=f"before/{manifest}",
            tofile=f"after/{manifest}",
        )
    )
    # Deletion outright in sandbox (replaced modules + orphaned deps).
    deleted: list[str] = []
    for rel in plan.get("delete", []) or []:
        victim = _inside(root, rel)  # prefix-asserted; escape raises
        if victim.is_dir() and not victim.is_symlink():
            shutil.rmtree(victim)
            deleted.append(rel)
        elif victim.exists() or victim.is_symlink():
            victim.unlink()
            deleted.append(rel)
    receipt["deleted_paths"] = deleted
    touched_py: list[str] = []
    # Vendor: copy to _vendored/<wheel>/, rewrite imports, ATTRIBUTION + pin.
    if strategy == "vendor":
        vendor = _apply_vendor(root, plan, wheel, installed or "")
        receipt["vendor"] = {k: v for k, v in vendor.items() if k != "touched"}
        receipt["vendored_dir"] = vendor["dir"]
        receipt["vendored_files"] = vendor["files"]
        receipt["attribution_path"] = vendor["attribution"]
        receipt["notes"] = (
            f"vendored {wheel} {vendor['pin']} "
            f"({len(vendor['files'])} files, "
            f"{vendor['rewritten']} imports rewritten); "
            f"see {vendor['attribution']}."
        )
        touched_py.extend(vendor["touched"])
    # Adapter: one attempt, then api-mismatch + revert.
    if strategy == "adapter":
        rel = adapter_path(
            plan.get("layout", "flat"), wheel, plan.get("package")
        )
        source = _adapter_source(
            component=component or wheel,
            wheel=wheel,
            import_name=plan.get("import_name") or wheel.replace("-", "_"),
            funcs=plan.get("adapter_funcs") or ["main"],
            exception_map=dict(plan.get("exception_map", {}) or {}),
        )
        if not is_delegation_only(source):
            revert(str(root), snap)
            receipt["reverted"] = True
            return _fail(
                "api-mismatch",
                f"adapter for {wheel} is not delegation-only",
                component=component,
                receipt=receipt,
            )
        _write_inside(root, rel, source)
        receipt["adapter_path"] = rel
        touched_py.append(rel)
        if not plan.get("adapter_valid", True):
            revert(str(root), snap)
            receipt["reverted"] = True
            return _fail(
                "api-mismatch",
                f"wheel {wheel} API does not fit after one adapter attempt",
                component=component,
                detail=f"adapter {rel} written then reverted",
                receipt=receipt,
            )
    # Tidy (ruff, in-sandbox) + advisory typecheck, both recorded.
    receipt["tidy"] = _run_tidy(str(root), touched_py)
    receipt["typecheck"] = _run_typecheck(str(root), touched_py)
    # After-capture via the harness; regressions revert + keep-yours evidence.
    after = _capture(str(root), "after", command)
    receipt["after_nodes"] = len(after)
    diff = verify.diff_results(baseline, after, {})
    receipt["diff"] = diff
    verdict = verify.decide_verdict(diff, after)
    receipt["verdict"] = verdict
    if verdict == "fail":
        revert(str(root), snap)
        receipt["reverted"] = True
        return _fail(
            "regression",
            "after-suite regressed vs harness baseline",
            component=component,
            detail=json.dumps(diff, sort_keys=True)[:4000],
            receipt=receipt,
        )
    receipt["reverted"] = False
    return receipt
