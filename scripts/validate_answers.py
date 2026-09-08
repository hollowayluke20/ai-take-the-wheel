"""Validate every testdata/known_answers/NN-slug.json file.

Checks: parses as JSON, filename matches NN-slug.json, all required fields
present with the right types, accepted_answers items have non-empty
name/why, sources has 2-3 well-formed http(s) URLs, researched_on is a
YYYY-MM-DD date. No extra top-level fields allowed.

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
FILENAME_RE = re.compile(r"^\d{2}-[a-z0-9-]+\.json$")


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
    for key in data:
        if key not in REQUIRED_FIELDS:
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
