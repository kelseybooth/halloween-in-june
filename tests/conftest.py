"""Shared fixtures.

Every test runs against a throwaway SQLite file, which is what CI uses and what
`python bot.py` falls back to locally. The database module keeps its engine in a
module-level global, so each test resets that global and builds a fresh schema:
tests never share rows, and one test's failure cannot leave state behind.
"""

import asyncio
import os
import pathlib
import shutil
import sys

import pytest
import pytest_asyncio

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import database  # noqa: E402
import resolve  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker,
    create_async_engine,
)

# Two servers used throughout, so "scoped per guild" is always exercised rather
# than assumed. Real Discord snowflakes are 64-bit, and a value above 2**32 is
# what catches a column that was declared INTEGER instead of BIGINT.
GUILD_A = 900000000000000001
GUILD_B = 900000000000000002

# The drop the house opens on: the Entryway and the five things in it.
# **Not the drop the whole house is open on**, which it was until 26 October
# - every Release 1 row used to wait at drop 3 together. The renumbering
# spread them across 10 to 50 against the room each one is in, so a test
# that wants nine furnished rooms wants `LAST_DROP`, and this one is for
# tests about the house *opening*.
HOUSE_DROP = 10

# Everything that exists, exists here. The `db` fixture puts both test
# guilds on it, because almost every test in the suite wants a world with
# its content in it rather than a world part-way through its calendar - and
# a test that is about the calendar moves its own server and says so.
#
# The eight achievements parked at 99 are unreachable by design, and stay
# that way.
LAST_DROP = 50

ALICE = 100000000000000001
BOB = 100000000000000002


@pytest.fixture(scope="session")
def schema_template(tmp_path_factory):
    """Build the schema once, and hand back a file to copy.

    Creating 27 tables costs about half a second, which was most of the suite's
    runtime once it was paid per test. It is built by running init_db itself, so
    the template cannot drift from what a real startup produces.
    """
    path = tmp_path_factory.mktemp("template") / "schema.db"
    url = f"sqlite+aiosqlite:///{path.as_posix()}"

    async def build():
        await database.init_db()
        await database.close_db()

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    os.environ.pop("RAILWAY_ENVIRONMENT", None)
    database._engine = None
    database._session_factory = None
    try:
        # Its own loop, so this stays a plain fixture and does not drag the
        # per-test event loop up to session scope.
        asyncio.run(build())
    finally:
        database._engine = None
        database._session_factory = None
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous

    return path


def _without_durability(engine) -> None:
    """Stop a test database paying for a guarantee nobody collects.

    Each test gets a SQLite file in its own `tmp_path`, deleted when the
    test ends and read by nobody after the process exits. `synchronous`
    buys one thing - that a committed transaction survives losing power -
    and that file does not survive the test either way.

    It is not a small charge. Broken into phases, the fixture costs about
    1.4ms to make the directory, 2.0ms to copy the schema template and
    1.7ms to open a connection, against **27ms for a commit**: the sync is
    the fixture. And a test makes many more commits than it looks like,
    because every write through `database` is its own transaction.

    Measured end to end on a quiet machine, the whole suite went from
    **905s to 447s** - the same 2,226 tests, half the wall clock, one
    pragma. Under `-n 8` it is 173s, and the two compose almost exactly,
    which is the clearest evidence that the sync was what the parallel
    workers would otherwise have been queueing behind.

    **`journal_mode` is deliberately left alone.** Setting it to MEMORY as
    well measured 23x rather than 4.4x on the write path, but the whole of
    that extra is about 3% of the suite, and it changes what a process
    dying mid-transaction leaves behind - a corrupt file rather than a
    stale one. Three per cent does not buy a footnote about crash
    recovery. It is a separate change if anybody ever wants it.

    Production is PostgreSQL and never sees this. It lives here rather
    than in `database.py` for that reason: the one place the pragma would
    otherwise bite is a developer running the bot on local SQLite, who did
    not ask to lose durability.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection, _record):  # pragma: no cover - driver callback
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA synchronous=OFF")
        cursor.close()


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch, schema_template):
    """A fresh, empty database for one test.

    The schema arrives by copying the session template rather than being created
    again; the engine is then wired up exactly as init_db wires it, minus the
    schema step the copy already did. init_db's own behaviour - the migration,
    the guards, the backend choice - is covered directly in test_schema.py.
    """
    path = tmp_path / "test.db"
    shutil.copyfile(schema_template, path)

    url = f"sqlite+aiosqlite:///{path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)

    database._engine = create_async_engine(url, pool_pre_ping=True)
    database._enforce_sqlite_foreign_keys(database._engine)
    _without_durability(database._engine)
    database._session_factory = async_sessionmaker(database._engine, expire_on_commit=False)

    # Open the house in both test servers before anything runs. Content
    # resolution answers to one pointer now, and without this every test in
    # the suite would be asserting against a server where the game has not
    # started and nothing exists.
    for guild_id in (GUILD_A, GUILD_B):
        await database.set_setting(guild_id, resolve.DROP_KEY, LAST_DROP)

    try:
        yield database
    finally:
        await database.close_db()


@pytest.fixture
def fixed_rng():
    """A stand-in for `random` whose rolls and choices are scripted.

    `random()` returns each queued value in turn, then repeats the last one.
    `choice()` always takes the first option, so a test asserting on which pool
    was drawn from does not also depend on which line came out of it.
    """

    class FixedRNG:
        def __init__(self):
            self.rolls: list[float] = []
            self._used = 0.5

        def queue(self, *rolls: float) -> "FixedRNG":
            self.rolls.extend(rolls)
            return self

        def random(self) -> float:
            if self.rolls:
                self._used = self.rolls.pop(0)
            return self._used

        def choice(self, seq):
            return list(seq)[0]

    return FixedRNG()


@pytest.fixture
def registrations(monkeypatch):
    """Record what the commands asked to register, without a gateway.

    `tree.sync` needs a real connection, and the three commands that move
    a server's drop all call it. Patching here keeps those suites about
    the drop while still letting them assert that the menu was asked to
    follow - which is the half a one-sided test would miss.
    """
    import bot

    calls: list[tuple[int, int | None]] = []

    async def record(guild, drop=None, tree=None):
        import gating

        calls.append((guild.id, drop))
        return gating.commands_for(drop)

    monkeypatch.setattr(bot, "register_commands_for", record)
    return calls
