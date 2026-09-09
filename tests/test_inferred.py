"""Inferred-engine tests: the 4 bar lines + no-merge + PII sweep."""

import logging
import re

from attw import inferred

CONFLICT_STORY = {
    "name": "rota-clash",
    "tags": ["conflict"],
    "situation": "Two volunteers both wanted the Saturday rota slot.",
    "task": "My task was to agree cover without cancelling the session.",
    "action": "I listened to each person and proposed a split shift.",
    "result": "We covered the session with no cancellation.",
}

TEAMWORK_STORY = {
    "name": "foodbank-shift",
    "tags": ["teamwork"],
    "situation": "Our foodbank shift was short-staffed before opening.",
    "task": "My task was to keep the packing line moving.",
    "action": "I paired up with a new volunteer and shared the packing steps.",
    "result": "We opened on time and cleared the queue.",
}

ENTITY = re.compile(r"\b[A-Z][a-z]+\b|\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d+\b")


def _bank_text(bank):
    return " ".join(
        " ".join(
            str(story.get(key, ""))
            for key in ("situation", "task", "action", "result", "text")
        )
        for story in bank
    )


def test_conflict_story_used_and_named():
    result = inferred.answer_question(
        [CONFLICT_STORY, TEAMWORK_STORY], "give me a time you solved a conflict"
    )
    assert result["status"] == "answered"
    assert result["story_name"] == "rota-clash"
    assert "rota-clash" in result["draft"]
    bank_text = _bank_text([CONFLICT_STORY])
    for sentence in (
        CONFLICT_STORY["situation"],
        CONFLICT_STORY["task"],
        CONFLICT_STORY["action"],
        CONFLICT_STORY["result"],
    ):
        assert sentence in result["draft"]
    # Draft adds no entities beyond the bank (bar 4).
    draft_body = result["draft"].split(":", 1)[1]
    for entity in set(ENTITY.findall(draft_body)):
        assert entity in bank_text or entity in ("We", "My", "I")


def test_teamwork_only_bank_declines_conflict_question():
    result = inferred.answer_question(
        [TEAMWORK_STORY], "give me a time you solved a conflict"
    )
    assert result["status"] == "needs_student"
    assert result["draft"] is None
    assert result["message"] == inferred.DECLINE_MESSAGE
    # Must not invent a conflict: the word never appears from nowhere.
    assert "conflict" not in (result["draft"] or "")


def test_empty_bank_asks_student_and_writes_nothing():
    for empty in ([], None, {}):
        result = inferred.answer_question(empty, "tell me about a time you led")
        assert result["status"] == "needs_student"
        assert result["story_name"] is None
        assert result["draft"] is None
        assert result["message"] == "no fitting story -- ask the student"


def test_never_merges_two_stories():
    other = dict(
        TEAMWORK_STORY, name="garden-team",
        situation="Our garden group faced weeds before the fair.",
    )
    result = inferred.answer_question(
        [CONFLICT_STORY, other], "give me a time you solved a conflict"
    )
    assert result["story_name"] == "rota-clash"
    assert "weeds" not in result["draft"]
    assert "fair" not in result["draft"]


def test_no_story_values_in_logs(caplog):
    handler = logging.getLogger("attw.inferred")
    unique = "Saturday rota slot"
    with caplog.at_level(logging.DEBUG, logger="attw.inferred"):
        inferred.answer_question([CONFLICT_STORY], "tell me about a conflict")
    assert unique not in caplog.text
    assert handler is not None  # module exists; it just never logs values
