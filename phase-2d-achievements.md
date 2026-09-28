# Phase 2d — Achievements

## What 2d is

2d is the achievement system: a dispatcher, a ninth content file, one new table, the announcement path and `/stats`. The conditions themselves are not in this document — they are in the **Achievement Trigger Spec** tab, one row per achievement, and that tab is authoritative for what fires. This one says what ships, in what order, and how you know it is done.

The work divides unevenly. The engine is small: one dispatcher and about thirty short predicate functions, nearly all of which read state that already exists. The content is not small, and it is the reason this phase can stall.

### Prerequisites, and one that is not met

Met already:

- `relationship_at_pet` on `pet_events`, and `use_count` on `thing_uses` — both landed in 2b, both in `database.py`
- The content loader and drop resolution — seven files in 2b, frozen, and the eighth in 2c
- `/take`, `/drop`, `/use`, `/look`, the Alexa handler and the craving reaction handler — 2c, shipped. Every hook 2d listens on is a line of code that already runs; 2d adds a call at the end of each, not a new pathway
- `drawer_unjammed` — 2c.5, in flight. *Follow Your Nose* fires on it, so that one registration lands after 2c.5 does

Not met when this was written, met since:

- **Thirty-five unlock descriptions.** Drafted 28 September and delivered as `achievements.tsv`, the ninth content file, then reviewed line by line against the triggers. Six lines were reworded in that pass and *A Little Bit Lost* was generalized as a result. This was the phase's critical path and it is now clear; what remains is a read-through before launch, not a writing job.

## Two decisions settled before drafting

**Charcuterie Board reads the inventory.** The trigger is "this player's inventory holds all five cat food flavors at the same time", checked `on_take` — a direct read of `player_inventory` needing no new state. The known fragility is accepted: a player who drops a can to make room breaks the set until they pick another up. That is tolerable here because every flavor comes from a source that cannot run out, so the set can always be rebuilt.

The consequence for the build is bigger than the achievement. **`player_thing_seen` is not built at all.** It existed to serve *Charcuterie Board* alone, once *Catproof the House* moved to an inventory read on 27 September. With this decision nothing needs it, and 2d adds one table rather than two. The Achievement Trigger Spec has been updated to match.

**A group achievement appears in every current member's `/stats`,** marked as a server achievement, with nobody credited as the earner. The alternative — crediting whoever dropped the two hundredth thing — rewards arriving last at something everyone built.

## The ninth content file

Names and unlock text are content, not code. They change without a deploy, they arrive on drops like everything else, and a writer has to be able to edit them without opening the repository. 2c added the eighth file; 2d adds the ninth.

**`achievements.tsv`** — `achievement_id`, `kind`, `name`, `unlock`, `since_drop`, `sort_order`, `notes`.

| Column | Holds |
| --- | --- |
| `achievement_id` | Stable id, snake case. Code references this, never the name |
| `kind` | `public`, `secret` or `group`. Decides which table the award lands in, and nothing else |
| `name` | The public name, posted in the Halloween channel the moment anyone earns it |
| `unlock` | The private description, sent to the earner and shown again in `/stats` |
| `since_drop` | Which drop this row arrives at. Same resolution as every other content row |
| `sort_order` | Display order within a kind in `/stats` |
| `notes` | Writer and PM scratch. The loader ignores it |

**There is no `trigger` column, and there should not be one.** The conditions involve counts, time windows, sets and cross-table joins; a half-expressive mini-language in one cell is worse than a function per achievement. The file carries what a writer owns. The condition lives in the codebase next to the hook it listens on.

**`since_drop` is not the date gate.** Six achievements fire only on a given day and one only on Tuesdays, and those dates belong to the trigger function. `since_drop` controls when the row becomes visible — when the achievement exists at all on a server. An achievement can exist from launch and be earnable only on 21 October; those are different axes, and conflating them produces an achievement that quietly cannot be earned.

Validate on load alongside the other eight, and refuse to start on a duplicate `(achievement_id, since_drop)`, a `kind` outside the three values, an empty `name` or `unlock`, **a registered trigger whose `achievement_id` is not in the file, or a row in the file with no registered trigger.** That last pair is the one worth building carefully. It catches the day somebody adds a thirty-sixth achievement and never wires it up, or renames an id and half the awards silently stop landing.

## The dispatcher

One dispatcher, registered by hook. Nothing re-evaluates thirty-five conditions after every action; a hook runs only the predicates listening on it.

**Registration takes a set of hooks, not one.** Most achievements listen on exactly one. *Green Thumb* listens on two — `on_use` for the watering can and the pumpkin, `on_take` for the herbs — so registering one achievement against several hooks has to be ordinary rather than a special case.

**A hook fires every predicate registered on it and does not stop at the first match.** *Gourd Job* and *Green Thumb* can both fire from a single action: carving a pumpkin on 15 October earns both, and that is intended. Ordering within a hook is undefined and must stay that way — no predicate may depend on another having run first.

**Awarding is idempotent, and only a first award announces.** `player_achievements` takes a unique key on `(guild_id, user_id, achievement_id)`, awards are `INSERT ... ON CONFLICT DO NOTHING`, and the announcement fires only when the insert actually created a row. Without this, a standing condition — *Cat's Best Friend* is true forever once true — reposts its announcement on every `/pet` for the rest of October.

**A trigger checks; it never mutates.** The hook runs after the command has committed its own change. An achievement check that writes game state is a bug: it makes the same action behave differently depending on what the player had already earned.

**The date-gated seven are nearly one function.** Six fixed dates and one weekday, all of the shape "this thing, this window, Pacific". Widened 28 September: a date is not a calendar day but a 43-hour window, from 08:00 Pacific the day before through 03:00 Pacific the day after, so that players from Japan to Hawaii can all earn it on their own local date. Write it once, parameterised by a set of (hook, target) pairs and a window, and register it seven times. The Achievement Trigger Spec has the arithmetic and the two consequences.

**A predicate that raises must not take down the command that fired the hook.** Log it and carry on. A player who loses an achievement to an exception can earn it next time; a player whose `/take` returns an error has lost the thing.

## What has to be stored

2d adds one table.

| Table | Scope | Holds |
| --- | --- | --- |
| `achievements` | global | Loaded from `achievements.tsv` — id, kind, name, unlock, `since_drop` |
| `player_achievements` | per guild | `(guild_id, user_id, achievement_id, earned_at)`, unique on the first three |
| `server_achievements` | per guild | `(guild_id, achievement_id, earned_at)` — **new** |

Everything else 2d reads is already there: `relationship_at_pet`, `use_count`, `player_inventory`, `room_contents`, `thing_uses`, `library_found`, and the craving tally with its last-credited date. `player_thing_seen` is not built.

One piece of state has no home and does not deserve a table. *A Little Bit Lost* needs a short rolling record of where a player has arrived — generalised on 28 September to **any single room entered five or more times inside five minutes**, by any route. Keep a list of `(room_id, arrived_at)` per `(guild_id, user_id)`, trim it to the last five minutes on each `on_move`, then count arrivals per `room_id`; five in one room fires it. Cap the list, and accept that a restart loses it. It is the only achievement whose state is allowed to be ephemeral, and the only one where losing it costs a player nothing they can notice.

## Announcing an achievement

Two deliveries, with different constraints.

**The name goes up publicly in the Halloween channel every time anyone earns anything** — including secret achievements, where the name appearing is itself the hint that something is there to find. Name only, never the description.

**The description goes to the earner privately,** and the mechanism depends on where the hook fired:

- Fired inside a slash command — `on_take`, `on_drop`, `on_use`, `on_move`, `on_pet` — an interaction token is in hand, so send an ephemeral follow-up.
- Fired anywhere else — `on_reaction`, `on_message`, `on_midnight`, `on_cross` — there is no token. A reaction carries none, which is already why the craving's 😻 confirmation is public with no DM fallback. Send a direct message instead.
- **A failed DM is not an error.** People close their DMs. `/stats` holds the description permanently, so log the failure and carry on. Do not retry, and do not fall back to posting the description publicly — that spoils a secret achievement for everyone.

**A group achievement announces its name and sends no description to anyone,** because there is no earner. It still shows in `/stats` for every member.

The Halloween channel is the channel the house was initialized in, recorded on the guild row at init. **An announcement failure must never roll back an award.** Write the row, then announce; if the channel cannot be resolved or the send fails, the player still has the achievement and `/stats` still shows it.

## /stats

Held back from 2c deliberately, so it could be built against real achievement data rather than a stub. Release 1 shows **your own stats only**; looking up another member is a later release and changes what the command has to protect.

One ephemeral embed, holding:

- **Achievements earned**, each as its name and its unlock line, grouped by kind and ordered by `sort_order` within a kind. Group achievements appear here for every current member, marked as server achievements, with nobody named as the earner.
- **The pet count and the craving tally**, both of which already exist. The tally belongs here so the daily game outlives the achievement that rewards it once.
- **Nothing about achievements not yet earned.** No count out of thirty-five, no locked rows, no progress bars. A secret achievement's existence is revealed by somebody earning it, not by this command.

**Use an embed, not a plain message.** A message caps at 2,000 characters and an embed's description allows 4,096. Thirty-five names plus thirty-five unlock lines will pass 2,000 for a completionist, and the failure mode is the command breaking at the end of October for exactly the players who played the most. If a player somehow passes 4,096, truncate with a count, in the same shape `Also here:` already uses.

**Ephemeral, always.** `/stats` carries unlock descriptions, which are the spoilers. Posting them in the channel defeats the design that keeps the public announcement to a name.

**The empty state matters more than it looks.** A player who has earned nothing runs this on day one. It should read as an invitation rather than an error: pet count, craving tally, and a line saying there is nothing here yet.

## Which of the thirty-five ship

Twenty-eight of thirty-five are earnable. Seven cannot be earned at all, and not one of them is a trigger problem:

- Cat crossing, cut to after launch: *Unsticking the Situation*, *Return to Sender*, *It Takes a Village*
- The ghost system, cut last: *Getting into the Spirit*, *Ghostbuster*
- The doorbell, not built: *Signed, Sealed, Delivered*
- *Forwarding Address* is blocked too — the letter is a post-MVP deployment

**Register all thirty-five anyway.** Every one gets a row in `achievements.tsv` and a registered predicate; the seven simply listen on hooks that never fire this release. That is cheaper than maintaining a shipping subset, it keeps the loader's both-directions check meaningful, and it means cat crossing arriving after launch turns three achievements on without reopening 2d.

What it does mean is that **the drop calendar must not advertise the seven**. A name nobody can earn is worse than a name nobody has seen.

One sequencing note: *Follow Your Nose* fires on `drawer_unjammed`, which 2c.5 is building now. Register it with the rest — it starts firing when 2c.5 lands, and needs no change here.

## What 2d does not do

- No cat crossing, no ghost system, no doorbell, no letter — the four systems the blocked six are waiting on
- **No retroactive grants.** *Return to Sender* is described as granted automatically to players who did it the day before the drop, but there is nothing to grant from: the `sends` log ships with crossing, not with achievements, and at launch nothing has been logged. When crossing ships, the log ships with it, not with the achievement.
- No looking up another member's `/stats`
- No admin command to grant or revoke an achievement by hand
- No progress display for unearned achievements
- No `player_thing_seen`

## Definition of done

- `achievements.tsv` loads as the ninth content file, all thirty-five rows present, every `name` and `unlock` non-empty
- The loader refuses to start when a registered trigger has no row, and when a row has no registered trigger — both directions tested
- `server_achievements` exists; `player_achievements` carries its unique key and awards are `ON CONFLICT DO NOTHING`
- A standing condition announces exactly once: *Cat's Best Friend* tested across repeated `/pet` calls
- One action firing two achievements is tested — carving a pumpkin on 15 October earns *Gourd Job* and *Green Thumb*
- *Green Thumb* is tested on both of its hooks, `on_use` and `on_take`
- The date-gated seven run off one parameterised function against a faked clock, with both window edges tested to the minute, plus the Tuesday case and the 1 October pairing of *Trash Panda* and *Curbside Pickup*
- *Making Friends* and *Trying to Make Friends* split on `relationship_at_pet`, with a pet at exactly zero counting toward *Trying*
- *Charcuterie Board* and *Catproof the House* both read `player_inventory` directly, and neither can be farmed by dropping and re-taking
- A predicate that raises is logged and does not fail the command that fired the hook
- The private description arrives ephemerally from a slash-command hook and by direct message from a reaction hook; a closed DM is logged rather than raised
- An announcement failure leaves the award in place
- `/stats` renders as an ephemeral embed, shows a group achievement to a member who was not the earner, and has a tested empty state
- Each of the twenty-eight earnable achievements has a test that earns it

## Open questions

**Who writes the thirty-five unlock descriptions, and by when?** This is the phase's critical path and it currently has no owner. The engineering can proceed against placeholder rows, but the loader will not start on an empty `unlock`, so a placeholder pass is itself a decision someone has to make.

**Answered 28 September: they are written.** `achievements.tsv` carries all thirty-five, with `achievement_id`, `kind`, `name`, `unlock`, `since_drop`, `sort_order` and `notes` filled, and the seven blocked achievements flagged in `notes`. 2d is no longer waiting on content.

**Does the letter ship?** *Forwarding Address* needs `/use letter`, an address list and a picker. None of it exists, and none of it sits in any phase. Either it gets one, or the achievement stays blocked and the earnable count is twenty-eight.

**Settled 28 September: the letter is a post-MVP deployment.** *Forwarding Address* is therefore blocked at launch and the earnable count is **twenty-eight of thirty-five**. It still gets a row in `achievements.tsv` and a registered predicate like the other blocked six — the hook simply never fires until the letter ships.

**How is the Halloween channel configured per guild?** The announcement path needs to resolve it and nothing specifies where it comes from — an admin command, a config table, or a name convention. Small question, but 2d cannot announce anything until it has an answer.

**Settled 28 September: it is the channel the house was initialized in.** An admin runs the init command in a channel, that channel becomes the haunted house, and the same channel receives every achievement announcement. Record its id on the guild row at init. There is no separate announcement setting to configure, nothing to keep in sync, and no name convention to guess — if the bot can post the rooms there it can post the announcements there.

**Moot as of 28 September.** All thirty-five descriptions were written in a single pass, so they are consistent by construction and the worked-examples step is unnecessary. A read-through before launch is still worth an hour, since every line is read again each time a player opens `/stats`.
