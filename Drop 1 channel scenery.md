# Drop 1 channel scenery

*Copy deck for the Halloween channel's `/look` description and the detail nested under it. It supersedes section 5 of the POC copy deck, which was written when the channel had no description at all. Conventions are the ones already settled in the other two decks and are not restated here.*

**Superseded in part, 20 October.** Playtesters found the cat bed odd at a bare roadside, so the player now stands in a derelict roadside produce stand with the bed in a corner of it. Four nouns are added, the opening fragment is rewritten, two fragments are new, the fragment keys renumber to decades, and `cat_bed.look` takes a clause about the corner. **The copy and rows for all of that live in section 8 of the Drop 1 channel scenery work order** — work from there for the opener, and from this deck for everything outward of the stand, which is unchanged.

## Why this exists

Playtesters came out of drop 1 saying it felt empty, and they were precise about it: they got excited by `/look` and then found there was only the bed to look at. The hint promises a category — *"Specific things can be looked at"* — and the channel delivered one member of it.

Three decisions caused it, each defensible alone. `/look` in the channel printed a bare item list, because we settled that the channel needed no description. The bulk edit moving every existing row to `since_drop = 3` kept drop 3 from leaking and left the channel holding the bed and nothing else. And the cat is deliberately kept out of the list, so the one presence in the channel is invisible to the guided path.

**Two of those are now reversed and one is not.** The channel gets a description, and the description gets detail nested under it. **The cat stays an easter egg** — she appears nowhere in this deck, `/look cat` remains for anyone who thinks to try it, and the guided path still points only at the bed and later the toy.

An earlier draft of this scene put a farm on one side of the road: apple trees, a cornfield, a truck piled with pumpkins, a mailbox. It was warmer, and it was full of traps — nearly every noun invited an action the player has no verb for, and it implied the farm mattered when it does not. What is here instead is chosen so that the player's own sense of each thing supplies the reason not to touch it.

## The trap test

Every noun in this scene has to pass one question: **would a reasonable person's next thought be an action?** If it would, the noun is a trap, because drop 1 has only `/look` and `/use`. `/take` is a drop away and `/go` is two.

Three things make a noun safe, and the best ones are more than one at once:

- **Out of reach.** Twenty feet up, or across a field. Distance supplies the refusal before the player types anything.
- **Nothing to do with it in life either.** Fog, cold, a sound. Nobody's instinct is to manipulate fog.
- **Already finished.** Ruts worn in over several wet seasons, leaves that came down weeks ago, a nest whose colony is dead. There is nothing left to do to it.

The wasp nest is the model, and it is the reason this approach works: it is high up, it is dead, and nobody wants to handle one even at ground level.

**The category to watch is containers and openables**, because they are the most evocative things to write and the hardest to leave alone. A mailbox, a gate, a cellar door, a jar on a post. Each is a promise of an interaction, and drops 1 and 2 have nothing to pay it with. The fence below is described as having no gate in the visible stretch on purpose — one clause, and it saves a playtest round.

**Two things here are atmosphere rather than targets**, deliberately unbolded: the smell of the cold, and the sound of water in the ditch. `/look smell` is a worse experience than no smell at all.

## The noun tree at a glance

| Noun | Level | Named in | Visible | Status |
| --- | --- | --- | --- | --- |
| cat bed | item list | the list under the description | stage 1 | revised from POC deck |
| road | top | the top-level look | stage 1 | final |
| fog | top | the top-level look | stage 1 | final |
| branches | top | the top-level look | stage 2 | final |
| fence | top | the top-level look | stage 1 | final |
| ruts | nested | inside `road` | stage 1 | final |
| ditch | nested | inside `road` | stage 1 | final |
| leaves | nested | inside `branches` | stage 2 | final |
| wasp nest | nested | inside `branches` | stage 2 | final |
| field | nested | inside `fence` | stage 1 | final |
| tire tracks | top | the top-level look | stage 2 | final |

**Eleven targets, seven in stage 1 and four unlocked by the first look at the bed.** A noun named inside another noun's description needs no gating, no per-player state and no engine — it is simply there for whoever reads far enough. That is why the nest lives inside `branches` rather than in the top-level look: free, and it rewards the exact habit drop 3 depends on. Only the three stage-2 fragments need a condition, and the two nouns nested inside the branches ride along at no extra cost.

**Every row here is `takeable = no` with no `use` text, permanently.** Nothing in this scene carries a mechanic or a relationship point. The moment one of them pays out, players farm whichever is cheapest and the bed's once-a-day economy stops meaning anything.

## Stage 1 — the top-level look

Three short sentences in three fragments, with the item list under them. Printed order follows the keys, and both tables are kept in key order to match, so the scent closes the paragraph at every stage. The branches line has moved to stage 2 — see section 6. Short on purpose: `/look` is the most re-read output in the game, and a paragraph gets skimmed by the third time a player types it.

| Key | Text | Notes |
| --- | --- | --- |
| `channel.look.10` | A derelict produce **stand** sits at the edge of a dirt **road**, open along the side that faces it and roofed in tin. Past the opening the road runs pale and rutted into the **fog**, and dusk is closing in. | Three targets. Rewritten 20 October for the roadside stand. The dusk clause still fixes the scene permanently, so no fragment ever needs a daytime variant, and *past the opening* places the viewpoint inside the stand without resorting to "you are" |
| `channel.look.20` | Empty **shelves** line the back, and a hand-lettered **sign** over them still offers sweet corn, blueberries, brown eggs, in paint gone the color of the wood behind it. | New, 20 October. Two targets, one of them named by alias — sign resolves to shelves, which is the case the bolding check has to cover |
| `channel.look.50` | Along one shoulder a **fence** sags, four strands of wire on posts leaning in whatever direction they settled. | The gate clause lives in the fence's own text rather than here, to keep this fragment one sentence |
| `channel.look.80` | The air smells of cold and wet earth. | Atmosphere. No target — see the trap test |

Then, unchanged in shape: `Items here:` and the cat bed.

**Each fragment has to read correctly with any of its neighbors missing, and none of them may reach backwards.** That is the existing fragment rule and it bites here, because the obvious way to write stage 2 is *"the fog has drawn back a little"* — which is a lie the twentieth time a player looks. Fragments describe state; change gets announced once, elsewhere. Section 6 handles that.

**Bold the first occurrence of a noun only.** "Fog" appears in three fragments and is bolded in one. Bolding every instance reads as emphasis rather than as an affordance, and it is what the engine-derived version will do when it arrives.

## The nested look text

One string per noun. Each one names the nouns on the level below it, which is the only thing making those reachable — there is no index of lookable things, so a noun that nothing mentions does not exist.

| Key | Text | Names |
| --- | --- | --- |
| `road.look` | Dirt, graded a long time ago and not since. **Ruts** run the length of it where water has taken the same path more than once, and the **ditch** on either side has filled with leaves nobody is going to clear. | ruts, ditch |
| `ruts.look` | Dried hard, and deep enough to turn an ankle. They have been here through several wet seasons, which is how they got that deep. | — |
| `ditch.look` | Shallow, choked with leaves a week past their color and gone to brown mush, with a thin trickle of water somewhere underneath that you can hear and cannot see. | — |
| `fog.look` | It lies low and even, the way it does when the ground is still warm and the air above it is not. It completely obscures the road about thirty feet out, and it is thickest on the far side, where it keeps a shape it does not explain. | — |
| `branches.look` | They come out over the road from both sides and nearly touch above the middle of it. The **leaves** still on them are scarlet and orange and thinning, enough gone that the branches show through. Higher, where two limbs cross, a grey papery **wasp nest** hangs, about the size of a football. | leaves, wasp nest |
| `leaves.look` | Scarlet and orange, a few still stubbornly green near the trunk, and bright enough to be startling this close to dark. There are fewer of them than there were. Now and then one lets go and takes a long time to reach the road. | — |
| `wasp_nest.look` | Grey and layered, built out of something like chewed paper, torn open on one side by a bird or by weather. Whatever lived in it is finished for the year. It is also a good twenty feet up. | — |
| `fence.look` | Four strands of wire on posts that have mostly given up, sagging between them in long shallow curves. It runs as far as the fog lets you follow it, and there is no gate in any of that. Past it the ground opens into a **field**. | field |
| `field.look` | Flat, open, and giving up nothing. Whatever is grown there is not being grown now. | — |

**Three of these are doing work beyond description.** `fog.look` carries the only hint that anything is across the road, which is why it matters that fog is one of the two nouns bolded in the first fragment. `wasp_nest.look` ends on its own refusal, so the player never needs to be told no. And `field.look` is written to stay true if that field is ever a Christmas tree farm — same fence, same fog, one new fragment behind it.

**The chain is load-bearing, so the loader should check it.** If a writer trims *ruts* out of `road.look`, the `ruts` row stops being reachable by any path and nothing errors. Worth the same kind of start-up check as the bolding one in section 9: every thing in the channel at or below the current drop must be named in some string the player can reach.

## Aliases

TSV cells rather than strings, so they do not change the count in the summary. `name` is what `{name}` prints; aliases are additional inputs the resolver accepts.

| `thing_id` | `name` | `aliases` |
| --- | --- | --- |
| `road` | road | `dirt road\|lane\|dirt` |
| `fog` | fog | `mist\|haze` |
| `branches` | branches | `branch\|limb\|limbs\|bough\|boughs\|tree\|trees\|canopy` |
| `fence` | fence | `wire\|wire fence\|fencing\|post\|posts\|fence post` |
| `ruts` | ruts | `rut\|wheel rut\|wheel ruts\|grooves` |
| `ditch` | ditch | `gutter\|trench\|culvert` |
| `leaves` | leaves | `leaf\|foliage` |
| `wasp_nest` | wasp nest | `nest\|wasps nest\|wasp's nest\|hornet nest\|hornets nest\|wasps\|hornets\|paper nest` |
| `field` | field | `pasture\|meadow\|empty field` |
| `tire_tracks` | tire tracks | `tracks\|track\|tire track\|tyre tracks\|wheel tracks\|tire marks\|mud` |

**Four choices worth knowing about.**

**Nouns named in a description but given no row of their own are aliased onto their parent.** `/look posts` returns the fence, `/look mud` returns the tire tracks, `/look culvert` returns the ditch. The prose mentions all three, so a player can reasonably type them, and pointing them at the nearest real thing is better than a refusal.

**Singular and plural both, everywhere it applies.** `branch` and `branches`, `leaf` and `leaves`, `rut` and `ruts`, `track` and `tracks`. People type whichever they were thinking in.

**`tyre` is in there deliberately.** The deck is American English for everything a player reads, but aliases are inputs, and refusing a British speaker's spelling is a bad trade for one cell.

**Two near-misses kept apart on purpose.** `track` sits only on the tire tracks, never on the road, so `/look track` cannot land on the wrong one — and `dirt` sits only on the road while `mud` sits only on the tracks, which is the one pair a player is most likely to blur.

### Two leaks the aliases expose

**`/look leaves` used to resolve in stage 1 — fixed.** The scent line said *the air smells of cold and wet leaves*, which put the word on screen before the branches existed, so a player who typed it got the scarlet-canopy string two stages early. It now smells of *cold and wet earth*, and nothing in stage 1 names a stage 2 noun.

**`/look tracks` has the same shape and is safe to leave.** The row is at `since_drop = 1` while the fragment naming it is stage 2, but no stage-1 text contains the word, so a player would have to guess it cold. Already recorded under the open questions as deliberate.

### One check for the loader

**Alias collisions have to be checked against the whole things table at every drop, not against the channel.** None of the above collides today. But drop 3 brings an outdoor Entryway, drop 5 brings a Courtyard, and the field behind the fence may one day hold Christmas trees — at which point `tree` and `trees`, currently on `branches`, become ambiguous. The check is cheap and the failure is silent: a duplicate alias resolves to whichever row sorts first, with nothing logged.

## Settled: `cat_bed.look`

The locked string reads *"A round cushion in dark green corduroy, flattened in the middle where something has slept. This is the sort of bed that looks plumpable."* It was written when the channel was nowhere. Three options were drafted. Option 1, lightly edited, is the one.

**Two things any rewrite has to keep.** *Plumpable* is the only nudge toward `/use` anywhere in the prose — the hint rail is the other, and the string should not lean on it alone. And *where something has slept* has to stay coy: the cat is an easter egg, so the bed may imply an occupant and must never name one.

**One thing it should avoid.** A player who just read the channel description then looks at the bed should not get the scene described twice. These touch the setting in passing rather than restating it.

### Option 1 — the dry bed (chosen)

> A round cushion in dark green corduroy at the edge of the road. It is dry, which nothing else here is. Flattened in the middle where something has slept, and the sort of bed that looks plumpable.

**Chosen, and the arrival is canon rather than a loose end.** The dryness is carried by shipped copy: `drop.1.announce` in the POC deck reads *"The cat swats her paw and something slides a couple feet away...something that didn't appear to be here before now"* — locked, posted in the channel the moment drop 1 opens. The bed got here seconds earlier, batted in from inside the house or from wherever else the cat goes. So the look text leans on canon instead of inventing any, and the cat's part in it stays implied rather than named, which keeps her an easter egg.

**The cut clause was the right cut.** *Set at the edge of the road as though the spot were chosen* existed to imply arrival without an agent. With the announce doing that job publicly and in the cat's own voice, the look text no longer has to, and the shorter line is cleaner for it.

**One thing worth knowing rather than fixing.** The announce fires once, in the channel, at the moment the drop opens; this string is re-read for weeks. A player who shows up later never sees the explanation, so for them *"it is dry, which nothing else here is"* is an unexplained anomaly rather than a confirmation. That is arguably the better of the two readings — it pays off for whoever witnessed it and stays a small mystery for everyone else — but the explanation reaches fewer people than it looks.

**The incongruity is not that a bed is on a road — it is that it is dry on a wet one.** That is a sharper question than *why is this here*, and it answers itself the wrong way round: something has kept it dry, and nothing in the scene explains what. It also deliberately rubs against `ditch.look` and `channel.look.5`, where everything else is damp.

And it implies placement without an agent. *As though the spot were chosen* raises the question that the mailbox answers in drop 2, without spending any of it.

### Option 2 — the minimal patch (not taken)

> A round cushion in dark green corduroy, flattened in the middle where something has slept. On a dirt road in the fog it makes no sense at all. This is the sort of bed that looks plumpable.

**Both locked sentences survive verbatim and one is inserted between them.** For a string marked locked that may matter more than the better prose, and it is the option to take if the writers would rather amend than rewrite.

### Option 3 — setting first (not taken)

> Somebody has put a cat bed on a dirt road: a round cushion in dark green corduroy, dark with damp around the bottom edge and dry on top. Flattened in the middle where something has slept. The sort of bed that looks plumpable.

**Lands the oddness hardest and costs the most.** *Somebody has put* names an agent, which is a small spend on the reveal the mailbox is being saved for, and the damp lower edge slightly undercuts the invitation to plump it. Included because the opening clause is the most arresting of the three.

### If any of them is taken

The string lives in the POC copy deck, section 4, marked **locked** — so this is an amendment to shipped copy rather than new drafting, and the writers own it. Nothing else in that section changes: `cat_bed.use`, `use_fail` and `take_fail` all read correctly in the new setting as they stand.

## Fence: settled on wire (option A)

**Settled: option A, the sagging wire.** Nothing in the drafted copy changes — A is already what sections 4 and 5 carry, so choosing it costs a decision and no words. Option C was the recommendation here; it is recorded as declined rather than open, so nobody reopens it later as an unresolved question. B and C stay below for the record.

Four things that follow from A, worth stating so they are not re-derived:

- **`field.look` stays**, and with it the slot for a later season behind the fence.
- **`fog.look` keeps its last clause** — *"thickest on the far side, where it keeps a shape it does not explain"* — since the rewrite flagged under option C is not needed.
- **Drop 3 reveals the drive and the front door by the fog clearing**, with no gate anywhere, exactly as the next section reserves it.
- **The counts hold:** eleven targets, ten new `things.tsv` rows, nineteen strings. The summary table needs no change.

Drafted for comparison. The choice is not really about the fence — it is about **whether the player can see past it**, and that decides one nested noun, the setting's register, and whether the field stays available for a later season.

### Option A — wire, as drafted above (chosen)

See-through, agricultural, derelict. Keeps `field.look` and leaves the Christmas tree farm open. Pre-refuses movement by being a boundary you can see over and still not cross.

### Option B — board replaces wire (not taken)

| Key | Text |
| --- | --- |
| `channel.look.3` | Along one shoulder a **fence** of grey weathered board stands six feet high, the boards set edge to edge, too tall to look over. One of them has warped away from its neighbor. |
| `fence.look` | Cedar gone grey, six feet of it, nailed to rails on the far side so the posts do not show. Somebody built this to be looked at from the other side. Where one board has warped there is a **gap** about the width of two fingers. |
| `gap.look` | Not much. A pale vertical strip of whatever is back there — bare ground, and past that the fog again. About as informative as a keyhole. |

**The noun count holds:** `field` is gone, because you cannot see a field through a solid fence, and **gap** replaces it. That is a straight swap and arguably an upgrade — looking *through* something is a better small discovery than looking *at* an empty field, and *built to be looked at from the other side* is the most unsettling clause in either draft.

**Three costs, and one of them is the decider.** A board fence is suburban where wire is rural, and it quietly moves the scene from a county road to a subdivision. A privacy fence implies a yard, which implies a dwelling on that side — and the house is supposed to be across the road, so this either invents a second one or puts the fence on the wrong property. And **a Christmas tree farm does not fence with privacy board.** Option B spends the seasonal slot that the wire fence was chosen to protect.

### Option C — both, one per side (not taken)

Wire stays on the field side, unchanged. The board fence moves **across the road**, where it belongs to the house — which fixes the property problem, because a dwelling is exactly what a privacy fence implies.

| Key | Text |
| --- | --- |
| `channel.look.3` | Unchanged from option A — the sagging wire on the near shoulder. |
| `channel.look.4` | Across the road stands a **board fence**, six feet of weathered grey, with the fog thick behind it. One board has warped away from its neighbor. |
| `board_fence.look` | Cedar gone grey, nailed to rails on the far side so the posts do not show. Somebody built this to be looked at from the other side. Where one board has warped there is a **gap** about the width of two fingers. |
| `gap.look` | Not much. A pale vertical strip, and fog. About as informative as a keyhole. |

**What this buys.** Twelve targets instead of eleven. The field and its seasonal slot survive. The fog gets something concrete to hide behind, which is more ominous than fog alone — a thing deliberately screened rather than merely distant. And **the gap becomes a staged device for free**: the same knothole gives up a little more each drop as the fog lifts, which is one string per drop and no new mechanism.

**It also hands drop 3 the `/go` target it needs.** A gate is the openable trap this deck warns about — but a gate that appears when the fog clears, in the drop where `/go` and `/enter` arrive, is the trap turned into the front of the house.

**One knock-on if C is chosen:** `fog.look` currently reads *"thickest on the far side, where it keeps a shape it does not explain."* With a fence over there the shape is explained, so that clause wants rewriting to something like *"thickest beyond the board fence, where it gives up nothing at all."*

### The comparison, short

|  | A — wire | B — board | C — both |
| --- | --- | --- | --- |
| Targets | 11 | 11 | 12 |
| Register | Rural, abandoned | Suburban, deliberate | Rural road, screened house |
| Christmas tree slot | Open | Spent | Open |
| Property logic | Fine | Implies a second dwelling | Fence belongs to the house |
| Best new noun | the field | the gap | the gap |
| Rows to add | — | swap one | one |
| Drop 3 | fog clears | fog clears | a gate appears |

## Stage 2 — the fog thins

Triggered by the player's first `/look cat bed`, which is the one event the hint ladder already records per player. Three fragments unlock permanently for that player — and because the printed order follows the keys, the branches line reappears in position two rather than at the end.

| Key | Text | Notes |
| --- | --- | --- |
| `channel.look.30` | A plank **bin** by the wall is labeled FIREWOOD in the same hand, a few gray splinters still in the bottom of it. A coin **slot** is cut into the counter, and below it a patch of pale, unweathered wood shows where the cash box it fed was unbolted and carried off. | New, 20 October. In stage 2 so the stand's interior details arrive after the player has crouched to the bed, keeping stage 1 to five short sentences. Both nouns named by alias |
| `channel.look.40` | **Branches** reach out over the road from both sides, far enough up that they almost meet in the middle, and what leaves they have left are scarlet and orange, and they rustle softly. | The only fragment that points upward, and the way in to the two best nested nouns. Moved here from stage 1. Renumbered from `channel.look.2` to `channel.look.40` on 20 October, which keeps it fourth in the paragraph — after the stand's two fragments — rather than tacked on the end |
| `channel.look.60` | Across the road the fog holds its shape around something tall and unlit, too square to be trees. | Still no noun. *Too square to be trees* says house without spending it |
| `channel.look.70` | **Tire tracks** show in the dried mud of the shoulder — one set, turning off the road toward the other side and stopping where the fog does. Nothing has come back out over them. | The one new target. It does the job the mailbox would have done — evidence of an owner — without being a thing anyone can open |

And one line, once, appended to the reply to that first `/look cat bed`:

| Key | Text | Notes |
| --- | --- | --- |
| `channel.fog_thins` | *When you look up from the bed, the fog has thinned slightly.* | Private, italic, **no `Hint:` prefix** — it is not instructional. This is a new formatting case; the nearest precedent is `bed_yield.public`, which is a public non-hint line |

**This is why the change is announced here and not in the description.** A fragment reading *"the fog has drawn back"* is true once and a lie every time after. The description says what is there; the notice says what moved. Anyone adding a later reveal should copy that split.

**The payoff is now substantial, and this is a better fix than the one proposed here before.** Stage 2 opens four targets rather than one: the **branches**, the **leaves** and the **wasp nest** hanging off them, and the **tire tracks**. The earlier suggestion was to pull the nest out of `branches.look` and gate it on its own. Moving the whole branch line instead is cleaner, because the leaves and the nest stay nested and free — they arrive in stage 2 by inheritance rather than each needing a condition.

**One mechanism carries all of it, and that mechanism is the fog.** An earlier draft of this section argued that fog could not hide the canopy, on the grounds that looking up through a low layer is the easy direction. That is wrong. A player standing *inside* the fog is looking through many meters of it in every direction, upward included — and higher density at the ground does not help when the path to a branch twenty feet up and some way off is fog the whole distance. The canopy needs no separate explanation.

**Which is why the notice says *thinned* and names no place.** *Pulled back off the road* localized the change to the road surface, and that localization is exactly what forced a second mechanism for the branches. *Thinned slightly* covers the road and the canopy at once, and it keeps the fog as the single lever behind every reveal in the pre-house phase — stage 2 here, the mailbox in drop 2, the drive and the front door in drop 3. One thing for the writers to turn, three drops of change out of it.

**One cost worth naming.** The wasp nest is the best noun in the scene and it now sits behind a gate. A player who never follows the hint to the bed never finds it. The ladder points at the bed explicitly, so that should be rare, but it is no longer reachable by curiosity alone.

**Settled: stage 1 gets no overhead line.** The scene has no ceiling until the branches unlock, and that is deliberate. A flat placeholder like *the road runs under trees* would have to stay true in stage 2, since fragments are only ever added and never removed, and it would cost the branches their arrival for nothing.

**And one word closed two things at once.** The scent line — renumbered to `channel.look.6` so it closes the paragraph at every stage — now smells of *cold and wet earth* rather than leaves. That was the last overhead reference in stage 1 and the reason `/look leaves` resolved two stages early, and it is fixed by the one change.

## Later drops — what the fog gives up

Reserved, not drafted. The point of recording it now is that the fog stops being scenery and becomes the pacing device for the whole pre-house phase: every drop changes the place the player already lives in, rather than only adding an object to a list.

- **Drop 2.** The fog thins again and the **mailbox** resolves, with a name on it. That is the cheapest available fix for a standing problem — David needs introducing before any flavor text assumes him, and drop 4's Alexa quest is currently carrying that whole job alone. The shape across the road becomes a silhouette.
- **Drop 3.** The fog clears. The **drive** and the **front door** resolve, and `/enter` arrives in the same drop that makes them worth having.
- **Later.** The field behind the fence is the slot for a seasonal change, if the game outlives Halloween.

**All of that is `since_drop` on the fragments** — per server, resolved exactly as the toy rows already resolve, no new engine. Only the single step inside drop 1 needs a per-player condition.

## Refusals, and one new default

**`use_fail.default` is wrong for all of this, and `/use` is one of only two verbs drop 1 has.** It currently reads *"You turn the {name} over in your hands. Nothing obvious happens"* — which assumes a held object. On a fence, a ditch or a wasp nest twenty feet up it is nonsense, and every noun in this scene is one command away from producing it.

| Key | Text | Notes |
| --- | --- | --- |
| `use_fail.fixture` | There is nothing to do with the {name} but look at it. | New default, for anything with `takeable = no`. Flat on purpose; writers may want two or three variants |
| `wasp_nest.take_fail` | It is twenty feet up and full of whatever a wasp colony leaves behind. You decide against it. | Not needed until `/take` ships in drop 2, but somebody will try it on the first day it exists |

**Check `take_fail.fixture` reads outdoors.** It was written for furniture in rooms. From drop 2 it will be answering *take the fence* and *take the fog*.

**No `/go` refusals belong in this deck.** `/go` is not registered until drop 3, so there is nothing to refuse in drops 1 and 2 — but the road, the fence and the field all become `/go` candidates the moment it arrives, and the existing rule that a refusal never names a verb the player cannot use means those strings belong to drop 3's work rather than here.

## What the engine needs

Short, because it belongs in a work order rather than a copy deck.

1. **Stop suppressing the room description in the channel.** The channel row gets `room_text`, and `/look` prints it above the item list. This reverses a settled decision and retires a special case rather than adding one.
2. **Fragmented room text with one per-player condition.** Fragments 1, 3, 4 and 5 always; 2, 6 and 7 once that player has looked at the cat bed. Printed order follows key order, so an unlocked fragment slots back into its place in the paragraph rather than appending to the end. That fact is already stored in the hints table, keyed `(guild, player, hint_id)` — so this needs no new per-player state and is **not** the general per-player `present_when` deliberately parked in V3.2.
3. **A one-time private line** appended to the first `/look cat bed` reply.
4. **Ten new `things.tsv` rows** — `room_id` the channel, `takeable = no`, no `use` text, `since_drop = 1`. They need a `type`; `scenery` is the obvious value but the content spec should pick it rather than this deck.
5. **Hand-bolded nouns, plus a loader check**, since engine-derived bolding is workstream D and is not built. Refuse to start if a bolded span has no matching thing alias at or below the current drop, if a lookable channel thing is bolded nowhere, or if one is named in no reachable string. Bolding is the boundary that tells a player what is lookable, so it is load-bearing here rather than cosmetic.
6. **One new default**, `use_fail.fixture`.
7. **The `look_prefix` override probably reverts.** It existed to make `/look` a bare list in a channel with no prose. With a description above it, normal room behavior is likely right — which also closes the open question about what fills `Items here:` when the channel is empty.

## Open questions

1. **Tone.** This is colder than the farm draft. A dirt road, fog, a sagging fence and a dead nest is a lonelier place than cider and pumpkins. That is probably right for a game whose destination is a haunted house, and it makes the cat the only warm thing in the scene — which arguably improves her. But it is a decision, not a side effect, and the writers should take it deliberately. The leaf revision pushes back toward warm without adding a single affordance, which makes it the cheapest lever available on this question if more warmth is wanted.
2. **`cat_bed.look` predates the setting.** It was written when the channel was nowhere; it now sits in the mud of a dirt road at dusk. Does it want a clause about sitting there incongruously? That string is marked final, so it is a writers' call rather than an edit. Resolved: option 1, lightly edited, is the chosen text, and the dryness is carried by the locked \`drop.1.announce\` line. See the settled section above.
3. **Is stage 2 worth its own mechanism?** One target and one sentence, against one per-player condition and a new notice format. The wasp-nest swap in section 6 is the lever if it needs to be bigger.
4. **The truck is gone.** With no farm it has no owner, and it was the worst trap in the earlier set — a cab, a bed, wheels, and the implication of leaving. If the scene wants one more close, tactile object, it can come back up on blocks with its wheels off.
5. **The Christmas tree farm.** `field.look` is written to leave that open and nothing here commits to it.
6. **A known, bounded leak.** The `tire_tracks` row exists at `since_drop = 1`, so `/look tire tracks` resolves even in stage 1, before the fragment naming them appears. Gating the row on per-player state would cost more than it saves, and the noun is close to unguessable — but it is a leak and the acceptance pass should know it is deliberate.
7. **A player whose first `/look` is `/look cat bed`** never sees the stage-1 description. The ladder's first rung points at bare `/look`, so it should be rare, but the first impression is not guaranteed.

## Summary of new strings

| Item | Count | State |
| --- | --- | --- |
| Top-level fragments, stage 1 | 3 | Drafted above |
| Top-level fragments, stage 2 | 3 | Drafted above |
| Nested look strings | 9 | Drafted above |
| The one-time fog notice | 1 | Drafted. New formatting case — private, italic, no `Hint:` |
| `use_fail.fixture` | 1 | Drafted. New default |
| `wasp_nest.take_fail` | 1 | Drafted. Not needed until drop 2 |
| Revisions to existing copy | 1 | `cat_bed.look` — option 1 chosen, pending copy across into the POC deck |

**Eighteen new strings, one revision, and ten new `things.tsv` rows.** Drop 1 goes from one `/look` target to eleven, five of which cost nothing to reach because they are nested rather than staged.

What it does not fix: drop 1 still has one repeatable action, and the bed is still once a day. This answers *there is nothing to see*. If the next round of feedback is *there is nothing to do*, the lever is pacing — advancing to drop 2 sooner — rather than more nouns.
