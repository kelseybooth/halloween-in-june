# Achievement Trigger Spec

Release 1. What fires each of the 35 achievements, when it is checked, and what has to be stored for the check to be possible.

## Scope

Thirty-five achievements: 14 public, 3 group, 18 secret. For each one this document gives the **trigger** (the condition), the **hook** (when it is evaluated), the **scope** (player or server), and the **state** the check needs. It is what Phase 2d builds against. **All thirty-five names are final and approved as of 27 September** — the Story Bible is the source of the names, and nothing in it is a placeholder any more.

It does not restate what a command does — that is the **Functional Spec** — or why an achievement exists — that is the **Story Bible**. Where this document and the content files disagree about what exists, the files are right, and eleven such disagreements are called out below rather than papered over.

**Read the Blocked and scarce sections before scheduling 2d.** Writing this out surfaced that six achievements cannot be earned at all with the code and content as they stand, and four more can be earned by exactly one player per server, ever. Those are content and sequencing problems, not trigger problems, and they are cheaper to fix now than after launch.

## How a trigger works

**An achievement registers against one hook, or several where the fiction needs it.** Do not re-evaluate 35 conditions after every action; dispatch only the achievements listening on the hook that just fired. Most listen on exactly one. *Green Thumb* listens on two — `on_use` for the watering can and the pumpkin, `on_take` for the herbs — because there are three ways to notice that date and all of them should count. Build the dispatcher so that registering one achievement against several hooks is ordinary rather than a special case, and so that one action can fire more than one achievement. The hooks are:

**Refined 28 September: Green Thumb's `on_take` is scoped to the source, not the object.** It fires on taking herbs **from `herb_garden`**, not on picking up a `herbs` object that somebody dropped in the Entryway — that is scavenging, not gardening. This has a consequence for the hook's signature: `on_take` must carry **the source the take resolved against**, not only the `thing_id`, because the Functional Spec has a source and its yield count as one thing during resolution and both paths hand the player an identical `herbs`. Pass the resolved source id (null when the take came from the floor) and let the predicate require `herb_garden`. Nothing else in Release 1 needs it, but it is a field on the hook rather than a special case in one achievement.

| Hook | Fires |
| --- | --- |
| `on_take` | after a successful `/take` |
| `on_drop` | after a successful `/drop` |
| `on_use` | after a successful `/use` on a thing |
| `on_move` | after movement via `/use` on an exit |
| `on_pet` | after `/pet` |
| `on_reaction` | in the craving reaction handler |
| `on_message` | in the Alexa message handler |
| `on_midnight` | the existing daily job |
| `on_cross` | when the cat sends a thing to Dimension B — post-launch |

**A trigger is code, not content.** Resist a `trigger` column in a TSV. The conditions below are not expressible in one cell — they involve counts, time windows, sets and cross-table joins — and a half-expressive mini-language is worse than a function per achievement. The content files carry the achievement's *name* and its *unlock text*; the condition lives in the codebase next to the hook it listens on.

**Scope is player or server.** A player achievement is earned by one person; a group achievement is earned by the server and belongs to nobody. They live in different tables and only one of them announces a name.

**Awarding is idempotent, and only a first award announces.** `player_achievements` takes a unique key on `(guild_id, user_id, achievement_id)` and awards are `INSERT ... ON CONFLICT DO NOTHING`. Announce only when the insert actually created a row. Without this, every re-check of a standing condition — *Cat's Best Friend* is true forever once true — reposts the announcement on every `/pet` for the rest of October.

**A trigger checks, it never mutates.** The hook runs after the command has already committed its own change. An achievement check that writes game state is a bug: it makes the same action behave differently depending on whether the player had already earned something.

## Public achievements (14)

All scope **player** unless noted. "State needed" names anything the check cannot get from the tables the loader already builds.

| Achievement | Trigger | Hook | State needed |
| --- | --- | --- | --- |
| **Passing a Message to David** | Message matches the Alexa wake prefix, and contains one of *remind / reminder / remember* and one of *delivery / subscription / subscribe / order* | `on_message` | none |
| **Charcuterie Board** | Player's inventory contains all five of `cat_food_chicken`, `cat_food_salmon`, `cat_food_tuna`, `cat_food_gourmet`, `cat_food_expired` at the same time | `on_take` | none — but see the note below |
| **Found the Specs** | Player `/use`s `reading_glasses` | `on_use` | none |
| **Something's Cooking** | Player `/use`s the stove in the Kitchen while carrying `herbs`, `dark_chocolate` and `spice_jar` | `on_use` | none — **fixed 26 Sept.** From 28 Sept the `requires` gate on `/use` proves the ingredients, so the predicate is just a successful `on_use` of the stove |
| **Unsticking the Situation** | `graphite_powder` crosses to B from this player's drop | `on_cross` | a record of who dropped the thing that crossed. **Blocked — post-launch** |
| **Catproof the House** | Player's inventory holds five baby bottles at once — `used_baby_bottle` and `sanitized_baby_bottle` counted together | `on_take` | none — a direct read of `player_inventory`. **Redefined 27 Sept — see below** |
| **Return to Sender** | Five bottles sent to B by this player | `on_cross` | a `sends` log. **Blocked — post-launch** |
| **It Takes a Village** — bonus | Five `sanitized_baby_bottle` sent to B by this player | `on_cross` | the same `sends` log, with the thing id. **Blocked — post-launch** |
| **Gourd Job** | Player `/use`s the pumpkins in the Courtyard while carrying `carving_tools` | `on_use` | none |
| **Follow Your Nose** | `drawer_unjammed` is set for this player | `on_use` | none — fires in the same handler that sets the state |
| **Baby Talk** | Player `/use`s `baby_monitor` | `on_use` | none |
| **Dressed for the Season** | Player `/use`s `costume` | `on_use` | none — needs the content to read as wearing it |
| **Met the Craving** | Player's reaction matches the day's craving emoji | `on_reaction` | the craving tally already specified in the Functional Spec |
| **Forwarding Address** | Player picks the correct address from the `/use letter` picker | `on_use` | the letter, the address list and the picker. **Blocked — not built** |

**On Charcuterie Board — settled 27 September: hold all five at once.** The trigger is a direct read of `player_inventory` on `on_take`, needing no new state. It is fragile in a known way — a player who drops a can to make room, or gives one away, loses the set — and that is accepted, because every flavor comes from a source that cannot run out, so the set can always be rebuilt. The alternative, "has ever held each of the five", would have cost a `player_thing_seen` table written on every `/take`. **Nothing needs that table now, and it is not being built.**

**Catproof the House was redefined twice, and the second version is the simpler one.** The bottles are no longer five objects on the Secret Library shelf — they scatter eight a day across the whole house, with no per-player cap. On 27 September the trigger became **"this player's inventory holds five baby bottles at once"**, counting `used_baby_bottle` and `sanitized_baby_bottle` together, so a player who cleans what they collect does not lose progress. It is checked `on_take`, since taking is the only way an inventory grows.

That is cheaper than the version it replaces, in two ways worth noticing. Counting *takes* needed a per-player tally in `player_thing_seen`; counting what is in the bag is a direct read of `player_inventory` and needs no new state at all. And counting takes could be farmed by dropping and re-taking the same bottle, which the inventory reading cannot — the player has to genuinely hold five. It now behaves exactly like *Charcuterie Board*, including that one's known fragility: drop a bottle to make room and the set is broken until you pick another up.

What does not survive is the Story Bible's reason for it: *"Take all five baby bottles off the Secret Library shelf — left on the shelf, Eunoia will knock them off."* The new reason is: "Pick up five baby bottles lying around the house. Left loose, Eunoia would bat them over."

## Group achievements (3)

All scope **server**. They live in `server_achievements`, keyed `(guild_id, achievement_id)`.

| Achievement | Trigger | Hook |
| --- | --- | --- |
| **Strength in Numbers** | Any single room holds 25 or more of one `thing_id` | `on_drop` |
| **Making a Mess** | Any single room holds 200 or more things in total | `on_drop` |
| **The Feline Collection** — bonus | **The same room** holds 200 or more things **and** 100 or more of them are cat food of any flavor | `on_drop` |

**All three are the same query, and none of them names a room.** Each is a `GROUP BY room_id` over `room_contents` with a different `HAVING` clause — 25 of one `thing_id`, 200 of anything, or 100 cat food inside a room that already holds 200. Write one helper that returns the per-room totals on each drop and pass it three predicates. *The Feline Collection* is the only one that reads two numbers from the same group, and both must come from the **same room**: 120 cans spread over two rooms that each hold 200 things earns nothing.

**All three are `on_drop` only.** A room's contents can also fall when someone takes something, but an achievement is never revoked, so there is nothing to check on the way down. Counting on drop alone halves the work and cannot miss a crossing of the threshold.

**They count `room_contents`, not history.** A server that reaches 200 and then takes things out keeps the achievement, which is correct, and a server that reaches 199 twice earns nothing, which is also correct.

**Nobody gets individual credit, and that was settled on 27 September.** The Story Bible says the bot posts the achievement's name publicly whenever one is earned, and sends the description privately to the player who earned it. A group achievement has no such player. The decision: post the public name as usual, send the description to nobody, and show the achievement in the `/stats` of every current server member, marked as a server achievement. The alternative — crediting whoever dropped the 200th thing — rewards arriving last at something everyone built.

**These three are the achievements most at risk from the cat.** Once crossing ships, every `/pet` in a room where things are piled up can remove one. That tension is deliberate per the Story Bible, but it means a server can sit at 199 for a week. Worth watching in playtest before deciding the thresholds are right.

## Secret achievements (18)

All scope **player**.

| Achievement | Trigger | Hook | State needed |
| --- | --- | --- | --- |
| **A Little Bit Lost** | Any one room entered five or more times within five minutes | `on_move` | a short rolling per-player movement buffer |
| **Out on a Limb** | Player's first `/use tree` in the Courtyard | `on_use` | none — `library_found` already records it |
| **Bulk Buyer** | Player carries 25 or more cans of cat food, summed across flavors | `on_take` | none |
| **Making Friends** | 200 pets by this player while the relationship was positive | `on_pet` | **the relationship at pet time** — see below |
| **Trying to Make Friends** | 200 pets by this player while the relationship was negative | `on_pet` | the same |
| **Cat's Best Friend** | Relationship score reaches 100 | `on_pet` | none |
| **Signed, Sealed, Delivered** | `/use intercom` within three minutes of the doorbell | `on_use` | the doorbell event and its timestamp. **Blocked — not built** |
| **Brewing Trouble** | `/use` the Keurig on Oct 1 | `on_use` | none |
| **Trash Panda** | `/use` the trash can on Oct 1 | `on_use` | none |
| **Say Cheese** | `/use` any of the three mirrors on Oct 2 | `on_use` | none |
| **Green Thumb** | `/use` the watering can, `/take` herbs from the herb garden, or `/use` (carve) the pumpkin on Oct 15 | `on_use` (watering can, pumpkin) or `on_take` (from the herb garden only) | none |
| **Nacho Average Ghost** | `/use` the nacho chips on Oct 21 | `on_use` | none. **Scarce — see below** |
| **Using Your Noodle** | `/use` the pasta pot on Oct 25 | `on_use` | none |
| **Getting into the Spirit** | The day's ghost uses the bedsheet | `on_use` | the ghost system and a `bedsheet` thing. **Blocked — not built** |
| **Ghostbuster** | Correct accusation via the spirit board | `on_use` | the ghost system. **Blocked — not built** |
| **Breaking into the Halloween Candy** | `/use candy` | `on_use` | none |
| **Curbside Pickup** | `/use` the trash can on a Tuesday | `on_use` | none |
| **Not-So-Picky Eater** | Ten `/use` on `frozen_burrito`, cumulative, no time limit | `on_use` | a per-player use count — see below |

**A Little Bit Lost was generalized on 28 September.** It was five Entryway→Living Room→Entryway round trips; it is now **any single room entered five or more times inside five minutes**, by whatever route. Count arrivals per room, not round trips and not total moves: Bedroom→Kitchen→Courtyard→Kitchen→Living Room→Kitchen→Bedroom→Kitchen→Courtyard→Kitchen is five Kitchen arrivals and earns it. The player's starting room is not an arrival, and since a player cannot enter a room they are already in, five arrivals costs at least nine moves. Keep a rolling per-player list of `(room_id, arrived_at)` trimmed to the last five minutes, and on each `on_move` count the entries per `room_id`; any count reaching five fires it.

**The date-gated ones are nearly one function.** Six fixed dates and one weekday, all of the shape "this thing, this day, Pacific". Write it once, parameterised by a date predicate, and register it for each. *Green Thumb* is the exception that shapes the signature: it takes three things across two hooks, so the parameter is a **set of (hook, target) pairs, where a target is a thing or a source** rather than a single `thing_id`. Two collision notes. *Trash Panda* and *Curbside Pickup* both watch the trash can, and Oct 1 2026 is a Thursday, so they cannot collide — but both must be evaluated on the same `on_use`, not chained with an `elif`. And *Gourd Job* and *Green Thumb* **can** both fire from one action: carving a pumpkin on Oct 15 earns both, which is intended, so the dispatcher must not stop at the first match.

**Widened 28 September: a date achievement's day is a 43-hour window, not a calendar day.** The players run from Japan to Hawaii, nineteen hours apart, so any single Pacific calendar day shuts somebody out at one end or the other. "On 1 October" now means **30 September 08:00 Pacific through 2 October 03:00 Pacific**, and every other date takes the same shape.

The window is not a guess — it is exactly the union of "1 October in local time" across UTC+9 to UTC−10. Midnight on 1 October in Japan is 30 September 08:00 Pacific; the last minute of 1 October in Hawaii is 2 October 03:00 Pacific. A player at either extreme earns it during their own 1 October and nobody has to reason about time zones.

It stays one function. Instead of comparing `date(now, Pacific)` with the target, test `target − 1 day at 08:00 Pacific ≤ now < target + 1 day at 03:00 Pacific`. No Release 1 window crosses a daylight-saving boundary — US DST ends on 1 November 2026, so every October window is wholly PDT.

Two consequences to build against. **Consecutive windows overlap by nineteen hours**, so through 1 October both the 1 October and the 2 October achievements are live at the same time. That is harmless only because they watch different things, and it is one more reason the dispatcher must not stop at the first match. And **the Tuesday rule should widen the same way** — Monday 08:00 Pacific through Wednesday 03:00 — otherwise a player in Japan can only earn *Curbside Pickup* between 17:00 Tuesday and 17:00 Wednesday their time. Widening it introduces no collision with *Trash Panda*: the Tuesday windows nearest 1 October close on 30 September at 03:00 and reopen on 5 October at 08:00, both clear of the 1 October window.

**Not-So-Picky Eater is new, and settled: ten frozen burritos.** The burritos are a source in the Kitchen freezer, so supply is not the constraint — the player has to `/use` a `frozen_burrito` ten times, cumulatively, with no time limit. Each `/use` consumes one burrito and prints its `use` text, which is where the joke lives: *"The outside is a burrito. The middle is a popsicle."* Reading that ten times is the achievement.

**This is the first achievement that counts uses, and it needs one column.** `thing_uses` exists today to answer the cooldown question — "did this player use lumber in the last 48 hours" — which needs only a last-used timestamp. Counting to ten needs a running total. Add **`use_count`** to `thing_uses`, keyed `(guild_id, user_id, thing_id)` alongside `last_used_at`, incremented on every successful use. One table then serves both jobs, and any future "do this N times" achievement is free.

The alternative — a row per use, like `pet_events` — buys history nobody has asked for and grows without limit on a thing players will spam. A counter is right here; the snapshot row was right for petting only because the relationship at the time mattered.

**Making Friends and Trying to Make Friends — the `pet_events` fix, settled 26 September.** `pet_events` stores a timestamped row per pet, which answers "how many pets in the last ten minutes" for the mood weighting. It does not store what the relationship *was* at the time, so "200 pets while positive" cannot be computed from it.

Add one column: **`relationship_at_pet`, an integer, not null, written on every insert** with the relationship score as it stood *before* that pet was applied. The alternative — two running counters per player — is cheaper but throws the history away; the column lets the threshold move later, lets both achievements be recomputed if the positive/negative boundary changes, and costs one integer per pet.

**Backfill is a non-issue and that is why this is cheap now.** No real player state exists in production; all player data is test data, so the column can be added with a plain migration and no historical reconstruction. That stops being true the day a real server starts petting, and the history cannot be rebuilt afterwards — so this lands in 2b or 2c, not in 2d with the rest of the achievements.

**Settled 27 September: the meter runs −100 to 100, and zero sits on the negative side.** *Making Friends* counts pets taken while `relationship_at_pet` was **above** zero; *Trying to Make Friends* counts pets taken while it was **zero or below**. The boundary is deliberately not symmetric: every pet falls on exactly one side, so no pet is wasted. Zero is not a neutral starting point either — every player begins at 50, so a relationship sitting at zero has been driven all the way down, which is squarely a case of trying. In code this is one comparison — `> 0` for the first, `<= 0` for the second. The Story Bible's "a perfect relationship is 100" is the top of that range, and *Cat's Best Friend* still fires there. Both achievements are now buildable.

## What has to be stored

Three tables, one of them new, plus one column change.

| Table | Scope | Holds |
| --- | --- | --- |
| `achievements` | global | id, name, kind (public / secret / group), `since_drop`. Loaded from content like everything else |
| `player_achievements` | per guild | `(guild_id, user_id, achievement_id, earned_at)`, unique on the first three |
| `server_achievements` | per guild | `(guild_id, achievement_id, earned_at)` — **new** |
| `pet_events` | per guild | add a relationship snapshot column — **change**, and it must land before players start petting |

**Bonus is a label, not a column.** The Story Bible calls *It Takes a Village* and *The Feline Collection* bonus achievements because each sits on top of another achievement's condition and cannot be earned without it. The code does not distinguish them: there is no bonus field, no separate announcement, and no different treatment in `/stats`. They are stored, awarded and announced exactly like any other achievement, and the pairing is a fact about the fiction rather than something to persist.

**Blocked: seven achievements cannot be earned at all.** Three wait on cat crossing, which the Delivery Plan cuts to after launch: *Unsticking the Situation*, *Return to Sender* and *It Takes a Village*. Two wait on the ghost system, which the plan cuts last: *Getting into the Spirit* and *Ghostbuster*. One waits on the doorbell: *Signed, Sealed, Delivered*. *Forwarding Address* is the seventh — settled 28 September, the letter is a post-MVP deployment. This is a scheduling fact rather than a defect — but it means **2d delivers 28 of 35**, and the drop calendar should not advertise the others.

**One of those blocks is sharper than it looks.** *Return to Sender* is "granted automatically to players who did it the day before the drop", which requires a `sends` log to have been running before the achievement existed. Since crossing itself is post-launch, there is nothing to log at launch and the retroactive grant is moot — but the moment crossing ships, the log has to ship with it, not with the achievement.

**Scarcity: all four are fixed.** Four achievements were earnable by only one player per server, because the thing each of them needed existed exactly once in the house. All four now come from a source or a restock, so every player can reach them.

| Achievement | Was | Now |
| --- | --- | --- |
| **Catproof the House** | `used_baby_bottle` was `quantity = 5` in the Secret Library; the first player to take all five left an empty shelf | **Fixed, but not the way this table first recorded.** The `bottle_row` source was dropped on 26 September. Used baby bottles now **scatter**: eight a day into randomly chosen rooms and containers, admin-configurable through `bottles_per_day`. The object has **no** `max_per_player`, so the trigger is simply the fifth `on_take` of `used_baby_bottle` by that player. Everyone reaches five because supply is continuous, not because a cap rations a fixed shelf |
| **Something's Cooking** | `dark_chocolate` and `spice_jar` were one each in the whole house | **Fixed.** Chocolate: new source `chocolate_book` inside the Living Room bookshelves. Spice: the Amazon box is restocked with four jars on day 2 and every third day after — see Restocks in the Functional Spec |
| **Nacho Average Ghost** | `nacho_chips` is a takeable `quantity = 1` object; on Oct 21 only its holder can use it | **Fixed.** New source `chip_case` in the Kitchen pantry feeds the chips, and `nacho_chips` is `quantity = 0`. Anyone can take a bag on the day, so the achievement no longer belongs to whoever grabbed the only one |
| **Out on a Limb** — partial | `skeleton_key` is `quantity = 1`, so the second player to reach the library finds no key and the cabinet route closes for good | **Fixed.** New source `key_nail` — a ring of identical iron keys hanging on the library shelves — feeds the key, and the object is `quantity = 0`, `max_per_player = 1`, `droppable = no`. Every player can take one and only one, exactly as the carving tools already worked |

The fixes are not all the same shape, and the difference is the point. The bottles and the chocolate are *stashes* — things that were always there in quantity, so a source is the honest model. The spice is a *delivery* — David ordered it, it arrives in batches, and modelling it as an inexhaustible source would have quietly removed the joke. That is why the restock mechanism exists rather than a third source.

## Announcement and unlock text

Settled in the Story Bible, restated here because it decides what the writers owe:

- When anyone earns an achievement of any kind, the bot posts its **name only** in the Halloween channel — the channel the house was initialized in. A secret achievement's name going up is itself the hint that something is there to find.
- The player who earned it gets the **description** privately.
- `/stats` lists only what that player has earned, and in Release 1 shows **your own stats only** — looking up another member is a later release. Each earned achievement appears as its name and the line explaining how it was earned.

So each achievement needs two pieces of writing: a **name** (public, spoiler-free, goes up the moment anyone earns it) and an **unlock description** (private, can say what they did). The description does double duty — it is sent when the achievement fires and shown again in `/stats` — so write it to read as well on the tenth viewing as the first, and in a form that still makes sense weeks later out of context. **All thirty-five names are final.** What is still owed is thirty-five unlock descriptions, all of which were drafted on 28 September and now sit in achievements.tsv, the ninth content file.

Both live in the content files, not in code — same `since_drop` resolution as everything else, so an achievement's name can change at a later drop without a deploy.

One caution for the namer: a secret achievement's name is public from the first time anyone earns it, so it has to hint without instructing. *Trash Panda* does this well. *Follow Your Nose* is a title that survives being read by someone who has not found the drawer. A name like "Use Graphite on the Desk Drawer" would not.

## Open questions

Four questions this spec could not decide. All four were settled on 28 September; each answer sits under its question.

**What does *Something's Cooking* use?** "Use the kitchen" is not a thing. The stove is the obvious target and is already a Kitchen fixture, but the achievement text should name it so the writers can write the response.

**Settled 28 September: it requires the stove.** *Something's Cooking* fires when a player `/use`s the Kitchen stove while carrying `herbs`, `dark_chocolate` and `spice_jar`. The stove already exists as a Kitchen fixture. Its present `use` text is written as a failure — *"you don't have all of it yet"* — so it moves to `use_fail`, and a success line is owed. That is item 4 on the **Writer Revisit: Source Prose** tab, with drafts.

**What does *Dressed for the Season* look like?** There is no `/wear`. `/use costume` is the only mechanism, and its current `use` text has to read as putting it on rather than examining it.

**Settled 28 September: `/use costume` puts it on.** No `/wear` is coming, so the `use` text carries the whole moment. The present line ends on a mirror over a dresser, which is only true in one room — the costume is takeable and can be used anywhere. A room-independent rewrite is item 5 on the **Writer Revisit: Source Prose** tab, with drafts.

**Do the four scarcity fixes above get made?** Each is one cell, but they change content the writers are holding, so they should go in the same pass as the source-prose revisit rather than separately.

**Confirmed 28 September: all four are made.** Verified against the content files as they now stand. `bottle_row` is gone and used baby bottles arrive by restock, eight a day, admin-configurable through `bottles_per_day`. `chocolate_book` in the Living Room bookshelves yields `dark_chocolate`, and the Amazon box is restocked with four spice jars on day 2 and every third day after. `chip_box` in the Kitchen pantry yields `nacho_chips`. `key_nail` on the library shelves yields `skeleton_key`. All four yielded objects now sit at `quantity = 0`, so the source is the only route and no player can exhaust one.

**Which drop does each achievement arrive at?** Every achievement carries a `since_drop` like any other content row. Seven have real dates already; the rest default to launch. This folds into the drop calendar and does not block 2d.

**Settled 28 September: all thirty-five are drop 1.** Every achievement row carries `since_drop = 1`, so the whole set exists from launch. The `since_drop` column stays on `achievements.tsv` because later drops are expected to add achievements — it is the mechanism for that, not something Release 1 exercises. Note again that this is separate from the date gates: the seven date-bound achievements exist from drop 1 and simply cannot fire until their day.

---

*Written 26 September, against the approved Functional Spec and the Release 1 content files as they stand.*
