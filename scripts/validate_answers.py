"""Validate every testdata/known_answers/NN-slug.json file.

Checks: parses as JSON, filename matches NN-slug.json, all required fields
present with the right types, accepted_answers items have non-empty
name/why, sources has 2-3 well-formed http(s) URLs, researched_on is a
YYYY-MM-DD date. No extra top-level fields allowed.

Extension (SCHEMA.md, normative): input, expected_wheels, run_type,
better_spec, verify are REQUIRED for suite-run files and OPTIONAL
otherwise. A file is a suite-run file if it contains any extension key
(then ALL extension keys become required); legacy files with none must
still validate exactly as before.

Exit non-zero on any failure (CI relies on this).
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWN = ROOT / "testdata" / "known_answers"

REQUIRED_FIELDS = ("problem", "accepted_answers", "sources", "researched_on", "notes")
EXTENSION_FIELDS = ("input", "expected_wheels", "run_type", "better_spec", "verify")
ALLOWED_FIELDS = REQUIRED_FIELDS + EXTENSION_FIELDS
FILENAME_RE = re.compile(r"^\d{2}-[a-z0-9-]+\.json$")
RUN_TYPES = ("win", "hard", "keep-yours")
INPUT_KINDS = ("repo_url", "idea_text")
BETTER_MODES = ("red_to_green", "new_capability", "measured_gain", "keep_yours")


def is_good_url(url: object) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parts = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def validate_file(path: Path) -> list[str]:
    errors: list[str] = []
    if not FILENAME_RE.match(path.name):
        errors.append(f"{path.name}: filename must match NN-slug.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"{path.name}: invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return [f"{path.name}: top level must be an object"]
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"{path.name}: missing field {field!r}")
    is_suite = any(key in data for key in EXTENSION_FIELDS)
    if is_suite:
        for field in EXTENSION_FIELDS:
            if field not in data:
                errors.append(f"{path.name}: missing field {field!r}")
    for key in data:
        if key not in ALLOWED_FIELDS:
            errors.append(f"{path.name}: unexpected field {key!r}")
    if errors:
        return errors

    if not isinstance(data["problem"], str) or not data["problem"].strip():
        errors.append(f"{path.name}: 'problem' must be a non-empty string")
    answers = data["accepted_answers"]
    if not isinstance(answers, list) or not answers:
        errors.append(f"{path.name}: 'accepted_answers' must be a non-empty list")
    else:
        for i, item in enumerate(answers):
            if not isinstance(item, dict):
                errors.append(f"{path.name}: accepted_answers[{i}] must be an object")
                continue
            for key in ("name", "why"):
                if not isinstance(item.get(key), str) or not item[key].strip():
                    errors.append(
                        f"{path.name}: accepted_answers[{i}].{key} "
                        "must be a non-empty string"
                    )
    sources = data["sources"]
    if not isinstance(sources, list) or not 2 <= len(sources) <= 3:
        errors.append(f"{path.name}: 'sources' must be a list of 2-3 URLs")
    else:
        for url in sources:
            if not is_good_url(url):
                errors.append(f"{path.name}: malformed URL: {url!r}")
    researched = data["researched_on"]
    try:
        date.fromisoformat(researched)
    except (TypeError, ValueError):
        errors.append(
            f"{path.name}: 'researched_on' must be a YYYY-MM-DD date, "
            f"got {researched!r}"
        )
    if not isinstance(data["notes"], str):
        errors.append(f"{path.name}: 'notes' must be a string")
    if is_suite:
        errors.extend(validate_extension(path, data))
    return errors


def validate_extension(path: Path, data: dict) -> list[str]:
    errors: list[str] = []
    name = path.name

    inp = data["input"]
    if not isinstance(inp, dict):
        errors.append(f"{name}: 'input' must be an object")
    else:
        for key in inp:
            if key not in ("kind", "value"):
                errors.append(f"{name}: unexpected field 'input.{key}'")
        if inp.get("kind") not in INPUT_KINDS:
            errors.append(
                f"{name}: 'input.kind' must be exactly one of "
                f"{' | '.join(INPUT_KINDS)}, got {inp.get('kind')!r}"
            )
        if not isinstance(inp.get("value"), str) or not inp["value"].strip():
            errors.append(f"{name}: 'input.value' must be a non-empty string")

    run_type = data["run_type"]
    if run_type not in RUN_TYPES:
        errors.append(
            f"{name}: 'run_type' must be exactly one of "
            f"{' | '.join(RUN_TYPES)}, got {run_type!r}"
        )

    wheels = data["expected_wheels"]
    if not isinstance(wheels, list) or any(
        not isinstance(w, str) or not w.strip() for w in wheels
    ):
        errors.append(
            f"{name}: 'expected_wheels' must be a list of non-empty strings"
        )
    elif run_type in RUN_TYPES:
        if run_type == "keep-yours":
            if wheels != []:
                errors.append(
                    f"{name}: 'expected_wheels' must be [] for "
                    f"'keep-yours' runs, got {wheels!r}"
                )
        elif not wheels:
            errors.append(
                f"{name}: 'expected_wheels' must be a non-empty list "
                f"for '{run_type}' runs"
            )

    spec = data["better_spec"]
    if not isinstance(spec, dict):
        errors.append(f"{name}: 'better_spec' must be an object")
    else:
        for key in spec:
            if key not in ("mode", "tests", "benchmark"):
                errors.append(f"{name}: unexpected field 'better_spec.{key}'")
        mode = spec.get("mode")
        if mode not in BETTER_MODES:
            errors.append(
                f"{name}: 'better_spec.mode' must be exactly one of "
                f"{' | '.join(BETTER_MODES)}, got {mode!r}"
            )
        tests = spec.get("tests")
        if not isinstance(tests, list) or any(
            not isinstance(t, str) or not t.strip() for t in tests
        ):
            errors.append(
                f"{name}: 'better_spec.tests' must be a list of "
                "non-empty strings"
            )
            tests = None
        benchmark = spec.get("benchmark")
        if benchmark is not None and not isinstance(benchmark, dict):
            errors.append(
                f"{name}: 'better_spec.benchmark' must be an object or null, "
                f"got {benchmark!r}"
            )
            benchmark = "invalid"
        if mode in BETTER_MODES and tests is not None and benchmark != "invalid":
            if mode == "keep_yours":
                if tests != []:
                    errors.append(
                        f"{name}: 'better_spec.tests' must be [] for "
                        f"'keep_yours' mode, got {tests!r}"
                    )
                if benchmark is not None:
                    errors.append(
                        f"{name}: 'better_spec.benchmark' must be null for "
                        f"'keep_yours' mode, got {benchmark!r}"
                    )
            elif not tests and not (
                mode == "measured_gain" and isinstance(benchmark, dict)
            ) and not (
                # new_capability: tests don't exist yet; authored at build
                # time, adequacy enforced by the critic (SCHEMA.md).
                mode == "new_capability" and tests == []
            ):
                errors.append(
                    f"{name}: 'better_spec.tests' must be a non-empty list "
                    f"for '{mode}' mode"
                )

    verify = data["verify"]
    if not isinstance(verify, dict):
        errors.append(f"{name}: 'verify' must be an object")
    else:
        for key in verify:
            if key not in (
                "test_command",
                "baseline",
                "authored_tests",
                "zero_regressions",
            ):
                errors.append(f"{name}: unexpected field 'verify.{key}'")
        if not isinstance(verify.get("test_command"), str) or not verify[
            "test_command"
        ].strip():
            errors.append(
                f"{name}: 'verify.test_command' must be a non-empty string"
            )
        baseline = verify.get("baseline")
        if not isinstance(baseline, dict):
            errors.append(f"{name}: 'verify.baseline' must be an object")
        else:
            for key in baseline:
                if key not in ("captured", "tool"):
                    errors.append(
                        f"{name}: unexpected field 'verify.baseline.{key}'"
                    )
            if not isinstance(baseline.get("captured"), bool):
                errors.append(
                    f"{name}: 'verify.baseline.captured' must be a bool, "
                    f"got {baseline.get('captured')!r}"
                )
            if baseline.get("tool") != "pytest-json-report":
                errors.append(
                    f"{name}: 'verify.baseline.tool' must be exactly "
                    f"'pytest-json-report', got {baseline.get('tool')!r}"
                )
        authored = verify.get("authored_tests")
        if not isinstance(authored, list) or any(
            not isinstance(a, str) or not a.strip() for a in authored
        ):
            errors.append(
                f"{name}: 'verify.authored_tests' must be a list of "
                "non-empty strings"
            )
        if verify.get("zero_regressions") is not True:
            errors.append(
                f"{name}: 'verify.zero_regressions' must be true, "
                f"got {verify.get('zero_regressions')!r}"
            )
    return errors


def main() -> int:
    files = sorted(KNOWN.glob("*.json"))
    if not files:
        print("no known-answer files found", file=sys.stderr)
        return 1
    errors: list[str] = []
    for path in files:
        errors.extend(validate_file(path))
    if errors:
        for line in errors:
            print(f"FAIL: {line}", file=sys.stderr)
        print(f"{len(files)} files, {len(errors)} error(s)", file=sys.stderr)
        return 1
    print(f"OK: {len(files)} known-answer files valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
