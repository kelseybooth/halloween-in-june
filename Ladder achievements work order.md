# Ladder achievements work order

Nov 6, 2026 · @Qaruse

Five more achievements for the ladder, chosen 6 November. They build on what the ladder already does, as designed in The ladder (drop 30), and none of them overlaps *Rung by Rung*, *Hive Five* or *Board Meeting*. All five are secret and arrive at drop 30, with the ladder.

**Depends on:** the drop 30 ladder work (climbs, the cat roll, the 5-minute guard, set-downs), `room_deeds`, and `database.active_others_in_room` from *Captive Audience*.

**A climb** below means a successful `/use ladder` that reached the top. A cat climb, where the cat gets to the top first, is not a climb, the same rule *Rung by Rung* uses.

## The achievements

| `achievement_id` | `name` | `unlock` | `sort_order` |
| --- | --- | --- | --- |
| `king_of_the_mountain` | King of the Mountain | Climbed above the crowd and surveyed your kingdom. | 225 |
| `second_place` | Second Place | Lost the race up the ladder to the cat three times. She's very good at this. | 235 |
| `pass_it_on` | Pass It On | Set the ladder down, and someone else picked it up within minutes. Teamwork, of a kind. | 245 |
| `heavy_lifting` | Heavy Lifting | Hauled the ladder through four rooms without putting it down once. Your shoulders would like a word. | 255 |
| `head_for_heights` | Head for Heights | Climbed the ladder twenty-five times. You're spending more time up there than down here. | 265 |

All five: `kind` secret, `since_drop` 30.

## Triggers

### King of the Mountain

**A climb with an audience.** Award on a climb when at least `captive_audience_size` other players are in the same room and have run a command in the last `AUDIENCE_MINUTES` (10). That's the *Captive Audience* check, reused as it is.

**Why not count recent public posts?** That was *Noise Complaint*'s design, and it was dropped when the rattle achievements were built: the only record of what a room has seen is `interaction_log`, which the game doesn't read to decide anything. *Captive Audience* (renamed from Opening Act) shipped with the live headcount instead, so this one uses the same check.

### Second Place

**Three cat climbs that the player rolled themselves.** The tally goes up by one when a player's own `/use ladder` rolls the 10% cat climb: they started up and the cat beat them to the top. Award at 3.

- **Swats don't count.** A player who then tries to take or climb the ladder while the cat is guarding it gets a swat line, but no tick. They only earn ticks by starting a climb themselves that the cat takes.
- **The ladder doesn't have to be theirs.** It doesn't matter who carried the ladder there or set it down. Only whose `/use ladder` rolled the cat.
- Expect it to take a while: at 10% a roll, three cat climbs take about 30 climbs on average.

### Pass It On

**Rewards putting the ladder down, not grabbing it.** The player who set the ladder down earns it when a *different* player takes it within 10 minutes.

- **Counts as setting it down:** `/drop ladder`, the set-down when a player climbs a carried ladder, and the set-down when a top-step plank goes in.
- **Doesn't count:** the idle drop, because a player who went quiet didn't choose to share. Nor does the cat climb, since the player who rolled it didn't hand it on to anyone.
- **Taking it back yourself** within 10 minutes doesn't earn it, and it clears the chance for that set-down.
- **Keep one record** of the last set-down: who did it, and when. Check it on every `/take ladder`.

### Heavy Lifting

**Four rooms in one trip.** Count each move to another place, the road included, while the ladder stays in the player's inventory. Award on the fourth. The count resets to 0 whenever the ladder leaves the inventory, by any route: `/drop`, a climb, a plank, the idle drop or the trash. Moving back and forth between two rooms counts, because it's still four rooms' worth of carrying.

### Head for Heights

**25 climbs, any time.** Count the player's climbs from `room_deeds` (or `thing_uses`). Climbs from before this ships count, so no backfill is needed. Cat climbs don't count.

## Logging

The ladder's climbs and moves are already logged. Add:

- **King of the Mountain:** the audience size at the moment of each climb, so `captive_audience_size` can be tuned for climbs as well as rattles.
- **Pass It On:** each take of the ladder, with how long since the last set-down and who did it.

## Acceptance tests

On a QA server at drop 30, with `captive_audience_size` lowered and the cat roll forced where needed.

- **King of the Mountain:** with enough other testers active in the room, a climb earns it. With one fewer, it doesn't. A cat climb with a full audience doesn't.
- **Second Place:** tester A's climb rolls the cat three times: earned. Tester B's swats while A's cat is guarding don't move B's tally. B earns ticks only from B's own climbs that roll the cat.
- **Pass It On:** A drops the ladder and B takes it 5 minutes later: A earns it, B doesn't. After 11 minutes: nobody. A picks it back up: nobody. After an idle drop: nobody.
- **Heavy Lifting:** carry the ladder through four moves without setting it down: earned on the fourth. Drop it after three and carry it three more: not earned.
- **Head for Heights:** the 25th climb earns it. Cat climbs aren't counted.
- **Confirm the latest playable drop reaches 30,** so `/qa-drop` and `/advance-game` reach this drop. Every work order carries this step.
