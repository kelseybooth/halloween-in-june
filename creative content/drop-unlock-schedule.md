# Drop unlock schedule

*Refreshed 19 October from `drop-unlock-schedule.md`, the version delivered with the Phase 3a work order. The table, the mechanics and the achievement copy are current. The notes for drops 1 and 2, further down, still predate the bed-and-toy swap and are marked where they start.*

A drop-by-drop view of what exists for players at each stage. Everything here is a proposal except drop 0, which follows the shape already agreed: cat only, `/pet` and `/stats` and `/help`, no rooms.

**Recalibrated to carry the cat-relationship drops.** Cat toys and cat beds now occupy drops 1 and 2, and everything from the house onward shifts by two. The pre-house phase is no longer a holding pattern before the real game — it is a relationship with one character, built over three drops, which is a better use of the week than waiting.

**Drops advance by admin command, not by date.** Drop 0 opens when an admin starts the game in a named channel, and every later drop without an event trigger is advanced the same way. Dates come back once a few servers have run and the right pacing is known; until then the calendar is a human holding a button. The one exception already in the design is drop 6, gated on the staircase repair.

Two rules the schedule is built on:

- **`/help` only ever documents what is unlocked.** It grows one section per drop and never mentions a command or concept the player cannot reach yet. This is the main defence against the overwhelm the testers hit.
- **Nothing is revealed before it is useful.** A command arrives in the same drop as the first thing worth using it on.

---

## The table

| Drop | Description | Commands unlocked | Things revealed | Rooms revealed | Help sections | Intention |
| --- | --- | --- | --- | --- | --- | --- |
| **0** | **The Cat.** A Halloween channel with a cat in it. No house, no rooms, no mention of either. | Player: `/pet`, `/stats`, `/help` · Admin: `/start-game <channel>`, `/advance-game`, `/admin_config` | Eunoia only. The daily craving **is not built** and drop 0 ships without it; it belongs here when it exists. | None | What this is · Petting · Your stats | Teach that slash commands exist, across a surface of three. Make the first achievement unmissable. Establish the cat as the voice of the game. |
| **1** | **A Place to Sleep.** A cat bed appears in the channel. | Player: `/look`, `/use` | `cat_bed` — one, shared, usable but not takeable | The channel itself becomes lookable | — | Teach two verbs on one object that always obeys, in a place with nothing else to confuse it. Give the relationship a second lever, and a reason to come back tomorrow. |
| **2** | **Something to Play With.** Toys start arriving, and then things nobody in this channel owns. The cat is not easily impressed. | Player: `/take`, `/inventory` | `cat_toy`, maintained at two in the channel; then the household trickle: knit bootie, wooden rattle, photograph, brass key | None | — | Teach carrying things, on an object worth carrying. Seed the existence of a house without naming it — a baby's bootie and a brass key raise a question drop 3 answers. |
| **3** | **The Door.** The cat leads players to a house and into one room. One quest, tightly scoped. | Player: `/enter`, `/look`, `/go`, `/take` | Entryway subset only: coat rack, the salmon cat-food stash behind it, front door, ceiling | Entryway (partial prose) | Looking · Moving · Taking · The house | First room, one quest, highest possible reward-to-action ratio. Teach that descriptions hide findable things. |
| **4** | **The Rest of the Entryway.** The room fills in. Two or three more quests, same room. | Player: `/drop` | Remaining Entryway things: mirror, bulletin board, Amazon box, Alexa, stroller, shoes, booties, intercom, lumber, the ruined staircase | Entryway (full prose) | Dropping things · The noticeboard | Introduce David properly, with exposition, via the Alexa quest. Start the staircase as a group objective that gates drop 6. |
| **5** | **Downstairs.** The ground floor opens. | None new. `/stats` may gain server-wide progress | Everything in the four ground-floor rooms, including four cat-food stashes and the cake box | Dining Room, Kitchen, Living Room, Courtyard | The house (expanded) · Cat food · Achievements | Open the map. Start the cat-food economy. Bring most of the achievements into reach. |
| **6** | **Upstairs.** Opens when the staircase is repaired — a group gate, not a date. | None new | Upstairs Hallway, Bedroom and Nursery contents: costumes, carving tools, graphite, the roll-top desk and the smell | Upstairs Hallway, Bedroom, Nursery | Repairs · Costumes | Pay off the group objective from drop 4. Deliver the drawer puzzle and the Halloween box. |
| **7** | **The Secret Library.** Per-player discovery, exactly as Phase 2e specifies. | None new | Scorch circle, ritual diagram, cracked mirrors, spirit board, the key ring, copper wire | Secret Library (per player, on discovery) | None — the library is never documented in `/help` | Reward the curious. Keep the one room that is never announced. |
| **Later** | Unscheduled. Blocked on systems that do not exist. | — | The letter, the doorbell, the ghost system, cat crossing between dimensions | — | — | Seven achievements are blocked on these. They stay out of the schedule until someone commits to building them. |

---

## The cat-relationship mechanics

### The toy, drop 2

**Settled: toys are inventory items, picked up with `/take`.** The bed is not — it is a fixture in drop 1, and `/take` arrives with the toy in drop 2. Not fixtures, and not claimed by reaction — the reaction route is out because the craving game's handler, which it would have reused, turns out not to exist. A player runs `/look` in the channel, sees what is there, `/take`s it, and `/use`s it from their bag.

**They are maintained at two in the channel rather than dropped on a timetable.** Whenever fewer than two of an item are present, more appear at random times. That is a new restock mode: `restocks.tsv` adds rather than tops up, so it needs a **`max_present`** cap — fill toward it, never exceed it. One column, and it is a better rule than a rate, because the channel self-regulates: a quiet server keeps two sitting there, a busy one keeps getting fresh ones.

**Split across two drops, the object loop teaches itself in order.** Drop 1 is *look at a thing, use a thing*, on a bed that always obeys. Drop 2 adds *pick a thing up, check your bag*, on a toy worth carrying. The payoff lands in drop 3: a player reaching the Entryway already knows four of the five verbs they need, and the room has to teach only movement. That was the drop the testers stalled in.

- **The first offer is always refused.** The chance the cat plays starts at 0% and rises **25 percentage points per attempt**: 0, 25, 50, 75, 100.
- **On a successful play, +10 relationship**, and the cat is disinterested for **10 minutes** — attempts during the cooldown cost and earn nothing.

That gives a bounded, guaranteed shape: **success takes 3.2 attempts on average and 5 at the very worst.** Nobody can get stuck and nobody can shortcut it. It is a good mechanic; the numbers attached to it are the problem, and the balance section below is about those rather than the design.

Four things the spec has to pin down that the description leaves open:

- **The ramp resets to 0% after a success**, or a player sits at 100% forever and the mechanic stops existing after its first use.
- **Attempts during the cooldown do not advance the ramp.** Otherwise a player banks five refusals during the ten minutes and converts instantly on expiry, and the cooldown is decoration.
- **Ramp and cooldown are per player.** One cat, many simultaneous games — consistent with the suspension of disbelief the cat already asks for by being in every room at once. Server-wide state would make the toy a race, and a late joiner would inherit a ramp they did not build.
- **The toy is never consumed**, and the ramp and cooldown are what make repeated use meaningful rather than scarcity. If toys are inventory items after all, `max_per_player = 1` stops hoarding; as fixtures the question does not arise.

### The bed, drop 1

One cat bed is present in the channel from the moment drop 1 opens. `/use cat bed` fluffs it. **+15 relationship, once per player per day.**

- **One bed, shared, a fixture — settled.** Not takeable, never consumed, present from the drop's first minute. Everyone fluffs the same bed, which reads as communal care and contrasts with the toy, which is personal. It also keeps `/take` and `/inventory` out of drop 1 entirely. More beds are a content lever later, but each extra bed with its own cooldown multiplies the daily gain, so they are a balance change rather than a content addition.
- **Once per server day, Pacific, rather than a rolling 24 hours.** This differs from the literal wording and is friendlier: a rolling window punishes a player for fluffing early on Monday by pushing Tuesday's fluff later, and drifts across the week. A calendar day lets them do it whenever they are around. It also matches the existing midnight job and the Pacific day boundaries the achievements already use, and it is testable with the clock override.

### Settled: bed in drop 1, toy in drop 2 — and the bed is a fixture

**The bed moves to drop 1 and the toy to drop 2**, and the bed is **usable but not takeable**, so drop 1 teaches only `/look` and `/use`. `/take` and `/inventory` wait for the toy in drop 2.

That is a better version of the swap than the one discussed, and it simplifies three things at once:

- **No `max_present` restock column in drop 1.** One bed, present from the moment the drop opens, never consumed. The top-up-to-two rule only matters once items can be carried away, which is drop 2.
- **"One shared bed or one per player" closes itself.** A non-takeable fixture is shared by definition, and the 24-hour cooldown stays per player.
- **Drop 1 is two commands and one object.** The thinnest possible drop that still teaches something, which is what a proof of concept wants.

The reasoning behind the swap, for the record, was stronger than the one originally given.

**The case for the bed first is that the toy is a terrible first lesson.** A new player's very first `/use` is *designed* to fail — the ramp starts at 0% and the first offer is always refused. "The cat ignores it" is exactly what a broken command looks like, and the player has no way to tell the difference. The bed has no probability in it at all: use it, it works, +15. Teaching a verb with an object that always obeys, then introducing one that has to be coaxed, is the right order.

**The case against is that the bed is a thin drop.** Once a day, +15, and nothing until tomorrow. If drop 1 runs three to seven days, the bed gives a player three to seven actions total. The toy, with a ramp and a ten-minute cooldown, gives them something to do repeatedly in one sitting. **The bed is the better lesson; the toy is the better engine.**

**The thin-drop objection still stands and is accepted.** The bed gives +15 once a day and nothing else, so over a multi-day drop 1 a player has three to seven actions. That is fine for a proof of concept whose job is to prove gating and hinting rather than to hold attention, but it is a real constraint on how long drop 1 can run before the toy arrives.

**One carry-over task: the toy's first refusal needs copy that invites a retry.** When the toy lands in drop 2 its first use is still a guaranteed failure, and "the cat ignores it" still looks like a broken command. A refusal line that visibly expects a second attempt is the cheapest fix, and it is a writing task rather than a mechanic.

**Direct-to-inventory is dropped**, and the fixture decision makes the question moot: there is nothing to grant, because the bed never enters anyone's bag.

### The hint rail

**Settled: one mechanism carries every nudge in the game.** Quest notices and tutorial hints are the same shape — a line appended to a message the player was getting anyway — so they share one store and one dispatcher rather than each inventing a flag.

**Storage is one table: the things we have told this player.** `(guild, player, hint_id)`, one row per hint shown, plus the same table holding quest-notified ids. A handful of rows per player. `/qa-reset-player` must clear it, or the whole ladder is one-shot per tester per server.

#### Drop 0

| Trigger | Appended line |
| --- | --- |
| First pet that rolls **friendly** — the same message that awards *Making First Contact* | *This is your first achievement. Check /stats to see achievements and open quests.* |
| First pet that rolls **standoffish** | *Petting affects your relationship with the cat. Check /stats to view it.* |

Both routes lead to `/stats`, which is the right destination: with `/help` deferred, `/stats` is the only place in drop 0 that explains anything.

#### Drop 1

| Trigger | Appended line |
| --- | --- |
| First private message after drop 1 opens, **if the player has not yet run `/look`** | *There is something new here. Try /look.* |
| First `/look` at drop 1 or later | *Specific things can be looked at. E.g., /look cat bed.* |
| First `/look cat bed` | *Things can be used, too. Try /use cat bed.* |
| First `/use cat bed` | — the player earns *Fluffed to Perfection* |

The second line is deliberately generic and will still read correctly if a player's first `/look` happens much later, in the Entryway.

#### The quest notice

Computed rather than tracked. On any private cat message, work out which quests are currently visible and unearned, compare against the ids this player has been told about, and append *"(A new quest is available. Check /stats for details.)"* if there are new ones. `/stats` marks them seen too. This covers both the achievement case and the overnight drop-advance case in one code path, and the visibility computation is the same helper `/stats` already needs.

#### Two rules the ladder needs that the list does not state

**At most one appended line per message.** Otherwise a player who types `/look cat bed` as their first drop-1 action matches *both* "first `/look`" and "first `/look cat bed`", and gets two hints stacked on one reply — one of them telling them to do the thing they just did.

**Firing a later hint marks the earlier ones as shown.** Same scenario: `/look cat bed` should fire the *use* hint and quietly retire the *look at specific things* hint, because the player has demonstrably learned it. Without this rule the earlier hint surfaces later, out of order, as advice to do something already done. The general form — *a hint is retired either by being shown or by being made moot* — is worth building in from the start, because every hint added later will need it.

**One place the copy goes slightly wrong.** A player whose first pet rolls standoffish gets the second drop-0 hint, follows it to `/stats`, and reads *"No completed achievements. Have you met a black cat yet? Try /pet."* They have just met the cat. The instruction is still right, but the question is literally false. Either a second variant for "has petted, earned nothing", or trim the question and keep *"No completed achievements. Try /pet."* for that case.

### The meter — as built, and what V3 changes

The developer's audit of 14 October is the authoritative account of what exists. This section reconciles it with the three changes we want, and flags the four places where the two collide.

#### What is in the code today

| Property | Value | Where |
| --- | --- | --- |
| Range | −100 to +100, **hard-clamped** | `database.py:65`, clamp at `:1163` |
| Starting score | **+50** on a new row, created by `/pet` or `/enter` | `database.py:74` |
| Scope | per (player, server), one column on `users` | `database.py:180` |
| `/pet` effect | **none directly.** It rolls a mood: friendly → **+5**, standoffish → **−5** | `bot.py:84`, `:746` |
| Friendly chance | `80 − 10 × recent_pets`, floored at 0 | `bot.py:103` |
| `recent_pets` | that player's pets in **that server** in the last 10 minutes, counted before this one | `database.py:59`, `:1096` |
| Nightly drift | 00:00 Pacific, **skipped for anyone who petted in that server that day**. At +10 or above lose 10; at −20 or below gain 20; anything between goes straight to 0. Never crosses zero | `bot.py:315`, `database.py:1420` |
| `/stats` | already prints the raw integer, always ephemeral | `bot.py:2491` |
| Readers | `relationship_at_pet` on every `pet_events` row; three achievements. **Nothing else reads the meter** — no content gate, no `present_when`, no exit, no drop | `database.py:1139`, `triggers.py:87` |

Two things this settles that were open questions:

- **The crowding nudge is honest, and it moves.** The fourth pet inside ten minutes is break-even at 50% friendly, and from the fifth the expected change is negative, reaching −5 per pet at eight or more. **Settled: the nudge now fires the first time a pet has a 0% chance of success** rather than at the tenth pet.

  **That is one pet earlier, not four.** 0% is reached when the friendly chance `80 − 10 × recent` hits zero, which is `recent = 8` — the player's **ninth** pet in the window. The current trigger is `recent + 1 >= 10`, the tenth. So the new rule is cleaner to state and lands one pet sooner.

  **If the goal is to prevent inadvertent harm, the trigger wants to be earlier still.** By the ninth pet a player has already lost about six points in expectation. The onset of harm is the **fifth** pet, where the expected change first turns negative; break-even is the fourth. 0% has a real argument in its favour — it is the one moment the cat is unambiguously finished, so the message is maximally true and least likely to read as nagging someone for ordinary enthusiasm. But it is the point of maximum harm rather than its onset, and the nudge is now the only place in the game where the penalty is ever surfaced at all.
- **The decay already floors at zero in both directions**, which is exactly the asymmetry recommended here before anyone read the code. Nothing to decide. It is a *drift toward neutral* rather than a decay downward, and grudges soften at 20 a night while affection fades at 10 — a deliberate 2:1 forgiveness bias worth keeping.

#### What V3 changes

- **Start at 0** instead of +50. One line at `database.py:74` — and `/reset-haunted-house`, which also returns everyone to 50.
- **Remove the ceiling.** The clamp is a SQL `CASE` in the same statement as the arithmetic, so the upper bound comes out while the lower bound at −100 stays.
- **Keep the drift as built.** It already does the right thing at the floor.
- **`/stats` adds a sentence** under the raw figure. Four bands: *"The cat doesn't seem to care about you."* at exactly zero, *"Your relationship is currently negative"* below, *"positive"* above, *"very strong"* at 100 or more.
- **The drift's skip condition widens** from petting to any cat interaction — petting, the toy, the bed, feeding.
- **The public pet line reports the pet, not the relationship.** It branches on the mood roll — friendly or standoffish — and reads the score not at all. See below.

#### The public pet line: the individual pet, not the relationship

**Settled, and it reverses a recommendation of mine that the developer correctly implemented.** The 2f work order flagged this as an open decision and recommended branching on the relationship after the pet, on the grounds that it would give the game *"one rule instead of two"* — the same above-zero test that *Making Friends* used. The code does exactly that at `bot.py:684`.

**That argument has since dissolved on its own.** *Making Friends* and *Trying to Make Friends* are now a single fork at pet 200 rather than a per-pet sign test, so there is no longer a second rule to be consistent with. Nothing is gained by the public line reading the score, and something is lost.

**The line now branches on the mood roll.** Friendly prints "seems to like it"; standoffish prints "does not seem pleased". No comparison against the meter anywhere in that path. Three consequences:

- **It makes the earlier collision disappear rather than needing a fix.** The worry was that a brand-new player at zero would get the negative line, and that exactly-zero had no home. With no score comparison there is no boundary and no zero case. The `>= 0` change and the third string are both unnecessary.
- **Rename the two strings.** `pet.public.positive` and `pet.public.negative` now describe the cat's reaction rather than the state of the relationship, and those names will be misread by whoever next touches them. `pet.public.friendly` and `pet.public.standoffish` match the vocabulary the mood roll already uses.
- **`pet.public.continues` cannot carry a reaction.** The rate limit prints *"{player} continues to pet the cat"* for the second line in a thirty-minute window, which is deliberately flat. So the per-pet rule governs the first public line only, and the second stays a bare acknowledgement. That is fine, but it should be written down rather than discovered.

**One thing it does not buy, correcting a claim made here earlier.** This note previously argued that per-pet branching would let onlookers watch a spammer's reactions deteriorate, and that this would teach by imitation. **It will not.** The rate limit allows two public lines per player per place per thirty minutes, and only the *first* carries a reaction — the second is the flat *"continues to pet the cat"*. So a player who pets twelve times in ten minutes produces exactly one reaction line, posted at the start when their recent-pet count was zero and the friendly chance was still 80%. The deterioration is invisible in public by construction.

**A side effect worth knowing: `pet.public.negative` becomes rare.** A fresh thirty-minute window usually opens after a quiet spell, so the first line of a window is usually rolled at 80% friendly. The negative string therefore fires perhaps one time in five, and when it does it reports a dice roll rather than anything an onlooker could learn from. Under the old relationship-state branching the negative line was at least a stable signal — *this player's relationship is in the red* — which was legible even if less truthful about the moment.

That is an acceptable trade for a line whose job is to describe what just happened rather than to rank players, and the developer's objection to per-pet branching (a well-liked player publicly rebuffed) reads as a moment rather than a verdict under these semantics. But it does mean **the public line now carries no teaching signal at all.** If the crowding penalty should be legible to anyone other than the player incurring it, that needs a different mechanism — which is one more argument for moving the crowding nudge earlier than the tenth pet.

#### Two collisions between those changes and the built behaviour

**1. The drift is deliberately not a counterweight — and the skip condition widens.** **Settled: the drift applies only on days a player fails to interact with the cat at all**, and *interaction* now means petting, offering the toy, fluffing the bed **or** feeding her, rather than petting alone as the code has it today. Showing up protects your score; staying away costs it. The uncapped meter therefore has no ceiling and no tax on an active player, and devotion is cumulative by design — +15 to +25 a day for someone using every lever, which is what makes 250 and beyond reachable.

This also corrects an argument made here earlier. I had claimed the score would settle where daily gain meets daily decay, making the decay function the balance lever. Against this design there is no equilibrium at all, and that is the intent rather than an oversight.

**Three things the widened skip needs.**

**One date column, not four checks.** Stamp a `last_cat_interaction_date` per (player, server) from all four actions, and have the nightly job read that instead of querying pets. One write per interaction, one read per night, and a fifth interaction later is one line rather than a fifth branch in the decay query.

**Attempts count, not just successes.** This needs saying explicitly, because three of the four actions can fail: the toy's first offer is a *guaranteed* refusal, the bed refuses inside its 24-hour window, and a pet can roll standoffish. **Recommended: any attempt stamps the date.** The drift exists to notice absence, and a player who offered the toy four times and was refused four times was not absent. The alternative punishes them twice — once with the refusal, once with the overnight drift — and it would make the guaranteed first refusal actively hostile.

**Feeding needs defining.** It is the one interaction with no mechanic written yet. Whatever the action is — `/use` cat food, giving it to her, meeting the craving — it has to stamp the same column, and it carries a feed counter for *Bowl Half Empty*.

**2. The middle band is not a problem — withdrawn.** This note previously called the drift's middle band the most serious collision and recommended replacing *"go straight to 0"* with *"move 10 toward 0"*. **Those two rules are the same rule**, and the whole concern was a misreading.

Checked across the full −100 to +100 range, the built behaviour reduces to two clamped operations:

- positive scores: `max(0, score − 10)`
- negative scores: `min(0, score + 20)`

The three-band description in the audit is a verbose way of writing that. Inside the band there are never more than nine points to lose, so *go to 0* and *lose 10, floored at 0* land on the same number every time. There is no discontinuity at the boundary either — 9 → 0, 10 → 0, 15 → 5, 20 → 10 is a straight line.

**The only residual is the rate, and it is mild.** A first toy success at +10 does vanish after one idle day, because losing 10 from 10 is zero. But a player petting unhurriedly gains about +9 a day, so an idle day costs roughly what an active day earns — and critically, **any single interaction cancels the day's drift entirely**. One pet protects the whole balance. That is forgiving enough that it needs no change.

**3. Zero now has a line.** Settled: at exactly zero, `/stats` reads *"The cat doesn't seem to care about you."* Four bands in total — that line at zero, *negative* below, *positive* above, *very strong* at 100 or more. Worth noting it is the first thing every player will read about the relationship, and it is doing real work: it frames the climb as earning indifference away rather than as filling a bar.

#### Making Friends and Trying to Make Friends — settled, and the change is to what gets counted

**Settled: the two achievements are one fork at pet 200, not two grinds.** A player pets 200 times; the relationship's sign at that moment decides which they get. **Positive → *Making Friends*. Zero or negative → *Trying to Make Friends*.** Two hundred pets and still at zero is squarely a case of trying.

**This withdraws the boundary change proposed here earlier.** The comparisons stay exactly as built — `> 0` and `<= 0` at `triggers.py:87` — because the question was never really where zero sits. It was what the 200 counts. Nothing in `triggers.py` changes signs.

**What does change is the counting**, and it is a genuine spec change:

|  | As built | As settled |
| --- | --- | --- |
| Counter | Two. Pets where the score was positive; pets where it was zero or below | **One.** Total pets |
| Threshold | 200 *qualifying* pets for each | 200 pets, full stop |
| Evaluated | Continuously, per pet, per achievement | **Once**, at the 200th |
| Outcomes | Both are earnable by the same player over time | **Mutually exclusive.** Exactly one ever fires |

The new shape is better. It reads as a single journey with two possible endings rather than two parallel chores, and nobody has to explain why one player holds both.

**Three things the spec has to say.**

**1. Evaluate at "200 or more and neither held", not "exactly 200".** This is the one that matters. A check that fires only on the 200th pet is fragile — if the bot is down, a race loses the write, or the achievement system is gated off at that moment, pet 201 does not qualify and the achievement can never fire for that player. Phrase it as *on any pet where the total is at least 200 and neither achievement is held, award by the current sign*. Identical in the normal case, recoverable in every other.

**2. The sign is read *after* the 200th pet.** Settled. `relationship_at_pet` stores the score *before* each pet, so this check does not use that column — it reads the score as it stands once the pet's ±5 has applied. It costs nothing, the updated value being in hand at that point, and it means a player is never told the cat adores them in the same breath as a rebuff.

**3. Zero on pet 200 is more likely than it sounds.** The reasoning that nobody will be sitting at exactly zero by their 200th pet is sound against a normal meter, but not against this drift rule: *anything between +10 and −20 goes straight to 0 overnight*. The drift actively parks casual players on exactly zero, so it is a sticky value rather than a passing one. It does not change the outcome — zero goes to *Trying to Make Friends* either way, as specified — but it does mean *Trying* will be commoner than the name's tone suggests, and it is one more reason to look at that middle band.

**One honest note on `relationship_at_pet`.** The Achievement Trigger Spec justified storing it on the grounds that a running tally of qualifying pets could not be reconstructed afterwards. Under a single check at pet 200, the live score is enough and the column is no longer load-bearing for these two achievements. **Keep it anyway** — it is one integer per pet, it is already built, and it still lets the threshold move later or the rule be recomputed. But the spec's stated reason for it is now thinner than it was, and that is worth recording rather than leaving as folklore.

**Two hundred is now roughly twice as easy**, which is worth a glance rather than a change. Previously *Making Friends* needed 200 pets *while positive*, so a player who spent half their time in the negative needed 400 pets to get there. Now it is 200 flat. Against a ten-minute patience window that is still a lot of separate sessions, so the number probably stands.

#### Two content consequences

**The cat's first-pet voice was written against a warm start.** A player at 50 was already half-liked; a player at 0 is a stranger. The blurbs need a pass to make the cat aloof to someone it does not know and warm as the number climbs — and the arc improves, because there is now somewhere to warm up *from*. Note the mood roll itself does **not** read the relationship: friendly chance depends only on recent pets, so this is purely a writing change, not a behaviour one.

**The Story Bible's "a perfect relationship is 100" is no longer true.** With no ceiling, 100 is the *Cat's Best Friend* milestone and nothing more. One line, but it is canon.

#### What this does to the pacing

| Source | Gain | Reaching 100 from zero |
| --- | --- | --- |
| Petting | +3 expected per pet when unhurried, negative past four in ten minutes | \~33 unhurried pets, spread out |
| Toy | +10 per success, \~3.2 attempts each | 10 successes — **90 minutes minimum**, the floor being nine 10-minute cooldowns |
| Bed | +15 per day | **7 days** |
| All three | — | A few days of showing up, which is the window drops 1 and 2 are meant to fill |

Doubling the headroom to 100 turns the earlier 40-minute sprint into a multi-day arc without touching a single magnitude. The toy and bed keep +10 and +15; no rescaling, no daily cap.

### The six new achievements — complete, with all copy

**Settled, including every string.** Six rows, three live from drop 0.

| id | Name | `kind` | Condition | Hook | `since_drop` | Visible when |
| --- | --- | --- | --- | --- | --- | --- |
| `making_first_contact` | **Making First Contact** | secret | First `/pet` that rolls **friendly** | `on_pet` | 0 | never — secret |
| `a_paw_in_the_door` | **A Paw in the Door** | public | Relationship first reaches **50** | relationship change | 0 | has `making_first_contact` |
| `favorite_human` | **Favorite Human** | secret | Relationship reaches **250** | relationship change | 0 | never — secret |
| `persuasive` | **Persuasive** | public | First successful `/use cat toy` | `on_use` | 2 | drop ≥ 2 **and** has `making_first_contact` |
| `fluffed_to_perfection` | **Fluffed to Perfection** | public | First `/use cat bed` | `on_use` | 1 | drop ≥ 1 **and** has `making_first_contact` |
| `bowl_half_empty` | **Bowl Half Empty** | secret | **25** feeds | `on_use` | 3 | never — secret |
| `impressively_bad_luck` | **Impressively Bad Luck** | secret | The cat refuses the toy **4 times running** | `on_use` | 2, with the toy | never — secret |

**Unlock text** — what the player reads on earning it:

- **Making First Contact** — *The cat let you pet her. Don't let it go to your head.*
- **A Paw in the Door** — *You've earned 50 relationship points with the cat. She has noticed you and has decided you may stay.*
- **Favorite Human** — *You reached 250 relationship points with the cat. She has stopped pretending she doesn't like you.*
- **Persuasive** — *Tempted the cat into playing with a toy.*
- **Fluffed to Perfection** — *You fluffed the cat's bed to her standards. Well done.*
- **Bowl Half Empty** — *You fed the cat 25 times and she's still waiting for dinner. Keep going.*
- **Impressively Bad Luck** — *The cat ignored your attempts to play four times in a row.*

**Prompts** — what the three public ones read as open quests, before they are earned. **None carries a terminal full stop**, because the quest notice interpolates the prompt at the end of its own sentence and a prompt that punctuates itself would double the stop there:

- **A Paw in the Door** — *Attain a relationship of +50 with the cat*
- **Persuasive** — *Play with the cat*
- **Fluffed to Perfection** — *Give the cat a cozy nap spot*

#### Making First Contact is the single root, and that simplifies the schema

Every public quest is now gated on *Making First Contact*. That makes a clean spine:

1. Pet the cat. At 80% friendly the first try usually lands.
2. *Making First Contact* fires. Because it is secret it arrives as a surprise rather than as a box being ticked, and it teaches in one event that achievements exist at all — which was finding six from the playtest, where nobody knew they did.
3. Every quest the current drop allows becomes visible at once: *A Paw in the Door* in drop 0, plus *Fluffed to Perfection* from drop 1 and *Persuasive* from drop 2.

**It also retracts a finding from the last revision.** I said `requires` needed any-of semantics, because *A Paw in the Door* was to be visible after *Making First Contact* **or** *Fluffed to Perfection*. Now that *Fluffed to Perfection* itself requires *Making First Contact*, anyone holding it necessarily holds the root, so the disjunction collapses to the root alone. **`requires` can be a single prerequisite after all** — one achievement id — with the drop condition carried by `since_drop`, which is a column that already exists. Two single-valued columns rather than a set and a resolver.

That is worth protecting. The moment one quest needs two unrelated prerequisites, any-of or all-of comes back; keeping the tree rooted at one achievement keeps it out.

#### Three things the spec has to add

**1. Relationship thresholds need a hook that fires wherever the score moves.** Three achievements are score thresholds — 50, 100 and 250 — and the score is written by petting, the toy, the bed and feeding. *Cat's Best Friend* listens on `on_pet` today, which was sufficient when petting was the only lever. It is not any more: a player pushed to 50 by a bed fluff would go unchecked. **Recommended: an `on_relationship_change` hook**, fired wherever the score is written, with all three thresholds registered against it. This is the only genuinely new hook the six rows need — everything else is `on_pet` or `on_use`.

**2. The quest columns move from V3.2 into V3.0.** A public achievement with a visibility prerequisite *is* the quest system: `offered`, `requires`, `prompt`, and `/stats` rendering open goals. That was scheduled behind the writer pass over `kind`. These rows pull a minimal version forward into drop 0, which is now the earliest content in the game.

**3. Becoming visible has to be announced, or the spine does not work.** This is the gap. A player pets the cat, *Making First Contact* fires with its private line and public announcement — and then *A Paw in the Door* silently appears in `/stats`, where they will see it only if they happen to look. **Recommended: append the newly visible quest or quests to the private achievement message**, so earning the root hands the player their next goal in the same breath. Without it the tutorial depends on a player voluntarily running `/stats` with no reason to think anything changed.

#### Where the drops land

**`bowl_half_empty` is drop 3** — when the player first reaches the Entryway, which is where the salmon stash sits behind the coat rack. It is secret, so there is no visibility rule to write; the `since_drop` is the whole gate. It moves earlier only if the cat brings all five cat-food flavours in drop 2, which is still an open option.

**Persuasive closes the gap flagged last revision.** The toy carries drop 2 with a guaranteed first refusal, which is exactly where a player might conclude it is broken. A public quest reading *"Play with the cat"* turns that refusal into a visible objective rather than a dead end.

**Favorite Human supersedes the devotion tiers proposed here**, taking 250; 500 and 1,000 remain available if the climb needs more destinations later. It is also the first content that *requires* the ceiling to be gone, so those two changes now depend on each other.

**Settled at four**, because five is arithmetically impossible: the ramp runs 0%, 25%, 50%, 75%, **100%**, so the fifth attempt always succeeds. Four refusals running has probability 0.75 × 0.5 × 0.25 = **9.4%** — roughly one player in eleven on any given ramp, which is a good rarity for a secret row.

**The consecutive-days achievement is dropped**, which is fine but worth recording: the nightly drift is now the only thing in the game rewarding a return visit, and no achievement names that behaviour.

---

## Notes per drop

> **The notes for drops 1 and 2 below predate the bed-and-toy swap.** The table above is current: drop 1 is the cat bed, drop 2 is the toys. The two sections that follow still read as though the toy came first, and their headings match the old order. For drop 2 the authority is now the **Phase 3b Work Order** and the **Drop 2 copy deck — toys**; treat these notes as the reasoning that led there, not as the spec.

### Drop 0 — The Cat

Three commands and one character. `/stats` shows only the player's own numbers; there is no server view yet and no list of other players.

`/help` has three sections and should fit on one screen. It is also the right place to say, once, that this bot uses slash commands and how to find them — the two Discord-new testers did not know they existed, and then forgot them repeatedly.

**Drop 0 ships without the craving game.** It is unbuilt, and the MVP does not wait for it. That leaves `/pet`, `/stats` and `/help` — three commands and one character — which is thin but is the whole point of the drop. The craving slots in here whenever it is written.

**Two new achievements, both unmissable, both needing text.** *First pet*, and *first time reaching 50 relationship*. Writers to supply the names and unlock lines; placeholders until then. These matter more than they look: *Making Friends* and *Trying to Make Friends* need 200 pets and *Cat's Best Friend* needs 100 points, all three of which are **theoretically** reachable inside drop 0 but unlikely to land before the next drop. Without the two new rows, most players would finish drop 0 having earned exactly one thing.

**The 50-relationship achievement also does quiet structural work.** It puts a named milestone at the point the old meter used to *start* from, which is a clean way to mark that a stranger has become an acquaintance.

**The meter is visible, and `/stats` already prints the raw integer.** Settled: it keeps the figure and gains a sentence — *"Your relationship is currently negative"* below zero, *"positive"* above, *"very strong"* at 100 or more. Three bands, no bar, no percentage, which is right for a number with no maximum.

**Zero has its own line:** *"The cat doesn't seem to care about you."* Four bands with that one, and it is the first thing every player reads about the relationship — framing the climb as earning indifference away rather than filling a bar.

**The empty state is specified, and it carries the tutorial.** `/stats` always shows two headers. Under **Open Quests**, when there are none: *"No open quests"*. Under **Completed Achievements**, when there are none: *"No completed achievements. Have you met a black cat yet?"*

That is a better answer than appending a hint, because the empty log explains itself instead of looking broken. **One suggestion on the last line**, now that `/help` is being skipped: with no help text anywhere, `/stats` and the hint messages are the only places a player learns that slash commands exist at all — and two of the playtesters did not know. *"Have you met a black cat yet? Try /pet."* names the command without losing the voice.

### Drop 1 — Something to Play With

**This is where `/use` is taught, and that is a real improvement on the old schedule.** `/use` previously arrived alongside the Entryway's sixteen things, four of which it worked on. Here it arrives with exactly one object, in a channel with nothing else to try it on, attached to an outcome the player wants. The verb confusion the second tester hit is addressed better by this than by anything in the interface work.

Only the toy arrives in this drop. The household objects move to drop 2, so that drop 1 has one idea in it.

**`/look` in the channel is a drop-1 requirement**, because there has to be a way to see what has dropped in. That makes the channel-as-a-room change load-bearing rather than tidy: `/look` wants a room to look at.

**In the channel, `/look` prints only the item list, under "Items here" rather than "Also here".** Not complex: `also_here.prefix` already exists in `defaults.tsv`, and this needs one override. Cleanest home is a **`look_prefix` column on the room row**, falling back to the default when empty — one column, one cell filled, and the channel is already a room row.

Two consequences worth noting. **The channel needs no `room_text` at all**, which closes the open question about what the channel's description says: nothing, because `/look` there is a list and not a description. And **the empty case needs a line** — both items can be taken, and before the first drop lands there is nothing there, so something has to fill *"Items here:"* with no items.

### Drop 2 — Making a Home

The bed comes first and the household trickle follows: a knit bootie, a wooden rattle, a photograph, a brass key. Every one already exists in `things.tsv`; nothing is authored, things are only placed differently.

**The bed is the better bridge to the house than any of them.** A cat bed implies somewhere the cat sleeps, and the drop's shape is a player accumulating evidence of a home without anyone mentioning one. A brass key and a baby's bootie then raise a question that drop 3 answers.

**Option:** if the cat also brings all five cat-food flavours here, *Charcuterie Board* becomes reachable before the house. Against it: the gourmet can is canonically hidden in the kitchen cake box, so bringing it early spends that reveal.

### Drop 3 — The Door

The quest proposed: **the cat is hungry.** The salmon stash sits behind the coat rack and is named only in the coat rack's description, never in a listing. A player has to read prose, look at a thing, find what the prose hid, take it, and give it to the cat.

That teaches the single most important habit in the game — descriptions contain findable things — and it ends by feeding a cat the player has now spent two drops getting to know, which is a better payoff than it was when the cat was a week-old acquaintance.

The room starts with four things. The Entryway holds sixteen, of which four do anything, and the testers stalled in it.

### Drop 4 — The Rest of the Entryway

Two quests worth running here:

- **The Alexa reminder** (*Passing a Message to David*). This is where David gets introduced, by name and with context, before any flavour text assumes him. It fixes the exposition gap the Discord-experienced tester named.
- **The staircase.** A group objective requiring several players to place planks. It gates drop 6, so the thing that opens the upstairs is the server working together rather than the calendar.

### Drop 5 — Downstairs

The largest single expansion, and the one that most needs engine-derived bolding and autocomplete to be in place first. Four rooms at once is close to the flood the testers met; the difference has to come from the interface work, not from the content being smaller.

### Drop 6 — Upstairs

Gated on `stairs_repaired`, which is already server-wide in the Functional Spec. If the server never repairs the stairs, this drop does not open — worth deciding whether that is acceptable or whether there is a date-based fallback.

### Drop 7 — The Secret Library

Already fully specified in Phase 2e, including the four custom departure and arrival lines that keep the route hidden. Nothing in `/help` should mention it.

---

## Things this schedule surfaces

**The Halloween channel is not a room, and now it needs to be.** Drops 0 through 2 all happen in a place the room model does not contain. `/pet` already resolves there as a special case, but a thing a player can `/use` is new. **Cheapest fix by a distance: add the channel as a room-like row** with no exits, never listed, never reachable by movement. Toys and beds then become ordinary things with an ordinary `room_id`, `/use` resolves through the existing path, and nothing is special-cased. The alternative — a parallel resolution path for channel objects — means maintaining two of everything for three drops.

**The craving game's reaction handler does not exist, and two earlier plans assumed it did.** Drop 1's toy claiming and the drop-0 craving guess were both described as reusing one reaction handler. Nothing is built, so neither is reuse. Drop 0 ships without the craving; drop 1 avoids the problem by making the toy a fixture rather than a claimable item.

**Existing players already sit near 50, and the start becomes 0.** Two test servers have real rows. When the start value changes, either those rows get rebased, or new and old players are on incompatible scales and every relationship achievement is meaningless across the mix. `/reset-haunted-house` is the blunt answer and it is available — it is guild-scoped and returns everyone to the start value — but it also wipes inventories and achievements. Worth deciding per server rather than globally.

**Random appearance is already built.** `restocks.tsv` carries `thing_id`, `placement`, `amount`, `times_per_day`, `first_day`, `every_n_days`, `window_start`, `window_end` and `config_key`. Toys and beds are restock rows pointing at the channel. No new scheduling code, and the spawn rate becomes an admin-tunable number on day one rather than a deploy.

**The meter change touches more than the meter.** Starting at 0 inverts the two petting-achievement boundaries, retires the Story Bible's "a perfect relationship is 100", changes the `/stats` display from a bar to a tier, makes the decay function the real balance lever, and sends the 2f pet blurbs back for a voice pass. None of it is expensive; all of it is easy to miss. The Achievement Trigger Spec in particular carries a dated decision whose stated rationale is now false, so it needs editing rather than merely re-reading.

**Five new pieces of per-player state now, and none is a boolean:** the toy ramp counter, the toy cooldown expiry, the last bed fluff, the last cat-interaction date, and the feed count. That is past the point where "a few columns on the player row" is obviously right — three was proportionate, five is the shape of a small per-player key-value table, and a sixth is coming the moment anything else is counted. Worth deciding now rather than after the fifth column is added.

**The original three, for reference:** the toy ramp counter, the toy cooldown expiry, and the last bed fluff. The existing per-player states (`library_found`, `drawer_unjammed`) are flags, and the Functional Spec deliberately declined a `player_thing_seen` table. Three columns on the player row is the proportionate answer; a general per-player key-value store is not needed yet, but is what this becomes if a fourth and fifth arrive.

**The drop numbering collides with the content files.** `achievements.tsv` has `since_drop = 1` on all 35 rows, and `drops.tsv` has a single launch row. If launch is drop 0, either the files renumber or drop 0 maps to `since_drop = 1` and this table is off by one against the data. Going from six drops to eight makes settling it more urgent, not less.

**Initialization has to become incremental.** `/initialize-haunted-house` currently builds nine threads in one go. Drops 0 through 2 have no rooms at all, drop 3 has one, drop 5 adds four. With three room-less drops now rather than two, threads created at launch would sit unused for a week or more — and Discord archives idle threads, shortening the timer as a server approaches its limit. The admin command becomes per-drop, or becomes one command that opens whatever the current drop entitles.

**`/help` is a content file, not a string.** It has sections, each gated to a drop, each needing writing. Two of the new sections — Playing, Looking after the cat — are the first help text most players will ever read.

**`/drop` is now alone in drop 4.** `/use` moved to drop 1, so a player can acquire a toy in drop 1 and cannot put it down until drop 4. For a non-consumable toy with `max_per_player = 1` that is probably fine, but it is worth one look.

---

## Open questions

> **Four of the questions below have since been settled, and one line in the closed list is superseded.** Settled: **1** — bed in drop 1, toy in drop 2, and the bed is a fixture; **2** — *Impressively Bad Luck* is four refusals running, at 9.4%; **6** — the ramp resets on success and cooldown attempts do not advance it; **7** — the bed is a shared fixture and never enters a bag. In the closed list, *"toys and beds are inventory items maintained at two in the channel"* now applies to toys only. The **Phase 3b Work Order** carries the current version of all of these.

**Closed since the last revision:** existing test-server rows will be reset, so the start-value change carries no migration; the drift's middle band was never a problem and that finding is withdrawn; the nightly drift skips any day with a cat interaction, widened from petting alone; `/stats` at zero reads *"The cat doesn't seem to care about you"*, with a specified empty state for both headers; the quest-available notice rides the first private cat message after a quest becomes visible; the crowding nudge moves to the first 0% pet; `/advance-game` is the command name; toys and beds are inventory items maintained at two in the channel; `/look` in the channel prints *"Items here"* and no room description; `/help` is deferred; *Impressively Bad Luck* is in; the consecutive-days achievement is out.

**Still open, in rough order of consequence:**

1. **Bed first or toy first in drop 1?** The bed is the better lesson — a verb that always obeys — and the toy is the better engine. Recommended: swap to bed-first, and write the toy's first refusal to invite a retry.
2. **Does *Impressively Bad Luck* become four refusals in a row?** Five is impossible: the ramp guarantees the fifth attempt succeeds. Four has a 9.4% chance, which is a good rarity, and the copy needs the number changed.
3. **What is the feeding action, does it have a cooldown, and does it move the relationship?** Deferred out of the first spec — feeding is not reachable before drop 3 — but it still needs designing before V3.2, and *Bowl Half Empty* at 25 feeds with no cooldown is a two-minute grind given that cat-food sources cannot run out.
4. **Should the crowding nudge be earlier than the first 0% pet?** 0% is the ninth pet; harm starts at the fifth. Settled as 0% for now, and worth one more look because the nudge is the only place the penalty is ever surfaced.
5. **What fills "Items here:" when the channel is empty?**
6. Does the toy ramp reset after a success, and do cooldown attempts advance it? Recommended yes and no respectively.
7. One shared bed, or one per player? Now narrower, since beds are inventory items — the question is really whether a bed in a player's bag is theirs alone.
8. Does the cat bring all five cat-food flavours in drop 2, spending the gourmet reveal early?
9. Drop 6 is gated on a group repair. Is there an admin override if the server never does it?
10. Do drops 5 through 7 need bolding and autocomplete shipped first, or can they run without?
11. What are `/start-game <channel>` and `/advance-game` allowed to do on a second run, a second channel, or backwards?
12. The achievement calendar, now that Halloween is not the only payoff point and a winter-solstice repair is on the table — with the writers.
