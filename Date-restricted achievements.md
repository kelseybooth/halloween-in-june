# Date-restricted achievements

Oct 30, 2026 · @Qaruse

**Urgent: *Familiar* opens today, 30 October, at 15:00 UTC (08:00 Pacific), and closes 1 November at 11:00 UTC.** Any player command in that window earns it. This page collects the decisions from 28 September, 21 October and 30 October in the Achievement Trigger Spec, so the date checks can be built from one place.

## The dated achievements

Three achievements fire only inside a window of time. Two are live now at drop 0, and *Curbside Pickup* arrives with the kitchen at drop 30.

| Achievement | Day | Window (UTC) | Trigger and hook | Drop | Status today |
| --- | --- | --- | --- | --- | --- |
| *Familiar* | Halloween, 31 Oct | 30 Oct 15:00 to 1 Nov 11:00 | Any player command at all, checked at command dispatch, so `/stats` and `/help` count | 0 | **Opens today** |
| *Lucky Black Cat* | Black Cat Day, 27 Oct | 26 Oct 15:00 to 28 Oct 10:00 | Any cat interaction (pet, toy, bed or feed), wherever `last_cat_interaction_date` is stamped. Any pet counts, friendly or not | 0 | Passed |
| *Curbside Pickup* | Every Tuesday | Monday 08:00 to Wednesday 03:00 Pacific. In UTC: Mon 15:00 to Wed 10:00 until 1 Nov, then Mon 16:00 to Wed 11:00 | `/use` the trash can, `on_use` | 30 | Weekly, from drop 30 |

## The window rule

**Decided 28 September: a date's window is 43 hours, not one calendar day.** Players span Japan to Hawaii, so a single Pacific day shuts someone out. A day D means **D minus one day at 08:00 Pacific, up to D plus one day at 03:00 Pacific.** Test it as:

```latex
\text{(D} - 1\text{ day) at 08:00 Pacific} \le \text{now} < \text{(D} + 1\text{ day) at 03:00 Pacific}
```

In plain terms: start ≤ now < end, with both ends converted from Pacific time.

- **Store and compare in UTC.** *Familiar*'s window crosses the end of daylight saving time on 1 November, so its end is 11:00 UTC, not 10:00. Converting from `America/Los_Angeles` with a time zone library gets this right; adding a fixed −7 hours does not.
- **Curbside Pickup** follows the same rule, with D being every Tuesday.
- **Write it once.** All three are the same check: "this action, inside this window". Build one function taking a window rule and a set of (hook, target) pairs, and register it for each achievement.
- **Don't stop at the first match.** One action can earn more than one achievement, so evaluate every achievement listening on a hook rather than chaining them with `else if`.
- **The `since_drop` gate still applies.** A dated achievement can only fire once the server has reached its drop and the window is open.

## No longer dated

**Decided 21 and 30 October:** these six have no date. If the code still checks a date for any of them, remove it.

| Achievement | Trigger | Unlock text | Drop |
| --- | --- | --- | --- |
| *Brewing Trouble* | Any successful `/use` of the coffee maker | Drank coffee. | 30 |
| *Self-Reflection* | Any successful `/use` of any of the three mirrors | Checked a mirror. | 20 |
| *Using Your Noodle* | Any successful `/use` of the pasta pot | Put a pot on. | 30 |
| *Nacho Average Ghost* | Any successful `/use` of the nacho chips. **Changed 30 October** | Snacked on the nacho chips. | 30 |
| *Green Thumb* | All three, per player, in any order and on any days: `/use` the watering can, `/take` herbs from the herb garden, `/use` (carve) a pumpkin. Listens on `on_use` and `on_take`, and needs a per-player record of which of the three are done. **Changed 30 October** | Watered the garden, picked the herbs and carved a pumpkin. The courtyard has a gardener again. | 30, but carving needs the carving tools from drop 40 |
| *Trash Panda* | Taking any item out of the trash can. The trash can doesn't hold items yet, so this waits for a future release. **Changed 30 October** | Went through the trash and came out with something. | 99 |

21 October also added the two holiday windows above, *Lucky Black Cat* and *Familiar*, both written in UTC in `achievements.tsv`.

## Acceptance tests

Use a QA server with a fake clock, or an admin override for "now".

- **Familiar:** a command at 30 Oct 14:59 UTC earns nothing. One at 15:00 UTC earns it. `/stats` and `/help` count. One at 1 Nov 10:59 UTC still earns it, and one at 11:00 UTC doesn't.
- **Lucky Black Cat:** a pet at 26 Oct 15:00 UTC earns it, an unfriendly pet included. A pet at 28 Oct 10:00 UTC doesn't.
- **Curbside Pickup,** at drop 30: `/use trash can` on a Monday at 08:00 Pacific earns it, and on a Wednesday at 03:00 Pacific doesn't.
- **Undated:** *Self-Reflection* fires from `/use mirror` on an ordinary day at drop 20, and *Nacho Average Ghost* from `/use nacho chips` at drop 30.
- **Green Thumb,** at drop 40: watering, picking herbs and carving a pumpkin on three different days earns it after the third. Any two of them earn nothing.
- **Trash Panda** doesn't appear in any achievement list.

## Open question

- [x] ***Trash Panda*, *Green Thumb* and *Nacho Average Ghost* couldn't be earned this year,** because their days passed before drop 30. Decided 30 October: none of them is dated any more. See the table above.
