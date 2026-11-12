"""The ghost of the day: who gets picked, and who could have been.

Nothing here is visible to a player yet. The pick writes a row and the
bedsheet that would tell somebody about it is the next piece, so this
file is the only place the behaviour is observable at all - which is the
argument for covering the eligible set this closely now rather than
through the haunting later.

**The three conditions are tested apart.** Active, in the house, and
still in the server are three different reasons to be left out, and each
one is a different query clause that a refactor can drop silently: the
`actor` filter, the join, and the name resolution. A test that seeded a
player who satisfied all three and asserted they were picked would pass
with any two of them removed.
"""

from datetime import date, datetime, time, timedelta

import pytest

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import content as content_module
import content_loader
import database
import ghosts
import resolve

CAROL = 100000000000000003
DAVE = 100000000000000004

# A Tuesday, chosen for nothing but being unambiguous in both directions.
TODAY = date(2026, 11, 17)
YESTERDAY = TODAY - timedelta(days=1)

NAMES = {
    ALICE: ("Alice", "alice"),
    BOB: ("Bob", "bob_b"),
    CAROL: ("Carol", "carol.c"),
    DAVE: ("Dave", "dave"),
}


def everyone(user_id):
    """A `name_of` where nobody has left the server."""
    return NAMES.get(user_id)


def everyone_but(*gone):
    """A `name_of` where `gone` have left, and the rest have not."""

    def name_of(user_id):
        return None if user_id in gone else NAMES.get(user_id)

    return name_of


async def in_the_house(*user_ids, guild_id=GUILD_A):
    for user_id in user_ids:
        await database.start_game(user_id, guild_id, "CH", ["CH"])


async def played(user_id, *, day=YESTERDAY, guild_id=GUILD_A, hour=12, **fields):
    """One log row for one player, at an hour of one Pacific day."""
    start, _ = database.pacific_day_bounds_utc(day)
    await database.log_interaction(
        guild_id,
        user_id=user_id,
        now=start + timedelta(hours=hour),
        **{"action": "look", "outcome": database.SUCCESS, **fields},
    )


@pytest.fixture
async def server(db):
    """Two servers at the last drop, with four players not yet enrolled."""
    await content_loader.load_content(content_module.load_files())
    return db


# --------------------------------------------------------------------------
# Who counts as active
# --------------------------------------------------------------------------


async def test_a_command_yesterday_makes_a_player_active(server):
    await in_the_house(ALICE)
    await played(ALICE)

    assert await database.players_active_on(GUILD_A, YESTERDAY) == [ALICE]


async def test_a_player_who_never_entered_the_house_is_not_active(server):
    """The join, on its own.

    `/start` writes a log row before the player is enrolled, and so does
    a refusal to somebody who has never played, so a row is not proof of
    a player. Without the join to `player_game_state` this list is
    everybody Discord has ever pointed at the bot.
    """
    await played(ALICE)

    assert await database.players_active_on(GUILD_A, YESTERDAY) == []


async def test_a_system_row_about_a_player_does_not_make_them_active(server):
    """The `actor` filter, on its own.

    The nightly recovery acts on one player and writes `actor='system'`
    with their id on it, which is exactly the shape that would make an
    absent player look present - and the longer they are away, the more
    recovery rows they collect.
    """
    await in_the_house(ALICE)
    await played(ALICE, actor=database.SYSTEM, action="recovery")

    assert await database.players_active_on(GUILD_A, YESTERDAY) == []


async def test_a_refusal_still_counts_as_being_here(server):
    """A player who spent the evening being told the cabinet is locked
    was here, and this answers who was here."""
    await in_the_house(ALICE)
    await played(ALICE, outcome=database.REFUSED, reason="locked")

    assert await database.players_active_on(GUILD_A, YESTERDAY) == [ALICE]


async def test_the_day_ends_at_pacific_midnight_and_does_not_include_it(server):
    """Half-open, and the half that matters is the top.

    A row at one second to midnight belongs to the day that is ending; a
    row at midnight exactly belongs to the day beginning. `<= end` would
    put the first command of the new day into yesterday's eligible set,
    which on a server where somebody plays at midnight is a ghost picked
    from the wrong day.
    """
    await in_the_house(ALICE, BOB)
    start, end = database.pacific_day_bounds_utc(YESTERDAY)
    await database.log_interaction(
        GUILD_A, user_id=ALICE, action="look", now=end - timedelta(seconds=1)
    )
    await database.log_interaction(GUILD_A, user_id=BOB, action="look", now=end)

    assert await database.players_active_on(GUILD_A, YESTERDAY) == [ALICE]
    assert await database.players_active_on(GUILD_A, TODAY) == [BOB]


async def test_a_busy_player_is_named_once(server):
    await in_the_house(ALICE)
    for hour in (9, 12, 21):
        await played(ALICE, hour=hour)

    assert await database.players_active_on(GUILD_A, YESTERDAY) == [ALICE]


async def test_another_server_s_players_are_not_here(server):
    await in_the_house(ALICE)
    await in_the_house(BOB, guild_id=GUILD_B)
    await played(ALICE)
    await played(BOB, guild_id=GUILD_B)

    assert await database.players_active_on(GUILD_A, YESTERDAY) == [ALICE]
    assert await database.players_active_on(GUILD_B, YESTERDAY) == [BOB]


# --------------------------------------------------------------------------
# The pick
# --------------------------------------------------------------------------


async def test_it_picks_somebody_who_played_yesterday(server):
    await in_the_house(ALICE, BOB, CAROL)
    for who in (ALICE, BOB, CAROL):
        await played(who)

    pick = await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)

    assert pick.user_id in (ALICE, BOB, CAROL)
    assert pick.eligible == 3
    assert not pick.skipped


async def test_it_reads_yesterday_and_not_today(server):
    """Three players active today and none yesterday is a day with no
    ghost, because the pick happens at the changeover and the day it
    asks about is the one that just ended."""
    await in_the_house(ALICE, BOB, CAROL)
    for who in (ALICE, BOB, CAROL):
        await played(who, day=TODAY)

    pick = await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)

    assert pick.skipped
    assert pick.eligible == 0


async def test_two_players_is_a_day_with_no_ghost(server):
    """With two eligible the guess answers itself - whoever is not you -
    so the day is skipped rather than given away."""
    await in_the_house(ALICE, BOB)
    await played(ALICE)
    await played(BOB)

    pick = await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)

    assert pick.skipped
    assert pick.eligible == 2
    assert pick.minimum == 3


async def test_a_day_with_no_ghost_is_still_a_row(server):
    """Which is what stops the next run picking one."""
    await in_the_house(ALICE, BOB)
    await played(ALICE)
    await played(BOB)

    await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)
    row = await database.daily_ghost(GUILD_A, TODAY)

    assert row is not None
    assert row.user_id is None
    assert row.eligible == 2


async def test_the_minimum_is_configurable(server):
    """A test server with two testers lowers it to see the system at all."""
    await database.set_setting(GUILD_A, ghosts.MIN_PLAYERS, 2)
    await in_the_house(ALICE, BOB)
    await played(ALICE)
    await played(BOB)

    pick = await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)

    assert not pick.skipped
    assert pick.minimum == 2


async def test_a_player_who_has_left_the_server_is_not_eligible(server):
    """A ghost who has left cannot be named by anybody, so a day that
    picked one would be a day nobody could win."""
    await in_the_house(ALICE, BOB, CAROL, DAVE)
    for who in (ALICE, BOB, CAROL, DAVE):
        await played(who)

    pick = await ghosts.pick_for(
        GUILD_A, TODAY, name_of=everyone_but(ALICE)
    )

    assert pick.user_id in (BOB, CAROL, DAVE)
    assert pick.eligible == 3


async def test_the_minimum_is_applied_after_the_leavers_are_dropped(server):
    """Three active, one gone, and the day has no ghost.

    Resolving names after the choice instead would report three eligible
    and then either pick somebody no clue can spell, or re-roll under a
    count that has stopped being true. Both are wrong in a way nothing
    else here would catch: the first two tests above pass either way.
    """
    await in_the_house(ALICE, BOB, CAROL)
    for who in (ALICE, BOB, CAROL):
        await played(who)

    pick = await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone_but(CAROL))

    assert pick.skipped
    assert pick.eligible == 2


async def test_the_names_are_stored_as_they_were_at_the_pick(server):
    """Every clue is spelled from the stored name, so a player who
    renames themselves at noon must not scramble the letters the board
    has already handed out."""
    await database.set_setting(GUILD_A, ghosts.MIN_PLAYERS, 1)
    await in_the_house(ALICE)
    await played(ALICE)

    await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)
    row = await database.daily_ghost(GUILD_A, TODAY)

    assert row.user_id == ALICE
    assert row.display_name == "Alice"
    assert row.username == "alice"


async def test_a_second_pick_the_same_day_changes_nothing(server):
    """`/qa-midnight` settles every night a server owes and the nightly
    job can run twice, so a second call at noon must not take the sheet
    off whoever has it."""
    await in_the_house(ALICE, BOB, CAROL)
    for who in (ALICE, BOB, CAROL):
        await played(who)

    first = await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)
    again = await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)
    row = await database.daily_ghost(GUILD_A, TODAY)

    assert again is None
    assert row.user_id == first.user_id


async def test_the_primary_key_is_what_refuses_a_second_pick(server):
    """The guard, asked directly, because nothing else asks it.

    `pick_for` reads the day first and returns early, so every test
    above passes whether or not the write refuses - deleting that read
    left the file green, which is how this test came to exist. What
    stops two changeovers both picking is the insert: `ON CONFLICT DO
    NOTHING` plus a boolean saying whether this call was the one that
    wrote. An upsert here, or a writer that reported every call as a
    write, would hand the sheet to somebody new at noon.
    """
    first = await database.record_daily_ghost(
        GUILD_A, TODAY,
        user_id=ALICE, display_name="Alice", username="alice", eligible=3,
    )
    second = await database.record_daily_ghost(
        GUILD_A, TODAY,
        user_id=BOB, display_name="Bob", username="bob_b", eligible=3,
    )

    assert first is True
    assert second is False
    assert (await database.daily_ghost(GUILD_A, TODAY)).user_id == ALICE


async def test_the_same_player_can_be_the_ghost_two_days_running(server):
    """The design says so, and a pick that avoided yesterday's ghost
    would itself be a clue on a quiet server."""
    await database.set_setting(GUILD_A, ghosts.MIN_PLAYERS, 1)
    await in_the_house(ALICE)
    await played(ALICE, day=YESTERDAY)
    await played(ALICE, day=TODAY)

    first = await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)
    second = await ghosts.pick_for(
        GUILD_A, TODAY + timedelta(days=1), name_of=everyone
    )

    assert first.user_id == ALICE
    assert second.user_id == ALICE


async def test_each_server_picks_its_own(server):
    await database.set_setting(GUILD_A, ghosts.MIN_PLAYERS, 1)
    await database.set_setting(GUILD_B, ghosts.MIN_PLAYERS, 1)
    await in_the_house(ALICE)
    await in_the_house(BOB, guild_id=GUILD_B)
    await played(ALICE)
    await played(BOB, guild_id=GUILD_B)

    here = await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)
    there = await ghosts.pick_for(GUILD_B, TODAY, name_of=everyone)

    assert here.user_id == ALICE
    assert there.user_id == BOB


async def test_a_day_nobody_played_has_no_ghost_and_does_not_raise(server):
    """The log being empty is the state every server starts in, and the
    first changeover must read it as a quiet day rather than an error."""
    pick = await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)

    assert pick.skipped
    assert pick.eligible == 0


# --------------------------------------------------------------------------
# What it writes down
# --------------------------------------------------------------------------


async def logged(action=database.GHOST_PICKED):
    from sqlalchemy import select

    async with database._require_session()() as session:
        rows = await session.scalars(
            select(database.InteractionLog)
            .where(database.InteractionLog.action == action)
            .order_by(database.InteractionLog.id)
        )
        return list(rows.all())


async def test_a_pick_is_logged_with_the_count_it_chose_from(server):
    """The eligible count and the minimum together, because a run of
    skipped days is either a quiet server or a minimum set too high and
    the row has to say which."""
    await in_the_house(ALICE, BOB, CAROL)
    for who in (ALICE, BOB, CAROL):
        await played(who)

    pick = await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)
    rows = await logged()

    assert len(rows) == 1
    assert rows[0].actor == database.SYSTEM
    assert rows[0].user_id == pick.user_id
    assert "eligible=3" in rows[0].detail
    assert "minimum=3" in rows[0].detail
    assert "picked" in rows[0].detail


async def test_a_skipped_day_is_logged_as_skipped_and_names_nobody(server):
    await in_the_house(ALICE)
    await played(ALICE)

    await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)
    rows = await logged()

    assert len(rows) == 1
    assert rows[0].user_id is None
    assert "skipped" in rows[0].detail
    assert "eligible=1" in rows[0].detail


async def test_a_second_call_logs_nothing(server):
    """It changed nothing, so it says nothing. A row per call would make
    the log count picks that did not happen."""
    await database.set_setting(GUILD_A, ghosts.MIN_PLAYERS, 1)
    await in_the_house(ALICE)
    await played(ALICE)

    await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)
    await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)

    assert len(await logged()) == 1


# --------------------------------------------------------------------------
# Against what the game actually writes
# --------------------------------------------------------------------------


async def test_the_eligible_set_reads_rows_a_real_command_wrote(server):
    """Everything above seeds the log directly, which tests the query and
    not the call sites. This drives one real command instead, so the
    `actor`, `user_id` and `created_at` a command actually writes are the
    ones the join reads - the three columns every clause here depends on.
    """
    await in_the_house(ALICE)
    await resolve.set_current_drop(GUILD_A, 1)
    await database.log_interaction(
        GUILD_A,
        user_id=ALICE,
        action=database.LOOK,
        outcome=database.SUCCESS,
        now=await database.server_now(GUILD_A),
    )
    today = await database.server_today(GUILD_A)

    assert await database.players_active_on(GUILD_A, today) == [ALICE]


# --------------------------------------------------------------------------
# The drop the whole system belongs to
# --------------------------------------------------------------------------


def test_the_gate_matches_the_bedsheet_s_own_drop():
    """`ghosts.FROM_DROP` is a constant beside the row it gates, which
    is `world.HOUSE_FROM_DROP`'s arrangement and has the same failure
    mode: the file moves and the constant does not. Pinned here rather
    than read with an async content lookup on a path that runs after
    every command in the game."""
    bedsheet = [
        thing
        for thing in content_module.load_files().things
        if thing.thing_id == ghosts.BEDSHEET
    ]

    assert len(bedsheet) == 1
    assert bedsheet[0].since_drop == ghosts.FROM_DROP


async def test_a_server_below_the_drop_picks_nobody(server):
    """The gate `pick_for` shipped without.

    Three active players on a server at drop 45 is a server with no
    library, no spirit board and no bedsheet in its files - and it
    would have picked a ghost every night regardless, because nothing
    in the pick asked what drop it was. Invisible while nothing read
    the rows, and a sheet handed out thirty drops early the moment
    something did.
    """
    await resolve.set_current_drop(GUILD_A, 45)
    await in_the_house(ALICE, BOB, CAROL)
    for who in (ALICE, BOB, CAROL):
        await played(who)

    pick = await ghosts.pick_for(GUILD_A, TODAY, name_of=everyone)

    assert pick is None
    assert await database.daily_ghost(GUILD_A, TODAY) is None


# --------------------------------------------------------------------------
# The sheet follows the row
# --------------------------------------------------------------------------


async def holds(user_id=ALICE, guild_id=GUILD_A):
    return await database.carried_of(user_id, guild_id, ghosts.BEDSHEET)


async def is_the_ghost(user_id, *, day, guild_id=GUILD_A):
    await database.record_daily_ghost(
        guild_id, day,
        user_id=user_id, display_name="Alice", username="alice", eligible=3,
    )


async def test_the_sheet_arrives_on_the_ghost_s_next_command(server):
    """Which is where the design puts it: *the ghost's next command
    after the pick*. At midnight the bot has a guild and a row and
    nowhere to put a sentence."""
    today = await database.server_today(GUILD_A)
    await is_the_ghost(ALICE, day=today)

    said = await ghosts.hand_over(GUILD_A, ALICE)

    assert said == ghosts.ARRIVED
    assert await holds() == 1


async def test_a_second_command_the_same_day_says_nothing_more(server):
    """The notice is the change, not the state. A ghost who runs ten
    commands is told once."""
    today = await database.server_today(GUILD_A)
    await is_the_ghost(ALICE, day=today)

    await ghosts.hand_over(GUILD_A, ALICE)
    again = await ghosts.hand_over(GUILD_A, ALICE)

    assert again is None
    assert await holds() == 1


async def test_the_sheet_goes_when_the_day_has_moved_on(server):
    """Yesterday's ghost, on their next command, with somebody else
    wearing it today."""
    today = await database.server_today(GUILD_A)
    # Placed directly rather than through a hand_over for yesterday:
    # that call reads *today*, so it would have done nothing and left
    # the setup describing a sheet nobody held.
    await database.place_in_hands(GUILD_A, ALICE, ghosts.BEDSHEET)
    await is_the_ghost(BOB, day=today)

    said = await ghosts.hand_over(GUILD_A, ALICE)

    assert said == ghosts.GONE
    assert await holds() == 0


async def test_a_day_with_no_ghost_still_takes_the_sheet_back(server):
    """A skipped day is a day nobody is the ghost, so the sheet goes
    even though nobody is getting it. The row exists and says so,
    which is the reason a skip is a row."""
    today = await database.server_today(GUILD_A)
    await database.place_in_hands(GUILD_A, ALICE, ghosts.BEDSHEET)
    await database.record_daily_ghost(
        GUILD_A, today,
        user_id=None, display_name=None, username=None, eligible=1,
    )

    said = await ghosts.hand_over(GUILD_A, ALICE)

    assert said == ghosts.GONE
    assert await holds() == 0


async def test_a_ghost_two_days_running_is_told_nothing(server):
    """They keep it without a word, because nothing changed - and a
    second "something has appeared in your bag" would tell them the
    pick had repeated, which is a clue about the one thing the game is
    hiding."""
    today = await database.server_today(GUILD_A)
    await database.place_in_hands(GUILD_A, ALICE, ghosts.BEDSHEET)
    await is_the_ghost(ALICE, day=today)

    said = await ghosts.hand_over(GUILD_A, ALICE)

    assert said is None
    assert await holds() == 1


async def test_somebody_who_is_not_the_ghost_hears_nothing(server):
    today = await database.server_today(GUILD_A)
    await is_the_ghost(ALICE, day=today)

    assert await ghosts.hand_over(GUILD_A, BOB) is None
    assert await holds(BOB) == 0


async def test_a_sheet_left_over_from_a_missed_night_is_repaired(server):
    """The argument for reconciling rather than handing over.

    A bot that was down at midnight, or a night the pick raised, leaves
    a sheet in the hands of somebody who stopped being the ghost days
    ago and no row saying it should be taken. Because this compares the
    hand against today's row rather than trusting a handover that was
    supposed to have happened, the next command that player runs fixes
    it - and a day with no row at all is still a day they are not the
    ghost.
    """
    await database.place_in_hands(GUILD_A, ALICE, ghosts.BEDSHEET)

    said = await ghosts.hand_over(GUILD_A, ALICE)

    assert said == ghosts.GONE
    assert await holds() == 0


async def test_the_sheet_does_not_move_below_the_drop(server):
    """Belt as well as braces. The gate on the pick means a row should
    not exist below drop 50, and this is the other half: a row that
    exists anyway - written before the gate, or by a server walked
    backwards - does not put a thing in somebody's hands that their
    drop has no text for."""
    today = await database.server_today(GUILD_A)
    await is_the_ghost(ALICE, day=today)
    await resolve.set_current_drop(GUILD_A, 45)

    assert await ghosts.hand_over(GUILD_A, ALICE) is None
    assert await holds() == 0


async def test_the_sheet_cannot_be_dropped(server):
    """`droppable` no in the file, which is what the copy promises:
    *The bedsheet clings to you. It isn't done with you yet.*"""
    bedsheet = [
        thing
        for thing in content_module.load_files().things
        if thing.thing_id == ghosts.BEDSHEET
    ][0]

    assert bedsheet.droppable is False
    assert bedsheet.takeable is False
    assert bedsheet.max_per_player == 1

