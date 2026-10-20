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
