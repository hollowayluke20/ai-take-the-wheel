"""Verify stage: before/after protocol proving improvement (ticket 05 skeleton).

Pure parts are fully implemented (no I/O): nodeid-keyed diff algorithm per
04 Proposal L113-117, ordered verdict gate per 04 Proposal L119-126, and the
answer-key loader (verify keys extend known_answers per 04 Rulings).

Harness-owned pytest capture (04 Proposal L105-111) lands downstream: the
stubs below raise NotImplementedError until then. Implement calls these;
it never runs its own pytest for verdict purposes.
"""

from __future__ import annotations

import json
from pathlib import Path

_SKELETON = "ticket 05 skeleton"

# pytest-json-report outcomes we treat as red.
_BAD = {"failed", "error"}
_PASS = "passed"


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
    fixed: list[str] = []
    regressed: list[str] = []
    for node in set(baseline) & set(after):
        before, now = baseline[node], after[node]
        if before in _BAD and now == _PASS:
            fixed.append(node)
        elif before == _PASS and (now in _BAD or now == "skipped"):
            regressed.append(node)
    new = sorted(set(after) - set(baseline))
    removed = sorted(set(baseline) - set(after))
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


def run_suite(
    sandbox_dir: str | Path, test_command: str = "pytest -q", label: str = "baseline"
) -> Path:
    """Run the target suite in the sandbox copy; return the JSON report path.

    Harness OWNS this invocation (04 Proposal L105-111). Skeleton stub.
    """
    _ = (sandbox_dir, test_command, label)
    raise NotImplementedError(f"run_suite not implemented ({_SKELETON})")


def check(verify_json_path: str | Path) -> str:
    """Standalone critic gate over a verify.json file. Skeleton stub."""
    _ = verify_json_path
    raise NotImplementedError(f"check not implemented ({_SKELETON})")
