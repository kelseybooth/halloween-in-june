# Drop 30 work order: the ground floor (draft)

Oct 30, 2026 · @Qaruse

Drop 30 opens the Dining Room, Kitchen, Courtyard and Living Room, brings the ladder, lets the server finish the grand staircase, and makes the kitchen trash can work. The designs are in The ladder (drop 30), The kitchen trash can and Room text rewrite (drops 30–50). This page lists the content and the code.

**Depends on:** the Drop 20 work order (`stairs_upper`, the two lumber refusals, `to_hand_in_room`, `scatter_target`, `use_fail_cooldown`), the restock scheduler, the achievements engine, and bolding as in [How Bolding Works](https://claude.ai/artifact/FE7LgFADNevawevtWq3N9Q).

**Decided:**

- There's one ladder, starting in the Courtyard. Using it always sets it down. The road climb stays private, and the wasp nest pieces are only for collecting (29 October).
- Planks 73 to 90 need the ladder at hand, carried or standing in the Entryway (29 October).
- The kitchen back stairs are deleted. Upstairs is reached only by the repaired grand staircase, at drop 40 (30 October).
- The trash can mechanics are approved, and things stay in it until somebody takes it out (30 October).
- The curiosity cabinet and the oak tree exist from drop 30 but refuse until drop 50 (30 October).

## What the player sees

1. **Four rooms open.** The Entryway's doorways lead to the Dining Room and the Living Room, and through them to the Kitchen and the Courtyard.
2. **The ladder.** It stands in the Courtyard. Anyone can carry it, and climbing it shows each room from above. While it's carried, the player's hands are full.
3. **The staircase can be finished.** With the ladder at hand, `/use lumber` lays planks 73 to 90. The last plank posts the repair announcement and awards *Board Meeting* to everyone who laid a plank. The cat then sits on the top step until drop 40.
4. **Wasp nest pieces.** Each climb on the road knocks a piece of the nest into the road.
5. **The cat sometimes takes the ladder.** On 10% of climbs she gets to the top first and guards it for 5 minutes.
6. **The trash can works.** Players throw things away, fish them back out, and take the bag out to the curb.
7. **A cat bowl in the Courtyard.** Feeding works there as at the Entryway bowl.
8. **Two ways into the library tease.** The curiosity cabinet is locked, and the oak won't take a climber yet.
9. **New achievements:** *Bin Looking for You*, *Trash Panda, Hive Five* and *Board Meeting*, plus a new trigger for *Curbside Pickup*.

## Content files

| File | Drop 30 rows |
| --- | --- |
| `things.tsv` | `ladder` (`to_hand_in_room = yes`, `scatter_target = no`, `yields = wasp_nest_piece`), `wasp_nest_piece`, `cat_bowl_courtyard`, `board_books` (was `soft_blocks`), `LS` and `CS` at 30. `trash_can` with the aliases `trash bag` and `garbage bag` and `scatter_target = no`. `ivy` is now an exit with destination BE. `KH` and `HK` removed. Drop 40 rows ride along: the Bedroom's ivy exit `BC`, and `bedroom_window` with `requires = graphite_powder` |
| `thing_text.tsv` | Ladder rows (`default`, `in:CO`, `in:EN`, `in:CH`, `in:KI`, `in:DI`, `in:LI`, the cat and guarded lines), the wasp nest piece, the Courtyard bowl, the board books, the oak's and cabinet's drop 30 refusals, the `stairs_upper` lumber row with the ladder line, the trash can's new look, and the courtyard ivy's drop 30 refusal. Drop 40 rows ride along: the ivy's `stairs_repaired` and `window_open` rows, `BC`, and the window's `window_open` row |
| `room_text.tsv` | The rewritten Dining Room, Kitchen, Courtyard and Living Room, one paragraph each. The Courtyard's interim cat bowl sentence is gone |
| `defaults.tsv` | `carrying.ladder`, `ladder.cat.public`, `ladder.exhausted.public`, `stairs.repaired.public`, and the trash can lines `trash.menu` through `trash.out.public`. `carrying.ladder.ivy` is for drop 40 |
| `achievements.tsv` | New `bin_looking_for_you` and `hive_five` at 30. `trash_panda` and `board_meeting` moved from 99 to 30. `curbside_pickup`'s note has the new trigger |

All of these are in the creative content folder as of 30 October, and the content checker passes. Nothing above needs writing, only reading.

**Bolding follows How Bolding Works,** with no new engine work. The four room drafts were checked with the engine's own marking code at drop 30.

## Code changes

### The ladder

1. **A use line per room.** `thing_text` rows whose state names a room (`in:CO`, `in:EN`, `in:CH`, `in:KI`, `in:DI`, `in:LI`) apply when the player is in that room. `default` covers everywhere else.
2. **Hands full while carrying.** With `ladder` in the inventory, `/pet`, `/take` and `/use` refuse with `carrying.ladder`. The exceptions are `/use ladder`, `/use lumber` and `/use` on an exit. Feeding is a `/use`, so it's blocked too.
3. **Using it sets it down.** Any successful `/use ladder` moves a carried ladder from the inventory to the room's Also here list. A top-step plank does the same in the Entryway.
4. **Only the road climb drops a piece.** `/use ladder` on the road adds one `wasp_nest_piece` to the road's room contents. Climbs anywhere else drop nothing. The ladder's `yields` is set so the loader counts the piece as obtainable, so the engine must not treat it as a yield on every climb. A player's first road climb that knocks a piece down earns Hive Five. A cat climb drops no piece and doesn't count, and neither does picking up someone else's piece.
5. **The cat takes it.** On 10% of `/use ladder`, the cat line replaces the room's line and `ladder.cat.public` posts to the room. No nest piece falls. For the next 5 minutes, nobody can take or climb the ladder: `/take` and `/use` answer with the guarded `take_fail` and `use_fail`. The lock is per ladder and lifts silently. No relationship points either way.
6. **A carrier who goes quiet.** If the ladder is in a player's inventory and they run no command for 24 hours, it moves to their current location's Also here list, and `ladder.exhausted.public` posts there, in the room's thread or the channel.

### Finishing the staircase

7. **Top-step planks.** Drop 20 built the refusals. Now that the ladder exists, `/use lumber` in `stairs_upper` succeeds when the ladder is carried or standing in the Entryway, using the `stairs_upper` row's `use` line. Check for the ladder first, then the daily limit, as in drop 20.
8. **The last plank.** When the count reaches `staircase_planks`, set `stairs_repaired`, post `stairs.repaired.public`, and switch the staircase, lumber and Entryway fragment 7 to their repaired rows. Lumber disappears (`present_when = !stairs_repaired`). Until drop 40, `/go staircase` gets the cat-on-the-landing refusal.
9. ***Board Meeting*, for contributors only.** Right after the announcement, award it to every player who laid at least one plank, announced once in the group style. Players who never laid a plank don't get it. This is a new kind of group award: today a group row awards the whole server.

### The ground floor

10. **Any cat bowl counts.** Every cat food's `requires` names `cat_bowl`. Let any thing named "cat bowl" meet it, so feeding works at the Courtyard bowl (and the Upstairs Hallway bowl at drop 40).
11. **No way into the library or upstairs early.** The oak (`CS`) and the cabinet (`LS`) exist from drop 30 with refusal lines, and so does the courtyard `ivy`, now an exit to the Bedroom. Make sure the oak and cabinet can't move a player into the Secret Library before drop 50, and the ivy can't move anyone into the Bedroom at all in drop 30. The cabinet is already shut without the key, but the oak and the ivy aren't in `exit_refused_by`. From drop 40 the ivy opens only for players holding `window_open`, which is drop 40 work.
12. **Board books (optional).** If it's cheap, let the board books rotate through numbered `use` lines like the toys. The extra lines are in the Room text tab.

### The trash can

13. **The trash can holds things.** As specified in the trash can tab: `/use trash can` opens a private menu of droppable carried things with All or Some. Things move into `room_contents` with `container_id = trash_can`. `/take` takes them back out like any container. The lines are the `trash.*` keys in `defaults.tsv`, with the tokens `{name}`, `{count}` (how many the player carries) and `{amount}` (how many went in).
14. **Taking out the trash.** `/take trash can` empties it. Delete anything a source yields, a restock places (including `type:` rows), a `transforms_to` produces, or another thing `yields`. Place everything else in a random container in an open room, with `scatter_target` yes, outside the trash can and the Secret Library. The brass key counts as one-of-a-kind.
15. **Trash can achievements.** *Trash Panda* on the first take from the trash can. *Curbside Pickup* on `/take trash can` on a Pacific Tuesday, replacing its old `/use` trigger. *Bin Looking for You* on a player's first `/look` in the Kitchen, if they carry a `dirty_diaper` at that moment. Record that first look per player.

### Housekeeping

16. **The source-name check keeps every fragment.** `_check_sources_are_named_in_prose` keys room text by (room, state), so a room's later fragments overwrite its earlier ones. Check against all fragments for that state.
17. **Raise the latest playable drop to 30.** The engine's cap on the highest drop that can be reached must be 30, or `/advance-game` and `/qa-drop` stop short of this drop. A prior drop progression hit this bug, so every drop's work order carries this step.

## Logging

One `interaction_log` row per event below.

- **Ladder climbs:** room, whether the cat roll fired, and whether the ladder was carried.
- **Ladder moves:** takes, drops, set-downs by climbing or planking, and the 24-hour idle drop.
- **Planks 73 to 90:** the outcome (laid, no ladder, daily limit), where the ladder was, and the count after.
- **`stairs_repaired` reached:** the time, the number of different players who laid planks, and how many got *Board Meeting*.
- **Wasp nest pieces:** each one dropped and taken.
- **The trash can:** each throw-away (thing and count), each take-out, and each emptying, with what was deleted and where each one-of-a-kind thing landed.
- **Achievements:** each award above, with the player.

## Acceptance tests

Run on a QA server with `/qa-drop` to reach drop 30. First check that `/qa-drop` and `/advance-game` both reach 30 and stop there, which confirms change 17. Set `staircase_planks` to 5, so `stairs_upper` arrives at plank 4 and the repair finishes at plank 5.

**The rooms**

- After feeding the cat, the Entryway shows both doorways. `/look` in each new room shows its new text, and every bold word answers to `/look`.
- `/look curiosity cabinet` and `/use curiosity cabinet` both work, and the use gets "You tug at the glass doors. Locked." `/use oak tree` gets the oak's refusal, and the player stays in the Courtyard.
- `/use ivy` and `/go ivy` in the Courtyard get "a whole curtain of it peels away from the wall", and the player stays in the Courtyard.
- Feeding the cat at the Courtyard bowl works.

**The ladder**

- `/take ladder` in the Courtyard puts it in the inventory and takes it out of the Also here list. While carrying it, `/pet`, `/take` and `/use cat food` get the carrying line. `/go`, `/look` and `/use front door` work.
- `/use ladder` in each of the six rooms gives that room's line. Upstairs or anywhere else, it gives the default line. Each time, the ladder ends up in the room's Also here list.
- On the road, each climb adds one piece of wasp nest to the Also here list, and `/take piece of wasp nest` picks it up. The first climb that drops a piece earns Hive Five, and later climbs don't award it again. `/take wasp nest` still refuses.
- With the cat roll forced, the cat line shows, the room sees the public line, no piece falls, and `/take ladder` and `/use ladder` get the swat lines for 5 minutes, then work again.
- A tester who carries the ladder and goes quiet for 24 hours (shortened on QA) drops it where they stand, with the exhaustion line.

**The staircase**

- At plank 4, `/use lumber` without the ladder gets the high-steps refusal. With the ladder carried or standing in the Entryway, it lays plank 5, and a carried ladder ends up standing in the Entryway.
- Plank 5 posts the repair announcement. The staircase and Entryway text switch to repaired, lumber is gone, and every tester who laid a plank gets *Board Meeting*. A tester who laid none doesn't.
- `/go staircase` gets the cat-on-the-landing refusal.

**The trash can**

- `/use trash can` lists only droppable carried things. Throwing away 3 of 6 spice jars leaves 3 in the bag and 3 in the trash can's Also here list. The room sees that something was thrown away, not what.
- Another tester can `/take` a spice jar out and earns *Trash Panda*.
- `/take trash can` with cat food and a cat collar inside: the cat food is gone, the collar is in some container elsewhere (never the trash can, the shipping box or the Secret Library), and the clink line shows.
- On a Tuesday, Pacific time, `/take trash can` earns *Curbside Pickup*.
- A new tester carrying a dirty diaper earns *Bin Looking for You* on their first `/look` in the Kitchen. A second `/look` never awards it.

## Not in this drop

- **Upstairs**, the Bedroom window's graphite mechanic, the ivy climbs, the ladder's ivy refusal and the Upstairs Hallway cat bowl. All drop 40. Their text is already in the files at drop 40.
- **The Secret Library**, the ghost and the spirit board. Drop 50.
- **The room text for the Upstairs Hallway, Bedroom, Nursery and Secret Library.** They ship with their drops.
- **Alexa and the bulletin board,** at 99 until a later drop is picked.
- **Opening drop 40** stays an admin step.
