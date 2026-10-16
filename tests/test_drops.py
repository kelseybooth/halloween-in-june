"""The drop machine: one pointer, and the two commands that move it.

A server sits on one drop. Everything numbered at or below it has arrived;
everything above it is loaded, present in the files, and unreachable. That
is the whole rule, and it replaced a calendar - dated arrival plus a row
per arrived drop were two more answers to a question that now has one.

The property the proof of concept exists to prove is at the bottom: two
servers on different drops at the same time, each seeing its own game.
"""

import pytest

from conftest import ALICE, GUILD_A, GUILD_B, HOUSE_DROP
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import reach
import resolve
from content import Content, Drop, Room, TextRow

CAT = "eunoia"
BED = "cat_bed"


@pytest.fixture
async def started(db):
    """One server with content loaded and no game started in it yet."""
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, name="Test Server", channels=[halloween], members=[FakeMember(ALICE)]
    )
    await unstart(GUILD_A)
    await unstart(GUILD_B)
    return db, guild, halloween


async def unstart(guild_id):
    """Undo the fixture's helpfulness: this file is about not being started."""
    async with database._require_session()() as session:
        table = database.ServerConfig.__table__
        await session.execute(
            table.delete().where(
                table.c.guild_id == guild_id, table.c.key == resolve.DROP_KEY
            )
        )
        await session.commit()


def an_admin(guild, channel):
    return FakeInteraction(ALICE, guild.id, guild=guild, channel=channel)


async def start(started, channel=None):
    _, guild, halloween = started
    interaction = an_admin(guild, halloween)
    await bot.start_game.callback(interaction, channel or halloween)
    return interaction


async def advance(started, confirm=True):
    _, guild, halloween = started
    interaction = an_admin(guild, halloween)
    await bot.advance_game.callback(interaction, confirm)
    return interaction


# --------------------------------------------------------------------------
# The pointer
# --------------------------------------------------------------------------


async def test_a_server_nobody_started_has_no_game(started):
    """Unset is not drop 0. A bot sitting in a server it was invited to and
    never set up shows that server's members nothing at all."""
    assert await resolve.current_drop(GUILD_A) is None
    assert await resolve.arrived_drop_ids(GUILD_A) == set()
    assert await resolve.visible_thing_ids(GUILD_A) == set()


async def test_everything_at_or_below_the_pointer_has_arrived(started):
    await resolve.set_current_drop(GUILD_A, 1)

    assert await resolve.arrived_drop_ids(GUILD_A) == {0, 1}


async def test_everything_above_it_has_not(started):
    await resolve.set_current_drop(GUILD_A, 1)

    arrived = await resolve.arrived_drop_ids(GUILD_A)
    assert 2 not in arrived and HOUSE_DROP not in arrived


async def test_a_drop_the_files_do_not_define_is_refused(started):
    with pytest.raises(resolve.UnknownDrop):
        await resolve.set_current_drop(GUILD_A, 99)


async def test_an_unreadable_pointer_reads_as_no_game(started):
    """Somebody hand-edits the row. Showing nothing is the safe failure;
    showing everything is not."""
    await database.set_setting(GUILD_A, resolve.DROP_KEY, 0)
    async with database._require_session()() as session:
        table = database.ServerConfig.__table__
        await session.execute(
            table.update()
            .where(table.c.guild_id == GUILD_A, table.c.key == resolve.DROP_KEY)
            .values(value="soon")
        )
        await session.commit()

    assert await resolve.current_drop(GUILD_A) is None


# --------------------------------------------------------------------------
# What each drop actually contains
# --------------------------------------------------------------------------


async def test_drop_zero_is_the_cat_and_nothing_else(started):
    await resolve.set_current_drop(GUILD_A, 0)

    assert await resolve.visible_thing_ids(GUILD_A) == {CAT}


async def test_drop_one_adds_the_bed_and_still_no_house(started):
    await resolve.set_current_drop(GUILD_A, 1)

    assert await resolve.visible_thing_ids(GUILD_A) == {CAT, BED}


async def test_the_house_waits_for_its_own_drop(started):
    """The leak test. Nothing from drop 3 is reachable at drop 1 - not a
    room, not a thing, not an achievement."""
    await resolve.set_current_drop(GUILD_A, 1)

    visible = await resolve.visible_thing_ids(GUILD_A)
    assert "coat_rack" not in visible
    assert "lumber" not in visible
    assert await resolve.exits_from(GUILD_A, "EN") == []


async def test_the_pre_existing_achievements_wait_too(started):
    """Twenty-eight earnable achievements and seven blocked ones all belong
    to the house, and a drop-1 server must not offer any of them."""
    await resolve.set_current_drop(GUILD_A, 1)

    offered = await resolve.achievements(GUILD_A)
    assert "gourd_job" not in offered
    assert "making_a_mess" not in offered


async def test_the_petting_achievements_do_not_wait(started):
    """They fire on `on_pet` and `on_relationship_change` rather than being
    gated content, and `fire()` reads this same resolution - so a row out
    of reach could never award."""
    await resolve.set_current_drop(GUILD_A, 0)

    offered = await resolve.achievements(GUILD_A)
    assert {"making_friends", "trying_to_make_friends", "cats_best_friend"} <= set(offered)


# --------------------------------------------------------------------------
# /start-game
# --------------------------------------------------------------------------


async def test_starting_opens_drop_zero(started):
    _, _, halloween = started
    await start(started)

    assert await resolve.current_drop(GUILD_A) == 0
    assert await database.announcement_channel(GUILD_A) == halloween.id


async def test_starting_twice_in_the_same_channel_changes_nothing(started):
    await start(started)
    await resolve.set_current_drop(GUILD_A, 1)

    interaction = await start(started)

    assert await resolve.current_drop(GUILD_A) == 1
    assert "already open" in interaction.reply


async def test_a_second_channel_is_refused(started):
    """Moving a running game would leave every player looking at the
    channel it used to be in."""
    _, guild, halloween = started
    await start(started)
    somewhere_else = FakeChannel(name="general")
    guild.text_channels.append(somewhere_else)

    interaction = await start(started, channel=somewhere_else)

    assert await database.announcement_channel(GUILD_A) == halloween.id
    assert "refused" in interaction.reply


async def test_the_reply_is_private(started):
    interaction = await start(started)

    assert interaction.was_private


# --------------------------------------------------------------------------
# /advance-game
# --------------------------------------------------------------------------


async def test_advancing_before_starting_is_refused(started):
    interaction = await advance(started)

    assert await resolve.current_drop(GUILD_A) is None
    assert "/start-game" in interaction.reply


async def test_it_names_the_drop_before_opening_it(started):
    await start(started)

    interaction = await advance(started, confirm=False)

    assert await resolve.current_drop(GUILD_A) == 0
    assert "A Place to Sleep" in interaction.reply


async def test_confirming_opens_it(started):
    await start(started)

    await advance(started)

    assert await resolve.current_drop(GUILD_A) == 1


async def test_it_moves_exactly_one_drop(started):
    await start(started)

    await advance(started)
    second = await advance(started)

    assert await resolve.current_drop(GUILD_A) == 1
    assert "last one built" in second.reply


async def test_the_bed_arrives_with_its_drop(started):
    """What a player can actually reach, which for a fixture is not
    `room_contents`: fixtures are scenery and are resolved from their own
    `room_id`. Reaching for it is the test that matters either way."""
    await start(started)
    assert isinstance(await for_the_bed(), reach.NotFound)

    await advance(started)

    found = await for_the_bed()
    assert isinstance(found, reach.Found) and found.thing_id == BED


async def for_the_bed():
    return await reach.find(
        GUILD_A, ALICE, content_module.CHANNEL_ROOM, "cat bed", reach.Scope.ROOM
    )


async def test_the_drops_own_line_is_public(started):
    """In-world and everybody's: the whole channel watches the cat swat
    something across the floor. Nothing in that line names a drop, a
    command or an admin."""
    _, _, halloween = started
    await start(started)

    await advance(started)

    assert any("swats her paw" in line for line in halloween.posted)


async def test_the_admins_own_reply_is_private(started):
    """The other half of the pair. What the command *did* - which drop,
    what was placed, whether it posted - is nobody else's business."""
    await start(started)

    interaction = await advance(started)

    assert interaction.was_private
    assert "Drop 1" in interaction.reply
    assert "announced in the channel" in interaction.reply


async def test_the_two_halves_do_not_overlap(started):
    """Asserted in both directions, because a one-sided check here is
    exactly how these two got swapped once already: the private reply must
    not carry the in-world line, and the public line must not carry the
    bookkeeping."""
    _, _, halloween = started
    await start(started)

    interaction = await advance(started)

    assert "swats her paw" not in interaction.reply
    posted = "\n".join(halloween.posted)
    assert "Drop 1" not in posted
    assert "placed" not in posted


async def test_the_public_line_posts_once_per_drop(started):
    _, _, halloween = started
    await start(started)
    await advance(started)
    before = len(halloween.posted)

    await advance(started)  # refused: drop 1 is the last one built

    assert len(halloween.posted) == before


# --------------------------------------------------------------------------
# The property the whole phase exists to prove
# --------------------------------------------------------------------------


async def test_two_servers_sit_on_different_drops(started):
    await resolve.set_current_drop(GUILD_A, 0)
    await resolve.set_current_drop(GUILD_B, 1)

    assert await resolve.visible_thing_ids(GUILD_A) == {CAT}
    assert await resolve.visible_thing_ids(GUILD_B) == {CAT, BED}


async def test_advancing_one_leaves_the_other_where_it_was(started):
    await resolve.set_current_drop(GUILD_B, 0)
    await start(started)

    await advance(started)

    assert await resolve.current_drop(GUILD_A) == 1
    assert await resolve.current_drop(GUILD_B) == 0


# --------------------------------------------------------------------------
# Small handmade worlds, shared with the achievement and dispatcher suites
# --------------------------------------------------------------------------


def a_drop(drop_id, trigger="manual", value=None, event=None):
    """One row of a handmade calendar.

    `trigger` and `value` are still columns on a drop and the loader still
    validates them; nothing reads them to decide arrival any more, because
    that is the pointer's job.
    """
    return Drop(
        drop_id=drop_id,
        trigger=trigger,
        date=value,
        event=event,
        name=f"Drop {drop_id}",
        notes=None,
    )


def a_calendar(*drops, things=(), room_text=(), thing_text=()):
    """Content with a handmade set of drops, and one room to hang it on."""
    parsed = Content()
    parsed.rooms = [Room(room_id="EN", name="Entryway", sort_order=1, open_at_launch=True)]
    parsed.room_text = list(room_text) or [
        TextRow(entity_id="EN", state="default", since_drop=1, text={"look": "The hall."})
    ]
    parsed.things = list(things)
    parsed.thing_text = list(thing_text) or [
        TextRow(entity_id=t.thing_id, state="default", since_drop=1, text={"look": "A thing."})
        for t in things
    ]
    parsed.defaults = dict(content_module.load_files().defaults)
    parsed.drops = list(drops)
    return parsed
