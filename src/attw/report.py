"""Report stage: render ranked results as readable Markdown (ticket 11).

Produces, per component: (1) a comparison table (wheel x criteria, every
cell citing its evidence source link), (2) a short prose verdict stating
addition vs substitution, the winner, ``license_warning`` prose where
applicable, and gains cited by pytest node id, plus (3) failure-record
sections. Output lands twice via ``cli._save``: the run-record JSON
``database/<stamp>-<slug>.json`` and the ``<stem>.report.md`` sidecar.

UNCITED-CLAIM-IS-A-BUG: verdict claims that are checkable in code raise
:exc:`ReportError` (carrying the exact ``report/uncited-claim`` failure
record) instead of rendering silent prose. Checked claims: the winner
names a ranked wheel; dissent needs a runner-up row; ``license_warning``
prose needs a backing entry warning; each gain node id needs
verify-block backing. Plain-string (legacy) verdicts are not checkable
and pass through untouched. ``enforce=False`` renders a degraded report
with the bad verdict withheld (used by the CLI after recording the
failure) instead of raising.

Input shapes: legacy ``options`` blocks (``testdata/example_results.json``)
keep their narrow table; ``ranking`` blocks (entries from
``rank.rank_candidates`` plus ``candidates`` evidence dicts from
``evidence.collect_evidence``) get the wide cited table.
"""

from __future__ import annotations

import urllib.parse

from attw.failures import make_failure

STAGE = "report"

#: Failure code for a verdict claim with no backing evidence cell.
CODE_UNCITED = "uncited-claim"


class ReportError(Exception):
    """render_markdown() refused an uncited claim; carries `.failure`."""

    def __init__(self, failure: dict):
        super().__init__(failure.get("reason", "report failed"))
        self.failure = failure


def _fail(reason: str, component: str = "", detail: str = "") -> ReportError:
    return ReportError(
        make_failure(STAGE, CODE_UNCITED, reason, detail=detail,
                     component=component)
    )


# Signal -> column label for the wheel x criteria table. Mirrors the
# evidence.collect_evidence cell keys (05 D4: value + source link).
_CRITERIA: tuple[tuple[str, str], ...] = (
    ("stars", "Stars"),
    ("downloads_last_month", "DL/mo"),
    ("last_commit_date", "Pushed"),
    ("release_date", "Released"),
    ("open_issues", "Issues"),
    ("dep_count", "Deps"),
    ("so_count", "SO"),
    ("hn_count", "HN"),
    ("heuristics", "Docs"),
    ("dependents_count", "Dependents"),
    ("awesome_hits", "Awesome"),
    ("vulns", "CVEs"),
)


def _sanitize(text: object) -> str:
    """Keep one value inside its Markdown table cell."""
    return str(text).replace("|", "/").replace("\n", " ").strip()


def _cite(source: object) -> str:
    """Render an evidence source as a link; every cell cites something."""
    text = str(source or "").strip()
    if text.startswith(("http://", "https://")):
        host = urllib.parse.urlparse(text).netloc or "link"
        return f"[{host}]({text})"
    if text:
        return f"({text})"
    return "(source unknown)"


def _fmt_value(signal: str, value: object) -> str:
    """Compact one evidence value for a table cell."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4g}"
    if signal in ("last_commit_date", "release_date") and isinstance(value, str):
        return value[:10]
    if signal == "vulns" and isinstance(value, list):
        severities = [str(v.get("severity", "?")) for v in value
                      if isinstance(v, dict)]
        detail = ", ".join(severities) if severities else ""
        return f"{len(value)} advisories ({detail})" if detail else (
            f"{len(value)} advisories" if value else "none")
    if signal == "heuristics" and isinstance(value, dict):
        true = sum(1 for v in value.values() if v is True)
        return f"{true}/{len(value)} flags"
    if signal == "awesome_hits" and isinstance(value, dict):
        count = value.get("count", value)
        return str(count)
    if isinstance(value, (list, tuple)):
        return f"{len(value)} items"
    if isinstance(value, dict):
        return _sanitize(str(value))[:60]
    text = _sanitize(value)
    return text[:80] if len(text) > 80 else text


def _fmt_cell(cell: object) -> str:
    """Render one evidence cell as ``value + source cite`` (never bare)."""
    if cell is None:
        return "-"
    if not isinstance(cell, dict):
        return _sanitize(cell)
    value = cell.get("value")
    source = cell.get("source", "")
    if value is None:
        missing = cell.get("missing") or "missing"
        return f"n/a ({missing}) {_cite(source)}"
    rendered = _fmt_value(cell.get("_signal", ""), value)
    if cell.get("stale"):
        rendered += " stale"
    return f"{rendered} {_cite(source)}"


def _evidence_cell(evidence: dict) -> str:
    if not evidence:
        return "-"
    return ", ".join(f"{k}={v}" for k, v in evidence.items())


def _input_lines(value: object) -> list[str]:
    if isinstance(value, dict):
        kind = value.get("kind", "?")
        return [f"_{kind}_", "", _sanitize(value.get("value", "-") or "-")]
    return [_sanitize(value or "-")]


def _verify_nodes(results: dict) -> set[str] | None:
    """Node ids backing gain claims (fixed + passing new), or None."""
    verify = results.get("verify")
    if not isinstance(verify, dict):
        return None
    diff = verify.get("diff")
    if not isinstance(diff, dict):
        diff = verify
    outcomes = verify.get("outcomes", {})
    if not isinstance(outcomes, dict):
        outcomes = diff.get("outcomes", {})
    if not isinstance(outcomes, dict):
        outcomes = {}
    nodes = {str(n) for n in (diff.get("fixed") or [])}
    for node in diff.get("new") or []:
        if not outcomes or outcomes.get(node) in ("passed", "pass", True):
            nodes.add(str(node))
    return nodes


def _check_block(block: dict, verify_nodes: set[str] | None) -> None:
    """Raise ReportError when a checkable verdict claim lacks backing."""
    verdict = block.get("verdict")
    if verdict is None or isinstance(verdict, str):
        return  # nothing structured to check
    problem = block.get("problem", "-")
    names = [e.get("name") for e in block.get("ranking", [])]
    names += [o.get("name") for o in block.get("options", [])]
    decision = verdict.get("decision", "recommend")
    winner = verdict.get("winner")
    if decision == "recommend" and winner is not None and winner not in names:
        raise _fail(
            f"verdict names winner {winner!r} for {problem!r} "
            "with no backing ranking row/cell",
            component=str(problem),
        )
    if verdict.get("dissent") and len(block.get("ranking", [])) < 2:
        raise _fail(
            f"verdict records dissent for {problem!r} with no runner-up row",
            component=str(problem),
        )
    claimed_warning = verdict.get("license_warning") or block.get(
        "license_warning")
    if claimed_warning:
        backed = any(
            e.get("license_warning") for e in block.get("ranking", [])
        ) or any(o.get("license_warning") for o in block.get("options", []))
        if not backed:
            raise _fail(
                f"license_warning prose for {problem!r} has no backing "
                "entry warning",
                component=str(problem),
            )
    gains = block.get("gain_tests", []) or verdict.get("gains", [])
    if gains and verify_nodes is None:
        raise _fail(
            f"gain node ids for {problem!r} cited with no verify block "
            "to back them",
            component=str(problem),
            detail=", ".join(str(g) for g in gains),
        )
    if gains and verify_nodes is not None:
        orphaned = [str(g) for g in gains if str(g) not in verify_nodes]
        if orphaned:
            raise _fail(
                f"gain node ids for {problem!r} lack verify backing: "
                + ", ".join(orphaned),
                component=str(problem),
            )


def _ranking_table(block: dict) -> list[str]:
    """Wide wheel x criteria table; every cell cites its evidence source."""
    header = ["Wheel", "Score"] + [label for _, label in _CRITERIA]
    lines = ["| " + " | ".join(header) + " |",
             "| " + " | ".join("---" for _ in header) + " |"]
    by_name = {}
    for cand in block.get("candidates", []):
        if isinstance(cand, dict):
            name = cand.get("candidate") or cand.get("name")
            if name:
                by_name[str(name)] = cand
    for entry in block.get("ranking", []):
        name = str(entry.get("name", "-"))
        cells = by_name.get(name, {}).get("cells", {})
        if not isinstance(cells, dict):
            cells = {}
        row = [_sanitize(name), _sanitize(entry.get("score", "-"))]
        for signal, _label in _CRITERIA:
            cell = cells.get(signal)
            if isinstance(cell, dict):
                cell = {**cell, "_signal": signal}
            row.append(_fmt_cell(cell))
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _license_prose(block: dict, winner: str | None) -> str:
    """license_warning prose for the winner, citing the license cell."""
    for entry in block.get("ranking", []):
        if entry.get("name") == winner and entry.get("license_warning"):
            prose = f"License note: {_sanitize(entry['license_warning'])}"
            for cand in block.get("candidates", []):
                if not isinstance(cand, dict):
                    continue
                if (cand.get("candidate") or cand.get("name")) != winner:
                    continue
                cells = cand.get("cells", {})
                lic = cells.get("license_spdx") if isinstance(cells, dict) else None
                if isinstance(lic, dict) and lic.get("source"):
                    prose += f" {_cite(lic['source'])}"
                break
            return prose
    claimed = block.get("license_warning")
    if isinstance(claimed, str) and claimed:
        return f"License note: {_sanitize(claimed)}"
    return ""


def _block_verdict_lines(block: dict, verify_nodes: set[str] | None,
                         ) -> list[str]:
    """Prose verdict for one component (winner/dissent/gains all cited)."""
    verdict = block.get("verdict")
    problem = str(block.get("problem", "-"))
    kind = str(block.get("kind", "unknown"))
    if verdict is None:
        return []
    if isinstance(verdict, str):
        return [f"### {problem}", "", verdict, ""]
    decision = verdict.get("decision", "recommend")
    winner = verdict.get("winner")
    reason = verdict.get("reason", "")
    lines = [f"### {problem} ({kind})", ""]
    if decision == "keep":
        lines.append(f"Keep yours — no challenger wins for {problem}. "
                     f"{reason}".rstrip())
    else:
        verb = {"substitution": "replace with", "addition": "add"}.get(
            kind, "adopt")
        lines.append(f"{kind.capitalize()}: {verb} **{winner}**. "
                     f"{reason}".rstrip())
        lic_prose = _license_prose(block, winner)
        if lic_prose:
            lines.append(lic_prose)
        gains = block.get("gain_tests", []) or verdict.get("gains", [])
        if gains:
            cited = ", ".join(f"`{g}`" for g in gains)
            lines.append(f"Gains proven by: {cited} (verify block).")
        if verdict.get("dissent"):
            lines.append(f"Dissent: {verdict['dissent']} (scores above).")
        margin = verdict.get("margin")
        if margin is not None:
            lines.append(f"Margin: {margin} (per-component scores above).")
    return lines + [""]


def render_markdown(results: dict, *, enforce: bool = True) -> str:
    """Render a results dict as a Markdown report string.

    With ``enforce=True`` (default) an uncited verdict claim raises
    :exc:`ReportError`; with ``enforce=False`` the bad verdict is
    withheld in prose and its failure record joins the Failures section.
    """
    withheld: list[dict] = []
    verify_nodes = _verify_nodes(results)
    lines = ["# AI_TAKE_THE_WHEEL report", ""]
    lines += ["## Input", ""] + _input_lines(results.get("input", "-")) + [""]

    components = results.get("components", [])
    if components:
        lines += ["## Components", ""]
        for comp in components:
            if isinstance(comp, dict):
                lines.append(
                    f"- {comp.get('name', '-')} "
                    f"[{comp.get('kind', 'unknown')}]: "
                    f"{_sanitize(comp.get('description', '-'))}")
        lines += [""]

    profile = results.get("profile", [])
    lines += ["## Profile", ""]
    lines += [f"- {p}" for p in profile] or ["- (no problems)"]
    lines += [""]

    searches = results.get("searches", {})
    lines += ["## Searches", ""]
    if searches:
        for problem, queries in searches.items():
            lines.append(f"- {problem}:")
            lines += [f"  - `{q}`" for q in queries]
    else:
        lines.append("- (nothing searched)")
    lines += [""]

    for i, block in enumerate(results.get("problems", []), start=1):
        kind = block.get("kind", "unknown")
        kind_suffix = f" ({kind})" if kind != "unknown" else ""
        lines += [f"## Problem {i}: {block.get('problem', '-')}"
                  f"{kind_suffix}", ""]
        if block.get("ranking"):
            lines += _ranking_table(block) + [""]
        elif block.get("options"):
            lines += [
                "| Rank | Option | Why | Evidence | Source |",
                "| --- | --- | --- | --- | --- |",
            ]
            for rank, opt in enumerate(block.get("options", []), start=1):
                source = (f"{opt.get('source', '-')} "
                          f"[{opt.get('source_tag', '?')}]")
                lines.append(
                    f"| {rank} | {opt.get('name', '-')} | {opt.get('why', '-')}"
                    f" | {_evidence_cell(opt.get('evidence', {}))} | "
                    f"{source} |")
            lines += [""]
        try:
            _check_block(block, verify_nodes)
        except ReportError as exc:
            if enforce:
                raise
            withheld.append(exc.failure)
            lines += [f"### {block.get('problem', '-')} ({kind})", "",
                      f"Verdict withheld — uncited claim: {exc.failure['reason']}.",
                      ""]
        else:
            lines += _block_verdict_lines(block, verify_nodes)

    # Verdict: prose winner argument; every claim cites an evidence cell
    # (map bar). Omitted when None (skeleton runs have no verdict yet).
    verdict = results.get("verdict")
    if verdict:
        lines += ["## Verdict", "", str(verdict), ""]

    verify = results.get("verify")
    if isinstance(verify, dict) and verify:
        lines += ["## Verify", ""]
        if verify.get("test_command"):
            lines.append(f"Test command: `{verify['test_command']}`")
        if verify.get("verdict"):
            lines.append(f"Gate: `{verify['verdict']}`")
        diff = verify.get("diff")
        if isinstance(diff, dict):
            for key in ("fixed", "regressed", "new"):
                nodes = diff.get(key) or []
                rendered = ", ".join(f"`{n}`" for n in nodes) or "—"
                lines.append(f"{key.capitalize()}: {rendered}")
        lines += [""]

    failures = list(results.get("failures", [])) + withheld
    if failures:
        lines += ["## Failures", ""]
        lines += ["| Stage | Code | Reason |", "| --- | --- | --- |"]
        for failure in failures:
            lines.append(
                f"| {failure.get('stage', '-')} | {failure.get('code', '-')}"
                f" | {_sanitize(failure.get('reason', '-'))} |")
        lines += [""]
    return "\n".join(lines).rstrip() + "\n"
