# V3 — implementation plan

*Refreshed 19 October from `archived/v3-implementation-plan.md`, the version delivered with the Phase 3a work order, plus a status section recording where 3a and 3b stand.*

V3 is the post-playtest code line. It ships drops 0 through 7 and is not finished when drop 0 ships.

**Keep the two axes apart.** A release is what the developers deploy; a drop is a story beat the players experience. The Functional Spec already settled this — the runtime keys on drops and the calendar, never on a release number — so the plan below names releases V3.0 through V3.3 and leaves drop numbers to the content. One release can carry several drops; one drop can span two releases.

---

## Status, 19 October

**Phase 3a is in build** — the drops 0 and 1 proof of concept described in the next section. Nothing in it has changed.

**Phase 3b is specified and ready for handoff.** It is drop 2, and three documents carry it: the **Phase 3b Work Order** for the engine, **Drop 2 content file edits** for the TSV changes, and **Drop 2 copy deck — toys** for all twenty-seven strings. Read against workstream F below, which is where the toy was first sketched, it contains:

- **Three commands** — `/take`, `/drop` and `/inventory`, guild-registered at the drop.
- **Two toys, not one.** `feather_wand` and `crinkle_ball`, equally likely, drawn from the class by a `type:toy` selector on a single restock row and held at two in the channel by a class-scoped `max_present`. Because both carry the aliases `toy` and `cat toy`, drop 2 is the first release that can raise the ambiguity prompt — the two-pass resolver is exercised here rather than in drop 3.
- **The ramp, the cooldown and the award** exactly as workstream F states them, driven by `type = toy` rather than by any `thing_id`, so toy number three is a TSV row and not an engine change.
- **Three achievements** — *Persuasive*, *Impressively Bad Luck* (four refusals running, 9.4%) and *Tireless* (twenty-five plays). *Tireless* needs a `thing_uses` row written on every successful play, and that one insert is what makes the two larger collection achievements possible at all.
- **A six-rung hint ladder**, toy-agnostic and filtered to takeable toys, so a hint never names a toy that is not in the channel and the Amazon box is never offered as the subject of *Try /take*.
- **The bed stash** — a player's first cat-bed fluff after drop 2 arrives dislodges one of the two toys, detected against the drop 2 arrival timestamp rather than a null `last_bed_fluff`, which would fire for every drop 1 tester.
- **One column added now that nothing in 3b reads:** `placed_at` on `room_contents`. It cannot be backfilled for things already sitting in a channel, and it is the prerequisite for the toy drain.

**Deferred out of 3b, each with its reason recorded:** restock draw weights, because drop 2's two toys are deliberately equal; the catnip buff, settled in shape at +25 percentage points, three charges, a five-minute lapse and a thirty-minute re-application cooldown, and parked in the copy deck; the two larger collection achievements, `easily_amused` and `whole_toy_box`, because neither can carry a truthful `since_drop` until the drop that earns it exists; and toy rotation, which has a tab of its own.

**One cross-document conflict to settle.** The drop unlock schedule still places `/drop` in drop 4 and says so twice. Phase 3b ships it in drop 2, which was agreed deliberately — a player who can pick a toy up should be able to put it down in the same drop. The work order is right and the schedule needs the correction.

**The meter decisions in workstream F are settled rather than open.** Start at zero, no ceiling, floor unchanged at −100; the nightly drift skips any day with a cat interaction, stamped through one `last_cat_interaction_date` column; and *Making Friends* / *Trying to Make Friends* are a single fork evaluated at pet 200. The drop schedule's meter section reconciles all of it against the built code with line references.

---

## The POC: drops 0 and 1 only

**V3.0 narrows to a proof of concept.** Two drops, four player commands, one object, four achievements. Its job is not to be a game — it is to prove the two mechanisms everything later depends on: **gating** (content and commands appearing only when their drop arrives) and **hinting** (the rail that tells a player what to do next). Everything else waits.

### In scope

|  | Drop 0 | Drop 1 |
| --- | --- | --- |
| Player commands | `/pet`, `/stats` | **+** `/look`, `/use` |
| Admin | `/start-game <channel>`, `/advance-game`, `/admin_config` | — |
| Content | the cat | one cat bed, fixture, not takeable |
| Achievements | *Making First Contact*, *A Paw in the Door*, *Favorite Human* | **+** *Fluffed to Perfection* |
| Hints | two, both routing to `/stats` | three, ending at the bed |

Plus the meter rework in full — start at 0, no ceiling, drift skipped on any day with a cat interaction, the four-band `/stats` sentence — and the `on_relationship_change` hook, which *A Paw in the Door* and *Favorite Human* both need.

### Out of scope, and worth saying so explicitly

`/take`, `/inventory`, `/go`, `/enter`, `/drop`, every room, the toy, feeding, the craving game, `/help`, the `max_present` restock rule, and three of the seven new achievements — *Persuasive*, *Impressively Bad Luck* and *Bowl Half Empty*, all of which depend on the toy or on cat food.

### The thing that will break this if nobody catches it

**Every existing content row carries `since_drop = 1`.** All 35 achievements. All 142 rows in `things.tsv`. Under the old numbering that meant "live at launch"; under the new numbering it means **live the moment `/advance-game` is run once**.

So on the current files, advancing from drop 0 to drop 1 does not reveal a cat bed. It reveals **the entire game** — every thing in nine rooms, and all 35 achievements — in a POC that is supposed to be proving the opposite.

**The cheap fix is a bulk edit, not a content pass.** Set every existing row to a `since_drop` above the POC range — 3 works, since that is where the Entryway genuinely opens — and give the real per-row numbering to whoever builds drops 2 and 3. For the POC only the new rows need accurate values.

**With exactly one exception: Eunoia's own `things.tsv` row.** `/look cat` arrives in drop 1, and it resolves against her row rather than against the petting code, so moving her to drop 3 with everything else would make the cat unlookable in the drop that introduces looking. Her row stays at 0, the new `cat_bed` row goes in at 1, everything else moves to 3.

This is the drop-numbering collision that has been on the open list since the schedule was first written. It stops being theoretical the first time anyone runs `/advance-game`.

### What the POC proves, in order

1. **Commands appear per drop, per server.** Deregistration exercised on a 2→4 command set, with the two test servers able to sit on different drops at the same time.
2. **Content appears per drop.** `/look` finds a bed in drop 1 and nothing in drop 0, and nothing from drop 3 leaks into either.
3. **The hint rail fires in order, once each, and retires hints that have been made moot.**
4. **The quest spine works.** Pet → *Making First Contact* → *A Paw in the Door* becomes visible and the player is told so.
5. **The meter behaves.** Zero start, no ceiling at 100 or 250, four `/stats` bands, drift skipped on an interaction day.

### QA commands the POC actually needs

A subset, since there is nowhere to teleport to and nothing to spawn: **`/qa-drop`** (jump between 0 and 1 in both directions), **`/qa-reset-player`** (which must clear the hints-shown rows, or the ladder is one-shot per tester), **`/qa-relationship`** (50 and 250 are days of honest play away), **`/qa-clock`** and **`/qa-midnight`** (the bed's 24 hours and the nightly drift), and **`/qa-inspect`**. `/qa-teleport`, `/qa-spawn` and `/qa-state` can wait for rooms.

### Content to write for the POC

Small, but none of it exists yet: the cat bed's `look` text, its `use` success line and its `use_fail` for the 24-hour cooldown; the channel's `/look` prefix — *"Items here"* — and whatever fills it when the channel is empty; the five hint strings; the four `/stats` relationship bands and the two empty-state lines. Roughly fifteen strings.

---

## Before writing the V3.0 spec

Most of what blocked this list has been answered. What follows is what is settled, what is left, and the one thing that changed shape entirely.

### Settled

- **Timing.** Halloween is no longer the single payoff point; a winter-solstice repair is on the table, which lines up better with the autumn-equinox breaking point. The achievement calendar goes to the writers. **The house still aims to open by Halloween**, which is the constraint the release plan has to meet.
- **Drop numbering starts at 0.** Drop 0 is the cat alone in one channel.
- **Drops advance by admin command.** Drop 0 opens when an admin starts the game; every later drop without an event trigger is advanced by command. Dates return once a few servers have run. This retires the date-versus-threshold question and replaces the condition registry with a button, which is both cheaper and more honest about not knowing the pacing yet.
- **The channel is named per server**, so starting the game takes a channel argument — `/start-game <channel>` rather than a hardcoded name. The channel will be renamed later, and may differ in every server.
- **The channel becomes a room-like row.** Confirmed, and drop 1 needs `/look` in it to show what has dropped there, which makes the change load-bearing rather than tidy.
- **Drop 0 ships without the craving game.** It is unbuilt. It belongs in drop 0 when it exists; the MVP does not wait.
- **Two new drop-0 achievements:** first pet, and first time reaching 50. Writers supply names and unlock lines; placeholders until then.
- **`/stats`** keeps the raw figure and gains *"Your relationship is currently negative / positive / very strong"* for below zero, above zero and 100-or-more.
- **The two petting achievements are one fork at pet 200**, not two tallies of qualifying pets. The comparison operators stay as built; the sign is read on the score **after** that pet. Two implementation notes: the check must be *"200 or more and neither held"* rather than *"exactly 200"*, so a missed write cannot lock a player out forever; and the fork is mutually exclusive, so no player can ever hold both.
- **The public pet line reports the individual pet's reaction**, branching on the mood roll rather than on the meter. This reverses what 2f recommended and the code implements, and it dissolves the zero-boundary problem rather than needing a fix for it. The two strings want renaming to `pet.public.friendly` and `pet.public.standoffish`, since their current names describe the relationship.
- **Phases 2a through 2f are all done**, 2d with seven knowingly dormant achievements. There is nothing outstanding to split between releases — which changes V3's character completely, see below.

### Settled since: the drift, zero, gating, and five achievements with final text

- **The drift applies only on days a player does not interact with the cat at all**, and interaction widens from petting to **petting, the toy, the bed or feeding**. Implementation: one `last_cat_interaction_date` per (player, server), stamped by all four, read by the nightly job — not four branches in the decay query. **Attempts count, not just successes**, since the toy's first offer is a guaranteed refusal and the bed refuses inside its window.
- **`/stats` at exactly zero** reads *"The cat doesn't seem to care about you."* Four bands with that one.
- **Deregister locked commands.** Per-guild registration makes this cheap and per-server — see the note below.
- **Seven achievements, with final unlock text and all three quest prompts**, three of them live from drop 0. The drop schedule carries the table, the ids and the copy. Every public quest is gated on *Making First Contact*, which is secret — so a new player's quest log is deliberately empty until they have earned something, then fills.

### Nothing is left blocking the V3.0 spec

The list has emptied out. Taking them in order of how they closed:

- **The drift's middle band was never a problem.** *"Go straight to 0"* and *"move 10 toward 0"* are the same rule — checked across the whole −100 to +100 range, the built behaviour reduces to `max(0, score − 10)` above zero and `min(0, score + 20)` below. Finding withdrawn.
- **The existing test-server rows get reset**, so the start-value change carries no migration.
- **The quest notice rides the first private cat message** after a quest becomes visible, computed lazily rather than tracked as an event — which covers both the achievement case and the overnight drop-advance case in one code path.
- **The crowding nudge fires on the first 0% pet.**
- **`/start-game` and `/advance-game`** are named and their semantics are recommended; the second-run and backwards cases are the last detail and the spec can state them.
- **Feeding is deferred.** It is unreachable before drop 3, so it belongs to V3.2 rather than to the first spec.

### Two small decisions, both inside V3.1

> **Both have since been decided, and so have the two defaults below.** The bed ships in drop 1 and the toy in drop 2, with the bed a fixture; *Impressively Bad Luck* is four refusals running at 9.4%; the toy ramp resets on success and attempts inside the cooldown do not advance it. The Phase 3b Work Order §3 carries the ramp rules and the drop schedule carries the swap. The two items are kept here because the reasoning is still the clearest statement of why.

1. **Bed first or toy first in drop 1?** The bed is the better lesson and the toy is the better engine — see the schedule. Recommended: bed first, with the toy's first refusal rewritten to invite a retry.
2. **Does *Impressively Bad Luck* become four refusals rather than five?** Five is arithmetically impossible — the ramp guarantees the fifth attempt succeeds — and four carries a 9.4% chance, which is a good rarity for a secret row.

Plus two that the spec can simply state a default for: what fills *"Items here:"* when the channel is empty, and whether the toy ramp resets after a success with cooldown attempts not advancing it (recommended yes and no).

### Three things the five achievements add to the build

**An `on_relationship_change` hook.** Three achievements are now score thresholds — 50, 100 and 250 — and four actions write the score. *Cat's Best Friend* listens on `on_pet`, which was enough when petting was the only lever; a player pushed to 50 by a bed fluff would go unchecked. Fire the thresholds wherever the score is written.

**`requires` stays single-valued — retracting a finding.** I said it needed any-of semantics, because *A Paw in the Door* was to be visible after *Making First Contact* **or** *Fluffed to Perfection*. Now that *Fluffed to Perfection* requires *Making First Contact* itself, anyone holding it holds the root, and the disjunction collapses. All three public quests are rooted at one achievement, so `requires` is one id and the drop condition rides on `since_drop`, which already exists. Worth protecting: the first quest needing two unrelated prerequisites brings the resolver back.

**The quest columns move from V3.2 into V3.0.** A public achievement with a visibility prerequisite *is* the quest system — `offered`, `requires`, `prompt`, and `/stats` rendering open goals. A minimal version is now drop-0 content rather than later work. All three prompts are written.

### Per-guild registration answers both gating worries

**Different servers can sit on different drops.** Discord registers commands either globally — every server the bot is in — or per guild, against one specific server id, and each guild's set is independent. Server A on drop 1 and server B on drop 4 each get their own registered list. It is the same mechanism the QA commands use to exist only on the two test servers.

**And the hour-long delay does not apply.** The up-to-an-hour propagation is a property of **global** commands, which Discord caches aggressively. **Guild command updates land in seconds.** So advancing a drop shows the new commands effectively immediately.

Two consequences. **Every player command has to be guild-registered rather than global** — if the bot registers globally today, that is the change, and it means registering on guild join as well as on every advance, so the bot needs to know every guild it is in. And **use the bulk-overwrite endpoint**, which replaces a guild's whole command set in one call, rather than creating and deleting commands individually; it keeps each advance to one request per guild and stays clear of per-command create limits during `/qa-drop` churn in testing.

### Not blocking — the spec can name these as pending

Writer copy for the two new achievements, the `/help` drop-0 sections, and the achievement calendar now that a winter-solstice repair is in play. The four thread-behaviour verifications are also off the critical path entirely: drops 0 through 2 have no rooms, so nothing in V3.0 or V3.1 touches thread membership.

**One thing to check rather than decide:** the current values of `pet.public.positive`, `pet.public.negative`, `pet.public.continues` and `pet.crowding` in the repo's `defaults.tsv`. 2f specified them and the developer implemented 2f, but the copy of `defaults.tsv` in the project files predates that work and does not contain them, so the authoritative wording is in the repo and nowhere else we can see.

### What changed shape: V3 modifies built behaviour rather than building features

With 2a through 2f all done, V3 is not a construction project with a gating layer on top. **It is a gating layer over a finished game, plus a meter rework, plus the toy and the bed.** That is a different and smaller thing than this plan was originally scoped against, and three consequences follow:

- **The riskiest work is now subtraction.** Nine rooms, nine commands and 35 achievements exist and work. Drops 0 through 2 have to *hide* almost all of it, and the leak test in the acceptance pass stops being a nice-to-have — it is the main way this release can fail.
- **The drop gate has to sit in front of commands, not just content.** Text resolution already filters by `since_drop`. A command that is not yet unlocked has to refuse, or not be registered at all, and registering per drop is cleaner than refusing but means re-registering on every advance.
- **Nothing in 2e or 2f needs splitting.** `/enter`, the tutorial, the art set, the pet refinement and the achievement announce format are all built. They need gating to the drop that should own them, which is a config question rather than a work order.

## The shape of it

Four releases, and a design track running alongside that does not block the first two.

| Release | Ships | Needs | Earliest |
| --- | --- | --- | --- |
| **V3.0 — The Cat** | Drop 0: Halloween channel, cat, no rooms | Nothing that is still undecided | Days, not weeks |
| **V3.1 — Playing and Caring** | Drops 1 and 2: cat toys, cat beds, still no rooms | The meter rework, and the channel as a room | Right behind V3.0 |
| **V3.2 — The Door** | Drop 3: one room, the first quest | The tutorial-quest design, and the gating decision | After testers have lived in V3.1 |
| **V3.3 — The House** | Drops 4 through 7 | Bolding, autocomplete, fragments | The expensive one |

The reason this split works is that **drop 0 removes rooms rather than adding anything.** V2 already has nine working rooms. V3.0 is mostly gating, polish and a test harness, which is why it can start today against zero open decisions.

**The toy and bed drops bought the design team a week, and that is their second-biggest benefit.** The tutorial-quest design and the per-player gating decision were the critical path into the first room. With V3.1 sitting between the cat and the door, those decisions now have a whole release of runway that did not exist before — and V3.1 itself is blocked on one balance call rather than on a design programme. Taking the slot deliberately is worth more than filling it faster.

---

## Build in this order

### 1. The test harness, first — not last

You asked for drop-forcing commands as an element of V3. They should be the **first** thing built, because without them the rest of V3 cannot be checked at all:

- Drop 0 content becomes unreachable the moment the server advances to drop 1. Testing it afterwards requires going back.
- Drop 3 cannot be validated before it opens, which is the whole point of a staged schedule.
- The toy ramp is random, the toy cooldown is ten minutes and the bed cooldown is a day. None of those three can be exercised honestly without being able to set state and move the clock.
- Seven achievements are gated on fixed dates — 1, 2, 15, 21 and 25 October, plus any Tuesday. Without a clock override they are testable only on the day, once.

Half of this is already anticipated: the Functional Spec says a `server_config` override or a manual drop "can force one early for testing, while the calendar stays the source of truth for dated ones." So the core mechanism is a config key, not a new command.

### 2. One clock function, before anything else reads the clock

**Route every time-of-day read through a single `server_now()`.** Nothing else calls the system clock — not the midnight job, not the date-gated achievements, not the restock day counter, not the 19-hour Pacific windows.

This is a one-hour change today and a week of hunting later. It is also what makes a single `clock_offset_days` in `server_config` test every dated behaviour at once, coherently, rather than needing a separate override per feature. Do it in the first commit of V3.0 even though the override itself can come later.

### 3. Then the five workstreams below, in parallel

---

## Six workstreams that can start now

### A. Drop machinery and the test harness — one developer, first

Blocks B, D, E and F, so it goes first and alone.

- `server_now()` and the `clock_offset_days` override
- A `current_drop_override` key in `server_config` that wins over calendar arrival
- Drop-aware resolution exercised end to end: `(entity, state, since_drop)` at the highest *arrived* drop
- **The Halloween channel becomes a room-like row** — no exits, never listed, never reachable by movement. Three drops now happen in a place the room model does not contain, and `/pet` already special-cases it. Doing this in V3.0 means workstream F writes no new resolution path at all; leaving it means a parallel one for toys and beds. Cheap now, and it also retires an existing special case.
- **Incremental initialization.** `/initialize-haunted-house` currently builds nine threads in one call. Drops 0 through 2 have no rooms, drop 3 has one, drop 5 adds four. It becomes either per-drop or a single command that opens whatever the current drop entitles.
- The QA command set (specified below)

**One decision needed before this starts, and it is a one-liner:** `achievements.tsv` has `since_drop = 1` on all 35 rows and `drops.tsv` has a single launch row. If launch is now drop 0, either the files renumber or drop 0 maps to `since_drop = 1`. Settle it this week; the whole harness keys on it.

**Settled 21 October: drops count from 0.** Launch is drop 0, and drop 1 begins the moment the cat bed appears. So the files renumber; mapping drop 0 to `since_drop = 1` is off the table. `drops.tsv` needs a drop-0 row, and **`achievements.tsv` needs a real `since_drop` on every row** instead of 1 on all 35 — an achievement left at 1 cannot be earned at launch, which would hide every petting achievement for the whole of drop 0.

**The renumbering is in `achievements_since_drop.tsv`**, one row per achievement — the 35 original rows plus the ten added since — joined on `achievement_id`. Each value is the earliest drop where the trigger can actually be met. All six petting achievements are 0. Blocked achievements get 99 so they never surface as open quests until something schedules them. Two findings came out of it:

- **Six dated achievements could not be earned this year. Settled 21 and 30 October: none of them is dated any more.** *Brewing Trouble* and *Trash Panda* (1 October), *Self-Reflection* (2 October, and it was called *Say Cheese*), *Green Thumb* (15 October), *Nacho Average Ghost* (21 October) and *Using Your Noodle* (25 October) all needed rooms that open at drop 20 or later, after their dates had passed. Four are now "this thing, any day"; *Green Thumb* is three parts in any order; *Trash Panda* waits on a trash can that holds items. The writers' decision is in `Date-restricted achievements.md`, which is authoritative for which achievements check a date.
- **`cats_best_friend` still says *a perfect relationship*,** which stopped being true when the meter lost its ceiling.

### B. Thread hygiene — small, independent, must precede drop 3

Nothing here is undecided and none of it waits on A.

- `invitable: false` on every room thread, set at creation and patched onto the nine that exist
- A `THREAD_MEMBERS_UPDATE` handler enforcing *if someone was added to a room thread and the game does not say they are there, remove them*
- Membership is not authority: a command whose `channel_id` is not the player's `current_room` is refused ephemerally and in character
- Mention-add for arrivals, once the four verifications below come back
- **Threads must not be created until the drop that opens them.** Discord archives threads on inactivity and shortens the timer as a server approaches its thread limit. Nine threads created at drop 0 and first used at drop 3 — now three room-less drops away, likely two weeks or more — are nine archived threads. This is why incremental initialization is a V3.0 requirement rather than a later nicety — and it lands in the same commit as `invitable: false`, since both are arguments to thread creation.

### C. Content passes — writers only, zero engine, fully parallel

None of these touch code and none of them block on anything. They can all run during V3.0.

- **Refusals name the verb that would have worked.** \~40 `take_fail` and `use_fail` strings, with the three constraints already recorded: never name an unlocked-later verb, never name one that reveals a secret, only redirect where a verb actually applies.
- **Exit prose and aliases.** Already drafted — nine room rows revised, ten alias additions, one removal. This is review-and-merge, not authoring.
- **Present tense everywhere.** Leaving, taking, dropping, repairing, petting.
- **Character names out of early prose, exposition in.** David gets introduced before any flavour text assumes him.
- **Scenery lines.** The house-wide default ships first; per-room entries fill in one noun at a time.
- **`/help` sections, drop 0 first.** Three sections, one screen, and the one place that says slash commands exist and how to find them.
- **Fragmenting room text.** The existing paragraphs split cleanly at sentence boundaries, and the Entryway's two near-identical states collapse into shared sentences plus two gated fragments. The constraint for writers: every fragment must read correctly when its neighbours are absent, and must not reach backwards.

### D. Interface engine — needed for drop 3, not before

Starts now, ships with V3.2 and V3.3. Nothing in drops 0 through 2 needs it, which is more runway than it had.

- Engine-derived bolding
- Scenery resolution, with the per-entry response column present from the start even while empty, and the article stored rather than derived
- `/go`, exits and room names only, with the disguised-exit rule: `/go cabinet` returns the cabinet's own `use_fail`, and `/go secret library` fails exactly the way `/go dungeon` fails
- Autocomplete scoped per verb, listing only discovered destinations

### E. Quest schema — the parts that do not wait on the writer pass

The judgement calls are blocked. The plumbing is not.

- The `on_look` hook, which the dispatcher does not have today and which *Follow Your Nose* already needs
- `prompt`, `requires` and `offered_by` added to `achievements.tsv` as nullable columns
- `/stats` rendering open quests alongside earned achievements

Adding empty columns now costs nothing and means the writer pass, when it lands, is a content change rather than a migration.

### F. The toy, the bed and the meter — V3.1

> **This is the earliest sketch of the toy and bed, and five of its bullets have since been superseded.** The bed shipped in drop 1 as part of Phase 3a. The toys are Phase 3b: **two** rows, `feather_wand` and `crinkle_ball`, with real ids rather than a generic `cat_toy`, and **one** restock row drawing from the class rather than two rows. Phase 3b carries **three** achievements, not four — *Fluffed to Perfection* belongs to 3a. The two "one-character achievement fixes" are **withdrawn**: the two petting achievements became a single fork at pet 200 and the comparison operators stay exactly as built. *"The decay function is now the balance lever"* is **also withdrawn** — the drift is skipped on any day with a cat interaction, so there is no equilibrium to tune. And the three devotion achievements at 250, 500 and 1,000 were replaced by *Favorite Human* at 250, with the other two held in reserve. Everything else below — the ramp, the cooldown, the bed's Pacific day, the three player columns, the start value and the clamp — stands, and the Phase 3b Work Order implements it.

Everything here waits on A for the channel-as-a-room change. Nothing else is blocked.

- **Two things rows**, `cat_toy` and `cat_bed`, in the channel. `max_per_player = 1` on the toy; the bed is a shared fixture.
- **Two restock rows.** Random appearance is already built — `restocks.tsv` carries `times_per_day`, `window_start`, `window_end`, `every_n_days` and a `config_key`. Toys and beds are rows pointing at the channel, so the spawn rate is an admin-tunable number on day one rather than a deploy. **No new scheduling code.**
- **Three columns on the player row:** the toy ramp counter, the toy cooldown expiry, the last bed fluff. These are the first per-player values that are not booleans — the existing states (`library_found`, `drawer_unjammed`) are flags, and the Functional Spec declined a general per-player table on purpose. Three columns is proportionate; a fourth and fifth would mean revisiting that.
- **The ramp, precisely:** 0% on the first attempt, +25pp per attempt, reset to 0 on success, 10-minute cooldown after success, and **attempts during the cooldown advance nothing**. That last clause is what stops a player banking five refusals during the cooldown and converting the instant it lifts.
- **The bed:** one fluff per player per Pacific day, which shares a boundary with the midnight job rather than inventing a rolling window.
- **Four new achievement rows**, all on `on_use`, which already exists. No new hook — unlike the quest work in E.

**And the meter rework, which is where the care is needed.** Starting at zero with no ceiling closed the balance problem outright — the toy and bed keep +10 and +15, and nothing needs rescaling or capping. But it is a change to a number that several other things already read, and the parts are small enough to lose:

- **Start value 0**, and **no upper clamp**. Check what writes to the score today and whether anything clamps at 100.
- **Keep the lower bound.** Recommended: decay stops at 0 and only deliberate acts go below, down to the existing −100. Unbounded decay makes a month away unrecoverable.
- **The decay function is now the balance lever**, because with no ceiling the score settles where daily gain meets daily decay. Flat decay stops meaning anything as the number climbs; proportional decay makes the score a measure of recent devotion and makes 500 or 2,000 both reachable and earned. Whatever is in the code was written against a 100-point ceiling.
- **Two one-character achievement fixes.** *Making Friends* becomes pets at `>= 0` and *Trying to Make Friends* pets at `< 0`. The Achievement Trigger Spec's 27 September decision justified the current asymmetry on the premise that "every player begins at 50" — with a zero start, the two achievements reward the opposite of what their names say. `relationship_at_pet` means both can be recomputed rather than reset, which is the payoff for a column the spec argued for on exactly this ground.
- **`/stats` shows a tier and a figure, not a bar.** There is no maximum to fill a bar against.
- **Three devotion achievements** at 250, 500 and 1,000, secret rather than public. Without them the uncapped meter has no destinations above 100.

**Two documents now carry statements that are false**, and both should be edited rather than mentally corrected: the Achievement Trigger Spec's boundary rationale, and the Story Bible's "a perfect relationship is 100".

---

## The QA commands

**Register them guild-scoped on the two test servers, never globally.** Discord lets a bot register a command either *globally* — every server it is in — or *per guild*, meaning for one specific server id. A guild-scoped command exists only there: it appears in that server's slash menu and nowhere else, and it is a different registration call rather than a permission setting, so there is nothing for a player in a real server to discover, type or guess. "Staging guild" just means a server used for this and nothing else; **the two test servers already in use are the staging guilds**, `1542854260524453978` and `1548007001915658250`. Register the QA set against those two ids and the question is closed. Gate them to a QA role on top of that, since anyone in a test server can still see what is registered there. Every call replies ephemerally and writes one line to a log channel, so nobody silently corrupts state and forgets.

Prefix them all identically so they group in the slash menu.

| Command | Does | Why it is needed |
| --- | --- | --- |
| `/qa-drop <n>` | Jump the server to any drop, forwards or back | Pre-validate a drop before an admin advances to it. Distinct from the player-facing `/advance-game`, which only ever goes forward by one |
| `/qa-clock <+n days \| reset>` | Offset `server_now()` | Seven date-gated achievements, the midnight job, the restock day counter, the overlapping Pacific windows |
| `/qa-reset-player <member>` | Wipe one player's room, inventory, achievements, relationship and tutorial flag | **The most valuable one.** The first five minutes can otherwise be tested once per human |
| `/qa-reset-server` | Back to pre-initialization | A clean run of the whole schedule |
| `/qa-midnight` | Fire the daily job now | Bottle scatter, craving roll, restocks |
| `/qa-teleport <member> <room>` | Move a player without an exit | Reach the Secret Library without solving it |
| `/qa-state <member> <key> <value>` | Set a per-player or server state | `library_found`, `drawer_unjammed`, `stairs_repaired` |
| `/qa-grant <achievement> [member]` / `/qa-revoke` | Award or remove | Check announce copy without reproducing the condition |
| `/qa-spawn <thing> [room]` | Place a thing | Build an inventory for *Charcuterie Board* or *Bulk Buyer* without farming |
| `/qa-inspect <member>` | Dump a player's full state | Diagnose rather than guess |
| `/qa-cooldown <member> clear` | Clear the toy and bed cooldowns, and the 10-minute pet window | Ten minutes and a day are both too long to sit through on every run — and the pet window is what makes the mood roll and the crowding penalty testable |
| `/qa-relationship <member> <n>` | Set the score directly | Reaching 100 honestly takes days. *Cat's Best Friend*, the new 50 achievement, the three `/stats` bands and both pet-line branches are all one call each with this |

**The toy ramp needs no command of its own**, provided `/qa-state` can write it: setting the ramp to 4 makes the next attempt a guaranteed success, and setting it to 0 replays the guaranteed first refusal. That is the whole mechanic exercised in two calls, which is the argument for making `/qa-state` generic rather than a fixed list of flags.

Two notes on `/qa-drop`. **Going backwards does not undo play** — rolling from drop 4 to drop 3 re-hides content but does not un-take items or un-earn achievements, so a backwards jump should say so in its reply. And a forced drop must be *visibly* forced: `/qa-inspect` and the log line should both show that the pointer is overridden, or someone will spend an afternoon debugging a server that is simply not where they think it is.

> **Phase 3b adds three requirements to this set.** `/qa-cooldown ... clear` must also reset the toy ramp, not just the cooldowns; `/qa-reset-player` must clear the three new player columns, `last_bed_fluff` and the hints-shown rows, or the six-rung ladder is testable once per human; and the play history needs a write path — either `/qa-state` sets the play count or it inserts `thing_uses` rows — because *Tireless* otherwise costs twenty-five successful plays per test run. The work order §11 carries all three.

---

## The per-drop acceptance pass

The commands are the tool; this is the routine they serve. Run it on staging before each drop opens.

1. `/qa-reset-server`, `/qa-drop <n>`, `/qa-clock` to that drop's date
2. `/qa-reset-player` on a tester, then walk the drop's full command list
3. Confirm every thing, room and help section the schedule promises for drop N is reachable
4. **The leak test, which is the one that matters.** Confirm nothing from drop N+1 is reachable *or mentioned*: `/help` names no later command, autocomplete offers no later noun, no room description names a later thing, no refusal points at a verb that does not exist yet.

Point 4 is the test that would have caught what the playtesters hit. Everything else confirms the drop works; the leak test confirms the drop is *small*.

---

## Do not start these yet

> **Three rows below have since closed.** The decay function is kept exactly as built, with the drift skipped on any day with a cat interaction — there is no equilibrium to tune, so it is not a V3.1 decision at all. Relationship meter visibility is settled at four `/stats` bands with the raw figure still shown. And the crowding nudge is answered: the 14 October audit confirms rapid petting does cost score, so the warning is honest, though it fires five pets after the damage starts. The paragraph after the table still argues the decay function is the last open call in V3.1 — it is not.

Each is blocked on a decision, not on effort. The "needed by" is what makes them urgent or not.

| Blocked | Waiting on | Needed by |
| --- | --- | --- |
| The decay function | Flat or proportional, at what rate, and flooring at 0 or −100 | **V3.1 — with no ceiling, this is the only thing setting where a score settles** |
| Tutorial quests, the five solo quests | The onboarding-corridor design | V3.2 |
| Per-player `present_when` across all content | Permanent gating, or corridor-then-graduation | V3.2 |
| Quest prompts | The writer pass over `kind`: which of the 14 public rows become secret | V3.2 |
| Drop exit criteria | How long each room-less drop runs, and what advances it | During V3.0, before drop 0 ends |
| Relationship meter visibility | Decision | V3.0 — it is drop 0 content |
| The crowding nudge | Whether rapid petting actually costs score in v1 | V3.0 |
| `/help` beyond drop 0 | Who writes it, and whether it lives in `defaults.tsv` or its own file | V3.1 |

**Two of these are now urgent rather than merely open.** The meter's visibility is settled in substance — with three mechanics feeding it and decay pulling it back, a hidden score makes the pre-house phase illegible — so what is left is the tier naming, which is a writer task. The petting verification is a code read rather than a decision. The decay function is the one real decision left in V3.1, and unlike the balance call it replaced, it does not block the workstream: the toy and bed can be built against whatever decay exists today and retuned after.

The compensation is that the three genuinely hard design questions — the corridor, the writer pass, the quest prompts — all moved from V3.1 to V3.2. They have a release of runway they did not have before.

---

## Four verifications, one afternoon

All four are thread behaviour the docs do not state outright, and all four gate work in workstream B.

1. **Answered by testing, 15 October — a mention does add silently.** A normal member mentioning another member added them to the thread with no system message of any kind: no "{username} added {newuser} to the thread" line, no `RECIPIENT_ADD`. The mechanism we want therefore leaves no trace in the transcript. One residue goes into question 2: the bot adds while holding `MANAGE_THREADS` rather than as an ordinary member, and a privileged add is a different code path from the one that was tested.
2. **Answered by testing, 26 October — a privileged mention adds silently too, and it is now the mechanism.** Two private threads, both `invitable: false`, bot holding `MANAGE_THREADS`: the mention added the member with no system message of any kind, while `add_user` in an identical thread posted `RECIPIENT_ADD` — "Black Cat added <player> to the thread". The control is what makes the silence trustworthy, because it proves the check could see such a message at all. Shipped in PR #85: the arrival line in `_use_exit` is what admits the player, and `add_user` is gone from the move path. `/enter` still uses `add_user`, because its only player-naming line goes to the channel rather than into the thread.
3. **Not answered, and no longer load-bearing.** The arrival line is sent with the default `allowed_mentions` on purpose: suppressing the ping, or routing it through `_post_quietly`, strips the mention that does the admitting. The question only returns if something later wants an arrival that does not ping, and the answer would have to be found before suppressing anything.
4. **Answered by testing, 26 October — and the asymmetry runs the opposite way to the add.** A *bot* removing a player is not silent: `remove_user` posts `RECIPIENT_REMOVE` — "Black Cat removed <player> from the thread" — in the room they left. A player **leaving by hand is** silent: the thread drops them from its member list and posts nothing at all. So on the way in the bot has the quiet option and the player does not; on the way out the player has it and the bot does not, and nothing in the API lets the bot ask for a leave on somebody's behalf.

**Net effect on the out-of-game lines, as shipped.** A move used to produce two system messages: an add in the room entered, a remove in the room left. It now produces one, in the room left, below the departure line the game writes. There is no silent removal to match the silent add, so cutting the last one would mean not removing players from rooms at all — which is the thing the room model is for. A player can leave a room quietly of their own accord, per 4, but that is theirs to do and not something a move can call.

Plus two that are not about threads:

- **Does rapid petting cost relationship score in the v1 code?** The crowding nudge currently warns about a penalty no document defines.

**And one that is now answered rather than outstanding:** what writes the relationship score, whether it clamps, and what the decay does. The developer's 14 October audit covers all of it with line references — range, start value, mood roll, the per-pet expected values, the nightly drift, every reader. The drop schedule's meter section reconciles it against the three changes we want and names the four places they collide. **The audit also closed the crowding-nudge question: the penalty is real**, so the warning is honest, though it fires five pets after the damage starts.

---

## What this gets you

**Testers see something new in days, not weeks**, because drop 0 is a subtraction from a working game plus a harness.

**And then something new again a few days after that.** V3.1 is three things rows, one restock row, three player columns and four achievements across drops 1 and 2, on top of machinery V3.0 already built. It is the cheapest release in the plan and it is the one that gives the pre-house weeks a reason to exist.

**The design track stops being the critical path.** The corridor design, the writer pass over `kind` and the quest prompts now have until V3.2, with two shipped releases in front of them, so that time is free rather than borrowed.

**Every later drop gets rehearsed before it ships.** That is the harness earning its place, and it is the reason to build it first rather than when someone finally needs it.

**The risk to watch is V3.3.** Bolding, autocomplete, generalised `present_when` and fragmented room text are all in it, drops 4 through 7 all depend on it, and it is the only release with no natural way to cut scope. If it slips, drop 5 opens four rooms at once without the interface work that makes four rooms survivable — precisely the flood the playtest produced. Worth deciding now that **drop 5 waits for V3.3** rather than discovering it in week five.

**The second risk is subtler and worth naming.** Three room-less drops is a long time for a game whose selling point is a haunted house. The toy and the bed make that stretch worth playing rather than worth waiting through, but only if the relationship is legible — which is why the meter display stopped being cosmetic. The uncapped, decaying, zero-start meter is the right shape for a multi-week phase: there is always somewhere further to go and always a reason to come back tomorrow. It only works if a player can see where they are, which makes the tier naming a launch-blocking content task rather than a polish item.
