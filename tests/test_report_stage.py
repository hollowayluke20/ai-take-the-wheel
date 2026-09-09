"""Report-stage tests (ticket 11): fixture run-records in, assertions out.

Covers the comparison table, prose verdict (addition vs substitution,
winner, license_warning, gains by node id), cite presence, keep-yours
rendering, failure sections, uncited-claim enforcement, and the
analyze --dry-run / report-subcommand wiring.
"""

import json
from pathlib import Path

import pytest

from attw import cli
from attw.report import ReportError, render_markdown

GH = "https://api.github.com/repos/jd/tenacity"
PYPI = "https://pypi.org/pypi/tenacity/json"
STATS = "https://pypistats.org/packages/tenacity"


def _cell(value, source, missing=None, stale=False):
    return {"value": value, "source": source, "as_of": "2026-09-09T00:00:00",
            "stale": stale, "missing": missing, "detail": ""}


def _cand(name, warning=None, hn_missing=None):
    return {
        "candidate": name,
        "cells": {
            "stars": _cell(5000, GH),
            "downloads_last_month": _cell(900000, STATS),
            "last_commit_date": _cell("2026-09-01T10:00:00Z", GH),
            "release_date": _cell("2026-08-01T00:00:00Z", PYPI),
            "open_issues": _cell(12, GH),
            "dep_count": _cell(0, "https://deps.dev/pypi/tenacity"),
            "so_count": _cell(400, "weekly-cache"),
            "hn_count": _cell(None, "weekly-cache", missing=hn_missing)
            if hn_missing else _cell(25, "weekly-cache"),
            "heuristics": _cell({"readme": True, "docs": True}, GH),
            "dependents_count": _cell(300, "weekly-cache"),
            "awesome_hits": _cell({"count": 2}, "weekly-cache"),
            "vulns": _cell([], "https://deps.dev/pypi/tenacity/9.0.0"),
            "license_spdx": _cell("Apache-2.0", GH),
        },
        "license_warning": warning,
    }


def _entry(name, score, warning=None):
    return {"name": name, "score": score, "p0": 0.9, "p1": 0.8, "p2": 0.7,
            "penalty": 0.0, "confidence": 1.0, "norms": {},
            "license_warning": warning}


def _verdict(winner="tenacity", decision="recommend", dissent=None,
             gains=()):
    return {"decision": decision, "winner": winner, "margin": 0.5,
            "dissent": dissent, "reason": "top score wins per 02 rule",
            "gains": list(gains)}


def _results(**overrides):
    block = {
        "problem": "Retrying flaky calls",
        "kind": "substitution",
        "ranking": [_entry("tenacity", 12.0), _entry("backoff", 11.5)],
        "candidates": [_cand("tenacity"), _cand("backoff")],
        "verdict": _verdict(
            dissent="Close call: tenacity leads backoff by 0.5.",
            gains=["tests/test_retry.py::test_backoff"]),
        "gain_tests": ["tests/test_retry.py::test_backoff"],
    }
    results = {
        "input": {"kind": "idea_text", "value": "retry flaky calls"},
        "components": [{"name": "Retry", "description": "Retrying flaky calls",
                        "kind": "substitution", "call_sites": [],
                        "confidence": 0.6}],
        "profile": ["Retrying flaky calls"],
        "searches": {"Retrying flaky calls": ["retry backoff"]},
        "problems": [block],
        "verdict": None,
        "verify": {"test_command": "pytest -q", "verdict": "better",
                   "diff": {"fixed": ["tests/test_retry.py::test_backoff"],
                            "regressed": [], "new": []}},
        "failures": [],
        "dry_run": True,
        "mode": "auto",
    }
    results.update(overrides)
    return results


def _rows(out):
    return [ln for ln in out.splitlines() if ln.startswith("| tenacity")
            or ln.startswith("| backoff")]


def test_table_contents():
    out = render_markdown(_results())
    assert "| Wheel | Score |" in out and "| Stars |" in out
    rows = _rows(out)
    assert len(rows) == 2
    assert "12.0" in rows[0] and "tenacity" in rows[0]


def test_every_cell_cites_its_source():
    out = render_markdown(_results())
    for row in _rows(out):
        assert "](" in row or "(weekly-cache)" in row
    assert "api.github.com](" in out  # real source link, not bare text
    assert "(weekly-cache)" in out


def test_missing_cell_renders_reason_with_cite():
    results = _results()
    results["problems"][0]["candidates"][1] = _cand("backoff",
                                                    hn_missing="quota_hit")
    out = render_markdown(results)
    assert "n/a (quota_hit)" in out


def test_verdict_states_substitution_winner_and_gains():
    out = render_markdown(_results())
    assert "Substitution" in out
    assert "**tenacity**" in out
    assert "`tests/test_retry.py::test_backoff`" in out
    assert "Close call" in out


def test_addition_verdict_verb():
    results = _results()
    results["problems"][0]["kind"] = "addition"
    out = render_markdown(results)
    assert "Addition: add **tenacity**" in out


def test_license_warning_prose_with_cite():
    results = _results()
    results["problems"][0]["ranking"][0]["license_warning"] = (
        "GPL-3.0 mismatch: prose flag only.")
    out = render_markdown(results)
    assert "License note:" in out and "GPL-3.0" in out
    assert "api.github.com](" in out


def test_keep_yours_rendering():
    results = _results(verify=None)
    block = results["problems"][0]
    block["verdict"] = _verdict(decision="keep", winner=None)
    block.pop("gain_tests", None)
    out = render_markdown(results)
    assert "Keep yours" in out
    assert "adopt **" not in out and "add **" not in out


def test_uncited_winner_fails_the_render():
    results = _results()
    results["problems"][0]["verdict"]["winner"] = "ghost-lib"
    with pytest.raises(ReportError) as exc:
        render_markdown(results)
    assert exc.value.failure["stage"] == "report"
    assert exc.value.failure["code"] == "uncited-claim"
    assert "ghost-lib" in exc.value.failure["reason"]


def test_uncited_gain_fails_the_render():
    results = _results()
    results["problems"][0]["gain_tests"] = ["tests/test_x.py::test_ghost"]
    with pytest.raises(ReportError, match="uncited|backing"):
        render_markdown(results)


def test_gains_without_verify_block_fail():
    results = _results(verify=None)
    with pytest.raises(ReportError):
        render_markdown(results)


def test_unbacked_license_prose_fails():
    results = _results()
    results["problems"][0]["verdict"]["license_warning"] = "GPL scare"
    with pytest.raises(ReportError, match="[Ll]icense"):
        render_markdown(results)


def test_dissent_without_runner_up_fails():
    results = _results()
    results["problems"][0]["ranking"] = [_entry("tenacity", 12.0)]
    with pytest.raises(ReportError, match="[Dd]issent|runner-up"):
        render_markdown(results)


def test_enforce_false_withholds_and_records():
    results = _results()
    results["problems"][0]["verdict"]["winner"] = "ghost-lib"
    out = render_markdown(results, enforce=False)
    assert "Verdict withheld" in out and "ghost-lib" in out
    assert "## Failures" in out and "uncited-claim" in out


def test_failure_sections():
    results = _results()
    results["failures"] = [{"stage": "evidence", "code": "quota_hit",
                            "reason": "search capped", "detail": "",
                            "component": "tenacity"}]
    out = render_markdown(results)
    assert "## Failures" in out
    assert "evidence" in out and "quota_hit" in out


def test_legacy_fixture_still_renders():
    fixture = (Path(__file__).resolve().parent.parent / "testdata"
               / "example_results.json")
    out = render_markdown(json.loads(fixture.read_text(encoding="utf-8")))
    assert "| Rank | Option | Why | Evidence | Source |" in out
    assert "tenacity" in out


def test_dry_run_renders_without_implement_verify(tmp_path, monkeypatch,
                                                  capsys):
    from attw import find

    def _boom(component, limit=10):
        raise find.FindError(find._fail("source_down", "offline").failure)

    monkeypatch.setattr(find, "find_for_component", _boom)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["analyze", "--dry-run", "retry flaky calls"]) == 0
    out = capsys.readouterr().out
    assert "# AI_TAKE_THE_WHEEL report" in out
    saved = list((tmp_path / "database").glob("*.json"))
    sidecars = list((tmp_path / "database").glob("*.report.md"))
    assert len(saved) == 1 and len(sidecars) == 1
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["dry_run"] is True
    assert {f["stage"] for f in record["failures"]} == {"find"}
    assert "find" in sidecars[0].read_text(encoding="utf-8")


def test_report_subcommand_rejects_uncited(tmp_path, capsys):
    results = _results()
    results["problems"][0]["verdict"]["winner"] = "ghost-lib"
    path = tmp_path / "run.json"
    path.write_text(json.dumps(results), encoding="utf-8")
    assert cli.main(["report", str(path)]) == 1
    out = capsys.readouterr().out
    assert "uncited-claim" in out and "Verdict withheld" in out


def test_report_subcommand_accepts_cited(tmp_path, capsys):
    path = tmp_path / "run.json"
    path.write_text(json.dumps(_results()), encoding="utf-8")
    assert cli.main(["report", str(path)]) == 0
    assert "**tenacity**" in capsys.readouterr().out
