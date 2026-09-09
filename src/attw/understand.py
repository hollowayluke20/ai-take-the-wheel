"""Understand stage: profile a repo URL or plain-text idea into components.

Component is the common currency (map): repo URLs are read as code
(shallow clone into a temp dir, never the repo dir), idea-text is
decomposed up front with a deterministic splitter (the LLM front end
lands downstream), then one identical pipeline runs per component.

No API calls in this stage. Confidence is display-only (05 D4).
Doubt -> addition, never substitution (05 D7).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TypedDict

from attw.failures import make_failure

STAGE = "understand"

#: Failure codes used by this stage (subset of failures.CODES).
CODE_BAD_INPUT = "not_applicable"  # blank input / no Python files found
CODE_CLONE_FAILED = "source_down"  # shallow clone failed (bad URL, no git, offline)


class Component(TypedDict):
    """One decomposable unit. kind: addition | substitution | unknown."""

    name: str
    description: str
    kind: str
    call_sites: list[str]
    confidence: float


class UnderstandError(Exception):
    """decompose() failed; carries the exact failure record in `.failure`."""

    def __init__(self, failure: dict):
        super().__init__(failure.get("reason", "understand failed"))
        self.failure = failure


def _fail(code: str, reason: str, detail: str = "") -> UnderstandError:
    return UnderstandError(make_failure(STAGE, code, reason, detail=detail))


def classify_input(source: str) -> str:
    """Pure routing: URL with scheme -> repo_url, else idea_text."""
    return "repo_url" if source.startswith(("http://", "https://")) else "idea_text"


def decompose(source: str, *, timeout_s: int = 120) -> list[Component]:
    """Decompose any input into a component list.

    repo_url: shallow-clone (``git clone --depth 1``) into a fresh temp
    dir — never the caller's repo dir — scan the ``*.py`` files for
    hand-rolled patterns, and emit one Component per hit (kind
    ``substitution``). A repo with no test files gains one ``addition``
    component (missing suite). A repo with Python files but no
    recognized patterns yields one low-confidence ``addition`` fallback.

    idea_text: split the text into capability phrases; each becomes an
    ``addition`` Component (doubt -> addition, never substitution).

    Failure paths raise UnderstandError carrying the exact failure
    record (``failures.make_failure("understand", ...)``):
    blank input / no Python files -> ``not_applicable``; clone failure
    -> ``source_down`` with the git stderr in ``detail``.
    """
    if not source or not source.strip():
        raise _fail(CODE_BAD_INPUT, "Empty input: nothing to decompose.")
    if classify_input(source) == "repo_url":
        return _decompose_repo(source.strip(), timeout_s=timeout_s)
    return _decompose_idea(source.strip())


# ---------------------------------------------------------------------------
# idea-text front end (05 D7 shape; deterministic until the LLM lands)
# ---------------------------------------------------------------------------

_IDEA_SPLIT = re.compile(
    r"\s*(?:[;\n]+|\s+and\s+|\s+plus\s+|\s+with\s+)\s*", re.IGNORECASE
)


def _short_name(phrase: str, max_words: int = 7, max_chars: int = 60) -> str:
    words = phrase.split()
    name = " ".join(words[:max_words])
    if len(words) > max_words or len(name) > max_chars:
        name = name[:max_chars].rstrip()
    return name[:1].upper() + name[1:] if name else "Untitled capability"


def _decompose_idea(text: str) -> list[Component]:
    phrases = [p.strip(" .") for p in _IDEA_SPLIT.split(text)]
    phrases = [p for p in phrases if p]
    if not phrases:
        raise _fail(CODE_BAD_INPUT, "Empty input: nothing to decompose.")
    return [
        Component(
            name=_short_name(phrase),
            description=phrase[:1].upper() + phrase[1:] if phrase else phrase,
            kind="addition",  # doubt -> addition, never substitution (05 D7)
            call_sites=[],
            confidence=0.5,
        )
        for phrase in phrases
    ]


# ---------------------------------------------------------------------------
# repo front end: shallow clone to temp, scan *.py for hand-rolled patterns
# ---------------------------------------------------------------------------

# (pattern id, line regex, component name, description, min hits per file)
# A file matching a pattern means hand-rolled code doing a wheel's job ->
# kind substitution. Counts aggregate per file to avoid one-liner noise.
_PATTERNS: tuple[tuple[str, str, str, str, int], ...] = (
    (
        "http-client",
        r"urllib\.request|urlopen|urllib\.error|http\.client",
        "HTTP fetching with hand-rolled urllib helpers",
        "Downloading remote resources with hand-rolled urllib.request "
        "helpers instead of a maintained HTTP client.",
        1,
    ),
    (
        "cli",
        r"import argparse|from argparse|sys\.argv\[",
        "CLI parsing with hand-built argv/argparse code",
        "Parsing a command-line interface with hand-built argv/argparse "
        "code instead of a typed CLI framework.",
        1,
    ),
    (
        "csv",
        r"\.split\(\s*['\"],",
        "Hand-rolled delimited-text parsing",
        "Parsing CSV/delimited text with hand-rolled string splits "
        "instead of the csv module or a data library.",
        1,
    ),
    (
        "retry",
        r"retry|backoff|time\.sleep",
        "Retrying flaky calls with hand-rolled retry/sleep logic",
        "Retrying flaky calls with hand-rolled retry counters and sleeps "
        "instead of a retry library.",
        2,
    ),
    (
        "config",
        r"configparser|ConfigParser|os\.getenv|os\.environ\[",
        "Layered configuration with ad-hoc env/config reads",
        "Loading layered configuration with ad-hoc configparser/env reads "
        "instead of typed settings.",
        2,
    ),
    (
        "validation",
        r"isinstance\s*\(",
        "Validating nested data with hand-written isinstance checks",
        "Validating nested dicts/data with hand-written isinstance checks "
        "and raises instead of a validation library.",
        3,
    ),
)

_MAX_SITES = 10
_SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "__pycache__", "node_modules"}


def _clone_to_temp(url: str, timeout_s: int) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="attw-understand-"))
    try:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(tmp / "repo")],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise _fail(
            CODE_CLONE_FAILED,
            f"Cannot clone {url}: git is not installed.",
        ) from None
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp, ignore_errors=True)
        raise _fail(
            CODE_CLONE_FAILED,
            f"Cannot clone {url}: clone timed out after {timeout_s}s.",
        ) from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
        shutil.rmtree(tmp, ignore_errors=True)
        raise _fail(
            CODE_CLONE_FAILED,
            f"Cannot clone {url}: git clone failed.",
            detail=detail,
        ) from None
    return tmp / "repo"


def _py_files(root: Path) -> list[Path]:
    files = [
        p
        for p in sorted(root.rglob("*.py"))
        if not any(part in _SKIP_DIRS or part.startswith(".") for part in p.parts)
        and p.is_file()
    ]
    return files


def _has_tests(root: Path, files: list[Path]) -> bool:
    if (root / "tests").is_dir() or (root / "test").is_dir():
        return True
    return any(
        p.name.startswith("test_") or p.name.endswith("_test.py") for p in files
    )


def _scan_file(
    path: Path, root: Path, compiled: list[tuple[str, re.Pattern, str, str, int]]
) -> dict[str, list[str]]:
    """Map pattern id -> call sites (``relpath:lineno``) for one file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    rel = path.relative_to(root).as_posix()
    hits: dict[str, list[str]] = {}
    lines = text.splitlines()
    for pid, rx, _name, _desc, _min_hits in compiled:
        sites = [
            f"{rel}:{n}" for n, line in enumerate(lines, start=1) if rx.search(line)
        ]
        if sites:
            hits[pid] = sites[:_MAX_SITES]
    return hits


def decompose_repo_dir(root: Path | str) -> list[Component]:
    """Scan an already-cloned repo dir. Raises UnderstandError if no *.py."""
    root = Path(root)
    files = _py_files(root)
    if not files:
        raise _fail(
            CODE_BAD_INPUT,
            f"No Python files found under {root}.",
        )
    compiled = [
        (pid, re.compile(rx, re.IGNORECASE), name, desc, min_hits)
        for pid, rx, name, desc, min_hits in _PATTERNS
    ]
    by_pattern: dict[str, list[str]] = {}
    for path in files:
        for pid, sites in _scan_file(path, root, compiled).items():
            by_pattern.setdefault(pid, []).extend(sites)
    meta = {pid: (name, desc, min_hits) for pid, _rx, name, desc, min_hits in _PATTERNS}
    components: list[Component] = []
    for pid, sites in by_pattern.items():
        name, desc, min_hits = meta[pid]
        if len(sites) < min_hits:
            continue
        components.append(
            Component(
                name=name,
                description=desc,
                kind="substitution",
                call_sites=sites[:_MAX_SITES],
                confidence=0.6,
            )
        )
    if not _has_tests(root, files):
        components.append(
            Component(
                name="No automated test suite",
                description="The codebase ships with no automated tests, "
                "so regressions can only be caught by hand.",
                kind="addition",
                call_sites=[],
                confidence=0.55,
            )
        )
    if not components:
        label = root.name
        components.append(
            Component(
                name=f"{label} codebase overview",
                description=f"{len(files)} Python files scanned; no recognized "
                "hand-rolled patterns matched, so no substitution is proposed.",
                kind="addition",  # doubt -> addition (05 D7)
                call_sites=[],
                confidence=0.3,
            )
        )
    return components


def _decompose_repo(url: str, timeout_s: int) -> list[Component]:
    tmp_root = _clone_to_temp(url, timeout_s)
    # tmp_root = <tempdir>/repo; reaped after scanning (run JSON keeps
    # full copies per 05 D10, never pointers into temp).
    try:
        return decompose_repo_dir(tmp_root)
    finally:
        shutil.rmtree(tmp_root.parent, ignore_errors=True)


def profile(source: str) -> list[str]:
    """Compat shim (05 D1): component descriptions for a source.

    Raises UnderstandError on failure paths (use decompose() when the
    failure record itself is needed).
    """
    return [c["description"] for c in decompose(source)]
