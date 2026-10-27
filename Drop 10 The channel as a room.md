# The channel as a room

*Work order, updated 27 October. Everything here is settled, and the content file changes are already in the creative content folder. The channel (`CH`) is a place a player can be, like any room. Once inside the house, a player's body is in one room at a time, and the game enforces that.*

## Where a player is

- **Every player has exactly one location:** the channel, or one room of the house. Before drop 10 everyone is in the channel.
- **Moving between the road and the house is ordinary movement.** From the road, `/go house` or `/use front door`. From the Entryway, `/go road` or `/use front door`. `/enter` is retired.
- **The front door takes a player back out to the channel.** It's an ordinary exit, so `/go front door` and `/use front door` both work.
- **Leaving is always allowed, even before the cat is fed.** The feeding gate on the Entryway's other exits is there to stop players from being overwhelmed. Stepping back outside can't overwhelm anyone.
- **This also gives `/go` a job at drop 10.** Before, every Entryway exit led to rooms that open at drop 30. Now the front door is a working exit from day one.

## Commands in the wrong place

A player's **place** is the channel if they're in the channel, or their room's thread if they're in the house. These commands only work in the player's place:

| Command | Anywhere else |
| --- | --- |
| `/look`, `/use`, `/take`, `/drop`, `/go` | private message, `wrong_place.default` |
| `/pet` | private message, `wrong_place.pet` |

**These stay global:** `/stats`, `/inventory`, `/help`, and craving reactions. They don't involve the player's body.

**"Anywhere else" covers both cases.** A player in the kitchen who types `/look` in the channel gets the message. So does a player who has somehow ended up in a thread for a room they're not in. In both cases `{thread}` links to the player's actual place: their room's thread, or the channel if they're outside.

| Key | Text | Status |
| --- | --- | --- |
| `wrong_place.default` | Your spirit may be here, but your corporeal self is in {thread}. Try this action again there. | approved |
| `wrong_place.pet` | Your spirit may be here, but your hand, along with the rest of your corporeal self, is in {thread}. Try petting there. | approved |

**Why `/pet` is blocked too:** the cat is always in the player's room, but the player's hand is wherever their body is. The petting line says so, so it doesn't read as a bug.

**One trade-off to know about:** the bed and the toys are in the channel. A player in the house has to walk back out to fluff the bed or pick up a new toy. Toys they're already carrying still work anywhere.

## Thread membership follows location

Each room is a private thread with invites turned off, so players can't add each other. The bot keeps every room thread's membership equal to the players whose location is that room.

**Adding: by @mention, confirmed 26 October.** On the test server, the bot adding a player by @mentioning them in the thread worked, and Discord didn't post its "added to the thread" notice. This replaces adding players separately.

| When | The bot |
| --- | --- |
| A player moved from road to entryway | posts the arrival line in the Entryway thread; its @mention adds them |
| A player moves from room A to room B | posts the arrival line in B, whose @mention adds them, then removes them from A |
| A player leaves through the front door | removes them from the Entryway thread |
| Someone joins a thread they don't belong in | removes them straight away |
| On a schedule | runs a sweep: in every room thread, removes members whose location is a different room or the channel |

- **Two layers on purpose.** The bot is notified when someone joins a thread, so most mistakes get fixed straight away. The recurring sweep is the backup, for anything the bot missed while restarting or rate-limited. Suggested every 60 minutes, as a config value (`thread_sweep_minutes`) so it can be tuned without a deploy.
- **The sweep skips the bot itself and staff.** Admins and anyone with permission to manage threads can see every private thread whatever the bot does. Trying to remove them would fail and repeat every sweep.
- **The Secret Library follows the same rule.** Only players whose location is the library are in its thread, so discovery stays per player.
- **The main channel can't be enforced this way.** Nobody can be removed from it, so there the wrong-place messages are the only enforcement. That's fine, because the channel is only ever a place to stand.
- **Removal notices, tested 27 October.** Discord posts a notice when the bot removes a player from a thread, and none when a player leaves on their own. The notice can't be avoided, and it's accepted as noise.

## The front door, revised

**`things.tsv`:** `front_door` becomes an exit rather than a fixture. Keep its id, so its text rows still apply, and set `type = exit` and `destination_room_id = CH`. Add `outside|out|road` to its aliases. It is **not** gated on `fed_the_cat`.

| Key | Since | Text |
| --- | --- | --- |
| `front_door.look` | 10 | A heavy front door with a brass handle and three separate locks, every one of them undone. |
| `front_door.look` | 20 | A heavy front door with a brass handle and three separate locks, every one of them undone. A brass intercom panel is set into the wall beside it. |
| `front_door.use` | 10 | The handle turns easily, and the door swings open onto the road and the fog. The cat is already outside, somehow, sitting by the farm stand as if she never left. |
| `front_door.move_depart` | 10 | {player} lets themselves out through the front door. |
| `front_door.move_arrive` | 10 | {player} steps out of the house and back onto the road. |
| `front_door.take_fail` | 10 | It's a door. It's staying on its hinges. *(unchanged)* |

- **Both move lines are for leaving the house.** `move_depart` posts in the Entryway thread as the player goes out, and `move_arrive` posts in the channel as they reach the road. The other direction uses the `house` exit's lines, below.
- **The drop 10 look leaves out the intercom,** which arrives at drop 20. The drop 20 row adds it back. That fixes the intercom leak the Entryway fragmentation tab flagged.
- **The old use line is retired.** "It declines" described a door that wouldn't open, and this one does.

## The way in: a house across the road

Going in is ordinary movement too, so `/enter` is retired, along with its three lines: enter.public, enter.returning and enter.arrived. The road gets an exit of its own.

**`things.tsv`:** a new exit row, `house`, with `type = exit`, `room_id = CH`, `destination_room_id = EN` and `since_drop = 10`. Its aliases are `house|haunted house|front door|door|inside|in`, so `/go house` and `/use front door` both work from the road. It isn't gated on anything. On the Entryway side, `front_door`'s aliases already include `road`, so `/go road` works there.

**`room_text.tsv`:** players need to see the house in the road's description to find it. Fragment 60 already hints at it: *Across the road the fog obscures something tall and unlit, too square to be trees.* A drop 10 row for the same fragment reveals it, with no `visible_when`, so everyone sees it:

| Room / state / since | Fragment | Text |
| --- | --- | --- |
| `CH / default / 10` | 60 | Across the road the fog has thinned around a tall, unlit **house**. |

| Key | Since | Text |
| --- | --- | --- |
| `house.look` | 10 | A tall, square house across the road, dark in every window. The front door is shut. The cat takes a step toward it and glances back at you expectantly. |
| `house.use` | 10 | You cross the road to the house. The front door opens at a touch, the cat slips in ahead of you, and it closes behind you both. |
| `house.move_depart` | 10 | {player} crosses the road and disappears into the house. |
| `house.move_arrive` | 10 | The front door opens, and {player} comes in from the road. |
| `house.take_fail` | 10 | It's a whole house. It isn't coming with you. |

**What each trip shows**

| Trip | Private, to the player | Public, where they leave | Public, where they arrive |
| --- | --- | --- | --- |
| Road to Entryway (`/go house` or `/use front door`) | `house.use` | `house.move_depart`, in the channel | `house.move_arrive`, in the Entryway thread |
| Entryway to road (`/go road` or `/use front door`) | `front_door.use` | `front_door.move_depart`, in the Entryway thread | `front_door.move_arrive`, in the channel |

`house.move_depart` reads the same on a first visit and a return trip, so the return-visit variants drafted here earlier aren't needed.

**`#welcome` is retired.** Decided 27 October: the hint rail teaches the way in instead, with one new hint.

| Key | Fires | Text |
| --- | --- | --- |
| `hint.go_house` | The first time a player uses `/look house`, at drop 10 or later, if they have earned *Fluffed to Perfection* | Try /go house or /go front door. |

- **`/go front door` works from the road** because `front door` is one of the `house` exit's aliases there.
- **Once per player**, recorded in the hints table like every other hint.
- **The bed condition is *Fluffed to Perfection*,** which any successful fluff earns. A refused fluff doesn't count.
- **No "Hint:" in the text.** Every other hint in `defaults.tsv` is written without a prefix, so this one matches. If the rail shows "Hint:", the engine adds it.

**The pointer into the thread** is the arrival line itself. See Moving, below.

## Moving: messages and their order

This applies to every move, including between the road and the Entryway. A player moves from A to B:

1. **Private reply:** the exit's `use` line, as an ephemeral reply to the player.
2. **In A**, the channel or A's thread: the exit's `move_depart` line, or `move.depart` when it has none.
3. **In B:** the exit's `move_arrive` line, or `move.arrive`, with `{player}` rendered as an @mention. **That message is what adds the player to B's thread.** The mention also notifies them, so it's their link into the room as well. There's no separate add and no separate "head to" line.
4. **Remove the player from A's thread.** Skip this step when A is the channel.

- **`{player}` is an @mention only in arrival lines.** Everywhere else it stays a plain name, so nobody is pinged by other players' comings and goings.
- **A player who left their own room's thread** can no longer see it. On their next command, re-add them with a bare @mention in that thread before replying. The sweep doesn't do this, because an hourly mention would be noise.

## On deploy

- **Every player without a valid location is set to the channel.** A valid location is `CH`, or a room that has arrived on that server. On the beta server, that's everyone.
- **Run the sweep once at startup**, so any stray thread members from older builds are cleared.

## Achievements

***A Little Bit Lost* is now drop 10.** It's for entering the same room five times in five minutes. The road counts as a room, so going in and out of the house counts as entering. Its trigger has to count arrivals in `CH` as well as in house rooms.

## Logging

Each of these is a row in `interaction_log`:

| Event | `action` | `outcome` | `detail` |
| --- | --- | --- | --- |
| A command refused for being in the wrong place | `wrong_place` | `refused` | the command, where it was issued, and the player's actual location |
| A move, including road to house and back | `move` | `success` | from and to |
| The bot removes someone from a thread | `thread_removed` | `success` | the thread, and why: a move, a join event, or the sweep |

`actor` is the player for the first two and the system for the third. `relationship_delta` stays empty for all three.

**Config:** `thread_sweep_minutes = 60` in the config history, so it can be tuned without a deploy.

## Content files: already in the folder

These changes were made on 27 October to the files in **creative content**:

- **`things.tsv`:** `front_door` is now an exit to `CH`, with `outside|out|road` added to its aliases. There's a new `house` exit row from `CH` to `EN`, at drop 10, `sort_order` 160.
- **`thing_text.tsv`:**
  - `front_door`'s drop 10 row has the short look with no intercom, plus the new use and move lines.
  - A new drop 20 row adds the intercom to the look. It repeats every other cell of the drop 10 row, so it reads correctly whether a newer row replaces the older one entirely or cell by cell.
  - There's a new `house` row.
- **`room_text.tsv`:** a drop 10 row for `CH` fragment 60, with no `visible_when`.
- **`defaults.tsv`:** `wrong_place.default`, `wrong_place.pet` and `hint.go_house`. The hint is written like the others, with no "Hint:" prefix and a full stop at the end.
- **`achievements.tsv`:** `a_little_bit_lost` at drop 10, with a note.
- **Left in place on purpose:** `enter.public`, `enter.returning`, `enter.arrived` and `#welcome`. Delete them in the same change that removes `/enter`, so the live code never looks up a key that's gone.

## Code changes

1. **Location:** `CH` is a valid location and the default one, and the deploy step sets everyone else.
2. **Retire `/enter`:** remove the command and its four keys.
3. **Exits between `CH` and `EN`** go through the normal `/go` and `/use` paths. `CH` has an exit for the first time.
4. **The location check** on `/look`, `/use`, `/take`, `/drop`, `/go` and `/pet`. A refused command gets an ephemeral `wrong_place.*` reply, where `{thread}` links to the player's room thread or to the channel.
5. **The move sequence above**, with the arrival line as the @mention.
6. **Thread events:** when someone joins a thread for a room they're not in, remove them straight away. When a player has left their own room's thread, re-add them on their next command.
7. **The sweep:** every `thread_sweep_minutes`, and once at startup. It skips the bot and anyone who can manage threads.
8. **`hint.go_house`:** fires the first time a player uses `/look house`, at drop 10 or later, if they have *Fluffed to Perfection*.
9. ***A Little Bit Lost*** counts arrivals in `CH`.
10. **Fragment resolution:** for each room and fragment, the row with the highest arrived `since_drop` wins. `CH` fragment 60 is the first content that depends on this, and the Entryway fragments will too. Without it, both fragment 60 lines show at drop 10.
11. **The logging above.**

## Acceptance tests

Run on a QA server, using `/qa-drop`.

**Before drop 10**

- `/go house` on the road gets the standard refusal for an exit that doesn't exist.
- The road's `/look` shows no house. Players who have looked at the bed see the old fragment 60 line.

**At drop 10: the road and the hint**

- The road's `/look` shows *Across the road the fog has thinned around a tall, unlit house.* to everyone, and the old fragment 60 line to no one.
- `/look house` works. The first time, a player with *Fluffed to Perfection* gets `hint.go_house`. A player without it gets no hint, and a second `/look house` gets no hint either.

**Going in and coming out**

- **Going in:** `/go house`, `/go front door` and `/use front door` each work from the road. Each shows `house.use` privately, posts `house.move_depart` in the channel, and posts `house.move_arrive` in the Entryway thread with the player @mentioned. The player is then a member of the thread, and Discord shows no "added to the thread" notice.
- **Coming out:** `/go road`, `/go front door` and `/use front door` each work from the Entryway. Each shows `front_door.use` privately, posts `move_depart` in the thread and `move_arrive` in the channel, and removes the player from the Entryway thread. Discord's removal notice is expected.
- Leaving works before the cat has been fed.
- The front door's look has no intercom at drop 10 and has it at drop 20.

**Commands in the wrong place**

- A player in the Entryway runs `/look`, `/use`, `/take`, `/drop`, `/go` and `/pet` in the channel. Each gets an ephemeral reply. `/pet` gets `wrong_place.pet` and the rest get `wrong_place.default`. The link opens the Entryway thread.
- A player on the road runs `/look` in the Entryway thread before the bot has removed them. The reply links to the channel.
- `/stats`, `/inventory` and `/help` work anywhere. A craving reaction in the channel works while the player is in the house.

**Thread membership**

- Add a player by hand to a thread for a room they're not in. The bot removes them straight away.
- A player leaves their own room's thread by hand. Their next command re-adds them.
- Set `thread_sweep_minutes` low. Stray members are removed, and an admin and the bot never are.

**Deploy, achievements and logging**

- A player with no location, or with a room that hasn't arrived, ends up on the road after deploy.
- Going in and out of the house five times in five minutes earns *A Little Bit Lost*.
- `wrong_place`, `move` and `thread_removed` rows appear in `interaction_log`.
