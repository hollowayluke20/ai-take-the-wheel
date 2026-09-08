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


def test_npm_package_express():
    try:
        got = evidence.npm_package("express")
    except NETWORK_ERRORS as exc:
        pytest.skip(f"offline: {exc}")
    assert got["latest_version"]
    assert got["last_publish_date"] is not None
