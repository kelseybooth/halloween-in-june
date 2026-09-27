# Phase 2c — The commands

## What 2c is

2b made the house loadable. 2c makes it playable: the verbs a player types, the two uses that change the world, the restock scheduler 2b deliberately left unbuilt, and two event handlers that are not commands at all.

The behavior is already written down. **The Functional Spec is the contract; this document is the order of work and the traps.** Where the two disagree the Functional Spec wins, except where this one names something the spec does not cover — flagged each time.

### Prerequisites, and two that are not met

Phase 2b is complete and frozen. `container_id`, `relationship_at_pet` and `use_count` are all in `database.py`. `defaults.tsv` is at 23 rows, seven of them new for this phase.

**Two content rows will stop the loader starting.** 2b's source-prose check requires every source to be named — by its `name`, one of its `aliases`, or the name of the thing it `yields` — in the prose that reveals it. Two sources fail against the files as they stand:

| Source | Where | Why it fails |
| --- | --- | --- |
| `chip_case` | Kitchen pantry | The pantry's `look` describes the cat food towers and stops. None of *chips*, *tortilla chips*, *nachos* or *chip case* appears. |
| `key_nail` | Secret Library shelves | The shelves' `look` gives occult references, David's thrillers and a pinned diagram. None of *keys*, *key ring*, *iron keys* or *nail* appears. |

The pantry's cat food passes, on the alias *cat food*. These two are writer fixes rather than developer fixes, and they are the first thing 2c is blocked on — the keys especially, since they are a route into the Secret Library.

One more is cosmetic rather than blocking: the Amazon box's text ends *"The jar inside is the interesting part,"* which is false on day 1. The box is empty until the first spice restock lands on day 2.

## Build the resolver once

Every command that names a thing runs the same two passes. It is the most reused logic in the bot and the easiest thing to get subtly wrong, so build it as one function taking the verb as an argument, not as four similar blocks inside four handlers.

**The candidate set is chosen before pass one runs, and it depends on the verb.**

| Verb | Sees |
| --- | --- |
| `/take` | the room only — loose objects, anything inside a container there, and the sources there |
| `/drop` | the inventory only |
| `/use`, `/look` | inventory first, then the room |

This is not a detail. Widening `/take` to include the inventory produces a question the player cannot answer: carrying chicken, standing at the salmon cupboard, `/take cat food` asks "chicken or salmon?" and then cannot act on either answer. The Functional Spec works the example through; what matters in the code is that scope is an argument, not an afterthought.

Two more rules exist only to stop spurious prompts. **A source and the object it yields are one thing** during pass one — the chicken stash under the sofa and a can of chicken in the bag are the same thing in two places. And **several copies of one thing never prompt**; pass two picks. Get either wrong and the bot asks "chicken or chicken?" every time.

## The four commands

The Functional Spec has the behavior verb by verb and this does not repeat it. What follows is what is new and where the work sits.

**`/look`** keeps its name and loses its old body. Three shapes: bare, a thing, a container. The listing rules are the fiddly part — loose objects only, no sources anywhere, contained things shown when the container is looked at rather than in the room. `look_carried` replaces a thing's `look` while it is in the bag, which six things rely on.

**`/take`** is new. It branches on what resolved: a source hands over its `yields` and is not itself consumed, a finite object moves from `room_contents` to `player_inventory`, and `max_per_player` is checked before either. The reply uses the **yielded object's** `take` text, never the source's — sources have none written.

**`/drop`** is new and is the mirror image: scoped to the inventory, and the thing lands loose in the room with `container_id` empty. Dropping a spice jar in the Entryway does not put it back in the Amazon box.

**`/use`** extends past exits into four branches, taken in order: an exit moves the player, `transforms_to` swaps one thing for another in place, `use_cooldown_hours` gates on `thing_uses`, and anything else prints its `use` text. **Every successful use increments `use_count`** on the same `thing_uses` row the cooldown reads — 2b added that column, so check whether it also wired the increment before adding a second one.

Movement becomes visible: `move.depart` posts in the room being left, `move.arrive` in the destination. Both strings are new.

## The eighth content file

The craving needs a lookup the loader reads. The Functional Spec explicitly refuses a hard-coded table — a writer may replace the grouping before launch with smaller hand-made groups, and that has to be a content change rather than a code change. Nothing in the seven files holds it, so 2c adds the eighth.

**`emoji_groups.tsv`** — `emoji`, `subgroup`, `drawable`.

One row per Unicode Food & Drink emoji. `subgroup` is the Unicode subgroup: `food-fruit`, `food-vegetable`, `food-prepared`, `food-asian`, `food-marine`, `food-sweet`, `drink`, `dishware`. `drawable` is `no` on the dishware rows and `yes` on everything else.

Splitting the pool from the grouping is what makes the spec's dishware rule fall out for free instead of needing a special case. The daily craving is drawn only from `drawable = yes`, so a plate is never the answer — but a player who reacts with 🍽 still resolves to a known subgroup and simply never matches, which is exactly what the spec describes. Without `drawable` the code would need an exclusion list, and a writer's replacement grouping would have to remember to carry it.

Validate it alongside the other seven: every `emoji` unique once variation selectors are normalized, every `subgroup` non-empty, at least one row `drawable`. **Normalize on load, not on compare** — normalizing at compare time lets the file and the reaction disagree invisibly.

## The restock scheduler

2b built the data and left the job: `restocks.tsv` loads, `server_restocks` exists and is empty, `container_id` is on `room_contents`. 2c makes it run. The rules live in the Phase 2b work order under *The scheduler, which lands in 2c* and in the Functional Spec's Restocks section — the short version, so this document stands on its own:

- **Day numbers count from that server's own initialization date**, Pacific. The opposite of drops, deliberately.
- **`times_per_day` is not `amount`.** Eight bottles a day is eight occurrences of one bottle at eight independently drawn times, not one drop of eight.
- **Draw the time when the day begins and store it.** Re-rolling on each check skips or doubles.
- **Stock is incremented, never assigned.**
- **A window missed while the bot was down fires at the next opportunity**, caught up on start-up.
- **`placement = random` draws uniformly from 21 slots** — nine rooms and twelve containers — re-rolled every occurrence. A container slot writes `container_id`.

Three rows exist today. Test the container path and the random path separately, test a faked one-day cycle, and test catch-up by moving a server's initialization date backwards.

### Truncation ships with it, not after it

Ten scattered objects a day and nothing removing them until a player takes one comes to roughly seventy loose things a week. A busy room's `Also here:` line reaches Discord's 2,000-character cap inside the first fortnight, so `also_here.truncated` is not a precaution for later — it ships in the same phase as the thing that causes it. Cut the listing and append the count of what was left out.

## Alexa and the daily craving

Neither is a slash command. Both are event handlers, which is why the command list below still comes to ten.

**Alexa** is an `on_message` handler scoped to game threads, ignoring bots. A message beginning *alexa*, *hey alexa* or *ok alexa* gets the smart speaker's `use` text. If it also contains one of *remind / remember* and one of *delivery / subscription / subscribe / order*, she answers that she will remind David, and the player earns *Passing a Message to David*. This needs the Message Content intent, which is already on. It changes what the bot receives, not what it stores; no message content is persisted.

**The craving** is one emoji a day, the same for every player on a server, guessed by reacting to anything the bot posted. Three implementation notes, each a day lost if missed:

1. **`on_raw_reaction_add`, not `on_reaction_add`.** The latter fires only for messages still in the bot's cache, so guesses on anything posted before the last restart do nothing at all.
2. **Check whether the bot itself is among a reaction's users**, not whether the emoji is present. A player can add 👀 or 😻 by hand, and Discord merges identical emoji into one reaction with a count.
3. **There is no private confirmation available.** A reaction carries no interaction token and ephemeral replies need one. The 😻 is the confirmation, public by design.

The tally is **recorded in 2c and displayed in 2d**. Every player whose reaction matches scores that day once, whether first or twentieth, so store a last-credited date per player and compare before incrementing.

## The new strings

`defaults.tsv` gained seven rows for this phase. The text is in the file; this is the map from key to the moment it fires, which is the part the file cannot tell you.

| Key | Fires when |
| --- | --- |
| `also_here.truncated` | the room listing is cut for length; carries `{more}` |
| `unknown.noun` | resolution step 4, and the name matches nothing anywhere in the game |
| `contents.prefix` | heading the listing inside `/look <container>` |
| `move.depart` | in the room a player leaves; carries `{player}` and `{name}` |
| `move.arrive` | in the room they enter; carries `{player}` and `{room}` |
| `inventory.prefix` | heading `/inventory` |
| `inventory.empty` | `/inventory` with nothing carried |

**Two new tokens**, both now in the Content Schema: `{more}`, the count omitted from a truncated listing, and `{player}`, the member a public movement line is about. `{n}` already carries two meanings — one entry's count in `also_here.entry_multiple`, planks placed in the lumber reply — which is why the truncation line does not use it.

An empty container prints no listing at all, the same as an empty room. There is no "it's empty" string and there should not be one.

## One command re-registration

Registering slash commands costs about an hour of propagation and leaves stale signatures in the meantime, so 2c does it once, at the end, with every change batched together.

**Added:** `/take <thing>`, `/drop <thing>`, `/admin_config <key> <value>`. **Removed:** `/add-thing` and `/add-room-desc` — testing tools the loader made obsolete in 2b, held back precisely so they could go in this batch. **Unchanged in signature:** `/pet`, `/stats`, `/look [thing]`, `/inventory`, `/use <thing>`, `/enter-entryway`, `/initialize-haunted-house`.

That comes to ten: seven for players, three for admins.

`/admin_config` is the one 2b built the table for and deliberately did not register. It starts with `planks_required` and `bottles_per_day`, and it has to work mid-game — a server that set the staircase at ten planks and drew four players needs the number lowered, not the release abandoned. Lowering it below the planks already placed completes the staircase immediately rather than leaving it stuck.

Register `/stats` with no options. Adding the optional member argument later costs another re-sync; that is a known cost, not a surprise, and the alternative — registering an argument now that refuses with "coming soon" — is worse than not having it.

## What 2c does not do

**`/stats` stays exactly as it is.** It keeps working and gains nothing. The craving tally is recorded from the day 2c ships, but the four-part display in the Functional Spec — pet count, relationship, tally, achievements — waits for 2d, because three quarters of it is not worth building twice. It becomes an embed in 2d, once.

**No achievements.** Not the triggers, not the public announcements, not the private descriptions. `relationship_at_pet` and `use_count` are written from now on so 2d has history to read, and that is the whole of 2c's involvement.

**No events beyond the staircase.** Placing a plank is the only public event interaction in Release 1. The doorbell, the ghost of the day, the bedsheet and the spirit board belong to later releases and have no spec yet.

**No cat transport.** `cross_weight` carries 0, 1 or 5 on every row and nothing reads it — it is for the cat moving things between dimensions, a later release. Same for `requires`, which is populated on nothing. A developer who finds either column and infers behavior from it will invent a mechanic nobody asked for.

**No release announcements, and no admin command to advance anything.** The runtime keys on drops and the calendar; 2b settled that and nothing here reopens it.

## Definition of done

- The two failing source-prose rows are fixed and the loader starts clean against the content files
- One resolver serves all four verbs and takes the scope as an argument, with a test for the carrying-chicken-at-the-salmon-cupboard case on both `/take` and `/drop`
- `/take` and `/drop` move things correctly between `room_contents`, `player_inventory` and containers, `container_id` written on the way in and cleared on the way out
- `/take` respects `max_per_player` and prints the thing's own `take_fail` rather than a generic one
- `/use` covers all four branches, and every successful use increments `use_count` exactly once
- `/look` works in all three shapes, with sources absent from every listing
- Movement posts publicly in both the room left and the room entered
- `emoji_groups.tsv` loads and validates as an eighth content file
- The restock scheduler runs, with the container path, the random path, a faked one-day cycle and catch-up each tested separately
- `Also here:` truncates with a count rather than failing to send
- Alexa answers, and the craving accepts reactions, narrows by subgroup, and credits every matching player once per day
- The command list is ten, registered in one sync, with `/add-thing` and `/add-room-desc` gone
- Every one of the seven new default strings is reachable by a path a test can trigger

## Open questions

Carried in rather than raised here. None of them blocks 2c shipping.

**The drop calendar.** `drops.tsv` has one row. Every later drop needs a date before its content can be written, and nobody has yet written the list of conditions the event registry will offer. Needed before the second drop's content, not before 2c.

**The relationship meter's range and neutral point.** Undefined anywhere. `/stats` only prints the number, so 2c does not care — but *Making Friends* and *Trying to Make Friends* are unbuildable until someone reads the range off the existing code. That is 2d's first blocker, and worth settling before 2d starts rather than during it.

**Smaller craving groups.** The Unicode subgroups run from roughly a dozen to thirty emoji each, which is good enough for launch. A writer may replace them with hand-made groups beforehand; `emoji_groups.tsv` is what keeps that a content change.

**Nine achievements still have no name.** 2d's problem, and independent of everything here.
