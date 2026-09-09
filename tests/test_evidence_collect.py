"""Ticket 09: collect_evidence over MOCKED HTTP only (no live network).

Covers: happy path (all P0/P1/P2), quota-hit with PAT, unauth-capped
without PAT, source-down, backoff-once-then-success, cache hit / miss
(fetch-once-then-store) / stale / missing+refresh-fails, license
prose warning, repo-URL discovery, and the per-candidate search-API ban.
"""

import json
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

from attw import evidence
from attw.failures import CODES

REPOS = {
    "stargazers_count": 51000,
    "forks_count": 9000,
    "pushed_at": "2026-08-01T12:00:00Z",
    "open_issues_count": 42,
    "license": {"spdx_id": "MIT", "name": "MIT License"},
    "language": "Python",
    "default_branch": "main",
}

PYPI = {
    "info": {
        "version": "9.0.2",
        "requires_python": ">=3.9",
        "home_page": "https://github.com/jd/tenacity",
        "project_urls": {"Homepage": "https://github.com/jd/tenacity"},
        "classifiers": ["License :: OSI Approved :: MIT License"],
    },
    "releases": {"9.0.2": [{"upload_time_iso_8601": "2025-06-01T00:00:00"}]},
}

STATS = {"data": {"last_day": 111, "last_week": 500000, "last_month": 3000000}}

DEPS_VERSION = {
    "licenses": ["MIT"],
    "advisories": [{"advisoryKey": {"id": "GHSA-xxxx"}, "severity": "HIGH"}],
}

DEPS_DEPS = {"nodes": [{}, {}, {}]}
DEPENDENTS = {"nodes": [{}, {}]}

TREE = {
    "truncated": False,
    "tree": [
        {"path": "README.md"},
        {"path": "docs/index.rst"},
        {"path": "tests/test_tenacity.py"},
        {"path": "src/tenacity/py.typed"},
        {"path": "CHANGELOG.md"},
    ],
}

SO = {
    "items": [
        {"question_id": 11, "score": 99, "title": "How to retry with tenacity?"},
        {"question_id": 22, "score": 5, "title": "tenacity stop condition"},
    ]
}

HN = {
    "nbHits": 12,
    "hits": [{"objectID": "4242", "points": 50, "title": "Tenacity HN thread"}],
}

AWESOME_TEXT = (
    "# awesome python\n"
    "* [tenacity](https://github.com/jd/tenacity) - retry lib\n"
    "something else entirely\n"
)

SEED_ENTRY = {
    "so_count": 7,
    "so_top_score": 90,
    "so_top_qids": [1],
    "hn_count": 5,
    "hn_top_points": 40,
    "hn_top_ids": ["1"],
    "sentiment_snippet": "seed snippet",
    "awesome_hits": {"count": 1, "lists": ["awesome-python"]},
    "dependents_count": 1234,
}


def _http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, f"HTTP {code}", {}, None)


class FakeHTTP:
    """Substring-dispatched fake for evidence._get_json / _get_text."""

    def __init__(self):
        self.urls: list[str] = []
        self.routes: dict[str, object] = {}
        self.text: dict[str, object] = {}

    def get_json(self, url, headers=None):
        self.urls.append(url)
        for sub, resp in self.routes.items():
            if sub in url:
                item = resp.pop(0) if isinstance(resp, list) else resp
                if isinstance(item, Exception):
                    raise item
                return item
        raise AssertionError(f"unexpected URL in test: {url}")

    def get_text(self, url, headers=None):
        self.urls.append(url)
        for sub, resp in self.text.items():
            if sub in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected text URL in test: {url}")


@pytest.fixture
def fake(monkeypatch, tmp_path):
    transport = FakeHTTP()
    monkeypatch.setattr(evidence, "_get_json", transport.get_json)
    monkeypatch.setattr(evidence, "_get_text", transport.get_text)
    monkeypatch.setattr(evidence, "_RETRY_DELAY_S", 0)
    monkeypatch.setenv("GITHUB_TOKEN", "test-pat")
    monkeypatch.setenv("ATTW_CACHE_DIR", str(tmp_path))
    # Keep the real .env PAT out of these tests (loader is reused, not read).
    monkeypatch.setattr(
        "attw.github_search.load_github_token", lambda *a, **k: "test-pat"
    )
    return transport


def seed_cache(tmp_path, entry=None, fresh=True):
    week = evidence._current_week_id()
    now = datetime.now(timezone.utc)
    fetched_at = now if fresh else now - timedelta(days=10)
    stamp = fetched_at.isoformat(timespec="seconds")
    payload = {
        "week_id": week if fresh else "2000-W01",
        "fetched_at": stamp,
        "libs": {"tenacity": dict(entry or SEED_ENTRY)},
    }
    (tmp_path / f"mentions_{payload['week_id']}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    (tmp_path / "mentions_latest.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return payload


def base_routes():
    # Specific substrings FIRST (dict order = match order).
    return {
        "git/trees": TREE,
        "api.github.com/repos/": REPOS,
        "pypi.org/pypi/": PYPI,
        "pypistats.org": STATS,
        ":dependencies": DEPS_DEPS,
        ":dependents": DEPENDENTS,
        "/versions/": DEPS_VERSION,
        "api.stackexchange.com": SO,
        "hn.algolia.com": HN,
    }


def assert_cell_shape(cells):
    for signal, cell in cells.items():
        assert set(cell) == {
            "value",
            "source",
            "as_of",
            "stale",
            "missing",
            "detail",
        }, signal
        assert cell["as_of"], signal
        if cell["missing"] is not None:
            assert cell["value"] is None, signal  # never zero-filled
            assert cell["missing"] in CODES, signal


def test_happy_path_all_signals(fake, tmp_path):
    fake.routes.update(base_routes())
    fake.text["raw.githubusercontent.com"] = AWESOME_TEXT
    seed_cache(tmp_path)
    got = evidence.collect_evidence({"candidate": "tenacity"})

    assert got["candidate"] == "tenacity"
    assert got["repo_url"] == "https://github.com/jd/tenacity"  # discovered
    assert got["failures"] == []
    assert got["license_warning"] is None
    cells = got["cells"]
    assert_cell_shape(cells)

    # P0
    assert cells["stars"]["value"] == 51000
    assert cells["forks"]["value"] == 9000
    assert cells["last_commit_date"]["value"] == "2026-08-01T12:00:00Z"
    assert cells["open_issues"]["value"] == 42
    assert cells["primary_language"]["value"] == "Python"
    assert cells["license_spdx"]["value"] == "MIT"
    assert cells["pypi_version"]["value"] == "9.0.2"
    assert cells["release_date"]["value"] == "2025-06-01T00:00:00"
    assert cells["requires_python"]["value"] == ">=3.9"
    assert cells["downloads_last_month"]["value"] == 3000000
    assert cells["download_trend"]["value"] == 0.1667
    assert cells["vulns"]["value"] == [{"id": "GHSA-xxxx", "severity": "HIGH"}]
    # P1
    assert cells["dep_count"]["value"] == 3
    assert cells["so_count"]["value"] == 7
    assert cells["so_top_score"]["value"] == 90
    assert cells["hn_count"]["value"] == 5
    assert cells["hn_top_points"]["value"] == 40
    assert cells["discussion_proxy"]["value"] == {
        "open_issues": 42,
        "pushed_at": "2026-08-01T12:00:00Z",
    }
    assert cells["heuristics"]["value"] == {
        "readme": True,
        "docs": True,
        "tests": True,
        "py_typed": True,
        "changelog": True,
        "requires_python_bound": True,
    }
    # P2
    assert cells["dependents_count"]["value"] == 1234
    assert cells["awesome_hits"]["value"] == {
        "count": 1,
        "lists": ["awesome-python"],
    }
    # Sources + freshness
    assert "api.github.com/repos/jd/tenacity" in cells["stars"]["source"]
    assert "pypi.org" in cells["pypi_version"]["source"]
    assert "deps.dev" in cells["vulns"]["source"]
    assert cells["so_count"]["stale"] is False
    # Dependents came from the weekly cache: zero live dependents calls.
    assert not any(":dependents" in u for u in fake.urls)
    # Per-candidate search-API calls BANNED (02 L149).
    assert not any("/search/issues" in u for u in fake.urls)
    assert not any("/search/repositories" in u for u in fake.urls)


def test_github_quota_hit_with_pat(fake, tmp_path):
    fake.routes.update(base_routes())
    fake.routes["api.github.com/repos/"] = [
        _http_error("x", 429),
        _http_error("x", 429),
    ]
    seed_cache(tmp_path)
    got = evidence.collect_evidence(
        {"candidate": "tenacity", "repo_url": "https://github.com/jd/tenacity"}
    )
    cells = got["cells"]
    assert_cell_shape(cells)
    for signal in (
        "stars",
        "forks",
        "last_commit_date",
        "open_issues",
        "primary_language",
        "discussion_proxy",
        "heuristics",
    ):
        assert cells[signal]["value"] is None, signal
        assert cells[signal]["missing"] == "quota_hit", signal
    # License degrades gracefully: GitHub primary lost, PyPI 2nd source kept.
    assert cells["license_spdx"]["value"] == "MIT License"
    assert cells["license_spdx"]["missing"] is None
    # PyPI side is unaffected.
    assert cells["pypi_version"]["value"] == "9.0.2"
    assert any(f["code"] == "quota_hit" for f in got["failures"])


def test_github_unauth_capped_without_pat(fake, tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN")
    monkeypatch.setattr(
        "attw.github_search.load_github_token", lambda *a, **k: None
    )
    fake.routes.update(base_routes())
    fake.routes["api.github.com/repos/"] = _http_error("x", 403)
    seed_cache(tmp_path)
    got = evidence.collect_evidence(
        {"candidate": "tenacity", "repo_url": "https://github.com/jd/tenacity"}
    )
    assert got["cells"]["stars"]["missing"] == "no_pat_unauth_capped"
    assert got["cells"]["pypi_version"]["value"] == "9.0.2"


def test_pypi_source_down_cascades_to_version_gated(fake, tmp_path):
    fake.routes.update(base_routes())
    fake.routes["pypi.org/pypi/"] = [
        _http_error("x", 500),
        _http_error("x", 500),
    ]
    seed_cache(tmp_path)
    got = evidence.collect_evidence(
        {"candidate": "tenacity", "repo_url": "https://github.com/jd/tenacity"}
    )
    cells = got["cells"]
    assert cells["pypi_version"]["missing"] == "source_down"
    assert cells["vulns"]["missing"] == "not_applicable"
    assert cells["dep_count"]["missing"] == "not_applicable"
    assert cells["stars"]["value"] == 51000  # GitHub side still fine


def test_backoff_once_then_success(fake, tmp_path):
    fake.routes.update(base_routes())
    fake.routes["pypistats.org"] = [_http_error("x", 429), STATS]
    seed_cache(tmp_path)
    got = evidence.collect_evidence({"candidate": "tenacity"})
    assert got["cells"]["downloads_last_month"]["value"] == 3000000
    assert got["cells"]["download_trend"]["value"] == 0.1667


def test_cache_miss_fetch_once_then_store(fake, tmp_path):
    fake.routes.update(base_routes())
    fake.text["raw.githubusercontent.com"] = AWESOME_TEXT
    got = evidence.collect_evidence({"candidate": "tenacity"})
    week_file = tmp_path / f"mentions_{evidence._current_week_id()}.json"
    assert week_file.exists()  # stored, not just read
    assert (tmp_path / "mentions_latest.json").exists()
    cells = got["cells"]
    assert cells["so_count"]["value"] == 2  # len(SO items), live-refreshed
    assert cells["hn_count"]["value"] == 12  # nbHits, live-refreshed
    assert cells["dependents_count"]["value"] == 2
    assert cells["awesome_hits"]["value"]["count"] == 1
    assert cells["so_count"]["stale"] is False
    # Whole run stays in budget: 6 candidate calls + 5 refresh calls
    # (SO, HN, awesome, PyPI version lookup, version-level dependents).
    assert len(fake.urls) == 11


def test_cache_missing_and_refresh_fails_marks_stale(fake, tmp_path, monkeypatch):
    fake.routes.update(base_routes())
    monkeypatch.setattr(
        evidence, "_refresh_lib", lambda package: (_ for _ in ()).throw(
            RuntimeError("SO quota exhausted")
        ),
    )
    got = evidence.collect_evidence({"candidate": "tenacity"})
    cells = got["cells"]
    for signal in ("so_count", "hn_count", "awesome_hits", "dependents_count"):
        assert cells[signal]["value"] is None, signal
        assert cells[signal]["missing"] == "stale_cache", signal
        assert cells[signal]["stale"] is True, signal
    assert any(f["code"] == "stale_cache" for f in got["failures"])


def test_stale_cache_serves_values_marked_stale(fake, tmp_path, monkeypatch):
    fake.routes.update(base_routes())
    seed_cache(tmp_path, fresh=False)
    monkeypatch.setattr(
        evidence, "_refresh_lib", lambda package: (_ for _ in ()).throw(
            RuntimeError("offline")
        ),
    )
    got = evidence.collect_evidence({"candidate": "tenacity"})
    cells = got["cells"]
    assert cells["so_count"]["value"] == 7  # old values kept, never zeroed
    assert cells["so_count"]["stale"] is True
    assert cells["so_count"]["missing"] is None


def test_license_mismatch_is_prose_only(fake, tmp_path):
    routes = base_routes()
    apache_pypi = json.loads(json.dumps(PYPI))
    apache_pypi["info"]["classifiers"] = [
        "License :: OSI Approved :: Apache Software License"
    ]
    routes["pypi.org/pypi/"] = apache_pypi
    fake.routes.update(routes)
    seed_cache(tmp_path)
    got = evidence.collect_evidence({"candidate": "tenacity"})
    assert got["cells"]["license_spdx"]["value"] == "MIT"  # GitHub primary
    assert got["license_warning"] is not None
    assert "prose flag only" in got["license_warning"]


def test_license_alias_apache_agrees(fake, tmp_path):
    routes = base_routes()
    repos_apache = json.loads(json.dumps(REPOS))
    repos_apache["license"] = {"spdx_id": "Apache-2.0", "name": "Apache License 2.0"}
    routes["api.github.com/repos/"] = repos_apache
    apache_pypi = json.loads(json.dumps(PYPI))
    apache_pypi["info"]["classifiers"] = [
        "License :: OSI Approved :: Apache Software License"
    ]
    routes["pypi.org/pypi/"] = apache_pypi
    deps_apache = json.loads(json.dumps(DEPS_VERSION))
    deps_apache["licenses"] = ["Apache-2.0"]
    routes["/versions/"] = deps_apache
    fake.routes.update(routes)
    seed_cache(tmp_path)
    got = evidence.collect_evidence({"candidate": "tenacity"})
    assert got["cells"]["license_spdx"]["value"] == "Apache-2.0"
    assert got["license_warning"] is None


def test_pypi_404_is_not_applicable(fake, tmp_path):
    fake.routes.update(base_routes())
    fake.routes["pypi.org/pypi/"] = _http_error("x", 404)
    seed_cache(tmp_path)
    got = evidence.collect_evidence({"candidate": "nosuchpkg12345"})
    assert got["cells"]["pypi_version"]["missing"] == "not_applicable"


def test_no_repo_url_is_not_applicable_not_zero(fake, tmp_path):
    routes = base_routes()
    no_home = json.loads(json.dumps(PYPI))
    no_home["info"]["home_page"] = "https://example.com/x"
    no_home["info"]["project_urls"] = {}
    routes["pypi.org/pypi/"] = no_home
    fake.routes.update(routes)
    seed_cache(tmp_path)
    got = evidence.collect_evidence({"candidate": "tenacity"})
    assert got["repo_url"] is None
    assert got["cells"]["stars"]["missing"] == "not_applicable"
    assert got["cells"]["stars"]["value"] is None


def test_refresh_weekly_cache_writes_and_reuses(fake, tmp_path):
    fake.routes.update(base_routes())
    fake.text["raw.githubusercontent.com"] = AWESOME_TEXT
    first = evidence.refresh_weekly_cache(packages=["tenacity"])
    assert first.endswith(f"mentions_{evidence._current_week_id()}.json")
    payload = json.loads((tmp_path / "mentions_latest.json").read_text())
    assert payload["libs"]["tenacity"]["so_count"] == 2
    calls = len(fake.urls)
    second = evidence.refresh_weekly_cache()  # same week: no refetch
    assert second == first
    assert len(fake.urls) == calls


def test_invalid_candidate_raises(fake):
    with pytest.raises(ValueError):
        evidence.collect_evidence({})
