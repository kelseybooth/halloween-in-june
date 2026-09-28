"""The cat: pet counting, mood weighting, and the relationship meter."""

from datetime import timedelta

import pytest

import bot
import database
from conftest import ALICE, BOB, GUILD_A, GUILD_B


# --------------------------------------------------------------------------
# Mood weighting (pure, no database)
# --------------------------------------------------------------------------


# How many recent pets it takes to exhaust the cat's patience. Derived rather
# than written down, because both halves of it are balance numbers a writer is
# expected to retune - and a test that hardcodes this month's value fails on
# the tuning change rather than on the behaviour it is meant to protect.
PATIENCE = bot.BASE_FRIENDLY_CHANCE // bot.DECAY_PER_RECENT_PET


def test_friendly_chance_starts_at_base():
    assert bot.friendly_chance(0) == bot.BASE_FRIENDLY_CHANCE


@pytest.mark.parametrize("recent", range(PATIENCE + 1))
def test_friendly_chance_decays_one_step_per_recent_pet(recent):
    expected = bot.BASE_FRIENDLY_CHANCE - bot.DECAY_PER_RECENT_PET * recent
    assert bot.friendly_chance(recent) == expected


def test_the_chance_reaches_exactly_zero_rather_than_stepping_over_it():
    """True only while the base divides evenly by the step. If a retune breaks
    that, the cat never quite runs out of patience and this says so."""
    assert bot.friendly_chance(PATIENCE) == 0
    assert bot.friendly_chance(PATIENCE - 1) == bot.DECAY_PER_RECENT_PET


def test_friendly_chance_floors_at_zero_and_never_goes_negative():
    """A negative probability is treated as zero, not as a negative weight."""
    for recent in range(PATIENCE, PATIENCE + 33):
        assert bot.friendly_chance(recent) == 0


def test_choose_response_friendly_when_roll_is_under_the_chance(fixed_rng):
    """One point under the base, so a player with no recent pets gets the
    friendly pool."""
    roll = (bot.BASE_FRIENDLY_CHANCE - 1) / 100
    reaction = bot.choose_response(0, rng=fixed_rng.queue(roll))
    assert reaction.friendly is True
    assert reaction.text in bot.FRIENDLY_RESPONSES
    assert reaction.chance == bot.BASE_FRIENDLY_CHANCE


def test_choose_response_standoffish_when_roll_is_on_the_boundary(fixed_rng):
    """The comparison is `roll * 100 < chance`, so landing exactly on the
    base is standoffish."""
    roll = bot.BASE_FRIENDLY_CHANCE / 100
    reaction = bot.choose_response(0, rng=fixed_rng.queue(roll))
    assert reaction.friendly is False
    assert reaction.text in bot.STANDOFFISH_RESPONSES


def test_choose_response_is_always_standoffish_once_chance_hits_zero(fixed_rng):
    """No roll can be below 0, so past the cat's patience it is reliably
    hostile."""
    for roll in (0.0, 0.001, 0.5, 0.999):
        reaction = bot.choose_response(PATIENCE, rng=fixed_rng.queue(roll))
        assert reaction.friendly is False
        assert reaction.chance == 0


def test_response_pools_are_three_and_three_and_do_not_overlap():
    assert len(bot.FRIENDLY_RESPONSES) == 3
    assert len(bot.STANDOFFISH_RESPONSES) == 3
    assert not set(bot.FRIENDLY_RESPONSES) & set(bot.STANDOFFISH_RESPONSES)
    assert len(bot.PET_RESPONSES) == 6


def test_reaction_reports_the_chance_that_produced_it(fixed_rng):
    """The chance travels with the reaction, so the caller never recomputes it."""
    expected = bot.BASE_FRIENDLY_CHANCE - 3 * bot.DECAY_PER_RECENT_PET
    assert bot.choose_response(3, rng=fixed_rng.queue(0.1)).chance == expected


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


# --------------------------------------------------------------------------
# Nothing debug-shaped reaches players
# --------------------------------------------------------------------------


def test_debug_output_is_off():
    """A tripwire, not a tautology.

    SHOW_DEBUG_INFO appends the mood roll and the relationship score to every
    /pet reply, which shows players the dice behind the cat. It is useful
    locally and must never ship, so turning it on and forgetting fails here.
    """
    assert bot.SHOW_DEBUG_INFO is False


def test_a_pet_reply_carries_no_diagnostics(fixed_rng):
    """What the player actually sees: the response and their total, nothing more."""
    reaction = bot.choose_response(0, rng=fixed_rng.queue(0.1))
    message = f"{reaction.text}\n\nTotal pets: 7"
    if bot.SHOW_DEBUG_INFO:
        message += bot._debug_lines(reaction, 0, 50)

    assert "[testing]" not in message
    assert "mood:" not in message
    assert "relationship:" not in message
    assert "% friendly chance" not in message


# --------------------------------------------------------------------------
# relationship_at_pet
#
# Recorded ahead of the achievements that read it, because it is the one value
# that cannot be reconstructed later: the relationship is a running total, so a
# pet's score at the time is gone the moment the next pet moves it.
# --------------------------------------------------------------------------


async def pet_scores(db, user_id, guild_id):
    from sqlalchemy import select

    async with db._require_session()() as session:
        rows = await session.execute(
            select(db.PetEvent.relationship_at_pet)
            .where(db.PetEvent.user_id == user_id, db.PetEvent.guild_id == guild_id)
            .order_by(db.PetEvent.id)
        )
        return [r[0] for r in rows]


async def test_a_first_pet_records_the_starting_score(db):
    await db.increment_pet_count(ALICE, GUILD_A)
    assert await pet_scores(db, ALICE, GUILD_A) == [db.RELATIONSHIP_START]


async def test_each_pet_records_the_score_before_it_applied(db):
    """The point of the column: the value as it stood, not as it ended up."""
    await db.increment_pet_count(ALICE, GUILD_A)
    await db.adjust_relationship(ALICE, GUILD_A, 5)
    await db.increment_pet_count(ALICE, GUILD_A)
    await db.adjust_relationship(ALICE, GUILD_A, -5)
    await db.increment_pet_count(ALICE, GUILD_A)

    start = db.RELATIONSHIP_START
    assert await pet_scores(db, ALICE, GUILD_A) == [start, start + 5, start]


async def test_the_recorded_score_survives_later_movement(db):
    """A pet at 50 still reads 50 after the relationship has moved on."""
    await db.increment_pet_count(ALICE, GUILD_A)
    await db.adjust_relationship(ALICE, GUILD_A, -100)

    assert await pet_scores(db, ALICE, GUILD_A) == [db.RELATIONSHIP_START]


async def test_a_negative_relationship_is_recorded_as_negative(db):
    """One achievement counts pets at a negative score, so the sign has to land."""
    await db.increment_pet_count(ALICE, GUILD_A)
    await db.adjust_relationship(ALICE, GUILD_A, -80)
    await db.increment_pet_count(ALICE, GUILD_A)

    scores = await pet_scores(db, ALICE, GUILD_A)
    assert scores[1] == db.RELATIONSHIP_START - 80 < 0


async def test_scores_are_recorded_per_server(db):
    await db.increment_pet_count(ALICE, GUILD_A)
    await db.adjust_relationship(ALICE, GUILD_A, -60)
    await db.increment_pet_count(ALICE, GUILD_A)
    await db.increment_pet_count(ALICE, GUILD_B)

    assert await pet_scores(db, ALICE, GUILD_B) == [db.RELATIONSHIP_START]
