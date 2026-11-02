# Rattle achievements work order

Nov 2, 2026 · @Qaruse

Four secret achievements for the wooden rattle, plus the public lines they need and an idle drop for the rattle. **Noise Complaint and Accompanist are the ones we want.** Opening Act and Back Where It Belongs are included as simpler fallbacks, in case either of the first two is much harder to build.

**Depends on:** use lines that post to the room instead of privately, the idle drop and its default line from the Watering can work order, and the achievements engine.

## The achievements

### Wanted: Noise Complaint

| Field | Value |
| --- | --- |
| `achievement_id` | `noise_complaint` |
| `kind` | secret |
| `name` | Noise Complaint |
| `unlock` | Added a rattle to the racket. Somebody should call the landlord. |
| `since_drop` | 30 |
| `sort_order` | 135 |

**Trigger:** a `/use rattle` in a room whose thread has had at least 8 public lines about other players in the last 5 minutes. Public lines are the ones the bot posts to the room: arrivals and departures, takes, drops, pets, feeds, rattles, the music box, achievements and so on. Lines about the player who is rattling don't count, so nobody can earn it alone.

Make both numbers config values, `noise_complaint_lines` (default 8) and `noise_complaint_minutes` (default 5), so a small server can reach it.

### Wanted: Accompanist

| Field | Value |
| --- | --- |
| `achievement_id` | `accompanist` |
| `kind` | secret |
| `name` | Accompanist |
| `unlock` | Kept time on the rattle while the music box played. |
| `since_drop` | 40, when the music box arrives |
| `sort_order` | 145 |

**Trigger:** a `/use rattle` within 60 seconds of a different player's successful `/use music box` in the same room. The music box needs the new public line below, or nobody else in the room knows it's playing.

### Fallback: Opening Act

| Field | Value |
| --- | --- |
| `achievement_id` | `opening_act` |
| `kind` | secret |
| `name` | Opening Act |
| `unlock` | Gave a rattle performance to a live audience. Reviews are mixed. |
| `since_drop` | 30 |
| `sort_order` | 155 |

**Trigger:** a `/use rattle` while at least 3 other active players are in the same room. Active means their current room is that room and they've run a command in the last 10 minutes. Config: `opening_act_audience` (default 3).

### Fallback: Back Where It Belongs

| Field | Value |
| --- | --- |
| `achievement_id` | `back_where_it_belongs` |
| `kind` | secret |
| `name` | Back Where It Belongs |
| `unlock` | Carried the rattle in from the garden and played it in the nursery, where it belongs. |
| `since_drop` | 40, when the Nursery opens |
| `sort_order` | 165 |

**Trigger:** any successful `/use rattle` in the Nursery.

## Content changes

**`thing_text.tsv`, `rattle`, default row (drop 30).**

| Field | Today | New |
| --- | --- | --- |
| `look` | A wooden rattle with a painted stripe. It still works; you can tell by the weight of it. | *\[keep\]* |
| `use` | Rattle rattle! {player} is having some fun. | *\[keep\]* |
| `take_fail` | It stays in the grass, where its owner dropped it. | *(remove: a takeable thing never shows it)* |

**`thing_text.tsv`, `music_box`, default row (drop 40).**

| Field | Today | New |
| --- | --- | --- |
| `use` | You open the lid and the lullaby starts up, thin and slow. Through the baby monitor, faintly, the same tune is already playing. | {player} opens the music box, and a thin, slow lullaby drifts through the room. |
| `use`, new `in:NU` row (Nursery only) | — | {player} opens the music box, and a thin, slow lullaby drifts through the room. Through the baby monitor, faintly, the same tune is already playing. |

**Neither has a private line (decided 2 November).** Each thing's `use` line is posted to the room, and that post is the whole reply, including to the player who used it. The rattle keeps its line as it is. The music box's becomes the third-person line, and the baby monitor sentence moves to a Nursery-only `in:NU` row, where the monitor is. Both rows post publicly. No new `defaults.tsv` keys are needed.

**`achievements.tsv`:** the four rows above.

## Code changes

1. **The rattle and the music box answer in public.** A successful `/use rattle` or `/use music box` posts the thing's `use` line to the room's thread, with `{player}` filled in, instead of replying privately. There's no separate private line for either.
2. **Noise Complaint.** Count the public lines posted in the room's thread in the last `noise_complaint_minutes`, leaving out lines about the rattler. Award when the count is at least `noise_complaint_lines`. `interaction_log` already records most of these events with a room, so it may be the easiest source.
3. **Accompanist.** On `/use rattle`, check for a successful `/use music box` by another player in the same room in the last 60 seconds.
4. **Opening Act (fallback).** On `/use rattle`, count the other players whose current room is this one and who ran a command in the last 10 minutes. Award at `opening_act_audience` or more.
5. **Back Where It Belongs (fallback).** On `/use rattle`, award if the room is the Nursery.
6. **An idle drop for the rattle.** If the rattle is in a player's inventory and they run no command for 24 hours, move it to their current location's Also here list and post the default `exhausted.public` there: "{player} gets tired and sets the wooden rattle down." Same rule as the ladder and the watering can.
7. **Confirm the latest playable drop reaches 40.** Accompanist and Back Where It Belongs wait for drop 40, so the engine's cap on the highest reachable drop must be at least 40 when they ship, or `/advance-game` and `/qa-drop` stop short. Every work order carries this step.

## Logging

- **Rattles:** room, the public-line count at the moment for Noise Complaint, the number of other active players present, and whether the music box played in the last 60 seconds. One row answers every threshold question.
- **Music box uses,** with the room.
- **Rattle idle drops,** with where it was left.

## Acceptance tests

- `/use rattle` posts "Rattle rattle! {player} is having some fun." to the room, and the player gets no separate private reply. `/look rattle` no longer mentions the grass.
- `/use music box` posts "{player} opens the music box, and a thin, slow lullaby drifts through the room." to the room, with no private reply. In the Nursery it adds "Through the baby monitor, faintly, the same tune is already playing."
- **Noise Complaint:** with config lowered on QA (for example 3 lines in 5 minutes), two testers pet, take and drop in a room, then a third rattles and earns it. A tester who rattles alone, however often, doesn't.
- **Accompanist:** one tester plays the music box and a second rattles within a minute in the same room: earned. After 60 seconds, or in another room, or by the same tester: not earned.
- **Opening Act:** with 3 other testers active in the room, a rattle earns it. With 2, it doesn't.
- **Back Where It Belongs:** a rattle in the Nursery earns it. Anywhere else doesn't.
- A tester carrying the rattle who goes quiet for 24 hours (shortened on QA) drops it where they stand, and the room sees "{player} gets tired and sets the wooden rattle down."
