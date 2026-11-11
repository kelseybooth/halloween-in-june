"""Drop 46's other half: toys leave again, one at a time.

Six toys out and thirteen to collect means the draw has to keep moving,
and the thing that moves it is the cat carrying off what nobody has
touched. Two clocks decide that and the second is the whole design:

- **the toy's**, `placed_at`, which `/drop` rewrites - so picking a toy
  up and putting it down again buys it another day;
- **the spot's**, `toy_drains.drained_at`, which is why a pile of five
  comes down one a day instead of vanishing on one tick.

A spot is a room floor or one container: `room_contents` minus the
thing. The bin is not a spot, and a bag is not a place.

The other half of the rotation is at the draw: a toy every active
player is already carrying is not offered again. Only *every* - one
holder is not a reason to withhold it from anybody else - and only
*active*, so somebody who stopped playing a fortnight ago cannot hold
a toy out of the pool for the people still here.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeMember
from test_restocking import end_of_day
from test_world import carry

import bot
import content as content_module
import content_loader
import database
import resolve
import restocking
import world

CHANNEL = content_module.CHANNEL_ROOM
TRASH = content_module.TRASH_CAN
PANTRY = "pantry"

_RUN_ALL = restocking.run_all


@pytest.fixture
async def house(db, monkeypatch):
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A,
        channels=[halloween],
        members=[FakeMember(ALICE), FakeMember(BOB)],
    )
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, 46)
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    monkeypatch.setattr(
        bot,
        "bot",
        SimpleNamespace(
            guilds=[guild], get_guild=lambda gid: guild if gid == GUILD_A else None
        ),
    )
    return db, guild, halloween


async def put(thing_id, room="KI", container=database.LOOSE_IN_ROOM, ago_hours=None):
    """Place a toy, optionally with its clock already run down."""
    await database.place_in_room(GUILD_A, room, thing_id, 1, container_id=container)
    if ago_hours is not None:
        await age(thing_id, room, container, ago_hours)


async def age(thing_id, room, container, hours):
    now = await database.server_now(GUILD_A)
    session_factory = database._require_session()
    async with session_factory() as session:
        await session.execute(
            database.update(database.RoomContents)
            .where(
                database.RoomContents.guild_id == GUILD_A,
                database.RoomContents.room_id == room,
                database.RoomContents.container_id == container,
                database.RoomContents.thing_id == thing_id,
            )
            .values(placed_at=now - timedelta(hours=hours))
        )
        await session.commit()


async def whats_there(room="KI", container=database.LOOSE_IN_ROOM):
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(database.RoomContents.thing_id, database.RoomContents.count).where(
                database.RoomContents.guild_id == GUILD_A,
                database.RoomContents.room_id == room,
                database.RoomContents.container_id == container,
                database.RoomContents.count > 0,
            )
        )
    return {thing_id: count for thing_id, count in rows}


async def drain():
    return await world.carry_off_stale_toys([GUILD_A])


async def placed_at_of(thing_id, room="KI", container=database.LOOSE_IN_ROOM):
    session_factory = database._require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(database.RoomContents.placed_at).where(
                database.RoomContents.guild_id == GUILD_A,
                database.RoomContents.room_id == room,
                database.RoomContents.container_id == container,
                database.RoomContents.thing_id == thing_id,
            )
        )


# --------------------------------------------------------------------------
# The drain
# --------------------------------------------------------------------------


async def test_a_toy_that_has_sat_a_day_is_carried_off(house):
    await put("acorn", ago_hours=25)

    taken = await drain()

    assert [gone.thing_id for gone in taken] == ["acorn"]
    assert await whats_there() == {}


async def test_one_that_has_not_is_left_alone(house):
    await put("acorn", ago_hours=23)

    assert await drain() == []
    assert await whats_there() == {"acorn": 1}


async def test_a_pile_comes_down_one_a_day(house):
    """**The spot's clock, which is the whole design.** Every toy in the
    pile is stale on the first tick, so without a per-spot record the
    cat would take all five at once - a player who put their collection
    down for a day would come back to an empty room."""
    for hours, toy in enumerate(
        ("acorn", "wine_cork", "hair_tie", "bottle_cap", "spider_ring"), start=25
    ):
        await put(toy, ago_hours=hours)

    first = await drain()
    second = await drain()

    assert [gone.thing_id for gone in first] == ["spider_ring"]
    assert second == []
    assert len(await whats_there()) == 4


async def test_and_the_oldest_goes_first(house):
    await put("acorn", ago_hours=30)
    await put("wine_cork", ago_hours=100)

    taken = await drain()

    assert [gone.thing_id for gone in taken] == ["wine_cork"]


async def test_the_spot_reopens_once_the_day_is_up(house):
    await put("acorn", ago_hours=30)
    await put("wine_cork", ago_hours=30)
    await drain()

    session_factory = database._require_session()
    async with session_factory() as session:
        await session.execute(
            database.update(database.ToyDrain).values(
                drained_at=await database.server_now(GUILD_A) - timedelta(hours=25)
            )
        )
        await session.commit()

    assert len(await drain()) == 1
    assert await whats_there() == {}


async def test_two_spots_in_one_room_keep_two_clocks(house):
    """A floor and a container are different spots, so the cat may take
    one from each on the same tick - which is what `room_contents` minus
    the thing already means everywhere else in the game."""
    await put("acorn", ago_hours=30)
    await put("wine_cork", room="KI", container=PANTRY, ago_hours=30)

    taken = await drain()

    assert {gone.container_id for gone in taken} == {database.LOOSE_IN_ROOM, PANTRY}


async def test_a_toy_in_the_bin_is_never_taken(house):
    """The trash mechanic owns it, which is the same reason it does not
    count toward the six."""
    await put("acorn", room="KI", container=TRASH, ago_hours=200)

    assert await drain() == []
    assert await whats_there(container=TRASH) == {"acorn": 1}


async def test_a_toy_in_a_bag_is_never_taken(house, db):
    """The drain reads `room_contents` and nothing else, so this is true
    by construction - and asserted because *Playgroup* depends on it:
    collecting ten toys takes days, and a drain that reached into bags
    would make the achievement unreachable."""
    await carry(db, ALICE, GUILD_A, "acorn")

    assert await drain() == []
    assert await database.carried_of(ALICE, GUILD_A, "acorn") == 1


async def test_putting_it_down_again_restarts_its_clock(house):
    """`/drop` writes `placed_at`, so a toy somebody is playing with is
    never the one she takes. Asserted through the real write rather than
    by setting the column, because the behaviour belongs to that write."""
    await put("acorn", ago_hours=200)

    await database.place_in_room(GUILD_A, "KI", "acorn", 1)

    assert await drain() == []


async def test_a_row_with_no_clock_is_stamped_rather_than_swept(house):
    """**Both readings of a null timestamp are wrong**, and this project
    has shipped one of them: `taken_at` null exempted a carried thing
    from the idle sweep for ever. Treating null as infinitely old is the
    other error - the first tick would empty the house.

    So the clock starts on first sight: nothing is taken this tick, and
    the toy is judged on the next one like everything else.
    """
    await put("acorn")
    await age("acorn", "KI", database.LOOSE_IN_ROOM, 0)
    session_factory = database._require_session()
    async with session_factory() as session:
        await session.execute(
            database.update(database.RoomContents).values(placed_at=None)
        )
        await session.commit()

    assert await drain() == []
    assert await whats_there() == {"acorn": 1}

    # **The assertion that matters.** Nothing being taken is true either
    # way - a null row is invisible to the stale query - so the test has
    # to look at the stamp itself, or it passes with the repair deleted.
    assert await placed_at_of("acorn") is not None

    await age("acorn", "KI", database.LOOSE_IN_ROOM, 30)
    assert len(await drain()) == 1


async def test_the_room_hears_about_it(house):
    """The line is the only sign a player gets, so it goes out in the
    room the toy left - and it is the work order's words exactly."""
    _, _, halloween = house
    await put("acorn", room=CHANNEL, ago_hours=30)

    await bot.toy_drain.coro()

    assert halloween.posted == [
        "The cat trots off with the acorn and doesn't come back with it."
    ]


async def test_the_drain_frees_a_slot(house, monkeypatch):
    """Change 6, and the reason the drain exists at all: the cap counts
    what is out, so taking one lets the next draw happen."""
    for toy in ("acorn", "wine_cork", "hair_tie", "bottle_cap", "spider_ring", "jingle_ball"):
        await put(toy, room="KI", container=PANTRY, ago_hours=30)

    assert (
        await database.count_of_type_in_house(GUILD_A, "toy", except_container=TRASH)
        == 6
    )
    await drain()

    assert (
        await database.count_of_type_in_house(GUILD_A, "toy", except_container=TRASH)
        == 5
    )


# --------------------------------------------------------------------------
# What the draw will not offer
# --------------------------------------------------------------------------


async def test_a_toy_everybody_active_holds_is_not_drawn(house, db):
    """Thirteen toys and six slots means a group collecting a set waits
    on the draw, and a draw that keeps offering the one they all have is
    the slowest possible version of that."""
    today = await database.server_today(GUILD_A)
    for who in (ALICE, BOB):
        await carry(db, who, GUILD_A, "acorn")
        await database.touched_the_cat(who, GUILD_A, today)

    held = await database.toys_every_active_player_has(GUILD_A, "toy", today)

    assert held == {"acorn"}


async def test_one_player_holding_it_is_not_everybody(house, db):
    """A single holder is no reason to withhold a toy from anybody else."""
    today = await database.server_today(GUILD_A)
    for who in (ALICE, BOB):
        await database.touched_the_cat(who, GUILD_A, today)
    await carry(db, ALICE, GUILD_A, "acorn")

    assert await database.toys_every_active_player_has(GUILD_A, "toy", today) == set()


async def test_somebody_who_stopped_playing_does_not_count(house, db):
    """Otherwise a player who left a fortnight ago holds a toy out of the
    pool for everybody still here."""
    today = await database.server_today(GUILD_A)
    await carry(db, ALICE, GUILD_A, "acorn")
    await database.touched_the_cat(ALICE, GUILD_A, today)
    await carry(db, BOB, GUILD_A, "wine_cork")
    await database.touched_the_cat(BOB, GUILD_A, today - timedelta(days=30))

    held = await database.toys_every_active_player_has(
        GUILD_A, "toy", today - timedelta(days=7)
    )

    assert held == {"acorn"}


async def test_the_draw_itself_skips_what_everybody_has(house, db, monkeypatch):
    """**Through the sweep, not through the query.** The rule has two
    halves - knowing which toys everybody holds, and not offering them -
    and the tests above only hold the first. Deleting the filter in
    `restocking._what_to_place` left every one of them green.

    One active player carrying eleven of the twelve carriable toys, so
    the only thing the draw may place is the twelfth.
    """
    _, guild, halloween = house
    today = await database.server_today(GUILD_A)
    await database.touched_the_cat(ALICE, GUILD_A, today)

    arrived = await resolve.arrived_drop_ids(GUILD_A)
    pool = await database.stock_of_type("toy", arrived)
    assert len(pool) == 12
    for thing_id in pool[:-1]:
        await carry(db, ALICE, GUILD_A, thing_id)

    monkeypatch.setattr(
        restocking, "run_all", lambda ids: _RUN_ALL(ids, now=end_of_day())
    )
    await bot.restock_sweep.coro()

    placed = {
        thing_id
        for _, _, thing_id, _ in await database.stale_toys_by_spot(
            GUILD_A, "toy", await database.server_now(GUILD_A), except_container=TRASH
        )
    }
    assert placed == {pool[-1]}


async def test_and_places_nothing_when_they_have_them_all(house, db, monkeypatch):
    """No fallback to drawing anyway: a rule the draw ignores the moment
    it bites is a suggestion."""
    today = await database.server_today(GUILD_A)
    await database.touched_the_cat(ALICE, GUILD_A, today)
    arrived = await resolve.arrived_drop_ids(GUILD_A)
    for thing_id in await database.stock_of_type("toy", arrived):
        await carry(db, ALICE, GUILD_A, thing_id)

    monkeypatch.setattr(
        restocking, "run_all", lambda ids: _RUN_ALL(ids, now=end_of_day())
    )
    await bot.restock_sweep.coro()

    assert (
        await database.count_of_type_in_house(GUILD_A, "toy", except_container=TRASH)
        == 0
    )


async def test_nobody_active_means_nothing_is_withheld(house, db):
    """*Every one of nobody carries the acorn* is vacuously true and
    would skip the whole pool, leaving a quiet server with no toys at
    all - which is the opposite of what the rule is for."""
    await carry(db, ALICE, GUILD_A, "acorn")

    today = await database.server_today(GUILD_A)
    assert await database.toys_every_active_player_has(GUILD_A, "toy", today) == set()
