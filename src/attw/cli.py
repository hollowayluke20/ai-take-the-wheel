"""CLI: `attw analyze <url-or-idea>` end to end, plus per-stage entry points.

Architecture (ticket 05): analyze runs the full pipeline with --dry-run
(report without implement), --mode addition-only/substitution-only/auto,
--sandbox-dir and --out-dir. Per-stage subcommands exist for debugging;
stages that need network or a sandbox (evidence/implement/verify bodies,
cache refresh) raise NotImplementedError until their build tickets.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from attw import evidence, find, implement, rank, report, understand, verify
from attw.failures import make_failure


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]
    return slug or "analysis"


def analyze(
    source: str,
    out_dir: Path | None = None,
    *,
    dry_run: bool = False,
    mode: str = "auto",
    sandbox_dir: str | None = None,
) -> str:
    """Run understand -> find -> evidence -> rank -> report. Return Markdown.

    Unless dry_run, also attempts implement + verify; skeleton stages raise
    NotImplementedError, recorded as failure records (downstream-only).
    Saves the run record JSON + report.md sidecar into out_dir/database.
    """
    problems = understand.profile(source)
    searches = {problem: find.search(problem) for problem in problems}
    # NOTE: evidence stage has real fetchers, but nothing calls them yet —
    # find-stage returns no candidates, so there is nothing to enrich.
    failures: list[dict] = []
    if not dry_run:
        try:
            plan = implement.plan({"problem": problems[0] if problems else ""}, {})
            implement.apply(plan, sandbox_dir or "attw-sandbox")
        except NotImplementedError as exc:
            failures.append(make_failure("implement", "skeleton", str(exc)))
        try:
            verify.run_suite(sandbox_dir or "attw-sandbox")
        except NotImplementedError as exc:
            failures.append(make_failure("verify", "skeleton", str(exc)))
    results = {
        "input": {"kind": understand.classify_input(source), "value": source},
        "profile": problems,
        "searches": searches,
        "problems": [
            {"problem": problem, "options": rank.rank(problem)}
            for problem in problems
        ],
        "verdict": None,
        "failures": failures,
        "dry_run": dry_run,
        "mode": mode,
    }
    saved = Path(out_dir) if out_dir else Path("database")
    saved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    stem = f"{stamp}-{_slug(source)}"
    (saved / f"{stem}.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    markdown = report.render_markdown(results)
    (saved / f"{stem}.report.md").write_text(markdown, encoding="utf-8")
    return markdown


def build_parser() -> argparse.ArgumentParser:
    """Build the attw argument parser (also used by skeleton tests)."""
    parser = argparse.ArgumentParser(prog="attw")
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="Analyze a repo URL or idea.")
    p_analyze.add_argument("source", help="Repo URL or plain-text project idea.")
    p_analyze.add_argument(
        "--dry-run", action="store_true", help="Report without implement/verify."
    )
    p_analyze.add_argument(
        "--mode",
        choices=("auto", "addition-only", "substitution-only"),
        default="auto",
        help="Restrict implement to additions or substitutions.",
    )
    p_analyze.add_argument("--sandbox-dir", default=None, help="Sandbox location.")
    p_analyze.add_argument("--out-dir", default=None, help="Run-record output dir.")

    p_u = sub.add_parser("understand", help="Profile an input into problems.")
    p_u.add_argument("source", help="Repo URL or plain-text project idea.")

    p_f = sub.add_parser("find", help="Find candidate wheels for a problem.")
    p_f.add_argument("problem", help="Problem string.")

    p_e = sub.add_parser("evidence", help="Collect evidence for a candidate.")
    p_e.add_argument("candidate", help="Candidate name or JSON file.")

    p_r = sub.add_parser("rank", help="Rank options for a problem.")
    p_r.add_argument("problem", help="Problem string.")

    p_rep = sub.add_parser("report", help="Render a run-record JSON as Markdown.")
    p_rep.add_argument("run_json", help="Path to a database run-record JSON file.")

    p_i = sub.add_parser("implement", help="Integrate a winner (sandbox only).")
    p_i.add_argument("--component", required=True, help="Component name.")
    p_i.add_argument("--wheel", required=True, help="Winning wheel name.")
    p_i.add_argument("--sandbox-dir", required=True, help="Sandbox location.")

    p_v = sub.add_parser("verify", help="Check a verify.json against the gate.")
    p_v.add_argument("verify_json", help="Path to a verify.json file.")
    p_v.add_argument("--check", action="store_true", help="Run the critic gate.")

    sub.add_parser("refresh-cache", help="Weekly SO/HN/awesome cache refresh.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch subcommands. NotImplementedError -> message + exit 1."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "analyze":
            print(
                analyze(
                    args.source,
                    Path(args.out_dir) if args.out_dir else None,
                    dry_run=args.dry_run,
                    mode=args.mode,
                    sandbox_dir=args.sandbox_dir,
                )
            )
        elif args.command == "understand":
            for problem in understand.profile(args.source):
                print(f"- {problem}")
        elif args.command == "find":
            for hit in find.search(args.problem):
                print(f"- {hit}")
        elif args.command == "evidence":
            print(evidence.collect_evidence({"candidate": args.candidate}))
        elif args.command == "rank":
            for i, opt in enumerate(rank.rank(args.problem), start=1):
                print(f"{i}. {opt['name']} — {opt['why']}")
        elif args.command == "report":
            data = json.loads(Path(args.run_json).read_text(encoding="utf-8"))
            print(report.render_markdown(data))
        elif args.command == "implement":
            plan = implement.plan(
                {"component": args.component}, {"wheel": args.wheel}
            )
            print(implement.apply(plan, args.sandbox_dir))
        elif args.command == "verify":
            print(verify.check(args.verify_json))
        elif args.command == "refresh-cache":
            print(evidence.refresh_weekly_cache())
    except NotImplementedError as exc:
        print(f"not implemented yet ({exc})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
