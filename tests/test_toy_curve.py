"""Drop 2 balance: what a toy pays as the day goes on.

Each successful play is worth three quarters of the one before it, so
a player's day runs 10, 8, 6, 4, 3, 2, 2, 1, 1, 1, 1 and then nothing
- thirty nine points in all, most of them in the first few plays.

**A curve rather than a cap, and the difference is what a player
sees.** A cap pays full value and then abruptly pays nothing, which
reads as the game having broken; a curve tails off, so the eleventh
play paying one point is visibly the same rule as the second paying
eight. Nothing announces it, and that is the point.

The one easy thing to break is the far end of it. Success used to be
read off the meter moving (`effect.relationship is not None`), and a
play worth zero moves nothing - so that reading turns the tail of the
curve into refusals: refusal copy, no public line, and the ramp
climbing on a play that landed. Several tests below exist only to pin
that success is read off the play instead.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from conftest import ALICE, BOB, GUILD_A, GUILD_B
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
import resolve
import triggers
import world

WAND = "feather_wand"
BALL = "crinkle_ball"

# The shipped curve, play by play, and what a whole day of it comes to.
CURVE = [10, 8, 6, 4, 3, 2, 2, 1, 1, 1, 1]
A_DAY = 39


@pytest.fixture
async def channel(db):
    """A server on drop 2, with both toys in the channel."""
    achievements.clear()
    triggers.register_all()
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A,
        name="Test Server",
        channels=[halloween],
        members=[FakeMember(ALICE), FakeMember(BOB)],
    )
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, 2)
    await content_loader.place_arrived(GUILD_A)
    for toy in (WAND, BALL):
        await database.place_in_room(GUILD_A, content_module.CHANNEL_ROOM, toy, 1)
    for who in (ALICE, BOB):
        await database.ensure_user_exists(who, GUILD_A)
    bot.forget_public_pets()
    yield db, guild, halloween
    achievements.clear()


class _Loaded:
    def __init__(self, value):
        self._value = value

    def random(self):
        return self._value


def always(monkeypatch, *, succeed):
    monkeypatch.setattr(world, "random", _Loaded(0.0 if succeed else 0.999))


async def run(channel, command, *args, who=ALICE):
    _, guild, halloween = channel
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await command.callback(interaction, *args)
    return interaction


async def ready_again(db, who=ALICE, guild_id=GUILD_A):
    """Lift the cooldown without touching the day's play count.

    `clear_play_state` would clear both, which is right for a tester
    and useless for a test about the curve: it would reset the thing
    under test every time the clock got in the way.
    """
    async with db._require_session()() as session:
        await session.execute(
            update(database.User)
            .where(database.User.id == who, database.User.guild_id == guild_id)
            .values(toy_cooldown_until=None, toy_ramp=4)
        )
        await session.commit()


async def a_play(channel, monkeypatch, who=ALICE, thing="feather wand"):
    """One landed play, with the cooldown lifted first."""
    db, *_ = channel
    await ready_again(db, who)
    always(monkeypatch, succeed=True)
    return await run(channel, bot.use, thing, who=who)


async def score(who=ALICE, guild_id=GUILD_A):
    return await database.get_relationship(who, guild_id)


# --------------------------------------------------------------------------
# The curve
# --------------------------------------------------------------------------


def test_the_shipped_curve():
    """The numbers the balance was specified in, play by play."""
    assert [world.play_value(n, 10, 75) for n in range(1, 12)] == CURVE


def test_it_pays_nothing_from_the_twelfth_play():
    assert [world.play_value(n, 10, 75) for n in range(12, 20)] == [0] * 8


def test_a_whole_day_of_playing_comes_to_thirty_nine():
    assert sum(world.play_value(n, 10, 75) for n in range(1, 100)) == A_DAY


def test_the_first_play_is_the_base_rate():
    """`n` is one-based, so the first play of the day pays in full
    rather than already having a quarter taken off it."""
    assert world.play_value(1, 10, 75) == 10
    assert world.play_value(1, 20, 50) == 20


async def test_each_play_pays_its_place_on_the_curve(channel, monkeypatch):
    await run(channel, bot.take, "feather wand")

    running = 0
    for expected in CURVE:
        await a_play(channel, monkeypatch)
        running += expected
        assert await score() == running

    assert running == A_DAY


async def test_a_play_past_the_tail_pays_nothing(channel, monkeypatch):
    await run(channel, bot.take, "feather wand")
    for _ in CURVE:
        await a_play(channel, monkeypatch)

    await a_play(channel, monkeypatch)

    assert await score() == A_DAY


# --------------------------------------------------------------------------
# A play worth nothing is still a play
# --------------------------------------------------------------------------


async def spend_the_day(channel, monkeypatch):
    for _ in range(len(CURVE) + 1):
        await a_play(channel, monkeypatch)


async def test_it_still_counts_toward_tireless(channel, monkeypatch):
    """**The reason this is a curve and not a cap.** Twelve plays are
    twelve plays, whatever the last one paid."""
    await run(channel, bot.take, "feather wand")
    await spend_the_day(channel, monkeypatch)

    assert await database.use_count_of(ALICE, GUILD_A, WAND) == len(CURVE) + 1


async def test_it_still_reads_as_a_success(channel, monkeypatch):
    """The failure this is all guarding: success read off the meter
    rather than off the play turns the tail into refusals.

    Stops at the **first** play worth nothing rather than running the
    day out, because the second one earns *Purrsistent* and posts a
    line of its own - which would make this count two and say nothing
    about the play."""
    db, _, halloween = channel
    await run(channel, bot.take, "feather wand")
    for _ in CURVE:
        await a_play(channel, monkeypatch)

    # The public line has its own rate limit - two per half hour - and
    # a day of plays has long since spent it. Clearing it is what makes
    # this a test about the curve rather than about the limiter.
    bot.forget_public_pets()
    before = len(halloween.posted)
    await a_play(channel, monkeypatch)

    assert len(halloween.posted) == before + 1, "the public line still goes out"


async def test_it_still_resets_the_ramp(channel, monkeypatch):
    """Advancing it instead would make the next offer likelier
    *because* the player had run down the curve, which is backwards."""
    await run(channel, bot.take, "feather wand")
    await spend_the_day(channel, monkeypatch)

    ramp, _ = await database.play_state(GUILD_A, ALICE)
    assert ramp == 0


async def test_it_still_starts_the_cooldown(channel, monkeypatch):
    await run(channel, bot.take, "feather wand")
    await spend_the_day(channel, monkeypatch)

    _, until = await database.play_state(GUILD_A, ALICE)
    assert until is not None


# --------------------------------------------------------------------------
# What counts as a play
# --------------------------------------------------------------------------


async def test_refusals_do_not_move_the_player_down_the_curve(channel, monkeypatch):
    """**Only successes count.** A refusal is the cat saying no, and
    paying the player less for it would charge them for her mood."""
    await run(channel, bot.take, "feather wand")

    always(monkeypatch, succeed=False)
    for _ in range(4):
        await run(channel, bot.use, "feather wand")
    await a_play(channel, monkeypatch)

    assert await score() == CURVE[0]


async def test_both_toys_share_one_curve(channel, monkeypatch):
    """Per player, like the ramp and the cooldown. Carrying a second
    toy must not hand out a second fresh day."""
    await run(channel, bot.take, "feather wand")
    await run(channel, bot.take, "crinkle ball")

    await a_play(channel, monkeypatch, thing="feather wand")
    await a_play(channel, monkeypatch, thing="crinkle ball")

    assert await score() == CURVE[0] + CURVE[1]


async def test_the_day_is_per_player(channel, monkeypatch):
    await run(channel, bot.take, "feather wand")
    await run(channel, bot.take, "crinkle ball", who=BOB)
    for _ in range(3):
        await a_play(channel, monkeypatch)

    await a_play(channel, monkeypatch, who=BOB, thing="crinkle ball")

    assert await score(ALICE) == sum(CURVE[:3])
    assert await score(BOB) == CURVE[0]


# --------------------------------------------------------------------------
# Which day
# --------------------------------------------------------------------------


async def test_the_curve_starts_again_tomorrow(channel, monkeypatch):
    """Pacific midnight, the same boundary the bed's once-a-day keeps -
    so a player does not get a different reset hour depending on which
    thing they touched."""
    await run(channel, bot.take, "feather wand")
    await spend_the_day(channel, monkeypatch)
    assert await score() == A_DAY

    await database.set_setting(GUILD_A, database.CLOCK_KEY, 1)
    await a_play(channel, monkeypatch)

    assert await score() == A_DAY + CURVE[0]


async def test_yesterdays_stamp_reads_as_no_plays_yet(channel):
    """**No nightly sweep.** The day rolls over on the read, so a
    server the bot was down for does not wake up partway down
    yesterday's curve."""
    today = await database.server_today(GUILD_A)
    for _ in range(3):
        await database.count_toy_play(GUILD_A, ALICE, today)
    assert await database.toy_plays_today(GUILD_A, ALICE, today) == 3

    await database.set_setting(GUILD_A, database.CLOCK_KEY, 1)
    tomorrow = await database.server_today(GUILD_A)

    assert await database.toy_plays_today(GUILD_A, ALICE, tomorrow) == 0


async def test_a_play_worth_nothing_still_stamps_the_day(channel, monkeypatch):
    """Otherwise the row says yesterday while holding today's count,
    and every reader has to know to distrust it."""
    await run(channel, bot.take, "feather wand")
    await spend_the_day(channel, monkeypatch)

    today = await database.server_today(GUILD_A)
    assert await database.toy_plays_today(GUILD_A, ALICE, today) == len(CURVE) + 1


async def test_the_count_is_one_based(channel):
    """The first play of the day comes back as 1, which is the `n` the
    curve is written in terms of."""
    today = await database.server_today(GUILD_A)

    assert await database.count_toy_play(GUILD_A, ALICE, today) == 1
    assert await database.count_toy_play(GUILD_A, ALICE, today) == 2


# --------------------------------------------------------------------------
# The three dials
# --------------------------------------------------------------------------


async def test_the_cooldown_is_ten_minutes(channel):
    assert await world.play_cooldown(GUILD_A) == timedelta(minutes=10)


async def test_a_success_starts_the_cooldown(channel, monkeypatch):
    await run(channel, bot.take, "feather wand")
    await a_play(channel, monkeypatch)

    _, until = await database.play_state(GUILD_A, ALICE)
    now = await database.server_now(GUILD_A)
    assert (until - now).total_seconds() == pytest.approx(600, abs=30)


async def test_every_dial_is_tunable_per_server(channel):
    """In config rather than in code, because a number retuned
    mid-beta has to leave a dated trace - otherwise the interaction
    rows from before and after it cannot be told apart."""
    await database.set_config(GUILD_A, world.PLAY_COOLDOWN_SETTING, 15)
    await database.set_config(GUILD_A, world.TOY_BASE_SETTING, 20)
    await database.set_config(GUILD_A, world.TOY_DECAY_SETTING, 50)

    assert (await world.play_cooldown(GUILD_A)).total_seconds() == 15 * 60
    assert await world.toy_base_points(GUILD_A) == 20
    assert await world.toy_decay_percent(GUILD_A) == 50

    assert (await world.play_cooldown(GUILD_B)).total_seconds() == 10 * 60
    assert await world.toy_base_points(GUILD_B) == 10
    assert await world.toy_decay_percent(GUILD_B) == 75


async def test_retuning_the_curve_changes_what_a_play_pays(channel, monkeypatch):
    await database.set_config(GUILD_A, world.TOY_BASE_SETTING, 20)
    await database.set_config(GUILD_A, world.TOY_DECAY_SETTING, 50)
    await run(channel, bot.take, "feather wand")

    for expected in (20, 30, 35):
        await a_play(channel, monkeypatch)
        assert await score() == expected


def test_the_decay_is_a_percentage_because_the_registry_holds_integers():
    """`/admin_config` takes a whole number of at least one, so the
    ratio is stored as percent. Named for it, so that nobody retuning
    it types 0.75 and turns every play after the first into nothing."""
    default, _ = database.CONFIG_KEYS[world.TOY_DECAY_SETTING]

    assert world.TOY_DECAY_SETTING.endswith("_percent")
    assert default == 75


# --------------------------------------------------------------------------
# What the log says
# --------------------------------------------------------------------------


async def toy_rows(db):
    async with db._require_session()() as session:
        return list(
            (
                await session.scalars(
                    select(database.InteractionLog)
                    .where(
                        database.InteractionLog.action == database.USE,
                        database.InteractionLog.thing_id == WAND,
                        database.InteractionLog.outcome == database.SUCCESS,
                    )
                    .order_by(database.InteractionLog.id)
                )
            ).all()
        )


async def test_every_play_is_logged_with_what_it_paid(channel, monkeypatch):
    """**Zeros included**, which is what lets the data show where on
    the curve players stop rather than only where they were still
    earning."""
    db, *_ = channel
    await run(channel, bot.take, "feather wand")
    await spend_the_day(channel, monkeypatch)

    paid = [row.relationship_delta for row in await toy_rows(db)]
    assert paid == CURVE + [0]


async def test_each_row_says_where_on_the_curve_it_fell(channel, monkeypatch):
    """The delta alone cannot say: two players both earning one point
    are in very different places if one is on their eighth play and
    the other on their eleventh."""
    db, *_ = channel
    await run(channel, bot.take, "feather wand")
    for _ in range(3):
        await a_play(channel, monkeypatch)

    assert [row.detail for row in await toy_rows(db)] == ["play=1", "play=2", "play=3"]


async def test_a_play_worth_nothing_is_logged_as_a_success(channel, monkeypatch):
    """**Zero, not null.** Null is reserved for rows that cannot say -
    the ones carried over from `pet_events`. This one can, and
    `success` beside the zero is what separates it from a refusal,
    which writes the same zero."""
    db, *_ = channel
    await run(channel, bot.take, "feather wand")
    await spend_the_day(channel, monkeypatch)

    last = (await toy_rows(db))[-1]
    assert last.relationship_delta == 0
    assert last.outcome == database.SUCCESS
    assert last.detail == f"play={len(CURVE) + 1}"


async def test_a_play_worth_nothing_still_records_the_score(channel, monkeypatch):
    """The meter did not move, so the score has to be read rather than
    reported - otherwise the row is the one thing `score_after` exists
    to prevent, a row you can only interpret by summing deltas from
    the beginning of time."""
    db, *_ = channel
    await run(channel, bot.take, "feather wand")
    await spend_the_day(channel, monkeypatch)

    assert (await toy_rows(db))[-1].score_after == A_DAY


# --------------------------------------------------------------------------
# Testing it
# --------------------------------------------------------------------------


async def test_clearing_the_play_state_starts_the_curve_again(channel, monkeypatch):
    """It blocks a tester in exactly the way the cooldown does: eleven
    plays into a day there is no way to see a full-value play again
    until tomorrow."""
    await run(channel, bot.take, "feather wand")
    await spend_the_day(channel, monkeypatch)

    await database.clear_play_state(GUILD_A, ALICE)
    await a_play(channel, monkeypatch)

    assert await score() == A_DAY + CURVE[0]


# --------------------------------------------------------------------------
# Purrsistent: playing after it stopped paying
# --------------------------------------------------------------------------


async def earned(guild_id=GUILD_A, who=ALICE):
    return await database.player_achievements_of(guild_id, who)


async def test_it_takes_two_plays_worth_nothing(channel, monkeypatch):
    """**Two, not one.** The first free play can be an accident of a
    long afternoon; coming back for a second is the gesture."""
    await run(channel, bot.take, "feather wand")
    for _ in CURVE:
        await a_play(channel, monkeypatch)
    assert "purrsistent" not in await earned()

    await a_play(channel, monkeypatch)
    assert "purrsistent" not in await earned()

    await a_play(channel, monkeypatch)
    assert "purrsistent" in await earned()


async def test_paying_plays_do_not_count_however_many(channel, monkeypatch):
    """Eleven plays that all paid something is a good afternoon, not
    this. The whole achievement is about the ones worth nothing."""
    await run(channel, bot.take, "feather wand")
    for _ in CURVE:
        await a_play(channel, monkeypatch)

    assert "purrsistent" not in await earned()


async def test_refusals_do_not_count(channel, monkeypatch):
    """A refusal is worth nothing too, and is the opposite of the
    thing being rewarded - the cat said no, the player did not persist
    through anything."""
    await run(channel, bot.take, "feather wand")
    always(monkeypatch, succeed=False)
    for _ in range(8):
        await run(channel, bot.use, "feather wand")

    assert "purrsistent" not in await earned()


async def test_two_free_plays_on_different_days_still_count(channel, monkeypatch):
    """**Lifetime, not daily.** Two in one afternoon and two a
    fortnight apart are the same gesture, and a daily counter would
    make the second depend on which the player happened to be."""
    await run(channel, bot.take, "feather wand")
    for _ in range(len(CURVE) + 1):
        await a_play(channel, monkeypatch)
    assert "purrsistent" not in await earned()

    # Tomorrow, where the curve starts again - so the player has to
    # work all the way down it a second time to earn a second free play.
    await database.set_setting(GUILD_A, database.CLOCK_KEY, 1)
    for _ in range(len(CURVE) + 1):
        await a_play(channel, monkeypatch)

    assert "purrsistent" in await earned()


async def test_it_is_still_held_once_the_cat_pays_again(channel, monkeypatch):
    """Awards are idempotent and nothing takes one back: a new day
    paying ten points again does not undo yesterday's persistence."""
    await run(channel, bot.take, "feather wand")
    for _ in range(len(CURVE) + 2):
        await a_play(channel, monkeypatch)
    assert "purrsistent" in await earned()

    await database.set_setting(GUILD_A, database.CLOCK_KEY, 1)
    await a_play(channel, monkeypatch)

    assert "purrsistent" in await earned()


async def test_the_count_is_per_player(channel, monkeypatch):
    await run(channel, bot.take, "feather wand")
    await run(channel, bot.take, "crinkle ball", who=BOB)
    for _ in range(len(CURVE) + 2):
        await a_play(channel, monkeypatch)

    assert "purrsistent" in await earned()
    assert "purrsistent" not in await earned(who=BOB)
