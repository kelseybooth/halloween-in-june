"""Moving things between rooms, containers and bags.

The layer `/take`, `/drop` and `/use` sit on. Counts rather than rows, and every
write is an upsert or a conditional update rather than a read followed by a
write - so the interesting tests here are the ones where two things happen at
once and only one of them may win.
"""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import content_loader
import database
from test_loader import a_thing, contents
from test_world import a_house, carry


@pytest.fixture
async def house(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(BOB, GUILD_A)
    return db


async def bag(db, user_id=ALICE, guild_id=GUILD_A):
    return dict(
        [
            (name, count)
            for name, count in await database.get_carried(user_id, guild_id)
        ]
    )


# --------------------------------------------------------------------------
# Taking
# --------------------------------------------------------------------------


async def test_taking_moves_one_copy_from_the_room_to_the_bag(house):
    await content_loader.load_content(a_house(a_thing("spoon", name="spoon")))

    assert await database.take_from_room(ALICE, GUILD_A, "EN", "", "spoon") is True
    assert await bag(house) == {"spoon": 1}
    assert await contents(house, GUILD_A) == [("EN", "", "spoon", 0)]


async def test_taking_leaves_the_row_at_zero_rather_than_deleting_it(house):
    """A row at zero is how the loader knows this server has seen the thing, so
    a reload does not put it back on the counter."""
    await content_loader.load_content(a_house(a_thing("spoon")))
    await database.take_from_room(ALICE, GUILD_A, "EN", "", "spoon")

    assert await contents(house, GUILD_A) == [("EN", "", "spoon", 0)]


async def test_taking_the_last_one_twice_fails_the_second_time(house):
    await content_loader.load_content(a_house(a_thing("spoon")))

    assert await database.take_from_room(ALICE, GUILD_A, "EN", "", "spoon") is True
    assert await database.take_from_room(BOB, GUILD_A, "EN", "", "spoon") is False
    assert await bag(house, BOB) == {}


async def test_two_players_racing_for_the_last_copy(house):
    """The decrement is conditional on the count, so exactly one wins - no read
    of a stale value can let both through."""
    await content_loader.load_content(a_house(a_thing("spoon")))

    results = await asyncio.gather(
        database.take_from_room(ALICE, GUILD_A, "EN", "", "spoon"),
        database.take_from_room(BOB, GUILD_A, "EN", "", "spoon"),
        return_exceptions=True,
    )
    wins = [r for r in results if r is True]

    assert len(wins) == 1
    assert await contents(house, GUILD_A) == [("EN", "", "spoon", 0)]


async def test_several_copies_can_each_be_taken(house):
    await content_loader.load_content(a_house(a_thing("bottle", quantity=3)))

    for _ in range(3):
        assert await database.take_from_room(ALICE, GUILD_A, "EN", "", "bottle") is True
    assert await database.take_from_room(ALICE, GUILD_A, "EN", "", "bottle") is False
    assert await bag(house) == {"bottle": 3}


async def test_taking_from_a_container_empties_that_container(house):
    await content_loader.load_content(
        a_house(
            a_thing("box", name="box", type="fixture", takeable=False),
            a_thing("jar", name="jar", contained_in="box"),
        )
    )

    assert await database.take_from_room(ALICE, GUILD_A, "EN", "box", "jar") is True
    assert await contents(house, GUILD_A) == [("EN", "box", "jar", 0)]


async def test_taking_from_a_container_by_the_wrong_key_fails(house):
    """A jar inside the box is not a jar loose on the floor."""
    await content_loader.load_content(
        a_house(
            a_thing("box", name="box", type="fixture", takeable=False),
            a_thing("jar", name="jar", contained_in="box"),
        )
    )
    assert await database.take_from_room(ALICE, GUILD_A, "EN", "", "jar") is False


async def test_a_source_is_not_consumed(house):
    await content_loader.load_content(
        a_house(
            a_thing("can", name="can", room_id=None, quantity=0),
            a_thing("stash", type="source", yields="can", takeable=False),
        )
    )

    for _ in range(5):
        await database.take_from_source(ALICE, GUILD_A, "can")

    assert await bag(house) == {"can": 5}
    assert await contents(house, GUILD_A) == []


async def test_taking_works_for_a_player_who_never_petted(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    stranger = 555555555555555555

    assert await database.take_from_room(stranger, GUILD_A, "EN", "", "spoon") is True


# --------------------------------------------------------------------------
# Dropping
# --------------------------------------------------------------------------


async def test_dropping_moves_one_copy_back_to_the_room(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    await database.take_from_room(ALICE, GUILD_A, "EN", "", "spoon")

    assert await database.drop_into_room(ALICE, GUILD_A, "EN", "spoon") is True
    assert await bag(house) == {}
    assert await contents(house, GUILD_A) == [("EN", "", "spoon", 1)]


async def test_dropping_something_you_do_not_have_fails(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    assert await database.drop_into_room(ALICE, GUILD_A, "EN", "spoon") is False


async def test_a_dropped_thing_lands_loose_not_back_in_its_container(house):
    """Dropping the spice jar in the Entryway does not put it back in the box."""
    await content_loader.load_content(
        a_house(
            a_thing("box", name="box", type="fixture", takeable=False),
            a_thing("jar", name="jar", contained_in="box"),
        )
    )
    await database.take_from_room(ALICE, GUILD_A, "EN", "box", "jar")
    await database.drop_into_room(ALICE, GUILD_A, "EN", "jar")

    placed = {(row[1], row[3]) for row in await contents(house, GUILD_A)}
    assert placed == {("box", 0), ("", 1)}


async def test_a_thing_can_be_dropped_in_a_different_room(house):
    """A can of chicken can end up in the Nursery. That is how the house
    accumulates evidence of other players."""
    await content_loader.load_content(a_house(a_thing("spoon")))
    await database.take_from_room(ALICE, GUILD_A, "EN", "", "spoon")
    await database.drop_into_room(ALICE, GUILD_A, "KI", "spoon")

    assert ("KI", "", "spoon", 1) in await contents(house, GUILD_A)


async def test_dropping_adds_to_what_is_already_there(house):
    await content_loader.load_content(a_house(a_thing("bottle", quantity=2)))
    await database.take_from_room(ALICE, GUILD_A, "EN", "", "bottle")
    await database.drop_into_room(ALICE, GUILD_A, "EN", "bottle")

    assert await contents(house, GUILD_A) == [("EN", "", "bottle", 2)]


async def test_dropping_twice_when_carrying_one_fails_the_second_time(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    await database.take_from_room(ALICE, GUILD_A, "EN", "", "spoon")

    assert await database.drop_into_room(ALICE, GUILD_A, "EN", "spoon") is True
    assert await database.drop_into_room(ALICE, GUILD_A, "EN", "spoon") is False


# --------------------------------------------------------------------------
# Transforming
# --------------------------------------------------------------------------


async def test_a_transform_swaps_one_for_one(house):
    await content_loader.load_content(
        a_house(
            a_thing("used", name="used bottle", quantity=2, transforms_to="clean"),
            a_thing("clean", name="clean bottle", room_id=None, quantity=0),
        )
    )
    await database.take_from_room(ALICE, GUILD_A, "EN", "", "used")
    await database.take_from_room(ALICE, GUILD_A, "EN", "", "used")

    assert await database.transform_carried(ALICE, GUILD_A, "used", "clean") is True
    assert await bag(house) == {"clean bottle": 1, "used bottle": 1}


async def test_transforming_what_you_do_not_carry_fails(house):
    await content_loader.load_content(
        a_house(
            a_thing("used", name="used bottle"),
            a_thing("clean", name="clean bottle", room_id=None, quantity=0),
        )
    )
    assert await database.transform_carried(ALICE, GUILD_A, "used", "clean") is False


async def test_a_transform_is_one_way(house):
    await content_loader.load_content(
        a_house(
            a_thing("used", name="used bottle"),
            a_thing("clean", name="clean bottle", room_id=None, quantity=0),
        )
    )
    await database.take_from_room(ALICE, GUILD_A, "EN", "", "used")
    await database.transform_carried(ALICE, GUILD_A, "used", "clean")

    assert await database.transform_carried(ALICE, GUILD_A, "used", "clean") is False


# --------------------------------------------------------------------------
# Recording uses
# --------------------------------------------------------------------------


async def test_a_first_use_reports_no_previous_time(house):
    record = await database.record_use(ALICE, GUILD_A, "lumber")

    assert record.last_used_at is None
    assert record.use_count == 1


async def test_a_second_use_reports_the_first_ones_time(house):
    """The cooldown needs the value from before this use overwrote it."""
    first = await database.record_use(ALICE, GUILD_A, "lumber")
    assert first.last_used_at is None

    second = await database.record_use(ALICE, GUILD_A, "lumber")
    assert second.last_used_at is not None
    assert second.use_count == 2


async def test_use_count_increments_exactly_once_per_use(house):
    for expected in range(1, 11):
        assert (await database.record_use(ALICE, GUILD_A, "burrito")).use_count == expected


async def test_uses_are_counted_per_thing(house):
    await database.record_use(ALICE, GUILD_A, "lumber")
    assert (await database.record_use(ALICE, GUILD_A, "burrito")).use_count == 1


async def test_uses_are_counted_per_player(house):
    await database.record_use(ALICE, GUILD_A, "lumber")
    assert (await database.record_use(BOB, GUILD_A, "lumber")).use_count == 1


async def test_uses_are_counted_per_server(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(ALICE, GUILD_B)
    await database.record_use(ALICE, GUILD_A, "lumber")

    assert (await database.record_use(ALICE, GUILD_B, "lumber")).use_count == 1


async def test_last_used_can_be_read_without_recording_a_use(house):
    assert await database.last_used(ALICE, GUILD_A, "lumber") is None
    await database.record_use(ALICE, GUILD_A, "lumber")

    stamped = await database.last_used(ALICE, GUILD_A, "lumber")
    assert stamped is not None
    assert (await database.last_used(ALICE, GUILD_A, "lumber")) == stamped


# --------------------------------------------------------------------------
# Distinct players, which is how the staircase counts
# --------------------------------------------------------------------------


async def test_the_staircase_counts_players_not_uses(house):
    """Somebody using lumber twice still contributes one plank."""
    await database.record_use(ALICE, GUILD_A, "lumber")
    await database.record_use(ALICE, GUILD_A, "lumber")
    await database.record_use(ALICE, GUILD_A, "lumber")

    assert await database.distinct_users_of(GUILD_A, "lumber") == 1


async def test_each_new_player_adds_one(house):
    await database.record_use(ALICE, GUILD_A, "lumber")
    await database.record_use(BOB, GUILD_A, "lumber")

    assert await database.distinct_users_of(GUILD_A, "lumber") == 2


async def test_the_count_is_per_server(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(ALICE, GUILD_B)
    await database.record_use(ALICE, GUILD_A, "lumber")

    assert await database.distinct_users_of(GUILD_B, "lumber") == 0


async def test_nobody_has_used_it_yet(house):
    assert await database.distinct_users_of(GUILD_A, "lumber") == 0


# --------------------------------------------------------------------------
# Servers stay separate through all of it
# --------------------------------------------------------------------------


async def test_taking_in_one_server_does_not_empty_another(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(ALICE, GUILD_B)
    await content_loader.load_content(a_house(a_thing("spoon")))

    await database.take_from_room(ALICE, GUILD_A, "EN", "", "spoon")

    assert await contents(db, GUILD_A) == [("EN", "", "spoon", 0)]
    assert await contents(db, GUILD_B) == [("EN", "", "spoon", 1)]
