# Telemetry and tuning

*Asked 21 October: capture every tuning-relevant interaction. Two tables — a versioned config history, and an interaction log.*

## Decided 21 October

All the additions below are accepted, and `pet_events` is retired. The rest of this tab is the reasoning.

### `config_history`

| Column | Notes |
| --- | --- |
| `guild_id` | Per server |
| `key` | One tuning value per row |
| `value` |  |
| `effective_from` | Written through `server_now()` |
| `effective_to` | Null on the live row; windows never overlap per `(guild_id, key)` |

This **is** the live config, not a journal beside it: the current value is the row whose `effective_to` is null.

### `interaction_log`

| Column | Notes |
| --- | --- |
| `id` | Monotonic, so events in the same second order correctly |
| `guild_id` |  |
| `user_id` | Null for system rows |
| `actor` | `player` or `system` — the nightly decay is a system row |
| `action` | `pet`, `use`, `take`, `drop`, `look`, `decay`, `hint`, `unknown_noun`, and so on |
| `thing_id` | Nullable |
| `outcome` | `success` or `refused` |
| `reason` | On a refusal: `not_hungry`, `cooldown`, `requires_missing`, `crowding`, `wrong_room` |
| `relationship_delta` | 0 on a refusal |
| `score_after` | The player's score once this row applied |
| `drop` | The server's drop at the time |
| `detail` | Nullable text: the hint rung for `hint`, the typed noun for `unknown_noun` |
| `created_at` | Through `server_now()` |

**`pet_events` is retired.** The mood roll reads pets in the last ten minutes from `interaction_log` instead, which is the same query with a filter on `action`.

**Nothing is lost by retiring it.** `relationship_at_pet`, which *Making Friends* and *Trying to Make Friends* were built on, is `score_after` minus `relationship_delta` on the same row, and a player's pet count is a count of their `pet` rows.

### Tuning values to move into config — approved 21 October

Move a value if you could plausibly change it during the beta because of what this log shows. Keep it in code if changing it mid-season would be unfair to players who already earned something under the old value.

**Move now, ahead of drop 0** — petting is the only mechanic at launch, so these are the entire balance:

- Base pet success chance (80%)
- Chance lost per recent pet (10 points)
- Recent-pet window (10 minutes)
- Score change on a friendly pet and on a standoffish one (+5 and −5)
- The decay rate and floor — the real balance lever once the meter has no ceiling

**Move before each value's drop:**

- Drop 1: the bed's fluff limit (once per Pacific day)
- Drop 2: toy ramp start and step (0%, +25 points), toy cooldown (10 minutes), toys present (2, already in `server_config`)
- Drop 3: hunger window (8 hours)

**Keep out of config:** achievement thresholds — 200 pets, 25 plays, 4 refusals, the 250/500/1,000 devotion marks. Lowering one mid-season hands it to some players more cheaply than others got it.

**The relationship deltas have a wrinkle.** If they live in the proposed `relationship_delta` column on `things.tsv`, they sit in a content file, and `config_history` will not see them change. Fix it with one more key: record a **content version** — a commit hash or file checksum — as a `config_history` row on every content deploy. That dates every TSV change at once, the deltas, `restocks.tsv` and all the copy included.

## The short answer

Both tables are the right idea, and the config history is the better half — it is the one people skip and then regret. The interaction log is four fields short of answering the questions as stated, one existing table should be absorbed rather than duplicated, and two cheap additions would answer things the proposal cannot reach at all.

**The framing behind every call below: you can always throw rows away, and you can never recover a field you did not write.** This is a bot on a friends' server — the volume will be trivial, so the only real risk is a missing column. Log generously.

## The config history: yes, and make it the source of truth

It matters more than it looks, because every number in the interaction log is uninterpretable without it. *Players pet forty times a day* means nothing unless you know what the per-pet values and the decay rate were that week — and the whole point of moving `relationship_delta` into `things.tsv` is to make those change often.

- **Per server**, as proposed. Servers sit on different drops and will be tuned independently.
- **Narrow rather than snapshots.** One row per `(guild_id, key, value, effective_from, effective_to)`, not one row per whole-config snapshot. A snapshot table answers *what was the config on 14 October* more directly; a narrow one answers *when did decay last change*, survives a single-value edit without rewriting the set, and joins per key to each logged event. Narrow wins, and the snapshot question is just a group-by.
- **Non-overlapping windows per `(guild_id, key)`**, with `effective_to` null on the live row.
- **Make it the source of truth rather than a journal beside one.** If `server_config` holds the live value and this table records changes to it, the two will drift — and the drift will be silent and will only be noticed while analysing something else. Instead the live value *is* the row with a null `effective_to`.
- **Write the timestamps through `server_now()`**, per the single-clock rule, or the QA clock offset makes the history incoherent the first time anybody tests a dated behaviour.

## The interaction log: right shape, four fields short

Proposed: player, action, timestamp, relationship impact. Taking the stated questions one at a time:

**"How frequently people are *trying* to pet the cat" needs an outcome.** A refusal carries an impact of 0, which is indistinguishable from a successful interaction that happened to score 0. Add `outcome` — success or refused — and `reason` on a refusal: not\_hungry, cooldown, requires\_missing, crowding, wrong\_room. Without the reason you can see players bouncing off the game but not off what, which is the half that tells you where to fix it.

**"Whether they are decimating their score" needs the resulting score, and it needs decay in the log.** Add `score_after`: one integer that makes every row self-describing, rather than a figure you can only reconstruct by summing deltas correctly from the beginning of time. And **the nightly decay has to be a row in this same table**, with the system as the actor — because across a multi-week release it is decay, not the expired can, that will actually be eroding people's scores. A log of player actions alone is blind to the main downward force in the game.

**Two more that cost an integer each.** `thing_id`, nullable — `action = use` says nothing without knowing whether it was the toy, the bed or the expired can, which is the entire tuning question. And `drop`, the server's drop at the time: joinable from the config history, but it is the most important slicer there is and storing it costs nothing.

Plus `guild_id`, and a monotonic id so events inside the same second order correctly.

## Absorb `pet_events` rather than sitting beside it

`pet_events` already logs every pet with a timestamp, is never pruned, and exists to answer *how many pets in the last ten minutes* for the mood weighting. That is this table's query shape with a narrower where-clause. **Have the mood roll read the interaction log and retire `pet_events`**, rather than keeping two overlapping logs that can disagree about the same event. The Code Audit notes that if the mood mechanic ever goes, `pet_events` goes with it; generalising the table makes that a non-question.

## Two additions worth more than anything in the proposal

**Log when a hint fires, and which rung.** The hint ladder is a bet about discoverability, and the copy deck already records the worry it cannot settle on its own: if a tester reads `cat_bed.look` and does nothing, the hint rail is covering for prose that did not land, *and we will not be able to tell which one failed*. Logging the rung is exactly what makes those two distinguishable — prose that works shows up as an action with no hint before it.

**Log the noun whenever `/look <x>` returns the unknown-noun refusal.** That is a free, ranked list of the things players expect and the game does not have. It is the trap problem the whole scenery design has been fighting, turned from playtest anecdote into data — and the first week on the beta server would probably say more about the channel than three more playtests.

## Three smaller notes

**Volume is not the risk, and should not drive the design.** Every pet, use, take and look from a few dozen people is nothing; partition by month if it ever becomes a question. The expensive mistake is the field nobody wrote, which is the same mistake as `earned_at` on `player_achievements` — both should land before the beta server starts generating rows worth analysing.

**Nothing here is new in kind.** The bot already logs every pet, and `/stats` plus the leaderboard already surface most of what this records, so there is no new consent surface beyond the one the leaderboard raises.

**It answers one question the proposal did not ask and should.** Retention across a staged release — how many players who arrived at drop 1 are still playing at drop 4 — falls straight out of this table as a min-timestamp per player, and it is the number that decides whether the three room-less drops were a good idea.

## Before beta: two more things

**The config history only sees what lives in config.** A value hardcoded in the bot is invisible to it, so a tuning change made in code leaves no trace and the interaction rows from before and after it cannot be told apart. Decide which tuning values move out of code before beta. Candidates: the toy ramp's start and step (0%, +25 points), the toy cooldown (10 minutes), the bed's once-a-day limit, the recent-pet window (10 minutes) and the mood weights, the decay rate and floor, the hunger window (8 hours), and the per-thing relationship deltas through the proposed `relationship_delta` column. Restock rates already live in `restocks.tsv`.

**Keep the two test servers out of the analysis.** QA commands set scores, shift the clock and reset players there, and none of that is real play. Tag those two guilds so their rows never mix with beta data.
