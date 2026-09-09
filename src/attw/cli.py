"""CLI: `attw analyze <url-or-idea>` end to end, plus per-stage entry points.

Architecture (ticket 05): analyze runs the full pipeline with --dry-run
(report without implement), --mode addition-only/substitution-only/auto,
--sandbox-dir and --out-dir. Per-stage subcommands exist for debugging.
Ticket 13 wired analyze to the real stages per component: decompose ->
find (one query/component) -> evidence (cells) -> rank (winner or
keep-decline) -> implement (temp-clone target, apply) -> verify
(build_verify/write_verify_json); keep-decline and dry-run skip
implement/verify cleanly.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from attw import evidence, find, implement, rank, report, understand, verify
from attw.failures import format_one, make_failure
from attw.find import FindError
from attw.understand import UnderstandError


def _safe(text: object) -> str:
    """Render text printable on narrow consoles (e.g. Windows cp1252).

    GitHub descriptions may contain emoji; replace unencodable chars
    instead of crashing the find subcommand.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    rendered = str(text)
    return rendered.encode(encoding, errors="replace").decode(encoding)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]
    return slug or "analysis"


#: Find hits enriched with evidence per component (ticket 13 chain).
_FIND_LIMIT = 5

#: `git clone` timeout (s) for the sandbox target copy.
_CLONE_TIMEOUT_S = 120


def _clone_target(url: str, *, parent: str | None = None) -> str:
    """Clone a repo_url target into a fresh ``attw-`` sandbox dir.

    ``git clone --depth 1`` into an empty temp dir (05 D3: system temp
    default, ``--sandbox-dir`` override as parent); the original is never
    written, only read. Raises RuntimeError on clone failure.
    """
    sandbox = tempfile.mkdtemp(prefix="attw-", dir=parent)
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", url, sandbox],
        capture_output=True,
        text=True,
        timeout=_CLONE_TIMEOUT_S,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
        shutil.rmtree(sandbox, ignore_errors=True)
        raise RuntimeError(detail or f"git clone failed for {url}")
    return sandbox


def _reap(*paths: str | None) -> None:
    for path in paths:
        if path:
            shutil.rmtree(str(path), ignore_errors=True)


def _cell_value(cells: dict, key: str):
    cell = cells.get(key)
    if isinstance(cell, dict):
        return cell.get("value")
    return cell


def _build_verify_from_sandbox(sandbox: str, test_command: str) -> dict:
    """Assemble verify.json from the harness captures implement left behind.

    implement.apply captures baseline + after via verify.run_suite into
    ``<sandbox>/verify/{baseline,after}.json``; this parses both, attaches
    the fingerprint + heartbeat, runs the ordered gate, and returns the
    verify.json dict. Raises VerifyError when reports are missing (e.g.
    reaped by a revert) or unparseable.
    """
    base = Path(sandbox) / "verify"
    try:
        baseline = verify.parse_report(base / "baseline.json")
    except verify.VerifyError as exc:
        raise verify.VerifyError(
            f"baseline report missing after implement: {exc}",
            code="not_applicable",
        ) from exc
    try:
        after = verify.parse_report(base / "after.json")
    except verify.VerifyError as exc:
        raise verify.VerifyError(
            f"after report missing after implement: {exc}",
            code="not_applicable",
        ) from exc
    baseline["path"] = str(base / "baseline.json")
    after["path"] = str(base / "after.json")
    heartbeat = {
        "present": (base / "heartbeat.jsonl").is_file(),
        "stalled": verify.is_stalled(sandbox)["stalled"],
        "reason": verify.is_stalled(sandbox)["reason"],
    }
    return verify.build_verify(
        fingerprint=verify.fingerprint(sandbox, test_command),
        baseline=baseline,
        after=after,
        authored_paths=(),
        benchmark=None,
        mode="red_to_green",
        sandbox_dir=sandbox,
        heartbeat=heartbeat,
    )


def analyze(
    source: str,
    out_dir: Path | None = None,
    *,
    dry_run: bool = False,
    mode: str = "auto",
    sandbox_dir: str | None = None,
) -> str:
    """Run understand -> find -> evidence -> rank -> implement -> verify.

    Per component: decompose -> find (one query/component) -> evidence
    (cells per hit) -> rank (winner or keep-decline) -> if winner and not
    dry_run: temp-clone the target to a sandbox, implement apply, harness
    after-capture, build_verify/write_verify_json -> report renders the
    cited table + verdict with the verify block. A keep verdict skips
    implement/verify cleanly (no failure); --dry-run stops after report.
    Every stage failure is an exact failure record, downstream-only, and
    the loop continues to the next component. Saves the run record JSON +
    report.md sidecar into out_dir/database, plus per-component
    ``<stem>.verify/<component>/verify.json`` (+ baseline/after copies).
    An understand-stage failure is recorded and stops everything
    downstream-only (no find/evidence/rank output, no implement/verify).
    """
    try:
        components = [dict(c) for c in understand.decompose(source)]
    except UnderstandError as exc:
        results = {
            "input": {"kind": understand.classify_input(source), "value": source},
            "components": [],
            "profile": [],
            "searches": {},
            "candidates": {},
            "problems": [],
            "verify": {},
            "verdict": None,
            "failures": [exc.failure],
            "dry_run": dry_run,
            "mode": mode,
        }
        markdown, _stem = _save(results, source, out_dir)
        return markdown
    kind = understand.classify_input(source)
    test_command = "pytest -q"
    searches: dict[str, list[str]] = {}
    candidates: dict[str, list[dict]] = {}
    failures: list[dict] = []
    # Incumbent evidence (repo_url only): the target repo itself, pooled
    # with challengers so rank can keep-decline before implement.
    incumbent: dict | None = None
    if kind == "repo_url":
        try:
            incumbent = evidence.collect_evidence(
                {"repo_url": source.strip()}
            )
        except ValueError as exc:
            failures.append(
                make_failure(
                    "evidence", "not_applicable",
                    f"incumbent evidence skipped: {exc}",
                )
            )
            incumbent = None
        except Exception as exc:  # noqa: BLE001 — no incumbent, rank as before
            failures.append(
                make_failure(
                    "evidence", "source_down",
                    f"incumbent evidence failed for {source.strip()}: "
                    f"{type(exc).__name__}: {exc}",
                )
            )
            incumbent = None
        else:
            failures.extend(incumbent.get("failures", []))
    blocks: list[dict] = []
    verify_stage: dict[str, tuple] = {}  # component slug -> (verify_data, base, after)
    for component in components:
        problem = component["description"]
        cname = component.get("name", "")
        ckind = component.get("kind", "unknown")
        query = find.component_to_query(component)
        searches[problem] = [query]
        try:
            hits = find.find_for_component(component, limit=_FIND_LIMIT)
        except FindError as exc:
            failures.append(exc.failure)
            candidates[problem] = []
            ranked = rank.rank_candidates([])
            blocks.append(
                {
                    "problem": problem,
                    "kind": ckind,
                    "ranking": ranked["ranking"],
                    "candidates": [],
                    "verdict": ranked["verdict"],
                }
            )
            continue
        candidates[problem] = [dict(h) for h in hits]
        evidences: list[dict] = []
        for hit in hits:
            try:
                collected = evidence.collect_evidence(dict(hit))
            except ValueError as exc:
                failures.append(
                    make_failure(
                        "evidence", "not_applicable",
                        f"evidence skipped {hit.get('full_name', '?')}: {exc}",
                        component=cname,
                    )
                )
                continue
            except Exception as exc:  # noqa: BLE001 — chain records, loop moves on
                failures.append(
                    make_failure(
                        "evidence", "source_down",
                        f"evidence failed for {hit.get('full_name', '?')}: "
                        f"{type(exc).__name__}: {exc}",
                        component=cname,
                    )
                )
                continue
            failures.extend(collected.get("failures", []))
            evidences.append(collected)
        try:
            ranked = rank.rank_candidates(evidences, incumbent=incumbent)
        except Exception as exc:  # noqa: BLE001 — pure logic; guard anyway
            failures.append(
                make_failure(
                    "rank", "not_applicable",
                    f"rank failed for {cname!r}: {exc}",
                    component=cname,
                )
            )
            blocks.append(
                {
                    "problem": problem,
                    "kind": ckind,
                    "ranking": [],
                    "candidates": evidences,
                    "verdict": None,
                }
            )
            continue
        verdict = ranked["verdict"]
        block: dict = {
            "problem": problem,
            "kind": ckind,
            "ranking": ranked["ranking"],
            "candidates": evidences,
            "verdict": verdict,
        }
        blocks.append(block)
        if dry_run:
            continue
        if verdict.get("decision") == "keep" or not verdict.get("winner"):
            continue  # keep-decline: skip implement/verify cleanly (no failure)
        if kind != "repo_url":
            failures.append(
                make_failure(
                    "implement", "not_applicable",
                    "idea-text input has no target repo to integrate into; "
                    "implement skipped.",
                    component=cname,
                )
            )
            continue
        try:
            sandbox = _clone_target(source.strip(), parent=sandbox_dir)
        except Exception as exc:  # noqa: BLE001 — clone/git failure
            failures.append(
                make_failure(
                    "implement", "source_down",
                    f"Cannot clone {source} into a sandbox: {exc}",
                    component=cname,
                )
            )
            continue
        # Suite target from the sandbox (tests/ etc.): a bare `pytest -q`
        # lets the collector wander into docs/images dirs.
        test_command = implement._detect_test_command(sandbox)
        try:
            winner_name = verdict["winner"]
            winner_ev = next(
                (e for e in evidences if e.get("candidate") == winner_name),
                None,
            )
            cells = (winner_ev or {}).get("cells", {})
            winner = {
                "wheel": winner_name,
                "name": winner_name,
                "version_low": _cell_value(cells, "pypi_version"),
                "license": _cell_value(cells, "license_spdx") or "",
                "pypi_url": f"https://pypi.org/project/{winner_name}/",
                "fallbacks": [e["name"] for e in ranked["ranking"][1:3]],
            }
            plan = implement.plan(component, winner, mode)
            receipt = implement.apply(plan, sandbox, test_command)
        except Exception as exc:  # noqa: BLE001 — plan/apply crash
            failures.append(
                make_failure(
                    "implement", "failed-install",
                    f"implement failed for {cname!r}: "
                    f"{type(exc).__name__}: {exc}",
                    component=cname,
                )
            )
            _reap(sandbox)
            continue
        block["implement"] = receipt
        if isinstance(receipt, dict) and receipt.get("failure"):
            failures.append(receipt["failure"])
        try:
            verify_data = _build_verify_from_sandbox(sandbox, test_command)
        except verify.VerifyError as exc:
            failures.append(exc.failure)
            _reap(sandbox, (receipt or {}).get("snapshot"))
            continue
        except Exception as exc:  # noqa: BLE001 — chain records, loop moves on
            failures.append(
                make_failure(
                    "verify", "not_applicable",
                    f"verify failed for {cname!r}: "
                    f"{type(exc).__name__}: {exc}",
                    component=cname,
                )
            )
            _reap(sandbox, (receipt or {}).get("snapshot"))
            continue
        block["verify"] = verify_data
        try:
            base_text = (Path(sandbox) / "verify" / "baseline.json").read_text(
                encoding="utf-8"
            )
        except OSError:
            base_text = ""
        try:
            after_text = (Path(sandbox) / "verify" / "after.json").read_text(
                encoding="utf-8"
            )
        except OSError:
            after_text = ""
        verify_stage[_slug(cname or problem)] = (verify_data, base_text, after_text)
        gate = verify_data.get("verdict")
        if gate == "better":
            diff = verify_data.get("diff", {})
            outcomes = ((verify_data.get("after") or {}).get("outcomes")) or {}
            gains = list(diff.get("fixed", []))
            gains += [n for n in diff.get("new", []) if outcomes.get(n) == "passed"]
            if gains:
                block["gain_tests"] = sorted(set(gains))
        elif gate in ("fail", "stalled"):
            reasons = "; ".join((verify_data.get("gate") or {}).get("reasons", []))
            failures.append(
                make_failure(
                    "verify",
                    "regression" if gate == "fail" else "stalled",
                    f"gate {gate} for {cname!r}: {reasons}"[:2000],
                    component=cname,
                )
            )
        _reap(sandbox, (receipt or {}).get("snapshot"))
    gates = [
        b["verify"]["verdict"] for b in blocks if isinstance(b.get("verify"), dict)
    ]
    keeps = sum(
        1 for b in blocks
        if isinstance(b.get("verdict"), dict) and b["verdict"].get("decision") == "keep"
    ) + sum(1 for g in gates if g == "keep-yours")
    impl_failed = any(
        isinstance(b.get("implement"), dict) and not b["implement"].get("ok")
        for b in blocks
    )
    problems = [c["description"] for c in components]
    if dry_run:
        overall = None
    elif "fail" in gates or "stalled" in gates or impl_failed:
        overall = f"fail: {problems[0] if problems else source} did not verify clean"
    elif "better" in gates:
        winners = [
            b["verdict"]["winner"] for b in blocks
            if isinstance(b.get("verify"), dict)
            and b["verify"].get("verdict") == "better"
            and isinstance(b.get("verdict"), dict) and b["verdict"].get("winner")
        ]
        overall = f"better: {', '.join(winners) or 'gains proven (verify block)'}"
    elif keeps:
        overall = "keep-yours: no challenger wins; decline"
    elif failures:
        signal = next(
            (f for f in failures
             if f.get("stage") in ("understand", "find", "rank",
                                   "implement", "verify")),
            failures[0],
        )
        overall = f"fail: {signal.get('reason', 'stage failures')}"[:500]
    else:
        overall = None
    merged: dict = {}
    if verify_stage:
        fixed: set[str] = set()
        regressed: set[str] = set()
        new: set[str] = set()
        removed: list[dict] = []
        outcomes: dict[str, str] = {}
        order = {"fail": 0, "stalled": 1, "better": 2, "keep-yours": 3}
        best = None
        for _slug_key, (vdata, _b, _a) in verify_stage.items():
            diff = vdata.get("diff", {})
            fixed |= set(diff.get("fixed", []))
            regressed |= set(diff.get("regressed", []))
            new |= set(diff.get("new", []))
            removed += list(diff.get("removed", []))
            outcomes.update((vdata.get("after") or {}).get("outcomes") or {})
            verdict = vdata.get("verdict")
            if best is None or order.get(verdict, 9) < order.get(best, 9):
                best = verdict
        merged = {
            "test_command": test_command,
            "verdict": best,
            "diff": {
                "fixed": sorted(fixed),
                "regressed": sorted(regressed),
                "new": sorted(new),
                "removed": removed,
            },
            "outcomes": outcomes,
        }
    results = {
        "input": {"kind": kind, "value": source},
        "components": components,
        "profile": problems,
        "searches": searches,
        "candidates": candidates,
        "problems": blocks,
        "verify": merged,
        "verdict": overall,
        "failures": failures,
        "dry_run": dry_run,
        "mode": mode,
    }
    markdown, stem = _save(results, source, out_dir)
    if verify_stage:
        saved = Path(out_dir) if out_dir else Path("database")
        for slug_key, (vdata, base_text, after_text) in verify_stage.items():
            dest = saved / f"{stem}.verify" / slug_key
            dest.mkdir(parents=True, exist_ok=True)
            verify.write_verify_json(dest, vdata)
            if base_text:
                (dest / "baseline.json").write_text(base_text, encoding="utf-8")
            if after_text:
                (dest / "after.json").write_text(after_text, encoding="utf-8")
    return markdown


def _save(
    results: dict, source: str, out_dir: Path | None
) -> tuple[str, str]:
    """Write the run-record JSON + report.md sidecar.

    Returns ``(markdown, stem)`` so analyze can co-locate per-component
    ``<stem>.verify/`` artifacts. An uncited verdict claim
    (report.ReportError) is recorded as a failure and the sidecar renders
    degraded (verdict withheld) rather than silent prose — never a crash,
    never an unwritten sidecar.
    """
    try:
        markdown = report.render_markdown(results)
    except report.ReportError as exc:
        results["failures"].append(exc.failure)
        markdown = report.render_markdown(results, enforce=False)
    saved = Path(out_dir) if out_dir else Path("database")
    saved.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    stem = f"{stamp}-{_slug(source)}"
    (saved / f"{stem}.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    (saved / f"{stem}.report.md").write_text(markdown, encoding="utf-8")
    return markdown, stem


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
    p_r.add_argument(
        "problem",
        help="Problem string, or path to a candidates+cells JSON file "
        "({'candidates': [...], 'incumbent': {...} or [...]}).",
    )

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
            for component in understand.decompose(args.source):
                sites = ", ".join(component["call_sites"][:5])
                print(
                    f"- {component['name']} [{component['kind']}, "
                    f"confidence={component['confidence']}]"
                )
                print(f"  {component['description']}")
                if sites:
                    print(f"  call sites: {sites}")
        elif args.command == "find":
            try:
                hits = find.search(args.problem)
            except FindError as exc:
                print(f"find failed: {format_one(exc.failure)}")
                if exc.failure.get("detail"):
                    print(exc.failure["detail"])
                return 1
            for hit in hits:
                print(f"- {_safe(hit['full_name'])} ({hit['stars']} stars)")
                print(f"  {_safe(hit['description'])}")
                print(f"  {hit['url']}")
        elif args.command == "evidence":
            candidate: dict | str = args.candidate
            maybe_path = Path(args.candidate)
            if maybe_path.is_file():
                candidate = json.loads(maybe_path.read_text(encoding="utf-8"))
            elif args.candidate.startswith(("http://", "https://")):
                candidate = {"repo_url": args.candidate}
            else:
                candidate = {"candidate": args.candidate}
            try:
                print(json.dumps(evidence.collect_evidence(candidate), indent=2))
            except ValueError as exc:
                print(f"evidence failed: {exc}")
                return 1
        elif args.command == "rank":
            maybe_path = Path(args.problem)
            if maybe_path.is_file():
                payload = json.loads(maybe_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    candidates = payload.get("candidates", [])
                    incumbent = payload.get("incumbent")
                else:
                    candidates, incumbent = payload, None
                result = rank.rank_candidates(candidates, incumbent=incumbent)
                for i, entry in enumerate(result["ranking"], start=1):
                    print(
                        f"{i}. {entry['name']} score={entry['score']} "
                        f"(P0={entry['p0']} P1={entry['p1']} "
                        f"P2={entry['p2']} penalty={entry['penalty']} "
                        f"confidence={entry['confidence']})"
                    )
                    if entry["license_warning"]:
                        print(f"   license: {entry['license_warning']}")
                verdict = result["verdict"]
                print(
                    f"verdict: {verdict['decision']}"
                    f" winner={verdict['winner']} margin={verdict['margin']}"
                )
                if verdict["dissent"]:
                    print(f"dissent: {verdict['dissent']}")
            else:
                for i, opt in enumerate(rank.rank(args.problem), start=1):
                    print(f"{i}. {opt['name']} — {opt['why']}")
        elif args.command == "report":
            data = json.loads(Path(args.run_json).read_text(encoding="utf-8"))
            try:
                print(report.render_markdown(data))
            except report.ReportError as exc:
                print(f"report failed: {format_one(exc.failure)}")
                print(report.render_markdown(data, enforce=False))
                return 1
        elif args.command == "implement":
            try:
                plan = implement.plan(
                    {"component": args.component}, {"wheel": args.wheel}
                )
                receipt = implement.apply(plan, args.sandbox_dir)
            except Exception as exc:
                print(f"implement failed: {exc}")
                return 1
            print(json.dumps(receipt, indent=2))
            return 0 if receipt.get("ok") else 1
        elif args.command == "verify":
            try:
                result = verify.check(args.verify_json)
            except (verify.VerifyError, FileNotFoundError, ValueError) as exc:
                print(f"verify failed: {exc}")
                return 1
            print(result)
            return 0 if result.startswith(("verify: better",
                                           "verify: keep-yours")) else 1
        elif args.command == "refresh-cache":
            print(evidence.refresh_weekly_cache())
    except UnderstandError as exc:
        print(f"understand failed: {format_one(exc.failure)}")
        if exc.failure.get("detail"):
            print(exc.failure["detail"])
        return 1
    except NotImplementedError as exc:
        print(f"not implemented yet ({exc})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
