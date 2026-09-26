# Phase 2a — Clear the decks

Five pieces of work that need no functional spec, no achievement triggers, and none of
the open decisions in the Delivery Plan. Safe to start today, in this order — though
the first is substantially larger than the rest.

Source for all of it is the Code Audit. Repository is `kelseybooth/halloween-in-june`:
four Python files, ~1,800 lines, Railway and PostgreSQL, SQLite fallback locally.

## 1. Write the test suite, then add CI — do this first, and budget for it

**There are no tests in the repository.** The suites quoted in the audit were built
during development as throwaway scripts in a scratch directory, run once, and never
committed — no branch's history adds a test file. This step is therefore not automating
an existing suite. It is writing one.

That makes it the largest item in 2a rather than the smallest, and it is the one
everything else waits on. Step 4 touches nearly every query in the codebase, and the net
has to be up *before* that change, not after it.

Write coverage for:

- pet counts, mood weighting and the nightly decay job
- cross-server isolation — the property most easily broken by a wide refactor
- thread creation, rebuild, and the keep-alive sweep
- room, thing and inventory queries, which are what step 4 rewrites

Skip cohort assignment. Step 4 deletes it, and anything written for it now gets deleted
with it.

Then the workflow:

- GitHub Actions, on push and on pull request
- Python 3.13, install dependencies, run the suite
- Run against the SQLite fallback; do not require Postgres in CI
- Make it a required check for merges to main

**If the full suite is too much to front-load,** the defensible minimum before step 4 is
regression coverage of the queries step 4 rewrites, plus the cross-server isolation
tests. Ship that, begin step 4, backfill the rest alongside it. What is not acceptable is
beginning step 4 with nothing running.

## 2. `SHOW_DEBUG_INFO = False`

One line in `bot.py`. Players are currently shown the raw mood roll and relationship
score on every `/pet`. While in that reply path, check whether anything else
debug-shaped is reaching players.

## 3. Archive the three stale specs

They no longer describe the system and someone will build from them. Move them to an
`archive/` directory or delete them. The live documents are the Story Bible (v2), the
Content Schema, and the Delivery Plan — all in the project doc, none in the repo.

## 4. Remove cohorts

The large one. Everything is keyed on `(user_id, guild_id)` and additionally filtered on
cohort, so this reaches most queries.

To remove:

- `room_version_assignment` and the balancing logic on `/enter-entryway`
- the `cohort` column on `player_game_state`
- the `cohort` column on `things` (merged 22 September, unused by any server)
- the second set of room threads — 18 per server drops to 9
- every query filter on cohort

The number 18 is hard-coded in two places, not one. `/initialize-haunted-house` builds
the threads, and the **thread keep-alive job** un-archives all 18 every 24 hours because
Discord's longest auto-archive is 7 days. Both drop to 9. Miss the second and the rooms
quietly vanish a week after launch.

**Write the migration down before running it.** Three facts from the audit make this
sharper than it looks:

- Migrations are additive and automatic — columns are added by `ALTER` at startup if
  absent. Dropping a column is not additive, so it does not fit the existing mechanism.
- SQLite cannot alter a primary key in place.
- The bot deliberately refuses to start against a database predating multi-server
  scoping rather than guessing. Do not weaken that guard to make a migration easier.

Given all three, **leaving the cohort columns in place, nullable and unread, is the
cheaper and safer path.** Stop writing to them, remove every read, and drop them in a
later cleanup once the new schema has settled. The code change is what matters; the
column is inert.

## 5. Do not touch

- **Multi-server scoping.** Every table keyed by `(user_id, guild_id)`, tested against
  cross-server leakage including the cat, the mood window and the nightly decay. This was
  retrofitted deliberately. Keep all of it.
- **The migration guard** that refuses to start against an old database, and the refusal
  to fall back to SQLite on Railway.
- **The room map and the navigation graph** in `house_utils.py`. These move into content
  files later, under 2b. Leave them alone until the loader exists — changing them now
  means changing them twice.
- **`pet_events`, mood weighting and nightly decay.** Out of scope.

## Migrating existing servers

Decided: **admins re-run `/initialize-haunted-house`.** That command already deletes and
rebuilds every room thread and restores players to the house, so once the cohort code is
gone it rebuilds 9 threads instead of 18 and the old B threads go with the rest.

This is why the cohort values need no migration at all. A player's stored A or B becomes
data nothing reads: no query filters on it, no thread is chosen by it, and the rebuild
does not consult it. Leave the columns nullable and unread rather than dropping them —
dropping is not additive, so it does not fit the startup-`ALTER` mechanism, and SQLite
cannot alter a primary key in place.

Two things to get right in the rebuild. Players mid-game are moved by it, so announce it
before running rather than teleporting people out of a room. And the rebuild must be
idempotent — an admin who runs it twice, or runs it while a previous run failed halfway,
should end with 9 threads, not 9 more.

## What 2a explicitly does not need

The functional spec, the achievement trigger spec, the command list, and every open
decision in the Delivery Plan's decision table. If a task appears to need one of those,
it belongs in 2b or 2c and should be moved there rather than blocked here.

## Definition of done

- A committed test suite covers the queries step 4 rewrites plus cross-server
  isolation; CI runs it on every push and PR and is required to merge
- `/pet` shows no debug output
- The three stale specs are out of the working tree
- No code reads or writes cohort; `/initialize-haunted-house` builds 9 threads; the
  keep-alive job refreshes 9
- The full suite passes, and the bot starts cleanly against both a fresh database and a
  copy of a current production one
