# Drop 20 design: The Rest of the Hall

Oct 29, 2026 · @Qaruse

Drop 20 fills in the rest of the Entryway and starts the staircase repair, the server's shared job that leads upstairs. Alexa and the bulletin board wait for a later drop, so nothing that still needs building or testing blocks players from exploring the house.

## What's in and what waits

Drop 20 opens four of the five remaining Entryway fragments. All of them stay behind `fed_the_cat`, like the rest of the drop 10 fragments.

| Fragment | Text | Drop |
| --- | --- | --- |
| 2 | A cloudy mirror hangs by the door. | 20 |
| 3 | A stroller is parked in the corner by a pile of shoes and tiny booties. | 20 |
| 4 | A bulletin board hangs over a small table where a smart speaker blinks blue. | **waits (99)** |
| 5 | A shipping box sits half-opened against the wall. | 20 |
| 7 | The grand staircase is a ruin, with fresh lumber stacked beside it. | 20 |
| 7, `stairs_repaired` | A patched grand staircase sweeps up to the floor above. | 20 |

Fragment 4 names both delayed things, so the whole fragment waits with them. Fragment 6, the two doorways, stays at drop 30.

| Thing | At drop 20 |
| --- | --- |
| lumber | The staircase repair, below |
| grand staircase (`EH`) | Unsafe until repaired. Once repaired, it holds, but the way up waits for drop 40 |
| shipping box, spice jar | Jars arrive in the box on a schedule, below |
| intercom | Scenery. The front door's drop 20 look already names it |
| mirror | Scenery. Using it earns *Self-Reflection* (named *Say Cheese* when this was written) |
| stroller, shoes, booties | Scenery |
| Alexa | **Waits (99).** Her `room_id` is `ALL`, so delaying her takes her out of every room |
| bulletin board | **Waits (99),** until players can pin their own notes |

**Guessing is allowed.** A player who hasn't fed the cat can't see these things in the room text. Decided 29 October: if they guess a thing's name once the server has reached its drop, it works, so the engine needs no hiding rule for things. Only the room text and the exits stay gated on `fed_the_cat`. One side effect: an unfed player who guesses "lumber" can lay planks.

## The staircase repair

**The stairs need 90 planks, and each player can lay one a day.** In the beta logs, about 27 players showed up each day. At that rate the repair takes about 3½ days. If only the 18 most active players helped, it would take 5 days, so the less active players have a real share in it.

**The last 20% needs the ladder.** Planks 73 to 90 can only be laid with the ladder at hand, carried or standing in the Entryway. The ladder arrives in the courtyard at drop 30. Laying a plank with a carried ladder sets it down in the Entryway, ready for the next player. See The ladder (drop 30).

**The top-steps gate ships in drop 20**, because players will reach plank 72 during this drop. The ladder itself waits for drop 30.

| Ships in | What |
| --- | --- |
| 20 | Server state `stairs_upper`, set when plank 72 goes in |
| 20 | In `stairs_upper`, `/use lumber` with no ladder in the inventory or the Entryway refuses: "The steps you can reach from the floor are all done. The top ones are too high to fix without something to stand on." **(approved)** |
| 20 | `EH.look`, `EH.use_fail` and Entryway fragment 7 for `stairs_upper` **(approved, and in the files as of 29 October, with the refusal on a lumber stairs\_upper row)** |
| 30 | The ladder, carrying it, climbing it, the cat, and the successful top-step plank line |

**One conflict for the developer:** lumber's `use_fail` already holds the once-a-day message ("Your muscles will want about {time}..."). The ladder refusal needs a separate slot, so both messages can exist in `stairs_upper`.

- **Who:** any player who has fed the cat, using `/use lumber` in the Entryway.
- **How often:** once per player per day, on the same daily reset as the cat bed (`use_cooldown_daily = yes`). This replaces the 48-hour cooldown.
- **The count:** one shared count per server, not per player. Each plank adds 1.
- **The total:** config value `staircase_planks`, default **90**. `{total}` in the lumber line reads from it.
- **No points:** a plank isn't a cat interaction, so it earns no relationship points.

**On the 90th plank:**

1. The server state `stairs_repaired` is set.
2. The lumber disappears. Its `present_when = !stairs_repaired` already does this.
3. Fragment 7 and the staircase's look switch to their repaired versions.
4. `stairs.repaired.public` posts in the Entryway thread.

**Repaired before drop 40:** the stairs hold, but going up waits for drop 40, when the Upstairs Hallway exists. This uses the same pattern as the locked house. The `stairs_repaired` row at drop 20 has a `use_fail`. A second `stairs_repaired` row at drop 40 carries the look and the `use`.

| Key | Text | Status |
| --- | --- | --- |
| `lumber.use` | You haul a plank over to the staircase and hammer it into place. The steps look a little less like a ruin. {n} of {total} repairs done. | existing |
| `lumber.use_fail` | You've set your plank. Your muscles will want about {time} before the next one. | revised. `{time}` now counts down to the daily reset |
| `EH.use_fail`, default | The staircase is crumbled and unsafe. Whole steps are missing. It'll take more than one pair of hands to fix it. | existing |
| `stairs.repaired.public` | {player} hammers in the last plank. The grand staircase is whole again, thanks to everyone who lent a hand. | **a****p****p****roved****, new** |
| `EH.use_fail`, `stairs_repaired`, drop 20 | The new steps hold all the way up to the landing. The cat is already sitting on the top step, and she won't let you past. Not yet, apparently. You head back down. | **a****pprov****e****d****, new** |
| `EH.use`, `stairs_repaired`, drop 40 | You go up the repaired staircase. The new boards creak, cheerfully rather than ominously. | existing, moves from 20 to 40 |

## The shipping box and spice jars

Some changes are listed below. Spice jars arrive in the box under `restocks.tsv` row 1. On the drop's first day the box is empty. From day 2, two jars spawn in the box at random intervals of 2–10 hours, which averages about 8 jars a day. The box holds at most 16 jars (max\_present 16), and deliveries skip while it's full. There's no per-player limit. The random timing should spread the jars among players, and they can share.

The jars can be taken, but they have no use until the kitchen opens at drop 30. Their use line should end: "Lovely, but not useful on its own."

With Alexa waiting, the box's packing slip becomes **the first place players see David's name**. See open questions.

**Decided 29 October:**

- **Name:** "shipping box". Aliases: `shipping box|delivery box|amazon box|box|parcel|package`. Its look drops "Amazon": "A half-opened shipping box with the tape slit down the middle..."
- **No random spawns:** the box is never chosen as the destination for a randomly scattered spawn, such as the diapers and used baby bottles. This needs a new `things.tsv` column, `scatter_target`, which defaults to yes and is set to no on the box. Restock rows that name the box directly, like the spice jars, still deliver to it.
- **Its id (done 29 October):** rename `amazon_box` to `shipping_box` while drop 20 isn't live yet. The id appears in four places: restock row 1, the spice jar's `contained_in`, its `thing_text` row, and `the box's own row in things.tsv`.

**Arrival notice (approved 29 October):** when a delivery lands in the box, `delivery.arrived.public` posts in the Entryway thread:

> Something thumps against the front door, and when you look, the shipping box is a little fuller.

Players who haven't fed the cat are in that thread too, so they'll see the notice before the box appears in their room text. The notice is vague enough that this should read as a tease rather than a bug.

## Are You David?

**The next relationship milestone is 1,000 points.** A player has already passed 500, so there's no 500 achievement. The wording follows *Cat's Best Friend*, the 100-point one.

Approved:

| Field | Value |
| --- | --- |
| `achievement_id` | `are_you_david` |
| kind | secret, like the 100 and 250 milestones |
| name | Are You David? |
| unlock | You've earned 1,000 relationship points with the cat. |
| since\_drop | 20 |
| sort\_order | 215, beside *Favorite Human* |

**Why drop 20:** the name only makes sense once players have seen David's name, and drop 20 is where that happens. Players already past 1,000 when the drop opens should get it on their next cat interaction. The developer should confirm the check runs then, not only at the moment a score crosses 1,000.

## File changes

Applied to the content files on 29 October. Still for the developer: the scatter\_target column, the restock interval columns and the staircase\_planks config value. The look lines now end with "{n} of {total} repairs done.", so the engine needs to fill those tokens in looks as well as uses, and add the line break. 99 means not yet scheduled, the same as the other blocked rows.

| File | Change |
| --- | --- |
| `things.tsv` | `alexa` and `bulletin_board`: `since_drop` 20 → 99. `lumber`: `use_cooldown_hours` 48 → blank, `use_cooldown_daily` → yes |
| `things.tsv` | **Done 29 October:** `amazon_box` is named "shipping box", with aliases shipping box \| delivery box \| amazon box \| box \| parcel \| package. For the developer: a new column scatter\_target (default yes), set to no on the box. Done: the id is now shipping\_box in things.tsv, thing\_text.tsv, restocks.tsv and the README. |
| `thing_text.tsv` | `alexa` (default and `reminded`) and `bulletin_board`: 20 → 99. `EH` `stairs_repaired`: the drop 20 row keeps its look and gets the new `use_fail`; a new drop 40 row carries the look and the `use` |
| `thing_text.tsv` | **Done 29 October:** the box's look says "shipping box". The spice jar's use is now "You unscrew the lid and breathe in. Lovely, but not useful on its own." |
| `room_text.tsv` | Entryway fragment 4: 20 → 99. **Done 29 October:** fragment 5 is now "A shipping box sits half-opened against the wall." |
| `restocks.tsv` | **For the developer:** row 1 delivers two jars on day 2, then two more at a random interval of 2–10 hours after each delivery. The spice jar keeps no max\_per\_player. Done 29 October: max\_present is 16. The current columns can't express this, so it needs two new ones, for example `interval_min_hours` and `interval_max_hours`. Random-placement rows (bottles, diapers) skip anything with `scatter_target = no` |
| `achievements.tsv` | `passing_a_message_to_david`: 20 → 99, with a note that it waits for Alexa. Add board\_meeting: group, Board Meeting, "Got together and nailed down the grand staircase repair.", drop 20, sort 40. Add `are_you_david` |
| `defaults.tsv` | Add `stairs.repaired.public. Done 29 October: added delivery.arrived.public` |
| `drops.tsv` | Drop 20 notes: drop Alexa and the bulletin board, add the repair, and say "shipping box" for "Amazon box" |
| config | `staircase_planks`, default 90 |
| `README.md` | The "one plank per player per 48 hours" section becomes one a day |

## Open questions

- [ ] **David's introduction.** The drop schedule meant the Alexa reminder to introduce David "by name and with context." Without it, players only see his name on a packing slip. Is that enough for now, or does drop 20 need one more line about him?\
Response: that's enough context for now.
- [ ] **Progress between planks.** Players see the count only when they lay a plank. Should the staircase or lumber look show `{n} of {total}` too, or `/stats`?\
Response: When you look at the lumber or the staircase, show "{n} of {total} repairs done." after a line break, like the lumber use text.
- [ ] **Credit for the repair.** Is the public line on the last plank enough, or do you want a group achievement for the whole server? Response: Board Meeting, on the last plank, for players who laid at least one plank.
- [ ] **Opening drop 40.** The schedule says upstairs should open on the repair. Should a repaired staircase advance to drop 40 automatically once drop 30 is out, or stay an admin step?\
Response: stay an admin step. Use the cat blocking language I approved if drop 40 isn't out yet.
- [ ] **Which later drop** gets Alexa and the bulletin board. They sit at 99 until you pick one.\
Response: let's stay at 99 for now. There's too much prep work to pick a drop yet.

### Group achievement for the repair: options

It's awarded on the last plank, but only to players who laid at least one plank, right after `stairs.repaired.public`. It's announced once, like the other group achievements, as "{server} earned **{achievement}**: {description}". Row: kind `group`, `since_drop` 20, `sort_order` 40, after the three existing group achievements. Chosen: Board Meeting, with the edited line.

| Name | Unlock line |
| --- | --- |
| Stepping Up | Everyone pitched in, and the grand staircase is whole again. |
| Board Meeting | Got together and nailed down the grand staircase repair. |
| Many Hands | Rebuilt the grand staircase, one plank and one person at a time. |
| Barn Raising | Fixed the grand staircase the old-fashioned way: together, a plank a day. |

The lines don't name a plank count, so they stay true if `staircase_planks` changes. *It Takes a Village* is already taken by the bottle quest.
