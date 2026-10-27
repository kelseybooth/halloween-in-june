# Feeding design (drop 10)

*Feeding was the one cat interaction with no mechanic written. Drop 10's whole quest ends in a feed, so this had to be settled before the drop 10 work order could be written. Decisions taken 20 October; the arithmetic in section 4 is the part that needs other people to look at it.*

## What is settled

| Question | Settled |
| --- | --- |
| The verb | `/use <food>`. Effectively pre-decided — `bowl_half_empty` already fires on `on_use` |
| Cadence | **Hunger as a state**, not a bare cooldown. She is hungry or she is not, and feeding a sated cat is refused |
| How hunger returns | **Eight hours since her last meal, per player.** Timezone-neutral, one timestamp |
| What a feed is worth | **+10**, parity with a toy success |
| Is food consumed | **Yes — on success only.** A refusal costs nothing |
| The 25-feed achievement | 25 stands. The grind is accepted, and mostly dissolves anyway |
| Drop 10's quest payoff | **A new eighth achievement** for the first feed, public and prompted |
| Flavors | Flavor-blind, permanently unless someone argues otherwise. The five flavors are collection content for Charcuterie Board, not feeding variants |

**Two of those answers cancel the problem the third was worried about.** Consumption plus an eight-hour interval puts 25 feeds at roughly a fortnight of showing up twice a day, which reads as devotion rather than farming. Accepting the grind is cheap insurance rather than a live risk.

## Hunger, precisely

**Per player, settled by precedent rather than preference.** The toy's ramp, the toy's cooldown and the bed's daily window are all per player, and the reasoning the plan gave for the toy transfers unchanged: server-wide state would make feeding a race, and a late joiner would inherit a cat somebody else had already satisfied. A cat who is hungry for you and full for me is the same suspension of disbelief she already asks for by being in every room at once.

**Eight hours since her last successful feed.** That is roughly two feeds a day for someone who plays morning and evening, three for someone who times it, and it never punishes a player for living in the wrong timezone — which is what ruled out real Pacific meal windows, however much better they read.

**The interval has to be hours rather than minutes, or the toy dies.** At +10 with hunger returning every ten minutes, feeding would strictly dominate the toy: identical reward, no ramp, never refuses. Feeding earns its +10 by costing more actions, so it has to come round less often. Anything under an hour breaks the toy.

Three rules about the refusal, each of which matters more than it looks:

- **A refused feed does not consume the food.** Losing a can to a cat who was not hungry is the kind of thing players remember, and it would make the first refusal read as a bug.
- **A refused feed still stamps `last_cat_interaction_date`.** *Attempts count, not just successes* is already settled for the nightly drift. Offering food to a sated cat is showing up.
- **The refusal needs copy in the bed's register.** The bed already does this well — *"The bed already looks fluffy and cozy. Your services are not required today."* Feeding wants the same shape: she is fine, come back later, nothing is broken.

**One bowl, in the Entryway. Changed 20 October.** The original call here was no bowl, because the engine had no verb for two objects. Playtesters then worried the cat would cut herself on the can's edge, so the food now goes into a `cat_bowl` fixture, and `requires` can be met by a non-takeable thing in the player's room. The salmon requires `cat_bowl`, and the other four flavors `can_opener|cat_bowl`. Spec and copy are in the Entryway fragmentation tab, under The cat bowl.

**She is fed where her bowl is.** She is omnipresent at `room_id = ALL`, but every flavor requires the bowl, and the only bowl is in the Entryway. So from drop 10, feeding happens there and nowhere else, including the channel. The gate on drop 10's quest is still the food: the bowl is in plain sight, and the salmon is the thing to find.

## The eighth achievement

**Drop 10's quest had no achievement, and that is an oversight rather than a choice.** First pet has *Making First Contact*. First bed use has *Fluffed to Perfection*. First toy success has *Persuasive*. First feed had nothing — the only feeding achievement is *Bowl Half Empty*, which is secret and needs 25. The seven were written before feeding became drop 10's payoff.

| Column | Value |
| --- | --- |
| `achievement_id` | working id `first_meal`, writers to rename |
| `kind` | `public` |
| Condition | first successful feed |
| Hook | `on_use` |
| `since_drop` | 10 |
| `requires` | `making_first_contact`, like the other two public quests |
| `name` and unlock line | Room Service. Unlock line still owed — see below |
| `prompt` | Find the cat something to eat |

**Its prompt is the first one that is also a puzzle hint, and the tension is real.** *Persuasive* can say *"Play with the cat"* because the toy is lying in plain sight. The salmon is hidden in the coat rack's description deliberately — drop 10 exists to teach that descriptions conceal findable things. A prompt specific enough to be actionable spoils that lesson; one vague enough to preserve it may leave players with no idea what to do.

**It inherits the no-terminal-stop rule** from the other three prompts, because the quest notice interpolates the prompt mid-sentence and a self-punctuating prompt doubles the stop.

### Candidates for the name

**The fork to settle before picking words: does the name honor the finding or the feeding?** Drop 10 exists to teach that descriptions conceal findable things, so a name about the search reinforces that lesson every time it shows up in somebody's stats. A name about the meal honors the payoff instead, and sets up *Bowl Half Empty* as its sibling. Both are defensible and they are not combinable.

**One constraint.** *Bowl Half Empty* already owns the food-container pun. A second bowl, dish or plate joke in the same family reads as a theme rather than a pair, and the two become hard to tell apart in a list.

**One durability note.** Nothing should name salmon. Drop 10 is the only source of food until drop 30, so in practice the first feed is always salmon — but a player who joins at drop 30 could first feed something else, and a salmon name would be wrong forever.

| Name | Register | Honors | Note |
| --- | --- | --- | --- |
| **Short-Order Cook** | wry idiom, like *Fluffed to Perfection* | the feeding | **Recommended.** She asked, you produced, and the implication is that it will happen again — which is what *Bowl Half Empty* goes on to count. Fills a register slot nothing else in the set holds |
| **Staff** | one dry word, cat's-eye-view, like *Favorite Human* | the feeding | The relationship has just become employment. Very cat. Risk: reads as a role rather than an accomplishment |
| **Room Service** | idiom, domestic | the feeding | CHOSEN. She is the guest and the house is hers. Lands better once the house is open, which is the same drop |
| **Table for One** | wry, melancholy | the feeding | She dines alone. Sadder than anything else in the set, which may be a feature |
| **Resourceful** | single adjective, like *Persuasive* | the finding | Closest in register to *Persuasive* — which is also the argument against it. Two one-word adjectives for two first-time-with-an-object achievements would blur |
| **Pantry Raid** | pun-forward, like *A Paw in the Door* | the finding | The most fun of the set. *Raid* leans toward taking rather than giving, which is only half the quest |
| **Nothing Stays Hidden** | declarative, no close sibling | the finding | States the lesson outright. Strongest reinforcement, weakest joke |

**Settled: Room Service. The note below records what was argued for instead, for whoever reads this later. *Short-Order Cook*.** It occupies a register the set has not used, it implies the recurrence the 25-feed achievement measures, and it keeps the cat as the one issuing orders rather than the player as the one being clever. **Second choice *Staff*** if the preference is for the dry one-worder. I would avoid *Resourceful* specifically because *Persuasive* already holds that slot.

### What writers still owe

**For the achievement itself: nothing more.** The unlock line has been supplied, and everything else was already specified: id, kind, hook, `since_drop`, `requires`, name and prompt.

**The template, from the closest parallel.** *Fluffed to Perfection* is the same shape — public, first use of an object, prompted, gated on the root achievement — and its full row reads:

| Field | *Fluffed to Perfection* | *Room Service* |
| --- | --- | --- |
| `achievement_id` | `fluffed_to_perfection` | `room_service` |
| `name` | **Fluffed to Perfection** | **Room Service** |
| `kind` | public | public |
| Condition | First `/use cat bed` | First successful feed |
| Hook | `on_use` | `on_use` |
| `since_drop` | 1 | 10 |
| Visible when | drop ≥ 1 **and** has `making_first_contact` | drop ≥ 10 **and** has `making_first_contact` |
| `prompt` | *Give the cat a cozy nap spot* | *Find the cat something to eat* |
| **Unlock text** | *You fluffed the cat's bed to her standards. Well done.* | **← Supplied, below** |

**Supplied and final:**

> You fed the cat, but that's no more than she expected.

**It is the driest line in the set, and the driest belongs right here.** Every other unlock concedes something — *"She has noticed you and has decided you may stay"*, *"She has stopped pretending she doesn't like you"*, even *"Well done"*. This one concedes nothing, which is exactly the joke *Room Service* sets up: a service was rendered and received as her due. The name and the line agree with each other, which is more than most pairs in the set manage.

**It also rhymes with its own sibling.** *Bowl Half Empty* reads *"You fed the cat 25 times and she's still waiting for dinner. Keep going."* Same opening clause, same deflating turn. The first feed and the twenty-fifth now read as a deliberate pair — which is good, and worth recording, because if either is ever rewritten alone the echo breaks silently and nobody will notice.

**It clears both conventions:** a terminal full stop, and *the cat* before any pronoun, so a player who has not yet worked out who *she* is never meets an unexplained one.

**Two conventions the set follows, worth stating because they differ.** Unlock lines **do** take a terminal full stop; prompts **do not**, because the quest notice interpolates the prompt mid-sentence. And the unlock lines tend to end on a dry sting rather than on praise — *"Don't let it go to your head"*, *"Keep going"*, *"She has stopped pretending she doesn't like you"*. *Fluffed to Perfection* is the gentlest of them at *"Well done"*.

### And the wider feeding copy, which is more than the achievement

| What | Count | Note |
| --- | --- | --- |
| Feed success text | **5** | One per flavor. The toy deck's rule applies: the success is the payoff and should never repeat, which is why thirteen toys each got their own line rather than sharing one |
| The not-hungry refusal | **1–2** | In the bed's register — *"The bed already looks fluffy and cozy. Your services are not required today."* Read far less often than the toy refusals, since most feeds inside an eight-hour window succeed, so one or two is enough rather than twelve |
| The salmon's own `look` | **1** |  |
| The coat rack's `look` | **1** | **The quest's actual mechanism.** The salmon has to be named inside it and nowhere else — not in any listing. This is drop 10 Entryway prose rather than feeding copy, but the quest fails without it |
| *Room Service* unlock line | **0** | Supplied and final |
| *Bowl Half Empty* unlock line | 0 | Already written and locked: *"You fed the cat 25 times and she's still waiting for dinner. Keep going."* |

**Eight or nine strings now, and none of them blocks the achievement.** `take` on the food falls through to `take.default`, and the first feed needs no special success line — the achievement announcement carries that weight, exactly as it does for the bed and the toy.

## The arithmetic, and the milestone ladder

**Feeding at +10 twice a day adds about +20 to a devoted day.** Using the drop schedule's own pacing figures — petting +3 expected per unhurried pet, the toy +10 a success, the bed +15 a day — an engaged day now runs somewhere near +64, and a casual one near +35.

Against the milestones that exist: *A Paw in the Door* at 50, *Cat's Best Friend* at 100, *Favorite Human* at 250. **At +64 a day, 250 is four days. At +35, a week.** The nightly drift never bites an active player, because it skips any day with a cat interaction, so there is no counterweight.

**But feeding did not cause this, and it would be wrong to retune feeding to fix it.** The schedule's own pacing table already says the toy reaches 100 in *"90 minutes minimum, the floor being nine 10-minute cooldowns."* One hundred relationship points in an hour and a half, and 250 inside an afternoon, were true before feeding was designed. The thresholds were set against a meter that stopped at 100, and they were never rescaled when the ceiling came off.

**So the cheap fix is the one the schedule already reserved.** *Favorite Human* took 250 on the understanding that *"500 and 1,000 remain available if the climb needs more destinations later."* Later is now: 250 reads as a mid-game marker rather than the summit, and the top of the ladder moves up. That costs two content rows and no mechanic changes.

**A fifth lever, now settled.** The daily craving is drop 3, a once-a-day act of cat attention like the bed, and it pays 5 relationship points once per player per day. That adds at most +5 to a devoted day, so the figures above move only slightly.

**This is the part of the document that wants other eyes.** Three people have numbers in this system — the writers own the achievement copy, the developer owns what the code actually does per action, and the drop schedule owns the pacing table. I have added feeding's +10 to figures I did not measure. If the toy's real-world success rate or the petting cadence differs from the table, the conclusion holds but the numbers move.

## The craving game is not this, and an earlier draft of this section was wrong

*Superseded 26 October by the Craving game (drop 3) tab, which is now the spec. The craving is drop 3, uses the emoji catalogue's categories and types rather than Unicode subgroups, and pays 5 relationship points once per player per day. This section is kept for the reasoning.*

**Correction.** An earlier draft of this section argued the craving game was a flavor layer on feeding that could not ship before drop 30, because four of the five cat-food stashes sit behind drop 30's rooms. That was wrong in every part. The craving has nothing to do with feeding.

**What the craving actually is**, per the Story Bible and the Functional Spec: one Unicode food emoji a day, drawn from Food & Drink minus dishware, around 130 options. The cat craves something silly — cheese, broccoli — and **she never eats it.** Players guess by reacting with emoji to any bot message, and the bot answers with reactions on that message: 👀 for the right subgroup, ❌ when 19 of the 20 reaction slots are gone with no winner, 😻 when it is found. It is **the same craving for every player on the server**, deliberately, so guessing is collaborative and players can tell each other. It carries its own achievement, *Met the Craving*, and its own `/stats` line — a tally of distinct days a player reacted correctly, counting taking part rather than winning.

**It never belonged to drop 30.** The schedule has always placed it there: *"the daily craving is not built and drop 0 ships without it; it belongs here when it exists."* It has no room dependency and no food dependency, so nothing about feeding gates it and nothing about it gates feeding.

**What actually blocks it is the reaction handler** — `on_raw_reaction_add`, which does not exist. And it now carries that cost alone: the handler was originally justified by two features, since drop 1's toy was going to be claimed by reaction, and that route was abandoned when toys became `/take` inventory items. One customer, full price.

**Where the error came from, and it is worth fixing at the source.** The drop schedule's open question 3 asks *"what is the feeding action"* and offers three candidates: *"`/use` cat food, giving it to her, meeting the craving."* That sentence puts the craving forward as a possible feeding mechanic, which is how I read it. It is now ruled out, and the sentence should be corrected in the schedule so the next person does not make the same inference.

**One consequence for feeding, and it is small.** The hunger state was partly justified here as something the craving could hang off. That justification is gone. Hunger survives on its own merits — a sated cat refusing food reads far better than an arbitrary timer — but it is a fiction choice over an engine that is identical either way: one timestamp, compared against now. Nothing is lost, and nothing was built for a future that does not arrive.

## Two questions for the developer

**1. Feeding is the mechanic that tips the per-player state question, and the call is now theirs to weigh.** The running count: 3b added the toy ramp, the toy cooldown expiry and the last bed fluff; `last_cat_interaction_date` and the feed counter for *Bowl Half Empty* make five. Hunger needs a sixth. The craving, whenever it ships, needs a last-credited date per player so a latecomer is counted once — which makes seven. The V3 plan said three columns was proportionate and that five *"is the shape of a small per-player key-value table, and a sixth is coming the moment anything else is counted."* Feeding is that sixth thing, and this is the third consecutive release to defer the decision.

The question is not *columns or a table* in the abstract. It is: **does the extraction happen in drop 10, or does drop 10 add the sixth column and the extraction land in V3.3?** Either answer is defensible. What is not defensible is adding a seventh without anyone having chosen.

**2. The two timestamps are not the same thing and must not be merged.** Feeding touches both:

| Column | Type | Written by | Read by |
| --- | --- | --- | --- |
| `last_cat_interaction_date` | a **date** | petting, the toy, the bed, feeding — **attempts, not just successes** | the nightly drift, to decide whether to skip a player |
| `last_fed_at` | a **timestamp** | successful feeds only | hunger, to decide whether she will eat |

The names invite collapsing them, and collapsing them breaks both quietly: a pet would reset her hunger, and a refused feed would stop protecting the day's score. Worth confirming the developer reads them as distinct before either is written.

## What this does not cover

- **The drop 10 work order**, which this unblocks and which is the next thing to write.
- **The Entryway prose** — the coat rack with the stash buried in its description, the front door, the ceiling, the partial room text. Writers-only, fully parallel, and it can start now. The drop 1 scenery deck already established the pattern it needs: a noun named inside another noun's description, reachable by reading rather than by listing.
- **Thread verification 2**, answered 26 October: yes, tested on a test server (see The channel as a room). The question was: does mention-add still work, and stay silent, from a bot holding `MANAGE_THREADS` once `invitable: false` is set. Workstream B must precede drop 10 and cannot be specified until that comes back.
- **The onboarding corridor.** Drop 10's one room and one quest probably dodges it. Drop 20's sixteen things does not.
- ***Bowl Half Empty*'s copy**, which already exists and is locked in the drop schedule.

**The craving game**, which is now drop 3 and specified in its own tab, Craving game (drop 3). It is independent of feeding.

**Checked 26 October.** The renumbering put each cat-food row at its room's drop: salmon at 10, chicken, tuna and gourmet at 30, and expired at 40. `since_drop` now does the gating that room placement was doing, so only the salmon is reachable at drop 10. The salmon also has a second source, the dining-room sideboard, which arrives at 30.
