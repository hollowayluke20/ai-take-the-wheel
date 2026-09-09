"""Understand stage: profile a repo URL or plain-text idea into components.

Component is the common currency (map): repo URLs are read as code,
idea-text is decomposed up front (LLM front end lands downstream), then one
identical pipeline runs per component.
"""

from __future__ import annotations

from typing import TypedDict


class Component(TypedDict):
    """One decomposable unit. kind: addition | substitution | unknown."""

    name: str
    description: str
    kind: str
    call_sites: list[str]
    confidence: float


def classify_input(source: str) -> str:
    """Pure routing: URL with scheme -> repo_url, else idea_text."""
    return "repo_url" if source.startswith(("http://", "https://")) else "idea_text"


def decompose(source: str) -> list[Component]:
    """Decompose any input into a component list. Skeleton stub.

    Quality bar (ticket 05 D7): output matches the recorded human profile
    for the input; doubt -> addition, never substitution. The LLM front
    end lands in the build ticket; until then profile() serves the demo.
    """
    _ = source
    raise NotImplementedError("decompose not implemented (ticket 05 skeleton)")


def profile(source: str) -> list[str]:
    """Stub: return fixture problems regardless of input (real logic TBD)."""
    _ = source
    return ["Hand-rolled CSV parsing in Python", "Custom retry/backoff logic"]
