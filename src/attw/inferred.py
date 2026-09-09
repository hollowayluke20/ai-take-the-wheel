"""Inferred answers: draft "tell me about a time..." answers from stored STAR stories.

New module only. It never edits the profile store, the session module, or
session 1 files -- it reads a STAR bank passed in by the caller and returns
either a draft drawn strictly from ONE story, or a decline.

Rules (the bar):
- Output is a draft PLUS the name of the story used.
- If no story fits: ``"no fitting story -- ask the student"`` and stop.
- Never invent a story, never merge two stories into one fake event.
- Bar 2 (teamwork bank, conflict question): decline rather than invent.
  The draft prefix says "Drawn from '...'" so any use is openly attributed.
- Bar 4: the draft is assembled ONLY from substrings of the chosen story
  plus fixed generic glue (no proper nouns, grades, companies, or dates of
  its own), so by construction it adds zero facts outside the bank.

PII: this module never logs or prints story values. No ``logging``,
no ``print`` anywhere below.
"""

from __future__ import annotations

import re

DECLINE_MESSAGE = "no fitting story -- ask the student"

# Fixed generic glue only: no entities, no dates, no grades, no companies.
DRAWN_FROM_PREFIX = "Drawn from"

# Theme -> keywords signalling it. Question and stories are classified with
# the same table so matching is deterministic and auditable.
THEMES: dict[str, tuple[str, ...]] = {
    "conflict": (
        "conflict", "disagreement", "disagreed", "dispute", "argument",
        "clash", "tension", "difficult person", "difficult colleague",
        "resolve", "resolved", "mediat",
    ),
    "teamwork": (
        "teamwork", "team", "together", "collaborat", "cooperat",
        "helped each other", "joint",
    ),
    "leadership": (
        "lead", "led", "in charge", "delegat", "mentor", "supervis",
    ),
    "failure": (
        "fail", "mistake", "wrong", "error", "went badly", "setback",
    ),
    "pressure": (
        "pressure", "deadline", "stress", "urgent", "time-critical",
        "under time",
    ),
    "initiative": (
        "initiative", "volunteer", "proactive", "went beyond", "extra mile",
        "suggested",
    ),
}

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _field(story: dict, *keys: str) -> str:
    for key in keys:
        value = story.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _story_name(story: dict, index: int) -> str:
    for key in ("name", "id", "title"):
        value = story.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"story-{index + 1}"


def _story_tags(story: dict) -> set[str]:
    tags: set[str] = set()
    for key in ("tags", "themes", "competencies"):
        value = story.get(key)
        if isinstance(value, str):
            tags.update(_tokens(value))
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str):
                    tags.update(_tokens(item))
    return tags


def _story_text(story: dict) -> str:
    parts = [
        _field(story, "situation"),
        _field(story, "task"),
        _field(story, "action"),
        _field(story, "result"),
        _field(story, "text", "details", "body", "narrative"),
    ]
    return " ".join(part for part in parts if part)


def _question_themes(question: str) -> set[str]:
    lowered = question.lower()
    return {
        theme for theme, keywords in THEMES.items()
        if any(keyword in lowered for keyword in keywords)
    }


def _story_theme_hits(story: dict, text_lower: str, tags: set[str]) -> set[str]:
    hits: set[str] = set()
    for theme, keywords in THEMES.items():
        if theme in tags:
            hits.add(theme)
            continue
        if any(keyword in text_lower for keyword in keywords):
            hits.add(theme)
    return hits


def _word_overlap(question_words: set[str], story_words: set[str]) -> int:
    stop = {
        "a", "an", "the", "me", "you", "tell", "about", "time", "give",
        "describe", "when", "where", "what", "how", "did", "do", "have",
        "has", "had", "was", "were", "are", "is", "and", "or", "of",
    }
    return len((question_words - stop) & (story_words - stop))


def _coerce_bank(bank) -> list[dict]:
    if bank is None:
        return []
    if isinstance(bank, dict):
        for key in ("stories", "star_bank", "bank"):
            nested = bank.get(key)
            if isinstance(nested, list):
                return [s for s in nested if isinstance(s, dict)]
        return []
    if isinstance(bank, (list, tuple)):
        return [s for s in bank if isinstance(s, dict)]
    list_stories = getattr(bank, "stories", None)
    if isinstance(list_stories, list):
        return [s for s in list_stories if isinstance(s, dict)]
    for method in ("list_stories", "all_stories"):
        getter = getattr(bank, method, None)
        if callable(getter):
            try:
                result = getter()
            except TypeError:
                continue
            if isinstance(result, list):
                return [s for s in result if isinstance(s, dict)]
    return []


def _decline() -> dict:
    return {
        "status": "needs_student",
        "story_name": None,
        "draft": None,
        "message": DECLINE_MESSAGE,
    }


def _draft_for(name: str, story: dict) -> str:
    """Assemble the draft ONLY from the chosen story's own substrings."""
    ordered = [
        _field(story, "situation"),
        _field(story, "task"),
        _field(story, "action"),
        _field(story, "result"),
    ]
    body = " ".join(part for part in ordered if part)
    if not body:
        body = _field(story, "text", "details", "body", "narrative")
    return f"{DRAWN_FROM_PREFIX} '{name}': {body}"


def answer_question(bank, question: str) -> dict:
    """Draft an answer to `question` from one stored STAR story.

    Returns ``{"status", "story_name", "draft", "message"}``. On a fit,
    ``status`` is ``"answered"`` with the story name and a draft built
    solely from that story's facts. Otherwise ``status`` is
    ``"needs_student"``, ``draft`` is None, and ``message`` is
    ``DECLINE_MESSAGE``. Never invents, never merges: at most one story
    contributes text to any draft.
    """
    stories = _coerce_bank(bank)
    if not stories or not isinstance(question, str) or not question.strip():
        return _decline()

    question_themes = _question_themes(question)
    question_words = set(_tokens(question))

    scored: list[tuple[int, int, dict, str, str]] = []
    for index, story in enumerate(stories):
        name = _story_name(story, index)
        text = _story_text(story)
        if not text.strip():
            continue
        lowered = text.lower()
        tags = _story_tags(story)
        theme_hits = _story_theme_hits(story, lowered, tags)
        if question_themes:
            theme_score = len(question_themes & theme_hits)
        else:
            theme_score = 0
        overlap = _word_overlap(question_words, set(_tokens(text)))
        scored.append((theme_score, overlap, story, name, text))

    if not scored:
        return _decline()

    if question_themes:
        # A themed question needs a themed story: best theme overlap wins,
        # and zero overlap means decline (bar 2) -- never relabel teamwork
        # as conflict.
        scored.sort(key=lambda row: (-row[0], -row[1], row[3]))
        best_score, _, best_story, best_name, _ = scored[0]
        if best_score <= 0:
            return _decline()
    else:
        scored.sort(key=lambda row: (-row[1], row[3]))
        _, best_overlap, best_story, best_name, _ = scored[0]
        if best_overlap <= 0:
            return _decline()

    return {
        "status": "answered",
        "story_name": best_name,
        "draft": _draft_for(best_name, best_story),
        "message": "",
    }


def draft_answer(bank, question: str) -> dict:
    """Back-compat alias for :func:`answer_question`."""
    return answer_question(bank, question)
