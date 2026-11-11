"""Drop 46's one toy that does something after you put it down.

Every other toy is a play and a score. The mouse changes the odds on a
later `/pet`, which makes it the first toy keyed on its own id - named
in `world.play_with` rather than given a column, because a `catnip`
flag would be a column with one row set and the next toy with a
mechanic will want its own function, not the same flag.

**Two values and one stamp.** The charges count down per pet; the
stamp carries both the five-minute lapse and the thirty-minute
cooldown. One stamp rather than two columns is what stops a player
burning three pets quickly and starting a fresh buff - the charges run
out, the stamp does not move.

**The player is never told it worked.** The only sign is a line on a
friendly pet. A line on a standoffish one would be the game explaining
that the mouse had failed, and the public pet line never mentions it
at all: the room has no way to know a mouse was involved.
"""

from datetime import timedelta

import pytest

from conftest import ALICE, GUILD_A

import bot
import content as content_module
import content_loader
import database
import resolve
import world

MOUSE = "catnip_mouse"
SUFFIX = "She seems more blissful than usual."


@pytest.fixture
async def player(db):
    await content_loader.load_content(content_module.load_files())
    await resolve.set_current_drop(GUILD_A, 46)
    await db.ensure_user_exists(ALICE, GUILD_A)
    return db


async def now():
    return await database.server_now(GUILD_A)


# --------------------------------------------------------------------------
# The roll
# --------------------------------------------------------------------------


def test_the_buff_goes_in_before_the_floor():
    """**The whole rule in three numbers.** Eight recent pets takes the
    raw chance to zero; twenty-five points added to the raw number gives
    twenty-five, while adding them after the clamp would hand a pestering
    player a free quarter-chance on top of the zero they earned.

    The mouse makes the cat friendlier. It does not excuse crowding."""
    assert bot.friendly_chance(8) == 0
    assert bot.friendly_chance(8, buff=25) == 25
    assert bot.friendly_chance(0, buff=25) == 100


def test_and_still_cannot_pass_a_hundred():
    assert bot.friendly_chance(0, buff=100) == 100


# --------------------------------------------------------------------------
# Starting it
# --------------------------------------------------------------------------


async def test_a_successful_play_starts_a_buff(player):
    assert await world.catnip_takes_hold(GUILD_A, ALICE, await now())

    charges, stamped = await database.catnip_state(GUILD_A, ALICE)
    assert charges == 3
    assert stamped is not None


async def test_a_second_play_inside_the_cooldown_does_nothing(player):
    when = await now()
    await world.catnip_takes_hold(GUILD_A, ALICE, when)
    await database.spend_catnip_charge(GUILD_A, ALICE)

    assert not await world.catnip_takes_hold(
        GUILD_A, ALICE, when + timedelta(minutes=29)
    )

    charges, _ = await database.catnip_state(GUILD_A, ALICE)
    assert charges == 2


async def test_and_one_after_it_does(player):
    when = await now()
    await world.catnip_takes_hold(GUILD_A, ALICE, when)

    assert await world.catnip_takes_hold(GUILD_A, ALICE, when + timedelta(minutes=31))

    charges, _ = await database.catnip_state(GUILD_A, ALICE)
    assert charges == 3


async def test_spending_the_charges_does_not_reopen_the_cooldown(player):
    """**The reason one stamp carries both clocks.** A player who burns
    three pets in thirty seconds would otherwise be able to start a
    fresh buff immediately, and the mouse would be a permanent effect
    for anybody willing to spam `/pet`."""
    when = await now()
    await world.catnip_takes_hold(GUILD_A, ALICE, when)
    for _ in range(3):
        await database.spend_catnip_charge(GUILD_A, ALICE)

    charges, _ = await database.catnip_state(GUILD_A, ALICE)
    assert charges == 0
    assert not await world.catnip_takes_hold(
        GUILD_A, ALICE, when + timedelta(minutes=1)
    )


# --------------------------------------------------------------------------
# Running out, two ways
# --------------------------------------------------------------------------


async def test_it_is_worth_points_while_it_lasts(player):
    when = await now()
    await world.catnip_takes_hold(GUILD_A, ALICE, when)

    assert await world.catnip_in_force(GUILD_A, ALICE, when) == 25


async def test_three_pets_use_it_up(player):
    when = await now()
    await world.catnip_takes_hold(GUILD_A, ALICE, when)
    for _ in range(3):
        assert await world.catnip_in_force(GUILD_A, ALICE, when) == 25
        await world.spend_catnip(GUILD_A, ALICE)

    assert await world.catnip_in_force(GUILD_A, ALICE, when) == 0


async def test_five_minutes_use_it_up_too(player):
    """Whichever runs out first - and the clock is checked on read, so a
    buff nobody pet through is over the moment somebody does."""
    when = await now()
    await world.catnip_takes_hold(GUILD_A, ALICE, when)

    assert await world.catnip_in_force(GUILD_A, ALICE, when + timedelta(minutes=4)) == 25
    assert await world.catnip_in_force(GUILD_A, ALICE, when + timedelta(minutes=5)) == 0

    charges, _ = await database.catnip_state(GUILD_A, ALICE)
    assert charges == 0


async def test_a_lapsed_buff_still_holds_the_cooldown(player):
    """The charges are zeroed and the stamp is kept, so the thirty
    minutes run from the play and not from whenever it happened to be
    noticed."""
    when = await now()
    await world.catnip_takes_hold(GUILD_A, ALICE, when)
    await world.catnip_in_force(GUILD_A, ALICE, when + timedelta(minutes=10))

    assert not await world.catnip_takes_hold(
        GUILD_A, ALICE, when + timedelta(minutes=11)
    )


async def test_nobody_has_a_buff_by_default(player):
    assert await world.catnip_in_force(GUILD_A, ALICE, await now()) == 0


# --------------------------------------------------------------------------
# What the player sees
# --------------------------------------------------------------------------


async def test_the_line_is_the_work_orders_words(player):
    import phrasing

    assert await phrasing.default_say("pet.buffed_suffix") == SUFFIX


async def test_only_the_mouse_starts_one(player):
    """Every other toy is still a play and a score, which is what keeps
    the other nine a content change."""
    class Never:
        @staticmethod
        def random():
            return 0.0

    class Always:
        @staticmethod
        def random():
            return 1.0

    when = await now()
    for _ in range(4):
        await world.play_with(GUILD_A, ALICE, when, rng=Always, thing_id="acorn")
    effect = await world.play_with(GUILD_A, ALICE, when, rng=Never, thing_id="acorn")

    assert effect.played
    charges, stamped = await database.catnip_state(GUILD_A, ALICE)
    assert charges == 0
    assert stamped is None


async def test_a_refused_play_buffs_nothing(player, monkeypatch):
    """The cat has to actually take the mouse. A refusal advances the
    ramp and starts nothing, which is true of every toy and has to stay
    true of this one."""

    class Always:
        @staticmethod
        def random():
            return 1.0

    effect = await world.play_with(
        GUILD_A, ALICE, await now(), rng=Always, thing_id=MOUSE
    )

    assert not effect.played
    charges, stamped = await database.catnip_state(GUILD_A, ALICE)
    assert charges == 0
    assert stamped is None



# --------------------------------------------------------------------------
# The pet, with a mouse behind it
#
# Driven through `/pet` rather than through `world`, because the three
# halves of the buff live in three places and only this path joins them:
# `catnip_in_force` reads it, `choose_response` rolls with it, and the
# suffix is appended in the handler. Mutating any one of them left every
# test in the first half of this file green.
# --------------------------------------------------------------------------


async def a_thread():
    """A player standing in the Entryway with the house loaded."""
    from fake_discord import FakeChannel, FakeGuild, FakeMember

    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(GUILD_A, channels=[halloween], members=[FakeMember(ALICE)])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await database.start_game(
        ALICE, GUILD_A, "EN", await resolve.rooms_open_at_launch()
    )
    halloween.add_active(*[name for _, name in await resolve.all_rooms()])
    return guild, next(t for t in halloween.threads if t.name == "Entryway")


async def pets(rolls):
    """One `/pet` per roll, returning each private reply.

    **A list rather than a flag**, because the buff takes the chance to
    80 + 25 = 105 at zero recent pets, which clamps to 100 - so no roll
    can come back standoffish until the player has pet at least once.
    Forcing the mood needs a sequence, not a boolean.
    """
    from fake_discord import FakeInteraction

    guild, thread = await a_thread()
    said = []
    for roll in rolls:
        bot.random.random = lambda value=roll: value
        interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=thread)
        await bot.pet.callback(interaction)
        said.append("\n".join(text for text, _ in interaction.sent if text))
    return said


@pytest.fixture(autouse=True)
def _restore_random():
    original = bot.random.random
    yield
    bot.random.random = original


async def test_a_friendly_pet_says_so(player):
    """**The only sign the player gets.** Nothing announces the buff when
    it starts, nothing shows it in `/stats`, and the public pet line is
    unchanged - this sentence is the whole of it."""
    await world.catnip_takes_hold(GUILD_A, ALICE, await now())

    assert SUFFIX in (await pets([0.0]))[0]


async def test_a_standoffish_one_does_not(player):
    """A line here would be the game explaining that the mouse had
    failed, which is worse than silence.

    The second pet is the standoffish one: with one pet behind it the
    chance is 80 - 10 + 25 = 95, so a roll of 0.999 misses."""
    await world.catnip_takes_hold(GUILD_A, ALICE, await now())

    first, second = await pets([0.0, 0.999])

    assert SUFFIX in first
    assert SUFFIX not in second


async def test_the_buff_actually_changes_the_odds(player):
    """**The assertion the other two cannot make.** A roll of 0.0 is
    friendly with the buff or without it and a roll of 0.999 misses
    either way, so both of the tests above pass with `buff=buff` deleted
    from the call to `choose_response`.

    One pet in, the chance is 70 without the mouse and 95 with it. A
    roll of 0.8 is the gap: standoffish on its own, friendly on catnip.
    """
    await world.catnip_takes_hold(GUILD_A, ALICE, await now())
    first, second = await pets([0.0, 0.8])

    assert SUFFIX in second, "0.8 should land inside the buffed 95"

    # And the control, on a player with no mouse behind them: the same
    # second roll, now against 70, misses.
    await database.clear_catnip_charges(GUILD_A, ALICE)
    await database.increment_pet_count(ALICE, GUILD_A, drop=46)
    assert bot.friendly_chance(1) == 70
    assert bot.friendly_chance(1, buff=25) == 95


async def test_either_way_it_costs_a_pet(player):
    """*Three pets, friendly or not.* A buff that only paid for successes
    would last until it produced three of them, which is a different and
    much stronger mechanic than the one that was asked for."""
    await world.catnip_takes_hold(GUILD_A, ALICE, await now())

    await pets([0.0, 0.999])

    charges, _ = await database.catnip_state(GUILD_A, ALICE)
    assert charges == 1


async def test_without_a_buff_there_is_no_line(player):
    """The control, so the assertion above is about the buff rather than
    about the words always being there."""
    from types import SimpleNamespace

    from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(GUILD_A, channels=[halloween], members=[FakeMember(ALICE)])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await database.start_game(
        ALICE, GUILD_A, "EN", await resolve.rooms_open_at_launch()
    )
    halloween.add_active(*[name for _, name in await resolve.all_rooms()])
    thread = next(t for t in halloween.threads if t.name == "Entryway")

    bot.random.random = lambda: 0.0  # noqa: E731
    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=thread)
    await bot.pet.callback(interaction)

    assert SUFFIX not in "\n".join(text for text, _ in interaction.sent if text)


async def test_a_successful_one_does(player):
    """**The ramp has to be climbed first**, which is why this walks it:
    `play_chance(0)` is zero, so the first offer of any toy is a
    guaranteed refusal and a test that rolled a perfect zero against it
    would still be refused. Four refusals take the chance to 100."""

    class Always:
        @staticmethod
        def random():
            return 1.0

    class Never:
        @staticmethod
        def random():
            return 0.0

    when = await now()
    for _ in range(4):
        await world.play_with(GUILD_A, ALICE, when, rng=Always, thing_id=MOUSE)
    assert (await database.catnip_state(GUILD_A, ALICE))[0] == 0

    effect = await world.play_with(GUILD_A, ALICE, when, rng=Never, thing_id=MOUSE)

    assert effect.played
    charges, _ = await database.catnip_state(GUILD_A, ALICE)
    assert charges == 3
