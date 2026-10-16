# 

# Phase 3a Work Order — Drops 0 and 1

The gating and hinting proof of concept. Two drops, four player commands, one object.

## What this is

Phases 2a through 2f built a working game: nine rooms, nine commands, 35 achievements. **Phase 3a does not add to it. It hides almost all of it, and proves two mechanisms everything later depends on.**

**Gating** — content and commands exist only from the drop that owns them, per server, with two servers able to sit on different drops at once.

**Hinting** — one rail that tells a player what to do next, fires each line once, and never recommends something they have already done.

If those two work, drops 2 through 7 are content and scheduling. If they do not, nothing later is safe.

**The riskiest work here is subtraction.** The leak test in the acceptance pass is not a formality — it is the main way this release fails.

## Prerequisite: the content file edits

**Do not start until the content file edit spec has been applied.** Every existing row in `achievements.tsv` and `things.tsv` carries `since_drop = 1`. Under the new numbering, where drop 0 is the cat alone, the first `/advance-game` would reveal the entire game rather than a cat bed. That spec moves the existing rows out of reach, excepts Eunoia's own row, and adds the new rows and columns this work order assumes.

## Scope

|  | Drop 0 | Drop 1 |
| --- | --- | --- |
| Player commands | `/pet`, `/stats` | **plus** `/look`, `/use` |
| Admin commands | `/start-game`, `/advance-game`, `/admin_config` | — |
| Content | the cat | one cat bed, fixture, not takeable |
| Achievements | *Making First Contact*, *A Paw in the Door*, *Favorite Human* | **plus** *Fluffed to Perfection* |
| Hints | 2 | 3, plus the public drop announcement |

**Out of scope, and the gating must prove it:** `/take`, `/inventory`, `/go`, `/enter`, `/drop`, `/initialize-haunted-house`, all nine room threads, the cat toy, feeding, the craving game, `/help`, and the 35 pre-existing achievements.

## 1. The drop machine

**One clock function.** Route every time-of-day read through a single `server_now()` — the midnight job, the Pacific day boundaries, the bed's 24-hour window, everything. Nothing else calls the system clock. This is an hour's work now and a week of hunting later, and it is what makes a single `clock_offset_days` in `server_config` test every dated behaviour at once.

**A per-server current drop.** Stored per guild, starting unset. Content resolution already keys on `since_drop`; it now resolves against this value rather than against a calendar. A row whose `since_drop` exceeds the server's current drop is invisible — loaded, present in the files, not reachable.

**No calendar in 3a.** Drops advance by admin command only. Dates return once a few servers have run and the pacing is known.

## 2. Admin commands

**`/start-game <channel>`** — opens drop 0 in the named channel. The channel is named per server and will be renamed later, so it is an argument rather than a constant. Idempotent: a second call in the same channel reports the current state and changes nothing. A call naming a **different** channel is refused rather than moving the game, since moving it would orphan every player row's sense of where the game is.

**`/advance-game`** — moves the server forward exactly one drop. Forward only, one step, and it confirms before firing. At the last defined drop it refuses and says so rather than advancing into nothing. Going backwards is `/qa-drop` on the test servers and nowhere else.

Both are admin-only and both write an audit line.

## 3. Command registration is the gate

**Commands are deregistered, not refused.** A command a player cannot use is not in their slash menu at all — it cannot be typed, guessed, or half-learned. That is the whole point: the playtest overwhelm came from a menu full of verbs.

**Every player command is registered per guild, not globally.** Guild registration is what lets two servers sit on different drops, and guild command updates propagate in seconds where global ones can take an hour. If the bot registers globally today, that is the change — and it means registering on guild join as well as on every advance, so the bot must know every guild it is in.

**Use the bulk-overwrite endpoint**, replacing a guild's whole command set in one call, rather than creating and deleting commands individually. One request per guild per advance, and it stays clear of per-command create limits during `/qa-drop` churn in testing.

**The registered set per drop:**

| Drop | Player | Admin |
| --- | --- | --- |
| 0 | `/pet`, `/stats` | `/start-game`, `/advance-game`, `/admin_config` |
| 1 | `/pet`, `/stats`, `/look`, `/use` | the same |

## 4. The channel becomes a room

Three drops happen in a place the room model does not contain, and drop 1 needs `/look` there. **Add the Halloween channel as a room-like row** — no exits, never listed, never reachable by movement, no `room_text`.

That makes the cat bed an ordinary thing with an ordinary `room_id`, and `/use` resolves through the existing path rather than a parallel one. It also retires the special case `/pet` currently carries for resolving in the channel.

**`/look` in the channel prints a list and no description.** Prefix `channel.look_prefix` — *"Items here:"* — then the things present. `channel.look_empty` covers the case where nothing is there; in drop 1 that cannot happen, since the bed is a fixture, but it is reachable from drop 2.

**The cat is not in the list.** `/look cat` resolves against her `things.tsv` row as an easter egg, found rather than signposted.

## 5. The relationship meter

The developer's audit of 14 October is the authority on what exists. Four changes:

**Start at 0**, not +50 — `database.py:74`, and `/reset-haunted-house`, which also returns players to the start value.

**Remove the upper clamp.** The clamp is a SQL `CASE` in the same statement as the arithmetic. The upper bound comes out; the lower bound at −100 stays. *Favorite Human* at 250 is the first content that requires this.

**Widen the nightly drift's skip condition.** It currently skips any player who *petted* in that server that day. It must skip any player who **interacted with the cat at all** — petting, the toy, the bed, or feeding. Implementation: a single `last_cat_interaction_date` per (player, guild), stamped by every interaction and read by the nightly job, rather than four branches in the decay query.

**Attempts count, not just successes.** Three of the four interactions can fail — the toy's first offer is a guaranteed refusal, the bed refuses inside its window, a pet can roll standoffish. Any attempt stamps the date. The drift exists to notice absence, and a player who tried four times was not absent.

The drift's own arithmetic is unchanged and correct: positive scores lose 10 a night floored at 0, negative scores gain 20 a night capped at 0.

**Thresholds need a hook that fires wherever the score moves.** Three achievements are score thresholds — 50, 100 and 250 — and four actions write the score. *Cat's Best Friend* listens on `on_pet` today, which was enough when petting was the only lever; a player pushed to 50 by a bed fluff would go unchecked. Add **`on_relationship_change`**, fired wherever the score is written, and register all three thresholds against it.

## 6. Two things already built that change

**The crowding nudge moves.** It currently appends at the tenth pet in the ten-minute window. It now fires **the first time a pet has a 0% chance of success** — `80 − 10 × recent_pets` at zero, which is the ninth pet. Private only, as now.

Note for the record: the penalty begins earlier than the nudge. The fourth pet in ten minutes is break-even and the fifth is the first with a negative expectation. The nudge is the only place a player can ever learn the penalty exists, since the public line no longer reports relationship state.

**The public pet line reports the pet, not the relationship.** It currently branches on the meter after the pet, printing `pet.public.positive` if `> 0`. It must branch on the **mood roll** — friendly or standoffish — and read the score not at all. Rename the two strings to `pet.public.friendly` and `pet.public.standoffish`, since the current names describe the relationship and will be misread.

This reverses what Phase 2f recommended and the code correctly implements. The reason 2f gave was consistency with the petting achievements' above-zero test, and that test no longer exists in that form — see below.

**Making Friends and Trying to Make Friends become one fork.** Not two tallies of qualifying pets: **one counter of total pets, evaluated once.** At 200 pets, the sign of the relationship **after** that pet decides which fires. Positive → *Making Friends*. Zero or negative → *Trying to Make Friends*. The comparison operators at `triggers.py:87` do not change; what is counted does.

Two details. Evaluate on **"200 or more and neither held"**, not "exactly 200" — a check that fires only on the 200th pet is lost forever if the bot is down or a write races. And the two are **mutually exclusive**: no player can ever hold both.

## 7. `/stats`

Always ephemeral. Three parts, in order.

**The relationship.** The raw integer, as now, plus a sentence beneath it. Four bands: exactly 0, below 0, above 0, 100 or more. The figure stays visible and unrounded — it is the only thing telling a player which way they are moving, and the bands are deliberately wide.

**Open Quests.** Header and contents appear **only when the player has at least one visible quest**. With three public quests in the whole plan, a player will spend long stretches with none open, and a standing *"No open quests"* reads as broken rather than as waiting. The string for the empty state exists in the copy deck, parked, in case testing says otherwise.

**Completed Achievements.** Header always, including when empty, because its empty line is the only instruction anywhere in the game: *"No completed achievements. Try /pet."* With `/help` deferred and no welcome text, hiding it would leave a first `/stats` showing nothing but a number.

**Both lists run newest first.** Most recently earned achievement at the top, so *Making First Contact* sits at the bottom forever; most recently unlocked quest at the top, where a player looks after being told a new one is available.

Three notes. `player_achievements` has no stated awarded-at column — if there is none, descending insertion order gives the same answer. Quest order can reuse the hint rail's table, which already records the order quests were revealed. And ties need a deterministic tiebreak, since the dispatcher may fire two achievements from one action; insertion id descending is enough. **`sort_order` in `achievements.tsv` no longer drives `/stats`.**

**Running `/stats` marks every currently visible quest as seen**, and sets the has-opened-stats flag the quest notice reads.

## 8. Quests, minimally

A public achievement with a visibility prerequisite *is* a quest. This pulls a minimal version of the quest system into 3a.

Three columns on `achievements.tsv`, added by the content spec: **`offered`** (is this shown before it is earned), **`prompt`** (the prospective wording), **`requires`** (one achievement id that must be held first).

**A quest is visible to a player when** `offered` is set, `since_drop` is at or below the server's current drop, `requires` is held by that player, and the achievement is not yet earned.

**`requires` is single-valued.** Every public quest is rooted at *Making First Contact*, so one id is enough. The moment a quest needs two unrelated prerequisites this becomes a resolver, so keep the tree rooted.

## 9. Achievements in scope

| id | Name | `kind` | Condition | Hook | `since_drop` | Visible when |
| --- | --- | --- | --- | --- | --- | --- |
| `making_first_contact` | Making First Contact | secret | first `/pet` that rolls friendly | `on_pet` | 0 | never — secret |
| `a_paw_in_the_door` | A Paw in the Door | public | relationship first reaches 50 | `on_relationship_change` | 0 | holds `making_first_contact` |
| `favorite_human` | Favorite Human | secret | relationship reaches 250 | `on_relationship_change` | 0 | never — secret |
| `fluffed_to_perfection` | Fluffed to Perfection | public | first `/use cat bed` | `on_use` | 1 | drop ≥ 1 and holds `making_first_contact` |

Also live from drop 0 and already built: *Making Friends*, *Trying to Make Friends* and *Cat's Best Friend*, all reachable in principle and none likely to land before drop 1.

**The drop-0 spine is these rows, and it is the tutorial.** A player pets the cat; at 80% friendly the first try usually lands; *Making First Contact* fires as a surprise, teaching in one event that achievements exist; and *A Paw in the Door* becomes visible as their first open goal. Making First Contact being **secret** is the load-bearing part — a quest log that appears because you did something is a reward, where one that was always there is furniture.

Announce format is unchanged from 2f: private *"You earned \[name\]: \[description\]"*, public *"\[display name\] earned \[name\]"*.

## 10. The hint rail

One mechanism carries every nudge in the game. Quest notices and tutorial hints are the same shape — a line appended to a message the player was getting anyway — so they share one store and one dispatcher.

**Storage: one table of what this player has been told.** `(guild, player, hint_id)`, one row per hint shown, and the same table holds quest-notified ids and the has-opened-stats flag. A handful of rows per player. **`/qa-reset-player` must clear it**, or the ladder is one-shot per tester per server.

**Format:** every hint renders as *Hint: \<text>* in italics. The label is not part of the string.

**The invariant that covers every precondition: never recommend an action the player has already taken.** That gives all the per-hint conditions for free and catches a case the table does not state — a player whose first `/look` is `/look cat bed` would otherwise be told to try `/look cat bed`.

Two mechanics follow. **At most one appended line per message**, since one action can satisfy several triggers. And **a hint is retired either by being shown or by being made moot**, recorded the same way, so nothing resurfaces as advice to do something already done.

**The quest notice is computed, not tracked.** On any private cat message, work out which quests are currently visible and unearned, compare against the ids this player has been told about, and append if there are new ones. That covers both the achievement case and the overnight drop-advance case in one path, and reuses the visibility helper `/stats` needs anyway.

It graduates: until the player has attained **3 quests and** opened `/stats` at least once it points at `/stats`; after that it names the quest and its prompt inline. **Note that 3 is not reachable inside 3a** — only two public quests exist before drop 2 — so the graduated string ships unexercised by design. More quests arrive as V3 progresses.

**The drop announcement is public, and carries its hint.** When drop 1 opens, `drop.1.announce` posts in the channel with `hint.something_new` beneath it. Two consequences: the private firing of that hint **stays** as the fallback for anyone who was not there, and **the public firing must not set the per-player shown flag** — a channel post has no player attached, and marking everyone as told would kill the fallback for exactly the people it exists for.

All strings, triggers and statuses are in the **V3 POC copy deck**. Nothing in it is waiting on a writer.

## 11. The cat bed

One bed, in the channel, present from the moment drop 1 opens. **Usable, not takeable, never consumed.** `/take` does not exist in 3a; `cat_bed.take_fail` is written for drop 2.

`/use cat bed` fluffs it: **+15 relationship, once per player per Pacific day.** Shared fixture, per-player cooldown. It stamps `last_cat_interaction_date` and fires `on_use`.

## 12. New per-player state

| Field | Why |
| --- | --- |
| `last_cat_interaction_date` | the drift's skip condition, widened beyond petting |
| `last_bed_fluff_date` | the bed's once-a-day cooldown |
| hint/quest/stats rows | the rail's told-you table, keyed `(guild, player, hint_id)` |

The toy's ramp counter and cooldown, and the feed counter, arrive with drop 2 and drop 3. Three new per-player values here, five by drop 3 — worth deciding now whether this stays as columns on the player row or becomes a small per-player key-value table, because the answer changes once more fields arrive.

## 13. QA commands

Registered **guild-scoped on the two test servers only** — `1542854260524453978` and `1548007001915658250` — so the live server never sees them in its slash menu. Gated to a QA role on top of that. Every call replies ephemerally and writes one line to a log channel.

| Command | Does |
| --- | --- |
| `/qa-drop <n>` | jump the server to any drop, forwards or back |
| `/qa-reset-player <member>` | wipe one player's state **including the hint rows** |
| `/qa-relationship <member> <n>` | set the score — 50 and 250 are days of honest play away |
| `/qa-clock <+n days \| reset>` | offset `server_now()` |
| `/qa-midnight` | fire the nightly drift now |
| `/qa-cooldown <member> clear` | clear the bed's 24 hours and the 10-minute pet window |
| `/qa-inspect <member>` | dump player state, and say whether the drop pointer is overridden |

`/qa-teleport`, `/qa-spawn` and `/qa-state` wait for rooms. **A forced drop must be visibly forced** in `/qa-inspect` and the log, or someone will spend an afternoon debugging a server that is simply not where they think it is.

## 14. Definition of done

**Gating**

- Two test servers sit on different drops at the same time, each with its own registered command set
- At drop 0, `/look` and `/use` are absent from the slash menu — not present and refusing
- `/advance-game` adds them within seconds, without a restart
- Nothing from drop 2 or later is reachable or *mentioned* at drop 0 or 1: no room, no thread, no pre-existing achievement, no thing
- `/start-game` run twice is harmless; run against a second channel it refuses
- `/advance-game` at the last defined drop refuses

**The meter**

- A brand-new player starts at 0
- The score passes 100 and reaches 250 without clamping
- A day with a pet, and a day with only a bed fluff, both skip the drift
- A day with a *failed* bed fluff also skips it
- A day with no interaction drifts by the built rule
- `/stats` prints the figure and the right one of four bands, zero included

**Achievements and quests**

- First friendly pet awards *Making First Contact* and appends its hint
- *A Paw in the Door* is invisible before that and visible after
- Reaching 50 via a bed fluff awards it — proving `on_relationship_change` rather than `on_pet`
- 250 awards *Favorite Human*
- The Open Quests section is absent when nothing is open, and the Completed Achievements header is present when nothing is earned
- Both lists render newest first, and two achievements from one action render in a stable order

**The hint rail**

- Each of the five hints fires once and never again
- `/look cat bed` as a first action produces **one** hint, not two
- A player who uses the bed before looking at it gets the look hint, not the use hint
- A player who has done both gets neither
- Drop 1 opening posts the announcement with its hint beneath, publicly, once
- A player who was absent for that still gets the private hint on their next command
- `/qa-reset-player` replays the whole ladder from the start

**The pet changes**

- The public line reports the pet's own reaction, not the relationship
- The crowding nudge fires on the first 0% pet
- Pet 200 awards exactly one of the two friendship achievements, by the sign after that pet
- A player who passes 200 while the check is unavailable still earns it on a later pet

## 15. Known gaps, deliberately left

**Nothing in the game tells a new player to run `/pet`.** Every hint fires after an action, so the ladder cannot bootstrap itself. For 3a an admin shares `/pet` or pins a message in the channel. This is server furniture rather than game copy, and it is not a shippable answer for a public server — it needs solving before a real launch.

**The craving game does not exist.** It belongs in drop 0 when it is written; the POC does not wait.

**The graduated quest notice cannot fire.** Three quests is unreachable before drop 2.

**The pronoun sweep is not in this work order.** The cat is *she*, never *it*, and that needs one pass across the content files and the code — including `/look cat`, which still reads "It looks up at you with moonbright yellow eyes." Do it as a single pass; a half-converted file looks finished.
