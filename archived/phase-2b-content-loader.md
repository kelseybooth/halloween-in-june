# Phase 2b — The content loader

The keystone. After this, the house is content rather than code: the nine rooms, twenty exits and every thing come out of seven TSV files instead of `house_utils.py` and the `/add-thing` testing tool.

Prerequisites, all met: Phase 2a is complete, the Content Schema is written and proven against real data, and the seven files pass every consistency check.

**Decided: types and counts, not instances.** See "Why types" below. All player data in production is test data, so there is nothing to migrate — `reset_db.py` and a fresh load is the migration.

## The shape

Two kinds of table, and the split is the point.

**Content** — loaded from the files, global, never mutated at runtime. Not keyed by guild: the house is the same house in every server.

| Table | From | Key |
| --- | --- | --- |
| `room_types` | `rooms.tsv` | `room_id` |
| `room_text` | `room_text.tsv` | `room_id, state, since_drop` |
| `thing_types` | `things.tsv` | `thing_id` |
| `thing_text` | `thing_text.tsv` | `thing_id, state, since_drop` |
| `defaults` | `defaults.tsv` | `key` |
| `drops` | `drops.tsv` | `drop_id` |
| `restocks` | `restocks.tsv` | `restock_id` |

**World state** — per guild, mutable, never written by the loader except at first placement.

| Table | Holds |
| --- | --- |
| `player_inventory` | `(guild_id, user_id, thing_id, count)` |
| `room_contents` | `(guild_id, room_id, container_id, thing_id, count)` — finite things, placed at first load and moved by `/take` and `/drop`, plus everything the restock scheduler scatters. `container_id` is empty for a thing loose in the room |
| `player_states` | `(guild_id, user_id, state)` — `has_key`, `passage_open`, `library_found`, `drawer_unjammed` |
| `server_states` | `(guild_id, state)` — `stairs_repaired` |
| `server_config` | `(guild_id, key, value)` — `planks_required` and whatever follows |
| `thing_uses` | `(guild_id, user_id, thing_id, last_used_at, use_count)` |

`player_game_state` stays as it is, minus the cohort column 2a stopped reading: `current_room` and `rooms_unlocked` are still per player.

`thing_uses` is worth one line of justification. It is not only the 48-hour lumber cooldown. The staircase needs "{n} of {total} repairs done", counted by **distinct players**, and that is the same table read a different way. Any later "how many times has anyone" achievement is too. One table, three jobs.

## Why types

The entire finite world is **6 physical copies across 6 things** — the silver spoon, the candle stub, the gourmet can, the reading glasses, the cat collar and the music box. Against that, **16 sources feed 14 objects with no cap**: cat food, herbs, candy, copper wire, carving tools, costumes, graphite, chocolate, chips, burritos and the skeleton key. Add the three restocked things, which start at zero and accumulate indefinitely. Under instances every `/take` from a stash is an `INSERT` that never stops, while the part of the world that is genuinely fixed is six rows.

`lumber` is the one deliberate oddity: it keeps `quantity = many` because it is a shared pool of repair charges rather than a source, and it yields nothing.

Nothing in Release 1 needs per-copy identity. The bottle transform is one used becoming one sanitized. "Only one copy exists" is an invariant checked at take time. The `removed_on_take` flag the old schema was built around is doing work that `quantity` now does.

If a later release needs a labeled copy — a letter with a player's name on it, or *Return to Sender* tracking specific sends — that is an event log, not object identity. Add a `sends` table then. Do not make every can a row now to buy it.

## The load path

1. **Parse** all seven files.
2. **Validate before writing anything.** The load is all-or-nothing; a half-loaded house is worse than a stale one.
3. **Upsert content tables** in one transaction.
4. **Place finite things** per guild into `room_contents`, first load only.

Validation must cover, at minimum:

- every `yields` and `transforms_to` target exists
- every `contained_in` host exists, sits in the same room, and is not itself contained (one level only)
- no two things in the same room share an alias
- every thing has at least a `default` text row, and every text row has a thing
- every exit's `destination_room_id` is a real room
- every `present_when` names a state something can actually set
- **every source is named in the prose that reveals it — its container's `look` or `use`, or its room's `look`.** For a source with `contained_in`, its container's `look` or `use` for the same state; for a free-standing source, its room's `look` for the same state. Match on the source's `name`, any of its `aliases`, or the `name` of the thing it `yields`. This one is load-bearing rather than cosmetic — no listing anywhere shows a source, so if the prose does not name it, the content is unreachable
- every `restocks.tsv` row names a real `thing_id`; `amount`, `times_per_day` and `every_n_days` are positive; `window_start` is before `window_end`; and `placement` is `container` or `random` — a `container` row names a real container, a `random` row leaves that cell empty

These are the checks the content files are already passing, so they should pass on day one. Their value is on the *next* load, when a writer has edited a file.

## Reload semantics

This is the part to get right, because it is the part that will run against a live server with players mid-game.

**Content tables reload wholesale.** They are not mutable at runtime, so replacing them is safe.

**`room_contents` is not reset.** If somebody took the nacho chips, a reload must not put them back on the counter. New `thing_id`s are placed; ones already known to the guild are left exactly as they are.

**A `thing_id` that disappears from the files while players hold it aborts the load**, naming the ids and the holders. Loud beats silent — the alternative is inventories referencing things that no longer exist and a `/inventory` that renders blanks. Provide `--allow-orphans` for when it is deliberate.

**`--fresh` wipes world state and re-places everything.** This is the testing path and the migration path, since production holds only test data.

## Also in 2b

**The room map moves out of `house_utils.py`.** The nine rooms come from `rooms.tsv`, the twenty exits from the `type = exit` rows in `things.tsv`, with `destination_room_id` as the graph. `house_utils` keeps thread creation and membership — that is Discord plumbing, not content.

**Respect `open_at_launch`.** The Secret Library is `no`. It should not appear in `rooms_unlocked` for a new player.

**Drop resolution.** Load `drops.tsv` as a sixth content table, with columns `drop_id`, `trigger`, `date`, `event`, `name`, `notes`. Text resolves by `(entity, state, since_drop)`: among the rows whose drop has **arrived**, the highest `since_drop` wins, matching the state, falling back to `default`.

**A drop arrives three ways.** `trigger = date` when its date is at or before today, Pacific — the same moment on every server, nothing stored. `trigger = event` when a named condition first becomes true on that server. `trigger = manual` only when an admin fires it. Event and manual arrivals are **recorded** in a per-guild `server_drops` table the first time they fire and read back from there, never re-evaluated — a condition can stop being true, and content must not vanish from a house it has already changed. Validate `event` against a registry in code and refuse to start on an unknown name, exactly as for `present_when`. Release 1 ships zero event drops; the columns exist so the second one needs no migration.

Note the vocabulary, because the two words are not interchangeable. A **release** is a deployment; a **drop** is a moment content becomes visible to players. One release can carry a month of drops. The runtime only ever sees drops: store no release number, and build no admin command to advance one.

Every row is drop `1` (`launch`) today, so the mechanism is untested by the data — write a test that fakes a second drop with a future date and one with a past date, rather than trusting it.

**Restocks: the data in 2b, the scheduler in 2c.** Load `restocks.tsv` as a seventh content table, validate it, and create the per-guild `server_restocks` table that will record, per restock row, the last occurrence applied and the random time drawn for the next one. Add a `container_id` column to `room_contents` in the same migration — without it there is nowhere to record a jar that landed in the Amazon box or a bottle that landed in the sofa. 2b builds all of that and leaves `server_restocks` empty. It does not run the scheduler: a timed job that mutates `room_contents` is runtime behavior, and nothing it places can be seen until containers and `Also here:` exist.

### The scheduler, which lands in 2c

These rules are settled and do not change with the phase. They sit in this work order because they belong beside the file that carries them, and because the `room_contents` shape above only makes sense once you have read them.

**Day numbers count from that server's own initialization date in Pacific time**, not from a global calendar — the opposite of drops, and see the Functional Spec. Stock is incremented, never assigned, and a window missed while the bot was down is applied at the next opportunity rather than skipped.

**Two placements.** `placement = container` puts `amount` things into the named container. `placement = random` puts them into a uniformly chosen slot from all nine rooms and all twelve containers — 21 slots at equal probability, re-rolled for every occurrence.

**`times_per_day` is not `amount`.** Eight bottles a day means eight separate occurrences of one bottle each, at eight independently drawn times, not one drop of eight.

**`config_key`, where set, names a `server_config` key.** `bottles_per_day` starts at 8 and an admin can change it mid-game; a change applies from the next day and never retroactively adds or removes things already placed.

Three rows exist today: four spice jars into the Amazon box every third day from day 2, eight used baby bottles a day scattered, and two dirty diapers a day scattered. When 2c builds the job, test the container path and the random path separately, test a faked one-day cycle, and test the catch-up path by moving the server's initialization date backwards.

**Volume is the thing this will teach you.** Ten scattered objects a day accumulate, because nothing removes them until a player takes one. Expect the `Also here:` line in a busy room to reach Discord's 2,000-character cap within the first fortnight, so the truncate-with-a-count behavior has to ship in 2c alongside the scheduler rather than after it.

### Two columns for achievements, and one of them has a deadline

Add **`relationship_at_pet`** (integer, not null) to `pet_events`, written on every insert with the relationship score as it stood *before* that pet applied. *Making Friends* and *Trying to Make Friends* count 200 pets while the relationship was positive or negative, and `pet_events` does not record that today. **This has to land before a real server starts petting** — the history cannot be reconstructed afterwards. Right now backfill is free, because all player data is test data. That is why it belongs here rather than with the rest of the achievements in 2d.

Add **`use_count`** to `thing_uses`, alongside `last_used_at`, keyed `(guild_id, user_id, thing_id)` and incremented on every successful use. *Not-So-Picky Eater* is ten frozen burritos, and the table currently only answers the cooldown question. One table then does three jobs, and any later "do this N times" achievement is free.

Neither achievement is built in 2b. The columns are, so that 2d has something to read.

**Build `server_config`, but do not add `/admin_config` yet.** Registering a command costs an hour of propagation, and 2c changes the command list anyway. Build the table and read from it with a default; add the command with the rest of the command changes.

## What 2b does not do

No new command behavior. `/look` and `/inventory` must keep working, which means pointing them at the new tables, but the resolution ladder, `Also here:`, sources, containers and transforms are all 2c and wait for the functional spec.

No timed jobs either. The restock scheduler is 2c for the same reason: it changes the world on a clock, it needs `container_id` and container display, and it has nothing to show until `Also here:` exists.

Do not remove `/add-thing` and `/add-room-desc` yet. They are obsolete the moment the loader works, but removing them is a command-list change — batch it with 2c.

## Definition of done

- The seven TSVs load into content tables from a single command, in one transaction, with validation that refuses a bad file rather than half-loading it
- A second load with no file changes is a no-op against world state
- A load with a new thing places it; a load with a removed thing that players hold aborts and names them
- `house_utils.py` no longer holds the room list or the navigation graph
- The Secret Library is locked for a new player
- `/look` and `/inventory` behave exactly as they did before, reading from the new tables
- `room_contents` has a `container_id` column, `restocks.tsv` loads and validates, and `server_restocks` exists and stays empty — no timed job runs in 2b
- Tests cover the validation failures, the reload no-op, the orphan abort, and drop resolution against faked past-dated and future-dated drop rows
- The bot starts cleanly against a fresh database and against a `--fresh` reload
