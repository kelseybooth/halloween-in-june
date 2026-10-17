"""The channel as a room, and `/look` in it.

Three drops happen somewhere the room model did not contain, and drop 1
needs `/look` there. So the channel is a room row - `CH`, no exits, never
listed, never walked to - and the cat bed is an ordinary thing with an
ordinary `room_id`, resolved through the ordinary path.

What it is *not* is a room with prose. A `room_text` row for `CH` is a
load error, and that settles what the channel's description says: nothing.
`/look` there prints a list instead, and because there is no prose to name
the scenery, that list names fixtures too - which is the one way it
differs from `Also here:` in the nine rooms.
"""

import pytest

from conftest import ALICE, GUILD_A, HOUSE_DROP
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import resolve

BED = "A round cushion in dark green corduroy"


@pytest.fixture
async def channel(db):
    """A server whose game has been started, sitting on drop 0."""
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, name="Test Server", channels=[halloween], members=[FakeMember(ALICE)]
    )
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, 0)
    return db, guild, halloween


async def look(channel, thing=None):
    _, guild, halloween = channel
    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    await bot.look.callback(interaction, thing)
    return interaction


# --------------------------------------------------------------------------
# The list
# --------------------------------------------------------------------------


async def test_the_bed_is_listed_once_its_drop_opens(channel):
    """Asserted as the whole line, spacing included.

    The old version checked for "Items here:" and "cat bed"
    separately, and so passed happily against "Items here:cat bed" -
    which is what drop 1 shipped. A label and its contents are one
    rendered string and are worth asserting as one.
    """
    await resolve.set_current_drop(GUILD_A, 1)

    interaction = await look(channel)

    assert "Items here: cat bed" in interaction.reply


async def test_a_fixture_is_listed_even_though_it_is_not_in_room_contents(channel):
    """The difference from `Also here:`, and the reason the channel needs
    its own renderer: `loose_here` reads `room_contents`, which fixtures
    never enter."""
    await resolve.set_current_drop(GUILD_A, 1)
    async with database._require_session()() as session:
        from sqlalchemy import func, select

        placed = await session.scalar(
            select(func.count())
            .select_from(database.RoomContents)
            .where(database.RoomContents.guild_id == GUILD_A)
        )
    assert placed == 0

    assert "Items here: cat bed" in (await look(channel)).reply


async def test_the_cat_is_not_in_the_list(channel):
    """`/look cat` is an easter egg, found rather than signposted. A list
    reading "a cat, a cat bed" would hand over the only discovery drops 0
    and 1 have."""
    await resolve.set_current_drop(GUILD_A, 1)

    reply = (await look(channel)).reply

    assert "cat bed" in reply
    assert "cat," not in reply


async def test_there_is_no_description(channel):
    """The channel's prose is the empty string on purpose."""
    await resolve.set_current_drop(GUILD_A, 1)

    reply = (await look(channel)).reply

    assert reply.startswith("Items here:")


async def test_before_the_bed_there_is_nothing_to_list(channel):
    interaction = await look(channel)

    assert "Nothing here but the cat" in interaction.reply


async def test_the_reply_is_private(channel):
    assert (await look(channel)).was_private


# --------------------------------------------------------------------------
# Looking at one thing, in a place with no player row
# --------------------------------------------------------------------------


async def test_the_bed_can_be_looked_at(channel):
    await resolve.set_current_drop(GUILD_A, 1)

    interaction = await look(channel, "cat bed")

    assert BED in interaction.reply


async def test_an_alias_works_too(channel):
    await resolve.set_current_drop(GUILD_A, 1)

    assert BED in (await look(channel, "cushion")).reply


async def test_the_bed_is_not_there_before_its_drop(channel):
    interaction = await look(channel, "cat bed")

    assert BED not in interaction.reply


async def test_the_cat_can_be_looked_at_from_drop_zero(channel):
    """Her row is the one thing in the files at drop 0, and `/look cat` is
    why it has to be."""
    interaction = await look(channel, "cat")

    assert "black cat" in interaction.reply


async def test_none_of_this_needs_a_player_row(channel):
    """`/enter` does not exist at the drops where the channel is the only
    place there is, so nobody standing in it has a game state."""
    assert await database.get_game_state(ALICE, GUILD_A) is None

    assert (await look(channel, "cat")).reply


async def test_the_house_is_not_reachable_from_here(channel):
    """Even at the drop where the whole house exists, the channel can only
    see what is in the channel. Asserted on the coat rack's own prose
    rather than on the refusal, which names the thing you asked for and so
    would contain the words either way."""
    await resolve.set_current_drop(GUILD_A, HOUSE_DROP)

    interaction = await look(channel, "coat rack")

    assert "bentwood" not in interaction.reply.lower()


# --------------------------------------------------------------------------
# The rooms are untouched
# --------------------------------------------------------------------------


def test_the_channel_may_not_have_prose():
    """Asserted against the real validator, because the rule only works if
    the loader refuses the row rather than the renderer ignoring it."""
    import content as module

    parsed = module.load_files()
    parsed.room_text.append(
        module.TextRow(
            entity_id=module.CHANNEL_ROOM,
            state="default",
            since_drop=0,
            text={"look": "A channel."},
        )
    )

    problems = module.validate(parsed)

    assert any("must have no text row" in p for p in problems)


def test_no_exit_may_touch_the_channel():
    """Never reachable by movement, enforced in both directions."""
    import content as module

    parsed = module.load_files()
    assert not [
        t
        for t in parsed.things
        if t.is_exit and module.CHANNEL_ROOM in (t.room_id, t.destination_room_id)
    ]
