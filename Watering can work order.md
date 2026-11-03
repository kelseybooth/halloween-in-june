# Watering can work order (drop 30)

Nov 2, 2026 · @Qaruse

The Courtyard's watering can becomes a takeable object with four water levels: filled in the Kitchen, emptied over the herbs, and too full to carry with anything else. The design is in The watering can. It reuses two shapes from The ladder (drop 30): the hands-full rule and the idle drop, here on a 6-hour timer since the can was last used. It ships with the Drop 30 work order.

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
4. **Watering and filling are public.** Everyone in the room sees each one, in a single line with no private reply.
5. **A full can takes both hands.** The player can carry it, move, look and drop it, but can't pet, take or use anything else.
6. **A carrier who hasn't used it for 6 hours** sets it down wherever they are. The room sees a line, and the carrier is told where they left it.

## Content

**`things.tsv`, `watering_can`.** It's parked at 99 as a fixture today. Change it to an object: `room_id` CO, `quantity` 1, `takeable` yes, `droppable` yes, `max_per_player` 1, `cross_weight` 0, `since_drop` 30. Keep the aliases `watering can`, `can`, `watering`.

**The "can" alias is shared.** The gourmet cat food (`cat_food_gourmet`) also answers to `can`. A player carrying one who types `/use can` near the watering can is asked which they mean, and a carried gourmet can and a watering can in the room should both be offered. That's the engine working as intended, not a bug. Typing `watering can` or `watering` always reaches the watering can.

**`things.tsv`, new column `idle_drop_hours`.** How many hours a carried thing can go unused before it's set down. Set it to 6 for `watering_can`. Blank means no timer. The rattle uses it too (see the rattle achievements work order), and other one-of-a-kind things can later.

**`thing_text.tsv`, `watering_can`, all at drop 30.** The `state` names the can's level. `default` is the starting level. `use` stays empty on every row, because the use lines below depend on the room as well. The old `take_fail` goes.

| `state` | `look` | `take` | `drop` |
| --- | --- | --- | --- |
| `default` | A dented galvanized watering can with a long spout and an inch of rainwater in the bottom. | {player} picks up the dented watering can. Rainwater shifts around in the bottom. | {player} sets the watering can down with a hollow clank. |
| `empty` | A dented galvanized watering can with a long spout, dry inside. A rusty ring marks where the rainwater used to sit. | {player} picks up the empty watering can. It weighs almost nothing. | {player} sets the watering can down with a hollow clank. |
| `partly_full` | The dented watering can, about half full. The water sloshes when you nudge it. | {player} picks up the half-full watering can. The water inside sloshes. | {player} sets the watering can down with a hollow clank. |
| `full` | The dented watering can, filled to the brim. The water trembles at the spout whenever anything moves. | {player} heaves up the full watering can with both hands, and water slops over the rim. | {player} sets the full watering can down too fast, and water sloshes out over the rim and onto their feet. |

**`defaults.tsv`, new keys.** The four successes, a fill and three waterings, are posted to the room, and that post is the whole reply. Everything else here is private to the player.

| Key | Text |
| --- | --- |
| `watering_can.water.default` | (public) {player} tips an inch of rainwater over the herbs. |
| `watering_can.water.full` | (public) {player} gives the herbs a long, even shower. |
| `watering_can.water.partly_full` | (public) {player} waters the herbs until the can runs dry. |
| `watering_can.water.empty` | You tip the can over the herbs. One drop comes out. It needs filling first. |
| `watering_can.fill` | (public) {player} fills the watering can to the brim at the kitchen sink. |
| `watering_can.fill.already_full` | It's already full to the brim. Any more and you'd be watering the kitchen floor. |
| `watering_can.elsewhere` | You look around for something that needs watering. Nothing in here does. |
| `watering_can.elsewhere.empty` | It's empty. |
| `carrying.watering_can` | You'd need a free hand, which you don't have with this full watering can. |
| `exhausted.public` | {player} gets tired and sets the {name} down. |
| `idle_drop.public` | (public) {player} absent-mindedly sets the {name} down. |
| `idle_drop.private` | You realize you set the {name} down earlier somewhere in the {room}. |

**Room text:** none. The can is already cut from the Courtyard's description.

## Code changes

1. **A state that belongs to a thing.** The can's level is shared by every player, which no existing state is: today's states belong to a player or to the server. Store it per server for the can, start it at `default`, and resolve the can's `look`, `take` and `drop` by it. It never returns to `default`.
2. **`/use watering can` by room and level.** In the Courtyard, a can with water uses the `watering_can.water.*` line for its level and goes down one level: `default` and `partly_full` to `empty`, `full` to `partly_full`. An empty can gets `watering_can.water.empty` and stays empty. In the Kitchen, any level but full goes to `full` with `watering_can.fill`, and a full can gets `watering_can.fill.already_full`. Anywhere else, the level doesn't change: `watering_can.elsewhere`, or `watering_can.elsewhere.empty` if the can is empty. The fill and the three waterings post their line to the room's thread, with {player} filled in, and send no private reply. The other outcomes are private, because nothing changes for anyone else.
3. **Carried or in the room.** `/use watering can` works on a carried can or one in the Also here list. Using a carried can doesn't set it down, unlike the ladder.
4. **A full can fills both hands.** While the player carries the can at `full`, `/pet`, `/take` and `/use` refuse with `carrying.watering_can`. The exceptions are `/use watering can` and `/use` on an exit. `/go`, `/look`, `/drop`, `/inventory`, `/stats`, `/help` and craving reactions still work. The block lifts as soon as watering takes it to `partly_full`, or the can is dropped.
5. **Dropping keeps the level.** A dropped full can stays full. The slosh in its `drop` line is flavor only.
6. **The 6-hour idle drop.** The clock starts when a player takes the can and restarts every time they use it, filling or watering. If a player has carried it for `idle_drop_hours` (6) without using it, move it to their current location's Also here list at its current level, and post `idle_drop.public` there, in the room's thread or the channel. On that player's next command, send `idle_drop.private` once, with `{room}` as the room's name. This replaces the 24-hour no-command rule for the can, since 6 hours unused always comes first. `exhausted.public` stays as the default line for the 24-hour rule on anything else.
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
- `/use watering can` in the Courtyard posts the rainwater line to the room, with no private reply. The can is now empty, and `/look` says so.
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

- A tester who carries the can for 6 hours without using it (shortened on QA), while still running other commands, drops it where they stand, at its level. The room sees the absent-minded line, and on their next command the tester is told which room it's in. Using the can before then restarts the clock.
- A Courtyard watering counts toward *Green Thumb*. A fill, or an empty tip, doesn't.
- Thrown in the trash and taken out to the curb, the can reappears in a container somewhere, at the same level.

## Not in this work order

- **Filling with `/use kitchen sink`.** It could also fill a can the player is holding, as a convenience, but it isn't part of this design.
