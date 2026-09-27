# Functional Spec

Command behavior for Release 1. Written after the content, and describing it.

## Scope

This specifies what each command does in Release 1: how a name resolves to a thing, what each verb changes, and what the reply says. It is what Phase 2c builds against.

**It describes the content files; it does not command them.** That inversion is deliberate and worth stating plainly, because it is the reverse of the usual order. The nine rooms, 135 things and 142 text rows already exist and have been checked against each other. Where this document and the files disagree, the files are right and this document is wrong — the exception being the four places below that name a gap the files cannot express.

The column reference, the object model and the state model live in the **Content Schema**. This document does not repeat them; it says what the engine does with them.

Out of scope: achievement triggers (their own spec, 34 conditions, owned by QA as much as by engineering), anything in Release 2 or later, and the balance pass.

**Two columns exist in `things.tsv` but are unused in Release 1.** `requires` is populated on nothing, and `cross_weight` carries 0, 1 or 5 but nothing reads it — it is for the cat carrying things between dimensions, which is a later release. Build neither. A developer who finds them and infers behavior will invent a mechanic nobody asked for.

## The command list

Slash commands register once and propagate for about an hour, so this list is settled here and changed as rarely as possible. Ten commands, seven for players and three for admins.

| Command | Who | Change |
| --- | --- | --- |
| `/pet` | Player | unchanged |
| `/stats` | Player | gains the craving tally |
| `/look [thing]` | Player | rewritten — see below |
| `/inventory` | Player | reads the new tables |
| `/take <thing>` | Player | **new** |
| `/drop <thing>` | Player | **new** |
| `/use <thing>` | Player | extended beyond exits |
| `/enter-entryway` | Player | no longer assigns a cohort |
| `/initialize-haunted-house` | Admin | builds 9 threads, not 18 |
| `/admin_config <key> <value>` | Admin | **new** |

Gone: `/add-thing` and `/add-room-desc`. Both are testing tools made obsolete by the loader, and both write content into the database, which is now the content files' job alone. Remove them in the same registration as the additions.

**Movement stays on `/use`.** `/use back door` walks you to the Courtyard because an exit is a thing you use, and the resolution rules below apply to exits exactly as they do to everything else. There is no `/go`.

`/admin_config` is the home for per-server numbers: `planks_required` first, whatever follows after. It must be usable mid-game — a server that set the staircase at ten planks and drew four players needs the number lowered, not the release abandoned. Lowering it below the planks already placed completes the staircase immediately rather than leaving it stuck.

## Resolution

Every command that names a thing runs the same two passes: **which thing**, then **which copy**. This is the single most reused piece of logic in the bot; build it once.

Matching is on `name` or any pipe-separated entry in `aliases`, case-insensitive, punctuation stripped. Aliases are unique within a room — the content files are checked for this — so a name never matches two unrelated things in reach.

**The scope depends on the verb, and it is set before pass one runs.** A command can only act on things it could act on, so the candidate set is narrowed first and both passes then work inside it. Widening this later is the easiest way to reintroduce the bug below.

| Command | Candidate set |
| --- | --- |
| `/take` | the room only: loose objects there, anything inside a container there, and the sources there. **Not the inventory.** |
| `/drop` | the inventory only. |
| `/use`, `/look` | everything in reach: inventory first, then the room. |

The bug this prevents: a player carrying a can of chicken, standing beside the salmon cupboard, types `/take cat food`. With the inventory in scope, pass one sees two distinct things and asks "chicken or salmon?" — and if they answer chicken, there is no chicken in the room to take. The question was never answerable. Scoped to the room there is one candidate, and the salmon can goes in the bag. `/drop` has the same fault mirrored: carrying chicken beside the salmon cupboard, `/drop cat food` must not offer salmon.

When `/take` finds nothing in the room but the name matches something the player is carrying, the refusal is `take_fail.already_carried` ("You're already carrying the {name}") rather than `take_fail.absent`, which would be a lie. The `/drop` equivalent, `drop_fail.not_carried`, already exists.

**Pass one: which thing.**

Collect every distinct thing the name matches **within that verb's candidate set**. If more than one distinct thing matches, reply with `ambiguous.match` listing them and stop. Nothing is acted on until the player names one.

Only things in reach are offered. A flavor that exists only upstairs is never part of the question.

**A source and the object it yields count as one thing.** The chicken stash under the sofa and a can of chicken cat food in the bag are the same thing in two places. Without this rule a player carrying a can and standing by the stash is asked "chicken or chicken?" every time.

**Pass two: which copy.** With one thing agreed, walk down and stop at the first hit:

1. The player's inventory — skipped when the verb's scope excludes it, which for `/take` it does.
2. Loose objects in the room, including anything inside a container there.
3. Sources in the room.
4. Nothing in reach. If the name matches a thing that exists anywhere in the game, reply *"You don't see a {name} here."* Otherwise the generic unknown-noun reply.

Several copies of the same thing never prompt — that is what pass one settled. For `/use` and `/look`, a can in the bag and another on the floor is one thing in two places and step 1 takes the carried one; for `/take` the bag was never in scope, so the same situation resolves to the one on the floor.

**Step 4 never says where.** Confirming a thing exists somewhere is fine; naming its room gives away the Secret Library and the drawer before anyone has found them.

The reply always says which copy it acted on. That is also what makes `look_carried` fire.

## `/look`

Private reply. Three shapes.

**`/look` with no argument** prints the room's `look` for the player's current state, then the `Also here:` line.

The listing holds **loose objects in the room only**: takeable things with a finite quantity, sitting in `room_contents`, not inside a container. Sources never appear — they are inexhaustible and must be named in room prose or in the text of the thing that holds them, which the content files guarantee. Things inside a container do not appear either; they show when the container is looked at.

Entries use `also_here.prefix`, `also_here.separator`, and `also_here.entry_multiple` for a count above one — `herbs x10`. Omit the line entirely when nothing is loose. Four of the nine rooms are in that state at launch, which is correct: everything portable there is tucked inside something.

**`/look <thing>`** prints that thing's `look` for its current state. If the thing is in the player's inventory and has `look_carried`, that is printed instead — it exists for the six things whose description assumed where they were sitting.

**`/look <container>`** prints the container's own `look`, then the same listing for the loose objects inside it. **Sources are not listed, exactly as in a room.** One rule everywhere: no listing anywhere names a source. A source is found by reading the prose that holds it — the container's `look` for a contained source, the room's `look` for a free-standing one — and that prose is required to name it: the container's `look` **or** its `use`, enforced by a loader check (see the Phase 2b work order). The `use` alternative exists for the hollowed-out book in the Living Room bookshelves, where the whole point is that the chocolate is found by rummaging rather than by looking. Contained *objects* are still listed, which is how the gourmet can stays findable under the bed without the bed's prose giving it away.

**A bare name always works.** `/look present` finds the present inside the stocking inside the family room. Never build an `in <container>` parser — it is a syntax players have to guess, and discovery is already preserved by what the listing shows rather than by what the player has to type.

## `/take`

Resolution is scoped to the room, never the inventory (see Resolution). Resolve, then branch on what was resolved.

**A source** hands over the object named in its `yields`, and is not itself consumed. The reply uses **the yielded object's** `take` text, not the source's — the source has none. `yields` sits on 15 rows, and all 15 are `type = source`: the six cat food stashes, the copper wire coil, the carving tool sets, the pile of costumes, the graphite tin, the herb garden, the candy bowl, and — added 26 September — the row of baby bottles, the hollowed-out book and the ring of iron keys. Between them they hand out twelve distinct objects. The herb garden and the candy bowl were fixtures with a `yields` cell until 26 September; they behaved as sources in every respect, so the column was corrected rather than the behavior. Key the implementation on `yields`, not on `type` — in particular the rule that **a source and its yield count as one thing** during resolution, which is the only reason `/take candy` and `/take herbs` do not raise a spurious ambiguity prompt.

**A finite object** decrements `room_contents` and increments `player_inventory`. When the count reaches zero it leaves the room — and the `Also here:` line — entirely. This is what lets one player take the only copy.

**`max_per_player`** is checked before either. Three things set it, all to 1: the gourmet can, the skeleton key and the carving tools. Over the cap, the thing's own `take_fail` fires — all three have one written, and they read as refusals rather than errors ("You've already found yours").

**The used baby bottle is deliberately uncapped.** Eight are scattered through the house every day, so *Catproof the House* is earnable by everyone without a cap doing that work — the restock schedule is what spreads them, not a limit. Capping it would only penalize a player who collected diligently. Do not add one.

Refusals, in order of checking:

| Situation | Reply |
| --- | --- |
| `takeable = no` | the thing's `take_fail`, else `take_fail.fixture` |
| an exit | `take_fail.exit` |
| already at `max_per_player` | the thing's `take_fail` |
| resolution found nothing in reach | `take_fail.absent` |
| nothing in the room, but the name matches something carried | take\_fail.already\_carried |

A blank `take` cell falls through to `take.default`. Most things have no `take` text — 22 of 142 rows fill it — and that is the intended shape: the house default carries the ordinary case and a writer overrides where it matters.

## `/drop`

Resolution is scoped to the inventory, never the room. A player carrying chicken beside the salmon cupboard who types `/drop cat food` is dropping chicken, and is not asked.

Decrement `player_inventory`, increment `room_contents` for the player's current room. The thing appears in that room's `Also here:` line for everyone.

A dropped thing lands loose in the room, never inside a container: `/drop` writes `container_id` empty. Dropping the spice jar in the Entryway does not put it back in the Amazon box.

| Situation | Reply |
| --- | --- |
| not carrying it | `drop_fail.not_carried` |
| `droppable = no` | the thing's `drop_fail`, else `drop_fail.undroppable` |

`droppable = no` is set on two things, the carving tools and the skeleton key, and both have a `drop_fail` of their own written — "You'll want them when you get to the pumpkins" and "You go to set it down and find that you'd rather not." The flag is what refuses; the written line is what the refusal says, so a thing wants both. Blank `drop` falls through to `drop.default`.

One consequence worth stating: a source-fed object dropped in a room where no stash exists is a real object in a real place. Cans of chicken can end up in the Nursery. That is intended — it is how the house accumulates evidence of other players.

## `/use`

The widest verb. Resolve first, then take the first branch that applies.

**An exit.** Move the player: add them to the destination thread, post "exits via …" in the room they left, remove them from it. `destination_room_id` is the graph; it is populated on all 20 exits. Some exits are gated by state — the curiosity cabinet reads differently with `has_key` and again with `passage_open` — so the resolved text depends on the player's states, and a `use_fail` on the default state is what refuses a locked exit.

**A thing with `transforms_to`.** One row uses this: a used baby bottle, with `transform_room = KI`. Using it in the Kitchen removes one used bottle from the player's inventory and adds one sanitized bottle. Outside the Kitchen, the thing's `use_fail` fires ("It needs a sink and hot water, and there's neither of those here"). The transform is one-way.

**A thing with `use_cooldown_hours`.** One row: lumber, at 48. Record the use in `thing_uses`. If the player used it within the window, reply with its `use_fail`, which carries `{time}`. Nothing else in Release 1 has a cooldown, but build it off the column rather than special-casing lumber.

**Anything else** prints its `use` text. 138 of 142 rows have one. A blank falls through to `use.default`.

### Two uses that change the world

**Lumber, and the staircase.** Each `/use lumber` by a distinct player counts one plank. The target is `planks_required` from `server_config`. The reply carries `{n}` and `{total}`. When the count of distinct players reaches the target, set `stairs_repaired` **server-wide**: the Entryway and Upstairs Hallway descriptions swap to their `stairs_repaired` rows and the staircase exits open for everyone. Lumber also carries `present_when = !stairs_repaired`, so it disappears once the job is done — note the `!` negation, which the loader must support.

**Graphite, and the drawer.** `/use graphite` in the Upstairs Hallway sets `drawer_unjammed` for **that player only**, permanently. The roll-top desk's text switches to its `drawer_unjammed` row and the expired cat food source, gated by `present_when = drawer_unjammed`, becomes visible to them. Used anywhere else, graphite prints its ordinary `use` text and changes nothing.

These two are the model for every state change: the content files carry the text per state and the visibility gate, and the rule that sets the state lives here. Do not add a `sets_state` column.

## `/inventory` and `/stats`

Both private.

`/inventory` lists what the player carries, grouped by thing and counted, using the same `x{n}` form as the room listing. Under types and counts this is a direct read of `player_inventory` rather than a grouping of instance rows.

`/stats` shows **your own stats only**. It takes no arguments in Release 1. Looking up another member is a later release, and is called out below because it costs a command re-registration.

It holds four things:

- the pet count
- the relationship score with Eunoia
- **the craving tally**: the number of distinct days on which you reacted with the correct emoji. **Not the number of days you were first.** A player who adds the emoji after someone else has already found it still scores the day — the game is collaborative, and the tally counts taking part rather than winning a race
- **the achievements you have earned**, each as its name and the line explaining how you got it

**The achievement list reuses the unlock description**, the same private text sent when the achievement fired. It is not a second piece of writing, and the writers owe one description per achievement, not two. Only earned achievements appear; an unearned one is absent rather than greyed out, which is what keeps the secret ones secret.

**This message will outgrow 2,000 characters, and that is the part to design for.** Thirty-four achievements at a name plus a sentence each is well past the plain-message cap before the other three stats are added. Build `/stats` as an **embed** from the start: the counts as fields, the achievements as lines in the embed description, which allows 4,096 characters. If a player somehow exceeds that, continue into a second private follow-up rather than truncating — a player who has earned something and cannot see it will report it as a bug, correctly.

**Registering `/stats` with no options has a cost later.** Adding the optional member argument in a future release needs a re-sync, with the usual hour of propagation and stale signatures in between. That is acceptable — that release will be changing commands anyway — but it should be a known cost rather than a surprise. Do not register the option now and reject it with "coming soon"; an argument that exists and refuses is worse than one that does not exist.

## Alexa and the daily craving

Neither is a slash command. Both are event handlers, which is why the command list above stays at ten.

### Alexa

An `on_message` handler, scoped to game threads, ignoring bots. A message beginning `alexa`, `hey alexa` or `ok alexa` — lowercased, punctuation stripped — gets the smart speaker's `use` text.

If it also contains one of *remind / reminder / remember* **and** one of *delivery / subscription / subscribe / order*, Alexa answers that she will remind David to cancel the auto-delivery, and the player earns "Passing a Message to David".

*remind* is a prefix of *reminder*, so a substring test on the first group needs only *remind* and *remember*. Test both groups against the lowercased, punctuation-stripped message and require no particular order — "alexa remember to cancel the order" and "alexa the delivery, remind him" both pass, which is the point. **Costco is deliberately not a trigger word.** The standing order is no longer described as a Costco subscription anywhere in the content (Costco does not offer auto-delivery), so a player reading the to-do list has no reason to type it. David's Costco membership survives everywhere else — it is still where the mountain of cat food came from.

This needs the Message Content intent, which is already enabled. It changes what the bot receives, not what it stores; no message content is persisted.

### The daily craving

One food emoji per day, **the same for every player on a server**, so the guessing is collaborative. Drawn from the Unicode Food & Drink group minus its dishware subgroup — around 120 options. Dishware (🍽🥢🧂 and the rest) is in the group but is not food, and a plate as the cat's craving of the day is a strange day. It stays a legal guess and simply never earns a 👀, since it can never be the answer's subgroup. Custom server emoji are excluded, and variation selectors are normalized before comparing or some guesses silently will not match.

Players guess by reacting to any message the bot posted. The bot answers with reactions on that same message:

| Bot reaction | Means |
| --- | --- |
| 👀 | the guess is in the right Unicode food subgroup |
| ❌ | 19 slots are used with no correct guess; this is the 20th |
| 😻 | the craving has been found |

The ❌ exists because Discord caps a message at 20 distinct reactions. Without it a correct guess in the last slot would leave the bot no room to answer.

Three implementation notes that are each a day lost if missed. Use `on_raw_reaction_add`, not `on_reaction_add` — the latter only fires for messages still in the bot's cache, so guesses on anything posted before the last restart do nothing. Check whether **the bot itself** is among a reaction's users rather than whether the emoji is present, because a player can add any of the three by hand and Discord merges identical emoji into one reaction with a count. And **there is no private confirmation available**: a reaction carries no interaction token and ephemeral messages require one. The 😻 is the confirmation, public by design.

**Crediting the tally.** Every player whose reaction matches the craving scores that day, once, whether they were first or twentieth. `on_raw_reaction_add` fires per user even when the emoji is already on the message and Discord is only incrementing its count, so a latecomer clicking the existing reaction is seen; and because it is the same emoji, it costs none of the 20 distinct-reaction slots. Store a last-credited date per player and compare before incrementing, so a player who removes and re-adds the reaction, or reacts correctly on a second bot message the same day, is counted once.

One intended consequence: once the 😻 is up, the answer is visible to everyone who looks, so a late reaction is copying rather than solving. That is not a gap to close. The tally measures showing up, not solving, and the day's satisfaction is shared. Do not add a cutoff, a first-N-only rule, or any other guard against copying: the whole point of one craving per server is that players can tell each other. If a later release ever wants a measure of solving, it needs a separate counter, not a narrowing of this one.

## States

Six states exist in the content files. Scope is the thing to get right: a server-wide state changes the house for everyone, a per-player state changes it for one person, and they are stored in different tables.

| State | Scope | Set by |
| --- | --- | --- |
| `stairs_repaired` | server | the `planks_required`-th distinct player to `/use lumber` |
| `has_key` | player | holding the skeleton key |
| `passage_open` | player | using the curiosity cabinet while holding the key |
| `library_found` | player | climbing the oak and entering through the window |
| `drawer_unjammed` | player | `/use graphite` in the Upstairs Hallway |
| `default` | — | the absence of any of the above |

The split is a design decision, not an accident. The staircase is collective labor and its reward is access, so it lands for everyone at once. The library and the drawer are discoveries, and the discovery is the content — making them server-wide would mean only the first player ever experiences them.

**Releases and drops are different things, and only drops reach the runtime.** A **release** is a deployment: code and content files shipped together, numbered for the repository's benefit. A **drop** is a moment when something becomes visible to players. One release can carry the content for a dozen drops that arrive over the following weeks, which is the point — the engineer ships once and the house keeps changing. Nothing in the database records a release number, and no admin advances one.

`drops.tsv` is the calendar: `drop_id`, `trigger`, `date`, `event`, `name`, `notes`. At launch there is one row, `1 / date / launch`, and every content row carries `since_drop = 1`.

**Three triggers.** `date` arrives when its date is at or before today, Pacific — the same moment on every server, nothing stored. `event` arrives when a named condition first becomes true on that server. `manual` arrives only when an admin fires it, which is how a drop gets held back, or tested early.

**An arrival is permanent, and event arrivals are recorded.** A `date` drop needs no record: the date answers the question every time it is asked. An `event` or `manual` drop does — write a row to a per-guild `server_drops` table the first time it fires and read arrival from that table afterwards, never by re-evaluating the condition. A condition can stop being true (a counter falls back below a threshold, a thing is taken out of a room) and content must not vanish from a house it has already changed.

**Event names come from a registry in code, not free text in the file.** The loader validates `event` against the known list and refuses to start on an unknown name, exactly as it does for `present_when`. Release 1 ships zero event drops; the column exists so the second one needs no migration.

**Ordering.** Among arrived drops the highest `drop_id` wins. With event drops a server can have drop 5 arrived while drop 4 has not, so number drops in the order their content should supersede, and write each drop's text to read correctly without the drops below it. Two drops touching the same entity is the case to check twice.

### Restocks

A seventh content file, `restocks.tsv`, puts things into the house on a repeating schedule. It covers two placements: **into a named container**, and **scattered at random**. Three rows in Release 1 — four spice jars into the Amazon box every third day from day 2; eight used baby bottles a day, scattered; and two dirty diapers a day, scattered.

`restock_id`, `thing_id`, `placement`, `container`, `amount`, `times_per_day`, `first_day`, `every_n_days`, `window_start`, `window_end`, `config_key`, `since_drop`, `notes`.

**`times_per_day` and `amount` are different things.** The spice is one occurrence placing four jars; the bottles are eight separate occurrences placing one each, so they arrive at eight different moments rather than in a heap. Draw a separate random time for every occurrence.

**`placement = random` picks uniformly from every room and every container.** Nine rooms and twelve containers, so 21 slots at equal probability. A thing placed in a container is found by looking in it, the same as anything else contained — though not by the same mechanism.

**There are two kinds of "in a container", and the scheduler needs the second one.** `contained_in` is a content column on the thing type: it says this thing *always* lives in that container, in every server, for every copy — the gourmet can under the bed, the chocolate in the hollow book. It cannot say where one scattered bottle happens to be, because the next one lands somewhere else. That is `container_id`, a column on `room_contents` holding the per-copy location, empty for a thing loose in the room. The scheduler writes it, `/look <container>` reads both, and the `Also here:` line excludes both. Phase 2b adds the column; nothing reads it until 2c.

Two consequences of that, accepted rather than overlooked. The Secret Library is in the pool, so some bottles land where only players who have found it can reach them — which gives the room a second reason to exist. And the roll-top desk is in the pool as a container, which is fine: the desk is visible to everyone, only the jammed drawer's source is gated.

**`config_key`, where set, names a `server_config` key an admin can change mid-game.** `bottles_per_day` starts at 8. A change takes effect from the next day rather than retroactively — do not try to add or remove things already placed. The diapers have no key today; adding one is a single cell if the rate needs tuning.

**Scatter volume is the thing to watch in playtest.** Ten new objects a day across 21 slots is roughly 70 loose things a week, and they accumulate, because nothing removes them until a player takes one or the cat sends one away. The `Also here:` line in a busy room will reach the 2,000-character cap sooner than the Limits section assumed, so truncation-with-a-count is no longer a precaution: build it in 2c.

**Day numbers are per server, counted from that server's own day 1** — the Pacific date on which `/initialize-haunted-house` ran. Not from the launch date, and not from a global calendar. A server that starts three weeks late should find one spice jar delivery waiting, not seven; and every server should see the same shape of month regardless of when it joined. This is the opposite of how drops work, and deliberately so: a drop is a story beat that happens to everyone at once, a restock is a supply rhythm local to a house.

**The time within the day is random per server per occurrence,** drawn uniformly between `window_start` and `window_end`. Pick it when the day begins and store it; do not re-roll on each check, or a restock can be skipped or doubled depending on when someone happens to look.

**Stock accumulates and is never reset.** Day 2 adds four. Day 5 adds four more to whatever is left, so a room that nobody has visited holds eight. This is an increment, never an assignment — the difference matters the first time a player is holding a jar when the next delivery lands.

**It increments the container's contents, not a global count.** The jars go into `amazon_box` in the Entryway, and `/look amazon box` shows them like any other contained objects. Nothing is per-player.

**Missed windows still fire.** If the bot is down across a restock time, apply it at the next opportunity rather than skipping it. Track the last applied occurrence per server in `server_restocks` and catch up on start-up; a player should never be able to tell that the bot was asleep.

One consequence to accept: on day 1 the Amazon box is empty, so *Something's Cooking* cannot be completed until day 2 at the earliest. That is intended — it staggers the achievement rather than letting the first player through the Entryway take the only jar in the house.

Text resolves by `(entity, state, since_drop)`: the row matching the player's state, at the highest **arrived** `since_drop`, falling back to `default`. A row whose drop has not arrived is invisible — it is in the files, loaded, and simply not yet reachable. `present_when` is a different axis: it gates existence by *state* rather than by date, and supports negation, `!stairs_repaired` on lumber being the only use today. A per-player discovery such as `drawer_unjammed` or `library_found` is a state, never a drop; drops are the same for everyone on a server.

## Replies

**Private:** `/look`, `/inventory`, `/stats`. Looking around should not spam a shared thread, and a private reply is also what keeps one player's `drawer_unjammed` view from confusing everyone else in the room.

**Public in the room thread:** `/take`, `/drop`, movement via `/use`, and the two event interactions. The rooms are shared, so the room's state has to be legible to the people standing in it — if someone takes the last of something, the others need to see it happen rather than discover it later.

**`/use` on a thing** should be private in all but one case. Most `use` text is a small private moment ("you take one deliberate breath, which is a mistake"), and making every use public would bury the thread. The single exception should be a plank placed in the staircase, which should post publicly as well as privately, because it is a collaborative effort across many players.

### Limits

- A Discord message caps at **2,000 characters**. The longest room description plus a full `Also here:` line is well inside that, but a room where many things have been dropped is not bounded by anything today. Truncate the listing with a count rather than letting the send fail.
- A message caps at **20 distinct reactions**, which the craving game is built around.
- Ephemeral replies require an interaction. Reactions and plain messages have none.

### Templating

Tokens the engine substitutes: `{name}` the thing's name, `{room}`, `{n}` and `{total}` for the lumber counter, `{options}` for the ambiguity list, and `{time}` for a remaining cooldown. `{time}` is new with the lumber cooldown and needs adding to the Content Schema's Templating section.

## Open questions

Three things a developer will hit that this document does not settle.

**What are the drop dates, and who sets them?** Half of this is now settled: releases and drops are separate, and the runtime keys on drops and the calendar rather than on a release number nobody maintains (see States). What is left is the calendar itself. `drops.tsv` has one row, `launch`; every later drop needs a date before its content can be written. A `server_config` override, or a manual drop, can force one early for testing, while the calendar stays the source of truth for dated ones. Needed before the second drop's content is written, not before 2c ships. Event-driven drops are wanted and the schema now carries them; what nobody has written yet is the list of conditions the registry will offer.

**The craving's narrowing signal — settled for launch.** At \~130 options with no information, an honest player is guessing 1-in-130 and the daily loop will not sustain. For launch, 👀 means the right Unicode **subgroup** rather than the whole Food & Drink group: food-fruit, food-vegetable, food-prepared, food-asian, food-marine, food-sweet and drink. Dishware is excluded from the pool the craving is drawn from. Those run from roughly a dozen to thirty each, so a 👀 turns a 1-in-130 guess into something a room full of people closes out in a few tries. Build the grouping as a lookup the loader reads, not a hard-coded table — a writer may replace it before launch with smaller hand-made groups, and that should be a content change rather than a code change. Optional, and good enough for launch either way.

**Achievement triggers are a separate spec** and 2d waits on it. Nine of the 34 still have no name. It is independent of everything here, so it can be written in parallel with 2c.
