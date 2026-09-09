"""Failure records: schema for "stage X failed because Y".

Pure schema/helpers, no I/O. The loop's downstream-only rule reads these:
a failed stage records here and stops only what depended on it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# Pipeline stages, in order. Matches src/attw/ module layout (ticket 05).
STAGES = (
    "understand",
    "find",
    "evidence",
    "rank",
    "report",
    "implement",
    "verify",
)

# Canonical codes. Implement trio from 03 Proposal L167-175; evidence
# degradation reasons from 02 Proposal L192-200; skeleton/stall local.
CODES = (
    "failed-install",
    "api-mismatch",
    "regression",
    "no_pat_unauth_capped",
    "quota_hit",
    "source_down",
    "stale_cache",
    "deferred_source",
    "not_applicable",
    "skeleton",
    "stalled",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class FailureRecord:
    """One stage failure. `code` should be a CODES entry; `reason` is prose."""

    stage: str
    code: str
    reason: str
    detail: str = ""
    run_id: str = ""
    component: str = ""
    ts: str = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> FailureRecord:
        """Round-trip constructor; unknown keys raise TypeError."""
        return cls(**{k: data[k] for k in cls._fields() if k in data})

    @classmethod
    def _fields(cls) -> tuple:
        return ("stage", "code", "reason", "detail", "run_id", "component", "ts")


def make_failure(
    stage: str,
    code: str,
    reason: str,
    detail: str = "",
    run_id: str = "",
    component: str = "",
) -> dict:
    """Build a failure-record dict; unknown stage raises ValueError."""
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage!r} (expected one of {STAGES})")
    return FailureRecord(
        stage=stage,
        code=code,
        reason=reason,
        detail=detail,
        run_id=run_id,
        component=component,
    ).to_dict()


def format_one(record: dict) -> str:
    """One-line human rendering: `[stage/code] reason`."""
    return f"[{record['stage']}/{record['code']}] {record['reason']}"
