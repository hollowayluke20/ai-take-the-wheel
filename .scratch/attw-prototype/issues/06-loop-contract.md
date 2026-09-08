# 06 — Loop contract: gauntlet mechanics on this tracker

Status: open
Type: task

## Question

Reconcile the gauntlet-loop skill (`.agents/skills/gauntlet-loop/SKILL.md`)
with this repo's local-markdown tracker so overnight agents have one
unambiguous operating contract. Takeable now, in parallel with research.

## Decisions to make

- Bar location: gauntlet prefers `.wayfinder/` answer-keys; attw ground truth
  lives in `testdata/known_answers/`. Decide: extend the known_answers format
  to carry per-run keys (input, expected wheels, run type, better-spec) so
  there is exactly one bar. Ticket 01's hardening depends on this format.
- RUNLOG location: skill says `.wayfinder/RUNLOG.md`; tracker says
  `.scratch/`. Decide one home (recommend `.scratch/attw-prototype/RUNLOG.md`)
  and the exact line format.
- Critic blindness for generated code: what the critic sees (piece output +
  bar + repo) and must NOT see (builder notes, prior critic rounds?).
- Retry accounting: where the 3-retry count lives, what a retry request
  contains (single biggest gap, per the skill), what "flag for Luke" looks
  like as a file/comment.
- Verifier pass: `pytest` + `ruff check` commands for this repo, bug-sweep
  expectations for pipeline stages (not just library code).
- Claim/resolve mechanics per `docs/agents/issue-tracker.md` restated for
  agents with fresh memory (they will not have tonight's context).

## Done-criteria

Contract written up (recommend: `.scratch/attw-prototype/LOOP.md`, linked
from the map Notes), known_answers extension format specified, RUNLOG created
with header row. Unblocks the build phase, not the research.
