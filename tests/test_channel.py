"""The channel as a room, and `/look` in it.

Three drops happen somewhere the room model did not contain, and drop 1
needs `/look` there. So the channel is a room row - `CH`, no exits, never
listed, never walked to - and the cat bed is an ordinary thing with an
ordinary `room_id`, resolved through the ordinary path.

It used to be a room without prose: a `room_text` row for `CH` was a load
error, and `/look` printed a bare list. Playtesters found drop 1 empty for
exactly that reason, so the channel now has a description like any other
room and the list sits under it. The scenery that description names lives
in `test_scenery.py`; what is tested here is the channel as a room.
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


async def test_drop_one_is_prose_with_no_list_at_all(channel):
    """**The rule the house has always followed, restored here.**

    `Also here:` carries finite takeables and nothing else, and the
    prose names everything else - so a noun is on the line or in a
    sentence, never both. The channel strayed from that only because it
    had no prose to name anything with. It has prose now, the bed is
    named inside the stand it sits in, and drop 1 has nothing loose in
    it, so the whole reply is the description.
    """
    await resolve.set_current_drop(GUILD_A, 1)

    reply = (await look(channel)).reply

    assert reply.startswith("A derelict farm **stand**")
    assert "Also here:" not in reply


async def test_a_fixture_is_never_listed(channel):
    """A fixture has no presence row - `loose_here` reads
    `room_contents`, which the cat bed never enters - and that is now
    the whole answer rather than a reason to read a second table. The
    loader enforces the other half: a fixture no prose names is a load
    error, because nothing else would ever reveal it."""
    await resolve.set_current_drop(GUILD_A, 1)
    async with database._require_session()() as session:
        from sqlalchemy import func, select

        placed = await session.scalar(
            select(func.count())
            .select_from(database.RoomContents)
            .where(database.RoomContents.guild_id == GUILD_A)
        )
    assert placed == 0

    assert "Also here:" not in (await look(channel)).reply


async def test_a_taken_toy_leaves_the_list(channel):
    """**The list is two queries, and this is why.**

    It used to be one: everything whose *home room* is the channel, read
    straight out of the content table. That is correct for the cat bed,
    which is a fixture and never enters `room_contents` - the test above
    pins exactly that. It is wrong for anything a player can pick up,
    because a home room does not move when the thing does.

    Drop 1 hid it, having only the fixture. Drop 2 put two takeable toys
    in the same room and the wand stayed on the line after it had been
    taken, which reads as an endless supply: a playtester took it twice.
    """
    _, guild, halloween = channel
    await resolve.set_current_drop(GUILD_A, 2)
    for toy in ("feather_wand", "crinkle_ball"):
        await database.place_in_room(GUILD_A, content_module.CHANNEL_ROOM, toy, 1)

    assert "Also here: feather wand, crinkle ball" in (await look(channel)).reply

    taking = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    await bot.take.callback(taking, "feather wand")

    assert "Also here: crinkle ball" in (await look(channel)).reply


async def test_taking_the_last_loose_thing_leaves_prose_alone(channel):
    """The other half of the same split. The line goes away entirely
    rather than shrinking to the cat bed, because the bed was never on
    it - and the description is still standing underneath, which is why
    an empty list is not an empty room."""
    _, guild, halloween = channel
    await resolve.set_current_drop(GUILD_A, 2)
    await database.place_in_room(
        GUILD_A, content_module.CHANNEL_ROOM, "feather_wand", 1
    )

    taking = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    await bot.take.callback(taking, "feather wand")

    reply = (await look(channel)).reply

    assert "Also here:" not in reply
    assert "**stand**" in reply


async def test_the_cat_is_not_in_the_list(channel):
    """`/look cat` is an easter egg, found rather than signposted. A list
    reading "a cat, a cat bed" would hand over the only discovery drops 0
    and 1 have."""
    await resolve.set_current_drop(GUILD_A, 1)

    reply = (await look(channel)).reply

    assert "cat bed" in reply
    assert "cat," not in reply


async def test_the_description_sits_above_the_list(channel):
    """The channel used to have no prose on purpose. Playtesters found
    drop 1 empty for exactly that reason - `/look` offered them one
    noun - so it now reads like the room-like row it always was."""
    await resolve.set_current_drop(GUILD_A, 1)

    reply = (await look(channel)).reply

    assert reply.startswith("A derelict farm **stand** with a sound tin roof")
    assert "Also here:" not in reply


async def test_nothing_fixed_reaches_the_list(channel):
    """Bolded in the prose, absent from the list.

    Asserted at drop 2, because that is the first drop where there is a
    list to be absent from. A line reading "a road, a fog, a ditch, a
    cat bed, a feather wand" would bury the one noun on it a player can
    do anything with."""
    await resolve.set_current_drop(GUILD_A, 2)
    await database.place_in_room(
        GUILD_A, content_module.CHANNEL_ROOM, "feather_wand", 1
    )

    reply = (await look(channel)).reply
    listed = reply.split("Also here:")[1]

    assert "**road**" in reply
    for fixed in ("road", "fog", "stand", "fence", "cat bed"):
        assert fixed not in listed, fixed
    assert "feather wand" in listed


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


def test_the_channel_may_now_have_prose():
    """The inverse of the rule this file used to assert.

    A `room_text` row for the channel was a load error until drop 1's
    scenery. The reason it was banned - that the channel is not a room
    and must never become reachable - is enforced by the exits, which
    the next test still checks, not by keeping it mute.
    """
    import content as module

    parsed = module.load_files()
    rows = [r for r in parsed.room_text if r.entity_id == module.CHANNEL_ROOM]

    assert rows, "the channel's description is the point of drop 1"
    assert not module.validate(parsed)


def test_no_exit_may_touch_the_channel():
    """Never reachable by movement, enforced in both directions."""
    import content as module

    parsed = module.load_files()
    assert not [
        t
        for t in parsed.things
        if t.is_exit and module.CHANNEL_ROOM in (t.room_id, t.destination_room_id)
    ]
