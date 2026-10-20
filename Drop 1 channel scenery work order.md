# Drop 1 channel scenery work order

*Engine and content-file spec for giving the Halloween channel a description. The copy is final and lives in the Drop 1 channel scenery tab; nothing here restates it. Written to be run through Claude Code rather than read.*

## Scope

One capability, ten content rows, three loader checks. It gives the Halloween channel a `/look` description that arrives in two stages, which is the fix for the playtest finding that drop 1 felt empty — players got excited by `/look` and then found one thing to look at.

**This is a patch to drop 1, not a phase.** It can ship whenever there is room: after V3.2, inside it, or on its own. Nothing in V3.2 depends on it. But drop 1 is already live, so every week it waits is a week testers spend in a channel with one noun in it.

| In scope | Out |
| --- | --- |
| A `room_text` on the channel row, printed by `/look` | Scenery anywhere other than the channel |
| Room text as six fragments, three of them gated per player | The general per-player `present_when` — see section 2 |
| Ten `takeable = no` scenery rows with `look` text and aliases | Any `use` behavior, any relationship points |
| One new `defaults.tsv` key and one one-time private line | Engine-derived bolding — still workstream D |
| Three loader checks | The drop 2 and drop 3 fog steps — content changes, later |

**Nothing here touches the toy, the bed's mechanics, the ramp, the existing hint rungs or the meter.** The only existing behavior that changes is what `/look` prints in the channel.

## The one thing most likely to be built wrong

**Three of the six fragments are visible only after that player's first `/look cat bed`. That gate is a single boolean read against a table that already exists. It is not per-player `present_when`.**

The V3 implementation plan parks *per-player `present_when` across all content* as blocked on the onboarding-corridor design, and dates it V3.2. A developer who reads "per-player conditional content" will reasonably reach for that. Don't.

**What to read instead.** The hint rail already stores `(guild, player, hint_id)` — one row per hint shown — and the drop 1 ladder already records each player's first `/look cat bed`, because that is what retires `hint.look_specific` once they have done it. The gate is: *does this player have that row.* One lookup. No new table, no new column, no schema decision.

**Why this is worth being emphatic about.** The expensive wrong version is a general predicate evaluated per player against arbitrary content — a design programme with an open question attached, which would make a two-stage description cost the same as the whole onboarding corridor. The right version is an `if`.

**And it generalizes for free in the one direction this needs.** If a later drop wants a staged reveal keyed on some other action, that action is almost certainly already a hint trigger, so it is already a row in the same table.

## The fragment model

**Printed order follows key order, always.** An unlocked fragment slots into its numbered place in the paragraph; it is never appended to the end. That is load-bearing twice over: the scent is numbered 6 so it closes the paragraph at every stage, and the branches are numbered 2 so that when they unlock they land directly after the road rather than after the tire tracks.

| Key | Visible | What |
| --- | --- | --- |
| `channel.look.1` | always | the road and the fog |
| `channel.look.2` | after the bed look | the branches |
| `channel.look.3` | always | the fence |
| `channel.look.4` | after the bed look | the shape across the road |
| `channel.look.5` | after the bed look | the tire tracks |
| `channel.look.6` | always | the scent |

**Storage: six rows, not one cell.** Whatever table the room description lives in, the channel gets one row per fragment keyed as above, plus one nullable column expressing the gate — empty meaning always, and otherwise naming the single condition in section 2. That is one column with one value in use. **Do not build a condition language.** An enum with one member is the correct shape here; the second member can be added by whoever needs it.

**Fragments are added and never removed.** There is no state in which a fragment that has printed stops printing. Later staging works the same way: new fragments appear, existing ones stay true. The copy is written to that constraint, which is why nothing says *the fog has drawn back* — a description is re-read for weeks, and a change statement is a lie after the first time.

**Change gets announced once, separately.** The line telling a player something shifted is a one-time private message, specified in section 7, not a fragment.

## The channel room row

**Stop suppressing the description.** `/look` in the channel currently prints only the item list under `Items here:`, because the channel was settled as needing no `room_text` at all. **That decision is reversed.** The channel row gets a description and `/look` prints it above the item list, exactly as it does in a room.

**This retires a special case rather than adding one.** The suppression is the special case; removing it makes the channel behave like the room-like row it already is.

**The `look_prefix` override probably goes with it.** That column exists on the channel row to rename `Also here:` to `Items here:`, and it was chosen when the list was the entire output. With a description above it, normal room behavior is likely right. Check it against the rendered result and keep whichever reads better — but if `Items here:` stays, it should stay by choice rather than by inertia.

**One long-standing open question closes as a side effect.** *What fills `Items here:` when the channel is empty* has been on the open list since the schedule was first written. With a description above the list, an empty list is no longer a bare dangling header, so the answer can be *nothing*: omit the header when there is nothing under it.

**The channel still gets no exits and stays unreachable by movement.** It is never listed and never a `/go` destination. Nothing here changes that.

## 1. `things.tsv`

Ten new rows, identical except for four cells. The shared values:

`type = scenery` · `room_id = <CHANNEL>` · `quantity` 1 · `takeable` **no** · `droppable` no · `cross_weight` 1 · `max_per_player` blank · `requires`, `present_when`, `transforms_to`, `transform_room`, `yields`, `destination_room_id`, `contained_in` all blank · `use_cooldown_hours` blank · `since_drop` 1

**`scenery` is a new `type` value.** The copy deck declined to pick it and left it to this spec. Nothing may key behavior on an individual `thing_id` here — the class is what the loader checks and what any later outdoor scenery joins.

| `thing_id` | `name` | `aliases` | `sort_order` |
| --- | --- | --- | --- |
| `road` | road | `dirt road\|lane\|dirt` | 140 |
| `fog` | fog | `mist\|haze` | 141 |
| `branches` | branches | `branch\|limb\|limbs\|bough\|boughs\|tree\|trees\|canopy` | 142 |
| `fence` | fence | `wire\|wire fence\|fencing\|post\|posts\|fence post` | 143 |
| `ruts` | ruts | `rut\|wheel rut\|wheel ruts\|grooves` | 144 |
| `ditch` | ditch | `gutter\|trench\|culvert` | 145 |
| `leaves` | leaves | `leaf\|foliage` | 146 |
| `wasp_nest` | wasp nest | `nest\|wasps nest\|wasp's nest\|hornet nest\|hornets nest\|wasps\|hornets\|paper nest` | 147 |
| `field` | field | `pasture\|meadow\|empty field` | 148 |
| `tire_tracks` | tire tracks | `tracks\|track\|tire track\|tyre tracks\|wheel tracks\|tire marks\|mud` | 149 |

**`max_per_player` blank is correct here and 3b's loader check will not complain.** That check refuses on `type = toy` **and** `takeable = yes` **and** a blank `max_per_player`. Scenery is neither a toy nor takeable, so it is outside the check by design — worth knowing before someone "fixes" the check to be stricter.

### One known leak, and the decision to leave it

**Four rows sit at `since_drop = 1` while the fragment that names them is stage 2** — `branches`, `leaves`, `wasp_nest` and `tire_tracks`. So `/look branches` resolves for a player who has not looked at the bed yet, before anything on screen has mentioned a tree.

**Leave it.** Closing it means putting the same per-player gate on `things.tsv` rows as well as on fragments, which doubles the surface of the one new capability in order to hide four nouns that a player has to guess cold.

**One of the four is more guessable than the others, and that is the call to make.** `trees` is an alias on `branches`, and *trees* is a reasonable thing to type on a dirt road at dusk even with nothing prompting it. If that bothers anyone, the fix is to hold `tree` and `trees` out of the alias cell until drop 2 rather than to gate the row. The acceptance pass should treat all four as deliberate either way.

## 2. `thing_text.tsv`

**Eleven rows.** Ten `look` strings, one per scenery thing, all at state `default` and `since_drop` 1. Plus one `take_fail` override.

**Take the text from the copy deck, not from here.** It is in the Drop 1 channel scenery tab, section 5, and every row there is marked final. Retyping it into this spec would create a second source that drifts.

| `thing_id` | Key | Source |
| --- | --- | --- |
| `road`, `fog`, `branches`, `fence`, `ruts`, `ditch`, `leaves`, `wasp_nest`, `field`, `tire_tracks` | `look` | Copy deck section 5, all final |
| `wasp_nest` | `take_fail` | Copy deck section 8. **Not needed until `/take` ships in drop 2** — add it then, or now and leave it unreachable |

**The six fragments are not in this file.** They are room text, and they live wherever the channel's room description lives, one row per fragment — see section 3 above.

**None of the ten has `use` text, and none should.** They fall through to the new `use_fail.fixture` default in section 7. A scenery row that acquires a `use` success is a bug: the moment one pays out a relationship point, players farm whichever is cheapest and the bed's once-a-day economy stops meaning anything.

## 3. `defaults.tsv`

Two new keys. Text for both is in the copy deck, sections 7 and 6.

| Key | What | Note |
| --- | --- | --- |
| `use_fail.fixture` | `/use` on anything with `takeable = no` | **Needed because `use_fail.default` assumes a held object.** It reads *"You turn the {name} over in your hands…"*, which is nonsense on a fence or a ditch — and `/use` is one of only two verbs drop 1 has, so every scenery noun is one command away from producing it |
| `channel.fog_thins` | The one-time private line on a player's first `/look cat bed` | A new output shape — private, italic, **no `Hint:` prefix**, because it is not instructional. Nearest precedent is `bed_yield.public`, which is a public non-hint line |

### Three things about the notice

**It rides the `/look cat bed` reply, and the fuller description appears on the player's next `/look`.** Do not try to print the new description immediately. The sequence is: they look at the bed, they get the bed's text plus this line, and the next time they look at the channel there are six fragments instead of three. The line is what tells them to look again.

**It fires once per player and never again.** Same action that opens the gate, so whatever records the gate also suppresses the notice.

**It must not write anything to the hints-shown table.** It is not a hint and nothing keys off it. The only row that action writes is the one the hint ladder already writes for the first `/look cat bed`.

## 4. Bolding, and three loader checks

**Bolding is hand-authored in the text, not derived.** Engine-derived bolding is workstream D, needed for drop 3 and not built. The fragments and the `look` strings carry their own markers and the engine renders them like any other emphasis.

**It is load-bearing here rather than decorative.** Bolding is the only thing telling a player which nouns are lookable, and without it the scene has no boundary — if the ruts work, why not the gravel, the sky, the horizon. Hand-authoring is fine. Hand-authoring with no check is what drifts.

1. **Every bolded span resolves.** A bolded noun in channel text must match a `name` or an `alias` on a thing at or below the current drop. Catches a writer bolding a word with no row behind it — the player types the one noun the game just pointed at and gets a refusal.
2. **Every lookable channel thing is bolded somewhere.** The inverse, and it also catches the nesting chain breaking: trim *ruts* out of `road.look` and the `ruts` row becomes unreachable by any path, with nothing logged.
3. **No alias collides, checked against the whole things table.** Not just the channel. Nothing collides today, but drop 3 brings an outdoor Entryway, drop 5 a Courtyard, and the field may one day hold Christmas trees — at which point `tree` and `trees`, currently on `branches`, become ambiguous. A duplicate alias resolves to whichever row sorts first and logs nothing.

**Check 2 is the one that will fire during authoring**, and that is the point: it is the cheap version of the reachability guarantee the whole nesting model rests on.

## 5. QA

**Mostly inherited.** Two of these are already 3b requirements, which is worth knowing so nobody builds them twice.

| Need | New? |
| --- | --- |
| `/qa-reset-player` clears the hints-shown rows | **Already required by 3b** for the six-rung ladder. The same row gates stage 2, so the staging becomes re-testable for free |
| `/qa-spawn` places a scenery row | No — exists, and it is how to check a `look` string without waiting for a drop |
| Viewing the channel as a player who has and has not looked at the bed | New, but it is `/qa-reset-player` plus two commands rather than a tool |

Cases worth writing down:

1. **Stage 1 prints three fragments, stage 2 prints six**, with the scent last in both.
2. **The branches land in position two when they unlock**, not after the tire tracks. This is the case that catches an append-rather-than-insert implementation, and it is the most likely bug in the whole spec.
3. **`/look leaves` resolves in both stages, deliberately.** What must not happen is the word appearing in stage 1 *text* — see the known leak in section 1.
4. **`/use fence` returns `use_fail.fixture`**, not `use_fail.default`, and reads sensibly. Same for the ditch and the fog.
5. **`/look posts`, `/look mud` and `/look culvert`** resolve to the fence, the tracks and the ditch.
6. **The notice fires exactly once per player**, on the first `/look cat bed`, and fires again only after `/qa-reset-player`.
7. **The leak test.** No channel string names a room, a door, a drive, a mailbox, or any verb that does not exist yet.

## 6. Definition of done

1. `/look` in the channel prints a description above the item list, and the channel still has no exits and is still unreachable by movement.
2. A player who has never looked at the bed sees three fragments. After looking at it, their next `/look` shows six — branches in position two, scent last.
3. All ten scenery nouns resolve by `name` and by every alias, and `/use` on each returns `use_fail.fixture`.
4. The notice appears once on the first `/look cat bed`, and the fuller description on the `/look` after it.
5. The three loader checks pass on the shipped files and each one fails on a deliberately broken copy.
6. `/qa-reset-player` returns a tester to stage 1.
7. Nothing from drop 2 or later is reachable or named.
8. **No per-player `present_when` was built.** A negative requirement, and the one most worth checking at review.

## 7. Not in this spec

- **The drop 2 and drop 3 fog steps.** `since_drop` on fragments, content-only, no engine. The fog is the single lever behind every reveal in the pre-house phase and this release builds the mechanism it needs.
- **The mailbox.** Drop 2, and it is carrying a job beyond scenery — a name on it is the cheapest way to introduce David before any flavor text assumes him.
- **Engine-derived bolding.** Workstream D, needed for drop 3.
- **`wasp_nest.take_fail`** is written and unreachable until `/take` ships in drop 2. Add it whenever.

### Three copy loose ends, owned by the writers rather than by this spec

- The chosen `cat_bed.look` still needs copying into the POC copy deck section 4, where the superseded text is marked **locked**. The scenery deck is the source until someone does it.
- The POC deck still reads *"the only thing that says so is a private hint on each player's next message — no public line marks the change"* directly above the `drop.1.announce` row, which is marked locked and contradicts it. Anyone building drop 1 from that section gets it wrong.
- `channel.look.1` reads *"Dusk is closing in"* while its own notes cell still claims the clause fixes the scene at dusk permanently so no fragment ever needs a daytime variant. One of the two should give.

### The wasp nest, if it ever becomes obtainable

Parked 20 October, after a playtest in which testers were determined to get it. Worth keeping because that determination is an asset — a thing players fixated on in week one, delivered in week six, is the best kind of callback this game can make.

**The blocker is routing, not reach.** The channel is a room-like row with no exits, never listed and never a `/go` destination, and `/enter` is a one-way door into the house. A ladder in the Courtyard at drop 5 therefore cannot be brought to a nest hanging over the channel's road — there is no route back. Any ladder version of this needs the channel to become somewhere a player can return to, which is a feature with its own consequences: drops 0 to 2 content goes live again, `/go` gains a target outside the house, and the thread model gains a room it was built to exclude.

**The cheap version needs none of that.** A paper nest does not survive a winter. A later drop puts it on the ground — weather, or the cat, who is already the established agent for moving things into that channel — and it becomes takeable where it falls. One `things.tsv` row, one fragment, no route change, and it pays off for exactly the players who went after it.

**It needs a reason to want it.** Holding the nest has to amount to something, or the payoff is hollow after a two-month wait. An achievement is the cheapest answer and the one testers would talk about.

**One constraint on the copy, and it binds now rather than later.** `wasp_nest.take_fail` refuses on circumstance — *that seems unwise* — rather than on principle, and that is what keeps this option open. **Do not rewrite it into a refusal that forecloses the nest.** A line such as *there is no version of this where you end up holding it* would make the game a liar the day the nest comes down. Any future pass over these refusals should keep the no grounded in *not from here, not now* rather than *not ever*.

**The same rule already binds one other string.** `firewood_bin.take_fail` calls what is left in the bin rotten wood, no use for burning or for anything else, which deliberately stops players carrying splinters around looking for a fireplace. If any later drop wants firewood as a real item, that string is the first thing that has to change.

## 8. Addendum — the roadside stand (20 October)

*Playtest feedback after the scenery spec went out: a cat bed at the side of a road reads as odd. The testers asked for a shelter the player stands in, with the bed inside it. This addendum is the answer. It is additive to everything above — gating, resolution, the hint rail, bolding and QA are all unchanged — and it does not reissue the work order.*

### What it changes

- **Four new `things.tsv` rows**, same scenery defaults as section 1, taking the channel from ten lookable nouns to fourteen.
- **Four new `thing_text.tsv` look strings.** No new `use`, `take` or refusal strings; the `use_fail.fixture` default covers all four.
- **One existing fragment rewritten** (the opener) and **two new fragments**, one per stage.
- **The fragment keys renumbered to decades.** Mechanical, printed order unchanged.
- **One edit to `cat_bed.look`**, to put the bed in a corner of the stand.
- **Three aliases that point would-be traps at real answers.**

Nothing about `visible_when`, the hints-table read, `look_prefix`, the channel-as-a-room row or the acceptance cases changes.

### Why a stand rather than a shelter

The structure has to explain its own roof and its own open side, or it is just scenery with a player standing in it. A derelict produce stand explains both: the front is open because customers walked up to it, and the roof is good because produce needed keeping dry. It also sits **on the shoulder, outside the fence**, which is where the player already is — so `channel.look` fragments 3, 4 and 5 keep their geography exactly. A gazebo or any garden structure would put the player behind the sagging wire and make *across the road* point the wrong way.

It survives the earlier decision to drop the farm, and the distinction matters enough to record: what was rejected was a *stocked* farm — laden apple trees, a truck of pumpkins, a cornfield — which promised interaction it would not deliver. A stripped stand promises the opposite, and telling the player the farm is over is the thing that makes the farm safe to mention at all. It also leaves the Christmas tree farm option open rather than closing it.

**And the roof retires a problem.** The bed's dryness no longer needs explaining, because everything under a sound roof is dry. It had been leaning on `drop.1.announce`, a public line a late-joining player may never see.

### The renumber

The `fragment` column goes to decades so that every future insert is free. This is the second structural insert into this paragraph in a week, and both times the cost has been renumbering a column by hand and then checking for duplicates.

| Now | Becomes | Stage | Contents |
| --- | --- | --- | --- |
| `channel.look.1` | `channel.look.10` | 1 | the stand, the road, the fog, dusk — **rewritten** |
| — | `channel.look.20` | 1 | the shelves and the sign — **new** |
| — | `channel.look.30` | 2 | the firewood bin and the coin slot — **new** |
| `channel.look.2` | `channel.look.40` | 2 | branches, leaves, wasp nest |
| `channel.look.3` | `channel.look.50` | 1 | the fence |
| `channel.look.4` | `channel.look.60` | 2 | the shape across the road |
| `channel.look.5` | `channel.look.70` | 2 | tire tracks |
| `channel.look.6` | `channel.look.80` | 1 | the scent |

**The reading sweep is deliberate:** where you are, then the back wall, then the rest of the inside, then out and up, then the shoulder, then across the road, then the ground, then the smell closing the paragraph. Stage 1 reads 10, 20, 50, 80 — five sentences, still short. `channel.fog_thins` is unchanged.

### `things.tsv` — four new rows

Same column defaults as section 1: `type = scenery` · `room_id = CH` · `quantity` 1 · `takeable` **no** · `droppable` no · `cross_weight` 1 · `max_per_player` blank · everything from `requires` through `contained_in` blank · `use_cooldown_hours` blank · `since_drop` 1.

| `thing_id` | `name` | Named in |
| --- | --- | --- |
| `stand` | produce stand | fragment 10, stage 1 |
| `shelves` | shelves | fragment 20, stage 1 |
| `firewood_bin` | firewood bin | fragment 30, stage 2 |
| `coin_slot` | coin slot | fragment 30, stage 2 |

**Two of these inherit the known inconsistency from section 1.** `firewood_bin` and `coin_slot` sit at `since_drop = 1` while the fragment that names them is stage 2, so `/look bin` resolves before any prose has mentioned a bin — exactly as `branches`, `leaves`, `wasp_nest` and `tire_tracks` already do. Leave it, for the same reason: closing it means per-player gating on `things.tsv` rows as well as on fragments, and a player who guesses a noun early has earned the answer.

### `thing_text.tsv` — four new look strings

All four at `state = default`, `since_drop` 1.

| Key | Text |
| --- | --- |
| `stand.look` | Bare planks gone silver with weather, a tin roof that still holds, and a waist-high counter worn pale along the edge where people leaned to pay. Nobody has stocked it in a long time, and nobody has pulled it down either. |
| `shelves.look` | Four shelves of unfinished board along the back wall, swept almost clean, a little chaff and dried stem left in the corners. The sign above them lists what they used to hold, in letters faded to the same color as the wood. |
| `firewood_bin.look` | A plank bin, gray inside and out, FIREWOOD stenciled on the front in the same hand as the sign. A few splinters are left in the bottom, too light now to burn well, and a drift of bark dust under them. |
| `coin_slot.look` | A slot the width of a folded bill, cut through the counter and worn smooth on the underside. Looking from below, you see a rectangle of pale wood the size of a shoebox, four bolt holes at the corners, and no box. Whatever was collected here was collected a while ago. |

**No `use`, `take` or refusal strings.** All four are fixtures and fall to the `use_fail.fixture` default from section 3.

**There is no bench in the stand, and that is deliberate.** A bench is what a waiting shelter would have had, and it would have made `/sit` the obvious thing for a player to type — a verb that does not exist and never will. A counter is leaned on, not sat on. The stand gets the premise a bench would have given it without the trap.

### The fragment copy

**The fragment copy lives in the copy deck**, in its Stage 1 and Stage 2 tables alongside the other six, with the decade keys applied: `channel.look.10` and `.20` in Stage 1, `.30` in Stage 2. Edit the text there — this work order carries the row specs, the gating, the aliases and the refusals.

blueberries

*Past the opening* places the viewpoint inside the stand without resorting to "you are," which would break voice with the house's room text.

**One finding for section 4, and it is the only thing here that touches the bolding rule.** Three of these nouns are named in prose by an *alias* rather than by their row's `name`: **sign** resolves to `shelves`, **bin** to `firewood_bin`, **slot** to `coin_slot`. The channel has had no case of this until now, so the engine-derived bolding has to match against aliases as well as names, or those three words resolve under `/look` while printing unbolded — which is precisely the mismatch section 4 exists to prevent. Worth re-running check 2 against aliases before this ships.

### `cat_bed.look`

The bed moves into the corner where the cooler stood. Built on the chosen text as it read on 19 October:

> A round cushion in dark green corduroy, flattened in the middle where something has slept, sitting in the corner on a clean rectangle of boards where a cooler used to stand. It has not been here long. This is the sort of bed that looks plumpable.

**Apply the clause, not the paragraph.** The copy deck has been edited since, so take whatever `cat_bed.look` now reads and add the corner to it, keeping *plumpable* and *where something has slept*, both of which the deck records as load-bearing.

**The sign over the shelves listing brown eggs and the clean rectangle in the corner are one fact told twice**, from two angles, with nothing spelling out the connection. That is why there is no second sign labeling the cooler's old spot.

### Aliases

| `thing_id` | `aliases` |
| --- | --- |
| `stand` | produce stand\|farm stand\|farmstand\|roadside stand\|fruit stand\|vegetable stand\|stall\|counter\|roof\|tin roof\|planks |
| `shelves` | shelf\|sign\|board\|produce\|sweet corn\|corn\|blueberries\|blueberry\|eggs\|brown eggs |
| `firewood_bin` | bin\|plank bin\|wood bin\|woodbin\|firewood\|wood\|splits |
| `coin_slot` | slot\|coin slot\|cash box\|cashbox\|money box\|honor box\|honesty box\|box\|cash\|money |

**Three of these turn a trap into an answer**, which is the whole reason the alias list is longer than the noun list:

- `cash box`, `money box`, `honor box` → `coin_slot`. A player who types `/look cash box` is told the box is gone, which is a real answer rather than *whatever that is, this house doesn't have one.*
- `sweet corn`, `corn`, `strawberries`, `eggs`, `produce` → `shelves`. Fragment 20 names four things that exist as no object; all four now resolve to the empty shelves they were named on.
- `cooler`, `icebox`, `egg cooler` → **`cat_bed`**, added to the bed's own alias cell. The bed sits on the cooler's footprint and its look explains the absence, so a player asking about the cooler reads the one description drop 1 most wants them to read. That is a free rung on the hint ladder.

**Two things to check against section 1's collision pass.** `sign` can belong to only one row and goes to `shelves`, the more prominent of the two signs — so the slot's faded line is reachable as `slot`, `cash box` and the rest, but not as `sign`. And the `cooler` alias on `cat_bed` is the first alias in the channel pointing at something that is not a `type = scenery` row; confirm the resolver does not filter alias lookups by type.

### What is deliberately not in the stand

Recorded so nobody adds it back later.

- **No lock, and no cash box.** A lock is a puzzle promise and drop 1 has no verb that could solve one. A sign instructing the player to put money in asks for an action with no money and no `/put`. And drop 2 drops a **brass key** into this same channel — a locked box in drop 1 and a key in drop 2, in one place, is an inference the game can never honor.
- **No cooler as an object.** A cooler is a container, containers invite opening, `/open` does not exist and `contained_in` does. Its footprint carries the same information and cannot be interacted with.
- **No produce on the shelves.** Anything stocked is something to take, and `/take` arrives one drop later.
- **No bench**, per the note above.

### Open

- **The splits in the firewood bin — present or absent?** Written above as present and gray, which gives the bin something to be and gives the cat a reason to sleep beside it. Absent is more consistent with the stripped stand. Either works; one sentence changes.
- **`fog.look` and `road.look` were written for a player standing in the open.** Both should be read again now that the player is under a roof looking out through one side. `fog.look` in particular carries a *thickest* clause the deck already flagged once.
- **The tin roof is a vertical element in stage 1**, which brushes against the standing decision that stage 1 needs no vertical dimension. The roof is an enclosure overhead rather than a sightline through fog, and it is now the physical reason the canopy is not visible until the player has reason to look out — which turns that decision from a judgment call into a fact about the scene. Flagged rather than assumed.

### Refusals — every no needs a fact

*Playtesters tried `/take` and `/use` on everything in the scene, and were especially determined to get the wasp nest. This subsection supersedes the line above saying the four stand rows carry no refusal strings — they do now, and so do four nouns from the original ten.*

**`takeable = no` is not a design answer on its own.** It stops the player; it does not tell them why, so they try again. The rule this set follows: **a refusal is grounded in a fact about the world, never in the player's preference.** *You decide against it* reads as a soft no, and a determined player hears a soft no as a problem to solve.

**That is exactly why the wasp nest held out.** Its current `take_fail` — *"It is twenty feet up and full of whatever a wasp colony leaves behind. You decide against it"* — opens with a fact and then hands the decision back. The deck also notes that `wasp_nest.look` ends on its own refusal "so the player never needs to be told no." **The playtest is the evidence that this does not work:** a no embedded in a description does not read as a no, it reads as a description of a challenge. The explicit refusal has to carry the whole weight, and it has to be complete — answering every follow-up the player already had in mind, so there is nothing left to try. That is why the nest gets the longest string in the scene. A short refusal invites a second attempt; a complete one ends the conversation.

| `thing_id` | `take_fail` | `use_fail` |
| --- | --- | --- |
| `wasp_nest` | That seems unwise. It is twenty feet up and full of whatever a wasp colony leaves behind. | You are twenty feet below it and it has been dead since the first frost. Looking at it is the whole of it. |
| `stand` | It is a building, in the loosest sense of the word, and it is staying where it is. | You stand at the counter a moment, like a customer. Nothing is for sale, and there is nobody to sell it. |
| `shelves` | Four boards and a dozen nails, and whoever put them up meant them to stay. | You run a hand along a shelf. Chaff, dust, and a long time since anything sat here. |
| `firewood_bin` | The bin is bolted down, and what is left in it is rotten splinters — grey, light as balsa, no use for burning or for anything else. | You reach into the bin for a splinter, but it crumbles in your fingers. |
| `coin_slot` | The slot is a hole in a plank. The box it fed is four bolt holes and a clean rectangle, and whatever went through it is long gone. | You put a finger in the slot, which is exactly as rewarding as it sounds. There is nothing behind it any more. |
| `branches` | They are attached to trees. Good luck with that. | They are out of reach by a comfortable margin. Whatever is going on up there is going on without you. |
| `leaves` | The ones worth having are still on the branches, well over your head. The ones on the ground are brown and stuck down. | You stand and listen for a moment to the sound of rustling leaves. |
| `fence` | Four strands of wire and a line of posts, most of a field long. You are not carrying that anywhere. | You test a strand and it gives more than it should, which is what happens to wire nobody tightens. It is still a fence. |

**Each `use_fail` ends by pointing at the one verb that works**, explicitly or by implication, which satisfies the standing constraint that a refusal may redirect only where a verb actually applies. `/look` always applies. `/take`, `/go` and `/drop` are named nowhere in this set.

### One new default, for the six that are not objects at all

`take_fail.fixture` reads *"The {name} isn't yours to carry off,"* which is right for a built thing somebody owns and nonsense for weather. Add one key:

> `take_fail.terrain` — You would have to take the whole place with it.

It covers `road`, `fog`, `ruts`, `ditch`, `field` and `tire_tracks` in one line, because those six share one joke, and it is reusable in the house — the courtyard and the oak will want it. Their `use_fail` stays the proposed `use_fail.fixture` from section 3, which reads correctly on all six.

### Four things to watch

**`/take` is drop 2, `/use` is drop 1.** The eight `use_fail` strings are needed for the first drop; the eight `take_fail` strings and `take_fail.terrain` are not reachable until drop 2 and can ship with it. Nothing breaks if they land early.

**The firewood forecloses a later use, on purpose.** Rotten wood is no use for burning, which is what stops a player carrying splits around looking for a fireplace. If any later drop wants firewood as a real item, this string is the thing that has to change first.

**The bin and the counter are in the same scene as something out of reach.** Testers who want the nest will try standing on things. No string should acknowledge that, and the nest's refusal is written to foreclose the whole category rather than name a method — *it would come down in pieces* answers knocking it down without ever mentioning throwing anything.

**The fence refusal must not hint at a future.** The field behind it is reserved content, so *it is still a fence* is doing deliberate work: a sagging wire fence invites crossing, `/go` arrives in drop 3, and anything warmer than a flat close would read as a promise.
