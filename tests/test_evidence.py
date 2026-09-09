"""Tests for the free evidence fetchers. Each hits a known real package.

All tests skip gracefully when offline (URLError/HTTPError/TimeoutError).
"""

import urllib.error

import pytest

from attw import evidence

NETWORK_ERRORS = (urllib.error.URLError, urllib.error.HTTPError, TimeoutError)


def test_github_repo_requests():
    try:
        got = evidence.github_repo("https://github.com/psf/requests")
    except NETWORK_ERRORS as exc:
        pytest.skip(f"offline or rate-limited: {exc}")
    assert got["stars"] is not None and got["stars"] > 10_000
    assert got["primary_language"] == "Python"
    assert got["license"] is not None


def test_pypi_package_tenacity():
    try:
        got = evidence.pypi_package("tenacity")
    except NETWORK_ERRORS as exc:
        pytest.skip(f"offline: {exc}")
    assert got["latest_version"]
    assert got["latest_release_date"] is not None


def test_github_repo_no_search_call(monkeypatch):
    """02 L126/L149: no per-candidate search call; closed_issues dropped."""
    calls = []

    def fake_get_json(url, headers=None):
        calls.append(url)
        assert "/search/issues" not in url, "search-API call banned"
        return {
            "stargazers_count": 1,
            "forks_count": 2,
            "pushed_at": "2026-01-01T00:00:00Z",
            "open_issues_count": 3, "license": {"spdx_id": "MIT"}, "language": "Python",
        }

    monkeypatch.setattr(evidence, "_get_json", fake_get_json)
    got = evidence.github_repo("https://github.com/o/r")
    assert "closed_issues" not in got
    assert len(calls) == 1 and calls[0].endswith("/repos/o/r")
    assert got["stars"] == 1 and got["license"] == "MIT"


def test_npm_package_express():
    try:
        got = evidence.npm_package("express")
    except NETWORK_ERRORS as exc:
        pytest.skip(f"offline: {exc}")
    assert got["latest_version"]
    assert got["last_publish_date"] is not None
