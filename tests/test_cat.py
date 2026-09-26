"""The cat: pet counting, mood weighting, and the relationship meter."""

from datetime import timedelta

import pytest

import bot
import database
from conftest import ALICE, BOB, GUILD_A, GUILD_B


# --------------------------------------------------------------------------
# Mood weighting (pure, no database)
# --------------------------------------------------------------------------


def test_friendly_chance_starts_at_base():
    assert bot.friendly_chance(0) == bot.BASE_FRIENDLY_CHANCE


@pytest.mark.parametrize(
    "recent, expected",
    [(0, 70), (1, 60), (2, 50), (3, 40), (4, 30), (5, 20), (6, 10), (7, 0)],
)
def test_friendly_chance_decays_ten_points_per_recent_pet(recent, expected):
    assert bot.friendly_chance(recent) == expected


def test_friendly_chance_floors_at_zero_and_never_goes_negative():
    """A negative probability is treated as zero, not as a negative weight."""
    for recent in range(7, 40):
        assert bot.friendly_chance(recent) == 0


def test_choose_response_friendly_when_roll_is_under_the_chance(fixed_rng):
    # 69 < 70, so a player with no recent pets gets the friendly pool.
    reaction = bot.choose_response(0, rng=fixed_rng.queue(0.69))
    assert reaction.friendly is True
    assert reaction.text in bot.FRIENDLY_RESPONSES
    assert reaction.chance == 70


def test_choose_response_standoffish_when_roll_is_on_the_boundary(fixed_rng):
    """The comparison is `roll * 100 < chance`, so exactly 70 is standoffish."""
    reaction = bot.choose_response(0, rng=fixed_rng.queue(0.70))
    assert reaction.friendly is False
    assert reaction.text in bot.STANDOFFISH_RESPONSES


def test_choose_response_is_always_standoffish_once_chance_hits_zero(fixed_rng):
    """No roll can be below 0, so the 7th recent pet onward is reliably hostile."""
    for roll in (0.0, 0.001, 0.5, 0.999):
        reaction = bot.choose_response(7, rng=fixed_rng.queue(roll))
        assert reaction.friendly is False
        assert reaction.chance == 0


def test_response_pools_are_three_and_three_and_do_not_overlap():
    assert len(bot.FRIENDLY_RESPONSES) == 3
    assert len(bot.STANDOFFISH_RESPONSES) == 3
    assert not set(bot.FRIENDLY_RESPONSES) & set(bot.STANDOFFISH_RESPONSES)
    assert len(bot.PET_RESPONSES) == 6


def test_reaction_reports_the_chance_that_produced_it(fixed_rng):
    """The chance travels with the reaction, so the caller never recomputes it."""
    assert bot.choose_response(3, rng=fixed_rng.queue(0.1)).chance == 40


# --------------------------------------------------------------------------
# Pet counting
# --------------------------------------------------------------------------


async def test_first_pet_creates_the_row_and_returns_one(db):
    result = await db.increment_pet_count(ALICE, GUILD_A)
    assert result.total == 1
    assert result.recent == 0


async def test_pet_count_accumulates(db):
    for expected in range(1, 6):
        assert (await db.increment_pet_count(ALICE, GUILD_A)).total == expected
    assert await db.get_pet_count(ALICE, GUILD_A) == 5


async def test_recent_count_describes_the_state_the_player_arrived_in(db):
    """`recent` excludes the pet being recorded, so the first pet reports zero."""
    assert (await db.increment_pet_count(ALICE, GUILD_A)).recent == 0
    assert (await db.increment_pet_count(ALICE, GUILD_A)).recent == 1
    assert (await db.increment_pet_count(ALICE, GUILD_A)).recent == 2


async def test_pets_outside_the_window_do_not_count_as_recent(db):
    """A pet older than RECENT_PET_WINDOW has left the window; the cat forgets."""
    stale = db._utcnow() - db.RECENT_PET_WINDOW - timedelta(seconds=1)
    async with db._require_session()() as session:
        session.add(db.PetEvent(user_id=ALICE, guild_id=GUILD_A, created_at=stale))
        await session.commit()

    assert (await db.increment_pet_count(ALICE, GUILD_A)).recent == 0


async def test_a_pet_just_inside_the_window_still_counts(db):
    fresh = db._utcnow() - db.RECENT_PET_WINDOW + timedelta(seconds=30)
    async with db._require_session()() as session:
        session.add(db.PetEvent(user_id=ALICE, guild_id=GUILD_A, created_at=fresh))
        await session.commit()

    assert (await db.increment_pet_count(ALICE, GUILD_A)).recent == 1


async def test_pet_count_of_a_player_who_never_petted_is_zero(db):
    assert await db.get_pet_count(ALICE, GUILD_A) == 0


# --------------------------------------------------------------------------
# Relationship meter
# --------------------------------------------------------------------------


async def test_new_player_starts_at_the_configured_value(db):
    await db.increment_pet_count(ALICE, GUILD_A)
    assert await db.get_relationship(ALICE, GUILD_A) == db.RELATIONSHIP_START


async def test_relationship_of_an_unknown_player_reads_as_zero(db):
    assert await db.get_relationship(ALICE, GUILD_A) == 0


async def test_friendly_and_standoffish_reactions_move_it_by_five(db):
    await db.increment_pet_count(ALICE, GUILD_A)
    start = db.RELATIONSHIP_START

    assert await db.adjust_relationship(ALICE, GUILD_A, bot.RELATIONSHIP_STEP) == start + 5
    assert await db.adjust_relationship(ALICE, GUILD_A, -bot.RELATIONSHIP_STEP) == start


async def test_relationship_clamps_at_the_ceiling(db):
    await db.increment_pet_count(ALICE, GUILD_A)
    assert await db.adjust_relationship(ALICE, GUILD_A, 1000) == db.RELATIONSHIP_MAX
    # Already at the ceiling: a further increase must not exceed it.
    assert await db.adjust_relationship(ALICE, GUILD_A, 5) == db.RELATIONSHIP_MAX


async def test_relationship_clamps_at_the_floor(db):
    await db.increment_pet_count(ALICE, GUILD_A)
    assert await db.adjust_relationship(ALICE, GUILD_A, -1000) == db.RELATIONSHIP_MIN
    assert await db.adjust_relationship(ALICE, GUILD_A, -5) == db.RELATIONSHIP_MIN


async def test_adjusting_a_player_with_no_row_reports_zero_and_creates_nothing(db):
    """The meter is only meaningful for a player the server has seen."""
    assert await db.adjust_relationship(ALICE, GUILD_A, 5) == 0
    assert await db.get_pet_count(ALICE, GUILD_A) == 0


# --------------------------------------------------------------------------
# Two players in one server stay independent of each other
# --------------------------------------------------------------------------


async def test_two_players_in_one_server_have_separate_cats(db):
    await db.increment_pet_count(ALICE, GUILD_A)
    await db.increment_pet_count(ALICE, GUILD_A)
    await db.increment_pet_count(BOB, GUILD_A)
    await db.adjust_relationship(ALICE, GUILD_A, 25)

    assert await db.get_pet_count(ALICE, GUILD_A) == 2
    assert await db.get_pet_count(BOB, GUILD_A) == 1
    assert await db.get_relationship(BOB, GUILD_A) == database.RELATIONSHIP_START


async def test_one_players_recent_window_is_not_anothers(db):
    for _ in range(4):
        await db.increment_pet_count(ALICE, GUILD_A)
    assert (await db.increment_pet_count(BOB, GUILD_A)).recent == 0


async def test_guild_ids_above_32_bits_round_trip(db):
    """Discord snowflakes overflow INTEGER; the columns must be BIGINT."""
    assert GUILD_B > 2**32
    await db.increment_pet_count(ALICE, GUILD_B)
    assert await db.get_pet_count(ALICE, GUILD_B) == 1
