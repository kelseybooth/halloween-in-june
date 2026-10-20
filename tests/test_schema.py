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
from sqlalchemy import inspect, select, text, update

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


async def test_a_narrow_room_text_is_rebuilt_rather_than_altered(tmp_path, monkeypatch):
    """The drop 2 failure, caught before it shipped a second time.

    `fragment` joined `room_text`'s primary key, and neither backend can
    widen a primary key with `ALTER TABLE`. Added to the usual list the
    column would have appeared, the schema would have looked current,
    and the first content load would have died on six channel rows all
    reading (CH, default, 1) - after which the startup loader keeps
    serving the last good content and the release looks like it never
    shipped. That is exactly how drop 2 was lost.

    So the fix is a rebuild, and this drives the real upgrade: an
    existing database with the three-column key, booted, then loaded.
    """
    url = f"sqlite+aiosqlite:///{(tmp_path / 'narrow.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)

    database._engine = None
    database._session_factory = None
    await database.init_db()

    # Put room_text back the way it shipped: three key columns, no
    # fragment, and a row in it to prove the rebuild is not what makes
    # the load work.
    async with database._engine.begin() as conn:
        await conn.execute(text("DROP TABLE room_text"))
        await conn.execute(
            text(
                "CREATE TABLE room_text ("
                "room_id VARCHAR(8) NOT NULL, state VARCHAR(64) NOT NULL, "
                "since_drop INTEGER NOT NULL, look TEXT, "
                "PRIMARY KEY (room_id, state, since_drop))"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO room_text (room_id, state, since_drop, look) "
                "VALUES ('EN', 'default', 0, 'stale')"
            )
        )
    await database.close_db()

    database._engine = None
    database._session_factory = None
    await database.init_db()
    try:
        assert "fragment" in await columns_of(database, "room_text")

        # The load is the real assertion: six rows for one room, one
        # state and one drop is precisely what the old key forbade.
        import content as content_module
        import content_loader

        report = await content_loader.load_content(content_module.load_files())

        assert report.content_rows["room_text"] > 0

        async with database._require_session()() as session:
            fragments = await session.scalar(
                text(
                    "SELECT count(*) FROM room_text WHERE room_id = :room "
                    "AND state = 'default' AND since_drop = 1"
                ),
                {"room": content_module.CHANNEL_ROOM},
            )
        assert fragments == 8, "the eight channel fragments are the whole point"
    finally:
        await database.close_db()


async def test_fragment_is_not_in_the_alter_list(tmp_path):
    """A negative requirement, and the one worth checking at review.

    Putting it back would be silent: the column would exist, the
    rebuild would never fire because the rebuild only looks at the key,
    and the failure would wait for whichever room gets a second
    fragment next.
    """
    assert not any(
        table == "room_text" and column == "fragment"
        for table, column, _ in database._LATER_COLUMNS
    )


async def test_running_the_migration_twice_is_a_no_op(db):
    """Startup runs it every boot, so it has to be safe to repeat."""
    before = await columns_of(db, "pet_events")
    async with db._engine.begin() as conn:
        await db._add_missing_columns(conn)
        await db._add_missing_columns(conn)
    assert await columns_of(db, "pet_events") == before


async def test_the_play_ramp_lives_on_the_player(db):
    """**It moved.** It was `thing_uses.miss_streak`, keyed per (player,
    thing), on the reading that a ramp belonged to the toy. 3b settles
    that it is the cat's willingness to play with *you* - so carrying a
    second toy must not hand out a second fresh ramp, and a per-thing
    column would have done exactly that. Nothing ever wrote the old one,
    so the move cost nothing.
    """
    columns = await columns_of(db, "users")

    assert {"toy_ramp", "toy_cooldown_until"} <= columns
    assert "miss_streak" not in await columns_of(db, "thing_uses")


async def test_a_new_player_starts_at_the_bottom_of_the_ramp(db):
    """Zero is a guaranteed refusal, which is the intended first
    experience of the toy."""
    await db.ensure_user_exists(ALICE, GUILD_A)

    ramp, until = await db.play_state(GUILD_A, ALICE)

    assert (ramp, until) == (0, None)


async def test_the_guard_against_pre_multi_server_databases_still_stands(db):
    """2a's refusal to guess is not weakened by any of this."""
    assert issubclass(db.SchemaOutdatedError, db.StartupError)


# --------------------------------------------------------------------------
# Pre-2b rooms: both places a room name hides
#
# Before 2b a player's position and their unlocked-room list were both room
# *names*. Everything joins on ids now. The position was translated from the
# start; the list was not, and that gap is what broke `/use` on every exit for
# anyone who had entered the house before 2b.
# --------------------------------------------------------------------------


import content as content_module  # noqa: E402
import content_loader  # noqa: E402


@pytest.fixture
async def house(db):
    await content_loader.load_content(content_module.load_files())
    return db


async def an_old_player(db, user_id=ALICE, guild_id=GUILD_A, room="Living Room"):
    """A row exactly as the pre-2b code wrote it: names in both columns."""
    await db.ensure_user_exists(user_id, guild_id)
    rooms = await __import__("resolve").all_rooms()
    await db.start_game(user_id, guild_id, room, [name for _, name in rooms])


async def test_a_pre_2b_position_is_translated(house):
    await an_old_player(house)

    await house.migrate_room_names_to_ids()

    assert (await house.get_game_state(ALICE, GUILD_A)).current_room == "LI"


async def test_a_pre_2b_unlocked_list_is_repaired(house):
    """The half that used to be missed. `/use` on an exit compares
    `destination_room_id` - an id - against this list, so a list of names
    matched nothing and every exit refused."""
    await an_old_player(house)

    await house.migrate_room_names_to_ids()

    unlocked = (await house.get_game_state(ALICE, GUILD_A)).rooms_unlocked
    assert "EN" in unlocked
    assert "Entryway" not in unlocked


async def test_the_repair_does_not_hand_out_the_secret_library(house):
    """A verbatim translation would. Nothing has ever unlocked a room after
    entry, so there is no progress in the list to preserve - and the Secret
    Library is deliberately shut until 2e."""
    await an_old_player(house)

    await house.migrate_room_names_to_ids()

    assert "SE" not in (await house.get_game_state(ALICE, GUILD_A)).rooms_unlocked


async def test_a_current_row_is_left_alone(house):
    """Matched on names throughout, so a row already holding ids is untouched
    - which is what makes this safe to run on every boot."""
    await house.ensure_user_exists(BOB, GUILD_A)
    await house.start_game(BOB, GUILD_A, "KI", ["KI", "CO"])

    result = await house.migrate_room_names_to_ids()

    state = await house.get_game_state(BOB, GUILD_A)
    assert (state.current_room, state.rooms_unlocked) == ("KI", ["KI", "CO"])
    assert result == (0, 0)


async def test_the_repair_reports_what_it_touched(house):
    await an_old_player(house)

    assert await house.migrate_room_names_to_ids() == (1, 1)


async def test_running_the_repair_twice_changes_nothing(house):
    """Startup runs it every boot."""
    await an_old_player(house)
    await house.migrate_room_names_to_ids()
    after_once = (await house.get_game_state(ALICE, GUILD_A)).rooms_unlocked

    assert await house.migrate_room_names_to_ids() == (0, 0)
    assert (await house.get_game_state(ALICE, GUILD_A)).rooms_unlocked == after_once


async def test_it_repairs_every_player_not_just_the_first(house):
    await an_old_player(house, ALICE, GUILD_A)
    await an_old_player(house, BOB, GUILD_A, room="Kitchen")

    assert await house.migrate_room_names_to_ids() == (2, 2)
    for who in (ALICE, BOB):
        assert "EN" in (await house.get_game_state(who, GUILD_A)).rooms_unlocked


async def test_it_crosses_servers(house):
    await an_old_player(house, ALICE, GUILD_A)
    await an_old_player(house, ALICE, GUILD_B)

    await house.migrate_room_names_to_ids()

    assert "EN" in (await house.get_game_state(ALICE, GUILD_B)).rooms_unlocked


async def test_it_does_nothing_before_content_is_loaded(db):
    """It needs room_types to translate against, so it runs after the load."""
    assert await db.migrate_room_names_to_ids() == (0, 0)


# --------------------------------------------------------------------------
# Upgrading a database that already has the old shape
#
# From testing: drop 2 appeared not to have shipped at all. The files had
# it, the code had it, and the bot served drop 1's world - because
# `restocks.container` had been renamed to `destination` in the model and
# never added to the ALTER list, so every boot failed to write the
# content and `load_content_at_startup` kept the last good load. Exactly
# as documented, and invisible.
# --------------------------------------------------------------------------


async def test_a_renamed_column_reaches_a_database_that_predates_it(
    tmp_path, monkeypatch
):
    """The regression, as the real upgrade: a live `restocks` table in
    its pre-drop-2 shape, then a boot."""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'old.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)

    database._engine = None
    database._session_factory = None
    await database.init_db()
    async with database._engine.begin() as conn:
        await conn.execute(text("ALTER TABLE restocks DROP COLUMN destination"))
        await conn.execute(text("ALTER TABLE restocks DROP COLUMN max_present"))
        await conn.execute(text("ALTER TABLE restocks ADD COLUMN container VARCHAR(64)"))
    await database.close_db()

    database._engine = None
    database._session_factory = None
    await database.init_db()
    try:
        columns = await columns_of(database, "restocks")
        assert {"destination", "max_present"} <= columns

        # And the content it could not write before now writes.
        import content as content_module
        import content_loader

        report = await content_loader.load_content(content_module.load_files())
        assert report.content_rows["restocks"] > 0
    finally:
        await database.close_db()


def test_the_alter_list_names_real_columns():
    """Every entry in `_LATER_COLUMNS` has to exist on its model.

    This is the half of the problem that *is* checkable. A fully
    general "every model column survives an upgrade" test is not: the
    ALTER list is only responsible for columns added after a table was
    first created, and nothing in the schema records which those are -
    a test that drops everything and asks what comes back fails on the
    whole original schema, and one driven from the list itself is
    circular, which is how drop 2's missing entry went unnoticed.

    So this catches a stale or mistyped entry, the regression above
    catches the rename that actually broke, and the rule for the gap
    between them is written down: **a column added to a model goes in
    this list in the same commit, and a rename is an add plus an
    orphan.**
    """
    for table, column, _ in database._LATER_COLUMNS:
        model = database.Base.metadata.tables.get(table)
        assert model is not None, f"{table} is not a table"
        assert column in model.c, f"{table}.{column} is not on the model"
