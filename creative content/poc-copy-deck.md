# POC copy deck — drops 0 and 1

Every string the proof of concept needs, for review and editing. Twenty-three in all, every one of which now has text. The Status column is the authority on which are final.

**Status column:** *locked* = final, agreed copy. *draft* = has text, not yet confirmed. *parked* = written and kept, but not used in the POC. **Nothing is a *gap* any more** — that label meant a string with no text at all, and every row in the deck now has words in it.

---

## Settled conventions

**Hints are in the game's voice, not the cat's.** Every hint is *italicised* and prefixed with **Hint:**, so a player can see at a glance that the game is speaking rather than the cat changing character. The format is fixed across all six:

> She allows it, briefly, and then moves out of reach.
>
> *Hint: This is your first achievement. Check /stats to see achievements and open quests.*

That resolves the voice problem without softening the instruction — which matters, because two playtesters did not know slash commands existed and clarity beats charm in a tutorial line. The label also makes hints skippable for anyone who does not need them.

**The cat is "she" — settled.** Female pronouns throughout, never *it*. This now needs **one sweep across every content file and the code**, since pet blurbs, refusals and achievement text all carry a pronoun. The known holdout is the existing `/look cat` description — *"It looks up at you with moonbright yellow eyes"* becomes *"She looks up at you…"*. Do it as a single pass rather than string by string, so nothing is left half-converted and looking finished.

**`/look`**** in the channel does not list the cat.** `/look cat` stays an easter egg, found rather than signposted; the only things the player is guided toward are the bed, and later the toy.

---

## 1. `/stats` — the relationship line

**Both, in: the raw figure and a sentence interpreting it.** The number says which way the player is moving — a pet landing shows as five points — and the sentence says what the number *means*, which a bare integer never can. They are doing different jobs, so they go together.

**Nine bands, revised 17 October after testing.** The sentence sits under the figure, and both lines are labelled - a bare integer at the top of an embed does not say what it counts.

> Cat relationship strength: -5
> The cat is still trying to decide how she feels about you.
> Total pets: 1

| Key | Score | Text | Status |
| --- | --- | --- | --- |
| `stats.rel.unimpressed` | -100 to -31 | The cat is thoroughly unimpressed. | **locked** |
| `stats.rel.irritated` | -30 to -6 | The cat is mildly irritated. | **locked** |
| `stats.rel.undecided` | -5 to 5 | The cat is still trying to decide how she feels about you. | **locked** |
| `stats.rel.warming` | 6 to 50 | The cat is warming up to you. | **locked** |
| `stats.rel.may_stay` | 51 to 100 | The cat has decided you may stay. | **locked** |
| `stats.rel.likes` | 101 to 150 | The cat genuinely likes you. | **locked** |
| `stats.rel.claimed` | 151 to 200 | The cat has claimed you as her human. | **locked** |
| `stats.rel.adores` | 201 to 300 | The cat adores you. | **locked** |
| `stats.rel.anywhere` | 301 and up | The cat would follow you anywhere. | **locked** |

| Key | Text | Status |
| --- | --- | --- |
| `stats.relationship` | Cat relationship strength: {score} | **locked** |
| `stats.pets` | Total pets: {count} | **locked** |

**What the nine fixed.** The four bands they replace were wide enough to be unhelpful: *"She tolerates you"* was true at 1 and at 99, which is most of a month's play in one sentence. The three narrow bands around zero are where a new player spends their first week, and where a single pet should feel like it moved something; the upper ones widen again because by then a player is measuring in days.

**Zero is no longer its own band.** It said the cat did not care about you, which is a hard sentence to read on your first `/stats` - and it is where the drift returns everybody, so it was not only for new players. It sits inside *still trying to decide* now.

**The figure still earns its place.** A player can sit in one band for days, and only the number shows which way they are going. It stays visible and unrounded: the sentence says what the number means, the number says where it is heading, and neither does the other's job.

**The top band has no ceiling** because the meter has none - *Favorite Human* is at 250 and nothing stops a player going past it.

---

## 2. `/stats` — structure and empty states

| Key | When | Text | Status |
| --- | --- | --- | --- |
| `stats.header.quests` | only when the player has at least one visible quest | Open Quests | locked |
| `stats.header.achievements` | always | Completed Achievements | locked |
| `stats.quests.empty` | never — parked, see below | No open quests | parked |
| `stats.achievements.empty` | nothing earned | No completed achievements. Try /pet. | **locked** |

**Both lists run newest first.** Most recently earned achievement at the top, so *Making First Contact* sits at the bottom forever; most recently unlocked quest at the top, which is where a player looks after being told a new one is available.

Three notes for the build. **Achievements need an awarded-at value to sort on**, and `player_achievements` is keyed on `(guild, user, achievement_id)` with no stated timestamp — if there is none, descending insertion order gives the same answer for free. **Quests can reuse the hint rail's table**, which already records which quests a player has been told about and therefore in what order they appeared. And **ties need a deterministic tiebreak**: the dispatcher is explicitly allowed to fire two achievements from one action, so two rows can share a timestamp, and without a second sort key the order flickers between renders. Insertion id descending is enough.

One side effect: `sort_order` in `achievements.tsv` no longer drives `/stats`. It may still earn its place elsewhere, but nobody should maintain it believing it controls what a player sees.

The empty state is carrying real weight: with `/help` deferred, `/stats` is the only place in drop 0 that explains the game exists. **The quest section disappears when there is nothing in it** — header and empty line both. With only three public quests in the whole plan, a player will spend long stretches with none open, especially past the early game, and a standing *"Open Quests — No open quests"* would read as something broken rather than as something waiting.

**The achievements section stays unconditional**, because its empty line is the only instruction in the game: *"No completed achievements. Try /pet."* Hiding that would leave a first-time `/stats` showing nothing but a number.

`stats.quests.empty` is kept in the deck rather than deleted. If testing says the absent section reads as a missing feature rather than as a clean screen, it goes back in as a placeholder with no code change beyond the condition.

---

## 3. The hint rail

Six lines, each shown once per player, at most one per message.

Every hint renders as *Hint: \<text>* in italics. The strings below are the text after the label; the label itself is not part of the string, so it is not translated or edited per line.

### Drop 0

| Key | Trigger | Text | Status |
| --- | --- | --- | --- |
| `hint.first_friendly` | first pet that rolls friendly — same message that awards *Making First Contact* | This is your first achievement. Check /stats to see achievements and open quests. | locked |
| `hint.first_standoffish` | first pet that rolls standoffish | Petting affects your relationship with the cat. Check /stats to view it. | locked |

### Drop 1

| Key | Trigger | Text | Status |
| --- | --- | --- | --- |
| `hint.something_new` | first private message after drop 1 opens, if the player has not yet run `/look` | There is something new here. Try /look. | locked |
| `hint.look_specific` | first `/look` at drop 1 or later, if the player has not yet run `/look cat bed` | Specific things can be looked at. Try /look cat bed. | locked |
| `hint.try_use` | first `/look cat bed`, if the player has not yet run `/use cat bed` | Things can be used, too. Try /use cat bed. | locked |
| `hint.try_look` | first `/use cat bed`, if the player has not yet run `/look cat bed` | Things can be looked at, too. Try /look cat bed. | locked |

#### One rule that covers all the preconditions

`hint.try_use` and `hint.try_look` are a mirrored pair: whichever of looking and using a player does first, the hint points at the other, and each is suppressed once the player has done the thing it recommends. Rather than write that condition onto each hint, state it once as an invariant:

**Never recommend an action the player has already taken.**

That gives both preconditions for free, and it catches a third case nobody has written down. A player whose first `/look` is `/look cat bed` would otherwise get `hint.look_specific` — *"Specific things can be looked at. Try /look cat bed"* — telling them to do the thing they just did. Under the invariant it is suppressed, and the pair above cannot loop.

Two mechanics follow from it. **At most one appended line per message**, since one action can satisfy more than one trigger: a player typing `/look cat bed` first matches both the generic look hint and the specific one, and two stacked hints on one reply is worse than either alone. And **a hint is retired either by being shown or by being made moot** — the same row in the same table, so nothing resurfaces later as advice to do something already done.

### The quest notice

| Key | Trigger | Text | Status |
| --- | --- | --- | --- |
| `hint.new_quest` | first private message after a quest becomes visible — **until** the player has attained 3 quests **and** opened `/stats` at least once | A new quest is available. Check /stats. | locked |
| `hint.new_quest.named` | the same trigger, once the player has attained 3 quests **and** opened `/stats` at least once | A new quest is available. {quest\_name}: {quest\_prompt} | locked |

**The notice graduates.** Early on it teaches *where to look*; once the player has three quests behind them and has opened `/stats`, it stops signposting and delivers the quest itself. Both conditions matter and the **and** is doing real work: three quests means they understand what a quest is, opening `/stats` means they know where the log lives. Neither alone is enough to stop pointing at it.

Three notes for the build.

**It needs one new flag, and the rail already has a home for it.** "Has opened `/stats`" is a single row in the same per-player table that records which hints and quests a player has been told about — `/stats` already writes to that table to mark quests as seen, so this is one more id, not new storage.

**Use `{quest_prompt}`, not `{quest_prospective_blurb}`.** The string comes from the `prompt` column on `achievements.tsv`, and a token that matches the column name is what a developer will reach for. `{quest_name}` matches `name` the same way. Both follow the existing `{player}` convention.

**Settled: prompts carry no terminal full stop, and the template adds none.** *"Attain a relationship of +50 with the cat"* and *"Give the cat a cozy nap spot"* were already right, and *"*Play with the cat*"* loses its stop to match. `hint.new_quest.named` ends on the prompt and adds nothing after it, so a sentence like *A new quest is available. Persuasive: Play with the cat* closes on the prompt's own last word — which is the only way to make three prompts of different shapes read the same in one template. The rule generalises: **a string that will be interpolated into the end of another string does not punctuate its own ending.**

---

## 4. The cat bed

One bed, in the channel, from the moment drop 1 opens. Usable, not takeable, never consumed.

| Key | When | Text | Status |
| --- | --- | --- | --- |
| `cat_bed.look` | `/look cat bed` | A round cushion in dark green corduroy, flattened in the middle where something has slept. This is the sort of bed that looks plumpable. | locked |
| `cat_bed.use` | `/use cat bed`, first time that day | You shake out the cushion and fluff it back into shape. The cat watches the entire operation, then walks over, turns around three times, and sits down without looking at you. | locked |
| `cat_bed.use_fail` | `/use cat bed` within 24 hours of the last fluff | The bed already looks fluffy and cozy. Your services are not required today. | locked |
| `cat_bed.take_fail` | `/take cat bed` — **drop 2 only**, once `/take` exists | You get both hands under it before the cat claims it for her own. You leave it where it is. | locked — drop 2 |

---

## 5. The channel

The Halloween channel becomes a room-like place in drop 1. `/look` there prints a list and no description.

| Key | When | Text | Status |
| --- | --- | --- | --- |
| `channel.look_prefix` | `/look` in the channel, something present | Items here: | locked |
| `channel.look_empty` | `/look` in the channel, nothing present | Nothing here but the cat, and she was here already. | locked |

**Settled: the cat is not in the list.** `/look cat` remains an easter egg for anyone who thinks to try it, and the guided path points only at the bed, and later the toy. That keeps *"Items here:"* honest — everything under it is a thing, not a presence.

**In drop 1 the empty case cannot actually happen**, since the bed is a fixture that is always present and never consumed. The string is still worth having: it is reachable from drop 2, when the toy becomes takeable and two players can clear the channel between restocks, and an unwritten fallback in that position usually surfaces as an empty list with a dangling colon.

---

## 6. No welcome and no tutorial — and the one hole it leaves

**Settled, as an experiment: the POC ships with no welcome text and no tutorial.** The hint rail and the gating replace both. The existing `defaults.tsv` welcome comes out of scope, which is just as well — it was written when "launch" meant the haunted house, and drop 0 has no house, no rooms and no `/enter` to mention.

That is a clean call, and it is worth being clear about what it costs.

### The entry point is the one thing that cannot be hinted

Every hint in the rail fires *after* a player has done something. The first one needs a friendly pet; the rest need that one. So **nothing inside the game tells a player to run ****`/pet`**** in the first place.** The ladder cannot bootstrap itself, and with the welcome gone there is no copy that does it either.

The intended answer, from the 2f discussion, still works: **an admin pets the cat in the channel, the public line posts, and everyone watching learns the command exists.** That was the argument for `/pet` resolving in the channel at all, and it is a good one — discovery by imitation rather than by instruction.

**But the public line may not carry the command name.** It reads *"{player} pets the cat. The cat seems to like it."* — which tells a reader that something happened, not what to type. Discord shows a "used /pet" attribution above a command's *own* response; our design posts the public line as a separate bot message, which carries no attribution. So an onlooker sees an event with no verb attached.

Three ways to close it, in rough order of cheapness:

- **Channel topic or a pinned message.** Server furniture rather than game copy, so it does not reintroduce a tutorial, and it is visible to everyone forever including people who scroll past the day's messages. One line: *"There's a cat in here. Try /pet."*
- **Name the command in the public pet line.** Changes a string that already exists and which fires constantly, so it would get old fast. Not recommended.
- **Accept it, and brief the admins.** Fine for the POC specifically, since the testers are known people who can be told in Discord. It is not a shippable answer for a real server.

**Recommended: the pinned message, and brief the admins as well for the POC.** It costs one line, it is not a tutorial, and it means the POC is testing the hint rail rather than testing whether people can find the front door.

### Nothing announces a drop publicly

When drop 1 opens, the bed appears — and the only thing that says so is a private hint on each player's next message, one player at a time. No public line marks the change.

**Settled: the drop is announced publicly, and `hint.something_new` rides the announcement.** The two become one moment in the channel:

> The cat swats her paw and something slides a couple feet away...something that didn't appear to be here before now.
>
> *Hint: There is something new here. Try /look.*

That is cheap, reaches everyone at once including people who were not going to type anything today, and makes the drop advance visible to the admin who triggered it — useful during testing.

| Key | When | Text | Status |
| --- | --- | --- | --- |
| `drop.1.announce` | posted in the channel when drop 1 opens | The cat swats her paw and something slides a couple feet away...something that didn't appear to be here before now.&#32; | locked |

**The pattern is now set: one announcement string per drop, each able to carry that drop's hint.** Drop 2 writes its own rather than inventing the shape again.

Two things the developer needs, because this is the first hint attached to a public message rather than an ephemeral reply.

**Keep the private firing as well.** A public line is seen once, by whoever is in the channel at the time; a player who was asleep, or who joins later, never sees it. `hint.something_new` keeps its private trigger — first private message after drop 1 opens, if the player has not yet run `/look` — as the fallback. The precondition already stops it repeating to anyone who acted on the public one, so this costs nothing and closes the hole.

**The public firing must not set the per-player shown flag.** The rail records hints per player, and a channel post has no player attached. If the announcement marked everyone as told, the fallback would be dead on arrival for exactly the people it exists for. Only the private firing writes the flag.

## Summary of what is actually needed

|  | Count |
| --- | --- |
| Locked — final text | 22 |
| Parked — kept, unused in the POC | 1 |
| Of the above, posted publicly — the drop announcement | 1 |
| Of the above, drop 2 only — `cat_bed.take_fail` | 1 |

**Every string is written and reviewed. Nothing in this deck is waiting on a writer.** What is left is not copy and should not be solved with copy: the pinned message or channel topic that points a brand-new player at `/pet`, and the pronoun sweep, now that the writer has ruled: she, everywhere, in one pass.

**One decision is still open, and it is not a writing task.** Whether the quest notice graduates at 3 quests or 2 — at 3 it cannot fire inside the POC, since only two public quests exist before drop 2. It is marked in its own section.

**One line is worth watching in testing rather than editing.** `cat_bed.look` is the only string in the POC that has to do two jobs — describe the bed, and make a player want to use it without naming the command. If a tester reads it and does nothing, the hint rail is covering for prose that did not land, and we will not be able to tell which one failed.
