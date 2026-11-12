"""The haunting: a ghost pulls the sheet on and a shape drifts somewhere.

Driven through the real controls rather than through `record_haunting`,
because every way this can be wrong is at a seam between them: the
branch that opens the picker, the room the picker hands the box, and the
whisper the box hands the poster. A test that called the recorder
directly would prove a row gets written and nothing about whether a
player can reach it.

**The two seams discord.py hides** are `Select.values` and
`TextInput.value`, read-only properties backed by `_values` and `_value`.
Filling those is what Discord does on the way in, and it is the only way
to drive a component offline: the fake records the modal, and the test
fills it and submits.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from conftest import ALICE, BOB, GUILD_A, LAST_DROP
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import ghosts
import resolve
import states
import triggers


@pytest.fixture
async def house(db, monkeypatch):
    """Drop 50, two players in the Living Room, Alice wearing the sheet."""
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    triggers.register_all()
    await content_loader.load_content(
        content_module.load_files(), guild_ids=[GUILD_A]
    )
    await database.set_setting(GUILD_A, resolve.DROP_KEY, LAST_DROP)
    rooms = {room_id: name for room_id, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    for who in (ALICE, BOB):
        await database.start_game(who, GUILD_A, "LI", ["LI"])
    await database.place_in_hands(GUILD_A, ALICE, ghosts.BEDSHEET)
    monkeypatch.setattr(
        bot,
        "bot",
        SimpleNamespace(
            guilds=[guild], get_guild=lambda gid: guild if gid == GUILD_A else None
        ),
    )
    return db, guild, halloween, rooms


def place(house, room_id):
    _, _, halloween, rooms = house
    return next(t for t in halloween.threads if t.name == rooms[room_id])


def said_in(house, room_id):
    return "\n".join(line for line in place(house, room_id).posted if line)


async def open_the_picker(house, who=ALICE):
    _, guild, _, _ = house
    interaction = FakeInteraction(who, GUILD_A, guild=guild)
    await bot.use.callback(interaction, "bedsheet")
    return interaction


def the_view(interaction):
    for _, kwargs in interaction.sent:
        if kwargs.get("view") is not None:
            return kwargs["view"]
    return None


async def haunt(house, room_id, whisper, *, who=ALICE):
    """The whole flow: /use bedsheet, pick a room, type, submit."""
    _, guild, _, _ = house
    picker = await open_the_picker(house, who)
    select = the_view(picker).children[0]
    select._values = [room_id]

    chose = FakeInteraction(who, GUILD_A, guild=guild)
    await select.callback(chose)

    modal = chose.modals[-1]
    modal.whisper._value = whisper
    submitted = FakeInteraction(who, GUILD_A, guild=guild)
    await modal.on_submit(submitted)
    return submitted


def answered(interaction):
    """Whatever the ghost was told, however it was delivered."""
    lines = [text for text, _ in interaction.sent if text]
    lines += [
        str(kwargs.get("content")) for kwargs in interaction.edited
        if kwargs.get("content")
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Who can haunt at all
# --------------------------------------------------------------------------


async def test_a_player_without_the_sheet_is_offered_nothing(house):
    """**The whole of the permission check**, and it is not a new one.

    The branch sits below the not-carried refusal every `/use` goes
    through, so only the player holding the bedsheet reaches it - and the
    only way to hold one is to be today's ghost. Nothing asks separately,
    which is why there is no "you are not the ghost" line to write.
    """
    interaction = await open_the_picker(house, BOB)

    assert the_view(interaction) is None


async def test_the_ghost_is_offered_rooms(house):
    interaction = await open_the_picker(house)
    view = the_view(interaction)

    assert view is not None
    assert [option.value for option in view.children[0].options]


# --------------------------------------------------------------------------
# Which rooms
# --------------------------------------------------------------------------


async def test_the_list_is_rooms_that_have_arrived(house):
    rooms = await ghosts.rooms_to_haunt(GUILD_A, ALICE)

    assert set(rooms) <= await resolve.arrived_rooms(GUILD_A)
    assert "LI" in rooms


async def test_the_library_is_not_offered_until_the_ghost_has_found_it(house):
    """The one room that arrives for a server and not for a player.

    Listing it for a ghost who has never climbed the oak would be the
    game telling them the Secret Library is there - the drop's whole
    discovery, handed over in a dropdown.
    """
    before = await ghosts.rooms_to_haunt(GUILD_A, ALICE)
    await states.set_player_state(GUILD_A, ALICE, "library_found")
    after = await ghosts.rooms_to_haunt(GUILD_A, ALICE)

    assert ghosts.LIBRARY not in before
    assert ghosts.LIBRARY in after


async def test_where_the_ghost_stands_does_not_narrow_the_list(house):
    """A haunting is not a move. The ghost goes nowhere, so standing in
    the Kitchen is no reason to be unable to haunt the Living Room."""
    await database.update_current_room(ALICE, GUILD_A, "KI")

    rooms = await ghosts.rooms_to_haunt(GUILD_A, ALICE)

    assert {"LI", "KI"} <= set(rooms)


# --------------------------------------------------------------------------
# The whisper
# --------------------------------------------------------------------------


async def test_the_whisper_is_posted_in_the_room_it_names(house):
    await haunt(house, "LI", "I remember this room")

    assert "I remember this room" in said_in(house, "LI")
    assert said_in(house, "KI") == ""


async def test_the_posted_line_does_not_name_the_ghost(house):
    """The whole game is not knowing who it is."""
    await haunt(house, "LI", "boo")
    out = said_in(house, "LI")

    assert "boo" in out
    assert str(ALICE) not in out


async def test_the_ghost_is_told_privately_where_it_landed(house):
    submitted = await haunt(house, "LI", "boo")

    assert "boo" in answered(submitted)


async def test_a_whisper_cannot_ping_anybody(house):
    """`@everyone` in a whisper stays plain text.

    Nothing was written for this: every public line in the house goes out
    through `_post_quietly`, which turns each mention class off and lets
    back only an id the caller names. A haunting names none, so the
    whisper is inert by inheritance - and this is the test that says so,
    because inheriting a property silently is how it gets lost.
    """
    await haunt(house, "LI", "@everyone look behind you")

    mentions = place(house, "LI").mentions[-1]
    assert mentions is not None
    assert mentions.everyone is False
    assert mentions.roles is False
    assert mentions.users in ([], False)


async def test_a_whisper_longer_than_the_cap_is_cut(house):
    limit = await database.get_setting(GUILD_A, ghosts.MAX_CHARS)

    assert ghosts.trimmed("x" * (limit + 50), limit) == "x" * limit


async def test_the_box_will_not_take_more_than_the_cap(house):
    """Discord's own refusal, before a submit can happen at all."""
    _, guild, _, _ = house
    picker = await open_the_picker(house)
    select = the_view(picker).children[0]
    select._values = ["LI"]
    chose = FakeInteraction(ALICE, GUILD_A, guild=guild)

    await select.callback(chose)

    limit = await database.get_setting(GUILD_A, ghosts.MAX_CHARS)
    assert chose.modals[-1].whisper.max_length == limit


# --------------------------------------------------------------------------
# What it writes down
# --------------------------------------------------------------------------


async def logged(action=database.HAUNTED):
    from sqlalchemy import select

    async with database._require_session()() as session:
        rows = await session.scalars(
            select(database.InteractionLog)
            .where(database.InteractionLog.action == action)
            .order_by(database.InteractionLog.id)
        )
        return list(rows.all())


async def test_a_haunting_records_its_author_and_its_words(house):
    """Anonymous to players, not to admins - the trade the design makes
    for dropping the Story Bible's no-moderation."""
    await haunt(house, "LI", "something unkind")
    rows = await logged()

    assert len(rows) == 1
    assert rows[0].user_id == ALICE
    assert rows[0].detail == "something unkind"
    assert rows[0].thing_id == ghosts.BEDSHEET


async def test_pulling_the_sheet_on_is_not_a_haunting(house):
    """Opening the picker and walking away records nothing - which is
    what the spirit board's *nothing has stirred in the house today* has
    to keep being true of."""
    await open_the_picker(house)
    today = await database.server_today(GUILD_A)

    assert await logged() == []
    assert await database.hauntings_on(GUILD_A, ALICE, today) == 0


async def test_the_count_is_per_player_and_per_day(house):
    today = await database.server_today(GUILD_A)

    await haunt(house, "LI", "one")
    await haunt(house, "LI", "two")

    assert await database.hauntings_on(GUILD_A, ALICE, today) == 2
    assert await database.hauntings_on(GUILD_A, BOB, today) == 0
    assert await database.hauntings_on(GUILD_A, ALICE, today - timedelta(days=1)) == 0


# --------------------------------------------------------------------------
# Getting into the Spirit
# --------------------------------------------------------------------------


async def earned(user_id=ALICE):
    return set(await database.player_achievements_of(GUILD_A, user_id))


async def test_the_first_haunting_earns_it(house):
    await haunt(house, "LI", "boo")

    assert "getting_into_the_spirit" in await earned()


async def test_a_second_haunting_earns_nothing_new(house):
    """Idempotent per player, which is why *the first* haunting needs no
    predicate of its own and `_used` is the whole of it."""
    await haunt(house, "LI", "one")
    await haunt(house, "LI", "two")

    assert await earned() == {"getting_into_the_spirit"}
