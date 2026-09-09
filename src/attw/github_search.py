"""GitHub search wrapper (free API, no AI).

search_repos(query, limit=10): search repositories, return per-repo
{full_name, url, description, stars, forks, last_commit_date, open_issues,
closed_issues, license, primary_language}. Vital-sign fields mirror
evidence.github_repo(); they come from the search payload itself so one
call stays one call. closed_issues is always None here — the search API
does not return it, and fetching it per repo would burn the 10 req/min
search quota.

Auth: GITHUB_TOKEN is loaded from `.env` (parsed directly, no new
dependencies) or the environment; it is sent as a header and never
printed or logged. Authenticated search bucket: 30 req/min — callers
(e.g. attw.find) space queries with politeness sleeps; this module
raises RateLimitError on 429 / exhausted-quota 403 instead of sleeping,
so the caller decides what to record.

Rate limits: 429, or 403 with X-RateLimit-Remaining == "0", raises
RateLimitError carrying retry_after_s (from Retry-After or
X-RateLimit-Reset when present).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from attw.evidence import _USER_AGENT, _github_headers

_SEARCH_URL = "https://api.github.com/search/repositories"

#: Authenticated search bucket is 30 req/min -> space queries >= 2s apart.
POLITENESS_DELAY_S = 2.0

#: Repo-root `.env` when running from a source checkout (tests chdir into
#: tmp dirs, so cwd lookup alone would miss it). Monkeypatchable in tests.
_REPO_ROOT_DOTENV = Path(__file__).resolve().parents[2] / ".env"


class RateLimitError(Exception):
    """GitHub search quota exhausted; carries retry_after_s when known."""

    def __init__(self, message: str, *, retry_after_s: float | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


def load_github_token(env_path: str | Path | None = None) -> str | None:
    """Return GITHUB_TOKEN, loading `.env` directly (no new dependencies).

    Precedence: os.environ wins; otherwise parse `<cwd>/.env` (or
    env_path), falling back to the source-checkout repo-root `.env`
    (pytest stages chdir into tmp dirs, so cwd alone would miss it).
    Files are parsed as KEY=VALUE lines (ignores blanks/comments,
    strips matching quotes). A token found in a file is placed into
    os.environ (setdefault) so evidence._github_headers() sends it.
    The token value is never printed or logged. Missing file/token
    returns None (callers proceed unauthenticated).
    """
    existing = os.environ.get("GITHUB_TOKEN")
    if existing:
        return existing
    if env_path is not None:
        return _read_token_file(Path(env_path))
    found = _read_token_file(Path.cwd() / ".env")
    if found is not None:
        return found
    return _read_token_file(_REPO_ROOT_DOTENV)


def _read_token_file(path: Path) -> str | None:
    """Return GITHUB_TOKEN from one dotenv file, or None."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() != "GITHUB_TOKEN":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            os.environ.setdefault("GITHUB_TOKEN", value)
            return value
    return None


def _retry_after_s(headers) -> float | None:
    try:
        retry = headers.get("Retry-After") if headers else None
        if retry is not None:
            return max(0.0, float(retry))
        reset = headers.get("X-RateLimit-Reset") if headers else None
        if reset is not None:
            return max(0.0, float(reset) - time.time() + 1.0)
    except (TypeError, ValueError):
        return None
    return None


def _search(query: str, limit: int) -> list[dict]:
    load_github_token()  # .env -> environ so _github_headers() sends it
    params = urllib.parse.urlencode(
        {"q": query, "per_page": max(1, min(limit, 10)), "sort": "stars"}
    )
    headers = dict(_github_headers())
    headers["User-Agent"] = _USER_AGENT
    req = urllib.request.Request(f"{_SEARCH_URL}?{params}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        headers_of = getattr(exc, "headers", None)
        remaining = headers_of.get("X-RateLimit-Remaining") if headers_of else None
        if exc.code == 429 or (exc.code == 403 and remaining == "0"):
            raise RateLimitError(
                f"GitHub search rate-limited (HTTP {exc.code} for {query!r}).",
                retry_after_s=_retry_after_s(headers_of),
            ) from exc
        raise
    return data.get("items", [])


def search_repos(query: str, limit: int = 10) -> list[dict]:
    """Search GitHub repos, returning vital signs per hit."""
    results = []
    for item in _search(query, limit):
        lic = item.get("license") or {}
        results.append(
            {
                "full_name": item.get("full_name"),
                "url": item.get("html_url"),
                "description": item.get("description"),
                "stars": item.get("stargazers_count"),
                "forks": item.get("forks_count"),
                "last_commit_date": item.get("pushed_at"),
                "open_issues": item.get("open_issues_count"),
                "closed_issues": None,
                "license": lic.get("spdx_id") or lic.get("name"),
                "primary_language": item.get("language"),
            }
        )
    return results
