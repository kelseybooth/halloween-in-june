"""Recover the two trails' progress from the interaction log.

`room_deeds` arrived with *Rung by Rung* and *Burrito Trail* on 2 November
2026, and it is written forward only - so a player who had already climbed
four rooms and left thirty burritos around the house would have started
both trails from nothing. This puts back what the log can prove.

**Two halves, and they are not equally sure of themselves.**

Climbs are recorded. Every successful `/use ladder` row carries
`room=XX carried=.. cat=.. nest=..` in `detail`, because the ladder wanted
those four facts in its own log row - so the room is read straight off it,
and `cat=yes` is exactly the climb the design says does not count.

Drops are inferred. A drop's `detail` is the container it went into or
nothing at all, so the room is not in the row. It is recoverable anyway:
`move` rows carry `from=XX to=YY`, so the room a player was standing in is
the destination of their last move before the drop. A drop with no move
before it in the log cannot be placed, and is reported rather than guessed.

**Run it twice and nothing happens twice.** Every write goes through the
same `ON CONFLICT DO NOTHING` the live path uses, and each deed is stamped
with the timestamp of the log row that proves it rather than with now.

Reports by default and writes only with `--apply`:

    python backfill_room_deeds.py
    python backfill_room_deeds.py --apply

It reads `DATABASE_URL` through `database.init_db`, the same way the bot
does, so it wants to run where the bot runs - `railway run` against the
deployed service, or with the public URL in the environment. `init_db`
creates missing tables, which is the one thing the no-write default does
not cover; after a deploy of the release that added `room_deeds` there is
nothing left for it to create.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select

import database
import telemetry
import world

log = logging.getLogger(__name__)

# `room=CO carried=no cat=no nest=no`, which is `bot._climb_detail`.
_ROOM = re.compile(r"\broom=([A-Za-z]+)")
_CAT = re.compile(r"\bcat=(yes|no)")
# `from=KI to=CO`, which is the move handler's own detail. Both halves are
# wanted: `to` is where a move put somebody, and `from` is the only record
# of where they were standing before they moved for the first time.
_TO = re.compile(r"\bto=([A-Za-z]+)")
_FROM = re.compile(r"\bfrom=([A-Za-z]+)")


@dataclass(frozen=True)
class Deed:
    """One row this script would write, and when it happened."""

    guild_id: int
    user_id: int
    action: str
    thing_id: str
    room_id: str
    first_at: datetime


@dataclass
class Plan:
    """What the log can prove, and what it cannot."""

    deeds: list[Deed] = field(default_factory=list)
    cat_climbs: int = 0
    drops_without_a_room: int = 0

    def by_thing(self) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for deed in self.deeds:
            counts[(deed.action, deed.thing_id)] += 1
        return dict(sorted(counts.items()))


async def _rows(action: str) -> list[tuple]:
    """Every successful player row for one action, oldest first.

    Oldest first because both halves depend on order: the earliest climb in
    a room is that deed's `first_at`, and a drop is placed by the move that
    came before it.
    """
    async with database._require_session()() as session:
        result = await session.execute(
            select(
                database.InteractionLog.guild_id,
                database.InteractionLog.user_id,
                database.InteractionLog.thing_id,
                database.InteractionLog.detail,
                database.InteractionLog.created_at,
            )
            .where(
                database.InteractionLog.action == action,
                database.InteractionLog.outcome == telemetry.SUCCESS,
                database.InteractionLog.user_id.is_not(None),
            )
            .order_by(database.InteractionLog.created_at)
        )
        return list(result.all())


async def plan() -> Plan:
    """Every deed the log can prove, and nothing written."""
    found = Plan()
    seen: set[tuple[int, int, str, str, str]] = set()

    def remember(guild_id, user_id, action, thing_id, room_id, when) -> None:
        # The first row wins, which is what makes `first_at` the first time.
        key = (guild_id, user_id, action, thing_id, room_id)
        if key in seen:
            return
        seen.add(key)
        found.deeds.append(Deed(*key, first_at=when))

    for guild_id, user_id, thing_id, detail, when in await _rows(telemetry.USE):
        if thing_id != world.LADDER:
            continue
        room = _ROOM.search(detail or "")
        if room is None:
            # A climb logged before `_climb_detail` carried the room.
            continue
        cat = _CAT.search(detail or "")
        if cat is not None and cat.group(1) == "yes":
            found.cat_climbs += 1
            continue
        remember(guild_id, user_id, telemetry.USE, thing_id, room.group(1), when)

    # **One timeline, moves and drops together.** Replaying the moves into a
    # "where everybody is standing" map and reading it at each drop is the
    # only way round a log with no room on a drop row - and it has to be one
    # pass over both, in time order, or a drop is placed by a move that had
    # not happened yet.
    #
    # **Seeded from the other half of the first move.** Half the drops in
    # the live log happen before their player is ever seen moving - most of
    # them in the channel, where a game starts and plenty of players stay -
    # and a drop with nothing before it would have been thrown away. A move
    # row says `from=CH to=EN`, so the room somebody was standing in before
    # they moved for the first time is recorded too. That is still a read
    # and not a guess, which is the line this script tries not to cross.
    moves = await _rows(telemetry.MOVE)
    standing: dict[tuple[int, int], str] = {}
    for guild_id, user_id, _thing, detail, _when in moves:
        who = (guild_id, user_id)
        came_from = _FROM.search(detail or "")
        if who not in standing and came_from is not None:
            standing[who] = came_from.group(1)
    timeline = sorted(
        [
            (when, 0, guild_id, user_id, None, detail)
            for guild_id, user_id, _thing, detail, when in moves
        ]
        + [
            (when, 1, guild_id, user_id, thing_id, detail)
            for guild_id, user_id, thing_id, detail, when in await _rows(telemetry.DROP)
        ],
        key=lambda row: (row[0], row[1]),
    )
    for when, kind, guild_id, user_id, thing_id, detail in timeline:
        who = (guild_id, user_id)
        if kind == 0:
            to = _TO.search(detail or "")
            if to is not None:
                standing[who] = to.group(1)
            continue
        if thing_id is None:
            continue
        room_id = standing.get(who)
        if room_id is None:
            # Never seen moving at all, so there is no `from=` to start them
            # in either. The room could be guessed from where a game begins,
            # and a guess in a table of facts is worse than a gap.
            found.drops_without_a_room += 1
            continue
        remember(guild_id, user_id, telemetry.DROP, thing_id, room_id, when)

    return found


async def apply(found: Plan) -> int:
    """Write the plan. Returns how many rows the database did not have.

    Counted by reading the table before and after rather than by trusting
    the inserts, because `DO NOTHING` does not say whether it did nothing -
    and "ran twice, wrote nothing the second time" is the claim this script
    most needs to be able to make.
    """
    before = await _deed_count()
    for deed in found.deeds:
        await database.record_room_deed(
            deed.user_id,
            deed.guild_id,
            deed.action,
            deed.thing_id,
            deed.room_id,
            when=deed.first_at,
        )
    return await _deed_count() - before


async def _deed_count() -> int:
    async with database._require_session()() as session:
        rows = await session.execute(select(database.RoomDeed.room_id))
        return len(rows.all())


def report(found: Plan, written: int | None = None) -> str:
    """What it found, in the order somebody reading it wants it."""
    lines = [f"{len(found.deeds)} deeds the log can prove:"]
    for (action, thing_id), count in found.by_thing().items():
        lines.append(f"  {action:5} {thing_id:24} {count}")
    lines.append(f"{found.cat_climbs} climbs the cat took, which do not count")
    lines.append(
        f"{found.drops_without_a_room} drops with no move before them, "
        "which cannot be placed"
    )
    if written is None:
        lines.append("Nothing written. Pass --apply to write.")
    else:
        lines.append(f"{written} rows written; the rest were already there.")
    return "\n".join(lines)


async def main(write: bool) -> None:
    await database.init_db()
    try:
        found = await plan()
        written = await apply(found) if write else None
        print(report(found, written))
    finally:
        await database.close_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill room_deeds from the log.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the deeds. Without it, nothing is written.",
    )
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(parser.parse_args().apply))
