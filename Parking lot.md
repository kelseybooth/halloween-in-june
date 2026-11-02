# Parking lot

Things found, understood, and deliberately not fixed yet. A row leaves
this file when somebody decides what it should do instead - not when
somebody works out why it happens, which is already written down here.

---

## A source's own `use` line is never read

**Parked 2 November 2026.** Found while chasing a playtest report that
`/use garden` in the Courtyard did not give the Sunday roast line.

### What happens

Every one of the seventeen sources in `things.tsv` has a `use` line
written in `thing_text.tsv`, and not one of them can be reached. The
word resolves to the thing the source hands out, and the reply comes
out of that thing's rows instead:

| Typed | What comes back |
| --- | --- |
| `/use herb bed` | The herbs is right there. You would have to pick it up first. |
| `/use candy bowl` | The piece of candy is right there. |
| `/use freezer` | The frozen burrito is right there. |
| `/use stash` (Living Room) | You turn it all the way round twice. There is no pull-tab anywhere on it... |
| `/use can opener hook` | That can't be used. |

The stash is the clearest: the player asked about a stash of cans under
a sofa and was answered with a sentence about one can's lid.

### Why

`reach.find` files a source and the object it yields as **one candidate,
under the yield's id and display name**. That is deliberate and it is
what makes `/take chicken` work whether the player is holding a can or
standing by the stash - the module's own docstring says so: *"A source
and the object it yields are one thing."* So by the time `/use` has a
`found`, the `herb_garden` is gone and only `herbs` is left; the herbs
are `consumed_on_use` and not in hand, so the reply is
`use_fail.not_carried`.

### The hook a fix would use

`reach` already keeps `source_names` and `yield_names` apart on the
candidate, with a comment saying it is "what lets a word only one of
them answers to pick that one". So a word that only the source answers
to - *garden*, *herb bed*, *freezer*, *hook* - could read the source's
own rows, while a word the yield answers to keeps today's behaviour.
`Found` also carries `source_id` and `yields`, set only when the copy
came from the source.

### Why it is not just an engine change

**Most of the seventeen lines read like `take` narration, not like a
use.** "You slide a can out from under the sofa." "You lift one off the
rail." "You take a can from the front row." Turning the class on as
written would describe a can leaving the stash when nothing left the
stash - which is the thing beta keeps flagging about tidying that does
not change `/look`.

Two or three are genuine uses and would work the day the engine read
them: the herb garden's Sunday roast, the hollowed book's "heavier than
theory", the chip box's "You stop counting the bags."

So the decision this is waiting on is a copy decision, not a code one:
which of the seventeen are uses, and what the rest should say instead.

### Also noticed on the way

`use_fail.not_carried` has no plural form, so three things in the house
produce "The herbs **is** right there" and "The tortilla chips **is**
right there."
