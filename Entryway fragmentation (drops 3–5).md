# DRAFT Entryway fragmentation — drops 3, 4 and 5

**Note for the developer: this is a DRAFT document for drops 3-5, which we are sharing in draft form for context only about the relationship\_delta concept. Please review this concept about what is likely to come soon, and how it will impact the work you have in progress. However, the details in this document will change before we should implement this document specifically.\
\
The shape.** `since_drop` sets the ceiling: what the server has unlocked at all. A per-player predicate sets the floor: whether this player has earned it. Neither works alone — `since_drop` by itself floods anyone who joins after drop 4, and a per-player gate by itself would show drop-5 content to a fast player in drop 3. Both columns already exist in `room_text.tsv`, and the Halloween channel already proves the pair works.

This settles the V3 plan's parked decision — *per-player `present_when` across all content · permanent gating, or corridor-then-graduation · V3.2* — as **corridor-then-graduation, implemented as more `visible_when` predicates on the existing per-entry column.** Not a general per-player `present_when` engine. That is a scope cut, and the developer should hear it before V3.2 starts.

## The split is three ways, not two

The schedule divides the Entryway's *things* across drops 3 and 4. The *prose* divides three ways, because the room text also names the arched and wide doorways, and the rooms behind them do not open until drop 5.

| Fragment | `since_drop` | Gated | Contents |
| --- | --- | --- | --- |
| 1 | 3 | no | the foyer, the **ceiling**, the **front door**, the **coat rack** |
| 2 | 4 | yes | the **mirror** |
| 3 | 4 | yes | the **stroller**, the **shoes**, the **booties** |
| 4 | 4 | yes | the **bulletin board**, the **smart speaker** |
| 5 | 4 | yes | the **Amazon box** |
| 6 | 5 | **no** | the arched **doorway**, the wide **doorway** |
| 7 | 4 | yes | the **staircase** and the **lumber** |

**Fragment 6 is deliberately ungated, and that is the most important row in the table.** If the exits sit behind a per-player predicate, a player who never completes drop 3's quest is still standing in the Entryway at drop 5 with no way out of it. Exits are never gated per player. The consequence is benign: an ungraduated player at drop 5 reads the foyer, the front door, the coat rack and two doorways, which reads perfectly well and still carries the quest prompt.

**One risk raised against this, and where it lands.** Could an un-graduated player walk out of the tutorial room mid-tutorial, straight from a bare description with a clear quest into a houseful of rooms? Not at drops 3 or 4: fragment 6 is `since_drop = 5`, and until then every Entryway exit leads somewhere that does not exist yet, so there is nowhere to go and nothing to gate. The case is real only from drop 5, once the ground floor opens.

**At drop 5 the exits are still the wrong thing to gate.** Putting the only doors in the game behind a per-player condition couples *can I leave this room* to *is the cat hungry*, and possibly to *is the cat in this room*, which the feeding design has not settled. Being briefly overwhelmed is recoverable in a way that being stuck in one room is not, and the gate would be protecting a late joiner for about ninety seconds in exchange for a permanent deadlock surface on the only door.

**Decided 21 October: no follow-the-player nudge.** The cat is always in the player's room, and the outstanding feed is carried by a new status line in `/stats` — *The cat looks at you with hunger in her eyes* — specified in the Social stats and leaderboard tab.

**One consequence worth recording.** With the cat always present, a never-fed player always eligible to feed her, and the salmon needing no opener, an un-graduated player can *always* complete the feed — so gating the doorways on `fed_the_cat` would no longer risk a deadlock. They stay ungated by choice rather than necessity, and the gate is available if the `/stats` line turns out not to be enough.

**And the flood is a drop-5 problem rather than an Entryway one.** Four rooms at once lands on every player, graduated or not, which is why the V3 plan already says drop 5 waits for V3.3's bolding and autocomplete. If four rooms is still too many after that, the lever is staging drop 5's own rooms — not holding players in the hall.

## Why the player sees less, in the fiction

The channel's staged reveal works because the fog explains it. The Entryway needs its own reason, and the cheapest one is already in the scene: **the player's attention is on the cat, not on the room.** The cat leads them in — that is the drop-3 premise — and they are watching her. Once she is fed and settles, they look at the room properly.

That beats a visibility argument for three reasons. It needs no light, no dark adaptation and no weather. It is per-player by construction, because it is keyed to an act the player performs. And it makes the second half of the room a payoff rather than a delivery, which is the same grammar as the fog thinning.

It wants a one-time private notice when the gate flips, the Entryway's equivalent of `channel.fog_thins`:

> `en_settles` — *Eunoia takes the can off to a corner of the coats, and for the first time since you came in you look at the room instead of at her.*

## The prose, row by row

Nearly all of this is lift-and-shift from the two EN rows that exist today. Only fragment 1 needs writing, and only fragment 5 needs a reword.

### Fragment 1 — `EN / default / 3`, always visible

New prose. It has to read as a whole room rather than a stub, and name nothing that arrives later.

> A tall foyer, two full stories up to a water-stained **ceiling**. The **front door** is shut behind you, three locks undone. A bentwood **coat rack** leans against the wall beside it under more coats than two people need, and a shallow ceramic **bowl** sits on the boards beside it, licked clean.

Three nouns, all three of them drop-3 things, and the coat rack placed last so the thing the hint ladder drives at is the thing the paragraph ends on.

### Fragments 2 to 5 and 7 — `EN / default / 4`, gated

Existing sentences, unchanged except where marked.

> **2.** An ornate **mirror** hangs beside the door, its silvering gone cloudy at the edges.
>
> **3.** A **stroller** is parked in the corner next to a pile of **shoes**, including a pair of tiny knit **booties**.
>
> **4.** A cork **bulletin board** by the door is layered with notes. Beside it on a small wooden table, a **smart speaker** blinks a patient blue ring.
>
> **5.** Someone has left an **Amazon box**, half-opened, against the wall. — *changed*
>
> **7.** The grand **staircase** is a ruin: steps cracked or missing, the banister hanging loose. A stack of fresh **lumber** leans against the wall beside it.

Fragment 5 today reads "at the foot of the stairs," which names the staircase before fragment 7 describes it. Both are drop-4 and both are gated, so the staircase is never actually absent when the box is present — but the player meets the phrase before the thing, which is the forward reach the fragment rule exists to prevent. Six words fix it.

Fragment 2 reaches *backwards*, to the front door, and that is fine: fragment 1 is always visible whenever fragment 2 is, so the reference can never dangle. The rule worth writing down is therefore not "never reach backwards" but **every fragment must read whole given every lower-numbered visible fragment, and must never reach forward.**

### Fragment 6 — `EN / default / 5`, always visible once drop 5 arrives

> An arched **doorway** on one side opens into the dining room, and a wide **doorway** opposite gives onto the living room.

### Fragment 7 has two state variants

> `EN / stairs_repaired / 4` — A grand **staircase** sweeps up to the floor above, patched here and there with fresh, pale wood.

**This needs one resolution rule, and it retires an existing hazard.** Fragments resolve per `(room_id, fragment)` at the highest arrived `since_drop`, taking the row whose `state` matches the room's current state and falling back to `default`. Then fragments 1 to 6 are written once and fragment 7 is the only one that exists twice. Today the two EN rows are 95% identical: a writer fixing a typo in the foyer sentence has to fix it in both, and would probably miss one. Fragmenting makes that structurally impossible.

## The predicate

`visible_when = fed_the_cat` on fragments 2, 3, 4, 5 and 7. One boolean, read exactly as `looked_at_bed` is read in the channel: a single lookup against the per-player hints table on `(guild, player, key)`. No new table, no new column, no new engine.

**Set it where the `room_service` achievement is awarded** — the first successful feed. Keeping it as its own flag rather than having `visible_when` read the achievements table means the column has one source of truth and one query shape, which is worth more than saving a row.

**Every drop-3 veteran already satisfies it.** They fed the cat when drop 3 was current, so at drop 4 the room opens with nothing to notice. The gate is invisible to everyone except the person it exists for.

**And the late joiner gets the sequence, just compressed.** They arrive in drop 4 or later, enter the house, meet four things and a quest prompt, feed the cat, and the room opens. Drops 3 and 4 in one sitting instead of two weeks apart — which is the right compression, because the order is what teaches, not the gap.

**No expiry row is needed.** The one failure mode worth insuring against was a player stuck in a half-visible room, and ungating fragment 6 removes it. A player who enters and never feeds the cat keeps the corridor and keeps the prompt, which is the correct experience rather than a bug.

## Three things in the files that block this

**1. Drop 3 is unwinnable as the files stand.** In the 20 October `things.tsv`, all five cat-food rows carry `requires = can_opener`, and the only source of an opener is `can_opener_hook` — `room_id = KI`, `contained_in = pantry`. The kitchen opens at drop 5. Drop 3's quest is *find the cat something to eat*, and it cannot be completed in drop 3 or drop 4.

Cheapest fix, one cell: **clear `requires` on `cat_food_salmon`.** The salmon is the flavor behind the coat rack and the only one drop 3 can reach, and "the cat's favorite is the one with the pull-tab" is a detail rather than a concession. The other four keep the requirement and come into reach with the kitchen at drop 5, which is where the opener already lives. Its `use_fail` needs rewriting too, since that string currently turns on there being no pull-tab.

The alternative, if the opener should arrive earlier: a `can_opener` row with `contained_in = amazon_box`, `room_id = EN`, `since_drop = 3` — canon-consistent with the to-do list's CANCEL AUTO-DELIVERY — which means moving the Amazon box out of fragment 5 and into drop 3, and giving `amazon_box` a drop-3 `look` variant that does not name David, so the drop-4 Alexa quest still gets to introduce him.

**2. `front_door` names the intercom, and the intercom is drop-4 content.** Its `look` reads *"A brass intercom panel is set into the wall beside it."* The front door is one of drop 3's four things, so at drop 3 a player reads about an intercom and `/look intercom` tells them the house doesn't have one. That is exactly the leak the acceptance pass's point 4 is for. Either give `front_door` a drop-3 `look` row without that sentence, or move `intercom` to drop 3 — which has something to recommend it, since the intercom appears in no room text at all and would therefore be a second thing findable only by reading prose, reinforcing drop 3's one lesson.

**3. `/go` is unlocked in drop 3 and has nowhere to go.** The schedule gives the player `/go` at drop 3, but every Entryway exit leads to a room that opens at drop 5 or later. For two drops the command sits in the slash menu and refuses on everything. Either `/go` moves to drop 5, or drop 3's Moving help section goes with it.

## What is needed, and from whom

**Writers — five small items.**

- Fragment 1, two sentences. Drafted above; needs approval or replacement.
- Fragment 5, six words: "at the foot of the stairs" out.
- `en_settles`, the one-time notice. Drafted above.
- A `use` success string for `cat_food_salmon`, and a rewritten `use_fail` for it that no longer hinges on the missing pull-tab. The other four flavors can wait for drop 5.
- A drop-3 `look` variant for `front_door` — a deletion, not a rewrite — unless the intercom moves to drop 3 instead.

**Developer — four items, none of them new machinery.**

- `visible_when` honored on `room_text` fragments, same read as `looked_at_bed`.
- `fed_the_cat` written on the first successful feed, beside the `room_service` award.
- The state-fallback rule: per `(room_id, fragment)`, highest arrived `since_drop`, state match then `default`.
- No per-player gate on any fragment that names an exit. Worth a comment in the file, because it is the kind of rule someone tidies away later while making the gating uniform.

**Owner — settled, 20 October.** The salmon cans have a pull-tab. The opener stays a drop-5 kitchen thing and gates the other four flavors. Drafted in the next section.

## The salmon pull-tab change

One cell in `things.tsv`, three strings in `thing_text.tsv`, one new key in `defaults.tsv`.

### `things.tsv`

`cat_food_salmon` — `requires` cleared, was `can_opener`. Nothing else on the row changes. The other four flavors keep the requirement, and the opener stays where it already is: `can_opener_hook`, in the pantry, drop 5.

### `cat_food_salmon` look — changed

> A can of salmon-flavored cat food, the label a lurid and confident pink, a pull ring set into the lid.

**The ring goes on the can and nowhere else** — not on the pack behind the coat rack. At drop 3 the detail does no work: the player has no opener and no concept of one, and nothing is blocking them. Its job is retroactive. At drop 5 the chicken refuses, and the player who remembers the salmon working now has the reason in front of them. Advertising it on the stash as well would spend the detail two drops before it can mean anything.

### `cat_food_salmon` use — new

> You hook a finger through the ring and pull. The lid comes away with a sound Eunoia evidently knows by heart — she is against your shin before it's halfway off. You empty it into the bowl, fold the lid down inside the can, and she doesn't look up again.

Three things it is doing. **No bowl**, because there isn't one: the can goes on the floor. **No room named**, because the salmon is carryable and this string has to work in the Entryway at drop 3 and in the Courtyard at drop 6. And **she arrives at the sound** rather than being already present, which keeps the string honest whether or not feeding ends up requiring the cat to be in the room — a question the feeding spec has not settled.

### `cat_food_salmon` use\_fail — cleared

With `requires` empty, the no-opener refusal can never fire on this row. A string that cannot fire is the kind of thing somebody later makes fire, so it should go rather than sit there.

The refusal that *can* fire on the salmon is the hunger gate, and that one is shared by all five flavors, so it belongs in `defaults.tsv` rather than five times over:

> `feed.not_hungry` — Eunoia looks at the can, then at you, with the mild disappointment of someone offered lunch at four in the afternoon. She isn't hungry yet.

**That needs one engine rule beside it:** a failed `requires` uses the thing's own `use_fail`, and any other failed gate uses the named default. `use_fail` is a single cell and there are now two reasons a feed can fail, so something has to decide which one speaks.

### Three strings that now contradict the opener gate

These predate the can opener — the 29 September `things.tsv` had no `requires` on any food row — and nobody has read them against it since.

**`cat_food_tuna`'s look already shows a ring pull:** *"the lid ring pulled slightly out from the rim."* If the salmon is the hand-openable flavor then the tuna cannot also be, and the tuna is the one stacked in the pantry where the opener lives. Replace the closure detail with one that explains the requirement instead of contradicting it:

> A can of tuna-flavored cat food, the lid solid and seamless, from before anyone thought of putting a ring on these.

**`cat_food_gourmet`'s use\_fail describes peeling the lid back:** *"You peel the lid back a fraction. The smell is, by cat food standards, genuinely appetizing."* That reads as a can that opens by hand and a player who stopped halfway. Suggested:

> The gold lid has no ring and no give. Whatever this cost, it did not include convenience.

**`cat_food_expired` has two different failures wearing one string.** Its `use_fail` — *"You get the lid up a fraction of a millimeter. That is as far as you are prepared to go."* — is a refusal about the player's judgment, not about a missing tool. But it fires on the `requires` gate, so a player without an opener gets a squeamishness line, and a player *with* an opener gets a success and feeds the cat a domed can. Either the expired can needs a second gate of its own, or it should not require an opener at all and this string becomes its only refusal, permanently.

After these three, the shared *"You turn the can over looking for a pull-tab"* line reads correctly on both of the rows that still use it.

### Settled: the expired can keeps the opener requirement

Of the two options above, this is the first: `cat_food_expired` keeps `requires = can_opener`, and the two failures stop sharing one string. The no-opener refusal carries the squeamishness; the success carries the cat's verdict and a **−75 relationship hit**.

| Key | Text |
| --- | --- |
| `cat_food_expired.use_fail` | The lid is domed up hard, and it gives a little under your thumb in a way that lids should not. You would need an opener, and you are not at all sure you want one. |
| `cat_food_expired.use` | The lid comes up with a hiss, and the smell arrives before the opener is all the way around. Eunoia is at your ankles exactly as long as it takes her to get one breath of it. Then she turns and walks away, and keeps walking, and does not look back. |

**One engine ask: nothing in the content files can hold a relationship delta today.** The toy's +10, the bed's +15 and a feed's +10 all live in code. A −75 on `/use` needs somewhere to sit, and the cheapest place is a new nullable `relationship_delta` column on `things.tsv` — which would let the other three move out of code at the same time and become tunable without a deploy.

**The magnitude is the thing to confirm, not the mechanic.** Against a start value of 0 and +10 a feed, −75 is roughly eight feeds; with the eight-hour hunger gate that is two and a half days of recovery at the fastest. It is by a wide margin the largest single swing in the game, and it is one command on a can a curious player may be carrying for no particular reason.

What makes it defensible is that the game warns twice — `cat_food_expired.look` already says the lid is domed and *you do not want to know*, and the new refusal says it again in the player's own hands. **But the second warning only reaches a player who tried without an opener.** Anyone already carrying one goes straight from the look to the success. So if −75 stands, the `look` is carrying the entire warning on its own, and it should be read with that job in mind.

**One upside worth recording.** This is the main route by which a player ever goes negative, which is what makes *Trying to Make Friends* — pets at a score below 0 — reachable at all. Without something like this it is close to dead content.

**And one suggestion.** A secret achievement on this turns a punishment into a story players tell each other, which is the difference between a trap that feels unfair and one that feels earned. The existing dry register would carry it well.

#### The achievement, drafted

Secret, so there is no prompt — a public quest line telling players to feed the cat expired food would be a different sort of game. `achievements.tsv` takes one row, and its seven columns are the whole of it; the trigger belongs in the Achievement Trigger Spec rather than the file.

| Column | Value |
| --- | --- |
| `achievement_id` | `one_star`\_review |
| `kind` | `secret` |
| `name` | One Star Review |
| `unlock` | Served Eunoia a can that expired a very long time ago. She will eat a mouse she found under the porch; she would not eat that |
| `since_drop` | 1 |
| `sort_order` | 190 |
| `notes` | Fires on a successful `/use` of `cat_food_expired`. Pairs with Room Service |

**Named *One Star Review*, 21 October.** *Room Service* is the first-feed achievement, so the hotel joke is already in the house and this is its dark twin — the guest's verdict on the meal. It does not collide with *Not-So-Picky Eater*, which is about the player eating Aunt Sue's burritos.

**`since_drop = 1` is the file's convention, not a claim about reachability.** All 35 existing rows carry 1, and whether the files renumber against the eight-drop schedule is still open. The real gate is physical: the only source of an expired can is `cat_food_stash_drawer`, in the rolltop desk in the Upstairs Hallway — drop 6, behind the jammed drawer, and therefore behind the graphite puzzle.

**That reachability also answers the caution above about the −75, and I withdraw it.** A player who can open that drawer has solved a multi-room puzzle, found the opener in the kitchen, and been playing for weeks. They are not sitting at 40 points, they are well up — so −75 is a scratch rather than a wipe, and it lands on the one player who can be relied on to find it funny.

#### Recommended: a `relationship_delta` column on `things.tsv`

**Add a nullable integer `relationship_delta`, applied on a successful `/use`.** Null — what every other row carries — means no change.

| Row | Delta |
| --- | --- |
| `cat_toy` | +10 |
| `cat_bed` | +15 |
| `cat_food_salmon`, `_chicken`, `_tuna`, `_gourmet` | +10 each |
| `cat_food_expired` | −75 |

**Scope it to `/use`, not to every source of score.** `/pet` is not a use of a thing, so its mood roll stays in code, and so does the nightly decay. The column is for *things that change the relationship when you use them*, which is a clean rule and covers everything currently known.

**Two engine rules ride with it.** The delta applies only after the gates pass, so a refusal moves nothing — which the feeding design already requires, since a refused feed consumes no food but still stamps `last_cat_interaction_date`. And it clamps against the existing floor of −100 and against no ceiling, per the uncapped-meter decision.

**The reason to do it now rather than when something else needs it.** The V3 plan makes the decay function the real balance lever and notes that whatever is in the code was written against a 100-point ceiling that no longer exists. Retuning decay means retuning it against the daily gain, and the daily gain *is* these four numbers. In code, every tuning pass is a deploy; in a column, it is a content edit — exactly the trade `restocks.tsv` already made for spawn rates, where the plan's own words are that the rate becomes an admin-tunable number on day one rather than a deploy.

**It also closes a gap in the QA set.** `/qa-relationship` can set a player's score, but nothing can change the *rates*, so balance testing currently means editing code between runs.

## The cat bowl

*Added 20 October. Playtesters worried the cat would cut herself on the can's edge — which the drafted `use` string invited, since it had the player setting an open can down on the floor. This reverses the feeding spec's "no bowl" decision, and the reason is good enough to be worth the reversal.*

### It has to be required, not decorative

`thing_text` is keyed by thing, state and drop, with no room dimension — so if `cat_food_salmon.use` mentions a bowl, it mentions one in every room the salmon is ever used in. A decorative bowl in the Entryway plus a `use` string that names it would read as nonsense in the Courtyard at drop 6.

So the bowl is a condition of feeding, and the cat eats where her bowl is. That is also how cats work, and it earns the Entryway a permanent reason to be walked through rather than passed.

**One engine ask.** `requires` currently reads as *the player is holding this* — it is how `can_opener` works. A floor fixture is not held, so `requires` has to be satisfied by **the thing being in the player's inventory or present in the current room.** Small generalization, and the house will want it again.

### Where it sits, and why that is tidy

Under the coat rack, beside the pack of salmon. That one placement explains two things already in the files: why the hall has a cat-food stash at all, and why half the cans are gone. This is where she is fed.

**It also makes drop 3 more legible rather than less.** The bowl goes in fragment 1, always visible — it is not a hidden thing. A player who walks in, sees a cat bowl on the floor and has a cat at their ankles knows what the room wants. The lesson about prose hiding findable things still lands on the salmon behind the coat rack; the bowl supplies the motive for looking.

### The rows and strings

`things.tsv` — one row: `cat_bowl` · name *cat bowl* · `type = fixture` · `room_id = EN` · `takeable` no · `droppable` no · `since_drop` 3. Aliases: `bowl|dish|food bowl|food dish|cat dish|water bowl|saucer`.

| Key | Text |
| --- | --- |
| `cat_bowl.look` | A shallow ceramic bowl, off-white, with a chip out of the rim and a ring of dried something around the inside. It has been licked clean more recently than it has been washed. |
| `cat_bowl.use_fail` | Nothing to be done with an empty bowl except fill it, and that takes a can. |
| `cat_bowl.take_fail` | It is hers, it lives on this floor, and she would notice. |

And `cat_food_salmon.use`, revised in place above:

> You hook a finger through the ring and pull. The lid comes away with a sound Eunoia evidently knows by heart — she is against your shin before it's halfway off. You empty it into the bowl, fold the lid down inside the can, and she doesn't look up again.

**Folding the lid down inside the can is the whole point of the edit.** It answers the sharp-edge worry concretely rather than by omission, and it accounts for where the can went, since cat food is `consumed_on_use`.

**`cat_bowl.use_fail` doubles as a hint rail.** *That takes a can* names the noun the quest needs without naming where it is, so the finding is still the work, and it names no verb the player does not already have.

### Three things left open

- **No bowl state.** A bowl that visibly held food after a feed would want a `full` state and something to expire it against the eight-hour hunger window. *Licked clean more recently than it has been washed* is true immediately after a feed as well as eight hours later, so one string covers both. A state is a later refinement, not a gap.
- **One bowl or several.** One, in the hall, is the recommendation: cats have a spot, and `/use <food>` elsewhere refuses by naming where the bowl is — a redirect to a place rather than to a verb, and `/go` exists from drop 3. If a later drop adds bowls, the kitchen is the obvious second.
- **The other four flavors.** Their `use` strings are still unwritten, and if all four pour into the same bowl then feeding stays a hall activity even after the ground floor opens. Worth confirming that is wanted before those strings are written.
