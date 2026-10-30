# Drop 20 work order: the rest of the hall

Oct 29, 2026 · @Qaruse

Drop 20 fills in the Entryway, starts the shipping box deliveries, and opens the shared staircase repair. The content files are already done. This page lists the code that's left. The design is in Drop 20 design, and the top-step rules come from The ladder (drop 30).

**Depends on:** the drop 10 work order (`fed_the_cat`, room text fragments, the locked house), the cat bed's daily reset (`use_cooldown_daily`), the restock scheduler, and the achievements engine.

**Decided 29 October:**

- Alexa and the bulletin board wait at 99. They need more testing and a notes feature first.
- The repair takes 90 planks by default, one per player per day, counted per server.
- Planks 73 to 90 need the ladder, which arrives at drop 30. So in drop 20 the repair stops at plank 72, on purpose.
- Players may guess thing names before feeding the cat. Only room text and exits stay gated on `fed_the_cat`.
- The box is now `shipping_box`, and random spawns never land in it.

## What the player sees

1. **The Entryway fills in.** After feeding the cat, a player's room text adds the cloudy mirror, the stroller with the shoes and booties, the shipping box and the ruined staircase with its lumber. The front door's look now mentions the intercom.
2. **Deliveries arrive.** From the drop's second day, two spice jars land in the shipping box every 2 to 10 hours, up to 16 at a time. Each delivery posts a notice in the Entryway thread.
3. **The server repairs the staircase.** `/use lumber` lays one plank per player per day, and the shared count shows after each plank and in the lumber's and staircase's looks.
4. **The repair reaches the top steps and stops.** At plank 72, the staircase and room text change to "mostly mended", and further planks are refused until the ladder arrives at drop 30.
5. **A new secret achievement.** *Are You David?* goes to players at 1,000 relationship points.

## Content files

All of these are in the creative content folder as of 29 October. Nothing below needs writing, only reading.

| File | Drop 20 rows |
| --- | --- |
| `things.tsv` | The Entryway things at `since_drop` 20. `alexa` and `bulletin_board` at 99. `shipping_box` (was `amazon_box`), named "shipping box". `lumber` with `use_cooldown_daily = yes` and no hours cooldown. The spice jar's `contained_in = shipping_box` |
| `thing_text.tsv` | Texts for those things. Lumber and staircase looks end with "{n} of {total} repairs done.". New `stairs_upper` rows for `lumber` (drop 20, with the high-steps refusal, and drop 30, with the ladder line) and for `EH`. `EH` `stairs_repaired` at drop 20 has the cat-on-the-landing `use_fail`, and its drop 40 row has the `use` |
| `room_text.tsv` | Entryway fragments 2, 3, 5 and 7 at drop 20. Fragment 4 at 99. A new fragment 7 row for `stairs_upper` |
| `restocks.tsv` | Row 1: two spice jars into `shipping_box`, `max_present` 16. Its `times_per_day` and `every_n_days` are placeholders until the interval columns in change 1 exist |
| `achievements.tsv` | `are_you_david` and `board_meeting` at 20. `passing_a_message_to_david` at 99 |
| `defaults.tsv` | `delivery.arrived.public` and `stairs.repaired.public` |
| `drops.tsv` | Drop 20's notes |

**Check the code for `amazon_box`.** The id was renamed in the content files. Any hard-coded reference to the old id needs the same change.

**Bolding follows [How Bolding Works](https://claude.ai/artifact/FE7LgFADNevawevtWq3N9Q),** with no new engine work. The drop 20 prose names each thing as `things.tsv` does (mirror, stroller, pile of shoes, booties, shipping box, grand staircase, lumber), and none of it contains asterisks. One check for the load: the intercom is named only in the front door's drop 20 look, not in any Entryway room fragment. Confirm that the named-in-its-room check counts look text, or the load will fail on it.

## Code changes

1. **Restocks at random intervals.** Add two columns to `restocks.tsv`, for example `interval_min_hours` and `interval_max_hours`. After each delivery, schedule the next one at a uniformly random time inside that range. For row 1, the first delivery is at a random time on the drop's second day, then every 2 to 10 hours. Keep `max_present`: fill toward 16 and never exceed it.
2. **`scatter_target`.** A new `things.tsv` column, default yes. Restock rows with `placement = random` (the bottles and diapers today) never pick a thing with `scatter_target = no` as their container. Set it to no on `shipping_box`.
3. **The arrival notice.** When a restock delivers into `shipping_box`, post `delivery.arrived.public` in the Entryway thread. All players in that thread see it, fed or not.
4. **One plank a day, counted per server.** `lumber` uses the cat bed's daily reset. Each successful `/use lumber` adds 1 to a per-server count. `{n}` is that count and `{total}` is a new per-server config value, `staircase_planks`, default 90.
5. **`{n}` and `{total}` in looks.** Fill these tokens in `look` text as well as `use` text. Put a line break before "{n} of {total} repairs done." wherever it appears, in looks and in `lumber.use`.
6. **The `stairs_upper` server state.** Set it when the count reaches 80% of `staircase_planks`, rounded down: plank 72 by default. From then on, `stairs_upper` rows apply to `lumber`, `EH` and Entryway fragment 7, the same way `stairs_repaired` rows will.
7. **Two refusals for lumber.** In `stairs_upper`, `/use lumber` needs the ladder at hand: in the player's inventory or in the Entryway's Also here list. Check this first, and refuse with the `stairs_upper` row's `use_fail` ("The steps you can reach from the floor are all done..."). Then check the daily limit and refuse with the once-a-day line ("You've set your plank. Your muscles will want about {time}..."). Both are `use_fail` today, so the once-a-day line needs its own slot, such as a `use_fail_cooldown` column or a lumber-specific default key. Until drop 30 there is no ladder thing, so every `stairs_upper` attempt gets the high-steps refusal.
8. **A takeable thing in the room can meet `requires`.** Today only a non-takeable thing in the room counts. The ladder rule in change 7 needs a takeable ladder standing in the room to count too.
9. ***Are You David?*** Award at 1,000 relationship points. Check for a score at or above 1,000, not only for crossing it, so players already past 1,000 when the drop opens get it on their next cat interaction.
10. **No hiding for things.** Things answer to their names once the server reaches their drop, whether or not the player has fed the cat. Exits, including the grand staircase, stay gated on `fed_the_cat` as in drop 10.
11. **Delayed content stays out.** Alexa (`room_id = ALL`), the bulletin board, fragment 4 and *Passing a Message to David* are at 99, and must not appear in any room, listing or achievement list.

12) **Raise the latest playable drop to 20.** The engine's cap on the highest drop that can be reached must be 20, or `/advance-game` and `/qa-drop` stop short of this drop. A prior drop progression hit this bug, so every drop's work order carries this step.

## Logging

One `interaction_log` row per event below, so the repair's pace and the box's stock can be tuned from the data.

- **Planks:** each `/use lumber`, with the outcome (laid, refused for the daily limit, refused for the top steps), the count after it, and whether the player had fed the cat.
- **`stairs_upper` reached:** the time, and how many different players had laid a plank by then.
- **Deliveries:** each spice delivery, with the jars added and the box's total after it, including deliveries that were capped at 16.
- **Spice jar takes and drops,** with the box's total after each.
- **Random spawns:** the container each bottle or diaper landed in, so a QA run can confirm none went into the box.
- ***Are You David?*** awards, with the player's score at the time.

## Acceptance tests

Run on a QA server with `/qa-drop` to reach drop 20. First check that /qa-drop and /advance-game both reach 20 and stop there, which confirms change 12. Set `staircase_planks` to 5 there, so `stairs_upper` arrives at plank 4. Shorten restock row 1's interval on the QA copy, for example to 1–2 minutes, so deliveries can be watched.

**The Entryway**

- A player who has fed the cat sees fragments 1, 2, 3, 5 and 7, in that order. There's no bulletin board or smart speaker sentence.
- A player who hasn't fed the cat sees only fragment 1, the same as drop 10.
- `/look front door` mentions the intercom.
- `/look alexa` and `/look bulletin board` get the not-here refusal in every room and in the channel.
- `/look shipping box`, `/look amazon box` and `/look delivery box` all show the shipping box.
- A player who hasn't fed the cat can `/look mirror` and `/use lumber` by guessing, but `/go staircase` gets the no-such-exit refusal.

**The shipping box**

- The box is empty on the drop's first day. Two jars arrive on the second day, then two more each interval.
- The box never holds more than 16 jars. Taking some lets deliveries fill it back up.
- Every delivery posts `delivery.arrived.public` in the Entryway thread.
- No bottle or diaper ever lands in the box, across at least a day of spawns.
- `/use spice jar` ends "Lovely, but not useful on its own."

**The repair**

- `/use lumber` lays a plank and shows "1 of 5 repairs done." after a line break. A second try the same day gets the once-a-day line with the time until the reset. The next day it works again.
- Two players laying planks on the same day bring the count to 2.
- `/look lumber` and `/look staircase` show the current count after a line break.
- At plank 4, `/look staircase` and the Entryway's fragment 7 switch to the "mostly mended" text.
- After that, `/use lumber` gets the high-steps refusal, whether or not the player has laid a plank today, and the count stays at 4.
- `/go staircase` in `stairs_upper` gets "You get most of the way up before the steps run out..."

**Achievements**

- A player already above 1,000 relationship points gets *Are You David?* on their next pet, toy, bed or feed. It's a secret achievement, so it shows only to them.
- *Passing a Message to David* doesn't appear in any achievement list.

## Not in this drop

- **Finishing the staircase.** The repair can't pass plank 72 without the ladder, so it can't finish during drop 20. Its pieces are already in the files: `stairs_repaired`, `stairs.repaired.public`, *Board Meeting* for every player who laid at least one plank, and the cat holding the landing until drop 40. Build and test them with the drop 30 work order. *Board Meeting* needs a new kind of group award, given only to contributors and announced once.
- **The ladder,** carrying it, climbing it, the cat taking it, and the wasp nest pieces. All of it is drop 30.
- **Alexa and the bulletin board,** at 99 until a later drop is picked.
- **Opening drop 40** stays an admin step.
