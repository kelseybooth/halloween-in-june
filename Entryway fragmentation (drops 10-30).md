# DRAFT Entryway fragmentation — drop 10

*Updated 27 October to match every decision so far. This tab holds the design reasoning; the developer's instructions are in the Drop 10 work order tab. Open questions are collected at the end.*

**\
The shape.** `since_drop` sets the ceiling: what the server has unlocked at all. A per-player predicate sets the floor: whether this player has earned it. Neither works alone — `since_drop` by itself floods anyone who joins after drop 10, and a per-player gate by itself would show drop-20 content to a fast player in drop 10. Both columns already exist in `room_text.tsv`, and the Halloween channel already proves the pair works.

This settles the V3 plan's parked decision — *per-player `present_when` across all content · permanent gating, or corridor-then-graduation · V3.2* — as **corridor-then-graduation, implemented as more `visible_when` predicates on the existing per-entry column.** Not a general per-player `present_when` engine. That is a scope cut, and the developer should hear it before V3.2 starts.

## The split is three ways, not two

The schedule divides the Entryway's *things* across drops 10 and 20. The *prose* divides three ways, because the room text also names the arched and wide doorways, and the rooms behind them do not open until drop 30.

| Fragment | `since_drop` | Gated | Contents |
| --- | --- | --- | --- |
| 1 | 10 | no | the foyer, the **ceiling**, the **front door**, the **coat tree**, the **cat bowl** |
| 2 | 20 | yes | the **mirror** |
| 3 | 20 | yes | the **stroller**, the **shoes**, the **booties** |
| 4 | 20 | yes | the **bulletin board**, the **smart speaker** |
| 5 | 20 | yes | the **Amazon box** |
| 6 | 30 | **yes** | the arched **doorway**, the wide **doorway** |
| 7 | 20 | yes | the **staircase** and the **lumber** |

**Fragment 6 is gated too, and so are the Entryway's exits. Decided 26 October.** Until a player has fed the cat, the doorways are missing from the room text and /go through them does not work, though the front door back to the road always does, so an occasional player who has fallen behind meets one room and one task rather than four rooms at once. The old objection was that a player who never completed drop 10's quest would be stuck in the Entryway at drop 30 with no way out of it. That can no longer happen: the cat is always there, a never-fed player is always eligible to feed her, and the salmon and the bowl are both in the room. An ungraduated player at drop 30 reads the foyer, the front door, the coat tree and the bowl, and keeps the quest prompt.

**Decided 21 October: no follow-the-player nudge.** The cat is always in the player's room, and the outstanding feed is carried by a new status line in `/stats` — *The cat looks at you with hunger in her eyes* — specified in the Social stats and leaderboard tab.

**One consequence worth recording.** With the cat always present, a never-fed player always eligible to feed her, and the salmon needing only the bowl in the same room, an un-graduated player can *always* complete the feed — so gating the doorways on `fed_the_cat` would no longer risk a deadlock. That is what makes the gate safe.

**This reverses the 21 October recommendation** to leave the exits ungated, which held that a few minutes of overwhelm was better than a deadlock on the only door. With feeding always possible inside the Entryway there is no deadlock to trade against, so the gate costs nothing. The drop-30 flood still reaches everyone who has fed the cat, and staging drop 30's rooms remains the lever for that.

## Why the player sees less, in the fiction

The channel's staged reveal works because the fog explains it. The Entryway needs its own reason, and the cheapest one is already in the scene: **the player's attention is on the cat, not on the room.** The cat leads them in — that is the drop-10 premise — and they are watching her. Once she is fed and settles, they look at the room properly.

That beats a visibility argument for three reasons. It needs no light, no dark adaptation and no weather. It is per-player by construction, because it is keyed to an act the player performs. And it makes the second half of the room a payoff rather than a delivery, which is the same grammar as the fog thinning.

It wants a one-time private notice when the gate flips, the Entryway's equivalent of `channel.fog_thins`:

> `en_settles` — *The cat **s**t**a**r**t**s** **e**ating,* *and **w**h**e**n** **you l**ook up **you* *n**o**t**i**c**e** m**o**re **o**f** the room**.*

## The prose, row by row

**Settled 27 October.** The room text is trimmed so each fragment is one short sentence naming its things, and the detail lives in each item's own `/look`. Fragment 6 describes the doorways rather than naming the rooms behind them, so players discover the dining and living rooms by looking or walking through.

| # | State | Drop | Gated on `fed_the_cat` | Text |
| --- | --- | --- | --- | --- |
| 1 | default | 10 | no | A tall foyer under a water-stained **ceiling**. The **front door** is shut behind you, with a crowded **coat tree** beside it and an empty cat **bowl** on the floor. |
| 2 | default | 20 | yes | A cloudy **mirror** hangs by the door. |
| 3 | default | 20 | yes | A **stroller** is parked in the corner by a pile of **shoes** and tiny **booties**. |
| 4 | default | 20 | yes | A **bulletin board** hangs over a small table where a **smart speaker** blinks blue. |
| 5 | default | 20 | yes | An **Amazon box** sits half-opened against the wall. |
| 6 | default | 30 | yes | An **arched doorway** opens on one side, and a **wide doorway** on the other. |
| 7 | default | 20 | yes | The grand **staircase** is a ruin, with fresh **lumber** stacked beside it. |
| 7 | stairs\_repaired | 20 | yes | A patched **staircase** sweeps up to the floor above. |

**All together**, once every fragment is showing (96 words):

> A tall foyer under a water-stained **ceiling**. The **front door** is shut behind you, with a crowded **coat tree** beside it and an empty cat **bowl** on the floor. A cloudy **mirror** hangs by the door. A **stroller** is parked in the corner by a pile of **shoes** and tiny **booties**. A **bulletin board** hangs over a small table where a **smart speaker** blinks blue. An **Amazon box** sits half-opened against the wall. An **arched doorway** opens on one side, and a **wide doorway** on the other. The grand **staircase** is a ruin, with fresh **lumber** stacked beside it.

A player at drop 10 who hasn't fed the cat sees fragment 1 alone, which is 28 words.

**Where the detail went.** Each item's own `/look` already says what the room text no longer does: the three locks, the coats, the cloudy silvering, the knit booties, the notes on the board, the blue ring, the broken steps and the glimpses through the doorways.

**The coat tree.** `coat_rack` keeps its id but is now named *coat tree*. `coat tree|tree|coat stand` are added to its aliases, and `coat rack` stays as one. The cans now sit behind its base, hidden by the coats:

| Key | Text |
| --- | --- |
| `coat_rack.look` | A bentwood coat tree under more coats than two people need: two parkas, two raincoats, three fleeces, two sizes of bunting suit, and a stroller rain cover awkwardly dangling. The coats hang nearly to the floor, and behind the base, hidden by them, is a large pack of salmon cat food. |
| `cat_food_stash_hall.look` | A cardboard pack of salmon-flavored cans tucked behind the base of the coat tree, the plastic wrap slit open down the middle and half the cans already gone. |

**The doorways are discovered, not announced.** Fragment 6 uses each exit's own name, and their looks show a glimpse instead of naming the room. `/go dining room` and `/go living room` still work, through the aliases.

| Key | Text |
| --- | --- |
| `ED.look` | Through the arch you can see the corner of a long table and a chair pushed back from it. |
| `EL.look` | Warm light spills through it, and the corner of a deep sofa beyond. |

**The cat bowl is in the files**, because fragment 1 names it: a `cat_bowl` fixture in the Entryway at drop 10, with the look, refusal and take refusal from The cat bowl section below. Since 27 October the salmon requires it, so feeding happens at the bowl.

**All of the above is in `room_text.tsv`, `things.tsv` and `thing_text.tsv` in creative content as of 27 October.** The two old one-block Entryway rows are gone.

Fragment 2 reaches *backwards*, to the front door, and that is fine: fragment 1 is always visible whenever fragment 2 is, so the reference can never dangle. The rule worth writing down is therefore not "never reach backwards" but **every fragment must read whole given every lower-numbered visible fragment, and must never reach forward.**

**This needs one resolution rule, and it retires an existing hazard.** Fragments resolve per `(room_id, fragment)` at the highest arrived `since_drop`, taking the row whose `state` matches the room's current state and falling back to `default`. Then fragments 1 to 6 are written once and fragment 7 is the only one that exists twice. Today the two EN rows are 95% identical: a writer fixing a typo in the foyer sentence has to fix it in both, and would probably miss one. Fragmenting makes that structurally impossible.

## The predicate

`visible_when = fed_the_cat` on fragments 2 to 7, and on the Entryway's exits. One boolean, read exactly as `looked_at_bed` is read in the channel: a single lookup against the per-player hints table on `(guild, player, key)`. No new table, no new column, no new engine.

**Set it where the `room_service` achievement is awarded** — the first successful feed. Keeping it as its own flag rather than having `visible_when` read the achievements table means the column has one source of truth and one query shape, which is worth more than saving a row.

**Every drop-10 veteran already satisfies it.** They fed the cat when drop 10 was current, so at drop 20 the room opens with nothing to notice. The gate is invisible to everyone except the person it exists for.

**And the late joiner gets the sequence, just compressed.** They arrive in drop 20 or later, enter the house, meet five things and a quest prompt, feed the cat, and the room opens. Drops 10 and 20 in one sitting instead of two weeks apart — which is the right compression, because the order is what teaches, not the gap.

**No expiry row is needed.** The one failure mode worth insuring against was a player stuck in a half-visible room, and that cannot happen while feeding is always possible in the Entryway. A player who enters and never feeds the cat keeps the one room and the prompt, which is the correct experience rather than a bug.

## Three things that blocked this, all resolved

**1. Drop 10 is unwinnable as the files stand.** In the 20 October `things.tsv`, all five cat-food rows carry `requires = can_opener`, and the only source of an opener is `can_opener_hook` — `room_id = KI`, `contained_in = pantry`. The kitchen opens at drop 30. Drop 10's quest is *find the cat something to eat*, and it cannot be completed in drop 10 or drop 20.

Cheapest fix, one cell: **clear `requires` on `cat_food_salmon`.** The salmon is the flavor behind the coat rack and the only one drop 10 can reach, and "the cat's favorite is the one with the pull-tab" is a detail rather than a concession. The other four keep the requirement and come into reach with the kitchen at drop 30, which is where the opener already lives. Its `use_fail` needs rewriting too, since that string currently turns on there being no pull-tab.

The alternative, if the opener should arrive earlier: a `can_opener` row with `contained_in = amazon_box`, `room_id = EN`, `since_drop = 10` — canon-consistent with the to-do list's CANCEL AUTO-DELIVERY — which means moving the Amazon box out of fragment 5 and into drop 10, and giving `amazon_box` a drop-10 `look` variant that does not name David, so the drop-20 Alexa quest still gets to introduce him.

**Resolved 27 October.** The salmon requires the cat bowl instead of the opener, so drop 10 can be won. The Amazon box alternative wasn't needed.

**2. `front_door` names the intercom, and the intercom is drop-20 content.** Its `look` reads *"A brass intercom panel is set into the wall beside it."* The front door is one of drop 10's five things, so at drop 10 a player reads about an intercom and `/look intercom` tells them the house doesn't have one. That is exactly the leak the acceptance pass's point 4 is for. Either give `front_door` a drop-10 `look` row without that sentence, or move `intercom` to drop 10 — which has something to recommend it, since the intercom appears in no room text at all and would therefore be a second thing findable only by reading prose, reinforcing drop 10's one lesson.

**Resolved 27 October.** The front door's drop 10 look no longer mentions the intercom; see The channel as a room. From drop 20, the door's look names the intercom, which arrives at the same drop.

**3. `/go` is unlocked in drop 10 and has nowhere to go.** The schedule gives the player `/go` at drop 10, but every Entryway exit leads to a room that opens at drop 30 or later. For two drops the command sits in the slash menu and refuses on everything. Either `/go` moves to drop 30, or drop 10's Moving help section goes with it.

**Resolved 27 October.** The front door is now an exit back to the road, so `/go` has a job from drop 10.

## What is needed, and from whom

**Writers — status, 27 October.**

- Fragment 1: approved 27 October, in the trimmed version.
- Fragment 5: done in the trim, which no longer mentions the stairs.
- `en_settles`, the one-time notice. Approved 26 October.
- The salmon's `use` line and its new `use_fail`: both approved and in the files, 27 October. The other four flavors' lines are drop 30 work.
- A drop 10 look for `front_door` without the intercom: done, in The channel as a room.

**Developer — four items, none of them new machinery.**

- `visible_when` honored on `room_text` fragments, same read as `looked_at_bed`.
- `fed_the_cat` written on the first successful feed, beside the `room_service` award.
- The state-fallback rule: per `(room_id, fragment)`, highest arrived `since_drop`, state match then `default`.
- Fragment 6 and the Entryway's exits (`ED`, `EL`, and `EH` once it leads anywhere) gated on `fed_the_cat` for each player: hidden from the room text, and `/go` out of the Entryway refused until the first feed. It is the only per-player gate on an exit, and it is safe only because feeding can always be completed inside the Entryway. Worth a comment in the file, so nobody later adds a feeding requirement the Entryway cannot meet.

**Owner — settled, 20 October.** The salmon cans have a pull ring, so the salmon needs only the cat bowl (see The cat bowl, below). The opener stays a drop-30 kitchen thing and gates the other four flavors. Drafted in the next section.

## The salmon pull-tab change

One cell in `things.tsv`, three strings in `thing_text.tsv`, one new key in `defaults.tsv`.

### `things.tsv`

`cat_food_salmon` — `requires` changes from `can_opener` to `cat_bowl`. Nothing else on the row changes. The other four flavors become `can_opener|cat_bowl`, and the opener stays where it already is: `can_opener_hook`, in the pantry, drop 30.

### `cat_food_salmon` look — changed

> A can of salmon-flavored cat food, the label a lurid and confident pink, a pull ring set into the lid.

**Approved and in the files, 27 October**, along with `requires = cat_bowl` on `cat_food_salmon` in `things.tsv`.

**The ring goes on the can and nowhere else** — not on the pack behind the coat tree. At drop 10 the detail does no work: the player has no opener and no concept of one, and nothing is blocking them. Its job is retroactive. At drop 30 the chicken refuses, and the player who remembers the salmon working now has the reason in front of them. Advertising it on the stash as well would spend the detail two drops before it can mean anything.

### `cat_food_salmon` use — new

> You hook a finger through the ring and pull. The lid comes away with a sound the cat evidently knows by heart — she is against your shin before it's halfway off. You empty it into the bowl, fold the lid down inside the can, and she doesn't look up again.

**Approved 27 October**, and written into `thing_text.tsv`.

**The public line, approved 27 October:** `feed.public` — {player} fed the cat. Finally.

It posts in the room for everyone else on any successful feed of any flavor, the same way `bed_fluff.public` works for the bed. It lives in `defaults.tsv` so every flavor shares it. It doesn't fire for the expired can, because she walks away from that and it isn't a feed.

Three things it is doing. **Into the bowl**, with the lid folded down inside the can, so the cat never comes near a cut edge. **No room named**, because the bowl is what makes the feed possible: the string only ever runs where a bowl is, and still reads right if a later drop adds a second one. And **she arrives at the sound** rather than already being at your feet, which reads right even though she is always somewhere in the room.

### `cat_food_salmon` use\_fail — needed again

With `requires = cat_bowl`, this refusal fires whenever the salmon is used anywhere without a bowl, which is everywhere except the Entryway. It must not mention a pull-tab. Per the one-bowl recommendation below, it should send the player to the bowl by naming where it is. **Approved 27 October, below, and written into thing\_text.tsv.**

> `cat_food_salmon.use_fail` — What were you planning to do, pour it on the floor? You need a cat bowl.

The other refusal that *can* fire on the salmon is the hunger gate, and that one is shared by all five flavors, so it belongs in `defaults.tsv` rather than five times over:

> `feed.not_hungry` — The cat looks at the can, then at you, with the mild disappointment of someone offered lunch at four in the afternoon. She isn't hungry yet.

**That needs one engine rule beside it:** a failed `requires` uses the thing's own `use_fail`, and any other failed gate uses the named default. `use_fail` is a single cell and there are now two reasons a feed can fail, so something has to decide which one speaks.

**Hunger is checked first. Decided 27 October.** Which refusal a feed gets:

| The cat is | The bowl is | Refusal |
| --- | --- | --- |
| not hungry | missing | `feed.wrong_time_and_place` — The cat looks skeptically at the can, then at you. This is neither the right time nor the right place. |
| not hungry | present | `feed.not_hungry` |
| hungry | missing, or the opener is | the flavor's own `use_fail`, for the first missing item in its `requires` |

A missing opener on its own doesn't change the not-hungry answer. Only the bowl does, because it's the "place." The expired can is the exception to all of this: it isn't a feed, so hunger never applies and its squeamish refusal always speaks.

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
| `cat_food_expired.use` | The lid comes up with a hiss, and the smell arrives before the opener is all the way around. The cat is at your ankles exactly as long as it takes her to get one breath of it. Then she turns and walks away, and keeps walking, and does not look back. |

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
| `unlock` | Served the cat a can that expired a very long time ago. She will eat a mouse she found under the porch; she would not eat that. |
| `since_drop` | 40 |
| `sort_order` | 190 |
| `notes` | Fires on a successful `/use` of `cat_food_expired`. Pairs with Room Service |

**Named *One Star Review*, 21 October.** *Room Service* is the first-feed achievement, so the hotel joke is already in the house and this is its dark twin — the guest's verdict on the meal. It does not collide with *Not-So-Picky Eater*, which is about the player eating Aunt Sue's burritos.

**`since_drop = 40`, the drop the expired can arrives in.** Its only source is `cat_food_stash_drawer`, in the rolltop desk in the Upstairs Hallway, behind the jammed drawer, and therefore behind the graphite puzzle.

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

**Corrected 21 October, from the developer: "applied on a successful `/use`" would pay the toy for failing.** A refused toy play is still a successful use — it records the use and advances the ramp. So the column means *what this use is worth*, and the thing's own handler decides whether it pays: the default handler pays on success, and the toy's pays only when the cat plays. The bed and food go straight through.

**The reason to do it now rather than when something else needs it.** The V3 plan makes the decay function the real balance lever and notes that whatever is in the code was written against a 100-point ceiling that no longer exists. Retuning decay means retuning it against the daily gain, and the daily gain *is* these four numbers. In code, every tuning pass is a deploy; in a column, it is a content edit — exactly the trade `restocks.tsv` already made for spawn rates, where the plan's own words are that the rate becomes an admin-tunable number on day one rather than a deploy.

**It also closes a gap in the QA set.** `/qa-relationship` can set a player's score, but nothing can change the *rates*, so balance testing currently means editing code between runs.

## The cat bowl

*Added 20 October. Playtesters worried the cat would cut herself on the can's edge — which the drafted `use` string invited, since it had the player setting an open can down on the floor. This reverses the feeding spec's "no bowl" decision, and the reason is good enough to be worth the reversal.*

### It has to be required, not decorative

`thing_text` is keyed by thing, state and drop, with no room dimension — so if `cat_food_salmon.use` mentions a bowl, it mentions one in every room the salmon is ever used in. A decorative bowl in the Entryway plus a `use` string that names it would read as nonsense in the Courtyard at drop 30.

So the bowl is a condition of feeding, and the cat eats where her bowl is. That is also how cats work, and it earns the Entryway a permanent reason to be walked through rather than passed.

**One engine ask.** `requires` currently reads as *the player is holding this* — it is how `can_opener` works. A floor fixture is not held, so `requires` has to be satisfied by **the thing being in the player's inventory or present in the current room.** Small generalization, and the house will want it again.

**Answered 21 October.** `requires` is already multi-valued. The new part is meeting a requirement from the current room, scoped to **non-takeable things only**. When several are missing, the first in the cell's order speaks, so the four opener flavors take `requires = can_opener|cat_bowl` and the salmon takes `requires = cat_bowl`. Hunger is read from `thing_uses.last_used_at` across the food rows, so a refused feed must never write it, and the expired can is excluded — she walks away from it, so it is not a feed.

### Where it sits, and why that is tidy

Under the coat tree, beside the pack of salmon. That one placement explains two things already in the files: why the hall has a cat-food stash at all, and why half the cans are gone. This is where she is fed.

**It also makes drop 10 more legible rather than less.** The bowl goes in fragment 1, always visible — it is not a hidden thing. A player who walks in, sees a cat bowl on the floor and has a cat at their ankles knows what the room wants. The lesson about prose hiding findable things still lands on the salmon behind the coat tree; the bowl supplies the motive for looking.

### The rows and strings

`things.tsv` — one row: `cat_bowl` · name *cat bowl* · `type = fixture` · `room_id = EN` · `takeable` no · `droppable` no · `since_drop` 10. Aliases: `bowl|dish|food bowl|food dish|cat dish|water bowl|saucer`.

| Key | Text |
| --- | --- |
| `cat_bowl.look` | A shallow ceramic bowl, off-white, with a chip out of the rim and a ring of dried something around the inside. It has been licked clean more recently than it has been washed. |
| `cat_bowl.use_fail` | Nothing to be done with an empty bowl except fill it, and that takes a can. |
| `cat_bowl.take_fail` | It is hers, it lives on this floor, and she would notice. |

And `cat_food_salmon.use`, revised in place above:

> You hook a finger through the ring and pull. The lid comes away with a sound the cat evidently knows by heart — she is against your shin before it's halfway off. You empty it into the bowl, fold the lid down inside the can, and she doesn't look up again.

**Folding the lid down inside the can is the whole point of the edit.** It answers the sharp-edge worry concretely rather than by omission, and it accounts for where the can went, since cat food is `consumed_on_use`.

**`cat_bowl.use_fail` doubles as a hint rail.** *That takes a can* names the noun the quest needs without naming where it is, so the finding is still the work, and it names no verb the player does not already have.

### Bowl details

- **No bowl state.** A bowl that visibly held food after a feed would want a `full` state and something to expire it against the eight-hour hunger window. *Licked clean more recently than it has been washed* is true immediately after a feed as well as eight hours later, so one string covers both. A state is a later refinement, not a gap.
- **One bowl or several. Settled: one,** in the Entryway. Food used anywhere else gets that flavor's own refusal, which for the salmon is *What were you planning to do, pour it on the floor? You need a cat bowl.* If a later drop adds bowls, the kitchen is the obvious second.
- **The other four flavors.** Their `use` strings are still unwritten, and if all four pour into the same bowl then feeding stays a hall activity even after the ground floor opens. Worth confirming that is wanted before those strings are written.

## Questions settled and still open, 27 October

1. **The intercom. Settled 27 October:** it stays in the front door's drop 20 look, and the intercom itself arrives at drop 20. No fragment mentions it, so reading the door's description is how players find it.
2. **Hints for drop 10. Settled: none, as a trial.** Players who reach the Entryway already know `/look` and `/take`, mostly because the road shows the house to players who have earned *Purrsuasive (or who have used /look house or been inside)*. The *Room Service* quest tells them there's something to do. The only hint involved is the one that points at `/go house` on the road.
3. **A drop 10 announcement. Settled: none.** Beta testers check their open quests, so *Room Service* does the announcing.
4. **Things in hidden fragments still exist. Settled: that's fine.** A player who guesses `/look mirror` before the room opens up still sees it.
5. **The other flavors (drop 30). Settled:** chicken, tuna and gourmet require the opener and the bowl (`can_opener|cat_bowl`), and that's in `things.tsv`. The expired can keeps the opener alone, since it isn't a feed. Their text gets written later, with the rest of the later drops' text.
6. **Later-drop text, still open:** the tuna look and gourmet refusal rewrites, and the other flavors' feeding lines.
7. **The expired can (drop 40):** the refusal and the −75 feeding line, *One Star Review*'s unlock line, and the `relationship_delta` column. None are in the files yet, and none are needed for drop 10.
