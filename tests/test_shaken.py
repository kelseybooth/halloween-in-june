"""An expiring player state, which is the first one the house has had.

Every other player state is a discovery: set once, kept for ever, and
`set_at` was only a record of when. `shaken` is the first whose row
carries a clock - a player who has fallen off the ivy cannot `/take`
until they eat or drink something, or until half an hour has gone by.

**Lazy, with no sweep.** Nothing wakes up to clear it; a row whose time
has run out is simply not in force the next time anybody asks. Kelsey
chose that over a timer. What it costs is that the row stays in the
table - and that turns out to be the only way to tell a state somebody
ate their way out of from one that ran out, which is the difference
*Walk It Off* is awarded on.

**Why these tests back-date the column.** `clock_offset_days` is the
only clock the QA command can move and it moves whole days, so there is
no way to advance a server by half an hour. The expiry arithmetic is
still against `database.server_now`, per the single-clock rule, but a
test that wants a stale row has to write the timestamp.
"""

import pytest
from datetime import timedelta

from sqlalchemy import update

from conftest import ALICE, BOB, GUILD_A

import database
import states


SHAKEN = "shaken"


async def back_date(db, minutes, who=ALICE, state=SHAKEN):
    """Move a state's stamp into the past, which the QA clock cannot do."""
    async with db._require_session()() as session:
        await session.execute(
            update(database.PlayerState)
            .where(
                database.PlayerState.guild_id == GUILD_A,
                database.PlayerState.user_id == who,
                database.PlayerState.state == state,
            )
            .values(
                set_at=await database.server_now(GUILD_A) - timedelta(minutes=minutes)
            )
        )
        await session.commit()


async def test_it_is_in_force_the_moment_it_is_set(db):
    await db.ensure_user_exists(ALICE, GUILD_A)

    assert await states.set_player_state(GUILD_A, ALICE, SHAKEN) is True
    assert await states.has(GUILD_A, ALICE, SHAKEN)
    assert not await states.ran_out(GUILD_A, ALICE, SHAKEN)


async def test_and_not_in_force_once_its_half_hour_is_up(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await states.set_player_state(GUILD_A, ALICE, SHAKEN)

    await back_date(db, 31)

    assert not await states.has(GUILD_A, ALICE, SHAKEN)


async def test_but_still_in_force_at_twenty_nine_minutes(db):
    """The boundary, from the side that still counts."""
    await db.ensure_user_exists(ALICE, GUILD_A)
    await states.set_player_state(GUILD_A, ALICE, SHAKEN)

    await back_date(db, 29)

    assert await states.has(GUILD_A, ALICE, SHAKEN)


async def test_the_row_is_left_behind_when_it_runs_out(db):
    """Which is the whole of how *Walk It Off* can ever be awarded.

    `has` says no and `ran_out` says yes, and those are two different
    questions about the same row.
    """
    await db.ensure_user_exists(ALICE, GUILD_A)
    await states.set_player_state(GUILD_A, ALICE, SHAKEN)
    await back_date(db, 31)

    assert not await states.has(GUILD_A, ALICE, SHAKEN)
    assert await states.ran_out(GUILD_A, ALICE, SHAKEN)


async def test_but_not_when_it_was_cleared(db):
    """Cleared by food deletes the row, so there is nothing to have run out."""
    await db.ensure_user_exists(ALICE, GUILD_A)
    await states.set_player_state(GUILD_A, ALICE, SHAKEN)

    assert await states.clear_player_state(GUILD_A, ALICE, SHAKEN) is True

    assert not await states.has(GUILD_A, ALICE, SHAKEN)
    assert not await states.ran_out(GUILD_A, ALICE, SHAKEN)


async def test_falling_again_on_a_stale_row_restarts_the_clock(db):
    """Two wrong answers from one call, before this.

    `set_player_state` returned False without writing if a row existed,
    which for a clocked state meant a second fall kept the first one's
    stamp - so the player was not shaken at all - and reported that they
    already were.
    """
    await db.ensure_user_exists(ALICE, GUILD_A)
    await states.set_player_state(GUILD_A, ALICE, SHAKEN)
    await back_date(db, 31)

    assert await states.set_player_state(GUILD_A, ALICE, SHAKEN) is True

    assert await states.has(GUILD_A, ALICE, SHAKEN)
    assert not await states.ran_out(GUILD_A, ALICE, SHAKEN)


async def test_a_discovery_is_still_set_once_and_answers_false(db):
    """Unchanged, and the reason the branch is on the state and not the verb."""
    await db.ensure_user_exists(ALICE, GUILD_A)

    assert await states.set_player_state(GUILD_A, ALICE, "drawer_unjammed") is True
    assert await states.set_player_state(GUILD_A, ALICE, "drawer_unjammed") is False


async def test_and_cannot_be_cleared_at_all(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await states.set_player_state(GUILD_A, ALICE, "drawer_unjammed")

    with pytest.raises(ValueError):
        await states.clear_player_state(GUILD_A, ALICE, "drawer_unjammed")


async def test_it_is_one_player_s_own(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(BOB, GUILD_A)
    await states.set_player_state(GUILD_A, ALICE, SHAKEN)

    assert await states.has(GUILD_A, ALICE, SHAKEN)
    assert not await states.has(GUILD_A, BOB, SHAKEN)


async def test_the_qa_clock_still_moves_it(db):
    """The single-clock rule, for the one dated thing the offset cannot express.

    Half an hour is not a number `clock_offset_days` can hold, but a day
    is - and a day forward has to expire a state set half an hour ago,
    or this is the one behaviour a QA server cannot drive at all.
    """
    await db.ensure_user_exists(ALICE, GUILD_A)
    await states.set_player_state(GUILD_A, ALICE, SHAKEN)
    assert await states.has(GUILD_A, ALICE, SHAKEN)

    await db.set_setting(GUILD_A, database.CLOCK_KEY, 1)

    assert not await states.has(GUILD_A, ALICE, SHAKEN)
    assert await states.ran_out(GUILD_A, ALICE, SHAKEN)
