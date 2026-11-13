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


# --------------------------------------------------------------------------
# What the picker calls the channel
# --------------------------------------------------------------------------
#
# `rooms.tsv` calls `CH` "the channel", which is what a player standing
# in it reads. The picker is a list of places to drift into from outside,
# and outside the house has always called it the road - `_say_in_room`
# says so in its own docstring.
#
# **Two names rather than one**, because `ghost.haunt.modal.title` is
# "Haunt the {room}". Every other room is a bare noun; the channel is the
# one name carrying its own article, so a single name is wrong in one of
# the two places whichever one is chosen. Both halves are pinned here,
# because a test on the label alone passes against *Haunt the the road*.


def option_for(view, value):
    return next(o for o in view.children[0].options if o.value == value)


async def open_the_box(house, choice, who=ALICE):
    """The picker up to the modal, which is where the titles are."""
    _, guild, _, _ = house
    picker = await open_the_picker(house, who)
    select = the_view(picker).children[0]
    select._values = [choice]
    chose = FakeInteraction(who, GUILD_A, guild=guild)
    await select.callback(chose)
    return chose.modals[-1]


async def used_row(who=ALICE):
    from sqlalchemy import select

    async with database._require_session()() as session:
        return await session.scalar(
            select(database.ThingUse).where(
                database.ThingUse.guild_id == GUILD_A,
                database.ThingUse.user_id == who,
                database.ThingUse.thing_id == ghosts.BEDSHEET,
            )
        )


async def test_the_road_is_in_the_list_under_its_own_name(house):
    """Capitalised and bare, like every other entry: the list reads
    "Entryway", "Dining Room", "Road"."""
    view = the_view(await open_the_picker(house))

    assert option_for(view, "CH").label == "Road"


async def test_the_box_finishes_the_sentence_about_the_road(house):
    """**The half a label test cannot see.** "the road" in the list and
    "the road" in the template gives *Haunt the the road*, which is the
    same stutter "the channel" has produced since the picker shipped."""
    box = await open_the_box(house, "CH")

    assert box.title == "Haunt the road"


async def test_the_ghost_is_told_it_drifted_into_the_road(house):
    answer = answered(await haunt(house, "CH", "boo"))

    assert "into the road" in answer
    assert "the the" not in answer


async def test_every_other_room_keeps_the_name_the_house_gave_it(house):
    """The pair is one string for every room but the channel, so this is
    the guard that the helper did not start renaming the house."""
    view = the_view(await open_the_picker(house))
    _, _, _, rooms = house

    for room_id in await ghosts.rooms_to_haunt(GUILD_A, ALICE):
        if room_id != "CH":
            assert option_for(view, room_id).label == rooms[room_id]


# --------------------------------------------------------------------------
# Every room, in one press
# --------------------------------------------------------------------------


async def test_every_room_is_the_first_option(house):
    """First, because it is the one choice that is not a room, and a
    ghost deciding to be everywhere should not have to read to the
    bottom of the house to find it."""
    view = the_view(await open_the_picker(house))

    assert view.children[0].options[0].value == ghosts.EVERYWHERE


async def test_the_sentinel_cannot_be_a_room(house):
    """A room id is two uppercase letters, so one character cannot
    collide - now or after a drop adds a room."""
    assert ghosts.EVERYWHERE not in [
        room_id for room_id, _ in await resolve.all_rooms()
    ]


async def test_every_room_hears_the_whisper(house):
    """Every room with a thread, and the road, which has none - the
    branch `_say_in_room` carries for every room-addressed line."""
    await haunt(house, ghosts.EVERYWHERE, "boo")
    _, _, halloween, _ = house

    for room_id in await ghosts.rooms_to_haunt(GUILD_A, ALICE):
        if room_id == "CH":
            assert any("boo" in line for line in halloween.posted)
        else:
            assert "boo" in said_in(house, room_id)


async def test_every_room_is_one_haunting_not_one_each(house):
    """**The decision this option was built around.** Nine rows would be
    nine hauntings, and *Boo Who?* asks for three of them in a day."""
    today = await database.server_today(GUILD_A)
    rooms = await ghosts.rooms_to_haunt(GUILD_A, ALICE)

    await haunt(house, ghosts.EVERYWHERE, "boo")

    assert len(rooms) > 1
    assert await database.hauntings_on(GUILD_A, ALICE, today) == 1
    assert len(await logged()) == 1


async def test_one_press_does_not_hand_over_boo_who(house):
    """*Haunted the house all day* has to cost a day. The award is
    checked at changeover; what this holds is the count it reads."""
    today = await database.server_today(GUILD_A)

    await haunt(house, ghosts.EVERYWHERE, "boo")

    assert await database.hauntings_on(GUILD_A, ALICE, today) < 3


async def test_three_presses_still_cost_three(house):
    """The other direction: one row per press, so the count is still
    reachable rather than pinned at one."""
    today = await database.server_today(GUILD_A)

    for whisper in ("one", "two", "three"):
        await haunt(house, ghosts.EVERYWHERE, whisper)

    assert await database.hauntings_on(GUILD_A, ALICE, today) == 3


async def test_the_one_row_says_it_was_every_room(house):
    """The admin's copy keeps the words, with the spread in front of
    them - the only place a log row can say it, since `interaction_log`
    has no room column."""
    rooms = await ghosts.rooms_to_haunt(GUILD_A, ALICE)

    await haunt(house, ghosts.EVERYWHERE, "something unkind")
    rows = await logged()

    assert rows[0].detail == f"every room ({len(rooms)}): something unkind"


async def test_every_room_records_no_single_room(house):
    """`last_used_at` and `last_used_room` are one fact, so a shape that
    was in every room at once was in no particular one. Coalescing would
    claim the sheet was last used somewhere it was not."""
    await haunt(house, ghosts.EVERYWHERE, "boo")

    assert (await used_row()).last_used_room is None


async def test_one_room_still_records_that_room(house):
    """Passes without the change. The guard that taking a list did not
    cost the single-room case its room."""
    await haunt(house, "LI", "boo")

    assert (await used_row()).last_used_room == "LI"


async def test_the_ghost_gets_a_line_of_its_own(house):
    """A separate key from the single-room one, which says *you drift
    into the {room}*: filling that with "house" would have described
    where the ghost went rather than that it was everywhere.

    **The whisper is asserted as well as the wording.** The line is
    copy and can be rewritten, but it has to keep `{whisper}` in it -
    a line that dropped the placeholder would read correctly and tell
    the ghost nothing about what it just said.
    """
    answer = answered(await haunt(house, ghosts.EVERYWHERE, "boo"))

    assert "hither and thither" in answer
    assert "boo" in answer
    assert "drift into the" not in answer


async def test_every_room_earns_the_spirit_once(house):
    """Nine rooms, one use, one award - *the first haunting* is a
    per-player fact and nine posts are still one haunting."""
    await haunt(house, ghosts.EVERYWHERE, "boo")

    assert await earned() == {"getting_into_the_spirit"}
