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

from sqlalchemy import text, update

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


# ---------------------------------------------------------------------
# The clock the stamp comes back on
# ---------------------------------------------------------------------
#
# **The one column the game subtracts that carries a timezone.** Every
# other dated thing the rules read - a toy cooldown, a lock, `taken_at`,
# a restock - is a naive column, and `server_now` is naive, so the
# arithmetic matches. `player_states.set_at` is `DateTime(timezone=True)`
# because it was written alongside the other bookkeeping stamps, back
# when nobody subtracted it. `shaken` made somebody subtract it.
#
# On SQLite that is invisible: the column hands back a naive datetime
# whatever was put in it, so every test above passes whether or not the
# arithmetic is right. On Postgres it comes back aware, and naive minus
# aware is a `TypeError` - which is not a `SQLAlchemyError`, so it goes
# straight past the handlers that apologise for the database and out to
# the catch-all, as "Something went wrong. Please try again."
#
# It took a playtester falling off the ivy on 9 November to find it: the
# first fall on the beta server, and `shaken` is the only state that
# expires, so it was the first row of its kind the game had ever read.
# Their account stayed broken afterwards rather than recovering, because
# the subtraction raises before the age it would have compared is ever
# looked at - so the half hour could not run out, and `/use`, which is
# how you eat your way out, resolves its noun through the same call.
#
# These tests write the stamp the way Postgres returns it, which SQLite
# parses back as aware. Without that, they pass against the bug.


async def stamped_with_a_timezone(db, minutes, who=ALICE, state=SHAKEN):
    """Back-date the stamp, written as Postgres hands it back: with an offset."""
    at = await database.server_now(GUILD_A) - timedelta(minutes=minutes)
    async with db._require_session()() as session:
        await session.execute(
            text(
                "UPDATE player_states SET set_at = :at "
                "WHERE guild_id = :g AND user_id = :u AND state = :s"
            ),
            {
                "at": at.strftime("%Y-%m-%d %H:%M:%S.%f") + "+00:00",
                "g": GUILD_A,
                "u": who,
                "s": state,
            },
        )
        await session.commit()


async def test_a_stamp_that_carries_a_timezone_is_still_in_force(db):
    """The row Kei's fall wrote: five minutes old, and still shaky."""
    await db.ensure_user_exists(ALICE, GUILD_A)
    await states.set_player_state(GUILD_A, ALICE, SHAKEN)
    await stamped_with_a_timezone(db, 5)

    assert await states.has(GUILD_A, ALICE, SHAKEN)
    assert not await states.ran_out(GUILD_A, ALICE, SHAKEN)


async def test_a_stamp_that_carries_a_timezone_still_runs_out(db):
    """And the same row half an hour later, which is how a fall ends itself."""
    await db.ensure_user_exists(ALICE, GUILD_A)
    await states.set_player_state(GUILD_A, ALICE, SHAKEN)
    await stamped_with_a_timezone(db, 40)

    assert not await states.has(GUILD_A, ALICE, SHAKEN)
    assert await states.ran_out(GUILD_A, ALICE, SHAKEN)
