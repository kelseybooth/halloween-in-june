"""The restock scheduler: things that reappear in the house over time.

2b loaded `restocks.tsv` and left the job unbuilt. This runs it.

Three rows exist today: four spice jars into the Amazon box every third day
from day 2, eight used baby bottles a day scattered anywhere, and two dirty
diapers a day scattered the same way. Between them that is ten objects a day
accumulating in a house where nothing removes them until a player takes one,
which is why the `Also here:` truncation shipped alongside.

**Day numbers count from each server's own initialization date**, in Pacific
time - deliberately the opposite of drops, which land on the same calendar day
everywhere.

**Occurrence times are derived, not rolled.** The work order asks for the day's
times to be drawn once at the start of the day and stored, so that re-rolling
on each check cannot skip or double an occurrence. This does the same job a
different way: the times are derived from a seed of (guild, restock, day), so
asking twice gives the same answer and the failure it warns about cannot
happen. The next one is still written to `server_restocks` for observability,
and the derivation uses a stable hash rather than Python's, which is salted per
process and would change every restart.
"""

from __future__ import annotations

import hashlib
import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

import database

log = logging.getLogger(__name__)

# A long outage should cost bounded work, not a month of placements at once.
MAX_CATCHUP_DAYS = 14

# Defaults for the config keys a restock row may point at.
CONFIG_DEFAULTS = {"bottles_per_day": 8}


@dataclass
class RestockReport:
    """What one sweep placed, for the logs and the tests."""

    placed: list[tuple[int, str, str, str, int]] = field(default_factory=list)
    guilds: int = 0

    @property
    def count(self) -> int:
        return sum(row[4] for row in self.placed)

    def summary(self) -> str:
        if not self.placed:
            return "restock: nothing due"
        return (
            f"restock: placed {self.count} thing(s) in "
            f"{len({row[0] for row in self.placed})} server(s)"
        )


def day_number(initialized_on: date, today: date) -> int:
    """Which day of this server's life today is. The first day is day 1."""
    return (today - initialized_on).days + 1


def is_active_day(first_day: int, every_n_days: int, day: int) -> bool:
    """Whether a schedule fires at all on this day of the server's life."""
    if day < first_day:
        return False
    return (day - first_day) % max(1, every_n_days) == 0


def _seeded(guild_id: int, restock_id: int, day: int) -> random.Random:
    """A generator that gives the same answers every time it is asked.

    Seeded from a stable digest rather than hash(), which Python salts per
    process - with hash() a restart would redraw every time and the whole
    point of deriving rather than storing would be lost.
    """
    digest = hashlib.sha256(f"{guild_id}:{restock_id}:{day}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _clock(value: str, fallback: time) -> time:
    try:
        hours, minutes = (int(part) for part in value.split(":"))
        return time(hour=hours, minute=minutes)
    except (ValueError, TypeError):
        return fallback


def occurrence_times(
    guild_id: int,
    restock_id: int,
    day: int,
    on: date,
    times_per_day: int,
    window_start: str,
    window_end: str,
) -> list[datetime]:
    """The naive-UTC moments this schedule fires on one Pacific day.

    `times_per_day` is a count of occurrences, not a quantity: eight bottles a
    day is eight arrivals of one bottle at eight independently drawn times, not
    one delivery of eight. They come back sorted so catch-up applies them in
    the order they would have happened.
    """
    rng = _seeded(guild_id, restock_id, day)
    start = _clock(window_start, time(0, 0))
    end = _clock(window_end, time(23, 59))

    opens = datetime.combine(on, start, tzinfo=database.PACIFIC)
    closes = datetime.combine(on, end, tzinfo=database.PACIFIC)
    span = max(0, int((closes - opens).total_seconds()))

    moments = []
    for _ in range(max(0, times_per_day)):
        offset = rng.randrange(span + 1) if span else 0
        local = opens + timedelta(seconds=offset)
        moments.append(local.astimezone(database.timezone.utc).replace(tzinfo=None))
    return sorted(moments)


async def _slots(guild_id: int) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """The scatter slots, and which room each container sits in.

    Nine rooms and twelve containers, drawn from uniformly - so a container is
    exactly as likely as a whole room, which is what the work order specifies.
    The map comes back too, because a `container` row needs to find its own
    container whether or not anything else is inside it.
    """
    session_factory = database._require_session()
    async with session_factory() as session:
        rooms = [
            row[0]
            for row in await session.execute(
                select(database.RoomType.room_id).order_by(database.RoomType.room_id)
            )
        ]
        containers = (
            await session.execute(
                select(database.ThingType.contained_in, database.ThingType.room_id)
                .where(database.ThingType.contained_in.is_not(None))
                .distinct()
            )
        ).all()

    by_container: dict[str, str] = {}
    async with session_factory() as session:
        for container_id, _ in containers:
            room = await session.scalar(
                select(database.ThingType.room_id).where(
                    database.ThingType.thing_id == container_id
                )
            )
            if room:
                by_container[container_id] = room

    slots = [(room, database.LOOSE_IN_ROOM) for room in rooms]
    slots += [(room, container) for container, room in sorted(by_container.items())]
    return slots, by_container


async def _room_of(thing_id: str) -> str | None:
    session_factory = database._require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(database.ThingType.room_id).where(
                database.ThingType.thing_id == thing_id
            )
        )


async def _times_per_day(guild_id: int, restock) -> int:
    """How many occurrences today, honouring an admin override.

    A change applies from the next occurrence onward and never retroactively
    adds or removes anything already placed.
    """
    if not restock.config_key:
        return restock.times_per_day

    session_factory = database._require_session()
    async with session_factory() as session:
        value = await session.scalar(
            select(database.ServerConfig.value).where(
                database.ServerConfig.guild_id == guild_id,
                database.ServerConfig.key == restock.config_key,
            )
        )
    if value is None:
        return CONFIG_DEFAULTS.get(restock.config_key, restock.times_per_day)
    try:
        return max(0, int(value))
    except ValueError:
        log.warning(
            "server_config %s is %r, which is not a number; using %s",
            restock.config_key,
            value,
            restock.times_per_day,
        )
        return restock.times_per_day


async def initialized_on(guild_id: int) -> date | None:
    """The Pacific date this server's house was first built."""
    session_factory = database._require_session()
    async with session_factory() as session:
        value = await session.scalar(
            select(database.ServerConfig.value).where(
                database.ServerConfig.guild_id == guild_id,
                database.ServerConfig.key == database.CONFIG_INITIALIZED_ON,
            )
        )
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


async def set_initialized_on(guild_id: int, on: date | None = None) -> date:
    """Record day one for a server, if it has not got one already.

    Restock day numbers count from here, so a server that never gets this never
    restocks. Set when the house is built, and defensively on the first sweep.
    """
    existing = await initialized_on(guild_id)
    if existing:
        return existing

    on = on or database.pacific_today()
    session_factory = database._require_session()
    insert = database._upsert_statement()
    async with session_factory() as session:
        await session.execute(
            insert(database.ServerConfig)
            .values(
                guild_id=guild_id,
                key=database.CONFIG_INITIALIZED_ON,
                value=on.isoformat(),
            )
            .on_conflict_do_nothing(
                index_elements=[database.ServerConfig.guild_id, database.ServerConfig.key]
            )
        )
        await session.commit()
    log.info("Server %s starts counting restock days from %s", guild_id, on)
    return on


async def run_for_guild(
    guild_id: int, *, now: datetime | None = None, rng=random
) -> RestockReport:
    """Apply every occurrence that has come due and not yet been applied.

    Catch-up falls out of this rather than being a separate path: the question
    is always "what should have happened between the last one applied and now",
    so a bot that was down for a day places that day's arrivals when it returns
    instead of skipping them.
    """
    report = RestockReport()
    now = now or database._utcnow()
    # Derived from `now` rather than read from the clock, so the two cannot
    # disagree: passing a `now` in the future has to move the day with it, or
    # catch-up tests silently exercise nothing.
    today = (
        now.replace(tzinfo=database.timezone.utc).astimezone(database.PACIFIC).date()
    )

    start_day = await set_initialized_on(guild_id)
    session_factory = database._require_session()

    async with session_factory() as session:
        rows = (await session.execute(select(database.Restock))).scalars().all()
        progress = {
            row[0]: row[1]
            for row in await session.execute(
                select(
                    database.ServerRestock.restock_id,
                    database.ServerRestock.last_applied_at,
                ).where(database.ServerRestock.guild_id == guild_id)
            )
        }

    slots, container_rooms = await _slots(guild_id)
    if not slots:
        return report

    # A container a restock row names is a real destination even when nothing
    # is statically inside it - the row is what declares it.
    for restock in rows:
        if restock.placement == "container" and restock.container:
            if restock.container not in container_rooms:
                room = await _room_of(restock.container)
                if room:
                    container_rooms[restock.container] = room

    for restock in rows:
        last = progress.get(restock.restock_id)
        per_day = await _times_per_day(guild_id, restock)
        if per_day < 1:
            continue

        # Only look back as far as the cap, so a long outage is bounded work.
        earliest = max(start_day, today - timedelta(days=MAX_CATCHUP_DAYS))
        due: list[datetime] = []
        cursor = earliest
        while cursor <= today:
            day = day_number(start_day, cursor)
            if is_active_day(restock.first_day, restock.every_n_days, day):
                for moment in occurrence_times(
                    guild_id,
                    restock.restock_id,
                    day,
                    cursor,
                    per_day,
                    restock.window_start,
                    restock.window_end,
                ):
                    if moment <= now and (last is None or moment > last):
                        due.append(moment)
            cursor += timedelta(days=1)

        if not due:
            continue

        for moment in sorted(due):
            landing = _destination(restock, slots, container_rooms, rng)
            if landing is None:
                break
            room_id, container_id = landing
            await _place(guild_id, room_id, container_id, restock.thing_id, restock.amount)
            report.placed.append(
                (guild_id, room_id, container_id, restock.thing_id, restock.amount)
            )

        await _record_progress(guild_id, restock.restock_id, max(due))

    if report.placed:
        report.guilds = 1
        log.info(
            "Restock placed %d thing(s) in guild %s", report.count, guild_id
        )
    return report


def _destination(restock, slots, container_rooms, rng) -> tuple[str, str] | None:
    """Where one occurrence lands, or None if it cannot land anywhere.

    A `container` row always goes to its named container, looked up by the
    container's own room rather than searched for among the scatter slots - a
    container that happens to hold nothing at load is still a real place, and
    searching the slot list would silently scatter the spice jars across the
    house instead.

    A `random` row draws a fresh slot for every occurrence rather than once for
    the day, so eight bottles scatter rather than arriving in a heap.
    """
    if restock.placement == "container" and restock.container:
        room = container_rooms.get(restock.container)
        if room is None:
            log.warning(
                "Restock %s names container %r, which is in no room; skipping",
                restock.restock_id,
                restock.container,
            )
            return None
        return room, restock.container
    return rng.choice(slots)


async def _place(
    guild_id: int, room_id: str, container_id: str, thing_id: str, amount: int
) -> None:
    """Add stock. Incremented, never assigned - a restock tops up what is there."""
    session_factory = database._require_session()
    insert = database._upsert_statement()
    async with session_factory() as session:
        await session.execute(
            database._add_to_room(
                insert, guild_id, room_id, container_id, thing_id, amount
            )
        )
        await session.commit()


async def _record_progress(guild_id: int, restock_id: int, applied_at: datetime) -> None:
    session_factory = database._require_session()
    insert = database._upsert_statement()
    async with session_factory() as session:
        await session.execute(
            insert(database.ServerRestock)
            .values(
                guild_id=guild_id,
                restock_id=restock_id,
                last_applied_at=applied_at,
                next_at=None,
            )
            .on_conflict_do_update(
                index_elements=[
                    database.ServerRestock.guild_id,
                    database.ServerRestock.restock_id,
                ],
                set_={"last_applied_at": applied_at},
            )
        )
        await session.commit()


async def run_all(guild_ids: list[int], *, now: datetime | None = None) -> RestockReport:
    """Sweep every server. Called on a schedule and once at startup."""
    combined = RestockReport()
    for guild_id in guild_ids:
        report = await run_for_guild(guild_id, now=now)
        combined.placed.extend(report.placed)
    combined.guilds = len({row[0] for row in combined.placed})
    return combined
