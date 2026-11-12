"""The first ghost: the one pick that is not random.

Whoever reaches the Secret Library first, once the ghost system is
live, is the ghost straight away - no minimum, no midnight, and the
sheet slides off a shelf in front of them.

**The condition is "has this server ever had a ghost", not "has
anybody found the library".** On a test server and on beta those are
the same event, because both parts launch together and the skeleton
keys hang inside; on QA they are days apart, and a library found while
Part 1 was being tested on its own must not spend the server's one
unmissable moment. So the marker is a row in `daily_ghosts`, a table
that is Part 2's and that every server starts with none of.

Driven through the completion hook, which is where it runs - and once
through the oak itself, because the sentence the writers wrote is *as
you climb in* and a test of the whole path is the only thing that says
the climb is where it lands.
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
import phrasing
import resolve
import triggers


@pytest.fixture
async def house(db, monkeypatch):
    """Drop 50, Alice and Bob in the Courtyard, under the oak."""
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    triggers.register_all()
    await content_loader.load_content(content_module.load_files(), guild_ids=[GUILD_A])
    await database.set_setting(GUILD_A, resolve.DROP_KEY, LAST_DROP)
    rooms = {room_id: name for room_id, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    for who in (ALICE, BOB):
        await database.start_game(who, GUILD_A, "CO", ["CO"])
    monkeypatch.setattr(
        bot,
        "bot",
        SimpleNamespace(
            guilds=[guild], get_guild=lambda gid: guild if gid == GUILD_A else None
        ),
    )
    return db, guild, halloween, rooms


def answered(interaction):
    lines = [text for text, _ in interaction.sent if text]
    lines += [
        str(kwargs.get("content"))
        for kwargs in interaction.edited
        if kwargs.get("content")
    ]
    return "\n".join(lines)


async def finish_a_command(house, who=ALICE):
    """One command's worth of the completion hook, which is where it runs."""
    _, guild, _, _ = house
    interaction = FakeInteraction(who, GUILD_A, guild=guild)
    await bot.on_app_command_completion(interaction, bot.look)
    return interaction


async def standing_in_the_library(who=ALICE):
    await database.update_current_room(who, GUILD_A, ghosts.LIBRARY)


async def holding(who=ALICE):
    return await database.carried_of(who, GUILD_A, ghosts.BEDSHEET)


async def ghost_row():
    return await database.daily_ghost(
        GUILD_A, await database.server_today(GUILD_A)
    )


# --------------------------------------------------------------------------
# The climb
# --------------------------------------------------------------------------


async def test_the_first_climb_into_the_library_hands_over_the_sheet(house):
    """The whole path, through the oak, because the line says *as you
    climb in* and nothing else proves that is when it arrives."""
    _, guild, _, _ = house
    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild)

    await bot.use.callback(interaction, "oak tree")
    await bot.on_app_command_completion(interaction, bot.use)

    state = await database.get_game_state(ALICE, GUILD_A)
    assert state.current_room == ghosts.LIBRARY
    assert await phrasing.default_say(ghosts.FIRST) in answered(interaction)
    assert await holding() == 1


async def test_the_row_names_them_and_keeps_both_names(house):
    """Every clue the board gives is spelled from the stored name, so a
    pick that stored neither would be a day with no clues."""
    await standing_in_the_library()

    await finish_a_command(house)
    row = await ghost_row()

    assert row.user_id == ALICE
    assert row.display_name == f"Player {ALICE}"
    assert row.username == f"player{ALICE}"


async def test_the_minimum_does_not_apply(house):
    """One player on the server, and the design says so: this pick is
    the one that cannot be skipped for want of company."""
    await database.set_setting(GUILD_A, ghosts.MIN_PLAYERS, 99)
    await standing_in_the_library()

    await finish_a_command(house)

    assert (await ghost_row()).user_id == ALICE


# --------------------------------------------------------------------------
# Once, and only once
# --------------------------------------------------------------------------


async def test_the_second_player_in_gets_nothing(house):
    await standing_in_the_library(ALICE)
    await finish_a_command(house, ALICE)

    await standing_in_the_library(BOB)
    second = await finish_a_command(house, BOB)

    assert await phrasing.default_say(ghosts.FIRST) not in answered(second)
    assert await holding(BOB) == 0
    assert (await ghost_row()).user_id == ALICE


async def test_the_first_ghost_is_not_told_twice(house):
    """Their own next command in the library must not re-announce it."""
    await standing_in_the_library()
    await finish_a_command(house)

    again = await finish_a_command(house)

    assert await phrasing.default_say(ghosts.FIRST) not in answered(again)
    assert await holding() == 1


async def test_a_ghost_on_an_earlier_day_means_the_moment_has_passed(house):
    """**The marker is the whole table, not today's row.** A server
    whose ghost system has been running for a week does not get a
    second first ghost because today's pick found nobody."""
    today = await database.server_today(GUILD_A)
    await database.record_daily_ghost(
        GUILD_A,
        today - timedelta(days=1),
        user_id=BOB,
        display_name="Bob",
        username="bob",
        eligible=3,
    )
    await database.record_daily_ghost(
        GUILD_A, today, user_id=None, display_name=None, username=None, eligible=1
    )
    await standing_in_the_library()

    await finish_a_command(house)

    assert (await ghost_row()).user_id is None
    assert await holding() == 0


async def test_a_day_the_pick_skipped_is_taken_over(house):
    """A day with nobody in it is a day with no ghost. The pick can run
    before anybody enters - the nightly job does not wait for a player
    - and that row must not block the first arrival."""
    today = await database.server_today(GUILD_A)
    await database.record_daily_ghost(
        GUILD_A, today, user_id=None, display_name=None, username=None, eligible=1
    )
    await standing_in_the_library()

    interaction = await finish_a_command(house)

    assert await phrasing.default_say(ghosts.FIRST) in answered(interaction)
    assert (await ghost_row()).user_id == ALICE


async def test_a_day_that_already_has_a_ghost_is_left_alone(house):
    today = await database.server_today(GUILD_A)
    await database.record_daily_ghost(
        GUILD_A, today, user_id=BOB, display_name="Bob", username="bob", eligible=3
    )
    await standing_in_the_library()

    await finish_a_command(house)

    assert (await ghost_row()).user_id == BOB
    assert await holding() == 0


# --------------------------------------------------------------------------
# Where and when it does not happen
# --------------------------------------------------------------------------


async def test_nothing_happens_outside_the_library(house):
    """Alice is in the Courtyard, which is where the fixture leaves
    her: being on the server is not being in the room."""
    await finish_a_command(house)

    assert await ghost_row() is None
    assert await holding() == 0


async def test_nothing_happens_before_the_drop(house):
    """The sheet comes off a library shelf, so a server that has not
    reached the library cannot have a ghost - and a QA server rolled
    back below 50 must stop having one."""
    await database.set_setting(GUILD_A, resolve.DROP_KEY, ghosts.FROM_DROP - 1)
    await standing_in_the_library()

    await finish_a_command(house)

    assert await ghost_row() is None


# --------------------------------------------------------------------------
# The claim itself
# --------------------------------------------------------------------------


async def test_the_claim_is_lost_rather_than_shared(house):
    """**What makes it atomic.** Two players walking in at the same
    second both read an empty table; the loser has to come away knowing
    they lost, or two people are wearing the sheet.
    """
    today = await database.server_today(GUILD_A)

    first = await database.claim_first_ghost(
        GUILD_A, today, user_id=ALICE, display_name="A", username="a"
    )
    second = await database.claim_first_ghost(
        GUILD_A, today, user_id=BOB, display_name="B", username="b"
    )

    assert (first, second) == (True, False)
    assert (await ghost_row()).user_id == ALICE


async def test_a_skipped_day_is_claimable_once(house):
    today = await database.server_today(GUILD_A)
    await database.record_daily_ghost(
        GUILD_A, today, user_id=None, display_name=None, username=None, eligible=0
    )

    first = await database.claim_first_ghost(
        GUILD_A, today, user_id=ALICE, display_name="A", username="a"
    )
    second = await database.claim_first_ghost(
        GUILD_A, today, user_id=BOB, display_name="B", username="b"
    )

    assert (first, second) == (True, False)


async def test_a_skipped_day_is_not_a_ghost(house):
    """Which is what keeps a quiet server's first ghost waiting for
    them rather than spent on a night nobody was around."""
    today = await database.server_today(GUILD_A)
    await database.record_daily_ghost(
        GUILD_A, today, user_id=None, display_name=None, username=None, eligible=1
    )

    assert await database.ever_had_a_ghost(GUILD_A) is False


async def test_a_real_pick_is_a_ghost_forever(house):
    today = await database.server_today(GUILD_A)
    await database.record_daily_ghost(
        GUILD_A,
        today - timedelta(days=30),
        user_id=ALICE,
        display_name="A",
        username="a",
        eligible=3,
    )

    assert await database.ever_had_a_ghost(GUILD_A) is True


async def test_the_marker_is_per_server(house):
    """A second server's first ghost is still waiting for it."""
    from conftest import GUILD_B

    today = await database.server_today(GUILD_A)
    await database.record_daily_ghost(
        GUILD_A, today, user_id=ALICE, display_name="A", username="a", eligible=3
    )

    assert await database.ever_had_a_ghost(GUILD_A) is True
    assert await database.ever_had_a_ghost(GUILD_B) is False


# --------------------------------------------------------------------------
# Living beside the nightly hand-over
# --------------------------------------------------------------------------


async def test_the_first_ghost_keeps_the_sheet_without_being_told_again(house):
    """`hand_over` runs on the same hook and must see a settled state:
    today's ghost, holding today's sheet, nothing to say."""
    await standing_in_the_library()
    await finish_a_command(house)

    assert await ghosts.hand_over(GUILD_A, ALICE) is None
    assert await holding() == 1


async def test_the_sheet_goes_at_the_next_changeover(house):
    """The design: they keep it until the changeover, when the reveal
    and the random picks begin."""
    await standing_in_the_library()
    await finish_a_command(house)
    today = await database.server_today(GUILD_A)
    await database.record_daily_ghost(
        GUILD_A,
        today + timedelta(days=1),
        user_id=BOB,
        display_name="B",
        username="b",
        eligible=3,
    )
    await database.set_setting(GUILD_A, database.CLOCK_KEY, 1)

    assert await ghosts.hand_over(GUILD_A, ALICE) == ghosts.GONE
    assert await holding() == 0
