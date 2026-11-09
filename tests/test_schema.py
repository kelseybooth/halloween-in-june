"""The phase 2b schema: content tables, world-state tables, and the migration.

The split these tests defend is the whole design. Content is global and never
mutated at runtime, which is what makes a reload safe. World state is per guild
and is the only thing a player can change. A content table that grew a guild_id,
or a world-state table that lost one, would break one half of that guarantee
quietly - the loader would start overwriting people's games, or two servers would
start sharing one.
"""

import logging
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import DateTime, inspect, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import database
import states


CONTENT_TABLES = {
    "room_types",
    "thing_types",
    "room_text",
    "thing_text",
    "defaults",
    "drops",
    "restocks",
    # The craving game's two: which emoji the game files where, and which
    # face the bot answers each outcome with. Global like all content, so
    # a writer swapping a reaction emoji is a reload rather than a release.
    "emoji_groups",
    "craving_reactions",
}

WORLD_TABLES = {
    "player_inventory",
    "room_contents",
    "player_states",
    "server_states",
    "server_config",
    "thing_uses",
    "server_restocks",
    # The craving game's three. All per server, because the craving is one
    # per server on purpose - the whole point is that players can tell
    # each other.
    "craving_days",
    "craving_messages",
    "craving_tally",
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
    """Four jobs: the cooldown, distinct-player plank counting, N-times
    achievements, and where the last one happened. The count is what makes
    the third answerable and `last_used_room` the fourth - *Accompanist*
    asks whether somebody else played the music box *here*, and a time
    with no place cannot say."""
    assert {"last_used_at", "use_count", "last_used_room"} <= await columns_of(
        db, "thing_uses"
    )


async def test_the_interaction_log_can_answer_the_questions_it_exists_for(db):
    """Four of these are what the first proposal was short of: an
    outcome, so a refusal is not a zero-scoring success; a reason, so
    you can see what players bounce off rather than only that they do;
    the score after, so a row is self-describing; and the thing, so
    `use` means something.

    `typed` is the fifth, added after a bug report that could not be
    traced: the thing says what the game decided, and only this says
    what the player asked for."""
    assert {
        "guild_id", "user_id", "actor", "action", "thing_id", "outcome",
        "reason", "relationship_delta", "score_after", "drop", "detail",
        "typed", "created_at",
    } <= await columns_of(db, "interaction_log")


async def test_pet_events_is_gone(db):
    """Absorbed, not duplicated. Two logs of the same event can
    disagree, and the mood roll now asks this one."""
    assert "pet_events" not in await table_names(db)


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
                db.PlayerState(
                    guild_id=GUILD_A,
                    user_id=ALICE,
                    state="has_key",
                    set_at=datetime(2026, 11, 1),
                ),
                db.ServerState(
                    guild_id=GUILD_A,
                    state="stairs_repaired",
                    set_at=datetime(2026, 11, 1),
                ),
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
        session.add(
            db.PlayerState(
                guild_id=GUILD_A,
                user_id=ALICE,
                state="drawer_unjammed",
                set_at=datetime(2026, 11, 1),
            )
        )
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
        # `users` survives the sweep above, so it is where a dropped
        # column can be left for the ALTER list to put back.
        await conn.execute(text("ALTER TABLE users DROP COLUMN last_decay_date"))
    await database.close_db()

    database._engine = None
    database._session_factory = None
    await database.init_db()
    try:
        names = await table_names(database)
        assert CONTENT_TABLES <= names
        assert WORLD_TABLES <= names
        assert "last_decay_date" in await columns_of(database, "users")

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
        assert fragments == 6, "the six channel fragments are the whole point"
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


async def test_the_log_gains_the_typed_column_in_place(db):
    """**The migration whose failure would be silent.**

    `log_interaction` swallows every error it meets, by design - a
    telemetry write that throws turns a pet the player already made
    into an error message. So a column the live database never gained
    is not an exception anybody sees. It is a log that simply stops
    filling, which is the drop 2 failure in a different table, and the
    reason that list carries a warning rather than a comment.

    Checked against a database that has the table *without* the column,
    because that is the live beta's shape and `create_all` will not
    touch a table that already exists.
    """
    async with db._engine.begin() as conn:
        await conn.execute(text("ALTER TABLE interaction_log DROP COLUMN typed"))
    assert "typed" not in await columns_of(db, "interaction_log")

    async with db._engine.begin() as conn:
        await db._add_missing_columns(conn)
    assert "typed" in await columns_of(db, "interaction_log")

    # And a row lands in it, which is the thing that was actually broken.
    assert await db.log_interaction(
        GUILD_A, action=database.USE, thing_id="cat_bed", typed="bed"
    )


async def test_running_the_migration_twice_is_a_no_op(db):
    """Startup runs it every boot, so it has to be safe to repeat."""
    before = await columns_of(db, "users")
    async with db._engine.begin() as conn:
        await db._add_missing_columns(conn)
        await db._add_missing_columns(conn)
    assert await columns_of(db, "users") == before


# --------------------------------------------------------------------------
# The two stamps the rules subtract
# --------------------------------------------------------------------------
#
# `player_states.set_at` and `server_states.set_at` shipped as
# `timestamptz NOT NULL DEFAULT now()`, and both halves of that were
# wrong for a column the game does arithmetic with. The timezone took a
# playtester's account down on 9 November 2026: naive minus aware raises
# a `TypeError`, which is not a `SQLAlchemyError`, so it went past every
# handler that apologises for the database. The default was quieter - it
# wrote the real time into a column the rules read as server time.
#
# **What can and cannot be driven here.** The shape a new database is
# created in, and the decision the migration makes, are both real tests
# below. The statements themselves are not: SQLite cannot `ALTER COLUMN`
# at all and reports every timestamp column naive whatever it was
# declared as, so there is no way to make the PostgreSQL path run
# against the backend CI has. They are pinned as text against a stand-in
# instead, which is worth having for exactly one reason - it is the only
# review the SQL gets before it runs over live rows.


@pytest.mark.parametrize("table", ["player_states", "server_states"])
async def test_a_state_stamp_is_naive_with_nothing_to_default_it(db, table):
    """What `thing_states.set_at` always was, and these two now are."""
    async with db._engine.connect() as conn:
        reflected = await conn.run_sync(
            lambda sync: {c["name"]: c for c in inspect(sync).get_columns(table)}
        )
    set_at = reflected["set_at"]

    assert getattr(set_at["type"], "timezone", False) is False
    assert set_at["default"] is None
    assert set_at["nullable"] is False


@pytest.mark.parametrize("table", ["player_states", "server_states"])
async def test_a_stamp_nobody_wrote_is_an_error_rather_than_an_hour(db, table):
    """The loud half of having no default, and the point of removing it.

    A writer that forgot the stamp used to get `now()` on the real
    clock, into a column the rules read as server time - which is a
    wrong answer that looks like a right one. Now it cannot be written
    at all.
    """
    model = {"player_states": db.PlayerState, "server_states": db.ServerState}[table]
    row = {"guild_id": GUILD_A, "state": "has_key"}
    if table == "player_states":
        row["user_id"] = ALICE

    with pytest.raises(IntegrityError):
        async with db._require_session()() as session:
            session.add(model(**row))
            await session.commit()


@pytest.mark.parametrize(
    "reflected, needs_repair",
    [
        ({"type": DateTime(timezone=True), "default": None}, True),
        ({"type": DateTime(), "default": "now()"}, True),
        ({"type": DateTime(timezone=True), "default": "now()"}, True),
        ({"type": DateTime(), "default": None}, False),
    ],
)
def test_what_counts_as_a_stamp_off_the_server_clock(reflected, needs_repair):
    """Either half is enough, and a column with neither is left alone.

    The shapes are the ones PostgreSQL reflection actually returns -
    checked against the beta database, where both columns came back as
    `TIMESTAMP(timezone=True)` with a `now()` default and
    `thing_states.set_at` came back as `TIMESTAMP()` with none.
    """
    assert database._stamp_is_off_the_server_clock(reflected) is needs_repair


class _PretendPostgres:
    """Just enough engine to drive the migration's PostgreSQL path.

    It answers `postgresql`, hands back a canned list of columns to
    repair instead of reflecting, and records every statement it is
    given. The reflection it skips is covered by
    `test_what_counts_as_a_stamp_off_the_server_clock`; what this exists
    for is the SQL, which is the one part of this change that cannot be
    rehearsed anywhere else.
    """

    def __init__(self, pending, refuse=False):
        self.dialect = SimpleNamespace(name="postgresql")
        self.pending = pending
        self.refuse = refuse
        self.statements: list[str] = []

    def connect(self):
        return _PretendConnection(self)

    def begin(self):
        return _PretendConnection(self)


class _PretendConnection:
    def __init__(self, engine):
        self._engine = engine

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def run_sync(self, _reflect):
        return self._engine.pending

    async def execute(self, clause):
        self._engine.statements.append(str(clause))
        if self._engine.refuse:
            raise SQLAlchemyError("could not alter the column")


async def test_the_retype_says_exactly_this_to_postgres():
    """The statements, pinned, because production is where they first run.

    `AT TIME ZONE 'UTC'` rather than a bare cast: a cast would read the
    stamp in whatever the session timezone happens to be. The default is
    dropped first so the cast never has to carry the default expression
    with it.
    """
    engine = _PretendPostgres(
        pending=[("player_states", "set_at", True), ("server_states", "set_at", True)]
    )

    await database._retype_state_stamps_as_naive(engine)

    assert engine.statements == [
        "ALTER TABLE player_states ALTER COLUMN set_at DROP DEFAULT",
        "ALTER TABLE player_states ALTER COLUMN set_at "
        "TYPE TIMESTAMP USING set_at AT TIME ZONE 'UTC'",
        "ALTER TABLE server_states ALTER COLUMN set_at DROP DEFAULT",
        "ALTER TABLE server_states ALTER COLUMN set_at "
        "TYPE TIMESTAMP USING set_at AT TIME ZONE 'UTC'",
    ]


async def test_a_column_that_only_kept_its_default_is_not_retyped():
    """Half-repaired is a state a boot can be interrupted into."""
    engine = _PretendPostgres(pending=[("player_states", "set_at", False)])

    await database._retype_state_stamps_as_naive(engine)

    assert engine.statements == [
        "ALTER TABLE player_states ALTER COLUMN set_at DROP DEFAULT"
    ]


async def test_a_retype_that_refuses_does_not_stop_the_boot(caplog):
    """The one migration in this file that is allowed to lose.

    Every other one is a prerequisite: the content load dies without the
    column, so a failure has to stop the bot rather than let it serve a
    half-loaded world. This one is a tidy-up - `_on_the_server_clock`
    already makes the read side correct against the old column - so a
    database where it cannot run is a database that plays, and taking
    the beta down over a column type would be the expensive way to be
    right.

    The second column is still attempted, which is why each one gets its
    own transaction: a failed statement poisons a PostgreSQL
    transaction, and one refusal should not abandon the other column.
    """
    engine = _PretendPostgres(
        pending=[("player_states", "set_at", True), ("server_states", "set_at", True)],
        refuse=True,
    )

    with caplog.at_level(logging.WARNING):
        await database._retype_state_stamps_as_naive(engine)

    assert [s for s in engine.statements if "DROP DEFAULT" in s] == [
        "ALTER TABLE player_states ALTER COLUMN set_at DROP DEFAULT",
        "ALTER TABLE server_states ALTER COLUMN set_at DROP DEFAULT",
    ]
    assert "player_states" in caplog.text
    assert "server_states" in caplog.text


async def test_the_retype_leaves_sqlite_alone(db):
    """Every local `python bot.py` boots through it, so it has to be safe.

    SQLite stores what it is handed and returns every stamp naive
    whatever the declared type says, so there is nothing here to repair
    and no `ALTER COLUMN` to repair it with.
    """
    before = await columns_of(db, "player_states")

    await db._retype_state_stamps_as_naive(db._engine)
    await db._retype_state_stamps_as_naive(db._engine)

    assert await columns_of(db, "player_states") == before
    await db.ensure_user_exists(ALICE, GUILD_A)
    assert await states.set_player_state(GUILD_A, ALICE, "drawer_unjammed") is True


async def test_the_retype_runs_at_startup(tmp_path, monkeypatch):
    """A migration nobody calls is the drop 2 failure in a new costume.

    It is called outside the transaction the rest of them share, which
    is the detail most likely to be lost in a later tidy-up: it owns a
    transaction per column so that one refusal cannot poison the next.
    """
    engines = []

    async def record(engine):
        engines.append(engine)

    monkeypatch.setattr(database, "_retype_state_stamps_as_naive", record)
    url = f"sqlite+aiosqlite:///{(tmp_path / 'boot.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)

    database._engine = None
    database._session_factory = None
    await database.init_db()
    try:
        assert engines == [database._engine]
    finally:
        await database.close_db()


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


# --------------------------------------------------------------------------
# The craving game
# --------------------------------------------------------------------------


async def test_a_message_remembers_which_day_its_face_is_from(db):
    """**Without the day, yesterday's 😻 is a lie.** The craving rolls over
    at midnight and the reactions do not, so the stored outcome has to say
    which answer it was about."""
    assert {"day", "outcome"} <= await columns_of(db, "craving_messages")


async def test_a_message_is_keyed_by_guild_and_message(db):
    async with db._engine.connect() as conn:
        key = await conn.run_sync(
            lambda sync: inspect(sync).get_pk_constraint("craving_messages")
        )

    assert set(key["constrained_columns"]) == {"guild_id", "message_id"}


async def test_nothing_counts_reaction_slots(db):
    """Deliberately absent. A player who also clicked the bot's emoji keeps
    it on the message after the bot removes its own, so any count stored
    here would drift from Discord's within a day. The live list is read
    every time instead."""
    columns = await columns_of(db, "craving_messages")

    assert not any("react" in name or "slot" in name or "count" in name
                   for name in columns)


async def test_the_ladder_can_have_a_rung_without_a_rank(db):
    """`out_of_guesses` is not a rung - it is the end of a message - so its
    progression is null rather than a number that could outrank a win."""
    async with db._engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync: inspect(sync).get_columns("craving_reactions")
        )
    progression = next(c for c in columns if c["name"] == "progression")

    assert progression["nullable"]
