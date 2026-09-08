"""GitHub search wrapper (free API, no AI).

search_repos(query, limit=10): search repositories, return per-repo
{full_name, url, description, stars, forks, last_commit_date, open_issues,
closed_issues, license, primary_language}. Vital-sign fields mirror
evidence.github_repo(); they come from the search payload itself so one
call stays one call. closed_issues is always None here — the search API
does not return it, and fetching it per repo would burn the 10 req/min
search quota.

Rate limits: after each search call we read X-RateLimit-Remaining /
X-RateLimit-Reset and sleep until reset (+1s) when exhausted.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from attw.evidence import _USER_AGENT, _github_headers

_SEARCH_URL = "https://api.github.com/search/repositories"


def _search(query: str, limit: int) -> list[dict]:
    params = urllib.parse.urlencode(
        {"q": query, "per_page": max(1, min(limit, 10)), "sort": "stars"}
    )
    headers = dict(_github_headers())
    headers["User-Agent"] = _USER_AGENT
    req = urllib.request.Request(f"{_SEARCH_URL}?{params}", headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        remaining = resp.headers.get("X-RateLimit-Remaining")
        reset = resp.headers.get("X-RateLimit-Reset")
        data = json.load(resp)
    if remaining == "0" and reset:
        time.sleep(max(0, int(reset) - int(time.time()) + 1))
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
