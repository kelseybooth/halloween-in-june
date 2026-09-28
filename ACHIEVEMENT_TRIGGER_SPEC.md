# Achievement Trigger Spec

Release 1. What fires each of the 35 achievements, when it is checked, and what has to be stored for the check to be possible.

## Scope

Thirty-five achievements: 14 public, 3 group, 18 secret. For each one this document gives the **trigger** (the condition), the **hook** (when it is evaluated), the **scope** (player or server), and the **state** the check needs. It is what Phase 2d builds against. **All thirty-five names are final and approved as of 27 September** — the Story Bible is the source of the names, and nothing in it is a placeholder any more.

It does not restate what a command does — that is the **Functional Spec** — or why an achievement exists — that is the **Story Bible**. Where this document and the content files disagree about what exists, the files are right, and eleven such disagreements are called out below rather than papered over.

**Read the Blocked and scarce sections before scheduling 2d.** Writing this out surfaced that six achievements cannot be earned at all with the code and content as they stand, and four more can be earned by exactly one player per server, ever. Those are content and sequencing problems, not trigger problems, and they are cheaper to fix now than after launch.

## How a trigger works

**An achievement registers against one hook, or several where the fiction needs it.** Do not re-evaluate 35 conditions after every action; dispatch only the achievements listening on the hook that just fired. Most listen on exactly one. *Green Thumb* listens on two — `on_use` for the watering can and the pumpkin, `on_take` for the herbs — because there are three ways to notice that date and all of them should count. Build the dispatcher so that registering one achievement against several hooks is ordinary rather than a special case, and so that one action can fire more than one achievement. The hooks are:

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
| **Something's Cooking** | Player `/use`s the stove in the Kitchen while carrying `herbs`, `dark_chocolate` and `spice_jar` | `on_use` | none — **fixed 26 Sept** |
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

**On Charcuterie Board.** "Holds all five at once" needs no new state and is the cheap reading, but it is fragile: a player who drops a can to make room, or gives one away, loses the set. This is intentional, because a player can always take an additional can from any of the cat food sources.

**Catproof the House was redefined twice, and the second version is the simpler one.** The bottles are no longer five objects on the Secret Library shelf — they scatter eight a day across the whole house, with no per-player cap. On 27 September the trigger became **"this player's inventory holds five baby bottles at once"**, counting `used_baby_bottle` and `sanitized_baby_bottle` together, so a player who cleans what they collect does not lose progress. It is checked `on_take`, since taking is the only way an inventory grows.

That is cheaper than the version it replaces, in two ways worth noticing. Counting *takes* needed a per-player tally in `player_thing_seen`; counting what is in the bag is a direct read of `player_inventory` and needs no new state at all. And counting takes could be farmed by dropping and re-taking the same bottle, which the inventory reading cannot — the player has to genuinely hold five. It now behaves exactly like *Charcuterie Board*, including that one's known fragility: drop a bottle to make room and the set is broken until you pick another up.

What does not survive is the Story Bible's reason for it: *"Take all five baby bottles off the Secret Library shelf — left on the shelf, Eunoia will knock them off."* The new reason is: "Pick up five baby bottles lying around the house. Left loose, Eunoia would bat them over."

## Group achievements (3)

All scope **server**. They live in `server_achievements`, keyed `(guild_id, achievement_id)`.

| Achievement | Trigger | Hook |
| --- | --- | --- |
| **Strength in Numbers** | Any single room holds 25 or more of one `thing_id` | `on_drop` |
| **Overdue Returns** | Any single room holds 200 or more things in total | `on_drop` |
| **The Feline Collection** — bonus | **The same room** holds 200 or more things **and** 100 or more of them are cat food of any flavor | `on_drop` |

**All three are the same query, and none of them names a room.** Each is a `GROUP BY room_id` over `room_contents` with a different `HAVING` clause — 25 of one `thing_id`, 200 of anything, or 100 cat food inside a room that already holds 200. Write one helper that returns the per-room totals on each drop and pass it three predicates. *The Feline Collection* is the only one that reads two numbers from the same group, and both must come from the **same room**: 120 cans spread over two rooms that each hold 200 things earns nothing.

**All three are `on_drop` only.** A room's contents can also fall when someone takes something, but an achievement is never revoked, so there is nothing to check on the way down. Counting on drop alone halves the work and cannot miss a crossing of the threshold.

**They count `room_contents`, not history.** A server that reaches 200 and then takes things out keeps the achievement, which is correct, and a server that reaches 199 twice earns nothing, which is also correct.

**Nobody gets individual credit, which needs a product decision.** The Story Bible says the bot posts the achievement's name publicly whenever one is earned, and sends the description privately to the player who earned it. A group achievement has no such player. My proposal: post the public name as usual, send the description to nobody, and show the achievement in the `/stats` of every current server member, marked as a server achievement. The alternative — crediting whoever dropped the 200th thing — rewards arriving last at something everyone built.

**These three are the achievements most at risk from the cat.** Once crossing ships, every `/pet` in a room where things are piled up can remove one. That tension is deliberate per the Story Bible, but it means a server can sit at 199 for a week. Worth watching in playtest before deciding the thresholds are right.

## Secret achievements (18)

All scope **player**.

| Achievement | Trigger | Hook | State needed |
| --- | --- | --- | --- |
| **A Little Bit Lost** | Five EN→LI→EN round trips within five minutes | `on_move` | a short rolling per-player movement buffer |
| **Out on a Limb** | Player's first `/use tree` in the Courtyard | `on_use` | none — `library_found` already records it |
| **Bulk Buyer** | Player carries 25 or more cans of cat food, summed across flavors | `on_take` | none |
| **Making Friends** | 200 pets by this player while the relationship was positive | `on_pet` | **the relationship at pet time** — see below |
| **Trying to Make Friends** | 200 pets by this player while the relationship was negative | `on_pet` | the same |
| **Cat's Best Friend** | Relationship score reaches 100 | `on_pet` | none |
| **Signed, Sealed, Delivered** | `/use intercom` within three minutes of the doorbell | `on_use` | the doorbell event and its timestamp. **Blocked — not built** |
| **Brewing Trouble** | `/use` the Keurig on Oct 1 | `on_use` | none |
| **Trash Panda** | `/use` the trash can on Oct 1 | `on_use` | none |
| **Say Cheese** | `/use` any of the three mirrors on Oct 2 | `on_use` | none |
| **Green Thumb** | `/use` the watering can, `/take` the herbs, or `/use` (carve) the pumpkin on Oct 15 | `on_use` (watering can, pumpkin) or `on_take` (herbs) | none |
| **Nacho Average Ghost** | `/use` the nacho chips on Oct 21 | `on_use` | none. **Scarce — see below** |
| **Using Your Noodle** | `/use` the pasta pot on Oct 25 | `on_use` | none |
| **Getting into the Spirit** | The day's ghost uses the bedsheet | `on_use` | the ghost system and a `bedsheet` thing. **Blocked — not built** |
| **Ghostbuster** | Correct accusation via the spirit board | `on_use` | the ghost system. **Blocked — not built** |
| **Breaking into the Halloween Candy** | `/use candy` | `on_use` | none |
| **Curbside Pickup** | `/use` the trash can on a Tuesday | `on_use` | none |
| **Not-So-Picky Eater** | Ten `/use` on `frozen_burrito`, cumulative, no time limit | `on_use` | a per-player use count — see below |

**The date-gated ones are nearly one function.** Six fixed dates and one weekday, all of the shape "this thing, this day, Pacific". Write it once, parameterised by a date predicate, and register it for each. *Green Thumb* is the exception that shapes the signature: it takes three things across two hooks, so the parameter is a **set of (hook, thing) pairs** rather than a single `thing_id`. Two collision notes. *Trash Panda* and *Curbside Pickup* both watch the trash can, and Oct 1 2026 is a Thursday, so they cannot collide — but both must be evaluated on the same `on_use`, not chained with an `elif`. And *Gourd Job* and *Green Thumb* **can** both fire from one action: carving a pumpkin on Oct 15 earns both, which is intended, so the dispatcher must not stop at the first match.

**Not-So-Picky Eater is new, and settled: ten frozen burritos.** The burritos are a source in the Kitchen freezer, so supply is not the constraint — the player has to `/use` a `frozen_burrito` ten times, cumulatively, with no time limit. Each `/use` consumes one burrito and prints its `use` text, which is where the joke lives: *"The outside is a burrito. The middle is a popsicle."* Reading that ten times is the achievement.

**This is the first achievement that counts uses, and it needs one column.** `thing_uses` exists today to answer the cooldown question — "did this player use lumber in the last 48 hours" — which needs only a last-used timestamp. Counting to ten needs a running total. Add **`use_count`** to `thing_uses`, keyed `(guild_id, user_id, thing_id)` alongside `last_used_at`, incremented on every successful use. One table then serves both jobs, and any future "do this N times" achievement is free.

The alternative — a row per use, like `pet_events` — buys history nobody has asked for and grows without limit on a thing players will spam. A counter is right here; the snapshot row was right for petting only because the relationship at the time mattered.

**Making Friends and Trying to Make Friends — the `pet_events` fix, settled 26 September.** `pet_events` stores a timestamped row per pet, which answers "how many pets in the last ten minutes" for the mood weighting. It does not store what the relationship *was* at the time, so "200 pets while positive" cannot be computed from it.

Add one column: **`relationship_at_pet`, an integer, not null, written on every insert** with the relationship score as it stood *before* that pet was applied. The alternative — two running counters per player — is cheaper but throws the history away; the column lets the threshold move later, lets both achievements be recomputed if the positive/negative boundary changes, and costs one integer per pet.

**Backfill is a non-issue and that is why this is cheap now.** No real player state exists in production; all player data is test data, so the column can be added with a plain migration and no historical reconstruction. That stops being true the day a real server starts petting, and the history cannot be rebuilt afterwards — so this lands in 2b or 2c, not in 2d with the rest of the achievements.

**Settled 27 September: the meter runs −100 to 100, and zero sits on the negative side.** *Making Friends* counts pets taken while `relationship_at_pet` was **above** zero; *Trying to Make Friends* counts pets taken while it was **zero or below**. The boundary is deliberately not symmetric: every pet falls on exactly one side, so no pet is wasted. Zero is not a neutral starting point either — every player begins at 50, so a relationship sitting at zero has been driven all the way down, which is squarely a case of trying. In code this is one comparison — `> 0` for the first, `<= 0` for the second. The Story Bible's "a perfect relationship is 100" is the top of that range, and *Cat's Best Friend* still fires there. Both achievements are now buildable.

## What has to be stored

Four tables, two of them new, plus one column change.

| Table | Scope | Holds |
| --- | --- | --- |
| `achievements` | global | id, name, kind (public / secret / group), `since_drop`. Loaded from content like everything else |
| `player_achievements` | per guild | `(guild_id, user_id, achievement_id, earned_at)`, unique on the first three |
| `server_achievements` | per guild | `(guild_id, achievement_id, earned_at)` — **new** |
| `player_thing_seen` | per guild | `(guild_id, user_id, thing_id, first_seen_at)` — **new**, written on every successful `/take`. Serves *Charcuterie Board* alone, now that *Catproof the House* reads the inventory directly, and will serve any future "collect the set" |
| `pet_events` | per guild | add a relationship snapshot column — **change**, and it must land before players start petting |

**Bonus is a label, not a column.** The Story Bible calls *It Takes a Village* and *The Feline Collection* bonus achievements because each sits on top of another achievement's condition and cannot be earned without it. The code does not distinguish them: there is no bonus field, no separate announcement, and no different treatment in `/stats`. They are stored, awarded and announced exactly like any other achievement, and the pairing is a fact about the fiction rather than something to persist.

**Blocked: six achievements cannot be earned at all.** Three wait on cat crossing, which the Delivery Plan cuts to after launch: *Unsticking the Situation*, *Return to Sender* and *It Takes a Village*. Two wait on the ghost system, which the plan cuts last: *Getting into the Spirit* and *Ghostbuster*. One waits on the doorbell: *Signed, Sealed, Delivered*. *Forwarding Address* makes seven if the letter does not ship. This is a scheduling fact rather than a defect — but it means **2d delivers at most 28 of 35**, and the drop calendar should not advertise the others.

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

- When anyone earns an achievement of any kind, the bot posts its **name only** in the Halloween channel. A secret achievement's name going up is itself the hint that something is there to find.
- The player who earned it gets the **description** privately.
- `/stats` lists only what that player has earned, and in Release 1 shows **your own stats only** — looking up another member is a later release. Each earned achievement appears as its name and the line explaining how it was earned.

So each achievement needs two pieces of writing: a **name** (public, spoiler-free, goes up the moment anyone earns it) and an **unlock description** (private, can say what they did). The description does double duty — it is sent when the achievement fires and shown again in `/stats` — so write it to read as well on the tenth viewing as the first, and in a form that still makes sense weeks later out of context. **All thirty-five names are final.** What is still owed is thirty-five unlock descriptions, none of which is written, and that is now the whole of the remaining writing job.

Both live in the content files, not in code — same `since_drop` resolution as everything else, so an achievement's name can change at a later drop without a deploy.

One caution for the namer: a secret achievement's name is public from the first time anyone earns it, so it has to hint without instructing. *Trash Panda* does this well. *Follow Your Nose* is a title that survives being read by someone who has not found the drawer. A name like "Use Graphite on the Desk Drawer" would not.

## Open questions

Six things this spec cannot decide.

**Does a group achievement appear in anybody's `/stats`?** I have proposed: yes, in every current member's, marked as a server achievement. Needs a yes or no before 2d.

**Charcuterie Board — hold all five at once, or have held each?** I have argued for "has held each", which costs the `player_thing_seen` table. The cheap reading ships without it.

**What does *Something's Cooking* use?** "Use the kitchen" is not a thing. The stove is the obvious target and is already a Kitchen fixture, but the achievement text should name it so the writers can write the response.

**What does *Dressed for the Season* look like?** There is no `/wear`. `/use costume` is the only mechanism, and its current `use` text has to read as putting it on rather than examining it.

**Do the four scarcity fixes above get made?** Each is one cell, but they change content the writers are holding, so they should go in the same pass as the source-prose revisit rather than separately.

**Which drop does each achievement arrive at?** Every achievement carries a `since_drop` like any other content row. Seven have real dates already; the rest default to launch. This folds into the drop calendar and does not block 2d.

---

*Written 26 September, against the approved Functional Spec and the Release 1 content files as they stand.*
