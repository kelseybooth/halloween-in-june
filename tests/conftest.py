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
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker,
    create_async_engine,
)

# Two servers used throughout, so "scoped per guild" is always exercised rather
# than assumed. Real Discord snowflakes are 64-bit, and a value above 2**32 is
# what catches a column that was declared INTEGER instead of BIGINT.
GUILD_A = 900000000000000001
GUILD_B = 900000000000000002

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
    database._session_factory = async_sessionmaker(database._engine, expire_on_commit=False)
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
