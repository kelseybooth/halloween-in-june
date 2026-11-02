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

**Nothing new is needed to build it.** `achievements.Context` already
carries `room_id` and `on_use` already fills it from
`state.current_room`, so the predicate reads the room it is given.
"Other players in this room" is `player_game_state.current_room`, and
"ran a command in the last 10 minutes" is an `interaction_log` row for
that player inside the window — which the existing
`(guild_id, user_id, action, created_at)` index covers. No schema
change, no new table, no backfill.

Drop 30 is reachable: `LAST_PLAYABLE_DROP` is 31.

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

**It waits on drop 40, and that is a release rather than a constant.**
The music box is an `object` in `NU`, and the Nursery arrives with
Upstairs. `LAST_PLAYABLE_DROP` is 31, and the comment above it is
explicit that the ceiling moves in the release that builds the next
drop. So Accompanist ships with Upstairs, not before it.

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

## Two things the content left behind

- **The rattle still has a `take_fail`**: "It stays in the grass, where
  its owner dropped it." The work order asked for its removal on the
  grounds that a takeable thing never shows it. The thing became
  takeable and the line stayed.
- **Public use lines are not built, and the rattle's copy now assumes
  them.** `bot.use` still replies privately — its docstring says so and
  gives the reason, that a use is a small private moment and making
  every one public would bury the thread. So a player who shakes the
  rattle today is privately shown a sentence about themselves in the
  third person. The copy is ready for a change the engine has not made.

That second one is a prerequisite for Accompanist rather than a
tidy-up: the trigger turns on one player noticing another player's music
box, and the work order says as much — "the music box needs the new
public line below, or nobody else in the room knows it's playing."

---

## Build order

1. **The two content leftovers above**, with the public-use-line change
   for the rattle and the music box. Small, and it makes the rattle's
   existing copy true.
2. **Captive Audience.** Nothing to plumb.
3. **`thing_uses.last_used_room`.** One column, and the thing
   Accompanist cannot be correct without.
4. **Accompanist, with the Upstairs release.**

Steps 1 and 2 are drop 30 and can go now. Steps 3 and 4 wait on drop 40
existing.
