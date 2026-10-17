# V3 content file edit spec

Every change to the content files that Phase 3a assumes. No code in here — this is data only, and it should be applied and committed **before** the work order is started.

## Read this first

**Work from the repo, not from any copy of these files in the project doc.** The copies attached to the Halloween project are from late September and are demonstrably behind: they contain no `thing_text.tsv` at all, and no row for the cat as a lookable thing, which Phase 2f added. Everything below is keyed by **id and column name**, never by row number or column position, so it applies cleanly to whatever the repo actually holds.

**Verify before you edit.** Each section ends with an assertion to check. If one fails, stop and report rather than guessing — a wrong `since_drop` is the one error here that silently unlocks the whole game.

**Files touched:** `things.tsv`, `thing_text.tsv`, `achievements.tsv`, `defaults.tsv`, `drops.tsv`, and the rooms registry (wherever rooms are defined — if rooms live in code rather than a TSV, section 5 is a code change and belongs in the work order instead; say so rather than inventing a file).

---

## 1. The `since_drop` move — do this one first and carefully

**The problem.** Drop numbering now starts at 0, where drop 0 is the cat alone in one channel. Every existing content row carries `since_drop = 1` — 142 rows in `things.tsv`, all 35 in `achievements.tsv`, every row in `room_text.tsv`. Under the new numbering, the first `/advance-game` would not reveal a cat bed. **It would reveal the entire game**: nine rooms of things and 35 achievements.

**The fix is a bulk move, not a content pass.** Set every existing row to `since_drop = 3`, which is where the Entryway genuinely opens under the current schedule. Per-row accuracy for drops 3 through 7 belongs to whoever builds those drops; it is not needed now and guessing at it now would be worse than leaving it uniform.

### 1a. `things.tsv`

Set `since_drop = 3` on every existing row, **with one exception**:

| `thing_id` | `since_drop` | Why |
| --- | --- | --- |
| the cat's own row | **0** | `/look cat` arrives in drop 1 and resolves against this row, not against the petting code. Moving it to 3 makes the cat unlookable in the drop that introduces looking. |

**Find the cat's row by `room_id = ALL`.** Phase 2f added it with the cat omnipresent, the same way `alexa` is. If there are two rows with `room_id = ALL`, the other is `alexa` — leave that one at 3. If there is **no** row with `room_id = ALL` other than `alexa`, the cat's thing row was never added: stop and report, because `/look cat` is in the Phase 3a definition of done.

### 1b. `achievements.tsv`

Set `since_drop = 3` on all 35 existing rows. No exceptions. The three that are reachable in drop 0 — *Making Friends*, *Trying to Make Friends*, *Cat's Best Friend* — are **not** exceptions, because they fire on `on_pet` and `on_relationship_change` rather than being gated content, and their `since_drop` only controls whether the loader offers them. Set them to **0** if the loader uses `since_drop` to decide whether an achievement can fire at all; set them to 3 if it only uses it for display. **Check which, and say which you did** — this is the one ambiguity in the whole spec.

### 1c. `room_text.tsv`

Set `since_drop = 3` on every row. There are nine room ids — `BE CO DI EN KI LI NU SE UH` — and none of them exists before drop 3.

### Assert

- No row in any content file has `since_drop = 1` or `2` after this, except the new rows added below
- Exactly one `things.tsv` row has `since_drop = 0`, and it is the cat
- Setting a test server to drop 1 and running `/look` finds the cat bed and nothing else

---

## 2. `things.tsv` — the cat bed

One new row. Columns not listed are empty.

| Column | Value |
| --- | --- |
| `thing_id` | `cat_bed` |
| `name` | `cat bed` |
| `aliases` | `cat bed\|bed\|cushion\|cat cushion` |
| `type` | `fixture` |
| `room_id` | the Halloween channel's room id (see section 5) |
| `quantity` | `1` |
| `takeable` | `no` |
| `droppable` | `no` |
| `use_cooldown_hours` | `24` |
| `since_drop` | `1` |
| `sort_order` | next free value |

**On `use_cooldown_hours`.** If that column already means "per player, rolling hours" then 24 is correct as written. **The design calls for once per Pacific day, not a rolling 24 hours** — a rolling window punishes a player for fluffing early on Monday by pushing Tuesday's fluff later, and drifts across the week. If the existing column is rolling, leave it at 24 and raise it: the per-day behaviour is then a small code change in the work order rather than a data value, and it should not be silently papered over here.

**`takeable = no` is load-bearing.** `/take` does not exist in Phase 3a at all, but it arrives in drop 2 and the bed must refuse it then.

### Assert

- `/look cat bed` resolves at drop 1 and not at drop 0
- `/use cat bed` succeeds once, then refuses for the rest of the day

---

## 3. `thing_text.tsv` — the bed's strings

Three rows for `cat_bed`, in whatever shape this file takes for `look`, `use` and `use_fail`. A fourth is written for drop 2 and may be added now or then.

| Field | Text |
| --- | --- |
| `look` | A round cushion in dark green corduroy, flattened in the middle where something has slept. This is the sort of bed that looks plumpable. |
| `use` | You shake out the cushion and fluff it back into shape. The cat watches the entire operation, then walks over, turns around three times, and sits down without looking at you. |
| `use_fail` | The bed already looks fluffy and cozy. Your services are not required today. |
| `take_fail` (drop 2) | You get both hands under it before the cat claims it for her own. You leave it where it is. |

Copy exactly. These are final and reviewed; the full deck with statuses is the **V3 POC copy deck**.

---

## 4. `achievements.tsv` — three new columns, four new rows

### 4a. Add three columns

| Column | Type | Meaning |
| --- | --- | --- |
| `offered` | boolean, empty = false | Is this shown to the player as an open quest before they earn it |
| `prompt` | string, nullable | The prospective wording, shown while the quest is open |
| `requires` | one `achievement_id`, nullable | Must be held by that player before this becomes visible |

**Leave all three empty on the 35 existing rows.** A later writer pass decides which of them become quests; nothing in Phase 3a depends on it.

**`requires` is single-valued on purpose.** Every public quest is rooted at `making_first_contact`, so one id is enough. The moment a quest needs two unrelated prerequisites this becomes a resolver, so the tree stays rooted at one achievement.

### 4b. Add four rows

`sort_order` takes the next free values. `notes` is yours.

| `achievement_id` | `kind` | `name` | `unlock` | `since_drop` | `offered` | `prompt` | `requires` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `making_first_contact` | `secret` | Making First Contact | The cat let you pet her. Don't let it go to your head. | `0` | — | — | — |
| `a_paw_in_the_door` | `public` | A Paw in the Door | You've earned 50 relationship points with the cat. She has noticed you and has decided you may stay. | `0` | yes | Attain a relationship of +50 with the cat | `making_first_contact` |
| `favorite_human` | `secret` | Favorite Human | You reached 250 relationship points with the cat. She has stopped pretending she doesn't like you. | `0` | — | — | — |
| `fluffed_to_perfection` | `public` | Fluffed to Perfection | You fluffed the cat's bed to her standards. Well done. | `1` | yes | Give the cat a cozy nap spot | `making_first_contact` |

**No prompt carries a terminal full stop.** The quest notice interpolates the prompt at the end of its own sentence, so a prompt that punctuates itself would double the stop. The general rule: a string that gets interpolated into the end of another string does not punctuate its own ending.

### 4c. Three more rows, for drops 2 and 3 — add now or later

These are final copy but their content does not exist yet in the POC. Adding them now is harmless, since `since_drop` keeps them out of reach.

| `achievement_id` | `kind` | `name` | `unlock` | `since_drop` | `offered` | `prompt` | `requires` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `persuasive` | `public` | Persuasive | Tempted the cat into playing with a toy. | `2` | yes | Play with the cat | `making_first_contact` |
| `impressively_bad_luck` | `secret` | Impressively Bad Luck | The cat ignored your attempts to play four times in a row. | `2` | — | — | — |
| `bowl_half_empty` | `secret` | Bowl Half Empty | You fed the cat 25 times and she's still waiting for dinner. Keep going. | `3` | — | — | — |

**Four, not five, in *Impressively Bad Luck*.** The toy's ramp runs 0%, 25%, 50%, 75%, 100%, so the fifth attempt always succeeds and a run of five refusals has probability exactly zero. Four has a 9.4% chance.

### Assert

- The loader reads the file with three new columns without error
- All 35 pre-existing rows have `offered`, `prompt` and `requires` empty
- `a_paw_in_the_door` is invisible to a player who does not hold `making_first_contact`

---

## 5. The rooms registry — the Halloween channel

Phase 3a needs the channel to be a room-like place, because `/look` in drop 1 wants something to look at and the cat bed needs a `room_id`.

| Property | Value |
| --- | --- |
| id | `CH` (or whatever matches the existing two-letter convention — the nine rooms use `BE CO DI EN KI LI NU SE UH`) |
| exits | none |
| listed | never — it must not appear in any room listing or destination list |
| reachable by movement | never |
| `room_text` | **none.** `/look` there prints a list, not a description |

**No `room_text.tsv` row for `CH`.** That is deliberate, and it closes the question of what the channel's description says: nothing.

**If rooms are defined in code rather than in a content file**, this is not a data edit — stop and report, and it moves into the work order as a schema change.

---

## 6. `defaults.tsv` — the strings

### 6a. Two renames

| Old key | New key | Why |
| --- | --- | --- |
| `pet.public.positive` | `pet.public.friendly` | The line now reports the pet's own reaction, not the relationship. The old names describe the relationship and will be misread by whoever next touches them. |
| `pet.public.negative` | `pet.public.standoffish` | The same. |

The **text** of both is unchanged. Only the keys move. The code change that makes the line branch on the mood roll rather than on the meter is in the work order.

### 6b. New keys

Copy exactly. The full deck with triggers and statuses is the **V3 POC copy deck**.

**`/stats` relationship bands**

> **Superseded 17 October.** These four were applied, shipped, and
> replaced by nine after testing - four bands were wide enough that
> *"She tolerates you"* covered a score of 1 and a score of 99. The
> nine that replaced them, and the two new labelled lines, are in the
> **V3 POC copy deck**, which is the live source. The table below is
> kept as a record of what this spec asked for, not as copy to apply.

| Key | Text |
| --- | --- |
| `stats.rel.zero` | The cat doesn't seem to care about you. |
| `stats.rel.negative` | She has not forgiven you for something. |
| `stats.rel.positive` | She tolerates you, and occasionally more. |
| `stats.rel.strong` | She would notice if you stopped coming. |

**`/stats` structure**

| Key | Text |
| --- | --- |
| `stats.header.quests` | Open Quests |
| `stats.header.achievements` | Completed Achievements |
| `stats.achievements.empty` | No completed achievements. Try /pet. |
| `stats.quests.empty` | No open quests |

**On `stats.quests.empty`:** add the key, but the quest section is **hidden entirely** when a player has no open quests, so nothing reads it in Phase 3a. It is there because testing may say the absent section looks like a missing feature, and then turning it on is a condition rather than a new string.

**The hint rail.** Each renders as *Hint: &lt;text&gt;* in italics; the label is **not** part of the string.

| Key | Text |
| --- | --- |
| `hint.first_friendly` | This is your first achievement. Check /stats to see achievements and open quests. |
| `hint.first_standoffish` | Petting affects your relationship with the cat. Check /stats to view it. |
| `hint.something_new` | There is something new here. Try /look. |
| `hint.look_specific` | Specific things can be looked at. Try /look cat bed. |
| `hint.try_use` | Things can be used, too. Try /use cat bed. |
| `hint.try_look` | Things can be looked at, too. Try /look cat bed. |
| `hint.new_quest` | A new quest is available. Check /stats. |
| `hint.new_quest.named` | A new quest is available. {quest_name}: {quest_prompt} |

`{quest_name}` and `{quest_prompt}` map to the `name` and `prompt` columns on `achievements.tsv`, and follow the existing `{player}` token convention.

**The channel**

| Key | Text |
| --- | --- |
| `channel.look_prefix` | Items here: |
| `channel.look_empty` | Nothing here but the cat, and she was here already. |

**The drop announcement**

| Key | Text |
| --- | --- |
| `drop.1.announce` | The cat swats her paw and something slides a couple feet away...something that didn't appear to be here before now. |

One announcement string per drop, each able to carry that drop's hint. `hint.something_new` posts beneath this one, publicly, when drop 1 opens.

### 6c. One key to retire

The existing **welcome** string. Phase 3a ships with no welcome text and no tutorial — the hint rail and the gating replace both. The existing copy was written when "launch" meant the haunted house, and drop 0 has no house, no rooms and no `/enter` to mention, so leaving it in place is worse than removing it.

**Do not delete it. Comment it out or move it aside**, so the words survive for whenever a real public launch needs them.

### Assert

- No key in `defaults.tsv` still reads `pet.public.positive` or `pet.public.negative`
- Every key listed in 6b resolves
- Nothing in the codebase still looks up the retired welcome key

---

## 7. `drops.tsv`

The file currently holds a single `launch` row. It needs rows for drop 0 and drop 1 so the drop pointer has something to point at.

| `drop_id` | `trigger` | `date` | `event` | `name` |
| --- | --- | --- | --- | --- |
| `0` | admin | — | — | The Cat |
| `1` | admin | — | — | A Place to Sleep |

**No dates.** Drops advance by `/advance-game` only in Phase 3a; the calendar returns once a few servers have run and the pacing is known. If the existing `launch` row is referenced anywhere, reconcile it with drop 0 rather than leaving both.

### Assert

- A fresh server starts at drop 0 with no rooms and two player commands
- `/advance-game` moves it to drop 1 and refuses a second advance

---

## 8. Not in this spec, and not a data edit

**The pronoun sweep.** The cat is *she*, never *it*. This touches content files **and** code — pet blurbs, refusals, achievement text all carry a pronoun — and the known holdout is the existing `/look cat` description, which still reads *"It looks up at you with moonbright yellow eyes."* Do it as **one pass** across everything rather than string by string: a half-converted file looks finished, which is how the wrong pronoun survives to launch.

It is listed separately because it is a different kind of change from the rest of this file, and because it wants one commit of its own so it can be reviewed as a whole.

---

## Order of operations

1. Section 1 — the `since_drop` move, and verify nothing leaks before going further
2. Section 7 — `drops.tsv`, so there is a drop 0 to sit on
3. Section 5 — the channel as a room
4. Sections 2 and 3 — the cat bed and its strings
5. Section 4 — the achievement columns and rows
6. Section 6 — the strings
7. Section 8 — the pronoun sweep, as its own commit

Section 1 is the one that matters. If it is wrong, every test after it passes for the wrong reason.
