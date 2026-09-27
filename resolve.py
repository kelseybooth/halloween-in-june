"""Which drops have arrived, and which text a player sees because of them.

A **release** is a deployment: code and content shipped together. A **drop** is a
moment something becomes visible to players. One release can carry a month of
drops, which is the point - the engineer ships once and the house keeps changing.
Nothing stores a release number and no command advances one.

Every content row carries `since_drop`. A row whose drop has not arrived is
loaded, present, and simply not yet reachable: text for it resolves to an earlier
drop's row, and things from it are not placed. When the drop arrives the row
starts winning, with no deploy and no migration.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select

import database

log = logging.getLogger(__name__)

# A date drop carrying this arrives the moment a server initializes, rather than
# on a calendar date. Every Release 1 row uses it.
LAUNCH = "launch"

DEFAULT_STATE = "default"


class UnknownDrop(Exception):
    """An admin tried to fire a drop the content files do not define."""


def _has_date_arrived(value: str | None, today: date) -> bool:
    """Whether a `date` trigger has come due.

    Answered from the calendar every time it is asked rather than recorded, so a
    dated drop lands at the same moment on every server and there is only one
    source of truth for it. An unparseable date is treated as not yet arrived:
    content appearing early because of a typo is worse than content appearing
    late, and the loader rejects the file anyway.
    """
    if not value:
        return False
    if value.strip().lower() == LAUNCH:
        return True
    try:
        return date.fromisoformat(value.strip()) <= today
    except ValueError:
        log.warning("Drop has an unreadable date %r; treating it as not yet arrived", value)
        return False


async def arrived_drop_ids(guild_id: int, *, today: date | None = None) -> set[int]:
    """Every drop that has arrived on this server.

    Dated drops are computed. Event and manual drops are read from server_drops,
    never re-evaluated: a condition can stop being true - a counter falls back, a
    thing is taken out of a room - and content must not vanish from a house it
    has already changed.
    """
    today = today or database.pacific_today()
    session_factory = database._require_session()

    async with session_factory() as session:
        rows = (
            await session.execute(select(database.Drop.drop_id, database.Drop.trigger, database.Drop.date))
        ).all()
        recorded = {
            row[0]
            for row in await session.execute(
                select(database.ServerDrop.drop_id).where(
                    database.ServerDrop.guild_id == guild_id
                )
            )
        }

    arrived = set()
    for drop_id, trigger, value in rows:
        if trigger == "date":
            if _has_date_arrived(value, today):
                arrived.add(drop_id)
        elif drop_id in recorded:
            arrived.add(drop_id)
    return arrived


async def record_arrival(guild_id: int, drop_id: int) -> bool:
    """Mark an event or manual drop as arrived. False if it already had.

    Permanent by design. This is the write that makes an arrival survive the
    condition that caused it going away again.
    """
    session_factory = database._require_session()
    async with session_factory() as session:
        known = await session.scalar(
            select(database.Drop.drop_id).where(database.Drop.drop_id == drop_id)
        )
        if known is None:
            raise UnknownDrop(f"No drop {drop_id} in the content files")

        already = await session.scalar(
            select(database.ServerDrop.drop_id).where(
                database.ServerDrop.guild_id == guild_id,
                database.ServerDrop.drop_id == drop_id,
            )
        )
        if already is not None:
            return False

        session.add(database.ServerDrop(guild_id=guild_id, drop_id=drop_id))
        await session.commit()

    log.info("Drop %s arrived in guild %s", drop_id, guild_id)
    return True


def _best(rows, arrived: set[int], state: str, column: str) -> str | None:
    """Pick the winning row: the player's state if it has one, else default.

    Within a state the highest arrived `since_drop` wins. Drops are numbered in
    the order their content should supersede, and because an event drop can
    arrive while a lower-numbered one has not, "highest arrived" is not the same
    as "highest" - which is why arrival is filtered before the maximum is taken.
    """
    for wanted in (state, DEFAULT_STATE) if state != DEFAULT_STATE else (DEFAULT_STATE,):
        candidates = [
            row
            for row in rows
            if row["state"] == wanted and row["since_drop"] in arrived and row[column]
        ]
        if candidates:
            return max(candidates, key=lambda row: row["since_drop"])[column]
    return None


async def room_look(
    guild_id: int, room_id: str, state: str = DEFAULT_STATE, *, today: date | None = None
) -> str | None:
    """The description of a room as this server currently sees it."""
    arrived = await arrived_drop_ids(guild_id, today=today)
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
    state: str = DEFAULT_STATE,
    *,
    today: date | None = None,
) -> str | None:
    """One column of a thing's text, resolved for state and arrived drops.

    Returns None when the content leaves the cell blank, which is the signal to
    fall through to the house default - see default_text.
    """
    if column not in database.ThingText.__table__.columns:
        raise ValueError(f"{column!r} is not a thing text column")

    arrived = await arrived_drop_ids(guild_id, today=today)
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


async def visible_thing_ids(guild_id: int, *, today: date | None = None) -> set[str]:
    """Things whose drop has arrived on this server.

    A thing from a later drop is loaded and inert: not placed, not listed, not
    resolvable. This is the gate the loader consults before placing anything.
    """
    arrived = await arrived_drop_ids(guild_id, today=today)
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(database.ThingType.thing_id, database.ThingType.since_drop)
            )
        ).all()
    return {thing_id for thing_id, since_drop in rows if since_drop in arrived}
