# Release 1 content

Tab-separated, UTF-8. Open in Excel or Google Sheets (import with tab as the delimiter,
and turn OFF any "convert text to numbers/dates" option so ids stay as written).

|File|Rows|What it is|
|-|-|-|
|`rooms.tsv`|9|Room ids and names. Structure, not text.|
|`room\_text.tsv`|11|Room `look` text. 9 rooms + 2 rows for the repaired staircase.|
|`things.tsv`|140|Every object, source, fixture and exit: ids, placement, flags. Structure, not text.|
|`thing\_text.tsv`|147|`look`, `look\_carried`, `use`, `take`, `drop` plus the three refusal strings.|
|`defaults.tsv`|16|Fallback strings used wherever a cell is left blank.|
|`drops.tsv`|1|The unlock calendar: which drop each row of content waits for.|
|`restocks.tsv`|3|Scheduled top-ups: what gets added to which container, how often.|

Writers edit `room\_text.tsv`, `thing\_text.tsv` and `defaults.tsv`.
`rooms.tsv` and `things.tsv` carry game rules — changing those is a design decision.

**Leave a cell blank to accept the house default.** Most things have no `take` or `drop`
text and fall through to `defaults.tsv`; fill the cell in and that one thing gets its
own line.

Full column reference and the resolution rules are in the **Content Schema** (New Spec
tab) of the Halloween project doc.

## Saving from Excel

Excel can't write UTF-8 TSV directly. Save as **Unicode Text (.txt)** or **CSV UTF-8**,
or just send the `.txt` it gives you — the smart quotes and em dashes survive and it
gets converted on this end.

## Two rules that shape the text

Both exist because several players share one house, and anything portable may already
be in somebody else's bag by the time you walk in.

**Nothing takeable and finite is named in prose.** Not in a room description, not in a
container's description. The engine lists those separately, so the prose can't go stale.
`/look` on a room prints the description and then `Also here: nacho chips`; `/look` on
the Amazon box prints the box and then `Also here: spice jar`. When the thing is gone,
the line is simply absent.

This is easy to break by accident. Two cases in the last pass named nothing at all —
"hollow, with something wrapped in foil inside" and "something catches the light with a
gold band on the label" — and were still false once the chocolate and the tin were
taken. Write hints that stay true either way.

**Sources are inexhaustible; objects are finite.** A stash of cat food is a `source`
that never runs out and can't be carried; a can is an `object` with no room of its own
that exists once drawn. Sources never appear in the `Also here:` line, so every source
must be named in its room's description or in the text of the thing that holds it.

## Where the cat food is

Four flavors, one stash per room, so collecting a set means ranging around the house.

|Room|Flavor|Hidden in|
|-|-|-|
|Kitchen|tuna|the pantry|
|Living Room|chicken|under the sofa|
|Entryway|salmon|behind the coat rack|
|Upstairs Hallway|expired|the roll-top desk's bottom drawer|
|Bedroom|chicken|a crate under the bed|
|Dining Room|salmon|the sideboard cupboard|

The single gourmet can is under the bed behind the chicken crate, and it is the only one
in the house.

## What changed since the copy you sent back

**48 rows added, 1 removed, 10 of your cells edited.** Everything else of yours is
byte-for-byte intact.

The removed row is `grocery\_list`, renamed to `to\_do\_list` — the text carried over
verbatim, only the key changed.

Your ten edited cells, all approved in conversation:

|Cell|Why|
|-|-|
|`ritual\_diagram.look`|"pinned to the wall" → "pinned to the shelf edge", to match where it now lives|
|`halloween\_box.use`|gained the cookie cutter clause|
|`rolltop\_desk.look`|no longer names the reading glasses (they're inside it)|
|`rolltop\_desk.use`|the bottom drawer is jammed shut, and no longer names the glasses|
|`amazon\_box.look`|no longer names the spice jar (it's inside it)|
|`amazon\_box.use`|same|
|`lumber.use\_fail`|the 48-hour cooldown message, replacing "you've already done your part"|
|`graphite\_powder.look`|a carried twist of paper, not the tin — the tin's own words moved to `graphite\_tin`|
|`graphite\_powder.take`|same|
|`graphite\_powder.drop`|same|

The 48 new rows are 34 scenery fixtures, 9 sources, `cat\_food\_expired`, `bad\_smell`,
`graphite\_tin`, `amazon\_box`'s companion text, and the `drawer\_unjammed` state row on
`rolltop\_desk`.

## Lumber: one plank per player per 48 hours

New column `use\_cooldown\_hours` on `things.tsv`, set to `48` on `lumber` and blank
everywhere else. New default `use\_fail.cooldown`. Lumber's own `use\_fail` was rewritten,
because "You've already done your part" was true under the old one-plank-ever rule and
is wrong now:

> You've set your plank. Your shoulders will want about {time} before the next one.

`{time}` is a new template token — the remaining cooldown, rendered by the engine. It
needs adding to the Templating section of the Content Schema.

The engine side is the real cost: nothing currently records a per-player, per-thing last
used time. `pet\_events` is the only behavioral log and it is shaped for the mood window.

`{total}`, the number of planks the staircase needs, becomes per-server configuration
rather than content — see the Delivery Plan.

## Expired cat food, the jammed drawer, and graphite

**Duck is gone** — `cat\_food\_duck` and the Upstairs Hallway duck stash are both removed.
The five flavors are now chicken, salmon, tuna, gourmet and **expired**, which matches
the "Charcuterie Board" achievement exactly.

**The desk's lid opens; only the bottom drawer is jammed.** The glasses, the manual and
the papers stay reachable at launch, so "Found the Specs" isn't gated behind this.
`rolltop\_desk` has a second text row, `drawer\_unjammed`. The expired cat food source
sits `contained\_in` the desk with `present\_when = drawer\_unjammed`.

**The bad smell is in the Upstairs Hallway from day one** — a non-takeable fixture named
in the room description. Looking at it points you at the desk; the source stays hidden
until the drawer opens.

**Graphite is now a source.** `graphite\_tin` in the Nursery yields `graphite\_powder`.
This was forced: as a single tin only one player could ever unjam anything, and
achievement 5 sends graphite to David, so the two uses destroyed each other. Because
sources may appear in room prose, the tin is back in the Nursery description it was cut
from last week.

That moved three of the writer's graphite cells. The tin's original description is
preserved word for word — it just sits on the source row now, where it belongs. The
object's `look`, `take` and `drop` are new, because a carried portion is a twist of
paper, not the tin.

**New column `since\_drop` on `things.tsv`**, so a thing can appear at a later drop
rather than existing from launch. Every row is `1` today; nothing uses it yet. The text
files already had this column — structure rows did not.

The rule that `/use graphite` sets `drawer\_unjammed` is **not** in the content files. It
lives in the Content Schema, like every other state rule. The TSVs say what a thing
looks like in a state and gate visibility with `present\_when`; they never say how a
state is reached.

## What was built

* **Scenery pass.** 34 fixtures for nouns that room prose named but no row covered —
the coat rack, the fireplace, the high chair, the dining table, the bed, and so on.
`/look` works on everything a description mentions.
* **The `quantity = many` split.** Nine sources; the six affected objects are now
roomless and start at zero. `lumber` deliberately keeps `quantity = many` — it's a
shared pool of repair charges, not a source, and yields nothing.
* **`contained\_in`.** Sixteen chains, all one level deep, host and content in the same
room.
* **The room pass.** Five takeable-finite things moved out of prose into `Also here:`.
The Nursery and the Kitchen were redrafted rather than trimmed, because the sentences
being cut were also carrying the shelf, the window and the counter.
* **The Amazon box transform was withdrawn**, not built. The listing rule above already
keeps the box's description true, and building it would have needed a trigger type
the engine doesn't have — the one real transform, `used\_baby\_bottle` →
`sanitized\_baby\_bottle`, fires on *use in a room*, whereas a box that empties fires on
*something else being taken out of it*. Reasoning is in the Content Schema.

## Checks that pass

Nothing unreachable; no alias collisions in any room; every thing has a text row and
every text row a thing; every `yields` and `transforms\_to` target exists; all container
chains one level deep; no stray tabs; valid UTF-8 throughout.

Nothing from the rebuild is outstanding.

One cosmetic oddity, not a bug: a container's listing includes the sources inside it, so
`/look bed` says "A plastic crate of cat food is pushed underneath" and then lists
"crate of chicken cat food".

