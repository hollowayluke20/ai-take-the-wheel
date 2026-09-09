"""Find stage: per Component, find candidate wheels via GitHub search.

Contract (tickets 02/05/08 + map bar):

- ONE search-API query per component, never per candidate (02 ban:
  search is for *finding*). Candidates are ranked by relevance =
  GitHub stars order (the search API's ``sort=stars``).
- Authenticated via GITHUB_TOKEN loaded from `.env`
  (github_search.load_github_token parses the file directly; the token
  is never printed, logged, or committed). Queries are spaced
  POLITENESS_DELAY_S apart for the authed 30 req/min search bucket.
- Query-mapping rule (deterministic): the lowercase
  ``"<name> <description>"`` text is scanned against _QUERY_RULES in
  order; the first rule with any keyword present as a substring wins
  and yields its curated query. No rule matches -> fallback: first 5
  significant tokens (lowercased alphanumerics, stopwords and
  <3-char tokens dropped, order preserved, deduped) joined with
  ``" language:python"``.
- No fabricated candidates: an empty result raises FindError carrying
  the exact failure record ``find/no-candidates`` (detail holds the
  query tried). Rate-limiting raises FindError ``find/quota_hit``;
  other network failures raise FindError ``find/source_down``.
"""

from __future__ import annotations

import json
import re
import urllib.error
from time import sleep
from typing import TypedDict

from attw import github_search
from attw.failures import make_failure

STAGE = "find"

CODE_NO_CANDIDATES = "no-candidates"  # ticket-08 spec (custom code)
CODE_QUOTA = "quota_hit"
CODE_DOWN = "source_down"


class Candidate(TypedDict):
    """One find-stage candidate, ready for evidence collection."""

    name: str
    full_name: str
    url: str
    description: str
    stars: int | None
    query: str


class FindError(Exception):
    """find_for_component() failed; carries the exact failure record."""

    def __init__(self, failure: dict):
        super().__init__(failure.get("reason", "find failed"))
        self.failure = failure


def _fail(code: str, reason: str, component: str = "", detail: str = "") -> FindError:
    return FindError(make_failure(STAGE, code, reason, detail=detail,
                                 component=component))


# Ordered (keywords, query): first rule with any keyword as a substring
# of the lowercased "<name> <description>" wins. Covers the six
# understand.py hand-rolled patterns + the missing-test-suite addition.
_QUERY_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("urllib", "urlopen", "http", "requests", "httpx", "fetch", "download"),
     "http client language:python"),
    (("argparse", "argv", "cli", "command-line", "command line",
       "click", "typer"), "cli framework language:python"),
    (("csv", "delimited"), "csv parser language:python"),
    (("retry", "backoff", "tenacity", "flaky"),
     "retry backoff language:python"),
    (("config", "dotenv", "setting", "environ", "layered"),
     "configuration management language:python"),
    (("isinstance", "validat", "pydantic", "schema", "attrs"),
     "data validation language:python"),
    (("test", "pytest", "suite"), "testing framework language:python"),
    (("dataframe", "pandas"), "dataframe language:python"),
    (("log", "logging"), "logging language:python"),
    (("progress", "tqdm", "eta"), "progress bar language:python"),
)

_STOPWORDS = frozenset({
    "the", "and", "plus", "for", "from", "into", "instead", "with",
    "hand", "rolled", "built", "using", "use", "code", "that", "this",
    "are", "its", "such", "than", "then", "they", "your", "you", "our",
    "their", "his", "her", "she", "him", "not", "but", "all", "any",
    "can", "had", "has", "have", "was", "one", "out", "get", "how",
    "new", "now", "old", "see", "two", "way", "who", "did", "let",
    "put", "say", "too", "made", "make", "many", "over", "through",
    "before", "between", "each", "other", "which", "there", "these",
    "those", "while", "where", "when", "what", "maintained", "library",
    "framework", "module", "helpers", "helper", "checks", "reads",
    "calls", "files", "file", "text", "python", "replace", "write",
    "writes", "written", "handwritten", "nested",
})

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-\+]*")


def component_to_query(component: dict) -> str:
    """Map a Component to exactly one deterministic GitHub search query."""
    text = f"{component.get('name', '')} {component.get('description', '')}"
    lowered = text.lower()
    for keywords, query in _QUERY_RULES:
        if any(keyword in lowered for keyword in keywords):
            return query
    seen: set[str] = set()
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(lowered):
        if len(token) < 3 or token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) == 5:
            break
    if not tokens:
        return "language:python"
    return " ".join(tokens) + " language:python"


def _to_candidate(item: dict, query: str) -> Candidate:
    full_name = item.get("full_name") or ""
    return Candidate(
        name=full_name.rsplit("/", 1)[-1] if full_name else "",
        full_name=full_name,
        url=item.get("html_url") or item.get("url") or "",
        description=item.get("description") or "",
        stars=item.get("stargazers_count", item.get("stars")),
        query=query,
    )


def find_for_component(component: dict, *, limit: int = 10) -> list[Candidate]:
    """Run ONE GitHub search query for a Component; return its candidates.

    Raises FindError (empty -> no-candidates; rate-limited -> quota_hit;
    other network failures -> source_down).
    """
    name = component.get("name", "")
    query = component_to_query(component)
    try:
        items = github_search.search_repos(query, limit=limit)
    except github_search.RateLimitError as exc:
        detail = f"query={query!r}"
        if exc.retry_after_s is not None:
            detail += f" retry_after_s={exc.retry_after_s:.0f}"
        raise _fail(CODE_QUOTA,
                    f"GitHub search rate-limited for component {name!r}.",
                    component=name, detail=detail) from exc
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError, json.JSONDecodeError) as exc:
        raise _fail(CODE_DOWN,
                    f"GitHub search failed for component {name!r}: "
                    f"{type(exc).__name__}.",
                    component=name, detail=f"query={query!r}") from exc
    if not items:
        raise _fail(CODE_NO_CANDIDATES,
                    f"No candidates found for component {name!r}.",
                    component=name, detail=f"query={query!r}")
    return [_to_candidate(item, query) for item in items]


def find_for_components(
    components: list[dict],
    *,
    limit: int = 10,
    delay_s: float = github_search.POLITENESS_DELAY_S,
) -> tuple[dict[str, list[Candidate]], list[dict]]:
    """Find candidates per Component (ONE query each, spaced delay_s apart).

    Returns (candidates_by_component_name, failures). A failed component
    records its failure and yields no candidates; other components
    continue (downstream-only).
    """
    found: dict[str, list[Candidate]] = {}
    failures: list[dict] = []
    for i, component in enumerate(components):
        if i > 0 and delay_s > 0:
            sleep(delay_s)  # 30 req/min authed search bucket
        try:
            found[component.get("name", "")] = find_for_component(
                component, limit=limit)
        except FindError as exc:
            found[component.get("name", "")] = []
            failures.append(exc.failure)
    return found, failures


def search(problem: str, *, limit: int = 10) -> list[Candidate]:
    """Compat entry: one query for a free-text problem string (unknown kind).

    Raises FindError on the same paths as find_for_component.
    """
    return find_for_component(
        {"name": problem, "description": problem, "kind": "unknown",
         "call_sites": [], "confidence": 0.0},
        limit=limit,
    )
