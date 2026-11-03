# Rattle achievements decision note

Nov 2, 2026. Answers the four achievements proposed in *Rattle
achievements work order*.

**We are building Accompanist and Captive Audience.** Noise Complaint
and Back Where It Belongs are not being built. Opening Act is renamed
Captive Audience, `achievement_id` included, and is no longer a
fallback — it is one of the two.

Nothing here is implemented yet. The work order's content fixes are
landing separately; see **Where the content already got to** below for
what is already true on `main` at `ac02e78`.

---

## The two we are building

### Captive Audience

| Field | Value |
| --- | --- |
| `achievement_id` | `captive_audience` |
| `kind` | secret |
| `name` | Captive Audience |
| `unlock` | Gave a rattle performance to a live audience. Reviews are mixed. |
| `since_drop` | 30 |
| `sort_order` | 155 |

**Trigger:** a `/use rattle` while at least `captive_audience_size`
other active players are in the same room. Active means their current
room is that room and they have run a command in the last 10 minutes.
Config `captive_audience_size`, default 3 — renamed from the work
order's `opening_act_audience` with the achievement, because
`captive_audience_audience` is not a key anybody should have to type.

**Three is the beta number, decided 2 November.** It is a config value
so a quiet server can lower it, but the shipped default is not a
placeholder waiting on play data.

**Nothing new is needed to build it.** `achievements.Context` already
carries `room_id` and `on_use` already fills it from
`state.current_room`, so the predicate reads the room it is given.
"Other players in this room" is `player_game_state.current_room`, and
"ran a command in the last 10 minutes" is an `interaction_log` row for
that player inside the window — which the existing
`(guild_id, user_id, action, created_at)` index covers. No schema
change, no new table, no backfill.

Drop 30 is reachable: `LAST_PLAYABLE_DROP` is 40.

### Accompanist

| Field | Value |
| --- | --- |
| `achievement_id` | `accompanist` |
| `kind` | secret |
| `name` | Accompanist |
| `unlock` | Kept time on the rattle while the music box played. |
| `since_drop` | 40 |
| `sort_order` | 145 |

**Trigger:** a `/use rattle` within 60 seconds of a different player's
successful `/use music box` in the same room.

**The release it was waiting for has happened.** This paragraph said
Accompanist waits on drop 40 because the music box is an `object` in
`NU` and the Nursery arrives with Upstairs, and that the ceiling was 31
and would move in the release that built the next drop. It moved on
2 November: `LAST_PLAYABLE_DROP` is 40, raised so beta can reach the
upstairs. The Nursery is reachable, so the drop is no longer what holds
this back - the missing column below is the only thing left.

**It also needs one column that does not exist.** "In the same room"
has no source today:

| Table | Has the room? | Has the recency? |
| --- | --- | --- |
| `interaction_log` | no | yes (`created_at`) |
| `thing_uses` | no | yes (`last_used_at`, updated every use) |
| `room_deeds` | yes (`room_id`) | no — `first_at` is written once and never updated |

`room_deeds` looks like the answer and is not: it is a deed ledger for
the trails, deliberately idempotent, so a player who played the music
box in the Nursery last week has a `first_at` of last week however many
times they play it tonight.

**Add `last_used_room` to `thing_uses`**, nullable, not part of the key,
written on each use. The predicate is then exact: another player's
`music_box` row with `last_used_at` inside 60 seconds and
`last_used_room` equal to `context.room_id`. Keeping it out of the key
is the point — `use_count` and the staircase's distinct-player count
both depend on one row per (player, thing), and a room in the key would
quietly split them.

The alternative is to read the other player's `current_room` and hope
they have not moved in the last minute. That was nearly safe when the
rattle was nailed to the Courtyard. Both the rattle and the music box
are portable now, so two players who just played together are exactly
the two most likely to be walking somewhere.

---

## Why not Noise Complaint

It is the one we wanted most and it is the most expensive of the four,
for reasons that are not visible from the work order.

**Its stated premise is wrong.** The work order says `interaction_log`
"already records most of these events with a room". It records no room
at all: `guild_id`, `user_id`, `actor`, `action`, `thing_id`, `outcome`,
`reason`, `relationship_delta`, `score_after`, `drop`, `detail`,
`created_at`. So the cheap path described does not exist, and a column
and a migration would be the start rather than the whole of it.

**The log records events, not public lines.** The threshold is written
in terms of what the room sees, and the log holds a great deal the room
never sees: refusals are private, `look` is private, and today every
`use` is private. Counting public lines from it means a hand-kept map of
which `(action, outcome)` pairs post publicly, copied out of `bot.py` —
the same duplication the bolding work was undertaken to delete, where
two copies of one rule drifted twice in an afternoon.

**One move is two public lines in two rooms.** A departure is seen where
the player left and an arrival where they arrived. A single `room_id`
column records one of them, so one of the two goes uncounted in the room
that watched it.

**Achievement announcements are public lines by the spec and are not log
rows at all.**

If we want it later, the version to build is a different question:
**count other players' recorded actions in the room**, not public lines.
That keeps the feel — eight things happened around you in five minutes —
and drops the copied mapping and the announcement gap outright. It still
needs the room on the log, which is worth doing on its own merits and
not as a tax on one achievement.

Captive Audience is the reason this is a deferral rather than a loss.
Both achievements say the same thing to a player — you played the rattle
and other people were there — and one of them needs nothing built.

## Why not Back Where It Belongs

No objection to it; it is simply the least interesting of the four and
it is downstream of the same release as Accompanist. One room check on a
hook that already has the room, waiting on the Nursery. If Upstairs
ships and somebody wants a third rattle achievement, this is the cheap
one to add.

---

## Where the content already got to

True on `main` at `ac02e78`, and most of it was not true when the work
order was written:

- **The rattle is takeable.** It is an `object` in `CO` with
  `takeable = yes`. The work order never asked for this and all four of
  its achievements needed it — Back Where It Belongs, Accompanist and
  the idle drop cannot be described without it.
- **`look` no longer mentions the grass**, which the work order's table
  marked *[keep]* while its own acceptance test asked for the change.
- **`use` is the third-person public line**, `"Rattle rattle!" {player}
  is having some fun.` The work order's table said this was already
  there and should be kept; what was there was "You give it a shake. The
  sound is far too cheerful for an empty garden."

## One thing the content left behind

- **The rattle still has a `take_fail`**: "It stays in the grass, where
  its owner dropped it." The work order asked for its removal on the
  grounds that a takeable thing never shows it. The thing became
  takeable and the line stayed.

### Correction, 2 November: public use lines were already built

**This note said they were not, and that was wrong.** The claim was that
`bot.use` still replies privately, that the rattle's copy had been
written for a change the engine had not made, and that a player shaking
it was privately shown a sentence about themselves in the third person.
None of that is true. The rattle has posted to the room, and said
nothing privately, since #136.

The mechanism is `world.after_use` returning `Effect(public=True)`,
which `_finish_use` routes to `_post_in_room` before dismissing the
ephemeral reply. It is in `world.py`, not `bot.py`, which is why
searching `bot.py` for the posting found nothing — and `bot.use`'s own
docstring still says "the reply is always private", which read as
confirmation. A stale comment and a search of the wrong file agreed with
each other, which is not the same as being corroborated.

So the music box needed one line beside the rattle rather than a change
to `/use`, and the shape was already the one this note asks for: the two
things named in code, no per-thing column.

### Public use lines are for these two things only

**Decided 2 November.** The rattle and the music box post their `use`
line to the room. Nothing else does, and there is no per-thing column
for it — the two are named in the code.

`bot.use`'s docstring argues the general case and the argument still
holds: *"a use is a small private moment, and making every one public
would bury the thread."* A property on every row would be an invitation
to turn the thread into a feed one tsv cell at a time, and the writers
would be the ones deciding how noisy the game is while reading one row.
Two things that are literally noises are a small, legible exception.

If a third thing ever wants it, that is the moment to ask whether this
has become a class. Two is not a class.

---

## Build order

1. ~~**The two content leftovers above**, with the public-use-line
   change for the rattle and the music box and nothing else.~~ **Done.**
   The rattle's `take_fail` is gone and the music box is named beside
   the rattle in `world.after_use`; its `default` line lost the baby
   monitor sentence, which moved to an `in:NU` row where the monitor
   is. Leaving it in both would have said it twice in the one room
   where it is true.
2. ~~**Captive Audience.**~~ **Done.** `captive_audience_size` defaults
   to 3 in `CONFIG_KEYS`, `database.active_others_in_room` counts the
   room off `last_command_at`, and the predicate excludes the rattler
   from their own audience.
3. ~~**The rattle's idle drop.**~~ **Done**, once #143 landed the
   generalised sweep: the rattle is an entry in
   `world.SET_DOWN_WHEN_IDLE` and nothing else, and the generalised
   `exhausted.public` fills in `{name}` to produce the line the work
   order asked for without anybody writing it twice.

   **It had to earn the tuple.** That set is for things the house has
   one of *and somebody else needs*, which a forgotten rattle was not
   until Captive Audience shipped - a rattle nobody is playing with is
   now the only thing between every other player and an achievement.
   Waiting for #143 was right: building it earlier would have meant
   writing the generalisation a second time.
4. **`thing_uses.last_used_room`.** One column, and the thing
   Accompanist cannot be correct without.
5. **Accompanist, with the Upstairs release.**

Steps 4 and 5 wait on drop 40 existing. Step 3 waits on somebody else's
branch, which is a better reason to wait than most.
