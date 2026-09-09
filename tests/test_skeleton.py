"""Skeleton tests for ticket 05: imports, CLI shape, pure helpers.

No live network, no sandbox mutation. Stage bodies beyond pure helpers
raise NotImplementedError carrying the ticket reference.
"""

import inspect
import json
from pathlib import Path

import pytest

from attw import cli, evidence, failures, implement, understand, verify


def test_modules_import():
    for module in (cli, evidence, failures, implement, understand, verify):
        assert module.__name__.startswith("attw.")


def test_cli_help_lists_all_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in (
        "analyze",
        "understand",
        "find",
        "evidence",
        "rank",
        "report",
        "implement",
        "verify",
        "refresh-cache",
    ):
        assert command in out


def test_working_stage_commands_exit_zero(capsys):
    assert cli.main(["understand", "an app idea"]) == 0
    assert "addition" in capsys.readouterr().out
    assert cli.main(["find", "CSV parsing"]) == 0
    assert cli.main(["rank", "CSV parsing"]) == 0


def test_implement_wires_and_verify_skeleton(tmp_path, capsys):
    # Ticket 12 built implement.plan/apply: missing sandbox -> receipt
    # failure (exit 1, exact failure string), not a skeleton stub.
    args = ["implement", "--component", "c", "--wheel", "w",
            "--sandbox-dir", str(tmp_path / "missing")]
    assert cli.main(args) == 1
    assert "implement: failed-install" in capsys.readouterr().out
    # Verify harness body landed with ticket 13: missing file -> gate
    # failure message + exit 1 (no "05 skeleton" stub any more).
    assert cli.main(["verify", "verify.json", "--check"]) == 1
    assert "verify failed" in capsys.readouterr().out


def test_built_evidence_commands_exit_zero(monkeypatch, capsys, tmp_path):
    # Ticket 09 built evidence.collect_evidence + refresh_weekly_cache;
    # wire-through only (no network — bodies mocked).
    monkeypatch.setattr(
        evidence, "collect_evidence", lambda candidate: {"candidate": "tenacity"}
    )
    monkeypatch.setattr(
        evidence, "refresh_weekly_cache", lambda *a, **k: str(tmp_path / "m.json")
    )
    assert cli.main(["evidence", "tenacity"]) == 0
    assert "tenacity" in capsys.readouterr().out
    assert cli.main(["refresh-cache"]) == 0
    assert "m.json" in capsys.readouterr().out


def test_stage_signatures():
    assert "candidate" in inspect.signature(evidence.collect_evidence).parameters
    assert "component" in inspect.signature(implement.plan).parameters
    assert "sandbox_dir" in inspect.signature(implement.apply).parameters
    assert "sandbox_dir" in inspect.signature(verify.run_suite).parameters
    # Ticket 07 built understand.decompose: idea-text yields additions.
    components = understand.decompose("an idea")
    assert components and {c["kind"] for c in components} == {"addition"}


def test_classify_input():
    assert understand.classify_input("https://github.com/x/y") == "repo_url"
    assert understand.classify_input("an app that parses CSV") == "idea_text"


def test_failure_record_round_trip():
    record = failures.make_failure("implement", "failed-install", "pip blew up")
    assert failures.FailureRecord.from_dict(record).to_dict() == record
    assert "[implement/failed-install]" in failures.format_one(record)
    with pytest.raises(ValueError, match="Unknown stage"):
        failures.make_failure("nope", "x", "y")


def test_diff_results_buckets():
    baseline = {"a": "passed", "b": "failed", "c": "passed", "d": "passed"}
    after = {"a": "failed", "b": "passed", "c": "skipped", "e": "passed"}
    diff = verify.diff_results(baseline, after, {"d": "deleted-by-wheel"})
    assert diff["fixed"] == ["b"]
    assert sorted(diff["regressed"]) == ["a", "c"]  # pass->skip is regressed
    assert diff["new"] == ["e"]
    assert diff["removed"] == [{"nodeid": "d", "reason": "deleted-by-wheel"}]


def test_decide_verdict_gate():
    assert verify.decide_verdict({"regressed": ["a"], "fixed": [], "new": [],
                                  "removed": []}, {}) == "fail"
    assert verify.decide_verdict({"regressed": [], "fixed": ["b"], "new": [],
                                  "removed": []}, {}) == "better"
    assert verify.decide_verdict({"regressed": [], "fixed": [], "new": ["e"],
                                  "removed": []}, {"e": "passed"}) == "better"
    assert verify.decide_verdict({"regressed": [], "fixed": [], "new": [],
                                  "removed": []}, {}) == "keep-yours"
    unexplained = [{"nodeid": "d", "reason": ""}]
    assert verify.decide_verdict({"regressed": [], "fixed": [], "new": [],
                                  "removed": unexplained}, {}) == "fail"


def test_load_answer_key_valid_and_invalid(tmp_path):
    key = tmp_path / "run.json"
    key.write_text(json.dumps({
        "problem": "P", "accepted_answers": [{"name": "w", "why": "y"}],
        "sources": ["https://example.com/a", "https://example.com/b"],
        "researched_on": "2026-09-09", "notes": "",
        "input": {"kind": "idea_text", "value": "idea"},
        "expected_wheels": ["w"], "run_type": "win",
        "better_spec": {"mode": "red_to_green", "tests": ["t::t"],
                        "benchmark": None},
        "verify": {"test_command": "pytest -q",
                   "baseline": {"captured": True, "tool": "pytest-json-report"},
                   "authored_tests": [], "zero_regressions": True},
    }), encoding="utf-8")
    assert verify.load_answer_key(key)["run_type"] == "win"
    bad = json.loads(key.read_text(encoding="utf-8"))
    bad["run_type"] = "maybe"
    key.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="run_type"):
        verify.load_answer_key(key)


def test_load_answer_key_real_suite_file():
    real = (
        Path(__file__).resolve().parent.parent
        / "testdata" / "known_answers" / "26-tldr-http-client.json"
    )
    assert verify.load_answer_key(real)["expected_wheels"][0] == "requests"


def test_choose_manifest_and_adapter_path():
    assert implement.choose_manifest(["setup.py", "pyproject.toml"]) == "pyproject.toml"
    assert implement.choose_manifest(["requirements-dev.txt"]) == "requirements-dev.txt"
    assert implement.choose_manifest(["README.md"]) is None
    assert implement.adapter_path("flat", "tenacity") == "_attw_tenacity_adapter.py"
    assert implement.adapter_path("src", "tenacity", "pkg") == (
        "src/pkg/_attw_tenacity_adapter.py"
    )
    with pytest.raises(ValueError, match="package"):
        implement.adapter_path("src", "tenacity")
    with pytest.raises(ValueError, match="layout"):
        implement.adapter_path("weird", "tenacity")


def test_analyze_dry_run_record(tmp_path, monkeypatch, capsys):
    from attw import evidence, find

    monkeypatch.setattr(
        find, "find_for_component",
        lambda component, limit=10: [{
            "name": "tenacity", "full_name": "j/tenacity",
            "url": "https://github.com/j/tenacity",
            "description": "retry", "stars": 1, "query": "q",
        }],
    )
    monkeypatch.setattr(
        evidence, "collect_evidence",
        lambda candidate: {"candidate": "tenacity", "repo_url": None,
                           "fetched_at": "t", "cells": {}, "failures": [],
                           "license_warning": None},
    )
    monkeypatch.chdir(tmp_path)
    assert cli.main(["analyze", "--dry-run", "an app that parses CSV"]) == 0
    assert "# AI_TAKE_THE_WHEEL report" in capsys.readouterr().out
    saved = list((tmp_path / "database").glob("*.json"))
    assert len(saved) == 1
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["input"]["kind"] == "idea_text"
    assert record["dry_run"] is True and record["failures"] == []
    assert record["mode"] == "auto" and record["verdict"] is None


def test_analyze_full_records_skeleton_failures(tmp_path, monkeypatch):
    # Ticket 13 wired the real chain: an idea-text full run records the
    # implement skip (no target repo) and skips verify cleanly.
    from attw import evidence, find

    monkeypatch.setattr(
        find, "find_for_component",
        lambda component, limit=10: [{
            "name": "tenacity", "full_name": "j/tenacity",
            "url": "https://github.com/j/tenacity",
            "description": "retry", "stars": 1, "query": "q",
        }],
    )
    monkeypatch.setattr(
        evidence, "collect_evidence",
        lambda candidate: {"candidate": "tenacity", "repo_url": None,
                           "fetched_at": "t", "cells": {}, "failures": [],
                           "license_warning": None},
    )
    monkeypatch.chdir(tmp_path)
    assert cli.main(["analyze", "an app that parses CSV"]) == 0
    saved = list((tmp_path / "database").glob("*.json"))
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    stages = {f["stage"] for f in record["failures"]}
    assert stages == {"implement"}


def test_report_renders_verdict_and_failures():
    from attw.report import render_markdown

    record = {"input": "x", "profile": [], "searches": {}, "problems": [],
              "verdict": "Winner: tenacity [stars=1].",
              "failures": [{"stage": "verify", "code": "stalled", "reason": "quiet"}]}
    out = render_markdown(record)
    assert "## Verdict" in out and "tenacity" in out
    assert "## Failures" in out and "stalled" in out
