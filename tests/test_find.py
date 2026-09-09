"""Find-stage tests (tickets 08/16). All HTTP is mocked — no live network here.

A session guard fails any test that touches the real urlopen; per-test
monkeypatches replace it with fakes.
"""

import io
import json
import urllib.error
import urllib.request

import pytest

from attw import cli, find, github_search
from attw.find import FindError


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("live network is banned in find-stage tests")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)


def _component(name, description):
    return {"name": name, "description": description, "kind": "substitution",
            "call_sites": [], "confidence": 0.6}


def _item(full_name, stars=1000):
    owner, repo = full_name.split("/")
    return {"full_name": full_name, "html_url": f"https://github.com/{full_name}",
            "description": f"{repo} does things", "stargazers_count": stars,
            "forks_count": 10, "pushed_at": "2026-09-01T00:00:00Z",
            "open_issues_count": 5, "license": {"spdx_id": "MIT"},
            "language": "Python"}


# --- query mapping: deterministic, covers the understand.py patterns ---

def test_component_to_query_rules():
    cases = [
        (_component("HTTP fetching with hand-rolled urllib helpers", "x"),
         "http client language:python"),
        (_component("CLI parsing with hand-built argv/argparse code", "x"),
         "cli framework language:python"),
        (_component("Hand-rolled delimited-text parsing", "csv splits"),  # csv
         "csv parser language:python"),
        (_component("Retrying flaky calls with hand-rolled retry/sleep logic", "x"),
         "retry backoff language:python"),
        (_component("Layered configuration with ad-hoc env/config reads", "x"),
         "configuration management language:python"),
        (_component("Validating nested data with hand-written isinstance checks",
                    "x"), "data validation language:python"),
        (_component("No automated test suite", "no tests"),  # addition
         "testing framework language:python"),
    ]
    for component, expected in cases:
        assert find.component_to_query(component) == expected
        # deterministic: same input twice, same output
        assert find.component_to_query(component) == expected


def test_component_to_query_fallback_is_deterministic():
    component = _component("Blorping zenthic widgets",
                           "Blorping zenthic widgets with quantum sprockets")
    first = find.component_to_query(component)
    assert first == find.component_to_query(component)
    assert first.endswith("language:python")


# --- query expansion: up to 3 deterministic queries per component ---

def test_component_to_queries_curated_shape():
    component = _component("HTTP fetching with hand-rolled urllib helpers",
                           "Downloading remote resources with urllib.")
    queries = find.component_to_queries(component)
    assert queries == ["http client language:python",
                       "python requests httpx http-client language:python",
                       "topic:http language:python"]
    assert queries[0] == find.component_to_query(component)
    assert queries == find.component_to_queries(component)  # deterministic


def test_component_to_queries_capped_at_three():
    component = _component("Blorping zenthic widgets",
                           "Blorping zenthic widgets with quantum sprockets")
    queries = find.component_to_queries(component)
    assert 1 <= len(queries) <= find.MAX_QUERIES_PER_COMPONENT
    assert queries[0] == find.component_to_query(component)
    assert len(set(queries)) == len(queries)  # deduped


def test_component_to_queries_bare_fallback_stays_single():
    component = _component("!!", "??")
    assert find.component_to_query(component) == "language:python"
    assert find.component_to_queries(component) == ["language:python"]


def test_humanizer_component_maps_to_paraphrase():
    # "latest" contains the "test" substring — the humanizer rule must
    # still win (it precedes the test rule in _QUERY_RULES).
    component = _component(
        "AI text humanizer",
        "Rewrite latest AI-generated text to sound human-written with "
        "varied style and tone to bypass AI detection.")
    assert find.component_to_query(component) == "paraphrase language:python"
    queries = find.component_to_queries(component)
    assert queries == ["paraphrase language:python",
                       "python text augmentation paraphrasing language:python",
                       "topic:nlp language:python"]


# --- .env token loading: parsed directly, never printed ---

def test_load_github_token_parses_dotenv(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    (tmp_path / ".env").write_text(
        '# comment\nOTHER=1\nGITHUB_TOKEN="tok-abc-123"\n', encoding="utf-8")
    try:
        assert github_search.load_github_token() == "tok-abc-123"
        import os
        assert os.environ["GITHUB_TOKEN"] == "tok-abc-123"
        assert capsys.readouterr().out == ""  # never printed
    finally:
        # load_github_token setdefault()s into the real environ, which
        # monkeypatch does not track — pop it so later live-network tests
        # keep the real PAT (teardown then restores the pre-test state).
        import os
        os.environ.pop("GITHUB_TOKEN", None)


def test_load_github_token_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(github_search, "_REPO_ROOT_DOTENV",
                        tmp_path / "missing.env")
    assert github_search.load_github_token() is None


def test_load_github_token_repo_root_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no .env here ...
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    fallback = tmp_path / "fallback.env"
    fallback.write_text("GITHUB_TOKEN=fallback-token\n", encoding="utf-8")
    monkeypatch.setattr(github_search, "_REPO_ROOT_DOTENV", fallback)
    try:
        assert github_search.load_github_token() == "fallback-token"
    finally:
        # Same setdefault leak as above — pop it (see parses_dotenv).
        import os
        os.environ.pop("GITHUB_TOKEN", None)


def test_load_github_token_env_wins(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    assert github_search.load_github_token() == "env-token"


# --- find_for_component: one query, success / empty / rate-limit ---

def test_find_for_component_multi_query_merge_and_order(monkeypatch):
    calls = []

    def _fake(query, limit=10):
        calls.append((query, limit))
        if query == "http client language:python":
            return [_item("psf/requests", 50000), _item("shared/lib", 50)]
        if query == "python requests httpx http-client language:python":
            return [_item("encode/httpx", 9000), _item("shared/lib", 7000)]
        return []

    monkeypatch.setattr(github_search, "search_repos", _fake)
    component = _component("HTTP fetching with hand-rolled urllib helpers",
                           "Downloading remote resources with urllib.")
    got = find.find_for_component(component, delay_s=0)
    expected_queries = find.component_to_queries(component)
    assert len(expected_queries) == 3
    # Component-level queries only, never per candidate (<=3, exact set)
    assert [q for q, _ in calls] == expected_queries
    assert [c["full_name"] for c in got] == ["psf/requests", "encode/httpx",
                                            "shared/lib"]
    assert [c["stars"] for c in got] == [50000, 9000, 7000]  # stars-ordered
    by_name = {c["full_name"]: c for c in got}
    assert by_name["shared/lib"]["stars"] == 7000  # dedupe keeps max stars
    assert by_name["psf/requests"]["query"] == "http client language:python"
    assert all(c["query"] in expected_queries for c in got)  # recorded


def test_find_for_component_dedupes_across_queries(monkeypatch):
    def _fake(query, limit=10):
        return [_item("psf/requests", 50000)]

    monkeypatch.setattr(github_search, "search_repos", _fake)
    component = _component("HTTP fetching", "http fetching")
    got = find.find_for_component(component, delay_s=0)
    assert [c["full_name"] for c in got] == ["psf/requests"]  # one row


def test_find_for_component_quota_mid_sequence(monkeypatch):
    calls = []

    def _fake(query, limit=10):
        calls.append(query)
        if len(calls) == 1:
            return [_item("psf/requests", 50000)]
        raise github_search.RateLimitError("limited", retry_after_s=42.0)

    monkeypatch.setattr(github_search, "search_repos", _fake)
    with pytest.raises(FindError) as exc:
        find.find_for_component(_component("HTTP fetching", "http stuff"),
                                delay_s=0)
    failure = exc.value.failure
    assert (failure["stage"], failure["code"]) == ("find", "quota_hit")
    assert "queries=" in failure["detail"]  # queries tried so far recorded
    assert calls[0] in failure["detail"]
    assert "42" in failure["detail"]


def test_find_for_component_empty_raises_no_candidates(monkeypatch):
    monkeypatch.setattr(github_search, "search_repos", lambda q, limit=10: [])
    component = _component("Blorping zenthic widgets",
                           "Blorping zenthic widgets")
    with pytest.raises(FindError) as exc:
        find.find_for_component(component, delay_s=0)
    failure = exc.value.failure
    assert failure["stage"] == "find"
    assert failure["code"] == "no-candidates"
    # empty from ALL queries -> every query tried is recorded
    assert "queries=" in failure["detail"]
    for query in find.component_to_queries(component):
        assert query in failure["detail"]


def test_find_for_component_rate_limit_maps_to_quota_hit(monkeypatch):
    def _limited(query, limit=10):
        raise github_search.RateLimitError("limited", retry_after_s=42.0)

    monkeypatch.setattr(github_search, "search_repos", _limited)
    with pytest.raises(FindError) as exc:
        find.find_for_component(_component("HTTP fetching", "http stuff"),
                                delay_s=0)
    failure = exc.value.failure
    assert (failure["stage"], failure["code"]) == ("find", "quota_hit")
    assert "42" in failure["detail"]


def test_find_for_component_network_error_maps_to_source_down(monkeypatch):
    def _down(query, limit=10):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(github_search, "search_repos", _down)
    with pytest.raises(FindError) as exc:
        find.find_for_component(_component("HTTP fetching", "http stuff"),
                                delay_s=0)
    assert exc.value.failure["code"] == "source_down"


def test_find_for_components_sleeps_between_queries(monkeypatch):
    monkeypatch.setattr(github_search, "search_repos",
                        lambda q, limit=10: [_item("a/b")])
    sleeps = []
    monkeypatch.setattr(find, "sleep", lambda s: sleeps.append(s))
    components = [_component(f"C{i}", "http fetching") for i in range(3)]
    found, failures = find.find_for_components(components, delay_s=2.0)
    assert failures == []
    assert sorted(found) == ["C0", "C1", "C2"]
    assert all(len(v) == 1 for v in found.values())  # deduped across queries
    # 3 queries per component: 2 within-component sleeps x3, plus 2
    # between-component sleeps; never before the first query.
    assert sleeps == [2.0] * 8


def test_find_for_components_partial_failure_keeps_going(monkeypatch):
    def _fake(query, limit=10):
        if "http" in query:
            return [_item("psf/requests")]
        return []

    monkeypatch.setattr(github_search, "search_repos", _fake)
    components = [_component("HTTP fetching", "http fetching"),
                  _component("Blorping zenthic widgets",
                             "Blorping zenthic widgets quantum sprockets")]
    found, failures = find.find_for_components(components, delay_s=0)
    assert len(found["HTTP fetching"]) == 1
    assert found["Blorping zenthic widgets"] == []
    assert len(failures) == 1
    assert failures[0]["code"] == "no-candidates"


# --- github_search transport: 429 mapping + header auth (mocked urlopen) ---

class _FakeResp:
    def __init__(self, payload, headers=None):
        self._buf = io.StringIO(json.dumps(payload))
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args):
        return self._buf.read()


def test_search_repos_429_raises_rate_limit(monkeypatch):
    def _raise(req, timeout=15):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests",
                                     {"Retry-After": "5"}, None)

    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    with pytest.raises(github_search.RateLimitError) as exc:
        github_search.search_repos("http client language:python")
    assert exc.value.retry_after_s == 5.0


def test_search_repos_403_quota_exhausted_raises_rate_limit(monkeypatch):
    def _raise(req, timeout=15):
        raise urllib.error.HTTPError(
            req.full_url, 403, "Forbidden",
            {"X-RateLimit-Remaining": "0",
             "X-RateLimit-Reset": "9999999999"}, None)

    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    with pytest.raises(github_search.RateLimitError):
        github_search.search_repos("http client language:python")


def test_search_repos_success_sends_token_and_maps_fields(monkeypatch,
                                                          tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    seen = {}

    def _ok(req, timeout=15):
        seen["auth"] = req.get_header("Authorization")
        return _FakeResp({"items": [_item("psf/requests", 50000)]})

    monkeypatch.setattr(urllib.request, "urlopen", _ok)
    got = github_search.search_repos("http client language:python", limit=3)
    assert seen["auth"] == "Bearer secret-token"
    assert got[0]["full_name"] == "psf/requests"
    assert got[0]["url"] == "https://github.com/psf/requests"
    assert got[0]["stars"] == 50000
    assert got[0]["closed_issues"] is None  # dropped per ticket 02
    assert got[0]["license"] == "MIT"


# --- CLI find wiring (mocked find.search: no network) ---

def test_cli_find_prints_candidates(monkeypatch, capsys):
    monkeypatch.setattr(
        find, "search",
        lambda problem, limit=10: [
            {"name": "requests", "full_name": "psf/requests",
             "url": "https://github.com/psf/requests",
             "description": "HTTP for humans", "stars": 50000,
             "query": "http client language:python"}])
    assert cli.main(["find", "HTTP fetching"]) == 0
    out = capsys.readouterr().out
    assert "psf/requests" in out
    assert "https://github.com/psf/requests" in out


def test_cli_find_unencodable_description_does_not_crash(monkeypatch, capsys):
    monkeypatch.setattr(
        find, "search",
        lambda problem, limit=10: [
            {"name": "cli", "full_name": "httpie/cli",
             "url": "https://github.com/httpie/cli",
             "description": "Human-friendly CLI \U0001f967", "stars": 1,
             "query": "cli framework language:python"}])
    assert cli.main(["find", "CLI parsing"]) == 0
    assert "httpie/cli" in capsys.readouterr().out


def test_cli_find_failure_exits_one(monkeypatch, capsys):
    def _fail(problem, limit=10):
        raise FindError({"stage": "find", "code": "no-candidates",
                         "reason": "No candidates found.", "detail": "q",
                         "run_id": "", "component": "", "ts": "t"})

    monkeypatch.setattr(find, "search", _fail)
    assert cli.main(["find", "blorping"]) == 1
    assert "no-candidates" in capsys.readouterr().out
