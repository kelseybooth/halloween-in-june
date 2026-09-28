"""Load the content files into the database.

    python load_content.py                  # check the files, then load them
    python load_content.py --check          # check only, write nothing
    python load_content.py --fresh          # wipe world state and place again
    python load_content.py --allow-orphans  # load despite things players still hold

The bot also loads content at startup, which is how Railway gets it - there is no
shell there to run this from. This script exists for the checks a writer wants
before deploying, and for the two destructive flags that have no business running
unattended on boot.

`--check` needs no database at all, so it works on a fresh clone.
"""

import argparse
import asyncio
import logging
import sys

from dotenv import load_dotenv

import achievements
import content
import triggers
import content_loader
import database

load_dotenv()

logging.basicConfig(level=logging.WARNING, format="%(levelname)-8s %(message)s")


def _check_only() -> int:
    try:
        parsed = content.load_files()
    except content.ContentError as exc:
        print(exc, file=sys.stderr)
        return 1

    triggers.register_all()
    problems = content.validate(parsed)
    # Both directions: a row nobody wired up can never be announced, and a
    # trigger with no row would award something with no name. Neither errors
    # at runtime, which is exactly why they are caught here.
    problems += achievements.registration_problems(parsed.achievement_ids)
    print(
        f"parsed {len(parsed.rooms)} rooms, {len(parsed.things)} things, "
        f"{len(parsed.room_text) + len(parsed.thing_text)} text rows, "
        f"{len(parsed.defaults)} defaults, {len(parsed.drops)} drops, "
        f"{len(parsed.restocks)} restocks, "
        f"{len(parsed.emoji_groups)} emoji ({len(parsed.craving_pool)} drawable), "
        f"{len(parsed.achievements)} achievements "
        f"({len(achievements.registered_ids())} wired up)"
    )
    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("all checks pass")
    return 0


async def _load(fresh: bool, allow_orphans: bool) -> int:
    try:
        parsed = content.load()
    except content.ContentError as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        await database.init_db()
    except database.StartupError as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        report = await content_loader.load_content(
            parsed, fresh=fresh, allow_orphans=allow_orphans
        )
    except content_loader.OrphanedThings as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        await database.close_db()

    print(report.summary())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the files and exit without touching the database",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="wipe world state and place everything again (destroys player progress)",
    )
    parser.add_argument(
        "--allow-orphans",
        action="store_true",
        help="load even though players still hold things the files no longer define",
    )
    args = parser.parse_args()

    if args.check:
        if args.fresh or args.allow_orphans:
            parser.error("--check writes nothing, so it cannot be combined with the others")
        return _check_only()

    if args.fresh:
        print("--fresh deletes every player's inventory, states and progress.")
        if input("Type 'yes' to continue: ").strip().lower() != "yes":
            print("cancelled")
            return 1

    return asyncio.run(_load(args.fresh, args.allow_orphans))


if __name__ == "__main__":
    sys.exit(main())
