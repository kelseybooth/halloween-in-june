"""Wipe player data so a test run starts from a clean slate.

    python reset_db.py --yes           # delete every user and pet event
    python reset_db.py --yes --fresh   # local SQLite only: delete the file itself

Both modes clear all players. `--fresh` additionally discards the schema so the
next startup rebuilds it from the current models - worth using after changing a
column default, since an ALTER-ed column keeps whatever SQL default it was
created with even when the model changes.

A timestamped backup of the SQLite file is taken first, so a reset is always
recoverable. PostgreSQL is not backed up: use your provider's snapshot tooling
before resetting anything you care about.
"""

import argparse
import asyncio
import os
import shutil
import sys
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import delete, func, select

import database

load_dotenv()


def _sqlite_path() -> str | None:
    """Local database file backing this run, or None when using PostgreSQL."""
    if os.getenv("DATABASE_URL", "").strip():
        return None
    return database.DEFAULT_SQLITE_URL.split("///", 1)[1]


def _backup(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = f"{path}.backup-{stamp}"
    shutil.copy2(path, target)
    return target


async def _summarise() -> tuple[int, int]:
    async with database._session_factory() as session:
        users = await session.scalar(select(func.count()).select_from(database.User))
        events = await session.scalar(select(func.count()).select_from(database.PetEvent))
    return users or 0, events or 0


async def _wipe() -> None:
    async with database._session_factory() as session:
        await session.execute(delete(database.PetEvent))
        await session.execute(delete(database.User))
        await session.commit()


async def main(fresh: bool) -> int:
    path = _sqlite_path()

    if path:
        backup = _backup(path)
        print(f"backup: {backup}" if backup else "backup: none (no database file yet)")
    else:
        print("backend: PostgreSQL - no automatic backup taken")

    if fresh and path:
        # Dropping the file also drops the schema, so the next startup recreates
        # every column with the defaults currently declared on the models.
        if os.path.exists(path):
            os.remove(path)
            print(f"deleted {path} - the next `python bot.py` rebuilds it")
        else:
            print(f"{path} did not exist; nothing to delete")
        return 0

    await database.init_db()
    before = await _summarise()
    await _wipe()
    after = await _summarise()
    await database.close_db()

    print(f"users:      {before[0]} -> {after[0]}")
    print(f"pet_events: {before[1]} -> {after[1]}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset player data for testing.")
    parser.add_argument("--yes", action="store_true", help="required; confirms the wipe")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="SQLite only: delete the database file so the schema is rebuilt too",
    )
    args = parser.parse_args()

    if not args.yes:
        print("This deletes every player record. Re-run with --yes to confirm.")
        sys.exit(1)

    sys.exit(asyncio.run(main(args.fresh)))
