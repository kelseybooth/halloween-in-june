"""The nightly drift back toward neutral, and the Pacific day it runs on."""

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
    """Record a pet an hour into the given Pacific day."""
    start, _ = db.pacific_day_bounds_utc(day)
    async with db._require_session()() as session:
        session.add(
            db.PetEvent(user_id=user_id, guild_id=guild_id, created_at=start + timedelta(hours=1))
        )
        await session.commit()


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
        (100, 90),
        (50, 40),
        (20, 10),
        (10, 0),  # exactly at the threshold, still decays
    ],
)
async def test_affection_fades_by_ten(db, before, after):
    await make_player(db, ALICE, GUILD_A, before)
    await db.apply_daily_decay(YESTERDAY)
    assert await score(db, ALICE, GUILD_A) == after


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
    await db.apply_daily_decay(YESTERDAY)
    assert await score(db, ALICE, GUILD_A) == after


@pytest.mark.parametrize("resting", [9, 5, 0, -5, -19])
async def test_scores_between_the_thresholds_are_left_alone(db, resting):
    """Neutral is the resting point, so nothing inside the dead band moves."""
    await make_player(db, ALICE, GUILD_A, resting)
    await db.apply_daily_decay(YESTERDAY)
    assert await score(db, ALICE, GUILD_A) == resting


async def test_decay_stops_at_the_dead_band_rather_than_running_on(db):
    """15 decays to 5, which is inside the dead band, so the next night it holds."""
    await make_player(db, ALICE, GUILD_A, 15)
    await db.apply_daily_decay(YESTERDAY)
    assert await score(db, ALICE, GUILD_A) == 5
    await db.apply_daily_decay(YESTERDAY + timedelta(days=1))
    assert await score(db, ALICE, GUILD_A) == 5


async def test_a_grudge_softens_toward_zero_without_reaching_it(db):
    """-25 + 20 is -5: recovery stops short of zero rather than clamping to it."""
    await make_player(db, ALICE, GUILD_A, -25)
    await db.apply_daily_decay(YESTERDAY)
    assert await score(db, ALICE, GUILD_A) == -5


@pytest.mark.parametrize("before", [100, 50, 11, 10, -20, -21, -50, -100])
async def test_one_night_never_flips_the_sign_of_a_relationship(db, before):
    """The invariant both clamps exist to protect: decay approaches neutral and
    stops. With today's constants (threshold 10/step 10, threshold -20/step 20)
    the arithmetic cannot overshoot on its own, so neither clamp ever fires -
    they are what keeps this true if those constants are ever retuned."""
    await make_player(db, ALICE, GUILD_A, before)
    await db.apply_daily_decay(YESTERDAY)
    after = await score(db, ALICE, GUILD_A)

    assert abs(after) <= abs(before)
    if before > 0:
        assert after >= 0
    else:
        assert after <= 0


async def test_a_long_absence_settles_at_zero_rather_than_oscillating(db):
    await make_player(db, ALICE, GUILD_A, database.RELATIONSHIP_START)
    day = YESTERDAY
    for _ in range(10):
        await db.apply_daily_decay(day)
        day += timedelta(days=1)
    assert await score(db, ALICE, GUILD_A) == 0


# --------------------------------------------------------------------------
# Who is skipped
# --------------------------------------------------------------------------


async def test_a_player_who_petted_that_day_does_not_decay(db):
    await make_player(db, ALICE, GUILD_A, 50)
    await petted_on(db, ALICE, GUILD_A, YESTERDAY)
    await db.apply_daily_decay(YESTERDAY)
    assert await score(db, ALICE, GUILD_A) == 50


async def test_petting_on_a_different_day_does_not_excuse_this_one(db):
    await make_player(db, ALICE, GUILD_A, 50)
    await petted_on(db, ALICE, GUILD_A, YESTERDAY - timedelta(days=1))
    await db.apply_daily_decay(YESTERDAY)
    assert await score(db, ALICE, GUILD_A) == 40


async def test_a_skipped_player_is_still_stamped(db):
    """Otherwise the next run would re-consider the same night for them."""
    await make_player(db, ALICE, GUILD_A, 50)
    await petted_on(db, ALICE, GUILD_A, YESTERDAY)
    await db.apply_daily_decay(YESTERDAY)
    assert await stamp(db, ALICE, GUILD_A) == YESTERDAY


# --------------------------------------------------------------------------
# Running the same night twice
# --------------------------------------------------------------------------


async def test_the_same_night_cannot_be_applied_twice(db):
    await make_player(db, ALICE, GUILD_A, 50)
    await db.apply_daily_decay(YESTERDAY)
    await db.apply_daily_decay(YESTERDAY)
    assert await score(db, ALICE, GUILD_A) == 40


async def test_a_second_run_reports_no_changes(db):
    await make_player(db, ALICE, GUILD_A, 50)
    assert len(await db.apply_daily_decay(YESTERDAY)) == 1
    assert await db.apply_daily_decay(YESTERDAY) == []


async def test_a_change_reports_before_and_after(db):
    await make_player(db, ALICE, GUILD_A, 50)
    (change,) = await db.apply_daily_decay(YESTERDAY)
    assert (change.user_id, change.guild_id) == (ALICE, GUILD_A)
    assert (change.before, change.after, change.day) == (50, 40, YESTERDAY)


async def test_an_unchanged_player_is_stamped_but_not_reported(db):
    """Inside the dead band there is nothing to report, but the night is settled."""
    await make_player(db, ALICE, GUILD_A, 5)
    assert await db.apply_daily_decay(YESTERDAY) == []
    assert await stamp(db, ALICE, GUILD_A) == YESTERDAY


# --------------------------------------------------------------------------
# Catching up after an outage
# --------------------------------------------------------------------------


async def test_catch_up_settles_every_elapsed_day(db):
    today = db.pacific_today()
    await make_player(db, ALICE, GUILD_A, 100, last_decay=today - timedelta(days=4))
    await db.run_pending_decay()
    # Three fully elapsed days between the stamp and today: -30.
    assert await score(db, ALICE, GUILD_A) == 70


async def test_catch_up_leaves_today_alone(db):
    """Today is still in progress - the player may yet pet the cat."""
    today = db.pacific_today()
    await make_player(db, ALICE, GUILD_A, 100, last_decay=today - timedelta(days=1))
    await db.run_pending_decay()
    assert await score(db, ALICE, GUILD_A) == 100
    assert await stamp(db, ALICE, GUILD_A) == today - timedelta(days=1)


async def test_a_never_decayed_player_settles_yesterday_only(db):
    """Not all of history: a new row must not be aged by the epoch."""
    await make_player(db, ALICE, GUILD_A, 100, last_decay=None)
    await db.run_pending_decay()
    assert await score(db, ALICE, GUILD_A) == 90


async def test_catch_up_is_capped(db):
    """A long outage costs at most MAX_CATCHUP_DAYS of work, not unbounded work."""
    today = db.pacific_today()
    stale = today - timedelta(days=db.MAX_CATCHUP_DAYS + 200)
    await make_player(db, ALICE, GUILD_A, 100, last_decay=stale)
    changes = await db.run_pending_decay()
    assert len(changes) <= db.MAX_CATCHUP_DAYS
    assert await score(db, ALICE, GUILD_A) == 0


async def test_catch_up_on_an_empty_database_does_nothing(db):
    assert await db.run_pending_decay() == []


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
