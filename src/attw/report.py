"""Report stage: render ranked results as readable Markdown.

Pure formatting, no logic. Input shape (see testdata/example_results.json):

{
  "input": str,                       # repo URL or idea text
  "profile": [str, ...],              # problems found by understand-stage
  "searches": {problem: [query...]},  # what find-stage searched for
  "problems": [
    {"problem": str,
     "options": [{"name": str, "why": str, "source": str,
                  "source_tag": str, "evidence": {k: v}}]}
  ]
}
"""

from __future__ import annotations


def _evidence_cell(evidence: dict) -> str:
    if not evidence:
        return "-"
    return ", ".join(f"{k}={v}" for k, v in evidence.items())


def render_markdown(results: dict) -> str:
    """Render a results dict as a Markdown report string."""
    lines = ["# AI_TAKE_THE_WHEEL report", ""]
    lines += ["## Input", "", str(results.get("input", "-")), ""]

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
        lines += [f"## Problem {i}: {block.get('problem', '-')}", ""]
        lines += [
            "| Rank | Option | Why | Evidence | Source |",
            "| --- | --- | --- | --- | --- |",
        ]
        for rank, opt in enumerate(block.get("options", []), start=1):
            source = f"{opt.get('source', '-')} [{opt.get('source_tag', '?')}]"
            lines.append(
                f"| {rank} | {opt.get('name', '-')} | {opt.get('why', '-')}"
                f" | {_evidence_cell(opt.get('evidence', {}))} | {source} |"
            )
        lines += [""]
    return "\n".join(lines).rstrip() + "\n"
