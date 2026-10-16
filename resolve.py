"""Which drops have arrived, and which text a player sees because of them.

A **release** is a deployment: code and content shipped together. A **drop** is a
moment something becomes visible to players. One release can carry a month of
drops, which is the point - the engineer ships once and the house keeps changing.
Nothing stores a release number and no command advances one.

Every content row carries `since_drop`. A row whose drop has not arrived is
loaded, present, and simply not yet reachable: text for it resolves to an earlier
drop's row, and things from it are not placed. When the drop arrives the row
starts winning, with no deploy and no migration.

**A server sits on one drop at a time, and that pointer is the whole rule.**
Everything numbered at or below it has arrived; everything above it has not.
Two servers can sit on different drops at once, which is what lets one be
played while another is tested a week ahead.

The pointer starts unset, which is not the same as drop 0: a server where
nobody has run `/start-game` has no game, and no content at all is reachable
in it. The calendar that used to answer this is gone for V3 - drops advance
by admin command only, and dates return once a few servers have run and the
pacing is known.
"""

from __future__ import annotations

import logging
from typing import NamedTuple, Sequence

from sqlalchemy import select

import database

log = logging.getLogger(__name__)

DEFAULT_STATE = "default"

# Where a server's drop pointer lives. Deliberately not in `CONFIG_KEYS`:
# `/admin_config` tunes numbers an admin may reasonably want to change
# mid-game, and which drop a server is on is not one of them. It moves by
# `/start-game`, `/advance-game` and nothing else.
DROP_KEY = "current_drop"

# What an unset pointer reads as. Not 0, which is a real drop.
NO_GAME = None


class UnknownDrop(Exception):
    """An admin tried to fire a drop the content files do not define."""


async def current_drop(guild_id: int) -> int | None:
    """Which drop this server is on, or None if its game has not started.

    The distinction matters: drop 0 is a channel with a cat in it, and
    `None` is a server the bot is merely a member of.
    """
    raw = await database.get_config_raw(guild_id, DROP_KEY)
    if raw is None:
        return NO_GAME
    try:
        return int(raw)
    except ValueError:
        log.warning(
            "server_config %s is %r in guild %s, which is not a drop number; "
            "treating the game as not started",
            DROP_KEY,
            raw,
            guild_id,
        )
        return NO_GAME


async def set_current_drop(guild_id: int, drop_id: int) -> None:
    """Move this server to a drop, which must be one the files define.

    Forward and backward both go through here. Only `/advance-game` and the
    QA commands call it, and only `/advance-game` is on the live server.
    """
    if drop_id not in await defined_drop_ids():
        raise UnknownDrop(f"No drop {drop_id} in the content files")
    await database.set_setting(guild_id, DROP_KEY, drop_id)
    log.info("Guild %s is now on drop %s", guild_id, drop_id)


async def defined_drop_ids() -> set[int]:
    """Every drop the content files define, whether or not anyone is on it."""
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = await session.execute(select(database.Drop.drop_id))
    return {row[0] for row in rows}


async def arrived_drop_ids(guild_id: int) -> set[int]:
    """Every drop that has arrived on this server.

    One rule: at or below the pointer. A server with no pointer has nothing,
    which is why a bot sitting in a server nobody has started shows that
    server's members no content at all.
    """
    current = await current_drop(guild_id)
    if current is NO_GAME:
        return set()
    return {d for d in await defined_drop_ids() if d <= current}


def _best(rows, arrived: set[int], state, column: str) -> str | None:
    """Pick the winning row: the player's state if it has one, else default.

    `state` may be several, in priority order, which is what a player holding
    more than one needs. The first that this entity actually has a row for
    wins, so the order can be "most specific first" without having to know
    which states each entity was written for: somebody who has opened the
    passage reads the open cabinet, and the same list asked about the oak
    falls past both to the oak's own row.

    Within a state the highest arrived `since_drop` wins. Drops are numbered in
    the order their content should supersede, and because an event drop can
    arrive while a lower-numbered one has not, "highest arrived" is not the same
    as "highest" - which is why arrival is filtered before the maximum is taken.
    """
    wanted = (state,) if isinstance(state, str) else tuple(state)
    ordered = [*dict.fromkeys((*wanted, DEFAULT_STATE))]
    for wanted in ordered:
        candidates = [
            row
            for row in rows
            if row["state"] == wanted and row["since_drop"] in arrived and row[column]
        ]
        if candidates:
            return max(candidates, key=lambda row: row["since_drop"])[column]
    return None


async def room_look(
    guild_id: int, room_id: str, state: str = DEFAULT_STATE
) -> str | None:
    """The description of a room as this server currently sees it."""
    arrived = await arrived_drop_ids(guild_id)
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    database.RoomText.state,
                    database.RoomText.since_drop,
                    database.RoomText.look,
                ).where(database.RoomText.room_id == room_id)
            )
        ).all()

    return _best(
        [{"state": r[0], "since_drop": r[1], "look": r[2]} for r in rows],
        arrived,
        state,
        "look",
    )


async def thing_text(
    guild_id: int,
    thing_id: str,
    column: str,
    state: "str | Sequence[str]" = DEFAULT_STATE,
) -> str | None:
    """One column of a thing's text, resolved for state and arrived drops.

    Returns None when the content leaves the cell blank, which is the signal to
    fall through to the house default - see default_text.
    """
    if column not in database.ThingText.__table__.columns:
        raise ValueError(f"{column!r} is not a thing text column")

    arrived = await arrived_drop_ids(guild_id)
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(database.ThingText).where(database.ThingText.thing_id == thing_id)
            )
        ).scalars().all()

    return _best(
        [
            {"state": r.state, "since_drop": r.since_drop, column: getattr(r, column)}
            for r in rows
        ],
        arrived,
        state,
        column,
    )


async def default_text(key: str) -> str | None:
    """A house fallback string, used wherever a content cell is blank."""
    session_factory = database._require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(database.DefaultText.text_value).where(database.DefaultText.key == key)
        )


async def visible_thing_ids(guild_id: int) -> set[str]:
    """Things whose drop has arrived on this server.

    A thing from a later drop is loaded and inert: not placed, not listed, not
    resolvable. This is the gate the loader consults before placing anything.
    """
    arrived = await arrived_drop_ids(guild_id)
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(database.ThingType.thing_id, database.ThingType.since_drop)
            )
        ).all()
    return {thing_id for thing_id, since_drop in rows if since_drop in arrived}


class AchievementRow(NamedTuple):
    """An achievement as one server currently sees it."""

    achievement_id: str
    kind: str
    name: str
    unlock: str
    sort_order: int


async def achievements(guild_id: int) -> dict[str, AchievementRow]:
    """Every achievement that exists on this server, by id.

    Same resolution as every other content row: within an id, the highest
    *arrived* drop wins, so a name can be rewritten at a later drop without a
    deploy. An achievement from a drop that has not arrived is absent here -
    it cannot be earned, announced or listed.

    Read in one query and cached nowhere. The alternative is a per-hook read
    of one row, which is the same work spread thinner and goes stale the
    moment content reloads.
    """
    arrived = await arrived_drop_ids(guild_id)
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    database.Achievement.achievement_id,
                    database.Achievement.since_drop,
                    database.Achievement.kind,
                    database.Achievement.name,
                    database.Achievement.unlock,
                    database.Achievement.sort_order,
                )
            )
        ).all()

    best: dict[str, tuple[int, AchievementRow]] = {}
    for achievement_id, since_drop, kind, name, unlock, sort_order in rows:
        if since_drop not in arrived:
            continue
        if achievement_id in best and best[achievement_id][0] >= since_drop:
            continue
        best[achievement_id] = (
            since_drop,
            AchievementRow(achievement_id, kind, name, unlock, sort_order),
        )
    return {key: row for key, (_, row) in best.items()}


# --------------------------------------------------------------------------
# The house itself
#
# The room list and the navigation graph used to live in house_utils.py. They
# come from the content files now: rooms from rooms.tsv, exits from the
# `type = exit` rows in things.tsv with destination_room_id as the graph. What
# stays in house_utils is Discord plumbing - creating threads and moving people
# in and out of them - because that is not content.
# --------------------------------------------------------------------------


class Exit(NamedTuple):
    """One way out of a room. An exit is a thing whose use moves the player."""

    thing_id: str
    name: str
    aliases: tuple[str, ...]
    destination: str


async def all_rooms() -> list[tuple[str, str]]:
    """(room_id, name) for every room, in the order the files give them."""
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(database.RoomType.room_id, database.RoomType.name).order_by(
                database.RoomType.sort_order, database.RoomType.room_id
            )
        )
        return [(row[0], row[1]) for row in rows]


async def room_names() -> list[str]:
    """Every room's display name, which is also its thread name."""
    return [name for _, name in await all_rooms()]


async def room_name(room_id: str) -> str | None:
    session_factory = database._require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(database.RoomType.name).where(database.RoomType.room_id == room_id)
        )


async def starting_room() -> str | None:
    """Where a new player begins: the first room open at launch."""
    session_factory = database._require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(database.RoomType.room_id)
            .where(database.RoomType.open_at_launch.is_(True))
            .order_by(database.RoomType.sort_order, database.RoomType.room_id)
            .limit(1)
        )


async def rooms_open_at_launch() -> list[str]:
    """The room_ids a new player starts with unlocked.

    The Secret Library is not among them. It is found by climbing the oak and
    coming in through the window, which is a discovery rather than a door, and
    the mechanism that records it belongs to 2c.
    """
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(database.RoomType.room_id)
            .where(database.RoomType.open_at_launch.is_(True))
            .order_by(database.RoomType.sort_order, database.RoomType.room_id)
        )
        return [row[0] for row in rows]


async def exits_from(guild_id: int, room_id: str) -> list[Exit]:
    """Every exit out of a room whose drop has arrived on this server."""
    arrived = await arrived_drop_ids(guild_id)
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    database.ThingType.thing_id,
                    database.ThingType.name,
                    database.ThingType.aliases,
                    database.ThingType.destination_room_id,
                    database.ThingType.since_drop,
                )
                .where(
                    database.ThingType.type == "exit",
                    database.ThingType.room_id == room_id,
                )
                .order_by(database.ThingType.sort_order, database.ThingType.thing_id)
            )
        ).all()

    return [
        Exit(thing_id, name, tuple(aliases or ()), destination)
        for thing_id, name, aliases, destination, since_drop in rows
        if since_drop in arrived and destination
    ]


async def resolve_exit(guild_id: int, room_id: str, typed: str) -> Exit | None:
    """Match what a player typed against the exits out of their room.

    Case-insensitive, whitespace-trimmed, and matching the exit's name or any of
    its aliases. Aliases are unique within a room - the loader checks it - so a
    name never matches two exits.
    """
    needle = typed.strip().lower()
    if not needle:
        return None

    for exit_ in await exits_from(guild_id, room_id):
        if needle == exit_.name.lower() or needle in {a.lower() for a in exit_.aliases}:
            return exit_
        if needle == exit_.thing_id.lower():
            return exit_
    return None
