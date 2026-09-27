"""The phase 2b schema: content tables, world-state tables, and the migration.

The split these tests defend is the whole design. Content is global and never
mutated at runtime, which is what makes a reload safe. World state is per guild
and is the only thing a player can change. A content table that grew a guild_id,
or a world-state table that lost one, would break one half of that guarantee
quietly - the loader would start overwriting people's games, or two servers would
start sharing one.
"""

from datetime import datetime

import pytest
from sqlalchemy import inspect, select, text

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import database


CONTENT_TABLES = {
    "room_types",
    "thing_types",
    "room_text",
    "thing_text",
    "defaults",
    "drops",
    "restocks",
}

WORLD_TABLES = {
    "player_inventory",
    "room_contents",
    "player_states",
    "server_states",
    "server_config",
    "thing_uses",
    "server_drops",
    "server_restocks",
}


async def table_names(db):
    async with db._engine.connect() as conn:
        return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


async def columns_of(db, table):
    async with db._engine.connect() as conn:
        return {
            c["name"]
            for c in await conn.run_sync(lambda sync: inspect(sync).get_columns(table))
        }


# --------------------------------------------------------------------------
# The tables exist
# --------------------------------------------------------------------------


async def test_every_content_table_is_created(db):
    assert CONTENT_TABLES <= await table_names(db)


async def test_every_world_state_table_is_created(db):
    assert WORLD_TABLES <= await table_names(db)


async def test_the_legacy_tables_are_still_there(db):
    """Left in place and unread, as the cohort columns were - dropping a table
    is not something the additive startup migration can do."""
    assert {"rooms", "things", "inventory"} <= await table_names(db)


# --------------------------------------------------------------------------
# The split
# --------------------------------------------------------------------------


@pytest.mark.parametrize("table", sorted(CONTENT_TABLES))
async def test_content_tables_are_not_keyed_by_guild(db, table):
    """The house is the same house in every server. A guild_id here would mean
    the loader had to write once per server, and a reload could clobber a game."""
    assert "guild_id" not in await columns_of(db, table)


@pytest.mark.parametrize("table", sorted(WORLD_TABLES))
async def test_every_world_state_table_is_scoped_to_a_guild(db, table):
    assert "guild_id" in await columns_of(db, table)


# --------------------------------------------------------------------------
# Columns the work order named
# --------------------------------------------------------------------------


async def test_room_contents_records_which_container(db):
    assert "container_id" in await columns_of(db, "room_contents")


async def test_thing_uses_records_a_count_as_well_as_a_time(db):
    """Three jobs: the cooldown, distinct-player plank counting, and N-times
    achievements. The count is what makes the third one answerable."""
    assert {"last_used_at", "use_count"} <= await columns_of(db, "thing_uses")


async def test_pet_events_records_the_relationship_at_the_time(db):
    assert "relationship_at_pet" in await columns_of(db, "pet_events")


async def test_text_tables_are_keyed_by_state_and_drop(db):
    for table in ("room_text", "thing_text"):
        assert {"state", "since_drop"} <= await columns_of(db, table)


# --------------------------------------------------------------------------
# container_id in the key
# --------------------------------------------------------------------------


async def test_the_same_thing_can_be_loose_and_in_a_container_at_once(db):
    """A spice jar in the Amazon box and another dropped on the floor beside it
    are two rows, and only the loose one belongs in `Also here:`."""
    async with db._require_session()() as session:
        session.add_all(
            [
                db.RoomContents(
                    guild_id=GUILD_A,
                    room_id="EN",
                    container_id=db.LOOSE_IN_ROOM,
                    thing_id="spice_jar",
                    count=1,
                ),
                db.RoomContents(
                    guild_id=GUILD_A,
                    room_id="EN",
                    container_id="amazon_box",
                    thing_id="spice_jar",
                    count=4,
                ),
            ]
        )
        await session.commit()

        rows = (
            await session.execute(
                select(db.RoomContents.container_id, db.RoomContents.count)
                .where(db.RoomContents.guild_id == GUILD_A)
                .order_by(db.RoomContents.container_id)
            )
        ).all()

    assert [(c, n) for c, n in rows] == [(db.LOOSE_IN_ROOM, 1), ("amazon_box", 4)]


async def test_loose_is_an_empty_string_not_null(db):
    """NULLs in a composite key compare as distinct from each other on some
    backends, which would let duplicate loose rows accumulate silently."""
    assert db.LOOSE_IN_ROOM == ""


# --------------------------------------------------------------------------
# Per-guild isolation, on the new tables too
# --------------------------------------------------------------------------


async def test_world_state_does_not_leak_between_servers(db):
    async with db._require_session()() as session:
        session.add_all(
            [
                db.PlayerInventory(
                    guild_id=GUILD_A, user_id=ALICE, thing_id="candy", count=3
                ),
                db.PlayerInventory(
                    guild_id=GUILD_B, user_id=ALICE, thing_id="candy", count=1
                ),
                db.PlayerState(guild_id=GUILD_A, user_id=ALICE, state="has_key"),
                db.ServerState(guild_id=GUILD_A, state="stairs_repaired"),
            ]
        )
        await session.commit()

        carried = await session.scalar(
            select(db.PlayerInventory.count).where(
                db.PlayerInventory.guild_id == GUILD_B,
                db.PlayerInventory.user_id == ALICE,
            )
        )
        states_b = (
            await session.execute(
                select(db.PlayerState.state).where(db.PlayerState.guild_id == GUILD_B)
            )
        ).all()
        server_b = (
            await session.execute(
                select(db.ServerState.state).where(db.ServerState.guild_id == GUILD_B)
            )
        ).all()

    assert carried == 1
    assert states_b == []
    assert server_b == []


async def test_a_players_discovery_is_not_another_players(db):
    """drawer_unjammed is per player on purpose: the discovery is the content."""
    async with db._require_session()() as session:
        session.add(db.PlayerState(guild_id=GUILD_A, user_id=ALICE, state="drawer_unjammed"))
        await session.commit()

        theirs = (
            await session.execute(
                select(db.PlayerState.state).where(
                    db.PlayerState.guild_id == GUILD_A, db.PlayerState.user_id == BOB
                )
            )
        ).all()

    assert theirs == []


# --------------------------------------------------------------------------
# Migrating a database that predates 2b
# --------------------------------------------------------------------------


async def test_an_older_database_gains_the_new_tables_and_columns(tmp_path, monkeypatch):
    """create_all adds missing tables; the ALTER list adds missing columns. A
    real deployment upgrades in place, so both halves have to work together."""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'old.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)

    database._engine = None
    database._session_factory = None
    await database.init_db()

    # Take the database back to its pre-2b shape: drop what 2b added, and drop
    # the columns the ALTER list is responsible for re-adding.
    async with database._engine.begin() as conn:
        for table in sorted(CONTENT_TABLES | WORLD_TABLES):
            await conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        await conn.execute(text("ALTER TABLE pet_events DROP COLUMN relationship_at_pet"))
    await database.close_db()

    database._engine = None
    database._session_factory = None
    await database.init_db()
    try:
        names = await table_names(database)
        assert CONTENT_TABLES <= names
        assert WORLD_TABLES <= names
        assert "relationship_at_pet" in await columns_of(database, "pet_events")

        # And it still works afterwards.
        result = await database.increment_pet_count(ALICE, GUILD_A)
        assert result.total == 1
    finally:
        await database.close_db()


async def test_running_the_migration_twice_is_a_no_op(db):
    """Startup runs it every boot, so it has to be safe to repeat."""
    before = await columns_of(db, "pet_events")
    async with db._engine.begin() as conn:
        await db._add_missing_columns(conn)
        await db._add_missing_columns(conn)
    assert await columns_of(db, "pet_events") == before


async def test_the_guard_against_pre_multi_server_databases_still_stands(db):
    """2a's refusal to guess is not weakened by any of this."""
    assert issubclass(db.SchemaOutdatedError, db.StartupError)
