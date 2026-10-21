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

import content
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

# The furthest `/advance-game` will take a server. `drops.tsv` defines drops
# the content already waits on - every Release 1 row sits at drop 3 - but
# defining a drop is not the same as having built it, and "the last defined
# drop" would walk a live server into one with no commands and no content.
#
# A constant rather than a per-server setting: there is no reason for two
# servers to disagree about which drops exist, and the test servers get
# anywhere they like through `/qa-drop`.
#
# **Raise it in the release that builds the next drop, in the same
# commit.** Drop 2 shipped with this still reading 1, so `/advance-game`
# refused to reach the drop that had just been built and the only way
# in was `/qa-drop` on a test server. `test_every_built_drop_is
# _reachable` is what stops that happening again.
LAST_PLAYABLE_DROP = 2


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


async def drop_name(drop_id: int) -> str | None:
    """What the files call a drop, for an admin about to open one."""
    session_factory = database._require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(database.Drop.name).where(database.Drop.drop_id == drop_id)
        )


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
    guild_id: int,
    room_id: str,
    state: str = DEFAULT_STATE,
    unlocked: frozenset[str] = frozenset(),
) -> str | None:
    """The description of a room as this player currently sees it.

    Assembled from fragments **in fragment order, never in arrival
    order**. Nine rooms have one fragment each and read exactly as they
    always did; the channel has six, three of which are gated on what
    this player has done.

    That ordering is the load-bearing part. The branches are fragment 2
    and unlock in the second stage, so they have to slot back into
    second position in the paragraph rather than being appended after
    the tire tracks - which is what an implementation that collects
    unlocked fragments as it finds them would do.

    `unlocked` is what this player has satisfied, passed in rather than
    looked up, so this stays a content resolver and the hint rail stays
    the only thing that knows what a hint id means.

    **State selection is `_best`'s, run once per fragment**: the
    player's states in priority order, then `default`, and the highest
    arrived drop within whichever state wins. The first version of this
    compared against one state and dropped the fallback, which turned
    every room a player held a state for into "You see a room." - the
    Living Room went blank the moment somebody unlocked the cabinet.
    Fragments changed how many answers there are, not how one is found.
    """
    arrived = await arrived_drop_ids(guild_id)
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    database.RoomText.state,
                    database.RoomText.since_drop,
                    database.RoomText.fragment,
                    database.RoomText.visible_when,
                    database.RoomText.look,
                ).where(database.RoomText.room_id == room_id)
            )
        ).all()

    # `_best`'s rule, applied once per fragment: the player's states in
    # priority order, then `default`, and within a state the highest
    # arrived drop. Running it per fragment rather than per room is what
    # lets a later drop rewrite one sentence of the channel, or one
    # sentence of a room in one state, without restating the rest.
    wanted = (state,) if isinstance(state, str) else tuple(state)
    ordered = [*dict.fromkeys((*wanted, DEFAULT_STATE))]

    found: dict[int, dict[str, tuple[int, str | None, str]]] = {}
    for row_state, since_drop, fragment, visible_when, look in rows:
        if since_drop not in arrived or not look:
            continue
        slot = found.setdefault(fragment, {})
        if row_state in slot and slot[row_state][0] >= since_drop:
            continue
        slot[row_state] = (since_drop, visible_when, look)

    parts = []
    for fragment in sorted(found):
        slot = found[fragment]
        for candidate in ordered:
            if candidate not in slot:
                continue
            _, visible_when, look = slot[candidate]
            # The gate is read *after* the state has been chosen, so a
            # fragment this player cannot see stays unseen rather than
            # falling through to some other state's version of itself.
            if not visible_when or visible_when in unlocked:
                parts.append(look)
            break

    return " ".join(parts) if parts else None


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


async def defaults_matching(prefix: str) -> list[str]:
    """Every house string whose key starts with this, in key order.

    One string per key rather than variants inside one cell: the
    writers review these decks as tables and `|` is the column
    delimiter, so a pipe-separated list would be split in two by the
    first edit. Adding a thirteenth refusal is a row.

    Sorted by key so a numbering gap is visible rather than silently
    making the pick uneven.
    """
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(database.DefaultText.text_value)
            .where(database.DefaultText.key.startswith(prefix))
            .order_by(database.DefaultText.key)
        )
    return [row[0] for row in rows if row[0]]


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
    offered: bool = False
    prompt: str | None = None
    requires: str | None = None


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
                    database.Achievement.offered,
                    database.Achievement.prompt,
                    database.Achievement.requires,
                )
            )
        ).all()

    best: dict[str, tuple[int, AchievementRow]] = {}
    for row in rows:
        achievement_id, since_drop = row[0], row[1]
        if since_drop not in arrived:
            continue
        if achievement_id in best and best[achievement_id][0] >= since_drop:
            continue
        best[achievement_id] = (
            since_drop,
            AchievementRow(achievement_id, *row[2:]),
        )
    return {key: row for key, (_, row) in best.items()}


async def open_quests(guild_id: int, user_id: int) -> list[AchievementRow]:
    """Every quest this player can currently see, newest first.

    **A public achievement with a visibility prerequisite is a quest.**
    Four conditions, all of which have to hold: it is `offered`, its drop
    has arrived here, this player holds what it `requires`, and they have
    not earned it yet.

    `requires` is single-valued on purpose. Every public quest is rooted
    at *Making First Contact*, so one id is enough - and the moment one
    needs two unrelated prerequisites this becomes a resolver, so the
    tree stays rooted.

    **Newest first**, because a player opens `/stats` just after being
    told a new quest is available and should not have to read to the
    bottom for it. "Newest" is the order they became visible, which is
    what the notices table records; a quest the player has not been
    notified of yet is newer than all of them and sorts above.
    """
    rows = await achievements(guild_id)
    earned = set(await database.player_achievements_of(guild_id, user_id))
    seen = await database.notice_order(guild_id, user_id)

    quests = [
        row
        for row in rows.values()
        if row.offered
        and row.achievement_id not in earned
        and (not row.requires or row.requires in earned)
    ]
    # Unseen first (they just appeared), then most recently seen.
    return sorted(
        quests,
        key=lambda row: (
            0 if row.achievement_id not in seen else 1,
            -seen.get(row.achievement_id, 0),
            row.achievement_id,
        ),
    )


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
