"""Tests for webfetch. Network tests skip gracefully when offline."""

import urllib.error

import pytest

from attw.webfetch import classify_source, fetch_readable

NETWORK_ERRORS = (
    urllib.error.URLError,
    urllib.error.HTTPError,
    TimeoutError,
    ValueError,
)


def test_fetch_readable_example():
    try:
        got = fetch_readable("https://example.com")
    except NETWORK_ERRORS as exc:
        pytest.skip(f"offline: {exc}")
    assert got["url"] == "https://example.com"
    assert got["title"] == "Example Domain"
    assert "Example Domain" in got["text"]
    assert got["fetched_on"]


def test_classify_source_first_hand():
    assert classify_source("https://github.com/psf/requests") == "first_hand"
    so_url = "https://stackoverflow.com/questions/590747/x"
    assert classify_source(so_url) == "first_hand"
    assert classify_source("https://news.ycombinator.com/item?id=1") == "first_hand"


def test_classify_source_secondary():
    assert classify_source("https://medium.com/some/post") == "secondary"
    assert classify_source("https://dev.to/some/post") == "secondary"


def test_classify_source_unknown():
    assert classify_source("https://example.com/page") == "unknown"
    assert classify_source("https://some-random-blog.example.net/x") == "unknown"
