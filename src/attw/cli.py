"""CLI: `attw analyze <url-or-idea>` runs the 5 stages end to end.

Stages are stubs returning fixture data — the point is the skeleton runs
and prints a report without crashing. The results dict is also saved to
database/<timestamp>-<slug>.json (one JSON file per analysis).
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from attw import find, rank, report, understand


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]
    return slug or "analysis"


def analyze(source: str, out_dir: Path | None = None) -> str:
    """Run understand -> find -> evidence -> rank -> report. Return Markdown."""
    problems = understand.profile(source)
    searches = {problem: find.search(problem) for problem in problems}
    # NOTE: evidence stage has real fetchers, but nothing calls them yet —
    # find-stage returns no candidates, so there is nothing to enrich.
    results = {
        "input": source,
        "profile": problems,
        "searches": searches,
        "problems": [
            {"problem": problem, "options": rank.rank(problem)}
            for problem in problems
        ],
    }
    saved = out_dir or Path("database")
    saved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    (saved / f"{stamp}-{_slug(source)}.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    return report.render_markdown(results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="attw")
    sub = parser.add_subparsers(dest="command", required=True)
    p_analyze = sub.add_parser("analyze", help="Analyze a repo URL or idea.")
    p_analyze.add_argument("source", help="Repo URL or plain-text project idea.")
    args = parser.parse_args(argv)
    if args.command == "analyze":
        print(analyze(args.source))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
