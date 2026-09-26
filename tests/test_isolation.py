"""Cross-server isolation.

A player who meets the bot in two servers has two independent cats and two
independent positions in the house. Every table is keyed by (user_id, guild_id);
these tests assert the behaviour that key exists to produce, table by table, so a
wide refactor that drops a `guild_id ==` filter somewhere fails here loudly.
"""

from datetime import date, timedelta

from sqlalchemy import update

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import house_utils


async def test_pet_counts_are_per_server(db):
    await db.increment_pet_count(ALICE, GUILD_A)
    await db.increment_pet_count(ALICE, GUILD_A)
    await db.increment_pet_count(ALICE, GUILD_B)

    assert await db.get_pet_count(ALICE, GUILD_A) == 2
    assert await db.get_pet_count(ALICE, GUILD_B) == 1


async def test_the_recent_pet_window_is_per_server(db):
    """Pestering the cat in one server must not sour it in another."""
    for _ in range(5):
        await db.increment_pet_count(ALICE, GUILD_A)

    assert (await db.increment_pet_count(ALICE, GUILD_B)).recent == 0


async def test_relationships_are_per_server(db):
    await db.increment_pet_count(ALICE, GUILD_A)
    await db.increment_pet_count(ALICE, GUILD_B)
    await db.adjust_relationship(ALICE, GUILD_A, -40)

    assert await db.get_relationship(ALICE, GUILD_A) == db.RELATIONSHIP_START - 40
    assert await db.get_relationship(ALICE, GUILD_B) == db.RELATIONSHIP_START


async def test_nightly_decay_treats_each_server_separately(db):
    """Petting in one server does not excuse an idle day in another."""
    day = date(2026, 6, 10)
    for guild in (GUILD_A, GUILD_B):
        await db.ensure_user_exists(ALICE, guild)
        async with db._require_session()() as session:
            await session.execute(
                update(db.User)
                .where(db.User.id == ALICE, db.User.guild_id == guild)
                .values(relationship=50, last_decay_date=None)
            )
            await session.commit()

    start, _ = db.pacific_day_bounds_utc(day)
    async with db._require_session()() as session:
        session.add(
            db.PetEvent(user_id=ALICE, guild_id=GUILD_A, created_at=start + timedelta(hours=1))
        )
        await session.commit()

    await db.apply_daily_decay(day)

    assert await db.get_relationship(ALICE, GUILD_A) == 50  # petted here
    assert await db.get_relationship(ALICE, GUILD_B) == 40  # idle here


async def test_game_state_is_per_server(db):
    await db.start_game(ALICE, GUILD_A, "Entryway", ["Entryway"])
    assert await db.get_game_state(ALICE, GUILD_B) is None

    await db.start_game(ALICE, GUILD_B, "Entryway", ["Entryway"])
    await db.update_current_room(ALICE, GUILD_A, "Kitchen")

    assert (await db.get_game_state(ALICE, GUILD_A)).current_room == "Kitchen"
    assert (await db.get_game_state(ALICE, GUILD_B)).current_room == "Entryway"


async def test_deleting_game_state_in_one_server_leaves_the_other(db):
    await db.start_game(ALICE, GUILD_A, "Entryway", [])
    await db.start_game(ALICE, GUILD_B, "Entryway", [])

    await db.delete_game_state(ALICE, GUILD_A)

    assert await db.get_game_state(ALICE, GUILD_A) is None
    assert await db.get_game_state(ALICE, GUILD_B) is not None


async def test_room_descriptions_are_per_server(db):
    await db.set_room_description(GUILD_A, "Kitchen", "A in the kitchen")
    await db.set_room_description(GUILD_B, "Kitchen", "B in the kitchen")

    assert await db.get_room_description(GUILD_A, "Kitchen") == "A in the kitchen"
    assert await db.get_room_description(GUILD_B, "Kitchen") == "B in the kitchen"


async def test_a_room_described_in_one_server_is_blank_in_another(db):
    await db.set_room_description(GUILD_A, "Kitchen", "only here")
    assert await db.get_room_description(GUILD_B, "Kitchen") is None


async def test_things_are_per_server(db):
    await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can")
    things_a = await db.get_things_in_room(GUILD_A, "Kitchen")
    things_b = await db.get_things_in_room(GUILD_B, "Kitchen")

    assert [name for _, name in things_a] == ["cat food"]
    assert things_b == []


async def test_looking_at_a_thing_does_not_reach_across_servers(db):
    await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can")
    assert await db.look_at_thing(ALICE, GUILD_A, "Kitchen", "cat food") is not None
    assert await db.look_at_thing(ALICE, GUILD_B, "Kitchen", "cat food") is None


async def test_inventories_are_per_server(db):
    thing_a = await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can")
    thing_b = await db.add_thing(GUILD_B, "Kitchen", "cat food", "a can")

    await db.add_to_inventory(ALICE, GUILD_A, thing_a)

    assert await db.get_inventory(ALICE, GUILD_A) == [("cat food", 1)]
    assert await db.get_inventory(ALICE, GUILD_B) == []
    assert await db.inventory_count(ALICE, GUILD_B) == 0

    await db.add_to_inventory(ALICE, GUILD_B, thing_b)
    assert await db.inventory_count(ALICE, GUILD_A) == 1
    assert await db.inventory_count(ALICE, GUILD_B) == 1


async def test_carrying_a_thing_in_one_server_does_not_hide_it_in_another(db):
    """Visibility is decided from that server's own inventory rows."""
    thing_a = await db.add_thing(GUILD_A, "Kitchen", "note", "a note", removed_on_take=True)
    await db.add_thing(GUILD_B, "Kitchen", "note", "a note", removed_on_take=True)

    await db.add_to_inventory(ALICE, GUILD_A, thing_a)

    assert await db.get_things_in_room(GUILD_A, "Kitchen") == []
    assert len(await db.get_things_in_room(GUILD_B, "Kitchen")) == 1


async def test_player_locations_are_listed_per_server(db):
    await db.start_game(ALICE, GUILD_A, "Entryway", [])
    await db.start_game(BOB, GUILD_A, "Entryway", [])
    await db.start_game(ALICE, GUILD_B, "Entryway", [])

    assert len(await db.get_all_player_locations(GUILD_A)) == 2
    assert len(await db.get_all_player_locations(GUILD_B)) == 1


async def test_seeding_rooms_in_one_server_does_not_seed_another(db):
    created = await db.seed_rooms(GUILD_A, house_utils.ROOMS)
    assert created == len(house_utils.ROOMS)

    # Rerunning is a no-op for A, but B still needs all of them.
    assert await db.seed_rooms(GUILD_A, house_utils.ROOMS) == 0
    assert await db.seed_rooms(GUILD_B, house_utils.ROOMS) == len(house_utils.ROOMS)
