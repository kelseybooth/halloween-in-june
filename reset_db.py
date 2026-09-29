"""Wipe every server's game so a test run starts from a clean slate.

    python reset_db.py --yes           # clear every server's progress
    python reset_db.py --yes --fresh   # local SQLite only: delete the file itself

**This clears every server in the database.** To reset one, use the
`/reset-haunted-house` command in that server - it is scoped to the guild it
is run in, and it is the only option on a host with no shell.

Both modes clear all progress. `--fresh` additionally discards the schema so
the next startup rebuilds it from the current models - worth using after
changing a column default, since an ALTER-ed column keeps whatever SQL default
it was created with even when the model changes.

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
from sqlalchemy import func, select

import content_loader
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



async def _wipe() -> None:
    """Delete every server's game, children before parents.

    **The table list is read off the schema rather than written here.** It
    used to be written here, and it fell eleven tables behind: it named
    `inventory`, `player_game_state`, `pet_events` and `users` while
    achievements, the current inventory, room contents, player and server
    states, uses, config, drops, restocks and art all quietly survived a
    "reset". The result was worse than doing nothing - players vanished and
    everything they had done stayed.

    Phase 2b split content from world state on exactly the line this needs:
    content is global and carries no `guild_id`, world state is per guild and
    always does, and `test_schema.py` asserts it table by table in both
    directions. So `content_loader.world_tables()` is the right question
    asked of the schema, and it cannot drift again.

    Order matters: `inventory` and `player_game_state` both carry a foreign
    key to `users`, so deleting users first fails the constraint. That is not
    hypothetical - it has always failed on PostgreSQL for any server where
    somebody had entered the house, and appeared to work locally only because
    SQLite ignored the constraint and left the rows orphaned instead.
    """
    async with database._session_factory() as session:
        for name in content_loader.world_tables():
            await session.execute(database.Base.metadata.tables[name].delete())
        await session.commit()


async def _counts() -> dict[str, int]:
    """How many rows each world table holds, across every server."""
    out = {}
    async with database._session_factory() as session:
        for name in content_loader.world_tables():
            table = database.Base.metadata.tables[name]
            out[name] = await session.scalar(select(func.count()).select_from(table))
    return out


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

    try:
        await database.init_db()
    except database.SchemaOutdatedError:
        # Rows cannot be cleared from a schema this code no longer understands;
        # the file has to be rebuilt.
        print("this database predates per-server scoping - re-run with --fresh to rebuild it")
        return 1
    before = await _counts()
    await _wipe()
    after = await _counts()
    await database.close_db()

    touched = {name: n for name, n in before.items() if n}
    if not touched:
        print("nothing to clear - the database held no games")
    for name, n in sorted(touched.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<22} {n} -> {after[name]}")
    left = sum(after.values())
    print(f"cleared {sum(touched.values())} row(s) across {len(touched)} table(s)")
    if left:
        print(f"WARNING: {left} row(s) survived, which should not happen")
        return 1
    print("content is untouched; the next `python bot.py` reloads it and "
          "re-places every server's stock")
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
