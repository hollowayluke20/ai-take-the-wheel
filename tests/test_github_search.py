"""Tests for github_search. Skips gracefully when offline or rate-limited."""

import urllib.error

import pytest

from attw.github_search import search_repos

NETWORK_ERRORS = (urllib.error.URLError, urllib.error.HTTPError, TimeoutError)


def test_search_repos_retry_backoff():
    try:
        got = search_repos("retry backoff python", limit=3)
    except NETWORK_ERRORS as exc:
        pytest.skip(f"offline or rate-limited: {exc}")
    assert len(got) >= 1
    first = got[0]
    assert first["full_name"] and "/" in first["full_name"]
    assert first["url"].startswith("https://github.com/")
    assert first["stars"] is not None
