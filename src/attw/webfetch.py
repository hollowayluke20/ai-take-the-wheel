"""Web fetch + source tagging (no AI).

- fetch_readable(url): GET the page, extract the main readable text with
  trafilatura (strips nav/boilerplate).
- classify_source(url): tag a URL as first_hand / secondary / unknown using
  the editable SOURCE_TIERS domain lists below.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlparse

import trafilatura

# Editable domain lists. Subdomains match (e.g. gist.github.com counts as
# github.com). Extend "secondary" with blog/listicle domains as they appear.
SOURCE_TIERS: dict[str, set[str]] = {
    "first_hand": {
        "github.com",
        "reddit.com",
        "news.ycombinator.com",
        "x.com",
        "twitter.com",
        "stackoverflow.com",
    },
    "secondary": {
        "medium.com",
        "dev.to",
    },
}


def _host(url: str) -> str:
    host = urlparse(url).hostname or ""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def classify_source(url: str) -> str:
    """Return 'first_hand', 'secondary', or 'unknown' for a URL."""
    host = _host(url)
    for tier in ("first_hand", "secondary"):
        for domain in SOURCE_TIERS[tier]:
            if host == domain or host.endswith("." + domain):
                return tier
    return "unknown"


def fetch_readable(url: str) -> dict:
    """Fetch a page and return {url, title, text, fetched_on}."""
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ValueError(f"Could not download: {url!r}")
    text = trafilatura.extract(downloaded, favor_precision=True) or ""
    metadata = trafilatura.extract_metadata(downloaded)
    title = metadata.title if metadata and metadata.title else ""
    return {
        "url": url,
        "title": title,
        "text": text,
        "fetched_on": date.today().isoformat(),
    }
