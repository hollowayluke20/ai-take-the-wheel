"""Evidence stage: fetch free real-world evidence for candidate solutions.

No AI, no paid APIs. Three fetchers, all stdlib-only (urllib):

- github_repo(url): stars, forks, last_commit_date, open_issues,
  license, primary_language via one GET /repos call (02 Proposal L114;
  per-candidate search-API calls BANNED, closed_issues DROPPED per L126).
- pypi_package(name): latest_version, latest_release_date, recent download
  counts via PyPI JSON + the pypistats API.
- npm_package(name): latest_version, last_publish_date, weekly downloads
  via the npm registry + api.npmjs.org.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

_TIMEOUT = 15
_USER_AGENT = "attw/0.0.1 (evidence fetcher)"


def collect_evidence(candidate: dict) -> dict:
    """Per-candidate fetch-plan entry point (02 Proposal L134-152).

    Exact sequence (search-API calls BANNED): GET /repos, PyPI JSON,
    pypistats recent, deps.dev GetVersion, GetDependencies (P1, skip on
    429), git-tree heuristics, plus local weekly-cache reads. Skeleton.
    """
    _ = candidate
    raise NotImplementedError("collect_evidence not implemented (ticket 05)")


def refresh_weekly_cache(week_id: str | None = None) -> str:
    """Weekly SO/HN/awesome refresh job (02 Proposal L154-170). Skeleton.

    Reads live endpoints once per ISO week into
    database/cache/mentions_<week_id>.json. NO live network in ticket 05.
    """
    _ = week_id
    raise NotImplementedError("refresh_weekly_cache not implemented (ticket 05)")


def _get_json(url: str, headers: dict | None = None) -> dict:
    req_headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.load(resp)


def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_repo(url: str) -> dict:
    """Fetch vital signs for a GitHub repo URL.

    Single GET /repos call only (02 Proposal L138, L149). closed_issues is
    DROPPED per 02 Proposal L126 — the per-candidate GET /search/issues call
    is DELETED (separate 10/min bucket); no null+reason cell is emitted for
    it because the signal itself was dropped, not degraded.
    """
    path = urllib.parse.urlparse(url).path.strip("/").removesuffix(".git")
    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError(f"Not a GitHub repo URL: {url!r}")
    owner, repo = parts[0], parts[1]

    data = _get_json(
        f"https://api.github.com/repos/{owner}/{repo}", _github_headers()
    )
    lic = data.get("license") or {}

    return {
        "stars": data.get("stargazers_count"),
        "forks": data.get("forks_count"),
        "last_commit_date": data.get("pushed_at"),
        "open_issues": data.get("open_issues_count"),
        "license": lic.get("spdx_id") or lic.get("name"),
        "primary_language": data.get("language"),
    }


def pypi_package(name: str) -> dict:
    """Fetch version, release date and recent downloads for a PyPI package."""
    data = _get_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
    version = data["info"]["version"]
    uploads = data.get("releases", {}).get(version, [])
    times = [
        u.get("upload_time_iso_8601")
        for u in uploads
        if u.get("upload_time_iso_8601")
    ]
    latest_release_date = max(times) if times else None

    downloads_last_day: int | None = None
    downloads_last_week: int | None = None
    downloads_last_month: int | None = None
    try:
        stats = _get_json(
            f"https://pypistats.org/api/packages/pypi/recent/{urllib.parse.quote(name)}"
        )
        stats_data = stats.get("data", {})
        downloads_last_day = stats_data.get("last_day")
        downloads_last_week = stats_data.get("last_week")
        downloads_last_month = stats_data.get("last_month")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        pass

    return {
        "latest_version": version,
        "latest_release_date": latest_release_date,
        "downloads_last_day": downloads_last_day,
        "downloads_last_week": downloads_last_week,
        "downloads_last_month": downloads_last_month,
    }


def npm_package(name: str) -> dict:
    """Fetch version, publish date and weekly downloads for an npm package."""
    quoted = urllib.parse.quote(name, safe="")
    meta = _get_json(f"https://registry.npmjs.org/{quoted}")
    version = (meta.get("dist-tags") or {}).get("latest")
    last_publish_date = (meta.get("time") or {}).get(version) if version else None

    weekly_downloads: int | None = None
    try:
        dl = _get_json(f"https://api.npmjs.org/downloads/point/last-week/{quoted}")
        weekly_downloads = dl.get("downloads")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        pass

    return {
        "latest_version": version,
        "last_publish_date": last_publish_date,
        "weekly_downloads": weekly_downloads,
    }
