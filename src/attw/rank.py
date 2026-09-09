"""Rank stage: pure-logic ranker (ticket 10, implements 02 Proposal L168-188).

Pure logic, no I/O. Scoring rule (02 L172-188, literal):

- Log10-relative norms, per-component candidate set (max in set = 1):
  ``dl = log10(1 + last_month) / log10(1 + max_last_month)``; ``stars_n``
  and ``forks_n`` use the same log10-relative norm; ``fresh_n``,
  ``release_n`` and ``issues_n`` use ``1/(1 + d/180)`` / ``1/(1 + open/100)``.
- ``P0 = mean(stars_n, dl, fresh_n, release_n, issues_n)`` (5 signals, equal;
  ``forks_n`` is computed for the breakdown but is NOT in P0 per the 02 text).
- ``P1 = mean(dep_n, so_n, hn_n, docs_n)``; ``P2 = mean(dependents_n,
  awesome_n)``.
- ``score = 10*P0 + 3*P1 + 1*P2 - penalty``; CVE penalty 2.0 per
  HIGH/CRITICAL, 0.5 per MEDIUM, capped at 4.0, never a veto.
- License: zero numeric effect, prose ``license_warning`` only.
- Missing cells are excluded from their tier mean (denominator shrinks);
  ``confidence = complete / 11`` is display-only (05 D4), never multiplied
  into the score.

Input candidates accept :func:`attw.evidence.collect_evidence` dicts
(``{"candidate", "cells": {key: {"value": ...}}, "license_warning"}``) or
plain ``{"name", "cells": {key: raw-value}}`` dicts.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

W_P0 = 10.0
W_P1 = 3.0
W_P2 = 1.0

CVE_HIGH_CRIT = 2.0
CVE_MEDIUM = 0.5
CVE_CAP = 4.0

# Margin below which the verdict records dissent naming the runner-up (05 D5).
DISSENT_MARGIN = 1.0

# The 5 repo-content heuristic flags behind docs_n. collect_evidence emits a
# 6th flag (requires_python_bound) which duplicates the P0 requires_python
# signal, so docs_n uses these 5 only.
DOC_FLAGS = ("readme", "docs", "tests", "py_typed", "changelog")

# Scored signals: 5 P0 + 4 P1 + 2 P2 (confidence denominator).
TOTAL_SCORED = 11


def _raw(cells: dict, key: str):
    """Unwrap an evidence cell (``{"value": ...}``) or a plain raw value."""
    if not isinstance(cells, dict) or key not in cells:
        return None
    cell = cells[key]
    if isinstance(cell, dict) and "value" in cell:
        return cell["value"]
    return cell


def _num(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def _log_norm(value: float | None, vmax: float | None) -> float | None:
    """log10(1+v)/log10(1+vmax); None when the signal (or set max) is missing."""
    if value is None or vmax is None:
        return None
    if vmax <= 0:
        return 0.0
    return math.log10(1.0 + value) / math.log10(1.0 + vmax)


def _parse_date(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _days_since(value, now: datetime) -> float | None:
    parsed = _parse_date(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds() / 86400.0)


def _fresh_norm(days: float | None) -> float | None:
    return None if days is None else 1.0 / (1.0 + days / 180.0)


def _issues_norm(open_issues: float | None) -> float | None:
    return None if open_issues is None else 1.0 / (1.0 + open_issues / 100.0)


def _dep_norm(dep_count: float | None) -> float | None:
    return None if dep_count is None else 1.0 / (1.0 + dep_count / 20.0)


def _docs_norm(flags) -> float | None:
    if not isinstance(flags, dict):
        return None
    return sum(1 for flag in DOC_FLAGS if flags.get(flag) is True) / len(DOC_FLAGS)


def _awesome_norm(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("count")
    count = _num(value)
    if count is None:
        return None
    return min(count / 3.0, 1.0)


def _cve_penalty(vulns) -> float:
    """2.0 per HIGH/CRITICAL, 0.5 per MEDIUM, capped at 4.0, never a veto."""
    if not isinstance(vulns, list):
        return 0.0
    total = 0.0
    for vuln in vulns:
        severity = (vuln.get("severity") if isinstance(vuln, dict) else None) or ""
        severity = str(severity).upper()
        if severity in ("HIGH", "CRITICAL"):
            total += CVE_HIGH_CRIT
        elif severity == "MEDIUM":
            total += CVE_MEDIUM
    return min(total, CVE_CAP)


def _mean(values: list[float | None]) -> tuple[float, int]:
    present = [v for v in values if v is not None]
    if not present:
        return 0.0, 0
    return sum(present) / len(present), len(present)


def _cand_name(candidate: dict, index: int) -> str:
    for key in ("candidate", "name", "pypi_name"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"candidate-{index}"


def rank_candidates(
    candidates: list[dict],
    incumbent: dict | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    """Rank candidates by the 02 L172-188 rule.

    Returns ``{"ranking": [...], "verdict": {...}}``. Each ranking entry
    carries ``score`` plus the full breakdown (``p0/p1/p2/penalty/norms/
    confidence/license_warning``) for the report to render. ``verdict`` is
    ``recommend`` (winner = rank #1) unless an ``incumbent`` evidence dict
    scores at/above the best challenger, in which case it is ``keep`` with
    ``winner`` None (keep-yours decline). Ties break by name ascending.
    """
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    raws: list[dict] = []
    for index, candidate in enumerate(candidates or []):
        cells = candidate.get("cells", {}) if isinstance(candidate, dict) else {}
        vulns = _raw(cells, "vulns")
        awesome_raw = _raw(cells, "awesome_hits")
        raws.append(
            {
                "name": _cand_name(candidate, index),
                "stars": _num(_raw(cells, "stars")),
                "forks": _num(_raw(cells, "forks")),
                "downloads": _num(_raw(cells, "downloads_last_month")),
                "push_days": _days_since(_raw(cells, "last_commit_date"), moment),
                "release_days": _days_since(_raw(cells, "release_date"), moment),
                "open_issues": _num(_raw(cells, "open_issues")),
                "dep_count": _num(_raw(cells, "dep_count")),
                "so_count": _num(_raw(cells, "so_count")),
                "hn_count": _num(_raw(cells, "hn_count")),
                "heuristics": _raw(cells, "heuristics"),
                "dependents": _num(_raw(cells, "dependents_count")),
                "awesome": awesome_raw,
                "vulns": vulns,
                "license_warning": candidate.get("license_warning"),
            }
        )

    maxima = {}
    for key in ("stars", "forks", "downloads", "so_count", "hn_count", "dependents"):
        present = [row[key] for row in raws if row[key] is not None]
        maxima[key] = max(present) if present else None

    entries: list[dict] = []
    for row in raws:
        norms = {
            "stars_n": _log_norm(row["stars"], maxima["stars"]),
            "forks_n": _log_norm(row["forks"], maxima["forks"]),
            "dl": _log_norm(row["downloads"], maxima["downloads"]),
            "fresh_n": _fresh_norm(row["push_days"]),
            "release_n": _fresh_norm(row["release_days"]),
            "issues_n": _issues_norm(row["open_issues"]),
            "dep_n": _dep_norm(row["dep_count"]),
            "so_n": _log_norm(row["so_count"], maxima["so_count"]),
            "hn_n": _log_norm(row["hn_count"], maxima["hn_count"]),
            "docs_n": _docs_norm(row["heuristics"]),
            "dependents_n": _log_norm(row["dependents"], maxima["dependents"]),
            "awesome_n": _awesome_norm(row["awesome"]),
        }
        p0, n0 = _mean(
            [
                norms["stars_n"],
                norms["dl"],
                norms["fresh_n"],
                norms["release_n"],
                norms["issues_n"],
            ]
        )
        p1, n1 = _mean([norms["dep_n"], norms["so_n"], norms["hn_n"], norms["docs_n"]])
        p2, n2 = _mean([norms["dependents_n"], norms["awesome_n"]])
        penalty = _cve_penalty(row["vulns"])
        score = W_P0 * p0 + W_P1 * p1 + W_P2 * p2 - penalty
        entries.append(
            {
                "name": row["name"],
                "score": round(score, 4),
                "p0": round(p0, 4),
                "p1": round(p1, 4),
                "p2": round(p2, 4),
                "penalty": round(penalty, 4),
                "confidence": round((n0 + n1 + n2) / TOTAL_SCORED, 4),
                "norms": {
                    key: (None if value is None else round(value, 4))
                    for key, value in norms.items()
                },
                "license_warning": row["license_warning"],
            }
        )
    entries.sort(key=lambda entry: (-entry["score"], entry["name"]))

    verdict: dict
    if not entries:
        verdict = {
            "decision": "keep",
            "winner": None,
            "margin": 0.0,
            "dissent": None,
            "reason": "no candidates to rank",
        }
        return {"ranking": [], "verdict": verdict}

    incumbent_score: float | None = None
    if incumbent is not None:
        pooled = list(candidates) + [incumbent]
        pooled_result = rank_candidates(pooled, now=moment)
        for entry in pooled_result["ranking"]:
            if entry["name"] == _cand_name(incumbent, len(candidates)):
                incumbent_score = entry["score"]
                break

    best = entries[0]["score"]
    runner_up = entries[1]["score"] if len(entries) > 1 else None
    margin = round(best - (runner_up if runner_up is not None else best), 4)
    dissent = None
    if runner_up is not None and margin < DISSENT_MARGIN:
        dissent = (
            f"Close call: {entries[0]['name']} leads {entries[1]['name']} "
            f"by {margin:.4f}; runner-up argued as acceptable alternate."
        )
    if incumbent_score is not None and incumbent_score >= best:
        verdict = {
            "decision": "keep",
            "winner": None,
            "margin": round(best - incumbent_score, 4),
            "dissent": None,
            "reason": "incumbent scores at/above the best challenger; decline",
        }
    else:
        verdict = {
            "decision": "recommend",
            "winner": entries[0]["name"],
            "margin": margin,
            "dissent": dissent,
            "reason": "top score wins per 02 L172-188 rule",
        }
    return {"ranking": entries, "verdict": verdict}


def rank(problem: str) -> list[dict]:
    """Compat shim: pipeline placeholder until find/evidence feed real cells.

    ``analyze`` calls this with a bare problem string (no evidence cells, so
    no real ranking is possible yet); the real ranker is :func:`rank_candidates`.
    """
    return [
        {
            "name": f"(stub option for {problem})",
            "why": "Placeholder — find/rank stages not built yet.",
            "source": "https://example.com",
            "source_tag": "unknown",
            "evidence": {},
        }
    ]
