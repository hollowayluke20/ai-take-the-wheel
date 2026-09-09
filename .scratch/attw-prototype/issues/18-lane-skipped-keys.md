# 18 — Lane: skipped suite keys 27–29/31/33 (QUEUED)

Status: claimed
Type: task
Lane: queued — launches when one of lanes 14–17 frees (cap 4). File claim:
none (runs only; may append run records to `database/`).

## Question

Run the skipped keys end-to-end and record verdicts: 27 (typer win), 28
(tenacity win), 29 (pydantic-settings win), 31 (pytest addition), 33
(httpx-vs-aiohttp hard).

## Spec

`attw analyze` per key, sandbox temp, PAT from `.env`, stall rule honored,
failures recorded with reasons. No code changes in this lane — if a run
exposes a code defect, record it as a follow-up ticket candidate and move
on (do not fix another lane's files). Priority: 28, 29 (likely wins), then
27, 31, 33.

## Done-criteria

All five runs recorded with verdict-vs-expected + notes; defect candidates
(if any) filed as sketched follow-ups; no code touched. Checker = supervisor
review of the run table (no critic needed for runs). Then done — nothing to
merge.
