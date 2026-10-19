# Drop 2 content file edits

*Companion to the Phase 3b Work Order, in the same form as the 3a content edit spec — written to be run through Claude Code rather than read. Apply in the order below.*

**Two ids in here cannot be literals.** The Halloween channel's room id is whatever symbolic id 3a assigned to the channel row — **not** a Discord channel id, which is per server and set by `/start-game <channel>`. It appears in two places below, written as `<CHANNEL>`.

## Order of operations

1. `drops.tsv` — the drop 2 row
2. `restocks.tsv` — one renamed column, one new column, one new row
3. `things.tsv` — the two toy rows
4. `thing_text.tsv` — both toys' strings
5. `defaults.tsv` — nineteen new keys
6. `achievements.tsv` — three new rows

## 1. `drops.tsv`

**Check first whether 3a already added it.** The 3a spec created the rows that spec needed; if drop 2 is already present, skip this section rather than duplicating the id.

| `drop_id` | `trigger` | `date` | `event` | `name` | `notes` |
| --- | --- | --- | --- | --- | --- |
| 2 | `manual` | — | — | Something to Play With | Advanced by `/advance-game`. No calendar in V3 |

## 2. `restocks.tsv`

**One column renamed.** `container` becomes **`destination`**. The three existing rows keep their values unchanged — the rename is because `placement` now decides what kind of id the column holds, and "container" stops being accurate the moment a restock targets a room.

**One new `placement` value: `room`.** Today `placement` is `container` (into a named container) or `random` (uniformly across every room and container). Neither expresses "into one specific room," which is what a channel toy needs. With `placement = room`, `destination` holds a room id.

**One new column: `max_present`**, after `amount`. The three existing rows get it **blank**, meaning no cap — they keep topping up by rate exactly as today. Only the toy row uses it.

**New row:**

| Column | Value |
| --- | --- |
| `restock_id` | `toy_channel` |
| `thing_id` | `type:toy` |
| `placement` | `room` |
| `destination` | `<CHANNEL>` |
| `amount` | 1 |
| `max_present` | 2 |
| `times_per_day` | 4 |
| `first_day` | 1 |
| `every_n_days` | 1 |
| `window_start` | 09:00 |
| `window_end` | 23:00 |
| `config_key` | `toys_present` |
| `since_drop` | 2 |
| `notes` | Fill toward `max_present`, never exceed. Cap is scoped to `type = toy`, not to this row |

**`thing_id` holds a class selector, not a thing id.** `type:toy` means *draw uniformly among the things of that type that are eligible to be placed* — in drop 2, the feather wand and the crinkle ball, equally likely, which is what the work order §2 asks for. This is the one new engine capability in this file, and it is worth paying for: the bed stash in the work order §8 already needs the same pick-a-random-toy helper, and the rotation work adds weights to that same draw later. The alternative — two restock rows, one per toy, each at `times_per_day = 2` — needs no engine change but gives each toy its own fixed schedule rather than a draw, so a freed slot is filled by whichever row happens to fire next rather than by a coin flip. If the selector is cut, that is the fallback, and the work order's "equally likely to draw" has to be reworded to match.

**On the cap and the class.** The work order's rule is *keep two toys in the channel*, counted across the toy class rather than per row. With one restock row drawing from the class the two readings already coincide, but to make sure adding rows later cannot create a conflict, **seed `server_config.toys_present` from this row's `max_present` and have the engine read the cap from `server_config`, not from the row.** `config_key` already names that key, which is the same pattern `bottles_per_day` uses.

**`times_per_day` and `amount` are different things**, as the Functional Spec sets out: four occurrences placing one toy each, so they arrive at four separate moments and the channel refills promptly after someone takes one. Draw a separate random time inside the window for every occurrence.

## 3. `things.tsv`

**Two new rows.** The feather wand in full, all twenty columns in file order; the crinkle ball after it, showing only the four cells that differ.

| Column | Value | Note |
| --- | --- | --- |
| `thing_id` | `feather_wand` |  |
| `name` | feather wand |  |
| `aliases` | `wand\|feather\|feathers\|feather toy\|cat toy\|toy` | **The alias list matters more than usual.** A player told only that "there is a toy" will type `/use toy`. From drop 2 that alias sits on both toy rows, so it has to reach the ambiguity prompt rather than resolve to whichever row sorts first — see the note under the crinkle ball. |
| `type` | `toy` | **A new value.** The work order keys the toy class on it, so nothing may key on `thing_id` |
| `room_id` | `<CHANNEL>` |  |
| `quantity` | 1 | One of each the moment the drop opens, so the channel starts at its cap of two rather than empty until the first restock window |
| `takeable` | yes |  |
| `droppable` | yes |  |
| `cross_weight` | 1 | Unread in Release 1. Do not build behavior on it |
| `max_per_player` | 1 |  |
| `requires` | — |  |
| `present_when` | — |  |
| `transforms_to` | — |  |
| `transform_room` | — |  |
| `yields` | — |  |
| `destination_room_id` | — |  |
| `contained_in` | — |  |
| `use_cooldown_hours` | — | **Leave blank, and resist the temptation.** The toy's ten-minute cooldown is per *player*, in minutes, and lives on the player row. This column is per *thing*, in hours, and would apply the cooldown to everyone at once |
| `since_drop` | 2 |  |
| `sort_order` | 138 | Current maximum is 137 |

**The crinkle ball is the wand's row with four cells changed.** Everything else is identical: `type = toy`, `room_id = <CHANNEL>`, `quantity` 1, `takeable` and `droppable` yes, `cross_weight` 1, `max_per_player` 1, the transform, yield and container columns blank, `use_cooldown_hours` blank, `since_drop` 2.

| Column | Value |
| --- | --- |
| `thing_id` | `crinkle_ball` |
| `name` | crinkle ball |
| `aliases` | `ball\|foil ball\|crinkle\|crinkle toy\|cat toy\|toy` |
| `sort_order` | 139 |

**Two of those aliases are shared with the feather wand on purpose.** `toy` and `cat toy` resolve to two things from drop 2, so `/take toy` and `/use toy` have to go through the existing ambiguity prompt and its `{options}` token rather than picking one. That path exists; what is new is that drop 2 is the first time it fires on a toy, so it belongs in the QA list. The unambiguous aliases are what a player ends up typing, and `{name}` in the hints resolves to the row's `name`, never to an alias.

The `cat_bed` row from 3a is unchanged. Its text gains a variant in the next section.

## 4. `thing_text.tsv`

**Five rows for the two toys**, all at `since_drop = 2`, state `default`. Text is in the Drop 2 copy deck — the wand in §1, the crinkle ball in §3 — take it from there rather than retyping it here, so a writer edit does not get stranded.

| `thing_id` | Key | Status |
| --- | --- | --- |
| `feather_wand` | `look` | In the copy deck |
| `feather_wand` | `use` | In the copy deck |
| `feather_wand` | `use_fail.cooldown` | In the copy deck. Carries no `{time}` — the writers cut it deliberately |
| `crinkle_ball` | `look` | In the copy deck §3 |
| `crinkle_ball` | `use` | In the copy deck §3 |

**`look_carried` is gone.** It was a fourth row until the writers merged it: the wand's single `look` now covers both the channel and the inventory, and the copy deck's When column says so. Do not add a `look_carried` row for the wand, and do not go looking for its string. The crinkle ball is the same — one `look`, no `look_carried`.

**The crinkle ball has no `use_fail.cooldown` row,** and that is not an omission to fix in the file. It falls through to the `use_fail.cooldown` default, which is what every other thing in the game does; the wand has a custom one only because the writers wrote one. If they want a second, it is one row and no engine change.

`take`, `drop` and the ramp refusal all fall through: `take.default`, `drop.default`, and the `use_fail.toy.*` pool.

**No row for the bed.** A `cat_bed` `use` variant at `since_drop = 2` was reserved here for the "something fell out of it" line, and it has been dropped: `bed_yield.public` and `hint.bed_yield` carry the news between them. The drop 1 fluff reply is unchanged on every server at every drop, and **every string this spec needs already exists** — there is nothing here waiting on a writer.

## 5. `defaults.tsv`

Nineteen new keys. All text is in the Drop 2 copy deck.

| Keys | Count | What |
| --- | --- | --- |
| `use_fail.not_carried` | 1 | The thing is in reach but not in the bag |
| `use_fail.toy.1` … `use_fail.toy.12` | 12 | The rotating play refusals. The engine collects every key matching `use_fail.toy.*` and picks one uniformly |
| hint.look\_toy, hint.take\_toy, hint.use\_toy | 3 | The three middle rungs of the hint ladder. Each carries {name}, resolved at fire time against the takeable toys in the channel |
| hint.hold\_to\_use | 1 | The refusal rung — first time /use is refused for not holding the toy. Carries {name} |
| hint.bed\_yield | 1 | Points at /look once the bed has dislodged something |
| bed\_yield.public | 1 | The public line when a fluff dislodges a toy. Replaces the bed's ordinary public /use line for that fluff only. Carries {player} |

**The hint keys belong here, in `defaults.tsv`, like every other hint** — which is also why none of them can carry a `since_drop`: the file has only `key` and `text`. That is the reason the three middle rungs are new keys rather than drop 2 variants of the drop 1 hints. `hint.something_new` is reused unchanged and so is not in the list above. The preconditions that decide when each one fires are engine logic, not content; they are in the Phase 3b Work Order §10.

**Numbered keys, not a pipe-separated cell.** The writers review the deck as tables, `|` is the table delimiter, and the first writer edit would split a refusal in two.

No existing default changes. `take_fail.already_carried`, `take_fail.fixture`, `drop_fail.not_carried`, `drop_fail.undroppable`, `take.default`, `drop.default` and `use_fail.cooldown` are all reused as they stand — the work order's one engine line routes the `max_per_player` refusal to `take_fail.already_carried` rather than requiring a per-thing string.

## 6. `achievements.tsv`

Three new rows, using the three columns 3a added (`prompt`, `requires`, `offered_by`).

| Column | *Persuasive* | *Impressively Bad Luck* |
| --- | --- | --- |
| `achievement_id` | `persuasive` | `impressively_bad_luck` |
| `kind` | `public` | `secret` |
| `name` | Persuasive | Impressively Bad Luck |
| `unlock` | **Already final in the drop schedule — confirm, do not rewrite** | **Already final in the drop schedule — confirm, do not rewrite** |
| `since_drop` | 2 | 2 |
| `sort_order` | 190 | 191 |
| `prompt` | Play with the cat | — secret, no prompt |
| `requires` | `making_first_contact` | — |
| `offered_by` | — | — |
| `notes` | Fires on the first successful toy play | Fires at a ramp of 4, which is four consecutive refusals. 9.4% |

No prompt carries a terminal full stop, and the template adds none.

**And a third row**, added after the copy deck's section 5 was settled:

| Column | *Tireless* |
| --- | --- |
| `achievement_id` | `tireless` — **confirmed, ships as-is** |
| `kind` | `secret` |
| `name` | **Tireless** — confirmed |
| `unlock` | Drafted in the copy deck §5; take it from there |
| `since_drop` | 2 |
| `sort_order` | 192 |
| `prompt` | — secret, no prompt |
| `requires` | — |
| `offered_by` | — |
| `notes` | Twenty-five successful toy plays, cumulative, any toy. `COUNT(*)` over the toy rows in `thing_uses` |

**This row depends on an engine change, not just a content one.** Nothing in 3b wrote a history of plays until the work order was amended; the achievement is a count over `thing_uses`, so the play handler has to insert a row per successful play. See the Phase 3b Work Order §9. The same insert is what makes the two later collection achievements possible at all, so it is worth confirming it landed before this row is added.

## 7. What the loader should refuse to start on

Worth adding alongside the existing content checks, because each of these fails silently otherwise:

- A `restocks.tsv` row with `placement = room` whose `destination` is not a known room id.
- A `max_present` set on a row whose `thing_id` has no `type`, or a `type` with no `server_config` cap seeded.
- A `things.tsv` row with `type = toy` and `max_per_player` blank — an uncapped toy lets one player hold the channel's entire supply.
- Any `use_fail.toy.*` key with a gap in its numbering, which would make the random pick uneven in a way nobody would notice.

**And one more, added after the fact:** a `things.tsv` row with `type = toy` and no `use` text. It does not error — it falls through to `use.default` and ships a toy whose payoff line is *"You turn the {name} over in your hands. Nothing obvious happens."* Of everything on this list it is the one most likely to reach a player, because a toy with no success line looks fine in the file and only reads as broken in play. See the Phase 3b Work Order §6.

**And one correction to the third check above, which as written would refuse to start on a legitimate row.** It must read `type = toy` **and `takeable = yes`** and `max_per_player` blank. A fixture toy carries no `max_per_player` by design — nobody can hold it, so there is nothing to cap — and the Amazon box in drop 3 is exactly that. The check is for uncapped *takeable* toys, which are the ones where one player could otherwise hold a channel's entire supply.

## 8. Not in this spec

- **The eleven other toy rows.** Written and waiting in the copy deck's bank; they are a later drop's content change, and they only stay a content change if nothing in 3b keys on `thing_id`.
- **Restock draw weights.** There are two toys to weight now, but drop 2 wants them equal, so no `draw_weight` column ships here. It arrives with the first rare toy, on the same draw the `type:toy` selector introduces.
- **The Amazon box**, which is drop 3, in the Entryway, as an easter egg.
- **The catnip buff's `pet_buff_minutes` column**, parked with its conditions in the copy deck.
- **The pronoun sweep**, if it is still outstanding from 3a.

**Two achievement rows are deliberately held back, and it is worth knowing why rather than adding them helpfully.** `easily_amused` (five distinct toys) and `whole_toy_box` (every planned toy) are both specified in the copy deck §5, but neither can carry a truthful `since_drop` yet — one belongs to the drop that brings the fifth toy and the other to the drop that brings the last, and neither drop exists in `drops.tsv`. A placeholder would also need the loader to tolerate a `since_drop` with no matching drop row, which nobody has verified. Each is a one-line addition once its drop is known.

**One thing that is not a TSV change but belongs with them.** `server_config.toy_set_total` is seeded at **13** in 3b — the declared size of the toy set. It has no content file of its own, so it lives in the work order (§9) rather than here, but anyone renumbering the toy rows later needs to change it in step or `whole_toy_box` becomes unearnable or premature.
