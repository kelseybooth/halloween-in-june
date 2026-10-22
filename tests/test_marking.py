"""Which lines in a room description are new to you.

A playtester came back from drop 1's second stage unable to tell which
sentences they had already read. That is a defect in the staged reveal
rather than in the prose, and it recurs at every drop that adds a
fragment to a room somebody has already looked at - so it is answered
once, for every room, rather than for the channel alone.

The marking is italics and nothing else: no label, no glyph. What is
tested here is *which* sentences get them, because that is where the
bugs are. The channel is the subject throughout because it is the only
room with more than one fragment today; nothing in the rule knows that.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import resolve


BRANCHES = "**Branches** reach out over the road"
FENCE = "Behind the stand a **fence** sags"


@pytest.fixture
async def channel(db):
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
    return interaction.reply


def marked(reply):
    """The sentences wrapped in italics, as a list."""
    parts = reply.split("\n")[0].split("_")
    return [chunk for n, chunk in enumerate(parts) if n % 2]


# --------------------------------------------------------------------------
# The first look is never marked
# --------------------------------------------------------------------------


async def test_a_first_look_marks_nothing(channel):
    """Otherwise a new player's opening `/look` arrives entirely in
    italics, which says "all of this is new" to somebody for whom
    nothing can be old."""
    assert marked(await look(channel)) == []


async def test_the_first_look_still_writes_the_rows(channel):
    """The half that makes the rule work. If a first look recorded
    nothing because it marked nothing, the *second* look would be the
    one that came out entirely italic - the same bug, one command
    later."""
    await look(channel)

    assert marked(await look(channel)) == []


async def test_a_first_look_is_per_player(channel):
    """Bob's first look is Bob's, whatever Alice has read. The rows are
    keyed on the player, which is the whole reason the hints table was
    the right place to put them."""
    await look(channel)
    await look(channel, "cat bed")
    await look(channel)

    assert marked(await look(channel, who=BOB)) == []


# --------------------------------------------------------------------------
# What arrives afterwards
# --------------------------------------------------------------------------


async def test_the_second_stage_arrives_marked(channel):
    """The case the playtester hit: three sentences appear in the middle
    of a paragraph they have already read, and nothing said which."""
    await look(channel)
    await look(channel, "cat bed")

    new = marked(await look(channel))

    assert len(new) == 3
    assert any(BRANCHES in line for line in new)


async def test_only_the_new_sentences_are_marked(channel):
    """The other half, and the one a naive implementation gets wrong by
    marking the whole paragraph the moment anything in it changes."""
    await look(channel)
    await look(channel, "cat bed")

    reply = await look(channel)

    assert FENCE in reply
    assert not any(FENCE in line for line in marked(reply))


async def test_marking_fires_once(channel):
    """Emphasis that never goes away is not emphasis."""
    await look(channel)
    await look(channel, "cat bed")
    await look(channel)

    assert marked(await look(channel)) == []


async def test_a_player_who_never_looked_first_sees_no_marks(channel):
    """Bob reaches the second stage before ever reading the room, so his
    opening paragraph is six sentences he has never seen. Marking them
    would be true and useless - new to him is all of it."""
    await look(channel, "cat bed", who=BOB)

    reply = await look(channel, who=BOB)

    assert BRANCHES in reply
    assert marked(reply) == []


# --------------------------------------------------------------------------
# The seams
# --------------------------------------------------------------------------


async def test_the_text_is_otherwise_untouched(channel):
    """Marking adds two characters to a sentence and changes nothing
    else about it - not the order, not the spacing, not the bolding
    inside."""
    await look(channel)
    await look(channel, "cat bed")

    marked_reply = (await look(channel)).split("\n")[0]
    plain = (await look(channel)).split("\n")[0]

    assert marked_reply.replace("_", "") == plain


async def test_italics_are_underscores_not_asterisks(channel):
    """**Not a style preference.** Every sentence that can be marked has
    bolding in it, because bolding is how a scenery noun announces
    itself - and `*a **b** c*` asks a markdown parser to decide where
    one emphasis ends and the next begins. `_` cannot collide with `**`
    at all."""
    await look(channel)
    await look(channel, "cat bed")

    reply = await look(channel)

    assert "_**Branches**" in reply
    assert "***" not in reply


async def test_resetting_a_player_returns_them_to_a_first_look(channel):
    """`forget_player` is table-driven and the rows went with everything
    else, which is right - a tester who has to re-earn stage 2 would
    otherwise re-earn it already marked as read."""
    await look(channel)
    await look(channel, "cat bed")
    await look(channel)

    await database.forget_player(GUILD_A, ALICE)
    await look(channel, "cat bed")

    assert marked(await look(channel)) == []


async def test_a_house_room_is_never_marked(channel):
    """Nine rooms have one fragment each and nothing ever adds to them,
    so the rule is a no-op there - which is the point of doing it
    generally rather than in the channel's own renderer. It costs those
    rooms one row per player and no reading change at all."""
    db, _, _ = channel
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.start_game(ALICE, GUILD_A, "EN", ["EN"])

    first = await bot._describe_room(GUILD_A, ALICE, "EN", resolve.DEFAULT_STATE)
    second = await bot._describe_room(GUILD_A, ALICE, "EN", resolve.DEFAULT_STATE)

    assert "_" not in (first or "")
    assert first == second
