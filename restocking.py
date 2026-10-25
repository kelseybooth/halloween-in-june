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

import content as content_module
import database
import resolve

log = logging.getLogger(__name__)

# A long outage should cost bounded work, not a month of placements at once.
MAX_CATCHUP_DAYS = 14

# Defaults live in database.CONFIG_KEYS, which is also what /admin_config
# validates against - one list, so a key cannot be settable but unread, or
# read with a different default than the command reports.
CONFIG_DEFAULTS = {key: default for key, (default, _) in database.CONFIG_KEYS.items()}


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

    **`config_key` names the one number its row is about**, and which
    number that is depends on the row. A scatter row - eight bottles a
    day, with no cap - is defined by its rate, so the key tunes the
    rate. A top-up row - fill the channel toward two toys - is defined
    by the ceiling, so the key tunes that instead and the rate stays
    the row's own. Without the split, registering `toys_present` would
    have set both at once: two would have halved the top-up frequency
    as well, and four would have doubled the toys.
    """
    if not restock.config_key or restock.max_present is not None:
        return restock.times_per_day
    if restock.config_key not in database.CONFIG_KEYS:
        log.warning(
            "Restock %s points at unknown config key %r; using its own %s",
            restock.restock_id,
            restock.config_key,
            restock.times_per_day,
        )
        return restock.times_per_day
    return max(0, await database.get_setting(guild_id, restock.config_key))


async def initialized_on(guild_id: int) -> date | None:
    """The Pacific date this server's house was first built."""
    session_factory = database._require_session()
    async with session_factory() as session:
        value = await session.scalar(
            select(database.ConfigHistory.value).where(
                database.ConfigHistory.guild_id == guild_id,
                database.ConfigHistory.key == database.CONFIG_INITIALIZED_ON,
                database.ConfigHistory.effective_to.is_(None),
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

    Restock day numbers and the drop calendar both count from here, so a
    server that never gets this never restocks.

    **Set by the first `/enter`, not by building the house.** An admin can
    initialize days before the game opens, and the calendar should start when
    somebody is actually inside to see it. Idempotent, so every later `/enter`
    is a no-op and the first one wins.
    """
    existing = await initialized_on(guild_id)
    if existing:
        return existing

    on = on or await database.server_today(guild_id)
    await database.set_config(guild_id, database.CONFIG_INITIALIZED_ON, on.isoformat())
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
    now = now or await database.server_now(guild_id)
    # Derived from `now` rather than read from the clock, so the two cannot
    # disagree: passing a `now` in the future has to move the day with it, or
    # catch-up tests silently exercise nothing.
    today = (
        now.replace(tzinfo=database.timezone.utc).astimezone(database.PACIFIC).date()
    )

    # Read, never create. Day one is the day the first player walked in, and
    # the sweep runs against every guild the bot is in - including ones where
    # the house has been built and nobody has entered yet. Setting it here
    # would start the calendar at boot and put spice jars in the Amazon box
    # before anyone could find them.
    # **A row that fires every day needs no calendar.** Day one is set
    # by the first `/enter`, which is a drop-3 command, so before the
    # house opens this used to return empty and the toy row in the
    # channel never fired at all - drop 2 had the two toys its content
    # rows placed on arrival and nothing after them.
    #
    # Falling back to today keeps drop 3's intent exactly. A row that
    # counts days - the spice jars arrive on day 2 and every third day
    # after - sees day 1 again every day and stays put, which is right:
    # they are in a box in a house nobody can reach. Once somebody
    # walks in, the real origin takes over and they count from it.
    start_day = await initialized_on(guild_id) or await database.server_today(guild_id)

    # Which drops this server has reached, for the class draw: a
    # selector must never hand out a toy from a drop that has not
    # opened here.
    arrived = await resolve.arrived_drop_ids(guild_id)

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
        if restock.placement == "container" and restock.destination:
            if restock.destination not in container_rooms:
                room = await _room_of(restock.destination)
                if room:
                    container_rooms[restock.destination] = room

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

            thing_id = await _what_to_place(restock, arrived, rng)
            if thing_id is None:
                # A class with nothing arrived in it yet. Not an error -
                # the toys' row is live from drop 2 and the schedule
                # simply has nothing to draw until then.
                continue

            if not await _room_for_more(guild_id, room_id, restock):
                # **Fill toward the cap, never past it.** A better rule
                # than a rate: a quiet server keeps two sitting there
                # and a busy one keeps getting fresh ones. The occurrence
                # is spent either way, so a full channel does not bank
                # placements and dump them when somebody takes one.
                continue

            await _place(guild_id, room_id, container_id, thing_id, restock.amount)
            report.placed.append(
                (guild_id, room_id, container_id, thing_id, restock.amount)
            )

        await _record_progress(guild_id, restock.restock_id, max(due))

    if report.placed:
        report.guilds = 1
        log.info(
            "Restock placed %d thing(s) in guild %s", report.count, guild_id
        )
    return report


async def _what_to_place(restock, arrived: set[int], rng) -> str | None:
    """Which thing this occurrence places.

    Usually the row's own `thing_id`. A row whose `thing_id` is a class
    selector - `type:toy` - draws uniformly among the things of that
    type whose drop has arrived, so one row keeps the channel stocked
    with either toy and a thirteenth needs no restock change.

    Drawn per occurrence rather than per day, like the scatter slots, so
    four toys in a day are four separate coin flips.
    """
    if not restock.thing_id.startswith(content_module.CLASS_PREFIX):
        return restock.thing_id
    kind = restock.thing_id[len(content_module.CLASS_PREFIX):]
    pool = await database.ids_of_type(kind, arrived)
    return rng.choice(pool) if pool else None


async def _room_for_more(guild_id: int, room_id: str, restock) -> bool:
    """Whether the cap leaves room for one more.

    **The cap counts the class, not the row.** The rule is *keep two
    toys in the channel*, and with thirteen toy rows written a per-row
    reading would allow twenty-six.

    **It is read from `server_config`, not from the row**, so a server
    can be retuned without a deploy and two rows drawing from the same
    class cannot disagree about the limit. The row's `max_present` is
    the seed for that setting and the fallback if it is unset.

    **Player placement is exempt**, and gets that for free by not
    coming through here: `/drop` and the bed stash write straight to
    the room. The cap governs the scheduler, not the world - somebody
    who puts a third toy down has put a third toy there, and nothing
    should tidy it away.
    """
    if restock.max_present is None:
        return True
    kind = (
        restock.thing_id[len(content_module.CLASS_PREFIX):]
        if restock.thing_id.startswith(content_module.CLASS_PREFIX)
        else None
    )
    if kind is None:
        return True
    cap = restock.max_present
    if restock.config_key:
        # The key means the cap on a row that has one - see
        # `_times_per_day` for the other half of that rule.
        cap = await database.get_setting(guild_id, restock.config_key) or cap
    return await database.count_of_type(guild_id, room_id, kind) < cap


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
    if restock.placement == "container" and restock.destination:
        room = container_rooms.get(restock.destination)
        if room is None:
            log.warning(
                "Restock %s names container %r, which is in no room; skipping",
                restock.restock_id,
                restock.destination,
            )
            return None
        return room, restock.destination
    if restock.placement == "room" and restock.destination:
        # One named room, loose on its floor. The channel is the only
        # one today, and the reason this placement exists: neither
        # `container` nor `random` can say "into that room".
        return restock.destination, database.LOOSE_IN_ROOM
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
