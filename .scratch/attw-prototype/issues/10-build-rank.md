# 10 — Build: rank stage

Status: claimed
Type: task
Blocked by: 09

## Question

Implement the ranker: score candidates with ticket 02's exact combination
rule and order them, expected winner #1 on every win run.

## Spec

Score = 10·P0 + 3·P1 + 1·P2 on log10-relative norms with log-damp downloads;
CVE −2.0 high/crit, −0.5 medium, capped −4, never veto; license prose-only
(no numeric effect); per-component-relative norms; confidence display-only
per ticket 05. Bar: on keys 26–31 the expected winner ranks #1; on hard runs
32–33 the winner is argued with dissent recorded (ranker outputs scores +
score breakdown the report renders); on keep-yours 34–35 the ranker must
decline (verdict keep, no winner). Pure logic, no I/O. Tests: hand-computed
fixture score tables incl. CVE-cap, keep-yours decline, tie behavior.

## Done-criteria

`rank.py` fully implemented; unit tests with fixture tables; gate green;
blind critic + verifier per LOOP.md.
