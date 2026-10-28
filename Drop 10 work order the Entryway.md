# Drop 10 work order: the Entryway

*27 October. For the developer. Drop 10 opens the house: a player crosses the road, comes into the Entryway, finds salmon behind the coat tree and feeds the cat at her bowl. Feeding opens the rest of the room for that player. The reasoning behind each decision is in the Entryway fragmentation and Feeding design tabs; this page is what to build.*

**Depends on:** The channel as a room, which covers the road, the house exit, the front door, the location check and thread membership. The two ship together.

**Decided 27 October:**

- **No hints for the feeding quest, as a trial, and no drop 10 announcement.** *Room Service* in the player's open quests does that job.
- **The road shows the house only to players who know about it:** they've earned *Purrsuasive*, used `/look house`, or been inside. Most players reach the Entryway through *Purrsuasive*, so they already know `/look` and `/take`. The `knows_house` flag behind this is specified in The channel as a room.
- **Guessing is fine.** A player who types the name of something they haven't seen yet can still reach it.
- **Chicken, tuna and gourmet now require `can_opener|cat_bowl`** in `things.tsv`. They're drop 30 data, already in the files, with their text to come later.

## What the player experiences

1. **Arriving.** The Entryway shows fragment 1 only: *A tall foyer under a water-stained **ceiling**. The **front door** is shut behind you, with a crowded **coat tree** beside it and an empty cat **bowl** on the floor.* The *Room Service* quest is visible: *Find the cat something to eat*.
2. **Finding the food.** `/look coat tree` reveals the salmon behind its base. `/take salmon` draws a can from the stash, which never runs out.
3. **Feeding.** `/use salmon` in the Entryway succeeds. The player gets the salmon's feeding line, the room gets `feed.public`, *Room Service* is awarded, `fed_the_cat` is written, and `en_settles` follows as a one-time private notice.
4. **The room opens, for that player only.** From then on, fragments 2 to 7 show as they arrive: 2 to 5 and 7 at drop 20, 6 at drop 30. The doorways in fragment 6 also open as exits.

## Content files: already in creative content

| File | What's there |
| --- | --- |
| `room_text.tsv` | Entryway fragments 1 to 7, plus fragment 7's `stairs_repaired` version. Fragments 2 to 7 have `visible_when = fed_the_cat`. The two old one-block Entryway rows are gone. |
| `things.tsv` | `cat_bowl`: a fixture in the Entryway at drop 10. `coat_rack` is renamed *coat tree*, and `coat rack` stays as an alias. `cat_food_salmon` now has `requires = cat_bowl`. |
| `thing_text.tsv` | The coat tree's and the salmon stash's looks. The two doorway looks, rewritten so the rooms are discovered rather than named. The cat bowl's three lines. The salmon's look (with its pull ring), its `use` and its `use_fail`. |
| `defaults.tsv` | `feed.public`, `feed.not_hungry`, `feed.wrong_time_and_place`, `en_settles` |
| `achievements.tsv` | `room_service`: public, offered, drop 10, prompt *Find the cat something to eat*, requires `making_first_contact` |

## Code changes

1. **Room text fragments.**
   - Show a room's description as its fragments in fragment order.
   - For each fragment, use the row with the highest arrived `since_drop`. Among those rows, pick the one whose `state` matches the room's current state, and fall back to `default`.
   - Honor `visible_when` exactly as `looked_at_bed` is read in the channel: one lookup against the per-player hints table.
   - The road's fragment 60 needs the same rule; see The channel as a room.
2. **`fed_the_cat`.** Write it on a player's first successful feed of any flavor, at the same moment *Room Service* is awarded. Keep it as its own flag in the hints table rather than reading the achievements table.
3. **`en_settles`.** Send it once, privately, right after the feed that first sets `fed_the_cat`.
4. **The doorways are gated.**
   - Until `fed_the_cat`, the Entryway's exits `ED`, `EL` and `EH` don't exist for that player: they aren't in the room text, and `/go` through them gets the standard no-such-exit refusal.
   - The front door is never gated.
   - This is the only per-player gate on exits. It's safe because feeding can always be done in the Entryway: the cat, the bowl and an endless salmon stash are all there. Leave a comment in the code saying so, so nobody later adds a feeding requirement the Entryway can't meet.
5. **Things named in hidden fragments aren't gated.** An unfed player at drop 20 who guesses `/look mirror` still sees the mirror. Only the room text is per-player. This is the agreed scope cut, not a general per-player `present_when`.
6. **`requires` can be met from the room.** A non-takeable thing in the player's current room satisfies it, as well as a thing they're carrying. That's how the bowl works. Takeable things still have to be carried.
7. **Which refusal a feed gets.** Check in this order:

   | The cat is | The bowl is | Refusal |
   | --- | --- | --- |
   | not hungry | missing | `feed.wrong_time_and_place` |
   | not hungry | present | `feed.not_hungry` |
   | hungry | missing, or the opener is | the flavor's own `use_fail` |
   - A missing opener alone doesn't change the not-hungry answer.
   - The expired can is outside all of this. It isn't a feed, so its own refusal always speaks.
8. **Hunger.**
   - Per player. The cat is hungry when eight hours have passed since that player's last successful feed, read from `thing_uses.last_used_at` across the food rows.
   - A refused feed doesn't write that timestamp and doesn't use up the can, but it does stamp `last_cat_interaction_date`.
   - A successful feed is worth +10 and uses up the can.
9. **`feed.public`.** Post it in the room on every successful feed of any flavor, the way `bed_fluff.public` works. It doesn't fire for the expired can.
10. ***Room Service*.** Award it on the first successful feed. It's visible from drop 10 to players who have *Making First Contact*. It's offered, so the quest notice carries its prompt.

## Logging

One `interaction_log` row per feed attempt:

- `action = feed` and the food as `thing_id`.
- `outcome = success` or `refused`.
- On a refusal, `reason` is `not_hungry`, `wrong_time_and_place`, `no_bowl` or `no_opener`.
- `relationship_delta = 10` on a success.

## Acceptance tests

Run on a QA server, using `/qa-drop` to reach drop 10.

**Arriving and finding the food**

- A new player entering the Entryway sees fragment 1 only, and the *Room Service* quest with its prompt.
- `/look coat tree` mentions the salmon behind the base. `/look bowl` shows the bowl. `/use bowl` gets *Nothing to be done with an empty bowl except fill it, and that takes a can.*
- `/take salmon` gives a can, and the stash never runs out.

**Feeding**

- `/use salmon` in the Entryway gives the salmon's feeding line. The room sees *{player} fed the cat. Finally.* The player earns *Room Service* and then gets `en_settles`.
- Feeding again within eight hours, in the Entryway, gets `feed.not_hungry`.
- Carrying salmon onto the road while the cat is hungry gets *What were you planning to do, pour it on the floor? You need a cat bowl.*
- On the road with the cat not hungry, the player gets `feed.wrong_time_and_place`.
- A refused feed keeps the can and doesn't reset the hunger timer.

**After the first feed**

- At drop 20, the fed player sees fragments 1 to 5 and 7. An unfed player on the same server still sees fragment 1 alone.
- At drop 30, the fed player also sees fragment 6, and `/go arched doorway` and `/go dining room` both work. An unfed player gets the no-such-exit refusal for both, and `/go road` still works for them.
- After the stairs are repaired, fragment 7 shows the patched staircase.
- `/look arched doorway` and `/look wide doorway` give the glimpse lines, which don't name the rooms.
- `feed` rows appear in `interaction_log` with the right outcome and reason.

## Addendum, 27 October: the house starts locked

*Added after work began. It touches the `house` exit, the bed fluff and one new item. Nothing above about feeding or the Entryway changes.*

**The idea.** Beta players already cooperate, swapping toys when someone is short. At drop 10 the front door is locked for the whole server, and a single key falls out of the cat bed. Whoever picks it up has to `/use key` on the road, and that unlocks the door for everyone. Taking the key is public, so the others can scroll back to see who has it.

**How it works**

1. **A server-wide state, `house_unlocked`**, unset at drop 10. It works like `stairs_repaired`.
2. **The `house` exit refuses while the door is locked.** Its `default` row is the locked state: a locked look, and a `use_fail` that also answers `/go house`. Its `house_unlocked` row has the normal look, `use` and move lines. This is the same pattern as `EH` before the staircase is repaired.
3. **The first key falls out of the bed.** On the first successful fluff by anyone on or after drop 10, a `house_key` drops onto the road. It uses the bed's existing dislodge behavior. The public line is `bed_yield.key.public` instead of `bed_yield.public`, and the fluffer still gets `hint.bed_yield`.
4. **Spares, while the door stays locked.** At least 24 hours after the last key fell, the next successful fluff drops another key. This repeats at most once a day until the door is unlocked, and stops for good once it is. `max_per_player = 1`, so a spare always goes to someone new.
5. **`/use key` on the road unlocks the door.** `requires = house`, so it only works where the house is. It sets `house_unlocked`, gives the player `house_key.use`, and posts `unlock.public` on the road. The player keeps the key afterwards.
6. **Any key after unlocking** gets *The door is already unlocked.* (the `house_unlocked` row's `use_fail`). Keys can still be taken, dropped and passed around.
7. **A locked `/go house` sets `knows_house`.** A player who tries the door clearly knows the house is there, so this counts alongside `/look house` and going in.
8. **Reset.** `/qa-reset` clears `house_unlocked` and removes every key.

**Content: already in creative content**

| File | What's there |
| --- | --- |
| `things.tsv` | `house_key`: *brass key*, aliases `brass key\|key\|house key\|front door key`, object, `requires = house`, `max_per_player = 1`, drop 10 |
| `thing_text.tsv` | `house` split into `default` (locked) and `house_unlocked`; `house_key` in both states |
| `defaults.tsv` | `bed_yield.key.public`, `unlock.public` |

| Key | Text |
| --- | --- |
| `house.look`, locked | A tall, square house across the road, dark in every window. The front door is shut and has the look of being locked, via three heavy brass deadbolts. The cat takes a step toward it and glances back at you expectantly. |
| `house.use_fail`, locked | You cross the road and try the front door. You'd be inside by now, except that it's locked. |
| `house_key.look` | A heavy brass key on a loop of faded ribbon. It looks like it belongs to a front door. |
| `house_key.take` | {player} pockets the brass key. |
| `house_key.drop` | {player} sets the brass key down. |
| `house_key.use` | You fit the key into the front door. The same key turns all three deadbolts, and one after another they slide back with a clunk you feel in your teeth. |
| `house_key.use_fail`, locked, away from the road | There's nothing here for it to open. The lock it was made for is at the front of the house. |
| `house_key.use_fail`, unlocked | The door is already unlocked. |
| `bed_yield.key.public` | {player} fluffs the cat bed, and something small but heavy falls out of it with a clink. |
| `unlock.public` | {player} unlocked the front door of the house. |

**The locks match inside and out.** The Entryway side of the front door reads *three separate locks, every one of them undone*, so the outside says three deadbolts and one key turns all three.

**Logging:** `key_dropped`, with whether it was the first key or a spare and who fluffed; `take` and `drop` rows for the key, as with any item; and `unlock`, with the player.

**Acceptance tests**

- At drop 10, `/go house` and `/use front door` on the road get the locked refusal, and `/look house` shows the locked look.
- The first fluff after drop 10 drops one key with `bed_yield.key.public`. A second fluff the same day drops nothing.
- `/take key` posts *{player} pockets the brass key.* A player who already has a key can't take a second.
- With the door still locked 24 hours after the last key fell, the next fluff drops a spare. Once the door is unlocked, no more spares fall.
- `/use key` on the road unlocks the door: the player sees `house_key.use`, the road sees `unlock.public`, and every player can now `/go house`. The house shows its unlocked look.
- `/use key` after that, by anyone holding a key, gets *The door is already unlocked.*
- A locked `/go house` sets `knows_house`, so the road then shows that player the house line.
- `/qa-reset` relocks the door and removes all keys.

## Not in this work order

**Drop 30 and 40 feeding:** the other four flavors, the expired can and its −75, *One Star Review*, and the `relationship_delta` column. These are still open; see the Entryway fragmentation tab's Open questions.
