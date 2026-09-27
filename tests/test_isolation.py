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


async def test_player_locations_are_listed_per_server(db):
    await db.start_game(ALICE, GUILD_A, "Entryway", [])
    await db.start_game(BOB, GUILD_A, "Entryway", [])
    await db.start_game(ALICE, GUILD_B, "Entryway", [])

    assert len(await db.get_all_player_locations(GUILD_A)) == 2
    assert len(await db.get_all_player_locations(GUILD_B)) == 1




# --------------------------------------------------------------------------
# Where the line moved in phase 2b
#
# Rooms and things used to be per guild, and the tests here asserted that two
# servers could describe the same room differently. That is deliberately no
# longer true: the house is one house, loaded from the files, shared by every
# server. What stayed per guild is everything a player can change.
#
# So the boundary is now content versus world state rather than server versus
# server, and these check it from the behavioural side - test_schema.py checks
# the same split at the column level.
# --------------------------------------------------------------------------


async def test_the_house_itself_is_shared(db):
    """One house, one set of descriptions, however many servers are playing."""
    import content_loader
    import resolve
    from test_world import a_house

    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(BOB, GUILD_B)
    await content_loader.load_content(a_house())

    assert await resolve.room_look(GUILD_A, "EN") == await resolve.room_look(GUILD_B, "EN")


async def test_stock_is_not_shared(db):
    """Two servers start with the same things and diverge the moment anyone
    picks something up."""
    import content_loader
    from test_loader import a_thing, contents
    from test_world import a_house

    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(BOB, GUILD_B)
    await content_loader.load_content(a_house(a_thing("chips")))

    assert await contents(db, GUILD_A) == await contents(db, GUILD_B)

    async with db._require_session()() as session:
        await session.execute(
            db.RoomContents.__table__.update()
            .where(db.RoomContents.guild_id == GUILD_A)
            .values(count=0)
        )
        await session.commit()

    assert await contents(db, GUILD_A) != await contents(db, GUILD_B)


async def test_what_a_player_carries_is_per_server(db):
    import content_loader
    from test_loader import a_thing
    from test_world import a_house, carry

    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(ALICE, GUILD_B)
    await content_loader.load_content(a_house(a_thing("spoon")))
    await carry(db, ALICE, GUILD_A, "spoon")

    assert len(await db.get_carried(ALICE, GUILD_A)) == 1
    assert await db.get_carried(ALICE, GUILD_B) == []


async def test_a_drop_fired_on_one_server_does_not_fire_on_another(db):
    """The per-guild half of the drop calendar, which is new in 2b."""
    import content_loader
    import resolve
    from test_drops import a_calendar, a_drop

    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(BOB, GUILD_B)
    await content_loader.load_content(
        a_calendar(a_drop(1, value="launch"), a_drop(2, trigger="manual"))
    )
    await resolve.record_arrival(GUILD_A, 2)

    assert await resolve.arrived_drop_ids(GUILD_A) == {1, 2}
    assert await resolve.arrived_drop_ids(GUILD_B) == {1}
