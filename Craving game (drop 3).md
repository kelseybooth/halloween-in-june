# Craving game (drop 3)

*26 October. Replaces every earlier version of the reaction rules, including the 😾 and 🔄 ladder. The source of truth for which emoji belongs where is the writers' `emoji-catalogue-v18.csv`, in the creative content folder. The two content files below are generated from it.*

## The game in one paragraph

Every day the cat craves one food or one prey animal. Players guess it by reacting with an emoji on any of the bot's public messages. The bot answers each guess with a cat face that says how close it was. The first correct guess a player makes each day earns them 5 relationship points. Nothing announces the game. A player who reacts with a heart on someone's achievement gets a 🐱 back, and that's the clue that the cat is watching.

## How a guess is judged

The catalogue sorts every emoji into a **category** and a **type** within it. Food has seven types (Veggie, Fruit, Meal, Bakery, Protein, Fast Food, Dessert). Prey has four (Bird, Bugs, Mammal, Scales). Adjacent has four (Drinks, Dishes, Ingredient, Cooking). Toy has two (Conventional, Unconventional). Misc and Cat have only Unrelated.

**Today's craving is always Food or Prey.** Adjacent and Toy can score a 😼 but never more.

Checks run in this order, and the first match decides:

| # | The guess | Outcome | Bot reacts |
| --- | --- | --- | --- |
| 0 | Marked `excluded` (the bot's own six reaction emoji) | Ignored | nothing |
| 1 | Misc or Cat, or not in the list at all | `greeting` | 🐱 |
| 2 | Adjacent, Toy, Food or Prey, but not today's category | `wrong_category` | 😼 |
| 3 | Today's category, wrong type | `right_category` | 😸 |
| 4 | Today's type, wrong emoji | `right_type` | 👀 |
| 5 | Today's craving | `win` | 😻 |
| — | Any wrong guess once the message has 19 different emoji on it | `out_of_guesses` | ❌ |

**"Not in the list" means Misc.** The list doesn't include skin-tone variants or server custom emoji, so a 👍🏽 or a custom emote gets the friendly 🐱 like any other unrelated emoji.

## What the message shows

The bot's reactions describe the message, not each guess, because Discord lets the bot add each emoji only once per message. So:

- **Each message shows only its highest outcome so far**, ranked by the `progression` column: 🐱 1, 😼 2, 😸 3, 👀 4, 😻 5. When a guess beats the message's current outcome, the bot removes its old reaction and adds the new one. A guess at or below the current outcome changes nothing.
- **The face walks along to the newest guess it answers.** Reactions are shown in the order they were first added, so a face that is still right drifts left as more guesses land beside it and ends up reading as a verdict on somebody else's guess. When a guess earns the outcome already showing, the bot takes its reaction off and puts it back, which moves it to the end. Only then: a worse guess must not drag the face down to it, a face a player has also clicked will not move at all, and a message at 19 is left alone because the ❌ is about to close it.
- **Removing the bot's reaction doesn't always free a slot.** If a player also clicked it, the emoji stays on the message with their count. So the bot must never keep its own tally of slots. It reads the message's live reaction list every time.
- **❌ at 19.** After the player's reaction lands, if the message has 19 or more different emoji and the guess isn't the craving, the bot adds ❌. That fills the twentieth slot, and nobody can add a new emoji after that.
- **A correct guess at 19 still gets 😻.** It takes the twentieth slot.
- **Old messages carry yesterday's answers.** The craving changes at midnight but reactions don't, so a 😻 from yesterday would point at the wrong emoji today. Store the message's outcome per game day. The first time a guess lands on a message today, the bot clears any game reactions it left there on an earlier day before judging.

## Scoring

- **5 relationship points for a correct guess, once per player per day.** That's `craving_points = 5` in config, so it's tunable like the toy and bed. It's deliberately small, because copying someone else's correct guess is easy, and that's fine.
- **"Found" is per player.** One player's win ends the game only for them. Everyone else keeps guessing on the same messages.
- **The display doesn't depend on who's guessing.** A player who already won today still gets 😻 if they click the answer again; they just don't score. This keeps the reaction logic a function of the emoji and today's craving only, which is simpler to build and to test.
- **The first win fires *Met the Craving*** (drop 3), with the standard public achievement message only, and it **@mentions the player**. No private message goes with it, because a reaction can't trigger one - so the public line is the whole announcement, and a printed name in a channel nobody is watching is one the earner never sees. Every achievement with no private half mentions its earner, not only this one. **Guesses don't count as cat interactions.** A guess, right or wrong, doesn't stop the overnight drift and doesn't count toward *Lucky Black Cat*.

## The /stats hint

A new status line, `stats.status.craving`, in the POC copy deck:

> She's craving something very specific today.

- **Shown only once the player has earned *Purrsuasive***, so new players aren't given one more thing at once. Drop 3 on.
- **It comes last, on a line of its own**, after the relationship description and any expectant, hungry or crowded line. Run on after one of those it reads as one more sentence about the petting, which is what the beta testers reported.
- **It vanishes once the player finds today's craving**, and returns the next day when the craving rolls over. There's no replacement line; the 😻 and the achievement announcement already confirm the win.

## Today's craving

- **Rolled once per server at Pacific midnight**, through `server_now()` like every other daily reset.
- **Drawn from rows with `drawable = yes`.** That's all Food and Prey, 136 emoji, minus two new in Unicode 18.0 (🫝 pickle and 🫌 monarch butterfly). Discord's emoji picker may not have them yet, and a craving nobody can type is unwinnable.
- **Uniform over emoji**, so Food comes up about 70% of the time and Prey 30%, in proportion to their size. If you want them even, draw the category first and then the emoji. It's a one-line change, and the content files don't change.
- The first 5 days of the game should have the cravings be the following, before random selection begins:
  - Mouse
  - Cut of meat
  - Broccoli
  - Fish
  - Egg

## The content files

**`emoji_groups.tsv` — revised.** One row for every emoji in the catalogue (1,927), same order:

`emoji · code · name · category · type · drawable · excluded`

- `category`, `type` and `excluded` are copied straight from the catalogue's Category, Type and Game Exclusion.
- `drawable` is derived: `yes` for Food and Prey, `no` for the two Unicode 18.0 emoji and everything else.
- The old `subgroup` column is gone. Category and type replace it, so the loader needs updating.
- Drinks are Adjacent now, not food, so a drink can earn 😼 at best.

**`craving_reactions.tsv` — new.** Six rows mapping each outcome to the emoji the bot reacts with and its `progression` rank. ❌ has no rank; it isn't part of the ladder. Keeping these in a file means the writers can swap a reaction emoji without a code change.

**When the writers edit the catalogue**, regenerate both files from it rather than hand-editing the TSVs.

## Developer notes

- **Strip U+FE0F (variation selector 16) from both sides before matching.** Discord sends 🕷️ with it, but the catalogue lists 🕷 without it. The catalogue isn't consistent either: 158 rows include it and the rest don't. Without stripping, those emoji silently fall through to `greeting`.
- **Which messages count:** any public message the bot posted in the game channel. Ignore reactions added by bots, and ignore reaction removals.
- **Rate limits:** an outcome change costs two calls (remove, then add). Queue per message, and if several guesses land at once, apply only the final highest outcome.
- **Telemetry:** one `interaction_log` row per judged guess, with `action = craving_guess`, the emoji and outcome in `detail`, `outcome = win` or `miss`, and `relationship_delta = 5` only on a scoring win.

## Answered questions

- **G****u****e****s****s****e****s**** ****d****o**** ****not c****o****u****n****t**** ****as a cat interaction**&#32;
- ***Met the Craving* ****s****h****o****u****l****d be a** **s****e****c****r****e****t**** ****a****c****h****i****e****v****e****m****e****nt**
- **D****rop 3 ****d****o****e****s**** ****not ****get an announcement**
- **🫜 root vegetable** is Unicode 16.0, and Discord's picker has it so it can be drawable
