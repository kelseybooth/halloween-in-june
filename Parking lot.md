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

---

## What is inside the mail has no text of its own

**Parked 11 November 2026.** Found while making the rest of the
sideboard's nouns typeable, after a playtester was shown the cat for
typing `mail`.

### What happens

The sideboard's `use` line is the only place three objects exist:

> You go through the mail. Two utility bills, a parenting magazine, and
> a card addressed to Elena, David, and Marcus.

Nothing in the files is a bill, a magazine or a card. Players have
typed them anyway - `card` seven times across `/look`, `/use` and
`/take`, `magazine` three, `bills` and `utility bills` three between
them - and every one of those got *you don't see a card here*, which
is false. They had just read about it.

### Why an alias was the wrong fix

Everything else the sideboard's prose names was aliased to the
sideboard in the same change, and these five were taken back out
before it shipped. An alias sends a word to a thing's whole row, and
the sideboard's row answers two verbs very differently:

| Typed | What an alias would give back |
| --- | --- |
| `/use card` | *You go through the mail... and a card addressed to...* |
| `/look card` | The sideboard's description, which does not mention a card |

The `use` half is right. The `look` half is a dead end wearing the
clothes of an answer: the player asked about a card and got a
paragraph about furniture, with no card in it and nothing to try next.
A refusal at least ends the sentence.

**The card is the one that matters.** It is addressed to Elena, David
and Marcus, which is three names disclosed by an object - the way this
house is allowed to say a name at all - and seven people have reached
for it.

### What it is waiting on

A copy decision, and there are two shapes of it:

- **Give them their own rows.** A card, and perhaps the magazine, as
  fixtures in the Dining Room with their own `look` text. Then every
  verb answers, and the card can carry whatever its own sentence is
  worth carrying.
- **Name them in the sideboard's `look` instead of only in its `use`.**
  Cheaper, and it makes the alias honest in one line - `/look card`
  would hand back a paragraph that mentions a card.

Either is writing rather than parsing, which is why it is here.

`tests/test_the_sideboard_answers.py` has the assertion that the five
words are still refused, so this row cannot quietly stop being true.

### Also noticed on the way

The sideboard has one `use`, so every word on it gets the mail:
`/use saucer` answers *You go through the mail.* That was already true
of `/use buffet` and is a smaller version of the same question - what
a fixture's single `use` should say when the fixture is a surface with
several things on it.
