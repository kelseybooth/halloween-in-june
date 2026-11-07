"""The Nursery's room paragraph stops doing its furniture's work.

It had been carrying three beats the things themselves already said -
the shelf's height, the crib's emptiness, and a full clause for the
monitor - and Kelsey's second pass took all three out. The shelf and the
crib lose nothing by it: both are still named in the paragraph, so both
are still one `/look` away.

**The monitor is the one that moved.** It is not named in the room's
prose at all now, and it is a fixture, so the engine never lists it
either - `Also here:` carries takeables and nothing else. The only route
to it that does not depend on finding something else first is: read the
room, see the changing table, look at the changing table, read that the
monitor sits at the end of it.

That matters more than a sentence usually does, because `baby_talk`
fires on `on_use` of this fixture and the Nursery is a drop of its own.
Whether one nested look is the right distance is Kelsey's call, and this
file does not try to settle it. It pins where the route runs today, so
that moving it is a decision somebody makes rather than a side effect of
editing a different cell.
"""

import re

import content as content_module


def nu_room_look(files) -> str:
    rows = [r for r in files.room_text if r.entity_id == "NU"]
    assert len(rows) == 1, [r.state for r in rows]
    return rows[0].text["look"]


def thing_text(files, thing_id, state="default"):
    return next(
        r for r in files.thing_text
        if r.entity_id == thing_id and r.state == state
    ).text


def names(thing) -> list[str]:
    return sorted(set(thing.names), key=len, reverse=True)


def mentions(text: str, thing) -> bool:
    low = (text or "").lower()
    return any(re.search(rf"\b{re.escape(n.lower())}\b", low) for n in names(thing))


def test_the_room_hands_the_shelf_and_the_crib_back_their_own_lines():
    """Both stay one look away, which is why losing the clauses is free."""
    files = content_module.load_files()
    look = nu_room_look(files)

    assert "out of reach of anybody small" not in look
    assert "though the crib is empty" not in look
    # The nouns are still there, so `/look shelf` and `/look crib` still land.
    assert "shelf" in look and "crib" in look
    assert "out of reach of anybody small" in thing_text(files, "nursery_shelf")["look"]
    assert "does not feel empty at all" in thing_text(files, "crib")["look"]


def test_the_room_no_longer_names_the_baby_monitor():
    """The edit this file exists for."""
    files = content_module.load_files()
    monitor = files.things_by_id["baby_monitor"]

    assert not mentions(nu_room_look(files), monitor)
    # And it cannot arrive via the item list either: only takeables are listed.
    assert not monitor.takeable


def test_but_the_changing_table_names_it_and_the_room_names_the_table():
    """The route, one look deep, and both halves of it have to hold.

    Either half alone is useless: a changing table nobody is pointed at
    is as good as a monitor nobody is pointed at.
    """
    files = content_module.load_files()
    table = files.things_by_id["changing_table"]
    monitor = files.things_by_id["baby_monitor"]

    assert mentions(nu_room_look(files), table)
    assert mentions(thing_text(files, "changing_table")["look"], monitor)


def test_three_sentences_satisfy_the_check_and_only_one_is_a_route():
    """What is actually holding the validator up, which is not what it looks like.

    `_check_unlisted_things_are_named_in_prose` asks whether anything in
    the room names the thing, by any writer but itself. Three rows do,
    and any one of them is enough - established by mutation, not by
    reading: rename the monitor out of the changing table's two mentions
    and content still loads, rename it out of David's note as well and it
    still loads, and only with the music box's `in:NU` line gone does
    `content.load()` raise and name the monitor.

    **Four sentences carried it before this room paragraph was rewritten,
    and three carry it now.** Keep the room's old clause and rename all
    three of these, and content is clean - so the paragraph alone used to
    be enough, and what is left holding the monitor up is a lullaby.

    Two notes on how to redo this, because both ways of getting it wrong
    look like answers. Mutate by renaming the monitor to a noun nothing
    answers to, never by emptying the `look` cell: an empty cell fires a
    couple of hundred unrelated problems and buries the one being tested.
    And read the problems from `content.validate()`, never off the
    exception - `ContentError.args[0]` is a string, so filtering it as a
    list of problems iterates characters, matches nothing, and reports
    none about the monitor at exactly the moment the monitor is the
    problem.

    So the check is not the thin guard it first appears to be. But three
    sentences are not three routes. David's note is itself found through
    the changing table, and the music box's line is a `use` line on a
    thing that has been carryable since drop 40 and is set down wherever
    its owner left it after six idle hours - so a player standing in the
    Nursery may well have neither in front of them.

    Pinned as a set so that deleting one is visible here, where the
    difference between a mention and a route is written down, rather than
    only in a check that cannot tell them apart.
    """
    files = content_module.load_files()
    monitor = files.things_by_id["baby_monitor"]

    writers = set()
    for row in files.thing_text:
        thing = files.things_by_id.get(row.entity_id)
        if thing is None or thing.room_id != "NU" or row.entity_id == "baby_monitor":
            continue
        if any(mentions(row.text.get(key), monitor) for key in ("look", "use")):
            writers.add(f"{row.entity_id}/{row.state}")

    assert writers == {
        "changing_table/default",
        "david_note/default",
        "music_box/in:NU",
    }
