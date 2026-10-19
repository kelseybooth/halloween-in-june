# Phase 3b Work Order — Drop 2, the toy

*Draft, 19 October. The second release in the V3 line. 3a proves gating and hinting on two drops and one object; 3b is the first release that adds an object players compete for, carry and put down.*

## What this is

Drop 2 introduces **two toys, three commands and a reason to come back twice a day**. It is deliberately the cheapest release in the plan: it adds two toy rows, one restock row, three player columns, three achievements and a six-rung hint ladder on top of machinery 3a has already built.

It is also the release where the drop machine gets its second honest test. 3a advances from drop 0 to drop 1 and reveals one fixture. 3b advances to drop 2 and has to reveal three commands, one takeable object and two achievements — while keeping nine rooms, 140 things and 33 achievements invisible.

## Prerequisites

1. **3a is shipped and its acceptance pass is green.** Everything below assumes `server_now()`, the per-server drop pointer, `/start-game`, `/advance-game`, guild-scoped registration via bulk overwrite, the channel-as-a-room row, the reworked meter and the hint rail all exist.
2. **The drop 2 content file edits are applied** — their own tab, run separately. Nothing here works against the files as they stand.

## Scope

| In | Out |
| --- | --- |
| `/take`, `/drop`, `/inventory` | Every room, `/go`, `/enter`, `/help` |
| The feather wand and the crinkle ball, two toy rows | The other twelve toys in the bank |
| The play ramp, cooldown and award | Restock **draw weights** — two toys, deliberately equal |
| `max_present`, scoped to the toy class | The catnip buff, the Amazon box |
| The bed stash, first fluff only | Recurring bed yields, and a drain for loose things |
| *Persuasive* and *Impressively Bad Luck* | The toy-collection achievement — see §12 |
| A public play line in the channel | Feeding, `bowl_half_empty`, the craving game |
| A six-rung hint ladder |  |

## 1. Three new commands

All three are **guild-registered on the drop 2 advance**, through the same bulk-overwrite call 3a uses. No global registration.

**`/take <thing>`** — resolution scoped to **the room only, never the inventory**. The room here is the channel row 3a built. On success, decrement `room_contents`, increment `player_inventory`, reply publicly.

| Situation | Reply |
| --- | --- |
| `takeable = no` | the thing's `take_fail`, else `take_fail.fixture` |
| already at `max_per_player` | **`take_fail.already_carried`** — see the note below |
| nothing in the room by that name | `take_fail.absent` |
| nothing in the room, but the name matches something carried | `take_fail.already_carried` |

**One engine line.** The Functional Spec routes the `max_per_player` refusal to *the thing's own* `take_fail`, with no default. Add the fallback to `take_fail.already_carried` — *"You're already carrying the {name}."* — which reads correctly and means no future capped thing needs a bespoke string either.

**`/drop <thing>`** — resolution scoped to **the inventory only, never the room**. Decrement `player_inventory`, increment `room_contents`, write `container_id` **empty**. Public reply. Refusals: `drop_fail.not_carried`, and `drop_fail.undroppable` where `droppable = no`.

**`/inventory`** — private. Groups by thing and counts, using the same `x{n}` form as the room listing. A direct read of `player_inventory`, not a grouping of instance rows.

**Build the two-pass resolver to the Functional Spec's full shape, because drop 2 now exercises it.** The two toys share the aliases `toy` and `cat toy`, so `/take toy` with both in the channel matches two distinct things and has to reach `ambiguous.match` rather than resolve to whichever row sorts first. That moves the ambiguity path from a drop 3 concern to a drop 2 one, and a resolver written for the single-candidate case is a rewrite rather than an extension.

## 2. The two toys

**Two rows — `feather_wand` and `crinkle_ball`, equally likely to draw** — each `takeable` yes, `droppable` yes, `max_per_player` 1, in the channel, `since_drop` 2. Full column values are in the content edits tab.

**The restock row draws from the class, not from a named thing.** Its `thing_id` is the selector `type:toy` rather than `feather_wand`, so one row keeps the channel topped up with either toy and a third toy row later needs no restock change. The engine work is a uniform pick over the eligible toys — the same helper the bed stash in §8 needs — and it is where draw weights go when a toy is meant to be rarer than another. The content edits tab records the fallback, two rows at two placements a day each, if this is more than 3b should take on.

**It must be carried to be used.** `/use feather wand` on a wand lying in the channel replies with the new `use_fail.not_carried` default — *"The {name} is right there. You would have to pick it up first."* Without this, `/take` has no purpose in the drop that exists to teach it.

**But the carry check is keyed on `takeable`, not on `/use`, and getting this wrong breaks two things.** The rule is: a thing with `takeable = yes` that the player is not carrying refuses with `use_fail.not_carried`; **a thing with `takeable = no` is used where it stands and is never carry-checked.** Written as a property of `/use` instead, the check makes every fixture permanently unusable — including the cat bed, which 3a already ships and which nobody can pick up, and the Amazon box in drop 3, whose entire easter egg is `/use` on a thing you were never meant to carry. The bed is the proof the rule already works this way; the box inherits it rather than being an exception to it.

## 3. The ramp

Precisely, because every clause here is load-bearing:

- **0% on the first attempt**, +25 percentage points per failed attempt, so 0 / 25 / 50 / 75 / 100.
- **Reset to 0 on success.**
- **A 10-minute cooldown after a success.**
- **Attempts during the cooldown advance nothing** — they are refused by the cooldown and leave the ramp where it is. This is what stops a player banking four refusals during a cooldown and converting the instant it lifts.
- **The ramp is per player per server, not per toy.** It means *her willingness to play with you right now*. Toys are interchangeable keys.
- **The cooldown is hers, not the toy's**, for the same reason and on the same scope.

**Three new columns on the player row:** the ramp counter, the toy cooldown expiry, and the last bed fluff (which 3a already added). These are the first per-player values that are not booleans.

**Row-driven, not special-cased — the one instruction in this order worth being emphatic about.** The ramp, the cooldown and the award live on the player. A toy's identity is nothing but a row with `type = toy`. With only two toys the cheap implementation is a pair of `if thing_id == …` branches, and that makes toy number three an engine change instead of a TSV row. Thirteen toy rows are already written and waiting.

## 4. The award, and the drift

**A successful play is +10** to the relationship score, through the same write path as the bed's +15, so `on_relationship_change` fires and the threshold achievements see it.

**Every play attempt stamps `last_cat_interaction_date`** — successes, ramp refusals and cooldown refusals alike. Attempts count, not just successes: the first attempt is a guaranteed refusal, and a player whose only interaction that day was an honest attempt should not be hit by the nightly drift.

## 5. The public play line

**A successful play posts publicly in the channel.** It is the best moment in the drop and the only thing that makes other players visible to each other in a room-less phase.

**Refusals stay private.** With the ramp as specified, the expected attempt of a first success is 3.2, so a player sees roughly 2.2 refusals per success. Public refusals would bury the channel under a cat declining to move.

**Its own rate-limit budget**, same shape as the pet line's — two per (player, place) per 30 minutes, in memory. A separate budget rather than a shared one, so that a player who has just used their pet-line allowance still gets a public line for the rarer and better event. In practice the limit will almost never bite: the 10-minute cooldown already caps successes at about three per half hour.

## 6. Refusal variant selection

The copy deck supplies **twelve** generic play refusals, because a player reads roughly 2.2 of them per success and one string would become the most repeated line in the game inside a week. Text resolution today returns exactly one row per `(entity, state, since_drop)`, so this is new.

**Numbered keys, picked uniformly at random.** `use_fail.toy.1` through `use_fail.toy.12` in `defaults.tsv`; the engine collects every key matching `use_fail.toy.*` and chooses one per refusal. Adding a thirteenth is a row.

**Do not pipe-separate variants inside one cell.** It is the obvious cheap answer and it is a trap: the writers review these decks as tables, `|` is the table delimiter, and the first writer edit would silently split a refusal in two.

The wand's own `use_fail.cooldown` is a per-thing string and overrides the default. It carries no `{time}` token — the writers cut it deliberately.

**The other half of a toy's text: the success line is never shared.** The refusals rotate and generalize, but the success is the payoff and the whole reason a player cares which toy turned up. A blank `use` cell does not error — it falls through to `use.default`, *"You turn the {name} over in your hands. Nothing obvious happens."* — so a toy shipped without its own success line quietly tells the player that playing with the cat does nothing at all. **The loader should refuse to start on a `type = toy` row with no `use` text.** That check is the only thing that catches this before a player does.

## 7. `max_present`, scoped to the toy class

The new restock mode, and the only substantial engine work in this release.

**The rule is keep two toys in the channel**, not keep two of each toy. The cap counts by class — `type = toy` — rather than by `thing_id`. With drop 2's two rows the per-row reading already allows four toys in the channel; with the thirteen rows already written it allows twenty-six, and turns `Items here:` into a wall of nouns. Build the right one now, while it costs nothing to choose.

**Player-caused placement is exempt.** `/drop` already ignores the cap, and the bed stash must too. The cap governs the *scheduler*, not the world: a player who drops a third toy has put a third toy there, and nothing should tidy it away.

**Fill toward the cap, never exceed it.** Whenever fewer than two toys are present, more appear at random times inside the restock window. This is a better rule than a rate, because the channel self-regulates: a quiet server keeps two sitting there and a busy one keeps getting fresh ones.

**Draw weights are out of scope.** Drop 2's two toys are deliberately equal, and a uniform pick over the eligible toys needs no weight column. The column and the weighted draw arrive with the first toy meant to be rarer than another, and the copy deck carries the tier assignment for when they do.

**One column to add now that nothing in this release reads: `placed_at` on `room_contents`.** Write it wherever a thing is placed — the restock scheduler, `/drop`, and the bed stash. It is the prerequisite for the toy drain, which is what stops the channel deadlocking once there is more than one toy: without a placement timestamp there is no way to tell a toy that arrived an hour ago from one nobody has wanted for a week. It costs one column and three write sites here, and it cannot be backfilled later for things already sitting in a channel. The mechanism it serves is specified in the **Toy rotation (future drop)** tab and belongs to whichever release adds the second toy.

## 8. The bed stash

A writer's idea, and it fills the hole drop 2 opened when the Amazon box moved to the Entryway: without it, the channel holds toys and nothing else, and a player who plays one into its cooldown has nothing left to reach for.

**A player's first successful fluff in drop 2 dislodges one of drop 2's two toys, chosen at random, onto the channel floor.** Later fluffs yield nothing in this release.

- **Onto the floor, not into the bag.** It teaches `/take`, which is this drop's whole lesson: fluff the bed, something falls out, pick it up. It is public, so the next person along can take it instead. And it needs no new placement code — incrementing `room_contents` is what `/drop` and the scheduler already do.
- **Exempt from `max_present`**, per §7.
- **Only on a successful fluff.** A fluff refused inside its 24-hour window yields nothing.
- **Bounded by construction.** One object per player, ever, so it cannot silt the channel however many players a server has.

**The yielding fluff posts publicly, and that post replaces the ordinary public fluff line rather than adding to it** — one fluff, one public line. The string is `bed_yield.public` in the copy deck §8 and carries `{player}`. One thing to confirm before building: if the bed's ordinary fluff is private today, which the Functional Spec implies by making `/use` on a thing private except the staircase plank, then this is the bed's *only* public line and there is nothing for it to replace.

**The detection has a trap in it, and it will silently break the tutorial for exactly the people testing it.** The obvious implementation is *"first fluff ever"*, read off `last_bed_fluff` being null. But every drop 1 tester has already fluffed, so their first fluff is behind them and they get nothing — and drop 1 testers are precisely who will be on the server when drop 2 opens.

**The fix needs no new column.** Fire when `last_bed_fluff` is null **or earlier than this server's drop 2 arrival timestamp**, which `server_drops` already records because `/advance-game` is a manual drop. One comparison, and it means "their first fluff in drop 2" rather than "their first fluff ever".

**The bed needs no new text.** A `cat_bed` `use` variant at `since_drop = 2` was reserved for the "something fell out of it" line and has been dropped — `bed_yield.public` and `hint.bed_yield` carry it between them, and the drop 1 fluff reply stays as it is on every server. One consequence worth recording: `(entity, state, since_drop)` resolution therefore gets no live exercise against already-shipped content in this release, so the first drop that genuinely overrides an existing string will be the first real test of it.

Later, once there is a drain for loose objects, this opens up to recurring low-chance yields — and the better version gives up the *unusual* toys rather than another drop 2 toy, so the restock and the bed have distinct characters. Not this release.

## 9. Three achievements

|  | *Persuasive* | *Impressively Bad Luck* |
| --- | --- | --- |
| `kind` | public | secret |
| `since_drop` | 2 | 2 |
| Hook | `on_use` | `on_use` |
| Fires on | the first successful toy play | four consecutive refusals |
| Prompt | Play with the cat | — secret, no prompt |
| `requires` | *Making First Contact* | — |

**`Impressively Bad Luck` needs no counter of its own, and this is worth spelling out before someone builds one.** The ramp already *is* the consecutive-refusal count: it starts at 0, increments only on a failed attempt, and resets to 0 on success. So **a ramp of 4 is exactly four refusals in a row** — the 0%, 25%, 50% and 75% attempts all missed. Cooldown refusals advance nothing (§3), so they cannot contribute, which is the right behavior and falls out for free rather than needing a rule.

The probability is 0.75 × 0.5 × 0.25 = **9.4%**, which is a good rarity for a secret row. Five in a row, as originally written, has probability exactly zero: the fifth attempt is at 100%.

**One omission to fix here, found while drafting the collection achievements.** Nothing else in 3b needs a history of plays, so as drafted there is nowhere to ask *how many distinct toys has this player played with* or *how many times* — the ramp and the cooldown are counters on the player row, not a record. **Write a row per successful toy play to `thing_uses`**: player, `thing_id`, timestamp. It is one insert in the play handler, it is the table the Functional Spec already uses for cooldowns, and it is what makes all three toy-collection achievements a single query over a single table rather than three bespoke counters. Without it none of them can be computed, including the two the copy deck has already settled.

**And a third, now in scope.** It is the only collection achievement that can be earned in the room-less phase — the other two need variety, and drop 2 has one toy — so it is the only thing in this release that rewards coming back across days rather than within a session. On top of the `thing_uses` insert above it costs one row in `achievements.tsv` and nothing else.

| Field | Value |
| --- | --- |
| `achievement_id` | `tireless` — writers to name |
| `kind` | secret |
| `since_drop` | 2 |
| Hook | `on_use` |
| Condition | **Twenty-five successful plays**, any toy, cumulative — `COUNT(*)` over the toy rows in `thing_uses` |
| Test | *twenty-five or more and not held*, never *exactly the twenty-fifth* |

**Successes, not attempts.** At 3.2 attempts per success, twenty-five successes is about eighty attempts. Counting attempts would reward the spamming the ramp and the crowding penalty exist to discourage.

**It cannot be farmed in a sitting, which is the number's justification.** The ten-minute cooldown after each success puts a hard floor of four hours ten minutes of continuous play on it, so in practice it is a week of a few plays a day.

Copy is in the Drop 2 copy deck §5. All three achievements in this release now read the same table: a plain count at 25 here, and distinct counts at 5 and 13 for the two that arrive later.

### The three collection achievements share one shape, and 3b sets it

`tireless` is the only one that can fire in this release, but it is the first of three, and the rules below govern all of them. Getting them right once here is what makes the later two a content change rather than engineering.

- **One table, three queries.** All three read the toy rows of `thing_uses`: a plain `COUNT(*)` at 25 for `tireless`, a `COUNT(DISTINCT thing_id)` at 5 for `easily_amused`, and the same distinct count at `toy_set_total` for `whole_toy_box`. No per-achievement counters.
- **The total is declared, never derived.** Seed **`server_config.toy_set_total = 13`** in this release. A row count over `things.tsv` reads as 2 while only drop 2's two toys exist, which would fire `whole_toy_box` on a player's first successful play — the exact failure the declared number exists to prevent. Declaring it now also means the figure is agreed once rather than invented by whoever builds a later drop.
- **N or more and not held, never *exactly* N.** A player can cross two thresholds in one session, be handed toys by QA, or come back after a long absence. Same shape the implementation plan already specified for the pet-200 fork.
- **Award once, never revoke.** Raising `toy_set_total` later must not take `whole_toy_box` back from anyone already holding it.
- **Never show progress.** All three are secret and `/stats` lists only earned achievements, so no player ever sees *3 of 13* — which is correct, because the total counts toys that do not exist yet. A progress line would leak how much game is still coming.

**What stays out of 3b, and why that is deliberate.** The `achievements.tsv` rows for `easily_amused` and `whole_toy_box` are **not** added in this release, because neither can carry a truthful `since_drop` yet: one belongs to the drop that brings the fifth toy, the other to the drop that brings the last, and neither drop exists in `drops.tsv`. A placeholder value would additionally require the loader to tolerate a `since_drop` with no matching drop row, which nobody has checked. Each row is a one-line content change once its drop is known, so deferring costs nothing — while shipping a dangling `since_drop` could cost a failed start.

## 10. The hint ladder

Six rungs. Conventions from 3a hold: the game's voice, italicized, prefixed **Hint:**, one mechanism for all of them, **at most one hint per message**, and a hint is retired by being shown or by being made moot. The invariant stands too — **never recommend an action the player has already taken**.

| # | Fires on | Precondition | Teaches | Key |
| --- | --- | --- | --- | --- |
| 0 | drop 2 opening — publicly with the announcement, privately as the fallback | a **takeable** toy is in the channel **and** the player has done none of `/look`, or `/look`, `/take`, `/use` on a takeable toy | that something changed | **reuses `hint.something_new`** — not a new string |
| 1 | the fluff that dislodges a toy | none — the yield is once per player | that something appeared | `hint.bed_yield` |
| 2 | the player's first `/look` after drop 2 | a **takeable** toy is in the channel **and** the player has not done `/look`, `/take` or `/use` on a takeable toy | that specific things can be looked at | `hint.look_toy` |
| 3 | the player's first `/look` at **any takeable toy** after drop 2 | a **takeable** toy is in the channel **and** the player has not done `/take` or `/use` on a takeable toy | `/take` | `hint.take_toy` |
| 4 | the player's first **successful** `/take` of **any takeable toy** | the player has not done `/use` on a takeable toy | `/use` | `hint.use_toy` |
| 5 | the first `/use` on any toy refused because the player is not holding it | first occurrence only | that a toy has to be held | `hint.hold_to_use` |

**Capitalized after the label**, matching drops 0 and 1 — *Hint: There is something new here. Try /look.* The label is not part of the stored string.

**Rungs 0 and 2 through 4 form one chain**, which is why the order matters more than usual: `something_new` points at `/look`, `/look` earns the hint pointing at `/look <toy>`, that earns `/take`, and that earns `/use`. Each rung's precondition is the previous rung's completion, so a player who skips ahead on their own is never told to do a thing they have already done.

**None of those three rungs names a toy, because drop 2 ships two of them.** The feather wand and the crinkle ball draw against the same two channel slots, so a hint naming one by name can point at a toy that is not present — and the player's first guided action would come back `take_fail.absent`, which is the worst available outcome for the release that is meant to prove the rail works. Hence `{name}` in the text, and **preconditions that count the verb rather than the verb plus a noun**: *has not taken any takeable toy*, not *has not taken a feather wand*. That is also what keeps the drop 0 invariant true — a player who took a crinkle ball has learned the lesson, and the rail must stop telling them to take a wand.

**`{name}` has two sources, and this is the detail most likely to be built wrong.** In rungs 2 and 3 it is **a takeable toy currently in the channel**, resolved when the hint fires rather than when the drop opens. In rung 4 it is **the toy the player has just taken**, because they are holding it.

**Only takeable toys count, anywhere in the rail.** Filter the candidate set to `type = toy` **and** `takeable = yes`, in the preconditions and in the `{name}` lookup. The Amazon box is a fixture: a player who somehow reaches the Entryway before the rail has finished must not be offered the box as the subject of *Try /take* — which would refuse with `take_fail.fixture` — and looking at the box must not count as satisfying a rung. Rung 5 needs no filter, since a fixture is never carry-checked and that refusal can only arise from a takeable toy.

**One hint per message still holds, and drop 2 creates the first real collision.** `hint.look_specific` from drop 1 — *"Specific things can be looked at. Try /look cat bed"* — and `hint.look_wand` are both eligible on the first `/look` of any player who never looked at the bed. **The newest drop's hint wins**, because it points at content the player has not seen; the bed hint is not lost, it fires on their next `/look` if still unsatisfied. The existing invariant covers everything else: a hint is suppressed once the player has done what it recommends.

**These are new keys, not drop-2 wordings of old ones**, because `defaults.tsv` carries only `key` and `text` — no `since_drop` — so an existing hint cannot acquire a second version. Cheaper than adding the column; the cost is that the hint set grows per drop.

**Tokens:** `hint.look_toy`, `hint.take_toy`, `hint.use_toy` and `hint.hold_to_use` all carry `{name}`, and `bed_yield.public` carries `{player}`. Neither `{toy}` nor `{user}` exists.

### What this ladder deliberately does not do

Three rungs from the first draft of this section are gone, and two of the omissions are judgement calls while one is a risk.

**No `/inventory` or `/drop` hint.** Drop 2 registers both commands and nothing now tells a player they exist. Acceptable if the intent is that the house teaches them later.

**No retry hint after a ramp refusal, and this is the one to watch.** The first play attempt is a guaranteed refusal — the ramp starts at 0% — and the refusal copy is written, deliberately, to promise nothing. With no retry hint, a player's introduction to the toy is a failure with nothing anywhere indicating that trying again *is* the mechanic rather than a dead end. Rung 5 does not cover it: that is the not-carried case. If playtest shows players trying once and stopping, this is the first thing to add back.

Wording for all of these lives in the Drop 2 copy deck §8.

## 11. QA additions

3a's set stands. Four need extending:

- **`/qa-cooldown <member> clear`** must now clear the toy cooldown **and** reset the ramp, as well as the pet window.
- **`/qa-state`** must be able to write the ramp counter directly. Setting it to 4 makes the next attempt a guaranteed success; setting it to 0 replays the guaranteed first refusal; setting it to 4 and failing is *Impressively Bad Luck* in one call. That is the whole mechanic exercised without farming, and it is the argument for `/qa-state` being generic rather than a fixed list of flags.
- **`/qa-spawn <thing>`** earns its place this release: placing either toy without waiting for a restock window.
- **`/qa-reset-player`** must clear the three new player columns, `last_bed_fluff`, **and** the hints-shown rows — or the six-rung ladder is testable once per human.

* **The ambiguity prompt needs a case of its own,** because drop 2 is the first release that can raise it. `/take toy` with both toys in the channel must list both and resolve on the follow-up; `/take toy` with only one present must resolve straight away, with no prompt.
* **The play history needs a QA write path,** or *Tireless* costs twenty-five successful plays per test run. Either `/qa-state` can set the play count, or it can insert `thing_uses` rows directly — whichever is cheaper, but one of them has to exist before the achievement is testable.

## 12. Definition of done

1. `/take`, `/drop` and `/inventory` appear within seconds of `/advance-game`, and are absent on a server still on drop 1.
2. The two test servers sit on drop 1 and drop 2 simultaneously with different registered command sets.
3. `/take` in the channel finds the feather wand and the crinkle ball and nothing else. Every other name from the toy bank and from the house replies `take_fail.absent`.
4. The ramp walks 0 / 25 / 50 / 75 / 100 under `/qa-state`, resets on success, and is left unchanged by attempts inside the cooldown.
5. Two toys are maintained in the channel and a third never appears from the scheduler — but a toy a player drops stays dropped.
6. A player whose last fluff predates the drop 2 arrival gets one of the two toys on their next fluff. Their second fluff the same day is refused and yields nothing.
7. All six hint rungs fire in order, once each, at most one per message, and `/qa-reset-player` makes them fire again.
8. *Persuasive* fires on the first success; *Impressively Bad Luck* at a ramp of 4; *Tireless* on the twenty-fifth successful play, with the play history written straight rather than farmed. None of the three is reachable on drop 1.
9. **The leak test, which is the one that matters.** Nothing from drop 3 is reachable *or mentioned*: no room, no `/go`, no `/enter`, no bank toy findable by any name, no refusal pointing at a verb that does not exist yet, and no later-drop quest in `/stats`.

## 13. Known gaps, deliberately left

- **Restock draw weights.** Drop 2's two toys are deliberately equal, so there is nothing to weight yet.
- **The toy-collection achievement.** Its target is every toy *planned for the game* rather than every toy arrived, so it cannot be earned until the last toy's drop and is not pre-house content. It needs a **declared total** — `toy_set_total`, seeded at 13 — rather than a count of `things.tsv` rows, which would read as 1 and fire it on the first successful play. Award once, never revoke, and never show progress. See the copy deck §5.
- **The catnip buff.** Settled in shape and size — **+25 percentage points on the friendly chance, three charges, lapsing after five minutes, not re-appliable for thirty** — and parked in the copy deck with its conditions. Any `/pet` spends a charge whether the cat is friendly or not, and the buff is added to the raw `80 − 10 × recent_pets` before the floor at 0. It lands on a toy that has no drop yet, so none of it is built in 3b.
- **The Amazon box.** Drop 3, in the Entryway, as an easter egg nobody is told about.
- **A drain for loose objects.** The stash is bounded at one per player, so this release is safe. The moment recurring yields arrive, *"the cat sends one away"* stops being flavor and becomes load-bearing. The mechanism is now written up in the Toy rotation (future drop) tab, and this release lands its one prerequisite, the placed\_at column in §7.
- **Feeding, `bowl_half_empty`, and the craving game.** All unreachable before drop 3 or unbuilt.
- **The fourth per-player column question.** Three columns was called proportionate; the catnip buff would be the fourth and forces the per-player-state-table decision deliberately rather than by drift. Nothing in 3b crosses that line.
