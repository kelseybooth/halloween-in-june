"""Grudges softening overnight, and the Pacific day it runs on.

What is left of the nightly drift. The downward half - affection
fading by ten a day for anybody who stayed away - is gone: a score
that falls during an absence punishes the players a staged release is
hardest on. The upward half stays, and no longer asks whether the
player turned up, because making recovery conditional on absence
would leave whoever keeps showing up stuck below zero longest.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select, update

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import database


async def make_player(db, user_id, guild_id, relationship, last_decay=None):
    """A player row with a known score, without going through /pet."""
    await db.ensure_user_exists(user_id, guild_id)
    async with db._require_session()() as session:
        await session.execute(
            update(db.User)
            .where(db.User.id == user_id, db.User.guild_id == guild_id)
            .values(relationship=relationship, last_decay_date=last_decay)
        )
        await session.commit()


async def petted_on(db, user_id, guild_id, day):
    """Record a pet an hour into the given Pacific day, and stamp it.

    The stamp is what the drift now reads. The pet row is written too,
    because the achievements still count those - the two are separate
    records of the same moment, and the drift asks the cheaper question.
    """
    start, _ = db.pacific_day_bounds_utc(day)
    async with db._require_session()() as session:
        session.add(
            db.PetEvent(user_id=user_id, guild_id=guild_id, created_at=start + timedelta(hours=1))
        )
        await session.commit()
    await db.touched_the_cat(user_id, guild_id, day)


async def score(db, user_id, guild_id):
    async with db._require_session()() as session:
        return await session.scalar(
            select(db.User.relationship).where(
                db.User.id == user_id, db.User.guild_id == guild_id
            )
        )


async def stamp(db, user_id, guild_id):
    async with db._require_session()() as session:
        return await session.scalar(
            select(db.User.last_decay_date).where(
                db.User.id == user_id, db.User.guild_id == guild_id
            )
        )


YESTERDAY = date(2026, 6, 10)


# --------------------------------------------------------------------------
# Which scores move, and by how much
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "before, after",
    [
        (-100, -80),
        (-40, -20),
        (-20, 0),  # exactly at the threshold, still recovers
    ],
)
async def test_grudges_soften_by_twenty(db, before, after):
    await make_player(db, ALICE, GUILD_A, before)
    await db.apply_daily_recovery(YESTERDAY)
    assert await score(db, ALICE, GUILD_A) == after


@pytest.mark.parametrize("resting", [100, 50, 20, 10, 9, 5, 0, -5, -19])
async def test_nothing_at_or_above_the_threshold_moves(db, resting):
    """**Affection does not fade any more.** A positive score only ever
    changes because somebody did something, and the dead band below
    zero is unchanged."""
    await make_player(db, ALICE, GUILD_A, resting)
    await db.apply_daily_recovery(YESTERDAY)
    assert await score(db, ALICE, GUILD_A) == resting


async def test_a_grudge_softens_toward_zero_without_reaching_it(db):
    """-25 + 20 is -5: recovery stops short of zero rather than clamping."""
    await make_player(db, ALICE, GUILD_A, -25)
    await db.apply_daily_recovery(YESTERDAY)
    assert await score(db, ALICE, GUILD_A) == -5


@pytest.mark.parametrize("before", [-20, -21, -50, -100])
async def test_one_night_never_overshoots_into_the_positive(db, before):
    """The clamp exists to protect this. With today's constants the
    arithmetic cannot overshoot on its own, so it never fires - it is
    what keeps this true if the step is ever retuned."""
    await make_player(db, ALICE, GUILD_A, before)
    await db.apply_daily_recovery(YESTERDAY)
    after = await score(db, ALICE, GUILD_A)

    assert before < after <= 0


async def test_a_long_grudge_settles_at_zero_rather_than_oscillating(db):
    await make_player(db, ALICE, GUILD_A, -100)
    day = YESTERDAY
    for _ in range(10):
        await db.apply_daily_recovery(day)
        day += timedelta(days=1)
    assert await score(db, ALICE, GUILD_A) == 0


# --------------------------------------------------------------------------
# Nobody is skipped
# --------------------------------------------------------------------------


async def test_a_player_who_petted_that_day_still_recovers(db):
    """**The change from the drift.** It skipped anybody who touched
    the cat, which was right when the question was whether to punish an
    absence and wrong for a climb back: it would leave the player who
    turns up every day in the hole longest while somebody who walked
    away climbed out for free."""
    await make_player(db, ALICE, GUILD_A, -40)
    await petted_on(db, ALICE, GUILD_A, YESTERDAY)

    await db.apply_daily_recovery(YESTERDAY)

    assert await score(db, ALICE, GUILD_A) == -20


async def test_a_player_who_stayed_away_recovers_the_same(db):
    """The two cases are deliberately identical now."""
    await make_player(db, ALICE, GUILD_A, -40)

    await db.apply_daily_recovery(YESTERDAY)

    assert await score(db, ALICE, GUILD_A) == -20


async def test_everybody_considered_is_stamped(db):
    """Otherwise the next run would re-consider the same night."""
    await make_player(db, ALICE, GUILD_A, 50)
    await petted_on(db, ALICE, GUILD_A, YESTERDAY)
    await db.apply_daily_recovery(YESTERDAY)
    assert await stamp(db, ALICE, GUILD_A) == YESTERDAY


# --------------------------------------------------------------------------
# Running the same night twice
# --------------------------------------------------------------------------


async def test_the_same_night_cannot_be_applied_twice(db):
    await make_player(db, ALICE, GUILD_A, -50)
    await db.apply_daily_recovery(YESTERDAY)
    await db.apply_daily_recovery(YESTERDAY)
    assert await score(db, ALICE, GUILD_A) == -30


async def test_a_second_run_reports_no_changes(db):
    await make_player(db, ALICE, GUILD_A, -50)
    assert len(await db.apply_daily_recovery(YESTERDAY)) == 1
    assert await db.apply_daily_recovery(YESTERDAY) == []


async def test_a_change_reports_before_and_after(db):
    await make_player(db, ALICE, GUILD_A, -50)
    (change,) = await db.apply_daily_recovery(YESTERDAY)
    assert (change.user_id, change.guild_id) == (ALICE, GUILD_A)
    assert (change.before, change.after, change.day) == (-50, -30, YESTERDAY)


async def test_an_unchanged_player_is_stamped_but_not_reported(db):
    """Above the threshold there is nothing to report, but the night is
    settled - otherwise the catch-up would reconsider it forever."""
    await make_player(db, ALICE, GUILD_A, 5)
    assert await db.apply_daily_recovery(YESTERDAY) == []
    assert await stamp(db, ALICE, GUILD_A) == YESTERDAY


# --------------------------------------------------------------------------
# Catching up after an outage
# --------------------------------------------------------------------------


async def test_catch_up_settles_every_elapsed_day(db):
    today = db.pacific_today()
    await make_player(db, ALICE, GUILD_A, -100, last_decay=today - timedelta(days=4))
    await db.run_pending_recovery()
    # Three fully elapsed days between the stamp and today: +60.
    assert await score(db, ALICE, GUILD_A) == -40


async def test_catch_up_leaves_today_alone(db):
    """Today is still in progress, and a day is settled once."""
    today = db.pacific_today()
    await make_player(db, ALICE, GUILD_A, -100, last_decay=today - timedelta(days=1))
    await db.run_pending_recovery()
    assert await score(db, ALICE, GUILD_A) == -100
    assert await stamp(db, ALICE, GUILD_A) == today - timedelta(days=1)


async def test_a_never_settled_player_settles_yesterday_only(db):
    """Not all of history: a new row must not be aged by the epoch."""
    await make_player(db, ALICE, GUILD_A, -100, last_decay=None)
    await db.run_pending_recovery()
    assert await score(db, ALICE, GUILD_A) == -80


async def test_catch_up_is_capped(db):
    """A long outage costs at most MAX_CATCHUP_DAYS of work, not unbounded work."""
    today = db.pacific_today()
    stale = today - timedelta(days=db.MAX_CATCHUP_DAYS + 200)
    await make_player(db, ALICE, GUILD_A, -100, last_decay=stale)
    changes = await db.run_pending_recovery()
    assert len(changes) <= db.MAX_CATCHUP_DAYS
    assert await score(db, ALICE, GUILD_A) == 0


async def test_catch_up_on_an_empty_database_does_nothing(db):
    assert await db.run_pending_recovery() == []


# --------------------------------------------------------------------------
# Pacific day boundaries
# --------------------------------------------------------------------------


def test_a_normal_day_is_24_hours():
    start, end = database.pacific_day_bounds_utc(date(2026, 6, 10))
    assert end - start == timedelta(hours=24)


def test_the_spring_forward_day_is_23_hours():
    """Built from local midnights, not by adding 24 hours."""
    start, end = database.pacific_day_bounds_utc(date(2026, 3, 8))
    assert end - start == timedelta(hours=23)


def test_the_fall_back_day_is_25_hours():
    start, end = database.pacific_day_bounds_utc(date(2026, 11, 1))
    assert end - start == timedelta(hours=25)


def test_consecutive_days_meet_exactly_with_no_gap_or_overlap():
    """A half-open range, so a pet at the seam belongs to exactly one day."""
    day = date(2026, 3, 7)
    for _ in range(4):
        _, end = database.pacific_day_bounds_utc(day)
        next_start, _ = database.pacific_day_bounds_utc(day + timedelta(days=1))
        assert end == next_start
        day += timedelta(days=1)


def test_bounds_are_naive_utc():
    """Stored timestamps are naive; an aware bound would raise on comparison."""
    start, end = database.pacific_day_bounds_utc(date(2026, 6, 10))
    assert start.tzinfo is None and end.tzinfo is None


# --------------------------------------------------------------------------
# What the interaction stamp is for now
#
# It used to decide who the drift skipped, and there is no skipping
# any more. It is still written by every pet, play, fluff and feed,
# because the leaderboard reads it: a player with no recorded
# interaction is not in the standings, which is what keeps day one
# from being a wall of zeroes. That half is tested in
# `test_leaderboard.py`; what matters here is that recovery ignores it.
# --------------------------------------------------------------------------


async def test_recovery_does_not_read_the_interaction_stamp(db):
    """Stamped or not, a grudge softens the same. The two cases were
    different under the drift and are deliberately identical now."""
    await make_player(db, ALICE, GUILD_A, -40)
    await make_player(db, BOB, GUILD_A, -40)
    await db.touched_the_cat(ALICE, GUILD_A, YESTERDAY)

    await db.apply_daily_recovery(YESTERDAY)

    assert await score(db, ALICE, GUILD_A) == -20
    assert await score(db, BOB, GUILD_A) == -20


async def test_each_server_recovers_its_own_rows(db):
    """One player, two servers, two separate grudges - settling one
    cannot reach into the other."""
    await make_player(db, ALICE, GUILD_A, -40)
    await make_player(db, ALICE, GUILD_B, -40)

    await db.apply_daily_recovery(YESTERDAY, guild_id=GUILD_A)

    assert await score(db, ALICE, GUILD_A) == -20
    assert await score(db, ALICE, GUILD_B) == -40
