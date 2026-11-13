# Drop 50 work order: the Secret Library

Nov 8, 2026 · @Qaruse

Drop 50 opens the Secret Library, the last room in the house, and the two ways into it: the oak tree from the Courtyard, and the curiosity cabinet from the Living Room. Each player discovers it for themselves. It also brings the ghost of the day and the spirit board game that catches the ghost. Checked against the files on 8 November.

**Build it in two parts, in this order.**

1. **Part 1, opening the library:** code changes 1 to 7. Ship it to QA first, so testing of the room and its objects can start while Part 2 is built. Change 7 (raising the latest playable drop to 50) belongs to Part 1, because QA can't reach the library without it.
2. **Part 2, the ghost and the spirit board:** code changes 8 to 15. Start it once Part 1 is on QA. Until Part 2 lands, the spirit board keeps its "isn't ready for you yet" line, so the library can be tested without it.

The acceptance tests are split the same way.

**Depends on:** drop 46 (in testing now, and reaching beta before this drop), the per-player states `library_found` and `passage_open`, `has_key` read off the inventory, `room_deeds`, and the drop 30 rule that the oak and the cabinet refuse until 50.

**Decided:**

- The library is found per player, because the discovery is the content (Phase 2e).
- **The ghost and the spirit board ship in drop 50, as Part 2** (decided 8 November). Their full design and every line of text are in The ghost and the spirit board (exported beside this file). The decisions made there stand: the ghost is drawn from players active the day before, at least 3 must be eligible, repeats are allowed, the board gives one letter clue and one guess a day, the ghost is revealed at changeover unless they never haunted (amended 11 November), whispers are capped at 300 characters with mentions off and the author logged, and *Boo Who?* is the new achievement.
- On 3 November the developer decided that climbing exits don't refuse a player whose hands are full, except the ivy with the ladder. So the ladder can go up the oak into the library, which *Rung by Rung* needs.

## What the player sees

1. **The oak takes a climber.** `/use oak tree` in the Courtyard climbs it, finds the half-hidden window and lands the player in the library. That first climb earns *Out on a Limb* and records `library_found` for them. After that, the oak is a quick way in and out.
2. **The library.** The room text, the scorch circle, the ritual diagram, three cracked mirrors, the empty cat bed, the spirit board, the shelves and the copper wire.
3. **The keys.** A ring of iron keys on the shelves gives each player one skeleton key, which can't be dropped or taken from them.
4. **The cabinet opens.** In the Living Room, the curiosity cabinet stops answering "Locked." for a player with a key: it swings out on its hidden hinge and lets them through. That sets `passage_open`, and from then on the back of the cabinet works from the library side too.
5. **The house is complete.** *Rung by Rung* and *Burrito Trail* can now be finished, because the library is the tenth place both need.
6. **A ghost each day (Part 2).** One active player secretly gets a bedsheet and can haunt any room with anonymous whispers. In the library, the spirit board gives each player one letter of the ghost's name and one guess a day. At the daily changeover, the board reveals who it was, as long as they haunted at all.

## Content

**Already in the files:**

| File | Drop 50 rows |
| --- | --- |
| `things.tsv` | The library's things: `scorch_circle`, `ritual_diagram`, `cracked_mirrors`, `empty_cat_bed`, `spirit_board`, `library_shelves`, `key_nail` (the ring of keys, a source), `skeleton_key`, `copper_wire_spool` (a source) and `copper_wire`. The exits `SL` (back of the cabinet) and `SC` (library window) |
| `thing_text.tsv` | Text for all of the above. The oak's (`CS`) drop 50 and `library_found` rows, and the cabinet's (`LS`) `has_key` and `passage_open` rows. Their drop 30 refusals stay underneath |
| `room_text.tsv` | The Secret Library at 50, rewritten and approved 11 November |
| `achievements.tsv` | *Out on a Limb*, *Rung by Rung* and *Burrito Trail* at 50 |

**Settled on 11 November:**

| What | Status |
| --- | --- |
| **The library's room text** | Approved and written to `room_text.tsv`, replacing the old `SE` row. It names the spool of copper wire |
| **Use lines for the two library sources** | The ring of keys and the spool of copper wire are sources. Their `use` lines are never read today: a source's own `use` line is a known gap in the Parking lot. If that's fixed, their lines need to read as uses, not as takes |
| **A library climb line for the ladder** (optional) | Skipped. In the library the ladder plays its default private line, as in any room without its own |

**Part 2 content.** The ghost's lines and achievements are in the files as of 11 November. The bedsheet and the spirit board rows can't go in yet: the loader refuses a thing nothing produces until `bedsheet` is in `PLACED_BY_CODE`, and the board's new look would show during Part 1. Add those rows in the Part 2 commit, exactly as below.

| File | What |
| --- | --- |
| `things.tsv` | **Add in the Part 2 commit.** A `bedsheet` row after `spirit_board`: name `bedsheet`, aliases `sheet\|bed sheet\|silvery sheet\|silver sheet\|silver bed sheet\|silver bedsheet\|ghost sheet`, type `object`, no room, `quantity` 0, `takeable` no, `droppable` no, `cross_weight` 0, `max_per_player` 1, `since_drop` 50, `sort_order` 179, `scatter_target` no |
| `thing_text.tsv` | **Add in the Part 2 commit.** A `bedsheet` default row at 50 with `look` and `look_carried` both "A silvery bedsheet, worn thin at the folds. It smells of cedar and something older." (the loader wants a default `look` on every thing) and `drop_fail` "The bedsheet clings to you. It isn't done with you yet." On the `spirit_board` default row at 50, set `look` to "A varnished board printed with the alphabet, YES in one corner, NO in the other and GOODBYE along the bottom. The heart-shaped planchette never sits quite still." and empty `use`, which drops the "isn't ready" line. Both rows pass the loader once `bedsheet` is in `PLACED_BY_CODE` |
| `defaults.tsv` | **Written 11 November**, 23 keys: `ghost.new`, `ghost.first`, `ghost.gone`, `ghost.haunt.picker`, `ghost.haunt.modal.title`, `ghost.haunt.modal.label`, `ghost.haunt.modal.placeholder`, `ghost.haunt.public`, `ghost.haunt.private`, `board.ask.clue`, `board.ask.ghost`, `board.ask.no_letters`, `board.ask.already`, `board.name.yes`, `board.name.no`, `board.name.self`, `board.name.non_player`, `board.name.already`, `board.name.not_yet`, `board.no_ghost` (both buttons), `ghost.reveal.named`, `ghost.reveal.nobody` and `ghost.reveal.quiet`. New tokens: `{whisper}`, `{letter}`, and `{count}` in the clue, written out as "three times" |
| `achievements.tsv` | **Written 11 November.** `getting_into_the_spirit` and `ghostbuster` moved from 99 to 50 with new notes, and `boo_who` added (secret, *Boo Who?*, "Haunted the house all day, and nobody guessed it was you.", drop 50, `sort_order` 305). All three are secret, so shipping them with Part 1 shows nothing |

## Code changes

### Part 1: opening the library

1. **The oak opens at 50.** Before 50 it refuses with its drop 30 line, and the drop 30 work order asked for it never to move a player into the library early. From 50, its drop 50 row applies: the first climb uses the discovery line and sets `library_found`, and later climbs use the shorter `library_found` line. The oak stays in `UNGATED_EXITS` and out of `exit_refused_by`, because a door gated on the state its own use produces would never open.
2. **The cabinet opens for a key-holder at 50.** `exit_refused_by` keeps it shut without `has_key`. With a key, the `has_key` row's line plays, and using it sets `passage_open`. After that, the `passage_open` rows apply from both sides, and `SL` stops refusing.
3. **The keys.** `key_nail` yields one `skeleton_key` per player (`max_per_player` 1, `droppable` no, `cross_weight` 0). Nothing new, but it's the first drop where anyone can reach it.
4. **The library stays out of placement.** One-of-a-kind things sent back into the house by the trash can and the idle drops already skip the library, because a player who hasn't found it couldn't get them back. Keep it that way.
5. ***Out on a Limb*** on a player's first move through the oak (`on_move`, as built).
6. ***Rung by Rung* and *Burrito Trail*** already count the library through `room_deeds` and `rooms.tsv`. Nothing to change, but they can only be completed from this drop.
7. **Raise the latest playable drop to 50.** `LAST_PLAYABLE_DROP` in `resolve.py` will be 46 once drop 46 lands, and drop 46 reaches beta first. Raise it to 50 in the same release, or `/advance-game` and `/qa-drop` stop short of the library. A prior drop progression hit this bug, so every drop's work order carries this step.

### Part 2: the ghost and the spirit board

Start once Part 1 is on QA. The full rules are in the ghost and spirit board tab; these are the pieces to build.

8. **The daily pick.** At the Pacific changeover, after the reveal (change 13), pick one ghost at random from players who ran any command on the previous Pacific day. Skip the day if fewer than `ghost_min_players` (config, default 3) are eligible. Store server, day, ghost, their display name and their username at the pick, and take every clue from those saved names. The same player can be picked two days running.
9. **The first ghost.** The first player to enter the library once the ghost system is live becomes the ghost straight away, with the first-ghost notice added to their arrival text, and the 3-player minimum doesn't apply. They keep the bedsheet until the next changeover, when the reveal and the random picks begin. Part 1 alone only ever runs on the QA server. On the second test server and on beta, both parts launch together, so the first player into the library always comes through the oak, since the skeleton keys hang inside. That's why the first-ghost notice is written for climbing in. On QA, a library found during Part 1 testing doesn't count: only the first entry after Part 2 goes live does.
10. **The bedsheet.** Placed in the ghost's inventory by code and removed at the next changeover. Add `bedsheet` to `PLACED_BY_CODE`. It can't be dropped, taken, sent away by the cat or thrown in the trash, and it never shows in `/stats`.
11. **`/use bedsheet`.** A room picker listing rooms open at the current drop (the library only if the ghost has found it), then a pop-up for the whisper, then the post in that room's thread, unsigned, with mentions turned off, capped at `haunt_max_chars` (config, default 300), and logged with its author for admins. No limit on how many. The first haunting earns *Getting into the Spirit*.
12. **`/use spirit board`.** A private reply with two buttons, **Ask the board** and **Name the ghost**, each limited to once per player per Pacific day.
    - **Ask:** the letter in place *n* of the saved name, where *n* comes from a fixed hash of day, server and player, so it can't be rerolled. The letters come from the first word of the saved display name, and only its first 8 letters, so the planchette circles at most eight times. Fold accents (É is E), skip anything that isn't A to Z before the first letter, and end the word at a space or any other non-letter, except hyphens and apostrophes, which are skipped. If the display name has no A to Z letters, use the saved username the same way. The full rules and examples are in the ghost tab. The count is written out (once, twice, three times…). The ghost gets the Y-O-U line, a name with no letters gets the won't-settle line, and on a day with no ghost every board answer is the GOODBYE line.
    - **Name:** Discord's member picker. Picking yourself, or someone who has never entered the house, refuses without using up the day's guess. Right gets YES and *Ghostbuster* the first time. Wrong gets NO. A right guess doesn't end the ghost's day. Until the ghost has haunted at least once that day, the button refuses before the picker opens, with "You rest your fingers on the planchette, but it won't budge. Nothing has stirred in the house today.", and the guess isn't used up.
13. **The reveal.** At changeover, before the new pick, post yesterday's ghost in the main channel by display name, with no ping, and the count of players who named them right. If the ghost never haunted that day, don't name them: post "Yesterday slipped by without a single haunting. The spirit board is keeping the name of whoever held the silvery sheet to itself." instead.
14. ***Boo Who?*** At changeover, award it to a ghost who haunted at least 3 times that day and was named by nobody.
15. **The spirit board's text switches** from the "isn't ready" row to the Part 2 look and buttons in the same release as changes 8 to 14, never before them.

## Logging

- **Library discoveries:** the time each player first reaches the library, and whether it was by the oak or the cabinet.
- **Skeleton keys taken,** and each player's first passage through the cabinet.
- **Ladder climbs in the library,** to see how many players chase *Rung by Rung* to the end.
- **Ghost picks (Part 2):** day, ghost, how many were eligible, and skipped days.
- **Hauntings:** room, length and author (for admins only, never shown to players).
- **Board uses:** each clue asked and each guess, right or wrong, so the difficulty can be tuned.

## Acceptance tests

Run on a QA server. First check that `/qa-drop` and `/advance-game` both reach 50 and stop there, which confirms change 7.

**Part 1, before 50 (at drop 46)**

- `/use oak tree` gets "You get a hand on the lowest branch and pull…", and the player stays in the Courtyard.
- `/use curiosity cabinet` gets "You tug at the glass doors. Locked." and nothing moves.
- `/look` can't reach anything in the library from anywhere.

**Part 1, at 50**

- `/use oak tree` in the Courtyard gives the discovery line, moves the player into the library, and earns *Out on a Limb*. A second climb gives the shorter `library_found` line.
- A second tester who hasn't climbed the oak can't get in through the cabinet: it's still locked for them.
- In the library, `/take skeleton key` gives one key. A second take refuses. `/drop skeleton key` refuses.
- With the key, `/use curiosity cabinet` in the Living Room plays the hidden-hinge line and moves the player into the library. After that, the cabinet works from both sides for that player only.
- `/use library window` climbs back down the oak to the Courtyard.
- Carrying the ladder, a tester climbs the oak into the library and climbs the ladder there. That counts toward *Rung by Rung*.
- A burrito dropped in the library counts toward *Burrito Trail*.
- Until Part 2 ships, `/use spirit board` still gets "isn't ready for you yet".
- Taking out the trash, or an idle drop, never places a one-of-a-kind thing in the library.

**Part 2: the ghost and the spirit board** (on QA, with `ghost_min_players` lowered and the changeover triggered by hand)

- The first tester to enter the library after Part 2 goes live gets the bedsheet and the first-ghost notice, even with fewer than 3 players.
- At changeover: the reveal posts yesterday's ghost with no ping. If the ghost never haunted, the quiet-day line posts instead and names nobody. A new ghost is picked only from testers active the day before, and only if enough are eligible.
- `/use bedsheet`: the room picker lists only reachable rooms, and the whisper posts unsigned, with `@everyone` left as plain text. A 301-character whisper is refused or trimmed. The first haunting earns *Getting into the Spirit*.
- `/drop bedsheet` refuses. The bedsheet isn't in `/stats`. The old ghost loses it at the next changeover and is told.
- **Ask the board:** a tester gets a letter with the right count of circles, never more than eight, from the first word of the ghost's display name (a ghost called "Kate (Ollie's mom)" only ever gives K, A, T or E), and the same tester asking again that day is refused. The ghost asking gets Y-O-U.
- **Name the ghost:** picking yourself or a non-player doesn't use up the guess. A right guess gets YES and *Ghostbuster*. A wrong one gets NO. A second guess that day is refused. Before the ghost's first haunting of the day, Name the ghost gets the won't-budge line, and the tester can still guess after the ghost haunts.
- A ghost who haunts 3 times and isn't named earns *Boo Who?* at the changeover.
- On a day with no ghost, both buttons get the GOODBYE line.

## Not in this drop

- ***Overdue Returns***, the Story Bible's group achievement for filling the library with 200 things. It isn't in the files, and *Making a Mess* already covers 200 things in any room.
