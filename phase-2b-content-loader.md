# Phase 2b — The content loader

The keystone. After this, the house is content rather than code: the nine rooms, twenty
exits and every thing come out of five TSV files instead of `house_utils.py` and the
`/add-thing` testing tool.

Prerequisites, all met: Phase 2a is complete, the Content Schema is written and proven
against real data, and the five files pass every consistency check.

**Decided: types and counts, not instances.** See "Why types" below. All player data in
production is test data, so there is nothing to migrate — `reset_db.py` and a fresh load
is the migration.

## The shape

Two kinds of table, and the split is the point.

**Content** — loaded from the files, global, never mutated at runtime. Not keyed by
guild: the house is the same house in every server.

| Table | From | Key |
| --- | --- | --- |
| `room_types` | `rooms.tsv` | `room_id` |
| `room_text` | `room_text.tsv` | `room_id, state, since_release` |
| `thing_types` | `things.tsv` | `thing_id` |
| `thing_text` | `thing_text.tsv` | `thing_id, state, since_release` |
| `defaults` | `defaults.tsv` | `key` |

**World state** — per guild, mutable, never written by the loader except at first
placement.

| Table | Holds |
| --- | --- |
| `player_inventory` | `(guild_id, user_id, thing_id, count)` |
| `room_contents` | `(guild_id, room_id, thing_id, count)` — finite things, placed at first load and moved by `/take` and `/drop` |
| `player_states` | `(guild_id, user_id, state)` — `has_key`, `passage_open`, `library_found`, `drawer_unjammed` |
| `server_states` | `(guild_id, state)` — `stairs_repaired` |
| `server_config` | `(guild_id, key, value)` — `planks_required` and whatever follows |
| `thing_uses` | `(guild_id, user_id, thing_id, used_at)` |

`player_game_state` stays as it is, minus the cohort column 2a stopped reading:
`current_room` and `rooms_unlocked` are still per player.

`thing_uses` is worth one line of justification. It is not only the 48-hour lumber
cooldown. The staircase needs "{n} of {total} repairs done", counted by **distinct
players**, and that is the same table read a different way. Any later "how many times
has anyone" achievement is too. One table, three jobs.

## Why types

The entire finite world is **15 physical copies across 11 things** — the skeleton key,
the spice jar, five baby bottles, and so on. Against that, **10 sources feed 11 objects
with no cap**: cat food, herbs, candy, copper wire, carving tools, costumes. Under
instances every `/take` from a stash is an `INSERT` that never stops, while the part of
the world that is genuinely fixed is tiny.

Nothing in Release 1 needs per-copy identity. The bottle transform is one used becoming
one sanitized. "Only one copy exists" is an invariant checked at take time. The
`removed_on_take` flag the old schema was built around is doing work that `quantity`
now does.

If a later release needs a labelled copy — a letter with a player's name on it, or
*Return to Sender* tracking specific sends — that is an event log, not object identity.
Add a `sends` table then. Do not make every can a row now to buy it.

## The load path

1. **Parse** all five files.
2. **Validate before writing anything.** The load is all-or-nothing; a half-loaded house
   is worse than a stale one.
3. **Upsert content tables** in one transaction.
4. **Place finite things** per guild into `room_contents`, first load only.

Validation must cover, at minimum:

- every `yields` and `transforms_to` target exists
- every `contained_in` host exists, sits in the same room, and is not itself contained
  (one level only)
- no two things in the same room share an alias
- every thing has at least a `default` text row, and every text row has a thing
- every exit's `destination_room_id` is a real room
- every `present_when` names a state something can actually set

These are the checks the content files are already passing, so they should pass on day
one. Their value is on the *next* load, when a writer has edited a file.

## Reload semantics

This is the part to get right, because it is the part that will run against a live
server with players mid-game.

**Content tables reload wholesale.** They are not mutable at runtime, so replacing them
is safe.

**`room_contents` is not reset.** If somebody took the nacho chips, a reload must not put
them back on the counter. New `thing_id`s are placed; ones already known to the guild are
left exactly as they are.

**A `thing_id` that disappears from the files while players hold it aborts the load**,
naming the ids and the holders. Loud beats silent — the alternative is inventories
referencing things that no longer exist and a `/inventory` that renders blanks. Provide
`--allow-orphans` for when it is deliberate.

**`--fresh` wipes world state and re-places everything.** This is the testing path and
the migration path, since production holds only test data.

## Also in 2b

**The room map moves out of `house_utils.py`.** The nine rooms come from `rooms.tsv`, the
twenty exits from the `type = exit` rows in `things.tsv`, with `destination_room_id` as
the graph. `house_utils` keeps thread creation and membership — that is Discord
plumbing, not content.

**Respect `open_at_launch`.** The Secret Library is `no`. It should not appear in
`rooms_unlocked` for a new player.

**Release resolution.** Text resolves by `(entity, state, since_release)`: the highest
`since_release` at or below the server's current release, matching the state, falling
back to `default`. Every row is release 1 today, so this is untested by the data —
write a test that fakes a release 2 row rather than trusting it.

**Build `server_config`, but do not add `/admin_config` yet.** Registering a command
costs an hour of propagation, and 2c changes the command list anyway. Build the table and
read from it with a default; add the command with the rest of the command changes.

## What 2b does not do

No new command behaviour. `/look` and `/inventory` must keep working, which means
pointing them at the new tables, but the resolution ladder, `Also here:`, sources,
containers and transforms are all 2c and wait for the functional spec.

Do not remove `/add-thing` and `/add-room-desc` yet. They are obsolete the moment the
loader works, but removing them is a command-list change — batch it with 2c.

## Definition of done

- The five TSVs load into content tables from a single command, in one transaction,
  with validation that refuses a bad file rather than half-loading it
- A second load with no file changes is a no-op against world state
- A load with a new thing places it; a load with a removed thing that players hold
  aborts and names them
- `house_utils.py` no longer holds the room list or the navigation graph
- The Secret Library is locked for a new player
- `/look` and `/inventory` behave exactly as they did before, reading from the new tables
- Tests cover the validation failures, the reload no-op, the orphan abort, and release
  resolution against a faked release 2 row
- The bot starts cleanly against a fresh database and against a `--fresh` reload
