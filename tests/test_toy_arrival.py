"""The toy that turns up during the day, and the line that says so.

Drop 2's channel starts empty on purpose, so every toy in it arrived
through the scheduler - which makes an unannounced arrival a toy nobody
goes looking for. This is that notice: when it goes out, when it stays
quiet, and how many of it.

Driven through the real sweep over the shipped content, with only the
clock pinned. Building the report is `test_restocking`'s half; what is
here is the decision the sweep makes about one.
"""

from types import SimpleNamespace

import pytest

from conftest import ALICE, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeMember
from test_restocking import end_of_day

import bot
import content as content_module
import content_loader
import database
import phrasing
import resolve
import restocking

CHANNEL = content_module.CHANNEL_ROOM

# The two keys that have to say the same thing today and are allowed to
# stop saying it.
BED_ARRIVED = "drop.1.announce"
TOY_ARRIVED = "channel.arrival"

# Captured before any test patches it, so sweeping twice in one test
# does not wrap the wrapper.
_RUN_ALL = restocking.run_all


@pytest.fixture
async def drop_two(db, monkeypatch):
    """A server at drop 2, with the channel as the files leave it."""
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(GUILD_A, channels=[halloween], members=[FakeMember(ALICE)])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, 2)
    monkeypatch.setattr(bot, "bot", SimpleNamespace(guilds=[guild]))
    return guild, halloween


async def sweep(monkeypatch, now=None):
    """The real sweep. Only the clock is pinned.

    `restock_sweep` reads the wall clock, and the toy row's window
    closes at 23:00 - a suite run at midnight would sweep a day with
    nothing due in it and every assertion here would pass vacuously.
    """
    when = end_of_day() if now is None else now
    monkeypatch.setattr(restocking, "run_all", lambda ids: _RUN_ALL(ids, now=when))
    await bot.restock_sweep.coro()


# --------------------------------------------------------------------------
# The channel starts empty
# --------------------------------------------------------------------------


async def test_drop_two_opens_with_an_empty_channel(drop_two):
    """**Nothing is placed on arrival.** The toys used to be sitting
    there the moment the drop landed, which made the scheduler's first
    week invisible: the channel was already at its cap of two, so every
    occurrence was spent on a full room until a player took one."""
    assert await database.count_of_type(GUILD_A, CHANNEL, "toy") == 0


async def test_and_then_the_schedule_fills_it(drop_two, monkeypatch):
    await sweep(monkeypatch)

    assert await database.count_of_type(GUILD_A, CHANNEL, "toy")


async def test_six_a_day_because_it_starts_empty(drop_two):
    """The rate and the empty start are one decision, not two. Four a
    day was the number when two were already lying there; the first
    toy of the game now has to arrive through the schedule, so the
    schedule runs oftener to pay for it."""
    toys = next(
        r for r in content_module.load_files().restocks if r.destination == CHANNEL
    )

    assert (toys.times_per_day, toys.max_present) == (6, 2)


async def test_the_cap_is_still_the_cap(drop_two, monkeypatch):
    """Six occurrences a day into a room that holds two. The extra four
    are spent, not banked - the point of the rate is how fresh a taken
    toy is replaced, not how many pile up.

    **Counted, not listed.** Which toy each occurrence draws from the
    class is a coin toss, so a full channel is sometimes two wands
    rather than one of each - and a list of distinct names reads as
    one toy when that happens.
    """
    await sweep(monkeypatch)

    assert await database.count_of_type(GUILD_A, CHANNEL, "toy") == 2


# --------------------------------------------------------------------------
# The notice
# --------------------------------------------------------------------------


async def test_a_toy_arriving_is_posted_in_the_channel(drop_two, monkeypatch):
    _, halloween = drop_two

    await sweep(monkeypatch)

    assert halloween.posted == [await phrasing.default_say(TOY_ARRIVED)]


async def test_it_is_the_words_the_cat_bed_arrived_with(drop_two):
    """What the ask was: the same sentence, so a player reads a toy
    turning up the way they read the bed turning up.

    **Two keys holding one sentence, on purpose.** `drop.1.announce`
    belongs to drop 1; a writer rewording it for the bed's arrival
    should not silently reword every toy arrival for the rest of the
    game. If this test ever fails because somebody edited one of them,
    the fix is to decide whether the other meant to follow - not to
    copy the text across.
    """
    assert await phrasing.default_say(TOY_ARRIVED) == await phrasing.default_say(
        BED_ARRIVED
    )


async def test_two_toys_in_one_sweep_is_one_notice(drop_two, monkeypatch):
    """The empty channel takes two on the first sweep and says so once.
    The line never names what came, so it reads the same either way -
    whereas the same sentence twice in a row reads as a bug rather than
    as two toys. The real case for this is a bot that was down for a
    day and places everything it owed at once."""
    _, halloween = drop_two

    await sweep(monkeypatch)

    assert await database.count_of_type(GUILD_A, CHANNEL, "toy") == 2
    assert len(halloween.posted) == 1


async def test_a_sweep_with_nothing_due_says_nothing(drop_two, monkeypatch):
    _, halloween = drop_two
    await sweep(monkeypatch)
    halloween.posted.clear()

    await sweep(monkeypatch)

    assert halloween.posted == []


async def test_anything_landing_on_that_floor_is_announced(drop_two, monkeypatch):
    """**Not toys only.** Drop 3 scatters bottles and diapers over every
    room, the channel among them. The line never names what came, so it
    is as true of a bottle sliding across the floor as of a toy - and
    the alternative is a thing appearing in front of everybody standing
    there with no notice at all.

    Which rooms the scatter picks is a real coin toss, so this asserts
    the rule rather than a number: one notice exactly when something
    new came to rest on that floor, and none when nothing did. The
    channel starts at the toy cap so the toy row cannot be what moves.
    """
    _, halloween = drop_two
    for toy in ("feather_wand", "crinkle_ball"):
        await database.place_in_room(GUILD_A, CHANNEL, toy, 1)
    await resolve.set_current_drop(GUILD_A, 3)
    before = await _loose_in_the_channel()

    await sweep(monkeypatch)

    assert await _placed_elsewhere(), "drop 3 should fill the house too"
    arrived = await _loose_in_the_channel() != before
    assert len(halloween.posted) == (1 if arrived else 0)


async def _loose_in_the_channel() -> dict[str, int]:
    """What is lying on the channel floor, by thing and by count."""
    from sqlalchemy import select

    async with database._require_session()() as session:
        rows = await session.execute(
            select(
                database.RoomContents.thing_id, database.RoomContents.count
            ).where(
                database.RoomContents.guild_id == GUILD_A,
                database.RoomContents.room_id == CHANNEL,
                database.RoomContents.container_id == database.LOOSE_IN_ROOM,
            )
        )
    return {thing_id: count for thing_id, count in rows}


async def _placed_elsewhere() -> bool:
    """Whether the sweep above actually put anything in another room,
    which is the half of that test it cannot see from the channel.

    Asks after the two things drop 3 scatters by name rather than
    counting a type in every room, because the house already has
    objects standing in it when the drop lands - a count would be true
    before the sweep ran and the assertion would mean nothing.
    """
    from sqlalchemy import select

    async with database._require_session()() as session:
        return bool(
            await session.scalar(
                select(database.RoomContents.thing_id).where(
                    database.RoomContents.guild_id == GUILD_A,
                    database.RoomContents.thing_id.in_(
                        ("used_baby_bottle", "dirty_diaper")
                    ),
                    database.RoomContents.count > 0,
                )
            )
        )


# --------------------------------------------------------------------------
# What is and is not an arrival
# --------------------------------------------------------------------------


def test_the_channels_own_floor_is_what_counts():
    placed = (GUILD_A, CHANNEL, None, "feather_wand", 1)

    assert bot._slid_into_the_channel(GUILD_A, placed)


def test_another_room_is_not_the_channel():
    placed = (GUILD_A, "BR1", None, "used_baby_bottle", 1)

    assert not bot._slid_into_the_channel(GUILD_A, placed)


def test_another_server_is_not_this_one():
    """`run_all` returns one report for every guild swept, so the guild
    id in the row is load-bearing: without it, a toy arriving in one
    server would post the line in all of them."""
    placed = (GUILD_A, CHANNEL, None, "feather_wand", 1)

    assert not bot._slid_into_the_channel(GUILD_A + 1, placed)


def test_something_tucked_inside_a_container_has_not_slid_anywhere():
    """No shipped schedule puts a thing in a container in the channel.
    This is the sentence staying true if one ever does."""
    placed = (GUILD_A, CHANNEL, "amazon_box", "spice_jar", 1)

    assert not bot._slid_into_the_channel(GUILD_A, placed)


# --------------------------------------------------------------------------
# When there is nowhere to post
# --------------------------------------------------------------------------


async def test_a_server_with_no_channel_set_up_loses_only_the_notice(
    drop_two, monkeypatch
):
    """The toy is placed and waiting either way. A half-finished setup
    costs a player the heads-up, not the toy."""
    _, halloween = drop_two
    await database.set_announcement_channel(GUILD_A, None)

    await sweep(monkeypatch)

    assert await database.count_of_type(GUILD_A, CHANNEL, "toy")
    assert halloween.posted == []
