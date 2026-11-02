# Watering can work order (drop 30)

Nov 2, 2026 · @Qaruse

The Courtyard's watering can becomes a takeable object with four water levels: filled in the Kitchen, emptied over the herbs, and too full to carry with anything else. The design is in The watering can. It reuses two shapes from The ladder (drop 30): the hands-full rule and the 24-hour idle drop. It ships with the Drop 30 work order.

**Depends on:** the drop 30 ladder work (the carrying block and the idle timer), the per-room `in:` rows, the trash can's one-of-a-kind rule, and *Green Thumb*'s three-part progress.

**Decided 2 November:**

- The can is cut from the room descriptions and becomes takeable. There's one, starting in the Courtyard.
- Its water level belongs to the can, shared by everyone, not to a player.
- It's filled with `/use watering can` in the Kitchen.
- A full can takes both hands. At any other level it's just carried.
- Dropping a full can keeps it full.

## What the player sees

1. **The can is in the Courtyard's Also here list**, with an inch of rainwater in it.
2. **`/use watering can` in the Courtyard waters the herbs** and takes the can down a level. The rainwater is good for one watering.
3. **`/use watering can` in the Kitchen fills it** to the brim.
4. **A full can takes both hands.** The player can carry it, move, look and drop it, but can't pet, take or use anything else.
5. **A carrier who goes quiet for 24 hours** sets it down wherever they are, and the room sees a line.

## Content

**`things.tsv`, `watering_can`.** It's parked at 99 as a fixture today. Change it to an object: `room_id` CO, `quantity` 1, `takeable` yes, `droppable` yes, `max_per_player` 1, `cross_weight` 0, `since_drop` 30. Keep the aliases `watering can`, `can`, `watering`.

**The "can" alias is shared.** The gourmet cat food (`cat_food_gourmet`) also answers to `can`. A player carrying one who types `/use can` near the watering can is asked which they mean, and a carried gourmet can and a watering can in the room should both be offered. That's the engine working as intended, not a bug. Typing `watering can` or `watering` always reaches the watering can.

**`thing_text.tsv`, `watering_can`, all at drop 30.** The `state` names the can's level. `default` is the starting level. `use` stays empty on every row, because the use lines below depend on the room as well. The old `take_fail` goes.

| `state` | `look` | `take` | `drop` |
| --- | --- | --- | --- |
| `default` | A dented galvanized watering can with a long spout and an inch of rainwater in the bottom. | {player} picks up the dented watering can. Rainwater shifts around in the bottom. | {player} sets the watering can down with a hollow clank. |
| `empty` | A dented galvanized watering can with a long spout, dry inside. A rusty ring marks where the rainwater used to sit. | {player} picks up the empty watering can. It weighs almost nothing. | {player} sets the watering can down with a hollow clank. |
| `partly_full` | The dented watering can, about half full. The water sloshes when you nudge it. | {player} picks up the half-full watering can. The water inside sloshes. | {player} sets the watering can down with a hollow clank. |
| `full` | The dented watering can, filled to the brim. The water trembles at the spout whenever anything moves. | {player} heaves up the full watering can with both hands, and water slops over the rim. | {player} sets the full watering can down too fast, and water sloshes out over the rim and onto their feet. |

**`defaults.tsv`, new keys.**

| Key | Text |
| --- | --- |
| `watering_can.water.default` | You tip the inch of rainwater over the herbs, and that's all of it. They accept it graciously. |
| `watering_can.water.full` | You give the herbs a long, even shower. They did not need it, and accept it graciously. The can feels lighter. |
| `watering_can.water.partly_full` | You water the herbs until the can runs dry. They accept it graciously, as always. |
| `watering_can.water.empty` | You tip the can over the herbs. One drop comes out. It needs filling first. |
| `watering_can.fill` | You hold the can under the faucet and let it fill all the way to the brim. It's suddenly very heavy. |
| `watering_can.fill.already_full` | It's already full to the brim. Any more and you'd be watering the kitchen floor. |
| `watering_can.elsewhere` | You look around for something that needs watering. Nothing in here does. |
| `watering_can.elsewhere.empty` | It's empty. |
| `carrying.watering_can` | You'd need a free hand, which you don't have with this full watering can. |
| `exhausted.public` | {player} gets tired and sets the {name} down. |

**Room text:** none. The can is already cut from the Courtyard's description.

## Code changes

1. **A state that belongs to a thing.** The can's level is shared by every player, which no existing state is: today's states belong to a player or to the server. Store it per server for the can, start it at `default`, and resolve the can's `look`, `take` and `drop` by it. It never returns to `default`.
2. **`/use watering can` by room and level.** In the Courtyard, a can with water uses the `watering_can.water.*` line for its level and goes down one level: `default` and `partly_full` to `empty`, `full` to `partly_full`. An empty can gets `watering_can.water.empty` and stays empty. In the Kitchen, any level but full goes to `full` with `watering_can.fill`, and a full can gets `watering_can.fill.already_full`. Anywhere else, the level doesn't change: `watering_can.elsewhere`, or `watering_can.elsewhere.empty` if the can is empty.
3. **Carried or in the room.** `/use watering can` works on a carried can or one in the Also here list. Using a carried can doesn't set it down, unlike the ladder.
4. **A full can fills both hands.** While the player carries the can at `full`, `/pet`, `/take` and `/use` refuse with `carrying.watering_can`. The exceptions are `/use watering can` and `/use` on an exit. `/go`, `/look`, `/drop`, `/inventory`, `/stats`, `/help` and craving reactions still work. The block lifts as soon as watering takes it to `partly_full`, or the can is dropped.
5. **Dropping keeps the level.** A dropped full can stays full. The slosh in its `drop` line is flavor only.
6. **The 24-hour idle drop.** If the can is in a player's inventory and they run no command for 24 hours, move it to their current location's Also here list at its current level, and post `exhausted.public` there, in the room's thread or the channel. It's the ladder's rule. **`exhausted.public` is the default for every idle drop:** a thing with its own key (`<thing_id>.exhausted.public`, like the ladder's) uses that, and anything else uses the default, with `{name}` filled in.
7. ***Green Thumb.*** Its watering step counts only a Courtyard watering that pours water: from `default`, `full` or `partly_full`. Filling the can, or tipping an empty one, doesn't count.
8. **The trash can.** The watering can is one-of-a-kind under the trash can's rule, so taking out the trash puts it back in the house at the level it was.
9. **Raise the latest playable drop to 30.** The engine's cap on the highest drop that can be reached must be at least 30, or `/advance-game` and `/qa-drop` stop short of this drop. A prior drop progression hit this bug, so every drop's work order carries this step.

## Logging

One `interaction_log` row per event below.

- **Fills:** the level before.
- **Waterings:** the level before and after, including an empty can's tip.
- **Takes and drops,** with the level.
- **Carrying refusals:** what the player tried to do with a full can.
- **Idle drops:** where the can was left and its level.

## Acceptance tests

Run on a QA server at drop 30. First check that `/qa-drop` and `/advance-game` both reach 30.

**Levels**

- The can is in the Courtyard's Also here list. `/look watering can` shows the rainwater line.
- `/use watering can` in the Courtyard gives the rainwater line. The can is now empty, and `/look` says so.
- Using the empty can in the Courtyard gives the one-drop line, and the can stays empty.
- Carry it to the Kitchen. `/use watering can` fills it, and a second use there gives the already-full line.
- In the Courtyard, the full can waters and goes to partly full, then waters again and goes to empty.
- In any other room, the can's level doesn't change: the nothing-to-water line, or "It's empty."
- A can standing in the Also here list can be filled and used without being taken.
- Each level's `take` and `drop` lines show to the room.

**Hands full**

- With a full can, `/pet`, `/take ladder` and `/use cat food` get the carrying line. `/go`, `/look`, `/use front door` and `/drop watering can` work.
- A full can, dropped and picked up again, is still full.
- After one watering (partly full), `/pet` and `/take` work again.

**Elsewhere**

- A tester holding the can who goes quiet for 24 hours (shortened on QA) drops it where they stand, at its level, and the room sees the line.
- A Courtyard watering counts toward *Green Thumb*. A fill, or an empty tip, doesn't.
- Thrown in the trash and taken out to the curb, the can reappears in a container somewhere, at the same level.

## Not in this work order

- **Filling with `/use kitchen sink`.** It could also fill a can the player is holding, as a convenience, but it isn't part of this design.
