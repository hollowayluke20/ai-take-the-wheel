"""Smoke test for the CLI skeleton (stubs end to end, no crash)."""


def test_analyze_runs_and_prints_report(tmp_path, monkeypatch, capsys):
    from attw.cli import main

    monkeypatch.chdir(tmp_path)
    assert main(["analyze", "an app that parses CSV uploads"]) == 0
    out = capsys.readouterr().out
    assert "# AI_TAKE_THE_WHEEL report" in out
    assert "Hand-rolled CSV parsing in Python" in out
    saved = list((tmp_path / "database").glob("*.json"))
    assert len(saved) == 1
