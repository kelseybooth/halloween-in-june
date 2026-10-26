"""The one line under the relationship prose: what the cat wants now.

Three conditions and six outcomes, and the whole of it is which
sentence appears when. The spec gives a table; this is that table,
driven through `/stats` rather than through the predicate, because the
two ways it can be wrong are both in the assembly: a pair that should
compose and does not, and a pair that should not and does.

**It is private.** `/stats @somebody` reports what a player has done;
this is what the cat happens to think of them this minute, which is
progress rather than result and nobody else's to read.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import resolve
import world


EXPECTANT = "Right now, the cat is watching you expectantly."
HUNGRY = "Right now, the cat is watching you with hunger in her eyes."
BOTH = (
    "Right now, the cat is watching you expectantly with hunger in her eyes."
)
CROWDED = "You've pet the cat a lot recently."

# A server the bot is merely a member of. The fixtures start both of
# conftest's guilds, so this one has to be nobody's.
UNSTARTED = 900000000000000999


@pytest.fixture
async def server(db):
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A,
        name="Test Server",
        channels=[halloween],
        members=[FakeMember(ALICE), FakeMember(BOB)],
    )
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, 0)
    await db.ensure_user_exists(ALICE, GUILD_A)
    return db, guild, halloween


async def status(server, who=ALICE):
    """The status line out of a real `/stats`, or None if there is none."""
    _, guild, halloween = server
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await bot.stats.callback(interaction, None)
    body = interaction.sent[-1][1]["embed"].description.split("\n")
    return next((line for line in body if line in
                 (EXPECTANT, HUNGRY, BOTH, CROWDED, f"{HUNGRY} {CROWDED}")), None)


async def pet(server, times, who=ALICE):
    _, guild, halloween = server
    for _ in range(times):
        interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
        await bot.pet.callback(interaction)


# **The literal drop, not `world.FEEDING_FROM_DROP`.** Written through
# the constant, every test below agreed with whatever the constant said,
# so the gate sitting seven drops early was invisible here: the house
# moved to 10 on 26 October and the cans went with it, while this said
# 3 and passed.
FEEDING_DROP = 10


async def feeding_time(db):
    """Drop 10, the house, where there is food in the game."""
    await resolve.set_current_drop(GUILD_A, FEEDING_DROP)


def test_the_gate_is_the_drop_the_cans_arrive_on():
    """The constant and the content have to name the same drop.

    `/stats` promising a hungry cat is a promise that `/use` on a can
    will answer, so the gate belongs on the drop the cans are in -
    read out of `things.tsv` rather than restated here, because the
    writers move them and nothing would tell us.
    """
    cans = min(
        thing.since_drop
        for thing in content_module.load_files().things
        if thing.thing_id in world.CAT_FOOD
    )

    assert world.FEEDING_FROM_DROP == FEEDING_DROP == cans


# --------------------------------------------------------------------------
# The table, row by row
# --------------------------------------------------------------------------


async def test_expectant_alone(server):
    """Better than even odds and nothing else to say."""
    assert await status(server) == EXPECTANT


async def test_nothing_at_all(server):
    """Exactly even odds is neither expectant nor crowded, and before
    drop 10 nobody is hungry - so there is no line, and a standing
    sentence that said so would be worse than silence."""
    await pet(server, 3)

    assert await status(server) is None


async def test_hungry_alone(server):
    db, *_ = server
    await feeding_time(db)
    await pet(server, 3)

    assert await status(server) == HUNGRY


async def test_expectant_and_hungry_are_one_sentence(server):
    """**Not composed.** *watching you expectantly with hunger in her
    eyes* is one sentence a writer wrote; joining the two would give
    *watching you expectantly. Right now, the cat is watching you with
    hunger in her eyes.*"""
    db, *_ = server
    await feeding_time(db)

    assert await status(server) == BOTH


async def test_crowded_alone(server):
    await pet(server, 5)

    assert await status(server) == CROWDED


async def test_hungry_and_crowded_compose(server):
    """**These two do compose**, because they are two separate facts
    and read as two sentences - which is also the order the spec puts
    them in: what she wants, then what you have been doing."""
    db, *_ = server
    await feeding_time(db)
    await pet(server, 5)

    assert await status(server) == f"{HUNGRY} {CROWDED}"


# --------------------------------------------------------------------------
# Where the boundaries are
# --------------------------------------------------------------------------


def test_expectant_and_crowded_can_never_coincide():
    """The table's dash in the crowded rows is a fact rather than a
    convention: both read the one chance, from opposite sides of it."""
    for recent in range(0, 20):
        assert not (bot._is_expectant(recent) and bot._is_crowded(recent))


def test_exactly_even_odds_is_neither():
    """A player at fifty percent is being told nothing useful in either
    direction. Strict on both sides, so the quiet band is one pet
    wide."""
    even = next(n for n in range(50) if bot.friendly_chance(n) == bot.BREAK_EVEN_CHANCE)

    assert not bot._is_expectant(even)
    assert not bot._is_crowded(even)
    assert bot._is_expectant(even - 1)
    assert bot._is_crowded(even + 1)


def test_the_warning_and_the_standing_condition_are_different_questions():
    """`_crowding_begins` is the edge and `_is_crowded` is the level.
    The nudge fires once because a line on every pet is wallpaper; the
    status line has to be true for as long as the condition is, because
    "you crossed over four pets ago" is not an answer to "where do I
    stand"."""
    crossing = next(n for n in range(50) if bot._crowding_begins(n))

    assert bot._is_crowded(crossing)
    assert bot._is_crowded(crossing + 3)
    assert not bot._crowding_begins(crossing + 3)


# --------------------------------------------------------------------------
# Hunger
# --------------------------------------------------------------------------


async def test_nobody_is_hungry_before_there_is_food(server):
    """**The gate that matters.** A player on any drop before the house
    has never been fed, so without it `/stats` tells all of them the cat
    is hungry in a game with nothing to feed her with.

    **Every earlier drop, not a hand-written three.** This read `(0, 1, 2)`
    and then drop 3, which was the whole of the gate when 3 was the house.
    The renumbering put five drops in that gap and the list did not grow
    with it, so it would have gone on passing while drops 3 to 9 all
    promised dinner.
    """
    earlier = sorted(
        drop.drop_id
        for drop in content_module.load_files().drops
        if drop.drop_id < FEEDING_DROP
    )
    assert earlier, "a gate with nothing before it is not a gate"

    for drop in earlier:
        await resolve.set_current_drop(GUILD_A, drop)
        assert not await bot._is_hungry(GUILD_A, ALICE), drop

    await resolve.set_current_drop(GUILD_A, FEEDING_DROP)
    assert await bot._is_hungry(GUILD_A, ALICE)


async def test_a_server_with_no_game_is_not_hungry_either(server):
    """A server nobody has started has no drop at all - `current_drop`
    is None there, not zero, and comparing None to a drop number
    raises rather than reading as early."""
    assert await resolve.current_drop(UNSTARTED) is resolve.NO_GAME
    assert not await bot._is_hungry(UNSTARTED, ALICE)


async def test_feeding_her_settles_it_for_eight_hours(server):
    db, *_ = server
    await feeding_time(db)
    await db.record_use(ALICE, GUILD_A, "cat_food_salmon")

    assert not await bot._is_hungry(GUILD_A, ALICE)


async def test_and_she_is_hungry_again_afterwards(server):
    db, *_ = server
    await feeding_time(db)
    await db.record_use(ALICE, GUILD_A, "cat_food_salmon")

    await db.set_setting(GUILD_A, database.CLOCK_KEY, 1)

    assert await bot._is_hungry(GUILD_A, ALICE)


async def test_any_can_counts(server):
    """Hunger does not care which flavour, which is why it is a MAX
    over the rows rather than a column on the player."""
    db, *_ = server
    await feeding_time(db)
    await db.record_use(ALICE, GUILD_A, "cat_food_gourmet")

    assert not await bot._is_hungry(GUILD_A, ALICE)


async def test_using_something_that_is_not_food_does_not_feed_her(server):
    db, *_ = server
    await feeding_time(db)
    await db.record_use(ALICE, GUILD_A, world.CAT_BED)

    assert await bot._is_hungry(GUILD_A, ALICE)


async def test_hunger_is_per_player(server):
    db, *_ = server
    await feeding_time(db)
    await db.ensure_user_exists(BOB, GUILD_A)
    await db.record_use(ALICE, GUILD_A, "cat_food_tuna")

    assert not await bot._is_hungry(GUILD_A, ALICE)
    assert await bot._is_hungry(GUILD_A, BOB)


# --------------------------------------------------------------------------
# Whose line it is
# --------------------------------------------------------------------------


async def test_it_never_appears_on_somebody_elses_stats(server):
    """A standing condition that changes minute to minute is progress,
    not result. The public view carries what a player has done."""
    db, guild, halloween = server
    await feeding_time(db)
    await db.ensure_user_exists(BOB, GUILD_A)
    await pet(server, 5, who=BOB)

    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    await bot.stats.callback(interaction, guild.get_member(BOB))
    body = interaction.sent[-1][1]["embed"].description

    for line in (EXPECTANT, HUNGRY, BOTH, CROWDED):
        assert line not in body


async def test_it_sits_under_the_prose_and_above_the_count(server):
    body = (await _embed(server)).description.split("\n")

    assert body[1].startswith("The cat is")
    assert body[2] == EXPECTANT
    assert body[3].startswith("Total pets")


async def _embed(server, who=ALICE):
    _, guild, halloween = server
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await bot.stats.callback(interaction, None)
    return interaction.sent[-1][1]["embed"]
