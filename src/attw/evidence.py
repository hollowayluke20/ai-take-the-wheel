"""Evidence stage: fetch free real-world evidence for candidate solutions.

Implements ticket 02's decided v1 spec (## Proposal):

- PAT-mandatory posture: ``GITHUB_TOKEN`` is loaded from ``.env`` via
  :mod:`attw.github_search` (reused loader; never printed/logged). Without a
  PAT, GitHub 401/403/429 degrades to ``no_pat_unauth_capped`` and the run
  continues on cache only.
- P0: ``GET /repos`` payload, PyPI JSON, pypistats last_month + trend,
  deps.dev GetVersion (vulns + SPDX tiebreak).
- P1: deps.dev dependencies (dep count), SO/HN mention counts (WEEKLY cache
  only), discussion proxy (piggybacked), docs/tests/typing heuristics
  (git-tree, 1 cheap call).
- P2: dependents count + awesome-list hits (WEEKLY cache only).
- BANNED: per-candidate ``GET /search/issues``,
  ``GET /search/repositories``, and any per-candidate StackExchange/Algolia
  live call. The weekly refresh job is the ONLY caller of those endpoints.
- Failures are ``null`` + reason enum, never zero-filled, never fabricated.
  Every cell carries source link + ``as_of``/``stale`` (ticket 05 D4).

Stdlib only (urllib).
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from attw.failures import make_failure

_TIMEOUT = 15
_USER_AGENT = "attw/0.0.1 (evidence fetcher)"

# 02 Proposal L162-170: one cache file per ISO week + a `mentions_latest`
# copy. Resolved against the repo root (not cwd) so pytest stages that
# chdir into tmp dirs still hit the real cache; tests override via env.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CACHE_DIR = _REPO_ROOT / "database" / "cache"

# Single retry delay on 429/5xx before degrading (tests set to 0).
_RETRY_DELAY_S = 2.0

# SO/HN/awesome cells older than this are served with stale:true (02 L168).
_STALE_AFTER_DAYS = 9

# deps.dev v3, free, no key, 429+backoff only (02 research notes).
_DEPSDEV = "https://api.deps.dev/v3/systems/PYPI/packages"

# Weekly-job endpoints (ONLY called from the refresh path, never per-run).
_SO_URL = "https://api.stackexchange.com/2.3/search/advanced"
_HN_URL = "https://hn.algolia.com/api/v1/search"
_AWESOME_URL = (
    "https://raw.githubusercontent.com/vinta/awesome-python/master/README.md"
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cache_dir() -> Path:
    override = os.environ.get("ATTW_CACHE_DIR")
    return Path(override) if override else _DEFAULT_CACHE_DIR


def _current_week_id() -> str:
    year, week, _ = datetime.now(timezone.utc).isocalendar()
    return f"{year}-W{week:02d}"


def _norm_name(name: str) -> str:
    """PEP 503-ish normalization for cache keys."""
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def _is_stale(fetched_at: str | None) -> bool:
    if not fetched_at:
        return True
    try:
        ts = datetime.fromisoformat(fetched_at)
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - ts > timedelta(days=_STALE_AFTER_DAYS)


def _cell(
    value,
    source: str,
    *,
    missing: str | None = None,
    as_of: str | None = None,
    stale: bool = False,
    detail: str = "",
) -> dict:
    """One evidence cell (05 D4): value + source link + as_of/stale.

    On failure ``value`` is None and ``missing`` carries the 02 L192-200
    reason enum — never a zero-fill, never fabricated (LOOP §9).
    """
    return {
        "value": value,
        "source": source,
        "as_of": as_of or _utcnow(),
        "stale": stale,
        "missing": missing,
        "detail": detail,
    }


def _get_json(url: str, headers: dict | None = None) -> dict:
    req_headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.load(resp)


def _get_text(url: str, headers: dict | None = None) -> str:
    req_headers = {"User-Agent": _USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch(url: str, headers: dict | None = None):
    """GET JSON with ONE retry on 429/5xx, else return the error.

    Returns ``(data, None)`` on success or ``(None, exc)`` on failure so
    callers can map the exception to a null+reason cell. No search-API
    quota is ever burned here — callers pass exact resource URLs only.
    """
    try:
        return _get_json(url, headers), None
    except urllib.error.HTTPError as exc:
        if exc.code == 429 or 500 <= exc.code <= 599:
            time.sleep(_RETRY_DELAY_S)
            try:
                return _get_json(url, headers), None
            except Exception as retry_exc:  # noqa: BLE001 — classified below
                return None, retry_exc
        return None, exc
    except Exception as exc:  # noqa: BLE001 — URLError/TimeoutError -> down
        return None, exc


def _github_reason(exc: Exception, has_pat: bool) -> str:
    """02 Proposal §5: 403/429 without PAT -> unauth-capped, else quota."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403, 429):
            return "quota_hit" if has_pat else "no_pat_unauth_capped"
        return "source_down"
    return "source_down"


def _http_reason(exc: Exception) -> str:
    """PyPI/pypistats/deps.dev: 429 -> quota, 404 -> N/A, rest -> down."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 429:
            return "quota_hit"
        if exc.code == 404:
            return "not_applicable"
        return "source_down"
    return "source_down"


def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _parse_owner_repo(url: str) -> tuple[str, str] | None:
    if "github.com" not in url:
        return None
    path = urllib.parse.urlparse(url).path.strip("/").removesuffix(".git")
    parts = path.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _discover_repo_url(pypi_data: dict) -> str:
    """Pick the first github.com URL from PyPI metadata (0 extra calls)."""
    info = pypi_data.get("info", {}) or {}
    urls = [info.get("home_page") or ""]
    project_urls = info.get("project_urls") or {}
    if isinstance(project_urls, dict):
        urls.extend(str(v) for v in project_urls.values())
    for url in urls:
        if "github.com" in str(url):
            return str(url).strip()
    return ""


def _classifiers_license(pypi_data: dict) -> str | None:
    info = pypi_data.get("info", {}) or {}
    for classifier in info.get("classifiers", []) or []:
        marker = "License :: OSI Approved :: "
        if classifier.startswith(marker):
            return classifier[len(marker):].strip() or None
    return None


# Common PyPI-classifier wordings -> SPDX-ish ids for fair comparison.
_LICENSE_ALIASES = {
    "apache software license": "apache-2.0",
    "apache license 2.0": "apache-2.0",
    "apache license, version 2.0": "apache-2.0",
    "bsd license": "bsd",
    "isc license (iscl)": "isc",
    "mozilla public license 2.0 (mpl 2.0)": "mpl-2.0",
    "gnu general public license v3 (gplv3)": "gpl-3.0",
    "gnu lesser general public license v3 (lgplv3)": "lgpl-3.0",
}


def _norm_license(value: str | None) -> str | None:
    """Compare SPDX-ish strings fairly: 'MIT' == 'MIT License'."""
    if not value:
        return None
    full = re.sub(r"\s+", " ", value.strip().lower())
    if full in _LICENSE_ALIASES:
        return _LICENSE_ALIASES[full]
    short = re.sub(r"\s+licen[cs]e$", "", full)
    return _LICENSE_ALIASES.get(short, short) or None


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
            f"https://pypistats.org/api/packages/{urllib.parse.quote(name)}/recent"
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


def _tree_heuristics(tree_data: dict, requires_python: str | None) -> dict:
    """Boolean docs/tests/typing flags from a git-tree payload (02 L123)."""
    entries = tree_data.get("tree", []) or []
    basenames = [str(e.get("path", "")).lower() for e in entries]
    leaf_names = [p.split("/")[-1] for p in basenames]

    def has_prefix(*prefixes: str) -> bool:
        return any(p.startswith(prefixes) for p in basenames)

    def has_base(*names: str) -> bool:
        return any(leaf in names for leaf in leaf_names)

    def starts_base(*starts: str) -> bool:
        return any(leaf.startswith(starts) for leaf in leaf_names)

    flags = {
        "readme": starts_base("readme"),
        "docs": has_prefix("docs/", "doc/", "documentation/"),
        "tests": has_prefix("tests/", "test/")
        or any(
            b.endswith("_test.py") or b.startswith("test_") for b in leaf_names
        ),
        "py_typed": has_base("py.typed"),
        "changelog": starts_base("changelog", "changes", "history", "news"),
        "requires_python_bound": bool(requires_python),
    }
    return flags


def _vulns_from_depsdev(data: dict) -> list[dict]:
    """Advisory ids + severities from a deps.dev GetVersion payload."""
    vulns = []
    for adv in data.get("advisories", []) or []:
        key = adv.get("advisoryKey", {}) or {}
        vid = key.get("id") or adv.get("id") or adv.get("url")
        if vid:
            vulns.append({"id": vid, "severity": adv.get("severity")})
    return vulns


def collect_evidence(candidate: dict | str) -> dict:
    """Fetch the full 02-spec signal set for one candidate (02 Proposal §2).

    Exact sequence, search-API calls BANNED: GET /repos, PyPI JSON,
    pypistats recent, deps.dev GetVersion, GetDependencies (P1, skip on
    429), git-tree heuristics (P1, skip on quota), plus LOCAL weekly-cache
    reads for SO/HN/awesome/dependents. A stale/missing cache triggers ONE
    fetch-once-then-store refresh when quota allows, else stale/missing
    cells (02 §3). Every failure is a null+reason cell + failure record.
    """
    from attw.github_search import load_github_token

    if isinstance(candidate, str):
        candidate = {"candidate": candidate}
    if not isinstance(candidate, dict):
        raise ValueError(f"candidate must be a name or dict, got {type(candidate)}")
    name = str(
        candidate.get("pypi_name")
        or candidate.get("candidate")
        or candidate.get("name")
        or ""
    ).strip()
    repo_url = str(
        candidate.get("repo_url")
        or candidate.get("url")
        or candidate.get("html_url")
        or ""
    ).strip()
    if not name and repo_url:
        parsed = _parse_owner_repo(repo_url)
        name = parsed[1] if parsed else ""
    if not name:
        raise ValueError("collect_evidence needs a candidate name or repo_url")

    load_github_token()  # .env -> environ; value never printed/logged
    has_pat = bool(os.environ.get("GITHUB_TOKEN"))
    fetched_at = _utcnow()
    cells: dict[str, dict] = {}
    failures: list[dict] = []

    def _fail(signal: str, source: str, code: str, reason: str, detail: str = ""):
        cells[signal] = _cell(None, source, missing=code, detail=detail or reason)
        failures.append(
            make_failure("evidence", code, reason, detail=detail, component=name)
        )

    quoted = urllib.parse.quote(name)

    # --- P0: PyPI JSON (also the repo-URL discovery source, 0 extra calls).
    pypi_url = f"https://pypi.org/pypi/{quoted}/json"
    pypi_data, pypi_err = _fetch(pypi_url)
    version: str | None = None
    requires_python: str | None = None
    if pypi_err is not None:
        code = _http_reason(pypi_err)
        for signal in ("pypi_version", "release_date", "requires_python"):
            _fail(signal, pypi_url, code, f"PyPI JSON failed: {pypi_err}")
    else:
        info = pypi_data.get("info", {}) or {}
        version = info.get("version")
        requires_python = info.get("requires_python")
        uploads = (pypi_data.get("releases", {}) or {}).get(version, [])
        times = [
            u.get("upload_time_iso_8601")
            for u in uploads
            if u.get("upload_time_iso_8601")
        ]
        cells["pypi_version"] = _cell(version, pypi_url)
        cells["release_date"] = _cell(max(times) if times else None, pypi_url)
        cells["requires_python"] = _cell(requires_python, pypi_url)
        if not repo_url:
            repo_url = _discover_repo_url(pypi_data)

    # --- P0: GitHub repo payload (single GET /repos; search calls BANNED).
    owner_repo = _parse_owner_repo(repo_url) if repo_url else None
    github_signals = (
        "stars",
        "forks",
        "last_commit_date",
        "open_issues",
        "primary_language",
        "license_spdx",
    )
    repos_url = ""
    default_branch: str | None = None
    github_ok = False
    github_license: str | None = None
    if owner_repo is None:
        for signal in github_signals:
            _fail(
                signal,
                "",
                "not_applicable",
                "No GitHub repo URL known for this candidate",
            )
        cells["discussion_proxy"] = _cell(
            None, "", missing="not_applicable", detail="piggybacks GET /repos"
        )
        failures.append(
            make_failure(
                "evidence",
                "not_applicable",
                "discussion proxy needs the GET /repos payload",
                component=name,
            )
        )
    else:
        owner, repo = owner_repo
        repos_url = f"https://api.github.com/repos/{owner}/{repo}"
        repo_data, repo_err = _fetch(repos_url, _github_headers())
        if repo_err is not None:
            code = _github_reason(repo_err, has_pat)
            for signal in github_signals:
                _fail(signal, repos_url, code, f"GET /repos failed: {repo_err}")
            _fail(
                "discussion_proxy",
                repos_url,
                code,
                f"discussion proxy needs GET /repos: {repo_err}",
            )
        else:
            github_ok = True
            lic = repo_data.get("license") or {}
            github_license = lic.get("spdx_id") or lic.get("name")
            default_branch = repo_data.get("default_branch")
            for signal, key in (
                ("stars", "stargazers_count"),
                ("forks", "forks_count"),
                ("last_commit_date", "pushed_at"),
                ("open_issues", "open_issues_count"),
                ("primary_language", "language"),
            ):
                cells[signal] = _cell(repo_data.get(key), repos_url)
            cells["license_spdx"] = _cell(github_license, repos_url)
            cells["discussion_proxy"] = _cell(
                {
                    "open_issues": repo_data.get("open_issues_count"),
                    "pushed_at": repo_data.get("pushed_at"),
                },
                repos_url,
                detail="proxy: issue/PR volume from the /repos payload (02 L75)",
            )

    # --- P0: pypistats last_month + trend (IGNORE raw day counts, 02 L117).
    stats_url = f"https://pypistats.org/api/packages/{quoted}/recent"
    stats_source = f"https://pypistats.org/packages/{quoted}"
    stats_data, stats_err = _fetch(stats_url)
    if stats_err is not None:
        code = _http_reason(stats_err)
        for signal in ("downloads_last_month", "download_trend"):
            _fail(signal, stats_source, code, f"pypistats failed: {stats_err}")
    else:
        recent = stats_data.get("data", {}) or {}
        last_month = recent.get("last_month")
        last_week = recent.get("last_week")
        trend = None
        if isinstance(last_month, (int, float)) and last_month:
            if isinstance(last_week, (int, float)):
                trend = round(last_week / last_month, 4)
        cells["downloads_last_month"] = _cell(last_month, stats_source)
        cells["download_trend"] = _cell(
            trend, stats_source, detail="last_week / last_month"
        )

    # --- P0: deps.dev GetVersion -> vulns (mark down, never veto) + SPDX.
    deps_version_url = ""
    deps_spdx: str | None = None
    if not version:
        for signal in ("vulns",):
            _fail(
                signal,
                "",
                "not_applicable",
                "No PyPI version to query GetVersion for",
            )
    else:
        deps_version_url = f"{_DEPSDEV}/{quoted}/versions/{urllib.parse.quote(version)}"
        deps_source = f"https://deps.dev/pypi/{quoted}/{urllib.parse.quote(version)}"
        deps_data, deps_err = _fetch(deps_version_url)
        if deps_err is not None:
            code = _http_reason(deps_err)
            _fail("vulns", deps_source, code, f"deps.dev GetVersion failed: {deps_err}")
        else:
            vulns = _vulns_from_depsdev(deps_data)
            licenses = deps_data.get("licenses") or []
            deps_spdx = licenses[0] if licenses else None
            cells["vulns"] = _cell(vulns, deps_source)

    # --- License combine (factor, never veto; prose warning only, 02 L130).
    pypi_lic = _classifiers_license(pypi_data) if pypi_data else None
    license_value = github_license or pypi_lic or deps_spdx
    if "license_spdx" in cells and cells["license_spdx"]["value"] is None:
        if license_value and pypi_data is not None:
            cells["license_spdx"] = _cell(license_value, pypi_url)
    license_warning: str | None = None
    seen = {_norm_license(v) for v in (github_license, pypi_lic, deps_spdx) if v}
    seen.discard(None)
    if not seen:
        license_warning = (
            f"No license detected for {name} from GitHub/PyPI/deps.dev; "
            "check before adopting (prose flag only, no score effect)."
        )
    elif len(seen) > 1:
        license_warning = (
            f"License sources disagree for {name} "
            f"(GitHub={github_license}, PyPI={pypi_lic}, deps.dev={deps_spdx}); "
            "treating as prose flag only, no score effect."
        )

    # --- P1: dep count (skippable on 429, 02 L119).
    deps_deps_url = (
        f"{deps_version_url}:dependencies" if deps_version_url else ""
    )
    if not deps_deps_url:
        _fail(
            "dep_count",
            "",
            "not_applicable",
            "No version to query GetDependencies for",
        )
    else:
        dep_data, dep_err = _fetch(deps_deps_url)
        if dep_err is not None:
            _fail(
                "dep_count",
                deps_deps_url,
                _http_reason(dep_err),
                f"GetDependencies failed: {dep_err}",
            )
        else:
            nodes = dep_data.get("nodes", []) or []
            cells["dep_count"] = _cell(
                len(nodes),
                deps_deps_url,
                detail="direct dependencies (first page)",
            )

    # --- P1: git-tree heuristics (skip on quota, 02 L123).
    if not github_ok or owner_repo is None:
        reason = "GET /repos unavailable, tree heuristics skipped"
        code = (
            cells.get("stars", {}).get("missing")
            if cells.get("stars", {}).get("missing")
            else "not_applicable"
        )
        _fail("heuristics", "", code, reason)
    else:
        owner, repo = owner_repo
        branch = default_branch or "HEAD"
        tree_url = (
            f"https://api.github.com/repos/{owner}/{repo}"
            f"/git/trees/{branch}?recursive=1"
        )
        tree_data, tree_err = _fetch(tree_url, _github_headers())
        if tree_err is not None:
            _fail(
                "heuristics",
                tree_url,
                _github_reason(tree_err, has_pat),
                f"git-tree fetch failed: {tree_err}",
            )
        else:
            flags = _tree_heuristics(tree_data, requires_python)
            detail = "truncated tree" if tree_data.get("truncated") else ""
            cells["heuristics"] = _cell(flags, tree_url, detail=detail)

    # --- Weekly cache reads (SO/HN/awesome/dependents): LOCAL, 0 network.
    # Cache MISS = fetch-once-then-store when quota allows (02 §3: first
    # run of the new week refreshes), else stale/missing cells.
    cache = _cache_state(_norm_name(name))
    if cache["state"] != "hit":
        try:
            _refresh_lib(name)
            cache = _cache_state(_norm_name(name))
        except Exception as exc:  # noqa: BLE001 — refresh is best-effort
            failures.append(
                make_failure(
                    "evidence",
                    "stale_cache",
                    f"weekly cache refresh failed: {exc}",
                    component=name,
                )
            )
    entry = cache["entry"] or {}
    cache_as_of = cache["fetched_at"] or fetched_at
    cache_stale = cache["state"] != "hit"
    cache_missing = (
        "stale_cache" if entry is None or not entry else None
    )
    for signal, key in (
        ("so_count", "so_count"),
        ("so_top_score", "so_top_score"),
        ("hn_count", "hn_count"),
        ("hn_top_points", "hn_top_points"),
        ("sentiment_snippet", "sentiment_snippet"),
        ("dependents_count", "dependents_count"),
    ):
        value = entry.get(key) if entry else None
        missing = None if value is not None else cache_missing or "stale_cache"
        cells[signal] = _cell(
            value,
            "weekly-cache",
            missing=missing,
            as_of=cache_as_of,
            stale=cache_stale,
            detail=f"week {cache['week_id']}" if cache["week_id"] else "no cache file",
        )
    awesome = (entry.get("awesome_hits") or {}) if entry else {}
    awesome_value = awesome or None
    cells["awesome_hits"] = _cell(
        awesome_value,
        "weekly-cache",
        missing=None if awesome_value else (cache_missing or "stale_cache"),
        as_of=cache_as_of,
        stale=cache_stale,
        detail=f"week {cache['week_id']}" if cache["week_id"] else "no cache file",
    )

    return {
        "candidate": name,
        "repo_url": repo_url or None,
        "fetched_at": fetched_at,
        "cells": cells,
        "failures": failures,
        "license_warning": license_warning,
    }


def _cache_state(norm: str) -> dict:
    """Read-only weekly-cache lookup (no network, ever)."""
    latest = _cache_dir() / "mentions_latest.json"
    if not latest.exists():
        return {
            "state": "missing",
            "entry": None,
            "fetched_at": None,
            "week_id": None,
        }
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "state": "missing",
            "entry": None,
            "fetched_at": None,
            "week_id": None,
        }
    libs = payload.get("libs", {}) or {}
    entry = libs.get(norm)
    fetched_at = payload.get("fetched_at")
    week_id = payload.get("week_id")
    if entry and not _is_stale(fetched_at) and week_id == _current_week_id():
        return {
            "state": "hit",
            "entry": entry,
            "fetched_at": fetched_at,
            "week_id": week_id,
        }
    return {
        "state": "refresh-needed",
        "entry": entry,
        "fetched_at": fetched_at,
        "week_id": week_id,
    }


def _so_entry(package: str) -> dict | None:
    """StackExchange mention count + top score (weekly job ONLY)."""
    params = urllib.parse.urlencode(
        {
            "site": "stackoverflow",
            "q": package,
            "pagesize": 10,
            "order": "desc",
            "sort": "votes",
        }
    )
    data, err = _fetch(f"{_SO_URL}?{params}")
    if err is not None or not isinstance(data, dict):
        return None
    items = data.get("items", []) or []
    scores = [i.get("score", 0) for i in items if isinstance(i.get("score"), int)]
    return {
        "so_count": len(items),
        "so_top_score": max(scores) if scores else 0,
        "so_top_qids": [i.get("question_id") for i in items[:3]],
        "so_titles": [str(i.get("title", ""))[:200] for i in items[:3]],
    }


def _hn_entry(package: str) -> dict | None:
    """HN Algolia story/comment count + points (weekly job ONLY)."""
    params = urllib.parse.urlencode({"query": package, "hitsPerPage": 20})
    data, err = _fetch(f"{_HN_URL}?{params}")
    if err is not None or not isinstance(data, dict):
        return None
    hits = data.get("hits", []) or []
    points = [h.get("points", 0) for h in hits if isinstance(h.get("points"), int)]
    return {
        "hn_count": data.get("nbHits", len(hits)),
        "hn_top_points": max(points) if points else 0,
        "hn_top_ids": [h.get("objectID") for h in hits[:3]],
        "hn_titles": [str(h.get("title", ""))[:200] for h in hits[:3]],
    }


def _awesome_entry(package: str) -> dict | None:
    """awesome-list hits via cached raw-fetch + grep (weekly job ONLY)."""
    try:
        text = _get_text(_AWESOME_URL)
    except Exception:  # noqa: BLE001 — any fetch problem -> sparse entry
        return None
    needle = package.lower()
    hits = [ln.strip()[:200] for ln in text.splitlines() if needle in ln.lower()]
    return {
        "count": len(hits),
        "lists": ["awesome-python"] if hits else [],
    }


def _dependents_entry(package: str, version: str | None) -> int | None:
    """deps.dev dependents first-page count (weekly job ONLY per §2 step 7).

    Dependents live one level down from the package: per-VERSION
    ``.../versions/{v}:dependents`` (the package-level path 404s).
    """
    if not version:
        return None
    quoted = urllib.parse.quote(package)
    version_quoted = urllib.parse.quote(version)
    data, err = _fetch(f"{_DEPSDEV}/{quoted}/versions/{version_quoted}:dependents")
    if err is not None or not isinstance(data, dict):
        return None
    return len(data.get("nodes", []) or [])


def _pypi_version(package: str) -> str | None:
    """Latest version from PyPI JSON (weekly-job helper, 0 extra quota)."""
    data, err = _fetch(f"https://pypi.org/pypi/{urllib.parse.quote(package)}/json")
    if err is not None:
        return None
    return (data.get("info", {}) or {}).get("version")


def _refresh_one(package: str) -> dict:
    """Fetch one lib's weekly signals (SO + HN + awesome + dependents)."""
    entry: dict = {}
    so = _so_entry(package)
    if so:
        entry.update({k: v for k, v in so.items() if not k.endswith("_titles")})
    hn = _hn_entry(package)
    if hn:
        entry.update({k: v for k, v in hn.items() if not k.endswith("_titles")})
    titles = (so or {}).get("so_titles", []) + (hn or {}).get("hn_titles", [])
    if titles:
        entry["sentiment_snippet"] = "; ".join(titles[:6])[:600]
    awesome = _awesome_entry(package)
    if awesome is not None:
        entry["awesome_hits"] = awesome
    dependents = _dependents_entry(package, _pypi_version(package))
    if dependents is not None:
        entry["dependents_count"] = dependents
    return entry


def _write_cache(payload: dict) -> Path:
    cache_dir = _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    week_path = cache_dir / f"mentions_{payload['week_id']}.json"
    text = json.dumps(payload, indent=2)
    week_path.write_text(text, encoding="utf-8")
    (cache_dir / "mentions_latest.json").write_text(text, encoding="utf-8")
    return week_path


def _refresh_lib(package: str) -> dict:
    """Fetch-once-then-store for a single lib (02 §3 refresh rule)."""
    week_id = _current_week_id()
    cache_dir = _cache_dir()
    week_path = cache_dir / f"mentions_{week_id}.json"
    if week_path.exists():
        try:
            payload = json.loads(week_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
    else:
        payload = {}
    payload.setdefault("week_id", week_id)
    payload.setdefault("libs", {})
    entry = _refresh_one(package)
    payload["libs"][_norm_name(package)] = entry
    payload["fetched_at"] = _utcnow()
    _write_cache(payload)
    return entry


def refresh_weekly_cache(
    week_id: str | None = None, packages: list | None = None
) -> str:
    """Weekly SO/HN/awesome refresh job (02 Proposal L154-170).

    Writes ``database/cache/mentions_<week_id>.json`` (+ ``mentions_latest``
    copy). If the week file already exists it is reused untouched (nightly
    runs never refresh mid-week); with ``packages`` given, missing libs are
    merged in. This is the ONLY caller of the StackExchange/Algolia/awesome
    endpoints — per-candidate collection never fetches them live.
    """
    week = week_id or _current_week_id()
    cache_dir = _cache_dir()
    week_path = cache_dir / f"mentions_{week}.json"
    if week_path.exists():
        try:
            payload = json.loads(week_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {"week_id": week, "libs": {}}
        payload.setdefault("libs", {})
        for package in packages or []:
            if _norm_name(package) not in payload["libs"]:
                payload["libs"][_norm_name(package)] = _refresh_one(package)
                payload["fetched_at"] = _utcnow()
        if packages:
            _write_cache(payload)
        else:
            latest = cache_dir / "mentions_latest.json"
            if not latest.exists():
                payload.setdefault("fetched_at", _utcnow())
                _write_cache(payload)
        return str(week_path)
    libs = {}
    for package in packages or []:
        libs[_norm_name(package)] = _refresh_one(package)
    payload = {"week_id": week, "fetched_at": _utcnow(), "libs": libs}
    return str(_write_cache(payload))
