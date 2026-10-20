"""The cat bed: drop 1's whole content, and the first thing to use.

One cushion in the channel. Usable, not takeable, never consumed - the
bed on the last day of October is the same bed as on the first. Fluffing
it is worth fifteen points, once a day, and it is the one interaction
with the cat that cannot go wrong.

It is also the first thing that moves the relationship without petting,
which is the case `on_relationship_change` was added for: a player who
crosses fifty by shaking out a cushion has to be noticed then rather
than at their next pet.
"""

from datetime import timedelta

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
import resolve
import triggers
import world

BED = "cat_bed"
FLUFFED = "You shake out the cushion"
REFUSED = "already looks fluffy"


@pytest.fixture
async def channel(db):
    """A server on drop 1: a cat, a bed, and nothing else at all."""
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
    await resolve.set_current_drop(GUILD_A, 1)
    yield db, guild, halloween
    achievements.clear()


async def fluff(channel, who=ALICE, thing="cat bed"):
    _, guild, halloween = channel
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await bot.use.callback(interaction, thing)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


async def score(who=ALICE):
    return await database.get_relationship(who, GUILD_A)


# --------------------------------------------------------------------------
# Fluffing it
# --------------------------------------------------------------------------


async def test_it_can_be_used_from_the_channel(channel):
    assert FLUFFED in replies(await fluff(channel))


async def test_it_is_worth_fifteen(channel):
    await fluff(channel)

    assert await score() == world.BED_FLUFF


async def test_a_player_with_no_row_gets_one(channel):
    """`/enter` does not exist at drop 1, so the first thing a player
    does may be this. Without a row the fifteen points would go
    nowhere and the command would look like it worked."""
    assert await database.get_game_state(ALICE, GUILD_A) is None

    await fluff(channel)

    assert await score() == world.BED_FLUFF


async def test_an_alias_works(channel):
    assert FLUFFED in replies(await fluff(channel, thing="cushion"))


async def test_the_reply_is_private(channel):
    assert (await fluff(channel)).was_private


async def test_the_fluff_itself_is_not_posted_in_the_channel(channel):
    """Placing a plank is the game's only public use, and this is not
    that: fluffing a cushion is between a player and the cat.

    The channel does get one line, and it is not this one - *Fluffed to
    Perfection* announces like every other achievement, carrying the
    name and not the prose.
    """
    _, _, halloween = channel

    await fluff(channel)

    posted = " ".join(halloween.posted)
    assert FLUFFED not in posted
    assert "Fluffed to Perfection" in posted


async def test_a_second_fluff_announces_nothing(channel):
    """The achievement is already held, and the refusal is private."""
    _, _, halloween = channel
    await fluff(channel)
    before = len(halloween.posted)

    await fluff(channel)

    assert len(halloween.posted) == before


# --------------------------------------------------------------------------
# Once a day
# --------------------------------------------------------------------------


async def test_the_second_fluff_is_refused(channel):
    await fluff(channel)

    assert REFUSED in replies(await fluff(channel))


async def test_a_refused_fluff_is_worth_nothing(channel):
    await fluff(channel)

    await fluff(channel)

    assert await score() == world.BED_FLUFF


async def test_everybody_gets_their_own_day(channel):
    """A shared fixture with a per-player cooldown: everyone can fluff
    it, nobody can fluff it twice."""
    await fluff(channel)

    assert FLUFFED in replies(await fluff(channel, who=BOB))
    assert await score(BOB) == world.BED_FLUFF


async def test_the_cooldown_lets_go_after_a_day(channel):
    db, _, _ = channel
    await fluff(channel)
    async with db._require_session()() as session:
        from datetime import timedelta

        from sqlalchemy import update

        await session.execute(
            update(db.ThingUse)
            .where(db.ThingUse.user_id == ALICE, db.ThingUse.thing_id == BED)
            .values(last_used_at=db._utcnow() - timedelta(hours=25))
        )
        await session.commit()

    assert FLUFFED in replies(await fluff(channel))
    assert await score() == world.BED_FLUFF * 2


# --------------------------------------------------------------------------
# It is scenery, not stock
# --------------------------------------------------------------------------


async def test_it_is_never_consumed(channel):
    """The bed on the last day of October is the same bed."""
    db, _, _ = channel

    await fluff(channel)

    assert await resolve.things_in_room(GUILD_A, content_module.CHANNEL_ROOM)


async def test_it_is_not_takeable(channel):
    parsed = content_module.load_files()

    assert parsed.things_by_id[BED].takeable is False


async def test_its_refusal_for_take_is_written_and_waiting(channel):
    """`/take` does not exist until drop 2, and the string is ready for
    when it does."""
    text = await resolve.thing_text(GUILD_A, BED, "take_fail")

    assert text and "claims it for her own" in text


# --------------------------------------------------------------------------
# What it tells the rest of the game
# --------------------------------------------------------------------------


async def test_fluffing_counts_as_touching_the_cat(channel):
    """The drift's skip condition is any interaction, not just petting."""
    await fluff(channel)

    async with database._require_session()() as session:
        from sqlalchemy import select

        stamped = await session.scalar(
            select(database.User.last_cat_interaction_date).where(
                database.User.id == ALICE, database.User.guild_id == GUILD_A
            )
        )
    assert stamped == database.pacific_today()


async def test_a_refused_fluff_counts_too(channel):
    """Attempts, not successes. A player who came and found the bed
    already plump was not absent."""
    db, _, _ = channel
    await fluff(channel)
    await database.touched_the_cat(ALICE, GUILD_A, database.pacific_today())
    async with db._require_session()() as session:
        from sqlalchemy import update

        await session.execute(
            update(db.User)
            .where(db.User.id == ALICE, db.User.guild_id == GUILD_A)
            .values(last_cat_interaction_date=None)
        )
        await session.commit()

    await fluff(channel)  # refused, inside the window

    async with db._require_session()() as session:
        from sqlalchemy import select

        stamped = await session.scalar(
            select(db.User.last_cat_interaction_date).where(
                db.User.id == ALICE, db.User.guild_id == GUILD_A
            )
        )
    assert stamped == database.pacific_today()


async def test_it_earns_fluffed_to_perfection(channel):
    await fluff(channel)

    earned = await database.player_achievements_of(GUILD_A, ALICE)
    assert "fluffed_to_perfection" in earned


async def test_crossing_fifty_by_fluffing_is_noticed(channel):
    """**The case `on_relationship_change` exists for.** Four fluffs is
    sixty, and not one of them is a pet - on the old wiring the player
    would have held fifty with nothing watching until they petted."""
    db, _, _ = channel
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.adjust_relationship(ALICE, GUILD_A, 40)

    await fluff(channel)

    assert await score() == 55
    assert "a_paw_in_the_door" in await database.player_achievements_of(GUILD_A, ALICE)


async def test_it_does_not_exist_at_drop_zero(channel):
    """The leak test for drop 1's only content."""
    await resolve.set_current_drop(GUILD_A, 0)

    interaction = await fluff(channel)

    assert FLUFFED not in replies(interaction)
    assert await score() == 0


# --------------------------------------------------------------------------
# The bed gives something up, once per player
#
# It fills the hole drop 2 opened: without it the channel holds toys and
# nothing else, and a player who plays one into its cooldown has nothing
# left to reach for.
# --------------------------------------------------------------------------


async def at_drop_two(channel):
    await resolve.set_current_drop(GUILD_A, 2)
    await content_loader.place_arrived(GUILD_A)


async def toys_loose(who=GUILD_A):
    return await database.present_of_type(who, content_module.CHANNEL_ROOM, "toy")


async def test_the_first_fluff_in_drop_two_dislodges_a_toy(channel):
    await at_drop_two(channel)
    before = len(await toys_loose())

    await fluff(channel)

    assert len(await toys_loose()) >= before


async def test_it_happens_once_per_player_ever(channel):
    """Bounded by construction, so it cannot silt the channel however
    many players a server has."""
    await at_drop_two(channel)
    await fluff(channel)
    assert await database.has_been_told(GUILD_A, ALICE, world.BED_STASH)

    async with database._require_session()() as session:
        from sqlalchemy import func, select

        total = await session.scalar(
            select(func.sum(database.RoomContents.count)).where(
                database.RoomContents.guild_id == GUILD_A
            )
        )

    await database.clear_cooldowns(GUILD_A, ALICE)
    async with database._require_session()() as session:
        from sqlalchemy import update

        await session.execute(
            update(database.ThingUse)
            .where(database.ThingUse.user_id == ALICE)
            .values(last_used_at=database._utcnow() - timedelta(hours=25))
        )
        await session.commit()
    await fluff(channel)

    async with database._require_session()() as session:
        from sqlalchemy import func, select

        after = await session.scalar(
            select(func.sum(database.RoomContents.count)).where(
                database.RoomContents.guild_id == GUILD_A
            )
        )
    assert after == total


async def test_a_refused_fluff_yields_nothing(channel):
    """Only a successful fluff. One refused inside its window gives up
    nothing."""
    await at_drop_two(channel)
    await database.notice(GUILD_A, BOB, "unrelated")

    await fluff(channel, who=BOB)
    first = await database.has_been_told(GUILD_A, BOB, world.BED_STASH)
    await fluff(channel, who=BOB)  # refused, inside the 24 hours

    assert first is True


async def test_nothing_is_dislodged_before_drop_two(channel):
    """There are no toys yet, so there is nothing in the bed to find -
    and the flag stays unset, so this player still gets theirs when
    drop 2 opens."""
    await fluff(channel)

    assert not await database.has_been_told(GUILD_A, ALICE, world.BED_STASH)


async def test_a_drop_one_tester_gets_theirs_when_drop_two_opens(channel):
    """**The trap the work order warns about.** Detecting "first fluff
    ever" would give nothing to every drop 1 tester - who are precisely
    the people on the server when drop 2 opens."""
    await fluff(channel)  # their first fluff ever, on drop 1
    await at_drop_two(channel)
    await database.clear_cooldowns(GUILD_A, ALICE)
    async with database._require_session()() as session:
        from sqlalchemy import update

        await session.execute(
            update(database.ThingUse)
            .where(database.ThingUse.user_id == ALICE)
            .values(last_used_at=database._utcnow() - timedelta(hours=25))
        )
        await session.commit()

    await fluff(channel)

    assert await database.has_been_told(GUILD_A, ALICE, world.BED_STASH)


async def test_the_yield_is_announced_in_the_channel(channel):
    _, _, halloween = channel
    await at_drop_two(channel)

    await fluff(channel)

    assert any("something falls out" in line for line in halloween.posted)


async def test_and_says_nothing_privately_at_all(channel):
    """**The public line is the whole event.**

    It used to be both: the channel said something fell out while the
    player's own reply said the same thing a second time and then told
    them to go and look. The one line now carries both halves - what
    fell out, and the cat taking the bed anyway - so there is nothing
    left for a private copy to add.
    """
    _, _, halloween = channel
    await at_drop_two(channel)

    interaction = await fluff(channel)

    assert any("something falls out" in line for line in halloween.posted)
    assert "You dislodged something from the bed" not in replies(interaction)
    assert interaction.withdrawn, "the spinner has to be taken back"


async def test_the_public_line_says_the_cat_takes_the_bed_anyway(channel):
    """The beat the private fluff text used to carry, moved rather than
    dropped: the point of the bed is that she settles into it."""
    _, _, halloween = channel
    await at_drop_two(channel)

    await fluff(channel)

    assert any("leaps into the bed and curls up" in line for line in halloween.posted)


async def test_a_fluff_that_yields_nothing_still_replies_privately(channel):
    """Only the *yield* goes public. An ordinary fluff is unchanged, and
    still carries its own rung."""
    await at_drop_two(channel)
    await fluff(channel)  # the one yield this player ever gets
    await database.clear_cooldowns(GUILD_A, ALICE)

    interaction = await fluff(channel)

    assert "shake out the cushion" in replies(interaction)
    assert not interaction.withdrawn


async def test_the_look_rung_survives_a_public_line_that_never_went_out(
    channel, monkeypatch
):
    """The fallback path, and the reason the rung is not spent when the
    public line *does* go out: a yield that said nothing anywhere would
    be a fluff that appeared to do nothing at all.

    Driven by emptying the string, which is the reachable version of
    this - `/use cat bed` is refused outside the announcement channel,
    so the channel is always there to post to.
    """
    original = bot.phrasing.default_say

    async def blank_the_public_line(key, **tokens):
        return "" if key == "bed_yield.public" else await original(key, **tokens)

    await at_drop_two(channel)
    monkeypatch.setattr(bot.phrasing, "default_say", blank_the_public_line)

    interaction = await fluff(channel)

    assert "You dislodged something from the bed" in replies(interaction)
    assert not interaction.withdrawn
