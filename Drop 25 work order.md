# Drop 25 work order — the Dining Room and the Kitchen

*31 October. Splits drop 30's four rooms into two halves so the ground
floor can be playtested in two sittings. Verified against the files and
against a running server before being written down; what was measured is
marked as measured.*

**The shape.** The Dining Room and the Kitchen, everything in them, the
arched doorway from the Entryway and the swinging door between them, move
to a new drop 25. The Courtyard and the Living Room stay at 30, and so do
the two doors that reach them: the Kitchen's **back door** and the
Entryway's **wide doorway**. Drop 25 opens two rooms with one way in and
one way between, and no way out of the Kitchen except back through the
Dining Room.

**Nothing to migrate.** `arrived` is `{d <= pointer}`, so a server already
on drop 30 has drop 25 the moment the file defines it. `when_drop_arrived`
answers "or past it", so a restock written for 25 would date from the day
that server reached 30. `place_arrived` is judged per thing and skips what
a server already has. `clear_unreachable_room_contents` only ever deletes
what has *not* arrived, and this change only moves things earlier. The
live beta notices one thing, and it is in the Entryway — see **The
fragment numbers** below.

---

## 1. `drops.tsv` — one new row

| drop_id | trigger | name | notes |
| --- | --- | --- | --- |
| 25 | manual | **Through the Arch** | The Dining Room and the Kitchen and everything in them, the arched doorway from the Entryway and the swinging door between them, the can opener, two more cat-food flavors. Deliberately not the back door. |

**Drop 30 keeps the name "The Ground Floor".** Not sentiment:
`test_the_ground_floor.test_the_ceiling_reaches_the_ground_floor` finds
the drop *by that name* and asserts the ceiling reaches it, deliberately
so the number in the test cannot agree with itself while disagreeing with
the content. Moving the name to 25 would quietly point that guard at the
wrong half. Drop 30's notes get rewritten to say what is left of it: the
Courtyard, the Living Room, the wide doorway, the back door, the chicken
cat food, and the bottle and diaper scatter.

`LAST_PLAYABLE_DROP` stays at 30. `next_drop_after(20)` becomes 25, which
is what `/advance-game` already handles — it asks the files for the next
drop rather than adding one, and has since the 26 October renumbering.
Nothing in `gating.PLAYER_COMMANDS` is added: drop 25 brings no new verb,
and the table says so by saying nothing, the same way drop 3 does.

## 2. The rows that move

Measured on the probe: **36 things, 36 `thing_text` rows, 8 achievements,
2 new room-text rows.**

| File | What moves to 25 |
| --- | --- |
| `things.tsv` | every row with `room_id` DI or KI **except `KC`**; `ED` (the arch, in EN); and the six objects the moved sources hand out |
| `thing_text.tsv` | one row per moved thing — all 36 have exactly one, at drop 30 today |
| `achievements.tsv` | `brewing_trouble`, `trash_panda`, `bin_looking_for_you`, `nacho_average_ghost`, `clean_plate_club`, `breaking_into_the_halloween_candy`, `curbside_pickup`, `not_so_picky_eater` |
| `room_text.tsv` | DI fragment 0; KI fragment 0, trimmed; and the Entryway's doorways, below |

**The six yields move because a source and its yield are one thing.**
`reach` files a source under what it hands out and applies the visibility
filter to the *source's* id, so a sideboard cupboard at 25 whose tuna
waits for 30 would hand players a can from a drop the server has not
reached, named and described out of rows nobody has unlocked. The six:
`candy`, `nacho_chips`, `frozen_burrito`, `cat_food_tuna`,
`cat_food_gourmet`, `can_opener`.

**`cat_food_chicken` does not move**, and it is the one that looks like it
should. It comes from the Living Room sofa and the Bedroom, so it stays at
30; the tuna and the gourmet are the two flavors drop 25 brings.

## 3. What stays at 30, and why each one does

| Row | Why |
| --- | --- |
| `KC`, `CK` — the back door, both ends | the Courtyard. This is the whole point of the split |
| `EL`, `LE` — the wide doorway | the Living Room |
| `somethings_cooking` | the stove arrives at 25; two of its three ingredients are the Courtyard's herbs and the Living Room's chocolate |
| `green_thumb` | the herb garden |
| `hive_five`, `board_meeting` | the road's wasp nest and the Entryway's staircase |

**The bottles came back out of this table on 31 October.** They were
listed here, with `catproof_the_house`, on the reasoning that the Kitchen
sink arrives at 25 with nothing to wash until the scatter starts at 30 -
and the answer was to move the scatter instead. `used_baby_bottle`,
`sanitized_baby_bottle`, their text rows and the `restocks.tsv` row that
makes them exist at all are at 25, so the sink has work from the day the
arch opens, and `catproof_the_house` follows them because its trigger is
only *hold five at once, clean or dirty* - nothing in it waits on the cat,
whatever the name and the artwork suggest. Three files, because a roomless
thing with `quantity = 0` arrives and never appears unless its restock row
moves with it.

**Three fixtures arrive at 25 with nothing to do, and all three read
correctly.** Checked, because this was the one place I expected to have to
write new copy. No refusal in the game names the thing you are missing:
a `requires` failure sends the thing's own `use_fail` with `{name}` filled
and nothing else, and `missing_requirements`' ordered answer is used only
to decide *which* refusal a feed gets. So the stove says *"Whatever you
were planning to cook, you don't have all of it yet"* and the pasta pot
says *"you have nothing to put in it"* — both about the player's hands
rather than about the house's inventory. The pasta pot has been doing
exactly this since drop 30 shipped, parked on pasta that does not exist.
**No new text rows needed.**

## 4. The prose

### The Kitchen: the back door becomes fragment 1

Fragment 0 loses its last clause and moves to 25. The clause becomes
fragment 1 at drop 30.

| # | Drop | Text |
| --- | --- | --- |
| 0 | **25** | A big old-fashioned kitchen. A pasta pot sits on the cast-iron stove, a drying rack stands empty by the kitchen sink, and a Keurig waits with a clean mug. The fridge-freezer hums beside the trash can, a cake box sits at the end of the counter, and the pantry door is ajar. A swinging door shows a sliver of a long table each time it moves. |
| 1 | **30** | Through the glazed back door there are steps, then tangled green. |

This is free: the back-door clause is already the **last** thing in the
paragraph, so splitting it off changes no reading order and needs no
renumbering. It also answers the *Room text rewrite* tab's own open
question — *one paragraph or fragments?* — for one room, in the direction
the Entryway already went.

The Kitchen keeps every source named in an arrived fragment: `burritos` is
free-standing and named in fragment 0 by its `fridge-freezer` alias, and
the pantry's two are named in the pantry's own look.

### The Entryway: the doorways become two fragments

The approved sentence is one clause pair in the **middle** of the
paragraph, so this one is not free. The arch takes fragment 6 at drop 25,
the wide doorway becomes fragment 7 at drop 30, and the staircase's three
state rows move from 7 to 8.

| # | Drop | Gated | Text |
| --- | --- | --- | --- |
| 6 | **25** | `fed_the_cat` | An arched doorway opens on one side of the hall. |
| 7 | **30** | `fed_the_cat` | A wide doorway opens on the other. |
| 8 | 20 | `fed_the_cat` | *the staircase, all three state rows, unchanged* |

Both halves keep the `fed_the_cat` gate, which the 26 October decision put
on fragment 6 and on `ED`/`EL` themselves. A player who has not fed the
cat still reads 28 words and meets one room, and drop 25 does not change
that.

### The fragment numbers, and the one thing the beta will notice

`_describe_room` keys "new to you" on `seen.{room}.{fragment}`, a row per
player per fragment. Renumbering the staircase 7 → 8 orphans every
`seen.EN.7`, so on the next `/look` after this ships, a beta player sees
the staircase sentence **and** the new wide-doorway sentence in italics,
once. That is the cost, and it buys the reveal: the wide doorway is a new
way out of the Entryway and the player should see that it arrived.

**The alternative, for the record.** `_best` picks the highest arrived
drop *within* a fragment, so fragment 6 could instead carry two rows — the
arch at 25 and the writers' approved both-doorways sentence at 30 —
superseding rather than splitting. That renumbers nothing and keeps the
approved text verbatim. It costs the italics instead: the fragment number
does not change, so the second doorway arrives unmarked. That is the
limitation `_describe_room`'s own docstring already admits about
state-varying text, and the Entryway's doorways are the first content that
would hit it on a drop boundary. **Recommending the split**, because a new
exit is the one thing in a room a player must not miss — but this is a
call worth making deliberately rather than inheriting.

## 5. Three checks to add first

The existing checker passes the finished proposal — and passes all three
ways of getting it wrong. Measured: each break below leaves
`content.validate` at **0 problems**. All three checks are also clean
against the files as they stand today, so they can land in their own
commit *before* the content moves, where they guard the move rather than
describe it.

| Check | What it catches | Measured |
| --- | --- | --- |
| **Nothing arrives before its prose.** A thing's `since_drop` may not be below the drop of its default `look` row. | `_check_text_coverage` asks whether a default row exists, never which drop it is written for. A thing moved forward without its text falls back to `_look_at`'s `You see {name}.` — the writers' sentence replaced by the thing's own name. | Leaving the stove's text at 30: *"thing stove arrives at drop 25 but its look text waits for drop 30"* |
| **A source arrives with what it hands out.** | `reach` files a source under its yield and filters on the source's id, so the yield leaks into play unarrived. | Leaving the tuna at 30: *"source cat_food_stash_sideboard arrives at drop 25 and hands out cat_food_tuna, which waits for drop 30"* |
| **Every arrived room is reachable at every drop**, walking from the road through arrived exits only. | `_check_reachable_rooms` builds one graph from every exit in the files and walks the finished house. A room that opens a drop before the only door into it is reachable there and stranded in play: prose resolves, thread exists, nobody can walk to it. | Leaving the arch at 30: *"at drop 25, room DI has arrived but cannot be reached"* — and KI with it |

The third one has a trap worth writing into its docstring: the start is
**the road, not the first `open_at_launch` room**. Starting from the
Entryway asks whether the road can be reached from inside a house that
does not exist yet, and reports drops 0 to 3 as broken. `arrived_rooms`'
callers already treat the channel as valid everywhere for this reason.

## 6. Tests

**Measured on the probe: the full suite is 2515 passed, 2 failed, and both
failures are the same assertion.**

| Test | Change |
| --- | --- |
| `test_content.test_the_shipped_content_parses` | `len(c.drops) == 9` → 10 |
| `test_loader.test_the_shipped_content_loads` | `content_rows["drops"] == 9` → 10 |

Nothing else moves, because almost every test sits at `LAST_DROP = 50` and
a drop inserted below the ceiling is invisible from up there.

**Three that pass and should not be left as they are.**

- `test_the_ground_floor.test_the_four_rooms_are_open_at_this_drop` asks
  `resolve.all_rooms()`, which reads `rooms.tsv` and knows nothing about
  drops — so it passes at drop 0, and it would pass if this change opened
  the Dining Room with no door into it. Its docstring says *"a drop whose
  rooms do not load is a drop that opened on nothing"*, which is the right
  question asked of the wrong function. It wants `arrived_rooms`, split:
  DI and KI at 25, CO and LI at 30. Worth fixing *because of* this change
  rather than merely updating for it.
- `test_marking.test_a_house_room_is_never_marked` opens *"Nine rooms have
  one fragment each and nothing ever adds to them"*. The Entryway already
  had seven; the Kitchen is about to have two. The test is fine — it looks
  twice and compares — but the premise in the docstring stops being true.
- `test_feeding.test_what_decides_is_the_room_and_not_a_drop_number`
  predicted this change in its own docstring: *"a writer who ... pushes the
  doorways back to 30 changes when this line is true, and nothing in the
  code has to be found and edited to match."* It passes untouched. Worth
  reading as the design already having been thought about.

New tests to write, one per decision this work order makes: the Kitchen
reads without the back door at 25 and with it at 30; `/go courtyard` and
`/go back door` in the Kitchen are not found at 25 and are the back door
at 30; `/go living room` in the Entryway is not found at 25; the Dining
Room and the Kitchen are reachable at 25 and the Courtyard and the Living
Room are not; the tuna and the gourmet can be had at 25 and the chicken
cannot.

## 7. How to make the edits

**Patch the cells in place; do not round-trip the files through `csv`.**
Learned on the probe: a `DictWriter` pass rewrote the board books' look
text, wrapping the cell and doubling the quotes around *"For Marcus, June
2026"*. The reader is indifferent and the diff is not — it put the
writers' approved copy in a content diff that has nothing to do with drop
25. Use the project's `sub(path, old, new, count=1)` idiom with an
asserted count, and keep the diff to the `since_drop` column and the four
prose rows.

All five files are CRLF. Read with `newline=None`, write with
`newline="\r\n"`, and check the counts afterwards.

## 8. Docs that go stale

- `creative content/drops.tsv` — both the 25 and 30 notes, above
- `creative content/drop-unlock-schedule.md` — its table has no drop 25
- `Room text rewrite (drops 30–50).md` — the Kitchen draft becomes two
  fragments, and its closing open question is answered for one room
- `Entryway fragmentation (drops 10-30).md` — its table of seven fragments
  becomes eight, and fragment 6's row splits in two
- `STORY_BIBLE.md` — wherever it lists what opens with the ground floor

## 9. Two things players get for free

**`/go doorway` in the Entryway stops being ambiguous at 25.** `ED` and
`EL` both answer to `doorway`, so today the word raises the ambiguity
prompt. With only the arch open it means the arch. It goes back to
ambiguous at 30, exactly as it is now.

**The diaper scatter starts reaching the Kitchen at 25.** `restocking`
asks `arrived_rooms` for its slots, so the two new rooms join the scatter
the moment they open, with no row to change — which is also what
`bin_looking_for_you` needs to be earnable at 25.

## 10. Answered: drop 25 posts nothing when it opens

Only `drop.1.announce` exists, and `/advance-game` tells the admin
*"nothing posted; drop N has no announcement line"*. That is already true
of 20 and 30, and **approved as-is on 31 October** — the ground floor
arriving in two halves does not need two announcements. No `defaults`
row, and nothing in the code to change.

## 11. Built 31 October

Shipped as two pull requests, the checks first so that they guarded the
move rather than describing it. Everything above held except two things,
both found by building it:

- **`/go living room` in the Entryway went through the arch.** `living
  room` is two edits from `dining room` and the forgiving pass runs over
  the candidates, so with the wide doorway not yet arrived a player who
  had spelled the room correctly was walked through the other doorway
  without a word about it. The rule in `reach.find` — a word somebody
  spelled correctly can never lose to somebody else's near miss — held
  only inside the candidate set, and now holds against the room too: a
  word naming a thing in this room that this player cannot see yet, by
  drop or by gate, is refused rather than corrected. Drop 25 surfaced it
  rather than causing it; both doorways sit behind `fed_the_cat`, so an
  unfed player has been able to hit it since drop 10.
- **The fragment numbers are 1 to 8, not 0 to 7.** The Entryway's rows
  start at 1. The split and the renumbering are as described; only the
  labels in section 4 were off by one.

Section 6's prediction held exactly: **2544 passed, nothing failed**, and
the only two pre-existing tests that needed a number changed were the two
counting the drops.
