# Phase 2e — Secret Library discovery

## What 2e is

The Secret Library exists in the content and is reachable by two routes, and right now neither is gated. `/use cabinet` in the Living Room and `/use tree` in the Courtyard both work for anybody who types them. 2e makes the two routes discoveries rather than doorways: a player finds the library by climbing the oak, and only afterwards can open the cabinet.

**It is a small phase.** The writers have already written every line it needs, the rooms already exist, and the state mechanism already ships. What is missing is the wiring and one genuinely new behavior in `/look`.

### What 2e is not

**It is not per-player room visibility.** Every room is a private thread the bot adds a player to on entry and removes them from on exit — the Entryway included, and that has worked since v1. The Secret Library is no different mechanically, and nothing in this phase changes how threads are managed. A player who has not discovered the library is simply never added to its thread, for the same reason they are not in the Bedroom while standing in the Kitchen.

### Prerequisites, all met

- `rooms_unlocked` and the room plumbing — 2a
- The content loader, `present_when` and text resolution by `(entity, state, since_drop)` — 2b, frozen
- `/use` on exits, `/look`, and thread add/remove on movement — 2c, shipped
- Per-player state written off a `/use` branch — 2c.5, shipped. `drawer_unjammed` is the precedent this phase copies three times

## The one new capability

**Two players standing in the same room must be able to see different exits.** Everything else in Release 1 renders a room identically for everyone who is in it. This is the first place where `/look` has to consult the acting player's state before deciding what to print.

It is narrower than it sounds, because the room's prose does not change — only the exit list does. The Courtyard reads the same for everybody, oak tree and all:

> An old, gnarled oak leans against the house, one thick branch reaching toward a small window half hidden in the ivy.

What differs is whether the exit list underneath offers the oak as a way out. For a player who has not climbed it, the Courtyard has one exit, the back door. For a player who has, it has two.

The same applies in the Living Room to the curiosity cabinet, and in the Secret Library to the cabinet on the way back out. Three rooms, four exits, one rule.

## Three states, and only two of them are stored

| State | Scope | Set by | Stored? |
| --- | --- | --- | --- |
| `library_found` | per player | the first successful `/use` of `CS`, the oak | **yes** |
| `has_key` | per player | holding a `skeleton_key` | **no — derive it** |
| `passage_open` | per player | `/use` of `LS` while `has_key` | **yes** |

**`has_key` is a read of the inventory, not a flag.** `skeleton_key` is `droppable = no`, `cross_weight = 0` and `max_per_player = 1`, so once a player takes one it can never leave them: it cannot be dropped, the cat cannot send it to Dimension B, and they cannot acquire a second. A stored flag would be a second copy of a fact that cannot change, and the two could drift. Derive it.

**`library_found` and `passage_open` are both irreversible and both per player.** Nothing takes them away, so they need no more than a row per player per state, exactly as `drawer_unjammed` works today.

One consequence worth naming: `passage_open` being per player means the cabinet stands ajar for the player who opened it and closed for everyone else, including someone in the room at the time. That is the price of keeping the library secret from players who have not found it, and it is the right trade, but it is a small fiction cost and it is listed in the open questions below.

## The two routes, and the order they have to happen in

**The oak is the only way in the first time, and that is structural rather than a rule to enforce.** The keys hang on a nail on the library shelves — `key_nail`, `contained_in` `library_shelves`, which is in the Secret Library. A player cannot take a key until they are already inside, and the only way inside without a key is the tree. So `library_found` always precedes `has_key`, and `has_key` always precedes `passage_open`, with no ordering check written anywhere.

The sequence:

1. **`/use tree` in the Courtyard.** Works for anybody, discovered or not. Moves the player to the Secret Library and sets `library_found`. Also fires *Out on a Limb*, which is why that achievement needs no state of its own.
2. **`/take key` in the library.** One per player, and it can never leave them. From this moment `has_key` reads true.
3. **`/use cabinet` in the Living Room.** Refused until `has_key`; on success it sets `passage_open` and moves the player through.
4. **After that**, both routes are open to that player in both directions: the oak and the window, the cabinet and the back of the cabinet.

**Nobody can be stranded.** `SC`, the window back down the oak, is ungated in both content and code. A player who climbs in and never finds the keys can always climb back out.

## The trap: usable before visible

**Do not gate `CS` with `present_when`.** `present_when` controls whether a thing exists for a player, and the oak has to be usable by a player who has not discovered it — otherwise `library_found` can never be set and the library can never be found by anyone. An exit gated on the state its own use produces is a locked door with the key inside.

So the two questions are separate, and 2e is the first place they come apart:

|  | Can the player `/use` it? | Does `/look` list it? |
| --- | --- | --- |
| `CS`, the oak | always | only with `library_found` |
| `SC`, the window | always | always — they are inside |
| `LS`, the cabinet | always; refused by `use_fail` without `has_key` | always — the cabinet is in the room's prose |
| `SL`, back of the cabinet | always; refused without `passage_open` | always — they are inside |

Only one cell in that table is new behavior. The other three are the existing rule that an exit is listed and a `use_fail` does the refusing.

**Listing an exit must never name its destination room.** The exit list shows the exit's own name — "curiosity cabinet", "back door" — not where it leads. If it printed destinations, the Living Room would announce the Secret Library to every player who typed `/look`, and the cabinet's locked glass doors would stop being a mystery. Check this holds before building anything else in this phase; it may already be true, in which case say so and move on.

## The content is already written

Nothing here needs a writer. Every state row this phase resolves against is in `thing_text.tsv` today:

| Entity | State | What is written |
| --- | --- | --- |
| `CS` | default | the full discovery: hauling up into the oak, noticing the window behind the ivy |
| `CS` | `library_found` | the short version — "You climb the old oak and slip in through the library window." |
| `LS` | default | `use_fail`: "You tug at the glass doors. Locked. The keyhole is big and old-fashioned, the kind that takes a skeleton key." |
| `LS` | `has_key` | the reveal — the cabinet swings outward on a hidden hinge |
| `LS` | `passage_open` | both a `look` and a `use` for the cabinet standing proud of the wall |
| `SL` | default | blocked by the back of the cabinet, keyhole on this side too |
| `SL` | `passage_open` | pushing it aside back into the Living Room |
| `SC` | default | the only state it needs |

Two things follow from reading those rows. The `LS` `has_key` row is the one that **sets** `passage_open` — it describes the hinge giving way, and it is written to be read once. And `LS` has no `look` row for the default state because the cabinet is already described in the Living Room's own prose, locked glass doors and all, which is what makes the `use_fail` land.

## What 2e does not do

- **No change to thread membership.** Rooms are private threads and players are added and removed on movement; that is v1 behavior and this phase leaves it alone
- **No server-wide unlock.** `SE` carries `open_at_launch = no`, which keeps it out of the initial world; discovery is per player and nothing in 2e makes the library public to a server
- **No new content.** Every line is written
- **No new column.** `present_when` is not extended and nothing is added to `things.tsv`
- No second key, no way to give a key away, no way to lose one
- No hint system. A player who never thinks to climb the tree never finds the library, and that is the design

## Definition of done

- `/look` in the Courtyard lists the oak as an exit for a player with `library_found` and does not for a player without, with both cases tested in the same room at the same time
- `/use tree` works for a player who has never used it, moves them to the Secret Library, and sets `library_found` exactly once
- The second `/use tree` prints the short `library_found` text rather than the discovery text
- *Out on a Limb* fires on the first `/use tree` and never again
- `/use cabinet` without a key prints the `use_fail` and does not move the player
- `/take key` gives exactly one key, a second attempt refuses, and the key cannot be dropped
- `/use cabinet` holding a key sets `passage_open`, moves the player, and prints the hinge text once
- After `passage_open`, both `LS` and `SL` print their `passage_open` text and move the player
- A player who climbs in and takes no key can always leave by the window
- Two players in the Living Room at the same time, one with `passage_open` and one without, each see the cabinet correctly for themselves
- No exit listing anywhere names its destination room

- Leaving by the oak or by the cabinet posts the custom departure line, and neither names a room or a route
- No public line in the Living Room or the Courtyard ever contains the words *Secret Library*, on the way out as well as the way in
- Arriving in the Living Room or the Courtyard from the library posts the custom arrival line, and the `{room}` token is never substituted into it
- `thing_text.tsv` carries `move_depart` and `move_arrive`, blank on every row but the four secret-exit ones, falling through to `defaults.tsv` when empty

## Open questions

**Settled 29 September: `passage_open` is per player for Release 1.** That keeps the library secret, but it means the cabinet stands open for its opener and shut for the player beside them. Server-wide would read better in the room and would make the Secret Library progressively public as the month goes on — which may be the better arc for a game that ends on 31 October, or may give the secret away on day three. Per player is the reversible choice, which is why it wins: widening it later is a one-line change, and narrowing it after players have seen the library standing open is not.

**Settled 29 September: `/use tree` announces, but says nothing useful.** Movement posts publicly in the room left and the room entered. A player climbing the oak would post "exits via the oak tree" to the Courtyard, which tells everyone standing there that the tree is a way out. So both secret exits get a departure line of their own, and the room learns that somebody left without learning how.

`CS`, the oak, posts to the Courtyard:

> `{player}` leaves, but you can't quite tell where they went.

`LS`, the cabinet, posts to the Living Room:

> You hear a creak and `{player}` is gone from the room. But how?

Note the token is `{player}`, lower case, the one `move.depart` and `move.arrive` already substitute. Do not mint a second spelling.

**This needs a column that does not exist yet.** `move.depart` lives in `defaults.tsv` as one string for the whole house, and these are per-exit overrides, which is `thing_text.tsv`'s job — but that file has no departure column. Add `move_depart`, blank on all 150 rows but two, falling through to `defaults.tsv` when empty, exactly as `take` and `drop` already do. It resolves by `(entity, state, since_drop)` like every other cell, so nothing new is needed in the loader. The Content Schema's column list needs the same addition.

**The way back leaks too, and it is now covered.** `move.arrive` reads *{player} arrives from the {room}*, and it names the room they came from. When somebody steps out of the cabinet into the Living Room, everyone standing there reads "arrives from the Secret Library" — which gives away more than the departure line was protecting. The same happens climbing down the oak into the Courtyard. `SL` and `SC` need arrival overrides too, or the secret survives the trip in and not the trip out. So add a matching `move_arrive` column on the same terms. Both lines were written on 29 September:

`SL`, arriving in the Living Room:

> `{player}` appears in the Living Room. Where did they come from?

`SC`, arriving in the Courtyard:

> With a small thud, `{player}` arrives in the Courtyard.

Neither names the Secret Library, and neither names the route — the cabinet and the oak both stay unmentioned, so a bystander learns only that somebody turned up. Capitalised *Living Room* to match the room's name in `rooms.tsv` and the Courtyard line beside it.

**Closed 29 September: 2e is not being cut.** Both 2e and 2f are in scope for launch, so the question of where to cut does not arise. Recording why it would have hurt, in case a later release is ever tempted: the Secret Library holds `key_nail`, `copper_wire_coil` and the scorch-mark circle, and *Out on a Limb* and *Making a Mess* both live there. Cutting 2e always cut more of the game than its size suggested.
