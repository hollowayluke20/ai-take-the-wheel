"""Find stage: per Component, find candidate wheels via GitHub search.

Contract (tickets 02/05/08 + map bar, broadened by ticket 16):

- Up to THREE search-API queries per component, never per candidate (02
  ban: search is for *finding*). [0] is the deterministic mapping below,
  [1] a synonym/expansion variant, [2] a topic-based query. Candidates
  from all queries are merged, deduped by repo, and ranked by relevance
  = GitHub stars order (the search API's ``sort=stars``).
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
- Every candidate records the query that found it (``Candidate.query``);
  the full query list per component is recoverable from its candidates
  and is recorded verbatim in failure details, so the run record shows
  all queries issued per component.
- No fabricated candidates: empty results from ALL queries raise
  FindError carrying the exact failure record ``find/no-candidates``
  (detail holds every query tried). Rate-limiting raises FindError
  ``find/quota_hit``; other network failures raise FindError
  ``find/source_down``.
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
    # Ticket 16: AI-humaniser components must reach mainstream
    # paraphrase/style libraries. Placed BEFORE the test rule: words
    # like "latest" contain the "test" substring and would otherwise
    # steal these components.
    (("humaniz", "humanis", "paraphras", "ai-generated", "ai detection",
       "style transfer", "bypass detector"),
     "paraphrase language:python"),
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


# Ticket 16: synonym/expansion variant per curated base query ([1]).
_EXPANSIONS: dict[str, str] = {
    "http client language:python":
        "python requests httpx http-client language:python",
    "cli framework language:python":
        "python cli argparse click typer language:python",
    "csv parser language:python":
        "python csv delimited parsing language:python",
    "retry backoff language:python":
        "python retry backoff tenacity language:python",
    "configuration management language:python":
        "python configuration dotenv settings language:python",
    "data validation language:python":
        "python validation pydantic schema language:python",
    "paraphrase language:python":
        "python text augmentation paraphrasing language:python",
    "testing framework language:python":
        "python testing pytest framework language:python",
    "dataframe language:python":
        "python dataframe pandas polars language:python",
    "logging language:python":
        "python logging loguru structlog language:python",
    "progress bar language:python":
        "python progress bar tqdm rich language:python",
}

# Ticket 16: topic-based query per curated base query ([2]).
_TOPICS: dict[str, str] = {
    "http client language:python": "topic:http language:python",
    "cli framework language:python": "topic:cli language:python",
    "csv parser language:python": "topic:csv language:python",
    "retry backoff language:python": "topic:retry language:python",
    "configuration management language:python":
        "topic:configuration language:python",
    "data validation language:python": "topic:validation language:python",
    "paraphrase language:python": "topic:nlp language:python",
    "testing framework language:python": "topic:testing language:python",
    "dataframe language:python": "topic:dataframe language:python",
    "logging language:python": "topic:logging language:python",
    "progress bar language:python": "topic:cli language:python",
}

#: Hard cap on search-API queries per component (ticket 16).
MAX_QUERIES_PER_COMPONENT = 3


def _core_tokens(query: str) -> list[str]:
    return [t for t in query.replace(" language:python", "").split()
            if t != "language:python"]


def component_to_queries(component: dict) -> list[str]:
    """Map a Component to up to 3 deterministic GitHub search queries.

    [0] is ``component_to_query`` (curated rule or fallback), [1] the
    synonym/expansion variant, [2] the topic-based query. Duplicates
    are dropped, order preserved, capped at MAX_QUERIES_PER_COMPONENT.
    Unmapped fallbacks broaden generically (first-3-tokens variant +
    first-token topic); a bare ``language:python`` base stays 1 query.
    """
    base = component_to_query(component)
    queries = [base]
    expansion = _EXPANSIONS.get(base)
    if expansion is None:
        core = _core_tokens(base)
        if len(core) > 3:
            expansion = " ".join(core[:3]) + " language:python"
        elif len(core) > 1:
            expansion = core[0] + " language:python"
    if expansion and expansion not in queries:
        queries.append(expansion)
    topic = _TOPICS.get(base)
    if topic is None:
        core = _core_tokens(base)
        if core:
            topic = f"topic:{core[0]} language:python"
    if topic and topic not in queries:
        queries.append(topic)
    return queries[:MAX_QUERIES_PER_COMPONENT]


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


def _stars_key(candidate: Candidate) -> tuple[bool, int]:
    stars = candidate.get("stars")
    return (isinstance(stars, int), stars if isinstance(stars, int) else 0)


def find_for_component(
    component: dict, *, limit: int = 10,
    delay_s: float = github_search.POLITENESS_DELAY_S,
) -> list[Candidate]:
    """Run up to 3 GitHub search queries for a Component; return candidates.

    Per-query calls stay component-level (never per candidate). Results
    merge across queries, dedupe by repo (``full_name``, highest stars
    win), and order stars-descending (``None`` stars last). Each
    candidate's ``query`` field records the query that found it, so the
    run record shows every query issued per component.

    Raises FindError (empty from ALL queries -> no-candidates, detail
    lists every query tried; rate-limited incl. mid-sequence ->
    quota_hit; other network failures -> source_down).
    """
    name = component.get("name", "")
    queries = component_to_queries(component)
    merged: dict[str, Candidate] = {}
    for qi, query in enumerate(queries):
        if qi > 0 and delay_s > 0:
            sleep(delay_s)  # same 30 req/min authed search bucket
        try:
            items = github_search.search_repos(query, limit=limit)
        except github_search.RateLimitError as exc:
            detail = f"queries={queries[:qi + 1]!r}"
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
                        component=name,
                        detail=f"queries={queries[:qi + 1]!r}") from exc
        for item in items:
            candidate = _to_candidate(item, query)
            key = (candidate["full_name"] or candidate["url"]
                   or candidate["name"] or query)
            prev = merged.get(key)
            if prev is None or _stars_key(candidate) > _stars_key(prev):
                merged[key] = candidate
    if not merged:
        raise _fail(CODE_NO_CANDIDATES,
                    f"No candidates found for component {name!r}.",
                    component=name, detail=f"queries={queries!r}")
    return sorted(merged.values(), key=_stars_key, reverse=True)


def find_for_components(
    components: list[dict],
    *,
    limit: int = 10,
    delay_s: float = github_search.POLITENESS_DELAY_S,
) -> tuple[dict[str, list[Candidate]], list[dict]]:
    """Find candidates per Component (up to 3 queries each, delay_s apart).

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
                component, limit=limit, delay_s=delay_s)
        except FindError as exc:
            found[component.get("name", "")] = []
            failures.append(exc.failure)
    return found, failures


def search(problem: str, *, limit: int = 10) -> list[Candidate]:
    """Compat entry: up to 3 queries for a free-text problem string.

    Raises FindError on the same paths as find_for_component.
    """
    return find_for_component(
        {"name": problem, "description": problem, "kind": "unknown",
         "call_sites": [], "confidence": 0.0},
        limit=limit,
    )
