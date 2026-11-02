"""Drop 30: the four rooms, and the three doors that are not doors yet.

The ground floor is almost entirely content - four rewritten rooms, a
ladder, a trash can, a cat bowl in the courtyard - and the engine work
it needs is small and scattered. This file holds the part that is about
drop 30 itself:

**The ceiling.** `/advance-game` has twice refused to reach the drop
that had just been built, so the drop the files call "The Ground Floor"
is checked against the furthest a server can be advanced. It moved to
30 ahead of three of drop 30's mechanics, on purpose: the content is
written and checked, and the ladder, the trash can and the top steps
are three releases behind it.

**Two secret ways in and an ivy, all shut.** The curiosity cabinet and
the oak exist from drop 30 so the engine bolds them in the Living Room
and Courtyard from the start, and the courtyard ivy became an exit to a
bedroom that does not open until drop 40. All three are refused, and
none of it is code: an arrived row with a refusal and no success beside
it is already how a writer says "not this way", and these three say it
in their own words.

**The board books rotate.** The first thing in the game whose `use` has
more than one line to it, which is the toys' trick applied to a thing
that is not a toy.
"""

import pytest

from conftest import ALICE, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember
from test_loader import a_thing, a_world
from test_world import carry

import achievements
import bot
import content as content_module
import content_loader
import database
import phrasing
import resolve
import states
import triggers
import world


THIS_DROP = 30


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.register_all()
    triggers.forget_arrivals()
    yield
    achievements.clear()


@pytest.fixture(autouse=True)
def forget_admissions():
    bot._ADMITTING.clear()
    yield
    bot._ADMITTING.clear()


@pytest.fixture
async def ground_floor(db):
    """Drop 30, the front door open, Alice fed the cat and standing inside.

    Fed because the four new rooms are behind that gate - the Entryway's
    inner doorways do not exist until the first can goes in the bowl -
    and a fixture that left her unfed would fail every test here on a
    condition none of them is about. `test_feeding` owns that gate.
    """
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(GUILD_A, channels=[halloween], members=[FakeMember(ALICE)])
    await content_loader.load_content(content_module.load_files())
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, THIS_DROP)
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    await db.start_game(ALICE, GUILD_A, "EN", await resolve.rooms_open_at_launch())
    await db.notice(GUILD_A, ALICE, content_module.FED_THE_CAT)
    return db, guild, halloween, rooms


def thread(ground_floor, room_name):
    _, _, halloween, _ = ground_floor
    return next(t for t in halloween.threads if t.name == room_name)


async def run(ground_floor, command, arg=None, *, room, who=ALICE):
    """One command, typed in a room's thread, with the player standing there.

    Her body has to be in the room and not only the command: the place
    check has been the rule since the threads became rooms.
    """
    db, guild, _, rooms = ground_floor
    await db.update_current_room(who, GUILD_A, room)
    interaction = FakeInteraction(
        who, GUILD_A, guild=guild, channel=thread(ground_floor, rooms[room])
    )
    args = () if arg is None else (arg,)
    await command.callback(interaction, *args)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


async def where(db, who=ALICE) -> str:
    return (await db.get_game_state(who, GUILD_A)).current_room


# --------------------------------------------------------------------------
# The ceiling
# --------------------------------------------------------------------------


def test_the_ceiling_reaches_the_ground_floor():
    """**The guard that has been needed twice.** Drop 2 shipped with the
    ceiling at 1 and drop 10 with it at 3, and both times the drop that
    had just been built could only be reached by `/qa-drop` on a test
    server.

    Read off the files rather than typed, so the number here cannot
    agree with itself while disagreeing with the content. `test_drops`
    asks the same question of the command table; this one asks it of the
    drop by name.
    """
    parsed = content_module.load_files()
    ground_floor = next(d for d in parsed.drops if d.name == "The Ground Floor")

    assert resolve.LAST_PLAYABLE_DROP >= ground_floor.drop_id


async def test_the_four_rooms_are_open_at_this_drop(ground_floor):
    """The other half of the ceiling: a drop that can be reached and whose
    rooms do not load is a drop that opened on nothing.

    **Asked of `arrived_rooms` and not of `all_rooms`.** It was the
    second until 31 October, which reads `rooms.tsv` and knows nothing
    about drops - so it passed at drop 0, and it would have passed if
    drop 25 had opened the Dining Room with no door into it. The right
    question of the wrong function, and the same shape as the mutation
    the last plank's release found.
    """
    assert THIS_DROP in await resolve.arrived_drop_ids(GUILD_A)

    here = await resolve.arrived_rooms(GUILD_A)
    for room_id in ("DI", "KI", "CO", "LI"):
        assert room_id in here


# --------------------------------------------------------------------------
# The two secret ways in, and the ivy
#
# All three are content, and all three are asserted here because all
# three are new at this drop and none of them was reachable before it.
# What would break them is not a change to any of these rows - it is a
# change to the rule in `_state_refusal` that reads them.
# --------------------------------------------------------------------------


async def test_the_cabinet_is_locked_without_the_key(ground_floor):
    db, *_ = ground_floor

    reply = replies(await run(ground_floor, bot.use, "curiosity cabinet", room="LI"))

    assert "Locked" in reply
    assert await where(db) == "LI"


async def test_the_oak_keeps_its_secrets(ground_floor):
    db, *_ = ground_floor

    reply = replies(await run(ground_floor, bot.use, "oak tree", room="CO"))

    assert "the oak can keep its secrets for now" in reply
    assert await where(db) == "CO"


async def test_the_courtyard_ivy_peels_off_the_wall(ground_floor):
    """An exit from drop 30 to a room that opens at drop 40, which is a
    shape the loader had not been handed before.

    It refuses with its own line rather than the engine's, which is what
    makes the tease readable: "not this way, not yet" says there is a
    way, where the generic refusal would have said there is nothing
    there.
    """
    db, *_ = ground_floor

    reply = replies(await run(ground_floor, bot.use, "ivy", room="CO"))

    assert "a whole curtain of it peels away from the wall" in reply
    assert await where(db) == "CO"


async def test_going_through_the_ivy_is_refused_the_same_way(ground_floor):
    """`/go` and `/use` are two ways through an exit, and a door shut to
    one of them and open to the other is what this catches."""
    db, *_ = ground_floor

    reply = replies(await run(ground_floor, bot.go, "ivy", room="CO"))

    assert "peels away from the wall" in reply
    assert await where(db) == "CO"


@pytest.mark.parametrize(
    "thing_id,word",
    [("ivy", "ivy"), ("CS", "oak tree"), ("CK", "back door")],
)
async def test_an_exit_refuses_a_take_in_its_own_words(
    ground_floor, thing_id, word
):
    """And `/take`, which was the one verb that answered over the top
    of the writers.

    Every other refusal in the take table lets a row speak for itself;
    the exit branch said `take_fail.exit` and nothing else, so "you
    can't put an exit in your bag" told a player the ivy was a way up
    before they had found it - the one place in the game where the
    house default gives away more than the written line. Every exit in
    the table had one written and not one of them had ever been read
    out.

    All three here are the same branch, and they are three because the
    ivy is the one the bug was reported on, the oak is the other
    exit a writer gave a joke of its own, and the back door is the
    twenty rows that just say doorway - so a revert fails three times
    rather than once in a way that reads as being about the ivy.

    Expected text read off the file rather than typed, so a copy edit
    is not also a test change.
    """
    written = next(
        r.text["take_fail"] for r in content_module.load_files().thing_text
        if r.entity_id == thing_id and r.state == "default"
    )

    reply = replies(await run(ground_floor, bot.take, word, room="CO"))

    assert reply == written
    assert "in your bag" not in reply or "doorway" in reply


async def test_and_the_ivy_still_never_says_the_word(ground_floor):
    """The half of the report that was not about whose words they
    were. Pinned apart from the line itself because this is the thing
    the ivy must never do, whatever it is rewritten to say."""
    reply = replies(await run(ground_floor, bot.take, "ivy", room="CO"))

    assert "exit" not in reply.lower()
    assert "window" not in reply.lower()

def test_neither_the_oak_nor_the_ivy_is_refused_by_code():
    """The point of the three tests above, stated once.

    `world.exit_refused_by` names the front door, the cabinet and the
    passage, and the cabinet is in it for the key rather than for the
    drop. The oak and the ivy are refused by what the writers wrote, so
    opening either one is a content change and not a release.
    """
    for thing_id in ("CS", "ivy"):
        assert not world.exit_refused_by(thing_id, set())


# --------------------------------------------------------------------------
# The board books
#
# Five lines for one `use`: the thing's own `thing_text` row, plus four
# `use.board_books.N` rows in the defaults. Sampled deterministically
# rather than statistically - `_First` and `_Last` are the fakes
# `test_the_box_as_a_toy` uses on the same `random.choice` - because a
# pool of five drawn forty times is a test that fails once a fortnight
# for no reason anybody can reproduce.
# --------------------------------------------------------------------------

ROW = "You pick up Goodnight Moon"
LAST_EXTRA = "You find Guess How Much I Love You"


class _First:
    def choice(self, pool):
        return pool[0]


class _Last:
    def choice(self, pool):
        return pool[-1]


class _Records:
    """Captures what was on offer, which is the thing worth asserting."""

    def __init__(self):
        self.pools = []

    def choice(self, pool):
        self.pools.append(list(pool))
        return pool[0]


async def read(ground_floor, thing="board books", room="LI"):
    return replies(await run(ground_floor, bot.use, thing, room=room))


async def test_the_row_is_still_the_first_line(ground_floor, monkeypatch):
    """**The row, not one option of five.** The extras are joined onto
    what the state resolution already picked rather than replacing it,
    which is the difference from the toys: a toy's refusals are a pool
    and nothing else, and a thing's `use` row is already written."""
    monkeypatch.setattr(bot, "random", _First())

    assert (await read(ground_floor)).startswith(ROW)


async def test_and_the_four_extras_can_be_drawn(ground_floor, monkeypatch):
    """Which is what the shipping box's refusals could not do for a month:
    written, approved, and never once reached."""
    monkeypatch.setattr(bot, "random", _Last())

    assert (await read(ground_floor)).startswith(LAST_EXTRA)


async def test_the_pool_is_five_lines_and_all_of_them_the_writers(
    ground_floor, monkeypatch
):
    """Nothing invented, nothing borrowed from another thing, and nothing
    missing. The count is the assertion the prefix match could get wrong
    in either direction - a typo in the id gives four, and a prefix one
    character short would reach every `use.` key there is."""
    rng = _Records()
    monkeypatch.setattr(bot, "random", rng)
    await read(ground_floor)

    written = set(await phrasing.defaults_matching("use.board_books."))
    written.add(
        await resolve.thing_text(GUILD_A, "board_books", "use", resolve.DEFAULT_STATE)
    )

    assert len(rng.pools) == 1
    assert set(rng.pools[0]) == written
    assert len(written) == 5


async def test_a_thing_with_no_extras_never_draws(ground_floor, monkeypatch):
    """Which is every other thing in the game. The pool is found by
    prefix, so a thing with nothing under its own prefix must not reach
    the picker at all - a one-line pool would still be a coin toss with
    one side, and the next thing to get extras would inherit it."""
    rng = _Records()
    monkeypatch.setattr(bot, "random", rng)

    written = next(
        r.text["use"] for r in content_module.load_files().thing_text
        if r.entity_id == "picnic_blanket" and r.state == "default"
    )

    reply = await read(ground_floor, thing="picnic blanket", room="CO")

    assert written in reply
    assert rng.pools == []
# --------------------------------------------------------------------------
# And the check that stops the next set of them going unread
# --------------------------------------------------------------------------


def test_an_extra_line_written_for_no_thing_is_caught_at_load():
    """**The one failure mode this shape has**, and the reason the toy
    refusals got the same check: the pool is found by prefix, so a key
    with a typo in the id is read by nothing and reported by nothing.
    The thing falls back to its own row, the player reads a perfectly
    good line, and the extras are never seen by anybody.
    """
    world_ = a_world(a_thing("odd_lamp"))
    world_.defaults["use.odd_lmap.1"] = "You turn the odd lamp over."

    problems = content_module.validate(world_)

    assert any("odd_lmap" in problem for problem in problems)


def test_an_extra_line_for_a_real_thing_is_fine():
    world_ = a_world(a_thing("odd_lamp"))
    world_.defaults["use.odd_lamp.1"] = "You turn the odd lamp over."

    problems = content_module.validate(world_)

    assert not any("odd_lamp" in problem for problem in problems)


def test_the_house_fallback_is_not_mistaken_for_one():
    """`use.default` is the line every thing with nothing written falls
    to, and it owns no thing. A check reading the prefix alone would
    have reported the house's own string as a typo on every load."""
    world_ = a_world(a_thing("odd_lamp"))
    assert "use.default" in world_.defaults

    problems = content_module.validate(world_)

    assert not any("use.default" in problem for problem in problems)


# ------------------------------------------------------------------------
# The courtyard, after a playtest
#
# Four things the reports asked for that are not copy edits. The
# rattle stops being scenery, the cap stops borrowing the fixture's
# refusal, and `take` starts reading the room the way `use` has since
# the ladder.
# ------------------------------------------------------------------------


def posted(ground_floor, room_name) -> list[str]:
    """Everything the room has been told, newest last."""
    return list(thread(ground_floor, room_name).posted)


async def test_the_rattle_comes_out_of_the_blanket(ground_floor):
    """It was a fixture with a refusal, which is the house saying no.

    It is one copy inside the blanket now, so it is also the first
    thing in the Courtyard a player can pick up besides the ladder.

    **Loaded again here, and that is not boilerplate.** This file's
    fixture loads the content before anybody exists, and the loader
    places stock into the guilds the `users` table has seen - so every
    other test in this file runs in a house with no stock on the floor
    at all, which is exactly what they want. A take needs the copy to
    be there.
    """
    db, *_ = ground_floor
    await content_loader.load_content(
        content_module.load_files(), guild_ids=[GUILD_A]
    )

    await run(ground_floor, bot.take, "rattle", room="CO")

    assert await db.carried_of(ALICE, GUILD_A, "rattle") == 1


async def test_and_shaking_it_is_for_the_whole_room(ground_floor):
    """The only `/use` in the game whose reply is public and nothing
    else.

    Every other one is private, because a use is a small private
    moment; a rattle shaken in an empty garden is a joke, and a joke
    told privately has no audience. Asserted both ways round - in the
    thread, and *not* in the player's own reply - because `public`
    routing that posted and also whispered would read as working.
    """
    db, *_ = ground_floor
    await carry(db, ALICE, GUILD_A, "rattle")

    interaction = await run(ground_floor, bot.use, "rattle", room="CO")

    assert any(
        "Rattle rattle!" in line for line in posted(ground_floor, "Courtyard")
    )
    assert "Rattle rattle!" not in replies(interaction)


async def test_a_second_can_opener_is_refused_in_its_own_words(ground_floor):
    """The cap read out `take_fail.fixture` - "the can opener is not
    yours to carry off" - to a player who had just been handed one off
    the hook and was holding it. Two things were wrong and both are
    fixed here: the opener has a line of its own now, and the branch
    no longer reaches for the one about ownership."""
    await run(ground_floor, bot.take, "can opener", room="KI")

    reply = replies(await run(ground_floor, bot.take, "can opener", room="KI"))

    assert "Why would you need two?" in reply
    assert "yours to carry off" not in reply


async def test_the_burrito_is_taken_differently_off_the_floor(ground_floor):
    """`in:XX` rows were built for the ladder's six climbs and were
    only ever read on a `use`, so a writer who gave a thing a line for
    one room got it when the thing was used and not when it was
    picked up.

    The freezer is the case that asked for it: a burrito comes out of
    a stack in the Kitchen and off the floor everywhere else, and the
    room is what tells those apart. Both halves here, because a change
    that made every take read the Kitchen row would pass on the first
    assertion alone.
    """
    await run(ground_floor, bot.take, "burrito", room="KI")
    await run(ground_floor, bot.drop, "burrito", room="CO")
    kitchen = posted(ground_floor, "Kitchen")

    await run(ground_floor, bot.take, "burrito", room="CO")
    off_the_floor = posted(ground_floor, "Courtyard")[-1]

    assert any("works one loose from the stack" in line for line in kitchen)
    assert "somebody abandoned here" in off_the_floor
    assert "from the stack" not in off_the_floor


async def test_the_chips_are_eaten_quietly_anywhere_else(ground_floor):
    """The same rule on the verb it already worked for, worth a test of
    its own only because the two lines are a pair: the one about the
    sink names a thing the Courtyard does not have."""
    db, *_ = ground_floor
    await carry(db, ALICE, GUILD_A, "nacho_chips", 2)

    kitchen = replies(await run(ground_floor, bot.use, "chips", room="KI"))
    courtyard = replies(await run(ground_floor, bot.use, "chips", room="CO"))

    assert "over the sink" in kitchen
    assert "not very quietly" in courtyard
    assert "sink" not in courtyard
