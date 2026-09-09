"""Ticket 07: understand-stage tests. Local fixtures only, no network.

Covers decompose() for idea-text (05 D7 shape, doubt->addition) and repo
dirs (pattern extraction via decompose_repo_dir), the exact failure
records on failure paths, and the analyze --dry-run / understand CLI
wiring (clone tests stub the git call; no real clone runs here).
"""

import json
from pathlib import Path

import pytest

from attw import cli, understand
from attw.understand import UnderstandError


def _write_repo(root: Path, *, with_tests: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "fetcher.py").write_text(
        "import urllib.request\n"
        "def get(url):\n"
        "    req = urllib.request.Request(url)\n"
        "    return urllib.request.urlopen(req).read()\n",
        encoding="utf-8",
    )
    (root / "cli_main.py").write_text(
        "import argparse\n"
        "def main():\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('--out')\n"
        "    return p.parse_args()\n",
        encoding="utf-8",
    )
    (root / "parse_util.py").write_text(
        "def row(line):\n"
        "    return line.split(',')\n",
        encoding="utf-8",
    )
    if with_tests:
        (root / "test_fetcher.py").write_text(
            "def test_get():\n    assert True\n", encoding="utf-8"
        )
    return root


def test_idea_single_phrase_is_addition():
    (components,) = understand.decompose("an app that parses CSV uploads")
    assert components["kind"] == "addition"  # doubt -> addition (05 D7)
    assert components["call_sites"] == []
    assert set(components) == {
        "name", "description", "kind", "call_sites", "confidence",
    }
    assert 0.0 <= components["confidence"] <= 1.0


def test_idea_multi_phrase_splits_into_additions():
    components = understand.decompose("fetch pages with retries and render markdown")
    assert len(components) >= 2
    assert {c["kind"] for c in components} == {"addition"}


def test_idea_blank_raises_exact_failure():
    with pytest.raises(UnderstandError) as exc:
        understand.decompose("   ")
    assert exc.value.failure["stage"] == "understand"
    assert exc.value.failure["code"] == "not_applicable"


def test_repo_dir_patterns_become_substitutions(tmp_path):
    components = understand.decompose_repo_dir(_write_repo(tmp_path / "repo"))
    by_name = {c["name"]: c for c in components}
    assert by_name["HTTP fetching with hand-rolled urllib helpers"]["kind"] == (
        "substitution"
    )
    assert by_name["CLI parsing with hand-built argv/argparse code"]["kind"] == (
        "substitution"
    )
    assert by_name["Hand-rolled delimited-text parsing"]["kind"] == "substitution"
    http = by_name["HTTP fetching with hand-rolled urllib helpers"]
    assert http["call_sites"] and all(
        s.startswith("fetcher.py:") for s in http["call_sites"]
    )
    # Fixture ships a test file, so no missing-suite addition appears.
    assert "No automated test suite" not in by_name


def test_repo_dir_without_tests_gains_addition(tmp_path):
    components = understand.decompose_repo_dir(
        _write_repo(tmp_path / "repo", with_tests=False)
    )
    by_name = {c["name"]: c for c in components}
    assert by_name["No automated test suite"]["kind"] == "addition"


def test_repo_dir_without_patterns_falls_back_to_addition(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "mod.py").write_text("X = 1\n", encoding="utf-8")
    (root / "test_mod.py").write_text("def test_x():\n    assert True\n",
                                      encoding="utf-8")
    (components,) = understand.decompose_repo_dir(root)
    assert components["kind"] == "addition"  # doubt -> addition, never substitution
    assert components["confidence"] < 0.5


def test_repo_dir_without_python_fails_exact(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(UnderstandError) as exc:
        understand.decompose_repo_dir(root)
    assert exc.value.failure["stage"] == "understand"
    assert exc.value.failure["code"] == "not_applicable"


def test_repo_clone_failure_is_source_down(monkeypatch):
    import subprocess

    def _boom(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "fatal: not found")

    monkeypatch.setattr(understand.subprocess, "run", _boom)
    with pytest.raises(UnderstandError) as exc:
        understand.decompose("https://example.com/nope.git")
    assert exc.value.failure["stage"] == "understand"
    assert exc.value.failure["code"] == "source_down"
    assert "fatal: not found" in exc.value.failure["detail"]


def test_repo_clone_uses_depth_one_to_temp(monkeypatch, tmp_path):
    import subprocess

    seen = {}

    def _fake_run(argv, **kwargs):
        seen["argv"] = argv
        dest = Path(argv[-1])
        dest.mkdir(parents=True)
        (dest / "a.py").write_text("X = 1\n", encoding="utf-8")
        (dest / "test_a.py").write_text("def test_a():\n    assert True\n",
                                        encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(understand.subprocess, "run", _fake_run)
    monkeypatch.chdir(tmp_path)
    components = understand.decompose("https://example.com/fake.git")
    assert "--depth" in seen["argv"] and "1" in seen["argv"]
    assert "attw-understand-" in seen["argv"][-1]  # temp dir, never the repo dir
    assert list(tmp_path.iterdir()) == []  # caller dir untouched
    assert isinstance(components, list) and components


def test_profile_shim_returns_descriptions():
    assert understand.profile("fetch pages with retries") == [
        c["description"]
        for c in understand.decompose("fetch pages with retries")
    ]


def test_understand_subcommand_prints_components(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["understand", "fetch pages with retries"]) == 0
    out = capsys.readouterr().out
    assert "addition" in out


def test_understand_subcommand_failure_exits_one(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["understand", "   "]) == 1
    assert "understand/not_applicable" in capsys.readouterr().out


def test_analyze_dry_run_records_components(tmp_path, monkeypatch, capsys):
    # Ticket 13 chain calls find/evidence live; mock them so this stays a
    # hermetic decompose-shape test (no network).
    from attw import evidence, find

    monkeypatch.setattr(find, "find_for_component", lambda component, limit=10: [])
    monkeypatch.setattr(
        evidence, "collect_evidence",
        lambda candidate: {"candidate": "x", "cells": {}, "failures": [],
                           "license_warning": None},
    )
    monkeypatch.chdir(tmp_path)
    assert cli.main(["analyze", "--dry-run", "fetch pages with retries"]) == 0
    assert "# AI_TAKE_THE_WHEEL report" in capsys.readouterr().out
    saved = list((tmp_path / "database").glob("*.json"))
    assert len(saved) == 1
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["components"] and all(
        c["kind"] == "addition" for c in record["components"]
    )
    assert record["profile"] == [c["description"] for c in record["components"]]
    assert record["failures"] == [] and record["dry_run"] is True


def test_analyze_records_understand_failure_downstream_only(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["analyze", "--dry-run", "   "]) == 0
    saved = list((tmp_path / "database").glob("*.json"))
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert [f["stage"] for f in record["failures"]] == ["understand"]
    assert record["components"] == [] and record["problems"] == []
    assert "understand" in capsys.readouterr().out.lower()


DEMO_IDEA = "an app that rewrites AI-generated text to sound human"


def test_demo_idea_yields_multiple_components():
    # Ticket 17: the demo lesson-2 blob must split on capability bounds.
    components = understand.decompose(DEMO_IDEA)
    assert len(components) >= 2
    assert {c["kind"] for c in components} == {"addition"}
    assert len({c["name"] for c in components}) == len(components)
    assert all(0.0 <= c["confidence"] <= 1.0 for c in components)


def test_single_capability_stays_single():
    components = understand.decompose("an app that summarizes PDFs")
    assert len(components) == 1
    assert components[0]["kind"] == "addition"


def test_multi_capability_no_delimiter_splits():
    components = understand.decompose(
        "rewrites AI-generated text to sound human, scores readability"
    )
    assert len(components) >= 2
    assert {c["kind"] for c in components} == {"addition"}


def test_vague_blob_gets_low_confidence():
    (components,) = understand.decompose("an app that does stuff")
    assert components["kind"] == "addition"
    assert components["confidence"] < 0.5
