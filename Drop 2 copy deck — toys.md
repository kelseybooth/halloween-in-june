# Drop 2 copy deck — the toys

## Settled conventions, carried from the POC deck

- **The cat is she**, never *it*.
- **Present tense, second person.** You flick, she watches.
- **Hints are in the game's voice**, italicized, prefixed **Hint:**.
- **Quest prompts carry no terminal full stop.** Flavor strings keep their punctuation.
- `{name}` and `{time}` are the only tokens in scope here.
- **The house default carries the ordinary case and a writer overrides where it matters.** Most toys below have no `take` or `drop` text on purpose.
- Use American English

**Success lines are third person and name the player; refusals stay second person.** Every toy `use` success posts **publicly in the channel**, so it has to read for people who did not type the command. Three rules follow, and all thirteen success lines in this deck now obey them:

- **The actor is `{player}`, never *you*.** No second-person pronouns anywhere in a success line, including possessives and asides — *yours*, *neither of you*, *looks up at you* all had to go.
- **The line names the toy.** Onlookers have no idea what was used, and Discord adds no attribution to a message the bot sends on its own rather than as a command's direct reply — so if the string does not say *feather wand*, nothing does.
- **Where the old line opened on the cat, it gains a short preface.** The catnip mouse and the wine cork both began *The cat…*, which read fine privately and reads as a non sequitur in a channel.

**The asymmetry with refusals is deliberate, not an oversight to tidy up.** Refusals are private and stay in second person — *You dangle the hair tie and set it swinging* — because a player's fumbling is their own business, while a success is worth broadcasting. A writer who sees the two registers side by side should leave them alone.

`{player}` takes a singular *they* where a pronoun is unavoidable: *before they have straightened up*.

**The toy takes an indefinite article on first mention — *a crinkle ball*, *an acorn* — with one exception.** The player who typed the command knows which acorn they are rolling; nobody else in the channel does, and *the acorn* invites them to go looking for one they have never seen. Later references in the same line stay definite or become pronouns, as ordinary English does: *… sets an acorn rolling … loses it in a gap too narrow to follow*.

**The Amazon box is the exception**, because there is exactly one of it and the whole room can see it. The same reasoning keeps *the cat bed* correct in the public fluff line — definite is right for anything there is only one of.

Refusals are unaffected, and for the same reason the two registers differ at all: they are private, and a player holding a toy knows perfectly well which one it is.

## 0. Three strings you already have, and one you do not

The second-`/take` refusal needs no new language. `defaults.tsv` already carries it, and the sentence is already right.

| Need | Key | Existing text | Verdict |
| --- | --- | --- | --- |
| A second `/take` when already holding one | `take_fail.already_carried` | You're already carrying the {name}. | **Reuse** |
| Using a toy inside the ten-minute cooldown | `use_fail.cooldown` | You've done that recently. Try the {name} again in {time}. | Reuse as the backstop; one bespoke line in §1 is better in her voice |
| Picking a toy up | `take.default` | You pick up the {name} and tuck it into your bag. | Reuse |
| Putting one down | `drop.default` | You set the {name} down. | Reuse |
| Using a toy lying in the channel without holding it | — | — | **New — see below** |

**One caveat on the reuse, and it is an engine line rather than a writing one.** The Functional Spec routes the `max_per_player` refusal to *the thing's own* `take_fail`, with no default fallback — the three existing capped things each have a bespoke line. Either the toy gets its own, or the cap case falls through to `take_fail.already_carried`. **Recommend the fallback:** the default sentence is already exactly right, and no future capped thing will need a bespoke string either.

**The one genuinely new default.** A player who types `/use feather wand` while the wand is lying in the channel needs to be told to pick it up — and under the refusal rule, the refusal names the verb that would have worked.

| Key | When | Text | Status |
| --- | --- | --- | --- |
| `use_fail.not_carried` | The thing is in reach but not in the bag | The {name} is right there. You would have to pick it up first. | Final |

**This refusal only ever applies to things that can be picked up.** The carry check is keyed on `takeable`, not on `/use`: a `takeable = yes` thing the player is not holding gets the line above, and **a `takeable = no` thing is used where it stands and is never carry-checked at all.** Two things in the game depend on that distinction — the cat bed, which 3a already ships and which nobody can pocket, and the Amazon box in drop 3, whose whole easter egg is `/use` on a thing you were never meant to carry. If the check is written as a property of `/use` rather than of the thing, both become permanently unusable and the box's joke can never fire.

## 1. The drop 2 toys

**Recommended: the feather wand.** It is the most legible invitation to play of any object on the list, which matters because drop 2 is where a player meets `/use` on a thing for the first time. A refusal reads naturally — she watches it and declines — where a refusal on, say, a cardboard box reads as the box being broken. *Settled: both ship in drop 2, equally likely — see below.*

**Drop 2 ships two toys, equally likely: the feather wand and the crinkle ball.** The crinkle ball's copy is in §3 and moves into drop 2 unchanged. Equal likelihood is the one weighting that needs no new column — a uniform draw over the arrived pool is the natural default, so §6's weight column stays deferred. The class-scoped `max_present` already handles two rows feeding the same two slots without a change.

The wand stays the deck's worked example below, because it is the one the ramp and cooldown notes are written against and both toys behave identically. The difference the second toy makes is to the hint rail, which is why §8's three middle rungs no longer name a toy.

`thing_id` `feather_wand` · `name` feather wand · `aliases` `wand|feather|feathers|feather toy|cat toy|toy` · `takeable` yes · `droppable` yes · `max_per_player` 1

**The alias list matters more than usual.** A player who has only ever been told "there is a toy" will type `/use toy`, so `toy` and `cat toy` both have to land.

| Key | When | Text | Status |
| --- | --- | --- | --- |
| `look` | In the channel or inventory | A plastic stick with a long ribbon tied to one end, and three feathers tied to the ribbon. One of the feathers has been thoroughly pre-chewed. | Final |
| `take` | Picking it up | — falls through to `take.default` | Reuse |
| `use` | **Success.** +10 | {player} flicks the ribbon on a feather wand. The cat comes up off the floor as though she has been waiting all week for exactly this, catches the feathers in both front paws, and holds them against her chest with an air of total vindication. | Final |
| `use_fail` | **Refusal.** The ramp said no | — rotates through the twelve in §2 | Final |
| `use_fail.cooldown` | Inside the ten minutes | The cat is finished, and is pretending the last few minutes did not happen. Try again later. | Final |
| `drop` | Putting it down | — falls through to `drop.default` | Reuse |

## 2. Twelve generic play refusals

**These are the most-read strings in drop 2, by some distance.** With the 0 / 25 / 50 / 75 / 100 ramp, the expected attempt of a first success is 3.2 — so a player sees roughly **2.2 refusals for every success**. One refusal string would become the most repeated line in the game inside a week.

The constraints they are written against: never promise, never forbid, always leave the retry open; never name a verb that does not exist yet; never imply the toy is defective; and work for any traditional toy through `{name}` alone, with no verb tied to the object's shape.

| Key | Text | Status |
| --- | --- | --- |
| `use_fail.toy.1` | The cat looks at the {name}. She looks at you. | Final |
| `use_fail.toy.2` | You have the cat's attention for most of a second. The {name} does not hold it. | Final |
| `use_fail.toy.3` | One of the cat's ears turns toward the {name}. The rest of her declines to follow. | Final |
| `use_fail.toy.4` | The cat watches the {name}. | Final |
| `use_fail.toy.5` | The cat's tail moves once. You could choose to read this as interest, if you were hopeful. | Final |
| `use_fail.toy.6` | The cat blinks at the {name}, then at the middle distance, where something more interesting is apparently happening. | Final |
| `use_fail.toy.``7` | The cat lies down, but keeps one eye on the {name}. | Final |
| `use_fail.toy.8` | The cat sits up and watches you. She does not get up. | Final |
| `use_fail.toy.9` | The cat sniffs the {name} once and settles back down. | Final |
| `use_fail.toy.10` | The cat crosses half the room, stops short of the {name}, and sits. | Final |
| `use_fail.toy.11` | The cat puts one paw on the {name} and leaves it there. | Final |
| `use_fail.toy.12` | The cat's pupils go wide at the {name}. Nothing else about her moves. | Final |

## 3. Five more traditional toys

**The crinkle ball has moved into drop 2; the other four are not in it.** Those four are bank. Each has its own `look` and its own success line — the success is the payoff and should never repeat — and each falls through to the twelve shared refusals in §2. `take` and `drop` fall through to the house defaults.

All below text have been approved by writers.

| `thing_id` | `name` · `aliases` | `look` | `use` — success, +10 |
| --- | --- | --- | --- |
| `crinkle_ball` | crinkle ball · `ball\|foil ball\|crinkle`\|crinkle toy\|cat toy\|toy | A foil ball about the size of a walnut. It makes an outsized noise for its size, which is the entire point of it. | {player} rolls a crinkle ball across the floor. The cat is on it before it stops, skids past, recovers with enormous dignity, and bats it under something where neither of them can reach it. |
| `catnip_mouse` | catnip mouse · `mouse\|felt mouse\|catnip` | A felt mouse, gray once, with one bead eye and a tail down to its last thread. It smells, faintly and persistently, of a very good time. | {player} offers a catnip mouse. The cat takes it in her teeth, flops onto her side, and kicks it with both back feet until it has been thoroughly dealt with. Then she lies there holding it, looking at nothing. |
| `jingle_ball` | jingle ball · `bell ball\|bell\|rattle` | A clear plastic ball with a bell rattling around inside it. Festive! | {player} sends a jingle ball down the floor. The bell does the work: the cat tracks the sound rather than the ball, pounces a foot behind it, and looks briefly betrayed before going again. |
| `laser_pointer` | laser pointer · `laser\|pointer\|red dot\|dot` | A pen-sized aluminum tube with a button on the side. Somebody has wrapped the middle in electrical tape, which suggests history. | {player} runs the dot of a laser pointer along the wall with the cat behind it, then lets it stop in a corner. She pins it flat under both front paws, holds it a long moment, and then looks up with the air of a cat who has solved something. |
| `spring_coil` | spring coil · `spring\|coil\|spiral` | A spiral of colored plastic, the kind that comes in a bag of forty and turns up around the house for years afterward. This one has been stretched out of shape. | {player} flicks a spring coil away. It goes somewhere nobody predicted, twice, and the cat follows it both times at a flat run with her ears pinned back. |

**On the laser pointer.** A cat can never catch the dot, which is the known cruelty of the object and a thing cat owners argue about. The success line above lets her pin it where it has stopped, so the play ends in a win rather than in an unresolvable chase. Worth preserving in any rewrite.

**On the catnip mouse — parked, not dropped.** A writer proposed that playing with the mouse should raise the chance of a friendly pet afterwards, and the idea is agreed in principle: catnip is the one toy where a real effect is the point, so the mechanic belongs on this row and nowhere else. **Settled: +25 percentage points on the next three pets, within five minutes, not re-applicable for thirty.**

The ten minutes was the whole problem. The pet roll is 80% friendly on the first pet in a window and sheds 10 percentage points per pet, and that window is already ten minutes — as is the toy cooldown after a success. A ten-minute buff is therefore up almost permanently, and the two windows coinciding turns a flourish into a farm: unbuffed, a full eight-pet window nets −4, at +20pp it nets +12, and with the toy's own +10 the loop pays about +22 every ten minutes against a nightly decay of 10. Clearing the pet window instead of raising the percentage is no better; it just lets the profitable early pets be re-run.

**Settled: +25 percentage points on the friendly roll.** The base chance is `80 − 10 × recent_pets`, so the buffed ladder runs 100 / 95 / 85 / 75 / 65 / 55 / 45. The first pet of a fresh window becomes a certainty, which is the intended effect.

| Pet in window | Base | Buffed | Expected meter |
| --- | --- | --- | --- |
| 1 | 80% | **100%** | +5.0 |
| 2 | 70% | 95% | +4.5 |
| 3 | 60% | 85% | +3.5 |
| 4 | 50% | 75% | +2.5 |
| 5 | 40% | 65% | +1.5 |
| 6 | 30% | 55% | +0.5 |
| 7 | 20% | 45% | −0.5 |

**Settled: three charges, a five-minute lapse, and a thirty-minute re-application cooldown.** Together those three numbers make the mechanic safe in a way neither a pure time window nor a pure charge count would have been on its own.

| Parameter | Value | What it does |
| --- | --- | --- |
| `catnip_buff_points` | **+25** | added to the raw friendly chance |
| `catnip_buff_pets` | **3** | charges, spent by **any** `/pet`, friendly or standoffish |
| `catnip_buff_minutes` | **5** | the buff lapses at five minutes even with charges left |
| `catnip_buff_cooldown_minutes` | **30** | a second buff cannot be applied until thirty minutes after the first |

**Three charges or five minutes, whichever comes first.** A player who pets twice and lets it lapse loses the third — that is what the five minutes is for.

**Charges count pet actions, not successes.** `/pet` always does something; the roll decides the mood, not whether the pet happened, so a standoffish roll spends a charge. At +25pp the first pet of a clean window is a certainty, but the second and third are 95% and 85%, so a player can spend all three and come away with two friendly pets.

**The thirty-minute cooldown is what turns this into a flourish rather than an engine, and it was the piece I had not thought of.** A buff is worth about **+7** — three buffed pets at +5.0, +4.5 and +3.5 against +3.0, +2.0 and +1.0 unbuffed. Capped at one buff per half hour, that is about +14 an hour on top of the roughly +60 an hour the toy already pays at its ten-minute cooldown: a quarter more, noticeable without being the reason to play. The cooldown also mimics the effect of catnip on real cats.

**One collision to know about rather than fix.** The toy's cooldown is ten minutes and the buff's is thirty, so a player can play the catnip mouse successfully three times in half an hour and only the first grants a buff. The buff is never announced — its only trace is the appended line on friendly pets — so most players will never notice. A player who works the pattern out will, and if that ever needs addressing it is a line on the catnip success rather than a change to the mechanic.

**And the likeliest source of "the buff didn't work" reports: it is additive on the crowding ramp, not a reset of it.** A player who has already petted five times in the last ten minutes and then plays the mouse gets 30 + 25 = 55% on the next pet, not 100%. The certain first pet holds only for a player who has not been petting — which the brief assumed, and which is worth having written down.

**Two columns, not three.** Charges plus a single timestamp cover all of it: store `catnip_buff_at` when the buff is applied; the buff is live while `now < catnip_buff_at + 5 min` with charges remaining, and re-applicable once `now >= catnip_buff_at + 30 min`. Both windows derive from the same stamp. That brings whichever release takes this to **five** per-player non-boolean values — 3b's three plus these two — which is past the point the implementation plan said to stop and build a general per-player state table rather than drift into one. That decision belongs to that release, not to 3b.

**And one spec detail that would otherwise be decided by accident.** Apply the +25 to the raw `80 − 10 × recent_pets` and floor the *result* at 0 — not to the already-floored value. Otherwise a player who has petted eleven times in the window sits at a floored 0% and the buff lifts them to 25%, undoing the crowding penalty for precisely the player it exists to discourage. Raw-then-floor gives them 80 − 110 + 25 = 0%, and the penalty still bites.

#### The buffed pet line

| Key | When | Text | Status |
| --- | --- | --- | --- |
| `pet.buffed_suffix` | appended to a **friendly** pet reply while the buff is live | She seems more blissful than usual. | Draft |

**Friendly only — standoffish replies are untouched**, per the brief. Four notes on how it attaches:

- **It is an append and carries its own leading space**, reading as a second sentence after whichever friendly line fired. It does not care which variant was selected.
- **"She" is correct here**, and is not a breach of the first-reference rule: the pet line it attaches to has already named the cat.
- **Private only.** The public pet line is a separate string reporting that pet's reaction to onlookers, and the buff is per-player hidden state — a bystander with no buff, reading that the cat is unusually blissful, has nothing to make sense of it with. Recommended: leave `pet.public.friendly` alone.
- **Pets only, not every positive interaction.** A bed fluff and a toy success are positive too, but the buff modifies the *pet roll*; appending it to those would claim an effect that is not there.

Three conditions on it, for whichever work order picks it up:

- **A column, not a special case.** `pet_buff_minutes` on the thing row, set only on `catnip_mouse` to begin with. Keyed on `thing_id` it breaks the rule in §7 that a toy's identity is nothing but a row.
- **It is the fourth per-player non-boolean value**, which the implementation plan named as the point where the decision to do without a general per-player state table gets revisited deliberately rather than drifted past.
- **Not 3b.** The mouse is in this bank and drop 2 ships the feather wand, so this cannot ride 3b in any case. Recommended home is the release after the door opens, where it is not competing with a release whose only job is to prove gating and hinting.

## 4. Seven unusual toys

Things a cat decides are toys. Mechanically identical to the traditional ones — same ramp, same cooldown, same +10 — but each carries its own refusals, because the joke is specific to the object. **The twelve generic refusals in §2 stay available as a backstop** for any of these, so a writer can add one custom line rather than three and nothing is left uncovered.

**§2's constraint binds the custom refusals too, and the first drafts of these broke it.** Selection stays random — the cat's interest waxes and wanes, and it does not have to climb in a straight line — but **no refusal may read as a verdict on the object.** A line can show boredom in the moment; it must never suggest the thing is not a toy, or that the matter is settled, or that trying again is pointless. The giveaways to watch for in a draft are *decided*, *closed*, *defeated*, *not worth it*, *already*, and any narrator aside agreeing with her.

### `amazon_box` · Amazon box — a fixture in the Entryway, not a drop 2 toy · `box|cardboard box|delivery box`

| Key | Text | Status |
| --- | --- | --- |
| `look` | N/A \[Use the existing text from the Amazon box in the entryway\] | Final |
| `use` — success | It takes almost nothing. {player} folds the box's flaps back and the cat is in it before they have straightened up, folded into a space two sizes smaller than she is, entirely content. | Final |
| `use_fail.1` | You fold the flaps back. The cat crosses the room to see what you are doing, and stops there. | Final |
| `use_fail.2` | You pick the box up and give it a heft, for no reason you could name. The cat watches you do it with real interest. | Final |
| `use_fail.3` | You spin the box on the floor. It makes one full turn before coming to a halt. The cat side-eyes it from where she is. | Final |
| `use_fail.4` | You push the box a few inches to the left, which improves nothing. The cat tracks it the whole way. | Final |
| `take_fail` | — falls through to take\_fail.fixture, which already reads "The {name} isn't yours to carry off." | Reuse |

**The box is never picked up, and it is not an exception to the must-carry rule — it is outside it.** `takeable = no`, so `/use amazon box` works where it stands and the `use_fail.not_carried` check in §0 never applies to it. The cat bed already behaves this way in drop 1, which is the precedent rather than a special case. `/take amazon box` refuses with `take_fail.fixture`, and that refusal is part of the joke: the player learns the box is furniture long before they learn it is a toy.

**Settled: the box is a fixture, it is the Amazon box, and it is not a drop 2 toy at all.** One `amazon_box` row standing in the Entryway from the drop that opens the Entryway. Players meet it as the container the spice jars arrive in, and the fact that `/use` does anything at all is theirs to find.

Three things follow:

- **It needs no hint, and should not get one.** This is an easter egg in the shape of `/look cat`. The box is already visible as a container, because players will be looking inside it for spice jars — what they will not know is that `/use amazon box` does anything. Naming it in a hint spends the joke. Discovery is by accident or by word of mouth, which is the point.
- **Drop 2 now has exactly one toy and no floor under it.** The box was going to be the thing a player could always try when the wand had not respawned. It is not, so the channel holds feather wands and nothing else, and a player who plays one into its cooldown has nothing to reach for. That is an argument for topping the wand up generously — `max_present` at 2, refilled the same day — rather than treating the rate as a knob to be set low.
- **Settled: she is everywhere in the house.** The player experiences her as nearby wherever they are, and the simultaneity across players is accepted rather than engineered around — the thread model hides it for nothing, since a player only ever reads the thread of the room they are standing in. Mechanically this is `room_id = ALL` on her `things.tsv` row from the drop that opens the first room, which is the device `alexa` already uses and currently the only row that uses it, so it needs no new schema and the success line above fires in the Entryway unchanged. Two riders and one consequence. `/look cat` now works in every room, which is where that easter egg belongs. She must still never appear in a room's `Items here:` listing — a rule that now has to hold in nine rooms rather than one. And the public pet line is rate-limited per player per *place*, so a player walking the house gets a fresh budget in every room: nine rooms is nine budgets, which is more public chatter than the limit was set for. The per-player pet window and the toy cooldown are per server and so unaffected — nobody sheds a cooldown by walking next door. It is the chatter that wants a second look, not the mechanics.

**One thing to check in the repo:** the existing `amazon_box` row's `name` and `aliases`. Whatever is already there wins over the list above — the only requirement is that `box` resolves.

### `hair_tie` · hair tie · `hairtie|elastic|hair elastic|bobble`

| Key | Text | Status |
| --- | --- | --- |
| `look` | A black elastic hair tie, stretched out and furred with lint. There is no way to know whose it was. | Final |
| `use` — success | {player} stretches a hair tie between two fingers and lets go. The cat takes it out of the air, lands with it, carries it three steps away, puts it down, and looks back to see whether this is still happening. | Final |
| `use_fail.1` | You stretch the hair tie between two fingers and let it snap. It would have looked fun, if the cat had been facing this way. | Final |
| `use_fail.2` | You dangle the hair tie and set it swinging. The cat glances up at the movement, and then away. | Final |
| `use_fail.3` | You twirl the hair tie around your finger until it flies off. The cat watches the whole performance and stays put. | Final |
| `use_fail.4` | You flick the hair tie so that it lands a foot away. The cat leans over, sniffs it once, and settles back down. | Final |

### `bottle_cap` · bottle cap · `cap|metal cap|crown cap`

| Key | Text | Status |
| --- | --- | --- |
| `look` | A metal bottle cap, crimped edge, slightly bent. It is sitting crimped side down, which is the correct way up for skittering. | Final |
| `use` — success | {player} sends a bottle cap spinning across the floor. It skips and chatters all the way to the wall, and the cat goes after it as though the noise were the thing worth catching. | Final |
| `use_fail.1` | You flick the cap. It skitters beautifully. The cat watches it go without moving. | Final |
| `use_fail.2` | The cat watches you flip the cap in the air. | Final |

### `wine_cork` · wine cork · `cork|stopper`

| Key | Text | Status |
| --- | --- | --- |
| `look` | A cork stained purple at one end, with the ghost of a vineyard printed down the side, and two small punctures in it exactly the right distance apart to be teeth. | Final |
| `use` — success | {player} rolls a wine cork over to the cat, who traps it against her chest, gets both back feet onto it, and kicks. The cork survives. Her commitment to the project does not waver. | Final |
| `use_fail.1` | The cat sniffs the cork, considers it for a moment, and leaves it where it is. | Final |
| `use_fail.2` | The cork rolls up against the cat, who lets it. | Final |

### `acorn` · acorn · `nut|oak nut`

| Key | Text | Status |
| --- | --- | --- |
| `look` | An acorn, still in its cap. What is it doing here? | Final |
| `use` — success | {player} sets an acorn rolling, and it rolls badly, which turns out to be the whole appeal. The cat chases a thing that keeps changing its mind, loses it in a gap too narrow to follow, and spends a while reaching after it with one arm. | Final |
| `use_fail.1` | The acorn rolls. The cat watches it roll. | Final |
| `use_fail.2` | The cat puts one paw on the acorn and holds it there a while, then lets it go without explanation. | Final |

**Writers: do not let the acorn name the oak tree.** The oak is how the Secret Library is found, and a toy description is not where that should surface.

### `spider_ring` · plastic spider ring · `spider|ring|plastic spider`

| Key | Text | Status |
| --- | --- | --- |
| `look` | A plastic spider on a ring, the kind that comes on a cupcake. Eight legs, some of them still attached. | Final |
| `use` — success | {player} walks a spider ring across the floor on what is left of its legs. The cat goes very still, then very low, and then entirely too fast, and the spider loses another leg. | Final |
| `use_fail.1` | The cat studies the spider for a long moment, apparently unconvinced, and does not get up. | Final |
| `use_fail.2` | The spider advances. The cat waits. The spider advances further. She yawns at it, which you did not know was available as a response. | Final |
| `use_fail.3` | The cat looks at the spider, then at you, with the specific patience of someone waiting for a joke to finish. | Final |

### `crumpled_receipt` · crumpled receipt · `receipt|paper ball|paper`

| Key | Text | Status |
| --- | --- | --- |
| `look` | A receipt balled up tight. Flattened out it would be half a foot of things nobody needed, but balled up it is perfect. | Final |
| `use` — success | {player} tosses a crumpled receipt. The cat snags it out of the air with both paws, carries it to the floor, and shreds one corner off it with real purpose. The receipt is now illegible, which is an improvement. | Final |
| `use_fail.1` | The paper ball lands near the cat, who looks at it, then past it, then at nothing in particular. | Final |
| `use_fail.2` | The cat bats it once from where she is lying, and does not follow it up. | Final |

## 5. The collection achievements

This is what makes a rare toy worth finding without making it worth more points. Every toy gives +10; the rare one's reward is that you have *seen* it.

| Field | Value |
| --- | --- |
| `achievement_id` | `whole_toy_box` |
| `kind` | secret |
| Hook | `on_use`, which already exists |
| Condition | A successful play with **every toy planned for the game, arrived or not** |
| Unlock line | You have coaxed the cat to play with every object in this house that she considers a toy. She had no idea you were keeping track. |

**Settled: the target is every toy planned for the game, not every toy that has arrived.** You are right and I was wrong. Scoped to arrivals it fires at the first opportunity — one toy in drop 2 means it lands on the same play as *Persuasive* — and "played with every toy" would be a lie in the mouth of a player holding three of thirteen. A fixed target also turns out to be the *more* stable of the two: it never moves, where an arrived-scoped target moves at every drop that adds a toy.

Four things follow:

- **Declare the total; do not derive it from the rows.** `things.tsv` will not hold the later toys for a long while — the 3b content spec deliberately leaves twelve of them out — so a row count would read as 1 and the achievement would fire on the first play anyway. A single declared number, `toy_set_total`, seeded at 13, keeps the target right while only one row exists and means the rows can still land drop by drop. **This is the one implementation requirement the decision creates.**
- **Award once, never revoke.** The predicate is *distinct toys played with ≥ `toy_set_total`*, checked on `on_use`. Raising the total later must not take the achievement back from anyone already holding it.
- **Never show progress, not even as a nice touch.** It is secret and `/stats` lists only earned achievements, so a player never sees "3 of 13" — which is correct, because the total counts toys that do not exist yet. A progress line would leak how much of the game is still coming.
- **Rarity now gates it hard.** With the target fixed at the full set, the rarest toy's draw weight decides whether anyone ever finishes. §6's weights put a specific rare at roughly every twelve days; that is the number to revisit if this is meant to be attainable rather than theoretical.

**And it stops being pre-house content, which is worth saying plainly.** Locked behind the last toy's drop, it cannot be a reason to fluff the bed or chase rare toys during drops 2 through 5 — which is what I had been using it for. If you want a mid-game reason to collect, that is a second, smaller achievement — five distinct toys, say — rather than a loosening of this one.

**And keep the rarest toy reachable.** An achievement gated on a dice roll the player cannot influence is only fun if the roll comes up in a reasonable number of weeks. The weighting in §6 is set with that in mind.

### The smaller one, for mid-game

The achievement above cannot be earned until the last toy's drop, which leaves the collecting instinct with nothing to reward in the meantime. This is that reward, and it costs nothing extra to build: **it reads the same counter at a lower bound.**

| Field | Value |
| --- | --- |
| `achievement_id` | `easily_amused` |
| `kind` | secret |
| `since_drop` | the drop that brings the fifth toy. **Not drop 2** |
| Hook | `on_use` — the same hook and the same distinct-toy count as `whole_toy_box` |
| Condition | A successful play with **five distinct toys** |
| `sort_order` | immediately before `whole_toy_box` |
| Unlock line | You and the cat have played with five different things. You are developing an eye for what counts. |

**Secret rather than public, and the reason is the prompt.** A public quest would have to say *"play with five different toys"* — which tells the player how many toys exist and that more are coming. That is the content schedule leaking out through a quest log.

**Five is reachable without luck, which is the point of the number.** Eight of the thirteen toys are common (§6), so five can be met from commons alone. `whole_toy_box` is gated on the rarest toy ever turning up; this one is gated only on showing up.

**Check both thresholds on every play and award any unheld one whose condition is met.** A player can cross five and thirteen in the same session, be handed toys by QA, or return after a long absence, so the test is *"five or more and not held"* rather than *"exactly the fifth"*. This is the same bug class the implementation plan already named for the pet-200 fork, and it takes the same fix.

**It still does not fill the drop 2 to 3 gap, and nothing of this shape can.** A variety achievement needs variety, and those drops have one toy between them. If you want a motive for the room-less phase, it has to count repetition rather than distinct objects — a quiet secret row at twenty-five successful plays, say, which one toy and a patient week will reach. Say the word and I will draft that too.

### The one that works in drop 2

Neither achievement above can be earned in the room-less phase, because both need variety and those drops have one toy between them. This one counts repetition instead, so it works from the day the wand arrives — and it is the only thing in drop 2 that rewards coming back across days rather than within a session.

| Field | Value |
| --- | --- |
| `achievement_id` | `tireless` |
| `kind` | secret |
| `since_drop` | **2** — this is the one that can ship with the wand |
| Hook | `on_use` |
| Condition | **Twenty-five successful plays**, any toy, cumulative |
| `sort_order` | before `easily_amused` |
| Unlock line | The cat has agreed to play with you twenty-five times. |

**Successes, not attempts.** At 3.2 attempts per success, twenty-five successes is around eighty attempts of honest play. Counting attempts instead would reward spamming, which the ramp and the crowding penalty exist to discourage.

**Twenty-five cannot be farmed in a sitting, and that is the number's whole justification.** The ten-minute cooldown after each success puts a hard floor of four hours and ten minutes of continuous play on it, so in practice it is a week of a few plays a day. A smaller number would be a session's work and would stop being a reason to return tomorrow.

**Secret, like the other two.** A public prompt would have to read *"play with the cat 25 times"*, which is a grind instruction rather than a quest, and naming the number invites counting instead of playing.

**Twenty-five or more and not held**, checked on `on_use`, same as the other two. A player can cross twenty-five while offline-adjacent edge cases pile up, and the test should never be *exactly* the twenty-fifth.

**The gap this exposes, which is bigger than this achievement.** All three of these read a record of plays that **nothing in the 3b work order currently writes.** The ramp and the cooldown live on the player row as counters, not as a history, so as drafted there is nowhere to ask *how many distinct toys has this player played with* or *how many times*. The fix is one insert: **a row per successful toy play in `thing_uses`** — player, `thing_id`, timestamp — which the Functional Spec already uses for cooldowns. Then all three achievements are one query over one table: a distinct count at 13, a distinct count at 5, and a plain count at 25. Without it, none of the three can be computed at all, including the two already agreed.

## 6. Rarity, and a correction to what I told you earlier

I said rarity could be expressed purely as restock cadence at zero engine cost. **That holds for two or three toys and breaks at thirteen.** Per-row `max_present = 2` across thirteen rows means up to twenty-six toys sitting in the channel, and the `Items here:` line becomes a wall of nouns.

**The fix is to scope the cap to the category rather than the row.** The rule becomes *keep two toys in the channel, drawn from the arrived pool* — and rarity stops being a calendar and becomes a draw weight.

| What it needs | Size |
| --- | --- |
| `max_present` evaluated against a group rather than one `thing_id` — either a `restock_group` column or simply `type = toy` | Small |
| A `weight` column on the restock row | One column |

It is still cheap, and it is better than cadence on three counts: the channel stays legible however many toys exist, a quiet server keeps two sitting there while a busy one keeps getting fresh ones, and adding a toy is one row with one number rather than a scheduling decision.

**Two tiers, not three.** Three tiers sound richer and make the arithmetic worse.

| Tier | `weight` | Toys |
| --- | --- | --- |
| Common | 4 | feather wand, crinkle ball, catnip mouse, jingle ball, spring coil, hair tie, bottle cap, crumpled receipt |
| Rare | 1 | laser pointer, wine cork, acorn, plastic spider ring |

The arithmetic, so the knob can be turned knowingly: eight commons at 4 and four rares at 1 is a total weight of 36, the box having left the pool as a fixture. A given common is 11.1% of each draw and a given rare 2.8%. At roughly three refills a day that is a specific common every three days and a specific rare about every twelve — rare enough to be worth mentioning in the channel, common enough that the collection achievement is reachable inside the pre-house phase. `restocks.tsv` already carries `config_key`, so both numbers are admin-tunable on day one rather than a deploy.

## 7. Four notes for the 3b work order

**1. Variant selection has nowhere to live in the schema today, and this deck needs it twice.** Text resolves by `(entity, state, since_drop)` to exactly one row and one string. Twelve rotating refusals need either numbered keys — `use_fail.1`, `use_fail.2` — with the engine picking uniformly among the matches, or a `variant` column.

**Do not use a pipe-separated cell.** It is the obvious cheap answer and it is a trap: writers review these decks as tables, `|` is the table delimiter, and the first writer edit would silently split a refusal into two. Numbered keys are safe under every tool the writers actually use.

**2. Row-driven, not special-cased.** The ramp counter, the cooldown and the award live on the *player*. The toy's identity is nothing but a row with `type = toy`. With exactly one toy in drop 2 the cheap implementation is `if thing_id == "feather_wand"` — and that makes toy number two an engine change instead of a TSV row. This is the one line in the work order worth being emphatic about.

**3. `max_present` is category-scoped**, per §6. It is the only non-trivial engine work in drop 2 and it generalises — feeding will want it too.

**4. One success line per toy, never shared.** The refusals rotate and generalise; the success is the payoff and the whole reason a player cares which toy appeared. A shared success line would undo the point of having thirteen.

## 8. The hint ladder, and the bed's fluff variant

**The standard, checked against drops 0 and 1: capitalized.** Those hints read *Hint: This is your first achievement. Check /stats to see achievements and open quests.* and *Hint: There is something new here. Try /look.* — sentence case, capital after the label. All six below match. As in the POC deck, **the label is not part of the stored string**: the strings here are the text after `Hint:`.

| Key | Fires on | Precondition | Text | Status |
| --- | --- | --- | --- | --- |
| `hint.bed_yield` | the fluff that dislodges something | none needed — the yield is once per player | You dislodged something from the bed. Check /look to see what appeared. | Draft |
| `hint.something_new` | drop 2 opening — publicly with the announcement, privately as the fallback | a **takeable** toy is in the channel **and** the player has not done `/look`, nor `/look`, `/take` or `/use` on any takeable toy | **Reused, not rewritten** — *There is something new here. Try /look.* | Final, from drop 1 |
| `hint.look_toy` | the player's first `/look` after drop 2 | a **takeable** toy is in the channel **and** the player has not done `/look`, `/take` or `/use` on any takeable toy | You can look at this new item. Try /look {name}. | Draft |
| `hint.take_toy` | the player's first `/look` at any takeable toy after drop 2 | a **takeable** toy is in the channel **and** the player has not done `/take` or `/use` on any takeable toy | This toy can be picked up. Try /take {name}. | Draft |
| `hint.use_toy` | the player's first successful `/take` of any takeable toy | the player has not done `/use` on any takeable toy | Give this toy a shake. Try /use {name}. | Draft |
| `hint.hold_to_use` | the first time a `/use` on any toy is refused for not holding it | first occurrence only | You need to hold it to use it. Try picking it up with /take {name}. | Draft |

**Two token corrections, both small and both silent failures if missed.** `{user}` is not a token the engine substitutes — the member a public line is about is **`{player}`**, per the Functional Spec's templating list. And `{toy}` is not one either; a thing's name is **`{name}`**. Corrected above and in the public line below.

**`defaults.tsv` cannot carry a drop-2 wording of an existing hint, which is why hints 3 to 5 are new keys rather than overrides.** That file has two columns, `key` and `text`, with no `since_drop`. So `hint.look_specific` — which drop 1 defines as *"Specific things can be looked at. Try /look cat bed"* — cannot acquire a second, wand-flavored version. Distinct keys are cheaper than adding `since_drop` to `defaults.tsv` and easier to read, but the consequence is that the hint set grows with every drop rather than being re-pointed.

**That overlap needs a precedence rule.** A drop-2 player who never looked at the bed is eligible for `hint.look_specific` *and* `hint.look_wand` on the same first `/look`, and only one hint goes per message. **Recommended: the newest drop's hint wins**, because it points at content the player has not seen. Nothing is lost — the bed hint fires on their next `/look` if it is still unsatisfied. The existing invariant does the rest: a hint is suppressed once the player has done the thing it recommends.

**The three middle rungs are toy-agnostic, because drop 2 now ships two toys.** With a feather wand and a crinkle ball drawing against the same two channel slots, a hint that names one of them can point at a toy that is not there, and the player's first guided action would come back `take_fail.absent` — the worst available outcome for a release whose job is proving the rail works. So the keys are `hint.look_toy`, `hint.take_toy` and `hint.use_toy`, the text carries `{name}`, and the preconditions count **the verb rather than the verb plus a noun**: *has not taken any takeable toy*, not *has not taken a feather wand*. That also restores the invariant we have held since drop 0 — a player who took a crinkle ball has learned the lesson, and the rail must stop telling them to take a wand.

**`{name}` has two different sources, and this is the detail most likely to be built wrong.** For `hint.look_toy` and `hint.take_toy` it resolves to **a takeable toy currently in the channel**, chosen when the hint fires rather than when the drop opens. For `hint.use_toy` it resolves to **the toy the player has just taken**, because they are holding it and naming a different one would be nonsense.

**Only takeable toys count, anywhere in the rail.** These rungs teach `/look`, `/take` and `/use` on something you pick up, and the Amazon box is a fixture — so a player who somehow reaches the Entryway before the rail has finished must not be offered the box as the subject of *Try /take*, which would refuse with `take_fail.fixture`, and looking at the box must not count as satisfying a rung. Filter the candidate set to `type = toy` **and** `takeable = yes`, in both the precondition and the `{name}` lookup. `hint.hold_to_use` needs no filter: a fixture is never carry-checked, so that refusal can only ever arise from a takeable toy in the first place.

### The public fluff line

| Key | When | Text | Status |
| --- | --- | --- | --- |
| `bed_yield.public` | the fluff that dislodges something, in the channel | As {player} fluffs the cat bed, something falls out. | Draft |

**It replaces the ordinary public fluff post for that one fluff rather than adding to it**, so a yielding fluff produces one public line and not two. Worth confirming one thing the *(if applicable)* was carrying: if the bed's ordinary fluff is private today — the Functional Spec makes `/use` on a thing private except the staircase plank — then this is the bed's only public line, and there is nothing for it to replace.

**Settled: there is no private fluff variant.** The public line and `hint.bed_yield` carry the news between them, so the `cat_bed` `use` row at `since_drop = 2` is dropped and nothing in this deck is outstanding. The drop 1 fluff reply stays exactly as it is, on every server, at every drop.

### Three rungs from the earlier ladder are gone

Worth noting rather than discovering later. The work order's §10 ladder had a hint after the **first ramp refusal** — *she is not always in the mood, try again* — and hints pointing at **`/inventory`** and **`/drop`**. This ladder has none of the three.

The `/inventory` and `/drop` omissions are a judgement call: drop 2 registers both commands and now nothing tells a player they exist.

The refusal one is the one I would reconsider. **The first play attempt is a guaranteed refusal by design** — the ramp starts at 0% — and the refusal copy is deliberately written to promise nothing. With no retry hint, a player's introduction to the toy is a failure with nothing anywhere telling them that trying again *is* the mechanic rather than a dead end. `hint.hold_to_use` does not cover it: that one is the not-carried case, not the ramp.

## Summary of what drop 2 actually needs

| Item | Count | State |
| --- | --- | --- |
| New `defaults.tsv` key — `use_fail.not_carried` | 1 | Drafted above |
| Existing defaults reused as-is | 4 | No writing needed |
| Feather wand — `look`, `use` success, `use_fail.cooldown` | 3 | Drafted above |
| Crinkle ball — look, use success | 2 | Drafted in §3, moved into drop 2 |
| Generic play refusals | 12 | Drafted above |
| *Persuasive*, *Impressively Bad Luck* and *Tireless* unlock lines | 3 | **The first two are already final in the drop schedule — confirm rather than rewrite.** *Tireless* is drafted in §5 and its name is confirmed. |
| The drop 2 hint ladder | 5 | **Drafted in §8.** Six hints, one of which reuses `hint.something_new`, so five are new keys |
| The cat bed's drop 2 fluff variant — something falls out of it | 0 | **Settled: not needed.** The public line and `hint.bed_yield` carry it, so the `since_drop = 2` row is dropped. |
| The public fluff line — `bed_yield.public` | 1 | Drafted in §8 |

**The two already-final unlock lines, quoted here so nobody has to open the drop schedule tab.** That tab carries an out-of-date banner; the live version is the `drop-unlock-schedule.md` file delivered with the 3a work order, and these are taken from it unchanged.

- *Persuasive* — unlock: *Tempted the cat into playing with a toy.* Prompt: *Play with the cat*
- *Impressively Bad Luck* — unlock: *The cat ignored your attempts to play four times in a row.* Secret, so no prompt.

**Twenty-seven new strings for drop 2**, with the hint ladder and the public fluff line drafted in §8 and no open questions left in them. Everything else in §§3–5 is bank, not backlog.
