"""Tests for the report renderer (pure formatting, fixture-driven)."""

import json
from pathlib import Path

from attw.report import render_markdown

FIXTURE = Path(__file__).resolve().parent.parent / "testdata" / "example_results.json"


def test_render_fixture():
    results = json.loads(FIXTURE.read_text(encoding="utf-8"))
    report = render_markdown(results)
    assert "# AI_TAKE_THE_WHEEL report" in report
    assert "Hand-rolled CSV parsing in Python" in report
    assert "python csv parsing library" in report
    assert "tenacity" in report
    assert "first_hand" in report
    assert "| Rank | Option | Why | Evidence | Source |" in report
