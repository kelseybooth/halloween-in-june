# The ladder (drop 30)

Oct 29, 2026 · @Qaruse

There is one ladder in the game. It stands initially in the courtyard, and anyone can carry it anywhere. Climbing it shows each place from above, lets anyone break off a piece of the wasp nest over the road, as often as they like, and having it at hand while using lumber, carried or standing in the Entryway, is the only way to repair the top 20% of the grand staircase. Every climb ends with the player back on the ground.

## The ladder itself

**One ladder, starting in the courtyard at drop 30.** It's an object with `quantity = 1`, so taking it removes it from the room. Wherever it's been put down, the room's "Also here" list shows it. The courtyard's room text doesn't mention it, so the text stays true after someone carries it off.

| Field | Value |
| --- | --- |
| `thing_id` | `ladder` |
| name | ladder |
| aliases | ladder, wooden ladder, stepladder, step ladder, rungs |
| type | object |
| `room_id` | `CO` |
| quantity | 1 |
| takeable, droppable | yes, yes |
| `max_per_player` | 1 |
| since\_drop | 30 |

| Key | Text |
| --- | --- |
| `ladder.look` | A tall wooden ladder, spattered with old paint, its rungs worn pale in the middle. It's taller than you are and looks quite heavy. |
| `ladder.look_carried` | The ladder, balanced on your shoulder. It's heavy, it's awkward, and it has opinions about doorframes. |
| `ladder.take` | {player} hoists the ladder onto one shoulder, staggers, and finds the balance point. |
| `ladder.drop` | {player} sets the ladder down and leans it against the wall, with visible relief. |

## Carrying it

**While the ladder is in a player's inventory, their hands are full.** `/pet`, `/take` and `/use` all refuse, with one private line:

| Key | Text |
| --- | --- |
| `carrying.ladder` | You try, but can't figure out how while you're carrying this ladder. |

**Still allowed while carrying:**

- `/use ladder`, to climb it. Using a carried ladder works like setting it down and then using it, so afterward it's in the room's Also here list, not the player's inventory.
- `/use lumber`, for the top steps of the staircase
- `/use` on an exit, such as `/use front door`. Otherwise a player carrying the ladder could leave a room by `/go` but not by `/use`.
- `/go`, `/look`, `/drop`, `/inventory`, `/stats`, `/help` and craving reactions, since none of them needs a free hand

**Feeding is blocked too,** because it's a `/use` of the cat food. Players will have to put the ladder down to feed the cat.

## Climbing it

**`/use ladder` climbs it wherever it is,** in the player's inventory or in the room's Also here list. A carried ladder is set down first, and it stays standing in the room afterward. The line depends on the room the player is in, and every line ends back on the ground. Only the road's climb does anything: it knocks a piece of the wasp nest down into the road. The rest are for the view.

| Where | `ladder.use` |
| --- | --- |
| Courtyard (`CO`) | You plant the ladder's feet on the flattest patch of grass and climb as high as you dare. Partway up you're level with the kitchen stoop, and at the top you're still below the second floor windows. Through one you can see a sage-green nursery, with a mobile turning slowly. Through another, a bedroom with a mirror catching the light. Lower, past the low branches of the old oak, there's a half hidden smaller window, and through it what looks like a library. The ground under the oak is all roots, though, and the ladder wouldn't stand steady there. You climb back down. |
| Entryway (`EN`) | You lean the ladder against the side of the grand staircase and climb. From up here you can finally see the carvings along the outside of it: a running vine of oak leaves and acorns, with a sleeping cat tucked into every third panel. Overhead, the water stain is as close as you're going to get. It's still dry. You climb back down. |
| The road (`CH`) | You set the ladder in the road where the branches meet overhead, and climb until the scarlet leaves brush your hair. The wasp nest hangs right in front of you, gray and papery and long empty. You break off a piece about the size of your palm, and it slips out of your fingers and drifts down to the road. You climb back down. |
| Kitchen (`KI`) | You prop the ladder beside the fridge-freezer and climb until you're hunched over the top rung, head bowed under the ceiling. Up here you can see the top of the fridge, which nobody has dusted in years, and a wooden spoon that went missing a long time ago. You climb back down. |
| Dining Room (`DI`) | You set the ladder by the tall windows and climb until your head brushes the ceiling. From above, the table set for three looks like a still life, and the stain under the wine glass looks like a map. You climb back down. |
| Living Room (`LI`) | You climb the ladder beside the bookshelves, hunched under the ceiling. From up here the room is all tops of things: the dusty top of the curiosity cabinet, the back of the sofa, the soft blocks on the rug spelling out their half a word. You climb back down. |
| Anywhere else | You lean the ladder against the wall and climb until you have to hunch over the top rung to keep from hitting your head. Up close, the ceiling has a hairline crack and one abandoned cobweb, and the room below looks smaller than it did. You climb back down. |

**Anywhere else** covers the upstairs rooms at drop 40 and the Secret Library at drop 50. They can get their own lines later.

| Key | Text | Notes |
| --- | --- | --- |
| `ladder.nest.public` | {player} climbs a ladder in the middle of the road, and a scrap of the old wasp nest flutters down. | Cut 29 October: the nest climb stays private |

## The wasp nest pieces

**Each climb on the road knocks a fresh piece of the wasp nest down into the road.** The nest itself stays whole in the tree and never runs out, so it's a discovery anyone who brings the ladder outside can make. This reuses the cat bed's pattern of dropping an item when it's used:

- `/use ladder` on the road adds one piece to the road's Also here list.
- Picking it up is an ordinary `/take`. The climb has already set the ladder down, so the climber's hands are free.
- `/take wasp nest` keeps its existing refusal, which already hints that the nest is out of reach.

The climb stays private. If the cat takes the ladder instead, no piece falls.

| Field | Value |
| --- | --- |
| `thing_id` | `wasp_nest_piece` |
| name | piece of wasp nest |
| aliases | piece of wasp nest, wasp nest piece, nest piece, piece of nest, piece, scrap, nest fragment, fragment of nest, fragment of wasp nest |
| `room_id`, quantity | `CH`, 0. Each road climb adds one |
| takeable, droppable | yes, yes |
| since\_drop | 30 |

| Key | Text |
| --- | --- |
| `ladder.use`, road | You set the ladder in the road where the branches meet overhead, and climb until the scarlet leaves brush your hair. The wasp nest hangs right in front of you, gray and papery and long empty. You break off a piece about the size of your palm, and it slips out of your fingers and drifts down to the road. You climb back down. |
| `wasp_nest.take_fail` | That seems unwise. It is twenty feet up and full of whatever a wasp colony leaves behind. *(existing, unchanged)* |
| `wasp_nest_piece.look` | A palm-sized scrap of wasp nest, gray and layered like a stack of very thin paper, and lighter than it looks. |
| `wasp_nest_piece.look_carried` | The scrap of wasp nest, riding carefully in your bag so it doesn't crumble. |
| `wasp_nest_piece.take` | {player} picks up a scrap of the old wasp nest and tucks it carefully away. |
| `wasp_nest_piece.use` | You hold it up to the light. Every layer is a slightly different gray, as if the wasps couldn't agree on a color. |

The nest's own text doesn't change. The pieces are only for collecting, and they count toward *Strength in Numbers* and *Making a Mess*. Untaken pieces stay in the road for anyone to pick up.

## The cat takes the ladder

**On 10% of `/**`**`u`****`s`****`e`****`  ladder `** ** the cat climbs it instead.** This replaces that room's climb line, so a road climb that rolls the cat drops no nest piece.

1. The player gets the cat line, and the room gets the public line.
2. The ladder stays standing in the room, as after any climb. If the player was carrying it, it's out of their inventory.
3. For the next 5 minutes, nobody can take or climb it. Anyone who tries gets the swat lines below. This lock is per ladder, not per player.
4. After 5 minutes the ladder is free again, silently.

The swats are play, with claws tucked in, and nobody gets hurt. They earn no relationship points either way.

| Key | Text |
| --- | --- |
| `ladder.use`, cat | You're two rungs up when the cat goes past you as if you were standing still. By the time you look up, she's on the very top, and she reaches down and bats at the top of your head, claws politely tucked in. You climb back down and let go. The ladder is hers now, at least for a while. |
| `ladder.cat.public` | {player} starts up the ladder, and the cat gets to the top first. |
| `ladder.take_fail`, guarded | You reach for the ladder, and a black paw shoots down from the top rung and swats your hand. She isn't finished with it. |
| `ladder.use_fail`, guarded | You put a foot on the bottom rung. From the top, the cat leans down and swats you smartly on the head. Not yet. |

**A carrier who goes quiet.** If a player has the ladder in their inventory and runs no command for 24 hours, the ladder leaves their inventory and stands in their current location's Also here list. The line below posts there, in the room's thread or the channel.

| Key | Text |
| --- | --- |
| `ladder.exhausted.public` | {player} drops the heavy wooden ladder out of exhaustion. |

## The top steps of the staircase

**Planks 73 to 90 need the ladder.** That's the last 20% of the default 90. In general, the ladder planks start at 80% of `staircase_planks`, rounded down, plus one. When the 72nd plank goes in, the server state `stairs_upper` is set. From then on, `/use lumber` works only when the ladder is at hand: in the player's inventory or in the Entryway's Also here list. A carried ladder is set down in the Entryway when the plank goes in. The once-a-day limit still applies.

**Expect a pause.** The staircase repair starts at drop 20, but the ladder arrives with the courtyard at drop 30. At about 27 planks a day, the server reaches plank 72 in under three days. After that, the repair waits for drop 30, and the no-ladder line works as a tease.

**One ladder means passing it around.** Each player lays at most one plank a day, so the last 18 planks take many players. Once the ladder is in the Entryway it stays there after every plank, so players can repair back to back without anyone carrying it. It only needs fetching if someone takes it somewhere else.

| Key | Text |
| --- | --- |
| `lumber.use`, `stairs_upper`, with ladder | You lean the ladder against the staircase, climb with a plank under one arm, and hammer it into one of the top steps. You climb back down. {n} of {total} repairs done. |
| `lumber.use_fail`, `stairs_upper`, no ladder (approved: one line for drops 20 and 30) | The steps you can reach from the floor are all done. The top ones are too high to fix without something to stand on. |
| `EH.look`, `stairs_upper` | The grand staircase, mended most of the way up in fresh, pale wood. The top few steps are still missing. {n} of {total} repairs done. |
| `EH.use_fail`, `stairs_upper` | You get most of the way up before the steps run out. The top few are still missing. You head back down. |
| Entryway fragment 7, `stairs_upper` | The grand staircase is mended most of the way up, but the top steps are still missing, with fresh lumber stacked beside its base. |

## Engine work for the developer

Most of this fits existing patterns. These parts are new:

| Need | Suggested shape |
| --- | --- |
| A use line per room | `thing_text` rows for `ladder` whose state names the room, such as `in:CO`, `in:EN`, `in:CH`, with `default` for anywhere else. The engine picks the row for the player's current room |
| Hands full while carrying | When `ladder` is in the inventory, refuse `/pet`, `/take` and `/use` with `carrying.ladder`, except `/use ladder`, `/use lumber` and `/use` on an exit. Any successful /use ladder, or a top-step plank, also moves a carried ladder out of the inventory and into the room |
| A requirement that depends on a state | In `stairs_upper`, `lumber` requires `ladder` in the inventory`  or in the room. Today requires is one value per thing, not per state, and only a non-takeable thing in the room meets it, so a takeable ladder standing in the room needs to count too ` |
| A server state set by a count | `stairs_upper` at plank 72, the same way `stairs_repaired` is set at plank 90 |
| A chance event on use | 10% of `/use ladder` rolls the cat instead of the climb |
| A timed lock on one thing | 5 minutes in which the ladder answers with its guarded `take_fail` and `use_fail` lines |
| An item dropped by one room's climb, and an idle timer | `/use ladder on the road drops a wasp_nest_piece into the road's Also here list, like the cat bed's yield. Climbs in other rooms drop nothing`. Separately, a carrier with no command for 24 hours sets the ladder down where they are, and ladder.exhausted.public posts |

## Open questions

- [ ] **A carrier who goes quiet.** Using the ladder always sets it down, so this only happens if a player picks it up and stops playing without using it. That would stall the last 18 planks for everyone. Suggested: if the carrier runs no command for 24 hours, the ladder goes back to the Entryway, beside the lumber, with a short line for the next person to look.\
Response: If the carrier goes quiet with no commands for 24 hours, post a message in their channel that "{player} drops the heavy wooden ladder out of exhaustion." It should go to the "also here:" text in their current location.
- [ ] **The pause at plank 72.** The repair will likely sit there until drop 30 opens the courtyard. Is that the pacing you want, or should the ladder arrive earlier? Response: this is the right pacing.
- [ ] **The road's public line.** Use `ladder.nest.public`, or keep the nest climb private?\
Response: Keep the nest climb private
- [ ] **A use for the nest pieces.** They're collectible only, for now. Is there a later quest in mind, or are they for *Strength in Numbers* and *Making a Mess*?\
Response: Only for Strength in Numbers and Making a Mess
