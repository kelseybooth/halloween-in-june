# Tests

```
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Before you push

```
git config core.hooksPath .githooks
```

One command per clone. It points git at `.githooks/pre-push`, which runs this suite
and refuses the push if it fails — the stand-in for a required status check, which
this repository's plan does not offer. `git push --no-verify` skips it.

Everything runs against a throwaway SQLite file, one per test — no Postgres, no
Discord, no network. CI runs the same command on Python 3.13.

| File | Covers |
| --- | --- |
| `test_cat.py` | Pet counting, the recent-pet window, mood weighting, the relationship meter, `relationship_at_pet` |
| `test_decay.py` | The nightly drift toward neutral, catch-up after an outage, and Pacific day boundaries across DST |
| `test_isolation.py` | Cross-server scoping, and where phase 2b moved that line |
| `test_content.py` | Parsing and validating the content files; every validator, fed the break it exists to catch |
| `test_schema.py` | The content/world-state split, table by table, and migrating a database that predates 2b |
| `test_loader.py` | Loading content, first placement, reload semantics, the orphan abort, `--fresh`, load-on-boot |
| `test_drops.py` | Drop arrival — dated, event and manual — and the text each one resolves to |
| `test_world.py` | The house from the content tables: rooms, exits, `/look`, `/inventory` |
| `test_threads.py` | Thread build, rebuild, the keep-alive sweep and permission reporting, against `fake_discord.py` |
| `test_reach.py` | Resolution: which thing a player meant, and which copy — scope per verb, sources and their yields |
| `test_moving.py` | Taking, dropping, transforming and recording uses, including two players racing for the last copy |
| `test_verbs.py` | `/take`, `/drop` and the four `/use` branches, driven through the handlers |
| `test_look.py` | `/look` in three shapes, the `Also here:` listing rules, truncation, `/inventory` |
| `test_restocking.py` | The restock scheduler: derived times, both placements, catch-up, admin overrides |
| `test_craving.py` | Alexa's two replies, and the daily craving — drawing, judging, and the tally |
| `test_admin_config.py` | `/admin_config`, and the shape of the ten-command list |
| `test_world_changes.py` | The staircase and the jammed drawer, `present_when` gates, and which scope each state has |
| `test_achievements.py` | The ninth content file: parsing, validation, drop resolution, and idempotent awards |
| `test_dispatcher.py` | The dispatcher and the nine hooks, and how an award gets announced |
| `test_triggers.py` | All thirty-five conditions, the 43-hour date window, and the three group queries |
| `test_stats.py` | `/stats`: what it shows, what it withholds, and the overflow case |

## Foreign keys

SQLite ignores foreign keys unless `PRAGMA foreign_keys=ON` is set on every
connection. `database._enforce_sqlite_foreign_keys` sets it, so the fallback
backend refuses the same rows PostgreSQL refuses and the suite means the same
thing in both places. `test_foreign_keys_are_enforced_on_this_backend` asserts
the setting directly, so a regression names its own cause rather than surfacing
as an unrelated failure somewhere else.

## Content versus world state

The split phase 2b introduced, and the one most worth not breaking. Content —
rooms, things, text, defaults, drops, restocks — is global and loaded from the
files; nothing mutates it at runtime, which is what makes a reload safe. World
state is per guild and is the only thing a player can change.

`test_schema.py` asserts it per table in both directions, because a content
table that grew a `guild_id` or a world-state table that lost one would fail
quietly and in opposite ways.

## States, and their two scopes

`stairs_repaired` is server-wide because collective labour earns a collective
reward. `drawer_unjammed` is per player because the discovery *is* the content —
server-wide would mean only the first person ever found it.

Getting either scope backwards would crash nothing and quietly make the game
worse, so `test_world_changes.py` checks the scope as well as the effect: two
players standing in the same Upstairs Hallway, one of whom can see the expired
cat food and one of whom cannot.

## Awarding an achievement exactly once

`Cat's Best Friend` is true forever once true, so a condition checked on every
`/pet` would re-announce for the rest of October. `award_player_achievement`
is one `INSERT ... ON CONFLICT DO NOTHING ... RETURNING` and answers whether
*this call* created the row - a read followed by a write would let two hooks
firing at once both conclude they were first.

`test_achievements.py` asserts it from both ends: the second award returns
`False`, and `earned_at` does not move.

## Which source a take came from

A source and its yield are filed as one thing during resolution, which is the
only reason `/take herbs` does not raise a spurious ambiguity prompt. The cost
is that `thing_id` cannot say where the herbs came from: taking them from the
herb garden and picking up a copy somebody dropped both report `herbs`.

`reach.Found.source_id` names the source, or `None` for a loose copy, and the
`on_take` hook carries it. *Green Thumb* is the only thing in Release 1 that
needs it — gardening counts, scavenging does not — but it is a field on the
hook rather than a special case in one predicate.

`test_reach.py` asserts both halves, and `test_dispatcher.py` drives it
through the real `/take`.

## The 43-hour day

Seven achievements fire on a date, and the date is not a calendar day. The
players run from Japan to Hawaii, nineteen hours apart, so "on 1 October"
means 30 September 08:00 Pacific through 2 October 03:00 Pacific — exactly the
union of "1 October in local time" across UTC+9 to UTC−10.

The failure mode is silent: a window an hour out means somebody at one end of
the world quietly cannot earn theirs, and nothing reports it. So
`test_triggers.py` tests **both edges to the minute**, plus a player in Japan
and one in Hawaii earning it on their own local date, and asserts consecutive
windows overlap by exactly nineteen hours — which is one more reason the
dispatcher must not stop at the first match.

## What `/stats` withholds

Two rules, and both are about what the command does **not** say.

It is **ephemeral, always**, because it carries the unlock descriptions — the
spoilers the public announcement is kept to a name to avoid. And it says
nothing about unearned achievements: no count out of thirty-five, no locked
rows, no progress bars. A secret achievement's existence is revealed by
somebody earning it.

It is an embed rather than a message because a message caps at 2,000
characters. All thirty-five rendered comes to about 2,600 — so a plain
message would have broken at the end of October for exactly the players who
played the most.

## Rooms a player unlocked before phase 2b

Two columns held room *names* before 2b: `current_room` and `rooms_unlocked`.
Only the first was ever migrated. `/use` on an exit compares
`destination_room_id` — an id — against the second, so for anyone who entered
the house before 2b it matched nothing and **every exit refused** with the
house's generic `use_fail`. `/look` at the same exit worked, because looking
does not consult the list, which is what made it read as one broken doorway
rather than a broken player.

A stale list is reset to the rooms open at launch rather than translated entry
by entry: nothing has ever unlocked a room after entry, so there is no
progress to preserve, and a verbatim translation would hand those players the
Secret Library.

`test_schema.py` covers the repair; `test_verbs.py` drives a pre-2b player
through the doorway that was reported broken, and checks the same player is
still kept out of the Secret Library.

## `ALL`, the room nobody stands in

`content.EVERYWHERE` marks a thing present in every room. The validator had
always exempted it from the "is this a real room?" check and nothing else
implemented it, so Alexa — the one thing declared to be everywhere — was
reachable nowhere: `/look alexa`, `/take alexa` and `/use alexa` all answered
"You don't see a alexa here", and her description had never been read by
anybody. She worked only as a message responder, because `on_message` reads
her text directly instead of resolving her as a thing.

`reach` admits `ALL` **as well as** the current room, never instead of it, so
a thing with an ordinary `room_id` is still in one room — `test_reach.py`
asserts that in both directions. She stays out of `Also here:` for free: the
listing holds loose takeable objects, and she is neither.

## Cohorts

Gone as of phase 2a step 4. Two columns survive the removal —
`player_game_state.room_version_assignment` and `things.cohort` — because the
startup migration can only add columns, never drop them. Nothing reads either.

`test_world.py` ends with a short section that backfills both columns the way a
pre-2a database would have them and checks the old values are genuinely inert:
a thing that used to be cohort-B only is visible to everyone, and a rebuild
places players by room alone.
