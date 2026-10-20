"""Drop 1's channel scenery: the fog, the fence, and what is under them.

Playtesters reported drop 1 as empty. They were right, and the reason
was structural rather than a thin paragraph: the channel was forbidden
prose, so `/look` printed `Also here: cat bed` and there was nothing
else in the world to type. Ten scenery nouns and a six-fragment
description give the drop something to be about, and the fragments
arrive in two stages so that looking at the bed changes the view.

What is tested here is the staging, because that is where the bugs
live. The prose itself is the writers' and is asserted only where the
engine's behaviour depends on it.
"""

import dataclasses

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import hints
import reach
import resolve
import world


@pytest.fixture
async def channel(db):
    """A server on drop 1, where the scenery lives."""
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A,
        name="Test Server",
        channels=[halloween],
        members=[FakeMember(ALICE), FakeMember(BOB)],
    )
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, 1)
    return db, guild, halloween


async def look(channel, thing=None, who=ALICE):
    _, guild, halloween = channel
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await bot.look.callback(interaction, thing)
    return interaction


async def use(channel, thing, who=ALICE):
    _, guild, halloween = channel
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await bot.use.callback(interaction, thing)
    return interaction


# --------------------------------------------------------------------------
# The two stages
# --------------------------------------------------------------------------


async def test_a_new_player_sees_three_fragments(channel):
    """The road, the fence, the smell of the air. Not the branches."""
    reply = (await look(channel)).reply

    assert "**road**" in reply
    assert "**fence**" in reply
    assert "cold and wet earth" in reply
    assert "**Branches**" not in reply
    assert "**Tire tracks**" not in reply


async def test_looking_at_the_bed_opens_the_other_three(channel):
    await look(channel, "cat bed")

    reply = (await look(channel)).reply

    assert "**Branches**" in reply
    assert "**Tire tracks**" in reply
    assert "too square to be trees" in reply


async def test_an_unlocked_fragment_takes_its_numbered_place(channel):
    """Ordered by `fragment`, never by arrival.

    The branches are sentence two. Appending them on unlock would put
    them after the tire tracks and read as a different paragraph to the
    player who earned them than to the writer who wrote it.
    """
    await look(channel, "cat bed")

    reply = (await look(channel)).reply

    assert reply.index("**Branches**") < reply.index("**fence**")
    assert reply.index("**fence**") < reply.index("**Tire tracks**")
    assert reply.index("**Tire tracks**") < reply.index("cold and wet earth")


async def test_the_stage_is_per_player(channel):
    """Alice looking at the bed does not thin Bob's fog.

    The gate reads the hint ladder's per-player row, which is the whole
    reason this could be done without the general per-player
    `present_when` the V3.2 list is holding.
    """
    await look(channel, "cat bed", who=ALICE)

    assert "**Branches**" in (await look(channel, who=ALICE)).reply
    assert "**Branches**" not in (await look(channel, who=BOB)).reply


async def test_the_channel_is_still_bare_at_drop_zero(channel):
    """The scenery is drop 1's, and drop 0 is the cat alone."""
    await resolve.set_current_drop(GUILD_A, 0)

    reply = (await look(channel)).reply

    assert "**road**" not in reply
    assert "Nothing here but the cat" in reply


# --------------------------------------------------------------------------
# The notice
# --------------------------------------------------------------------------


async def test_the_first_look_at_the_bed_says_the_fog_thinned(channel):
    """Otherwise nothing tells the player to look again, and the three
    sentences they unlocked are never read."""
    reply = (await look(channel, "cat bed")).reply

    assert "the fog has thinned" in reply


async def test_it_is_not_labelled_as_a_hint(channel):
    """Italic, unlabelled, and not from the rail. It reports something
    that happened rather than recommending an action, and the rail's
    budget is spent on `/use`."""
    reply = (await look(channel, "cat bed")).reply

    assert "*When you look up from the bed, the fog has thinned slightly.*" in reply
    assert "Hint: When you look up" not in reply

    # Above the hint: it reports what happened, the hint recommends what
    # to do, and the rail owns the last line everywhere else.
    assert reply.index("fog has thinned") < reply.index("Hint:")


async def test_it_fires_once(channel):
    await look(channel, "cat bed")

    assert "the fog has thinned" not in (await look(channel, "cat bed")).reply


async def test_it_does_not_fire_for_other_scenery(channel):
    assert "the fog has thinned" not in (await look(channel, "fence")).reply


# --------------------------------------------------------------------------
# Looking at the nouns
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed",
    ["road", "fog", "fence", "ditch", "ruts", "leaves", "field", "wasp nest"],
)
async def test_every_bolded_noun_answers(channel, typed):
    """Bolding is a promise. The loader checks the content side of it;
    this checks that `/look` in the channel actually resolves them."""
    await look(channel, "cat bed")

    reply = (await look(channel, typed)).reply

    assert "no such thing" not in reply
    assert len(reply) > 40


async def test_a_second_layer_is_reached_through_the_first(channel):
    """The ditch is named by the road, not by the paragraph. Two or three
    nouns opening onto two or three more is the shape the drop needed."""
    road = (await look(channel, "road")).reply

    assert "**ditch**" in road
    assert "leaves" in (await look(channel, "ditch")).reply


async def test_an_alias_works(channel):
    assert "no such thing" not in (await look(channel, "mist")).reply


# --------------------------------------------------------------------------
# Using what cannot be used
# --------------------------------------------------------------------------


async def test_a_fixture_refuses_in_its_own_words(channel):
    """`use.default` is "you turn the {name} over in your hands", which is
    nonsense on a ditch - and `/use` is one of only two verbs drop 1 has,
    so every scenery noun is one command away from it."""
    reply = (await use(channel, "ditch")).reply

    assert "nothing to do with the ditch but look at it" in reply
    assert "over in your hands" not in reply


async def test_the_refusal_is_private(channel):
    assert (await use(channel, "fence")).was_private


async def test_a_refused_use_is_not_recorded(channel):
    """It never happened, so it must not count as a use - `thing_uses` is
    what cooldowns and achievements read."""
    from sqlalchemy import func, select

    await use(channel, "fence")

    async with database._require_session()() as session:
        rows = await session.scalar(
            select(func.count())
            .select_from(database.ThingUse)
            .where(database.ThingUse.thing_id == "fence")
        )

    assert rows == 0


async def test_a_house_fixture_is_left_alone(channel):
    """**The refusal is scoped to scenery, not to `takeable = no`.**

    The argument for it reads as though it should cover the stove too,
    and the work order words it that way. But a house fixture with a
    blank `use` cell falls through to `use.default` *and counts as a
    use*, which `test_verbs.py` pins on purpose because use counts feed
    achievements - so widening this would change shipped drop-3
    behaviour from a patch whose scope says the only thing that changes
    is what `/look` prints in the channel.

    Asserted on the cat bed, which is `takeable = no` and not scenery.
    """
    row = content_module.load_files().things_by_id[world.CAT_BED]

    assert row.takeable is False
    assert row.type != content_module.SCENERY


async def test_the_bed_still_works(channel):
    """The fixture refusal must not swallow a fixture that has use text."""
    reply = (await use(channel, "cat bed")).reply

    assert "nothing to do with" not in reply


async def test_the_wasp_nest_cannot_be_taken(channel):
    """Written now and unreachable until `/take` ships at drop 2 -
    somebody will try it on the first day it exists."""
    rows = content_module.load_files().thing_text
    nest = [r for r in rows if r.entity_id == "wasp_nest"]

    assert any("decide against it" in r.text.get("take_fail", "") for r in nest)


# --------------------------------------------------------------------------
# The gate is the ladder's row, and nothing else
# --------------------------------------------------------------------------


async def test_the_gate_reads_the_ladder(channel):
    """Named rather than inferred, because the day the rail renames
    `DID_LOOK_BED` is the day the fog stops lifting, and the failure is
    silent - a paragraph that is simply shorter than it should be."""
    assert await bot._unlocked_for(GUILD_A, ALICE) == frozenset()

    await database.notice(GUILD_A, ALICE, hints.DID_LOOK_BED)

    assert await bot._unlocked_for(GUILD_A, ALICE) == frozenset(
        {content_module.LOOKED_AT_BED}
    )

# --------------------------------------------------------------------------
# Every noun, every alias, every refusal
# --------------------------------------------------------------------------

SCENERY = (
    "road", "fog", "branches", "fence", "ruts",
    "ditch", "leaves", "wasp_nest", "field", "tire_tracks",
)


def _aliases():
    things = content_module.load_files().things_by_id
    return [(t, name) for t in SCENERY for name in things[t].names]


@pytest.mark.parametrize("thing_id,typed", _aliases())
async def test_every_alias_resolves(channel, thing_id, typed):
    """`/look posts`, `/look mud`, `/look culvert` and the other
    thirty-odd. Aliases are where a scene like this is won or lost: the
    player types the word they thought of, not the word in the row."""
    found = await reach.find(GUILD_A, ALICE, content_module.CHANNEL_ROOM, typed,
                             reach.Scope.REACH)

    assert isinstance(found, reach.Found), f"{typed!r} -> {found}"
    assert found.thing_id == thing_id


@pytest.mark.parametrize("thing_id", SCENERY)
async def test_every_scenery_noun_refuses_use(channel, thing_id):
    """Definition of done 3. None of the ten has `use` text and none
    should: a scenery row that pays out a relationship point is farmed
    by whoever finds the cheapest one, and the bed's once-a-day economy
    stops meaning anything."""
    name = content_module.load_files().things_by_id[thing_id].name

    reply = (await use(channel, name)).reply

    assert f"nothing to do with the {name} but look at it" in reply


async def test_no_scenery_row_has_use_text():
    """Asserted against the files rather than the rendered reply, so a
    `use` string added later fails here rather than quietly turning one
    of the ten into a second bed."""
    parsed = content_module.load_files()

    for row in parsed.thing_text:
        if row.entity_id in SCENERY:
            assert "use" not in row.text, row.entity_id


# --------------------------------------------------------------------------
# What the prose must not mention
# --------------------------------------------------------------------------


async def test_nothing_from_a_later_drop_is_named():
    """The leak test. The mailbox is drop 2 and carries David's name with
    it; the house, its door and the drive are drop 3. A channel string
    that mentions one spends the reveal weeks early, for free.

    Four words rather than a wordlist, because the channel prose is
    ordinary English and a loose list catches "the ground opens" and
    "one lets go" - which would train whoever next edits it to delete
    the check instead of the leak.
    """
    import re

    parsed = content_module.load_files()
    here = {t.thing_id for t in parsed.things if t.room_id == content_module.CHANNEL_ROOM}
    blobs = [r.text.get("look", "") for r in parsed.room_text
             if r.entity_id == content_module.CHANNEL_ROOM]
    blobs += [v for r in parsed.thing_text if r.entity_id in here
              for v in r.text.values()]
    prose = " ".join(blobs).lower()

    for word in ("room", "rooms", "mailbox", "drive", "driveway", "door", "doors"):
        assert not re.search(rf"{word}", prose), word


# --------------------------------------------------------------------------
# The three loader checks, each against a deliberately broken copy
# --------------------------------------------------------------------------


def _broken(mangle):
    parsed = content_module.load_files()
    mangle(parsed)
    return content_module.validate(parsed)


def test_the_shipped_files_pass_all_three():
    assert not content_module.validate(content_module.load_files())


def test_a_bolded_word_with_no_row_behind_it_fails():
    """The player types the one noun the game just pointed at and is
    told the house has no such thing."""

    def mangle(parsed):
        for row in parsed.room_text:
            if row.entity_id == content_module.CHANNEL_ROOM and row.fragment == 1:
                row.text["look"] += " A **lamppost** stands here."

    assert any("lamppost" in p for p in _broken(mangle))


def test_a_bolded_word_that_has_not_arrived_yet_fails():
    """A drop-1 fragment bolding a drop-2 thing is the same failure
    arriving on a timer."""

    def mangle(parsed):
        for row in parsed.room_text:
            if row.entity_id == content_module.CHANNEL_ROOM and row.fragment == 1:
                row.text["look"] += " A **feather wand** lies here."

    assert any("until drop 2" in p for p in _broken(mangle))


def test_unbolding_a_scenery_noun_fails():
    """The inverse, and the one that will fire during authoring: trim
    *ruts* out of `road.look` and the row becomes unreachable by any
    path, with nothing logged."""

    def mangle(parsed):
        for row in parsed.thing_text:
            if row.entity_id == "road":
                row.text["look"] = row.text["look"].replace("**ruts**", "ruts").replace(
                    "**Ruts**", "Ruts"
                )

    assert any("scenery ruts is bolded nowhere" in p for p in _broken(mangle))


def test_a_second_person_take_line_fails():
    """`/take` and `/drop` are the only texts in the game with an
    audience other than the person who typed the command, and for a
    release they did not know it. All thirty-two were rewritten; this
    is what stops the thirty-third arriving in the old voice."""

    def mangle(parsed):
        for row in parsed.thing_text:
            if row.text.get("take"):
                row.text["take"] = "You pocket it, guiltily."
                return

    assert any("posted to the room" in p for p in _broken(mangle))


def test_a_misspelled_gate_fails():
    """The enum has one member, which is exactly why this is checked. A
    typo in that one word raises nothing: the fragment loads, the gate
    never matches, and the sentence is invisible to every player
    forever."""

    def mangle(parsed):
        parsed.room_text[:] = [
            dataclasses.replace(row, visible_when="looked_at_the_bed")
            if row.visible_when
            else row
            for row in parsed.room_text
        ]

    assert any("not a visibility gate" in p for p in _broken(mangle))


def test_a_scenery_alias_shared_with_anything_else_fails():
    """`tree` and `wire` both failed this on the first run, which is why
    neither is an alias today - `tree` is already the Courtyard's and
    `wire` becomes the copper wire's the day a player can carry one
    outdoors."""

    def mangle(parsed):
        things = parsed.things_by_id
        fence = things["fence"]
        parsed.things[parsed.things.index(fence)] = dataclasses.replace(
            fence, aliases=fence.aliases + ("wire",)
        )

    assert any("scenery fence answers to 'wire'" in p for p in _broken(mangle))


# --------------------------------------------------------------------------
# Back to stage one
# --------------------------------------------------------------------------


async def test_resetting_a_player_returns_them_to_stage_one(channel):
    """Definition of done 6. `forget_player` is table-driven, so the
    notices went with everything else - but the staging is a new reason
    to care, and a reset that left stage 2 latched would make the
    sequence testable exactly once per tester per server."""
    await look(channel, "cat bed")
    assert "**Branches**" in (await look(channel)).reply

    await database.forget_player(GUILD_A, ALICE)

    reply = (await look(channel)).reply
    assert "**Branches**" not in reply
    assert "the fog has thinned" in (await look(channel, "cat bed")).reply
