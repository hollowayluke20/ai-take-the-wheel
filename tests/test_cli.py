"""CLI chain tests (ticket 13): analyze wires the real stages per component.

Network is mocked (find/evidence); the chain shape is asserted through the
saved run record: find hits -> evidence cells -> rank verdict, dry-run stops
after report, idea-text full runs record an implement skip with no verify
failure.
"""

import json

from attw import evidence, find
from attw.find import FindError

_HITS = [
    {
        "name": "tenacity",
        "full_name": "jazzband/tenacity",
        "url": "https://github.com/jazzband/tenacity",
        "description": "retrying library",
        "stars": 100,
        "query": "retry backoff language:python",
    }
]

_EVIDENCE = {
    "candidate": "tenacity",
    "repo_url": "https://github.com/jazzband/tenacity",
    "fetched_at": "2026-09-09T00:00:00+00:00",
    "cells": {},
    "failures": [],
    "license_warning": None,
}


def _mock_stages(monkeypatch):
    monkeypatch.setattr(
        find, "find_for_component", lambda component, limit=10: list(_HITS)
    )
    monkeypatch.setattr(
        evidence, "collect_evidence", lambda candidate: dict(_EVIDENCE)
    )


def test_analyze_dry_run_stops_after_report(tmp_path, monkeypatch, capsys):
    from attw.cli import main

    _mock_stages(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert main(["analyze", "--dry-run", "an app that parses CSV uploads"]) == 0
    out = capsys.readouterr().out
    assert "# AI_TAKE_THE_WHEEL report" in out
    saved = list((tmp_path / "database").glob("*.json"))
    assert len(saved) == 1
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["dry_run"] is True and record["verdict"] is None
    assert record["failures"] == []
    assert record["problems"][0]["ranking"][0]["name"] == "tenacity"
    assert "implement" not in record["problems"][0]


def test_analyze_idea_text_full_run_skips_verify_cleanly(
    tmp_path, monkeypatch, capsys
):
    from attw.cli import main

    _mock_stages(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert main(["analyze", "an app that parses CSV uploads"]) == 0
    assert "# AI_TAKE_THE_WHEEL report" in capsys.readouterr().out
    saved = list((tmp_path / "database").glob("*.json"))
    assert len(saved) == 1
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    stages = {f["stage"] for f in record["failures"]}
    # ticket 15: empty-cells winner declines-weak; decline skips
    # implement/verify cleanly (no implement failure, no verify failure).
    assert stages == set()
    assert record["failures"] == []
    assert record["problems"][0]["verdict"]["decision"] == "decline-weak"
    assert "implement" not in record["problems"][0]


def test_analyze_find_failure_declines_cleanly(tmp_path, monkeypatch):
    from attw import cli
    from attw.failures import make_failure

    def _boom(component, limit=10):
        raise FindError(
            make_failure(
                "find", "no-candidates", "No candidates found.",
                component=component.get("name", ""),
            )
        )

    monkeypatch.setattr(find, "find_for_component", _boom)
    monkeypatch.chdir(tmp_path)
    cli.analyze("an app that retries flaky calls")
    saved = list((tmp_path / "database").glob("*.json"))
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert {f["stage"] for f in record["failures"]} == {"find"}
    assert record["problems"][0]["verdict"]["decision"] == "keep"
    assert "implement" not in record["problems"][0]


def test_analyze_repo_url_incumbent_tie_declines_before_implement(
    tmp_path, monkeypatch
):
    """Rank keep-path is wired: an incumbent matching the best challenger
    declines (no implement/verify) instead of installing."""
    from attw import cli, understand

    _mock_stages(monkeypatch)
    monkeypatch.setattr(
        understand, "decompose",
        lambda source, timeout_s=120: [{
            "name": "HTTP fetching",
            "description": "Downloading remote resources.",
            "kind": "substitution",
            "call_sites": [],
            "confidence": 0.6,
        }],
    )
    monkeypatch.chdir(tmp_path)
    cli.analyze("https://github.com/example/tiny-client", dry_run=True)
    saved = list((tmp_path / "database").glob("*.json"))
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    verdict = record["problems"][0]["verdict"]
    assert verdict["decision"] == "keep" and verdict["winner"] is None
    assert "implement" not in record["problems"][0]


def test_analyze_idea_text_has_no_incumbent(tmp_path, monkeypatch, capsys):
    """Idea-text runs never build incumbent evidence: empty-cells lone
    candidate declines-weak per ticket 15."""
    from attw.cli import main

    _mock_stages(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert main(["analyze", "--dry-run", "an app that parses CSV uploads"]) == 0
    saved = list((tmp_path / "database").glob("*.json"))
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    verdict = record["problems"][0]["verdict"]
    assert verdict["decision"] == "decline-weak"
    assert verdict["winner"] is None
