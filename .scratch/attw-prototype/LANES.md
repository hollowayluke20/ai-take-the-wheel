# LANES — parallel build contract (Alex structure, adopted 2026-09-09)

How we build from here. LOOP.md still governs each piece (claim, gate,
builder→critic→verifier, retries); this file governs how pieces run in
parallel and reach main.

## Roles

- **Supervisor**: holds the map + RUNLOG, hands out lanes, tracks state,
  refreshes the weekly mention cache (single writer), watches quotas.
  Writes no code. Kills a stuck lane (silent >20 min or 3 failed critic
  rounds) and respawns it fresh ONCE; if the respawn fails, logs
  NEEDS-LUKE and moves on. Never waits on Luke overnight.
- **Lane (builder)**: one ticket, claimed with its FILE CLAIM (see below).
  Builds per the ticket + LOOP.md. Hands ONLY `verified` pieces onward.
- **Checker (critic + verifier)**: per LOOP.md §§3–4, unchanged. Quality
  gate; a lane reaches the integrator only when the checker is happy.
- **Integrator**: merges `verified` pieces to main ONE AT A TIME via PR
  (`gh`), trickle-merge, never batched. Merge review covers conflicts,
  intent, and main-green — never re-checks quality (checker's job).
  On a gap: sends back to the lane with the single biggest gap, max
  2 retries, then NEEDS-LUKE log. NEVER writes code.

## Concurrency

- Cap: **4 concurrent lanes** (Luke C1). Scale to 8 only when quota
  behavior is understood.
- File claims (Luke C6c): a lane's ticket names the files it may touch;
  the supervisor rejects overlapping claims before launch. Integrator
  merges PRs strictly one at a time as backstop.
- Shared state (Luke C9): one PAT (`.env`, never printed/committed), one
  weekly cache (supervisor refreshes), one RUNLOG/map (supervisor writes).
  Lanes back off on 429s and record quota_hits. No lane-to-lane chatter.
- Live-run serialization (lesson 2026-09-09): lanes' simultaneous live API
  runs throttled the shared quota (429s → degraded evidence → winner drift
  on key 30). Live runs go ONE AT A TIME — lanes coordinate via the
  supervisor, never by guessing. Mocked unit tests stay parallel.
- Behavior-owner test updates: when a lane's specified behavior change
  breaks expectations in unclaimed test files, that lane updates those
  expectations (one-time claim extension, expectations only) — the
  integrator never writes code, so it cannot be the one to do it.

## Luke-blocking policy (Luke C7)

Nothing blocks for Luke. Lanes proceed on recorded assumptions; scope
changes (new ecosystems, publishing, upstream PRs) and secrets are the
only things that wait. NEEDS-LUKE is an async log he reads when he wants,
not a gate.

## First lanes (Luke C8, concurrent)

1. Lane 14 — test-group deps in sandbox (finishes key 30).
2. Lane 15 — minimum-quality floor for additions (demo lesson 1).
3. Lane 16 — broader find queries (demo lesson 3).
4. Lane 17 — smarter idea decomposition (demo lesson 2).
5. Lane 18 — skipped suite keys 27–29/31/33 (queued; launches when a lane frees).
