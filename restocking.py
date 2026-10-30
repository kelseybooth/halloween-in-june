"""The restock scheduler: things that reappear in the house over time.

2b loaded `restocks.tsv` and left the job unbuilt. This runs it.

Four rows exist today: two spice jars into the shipping box every two to ten
hours from the drop's second day, eight used baby bottles a day scattered
anywhere, two dirty diapers a day scattered the same way, and the channel's
toys. Between them that is ten objects a day accumulating in a house where
nothing removes them until a player takes one, which is why the `Also here:`
truncation shipped alongside.

**Day numbers count from each server's own initialization date**, in Pacific
time - deliberately the opposite of drops, which land on the same calendar day
everywhere.

**Except an interval row, which counts from its drop.** Drop 20 added
the other kind of schedule - a gap drawn at random after each delivery
rather than N times a day - and with it the question of what day one
means for a row that waits on a drop. The beta had been playing for a
month when drop 20 landed, so counting from the first `/enter` put the
spice order's day two four weeks in the past and one sweep would have
filled the box to its cap on the drop's opening day. See
`_drop_day_one`.

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
import telemetry

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
    # (guild, room, default key) for each delivery a room should be told
    # about. Only the shipping box has one today.
    announce: list[tuple[int, str, str]] = field(default_factory=list)
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


def interval_times(
    guild_id: int,
    restock_id: int,
    first_day_starts: datetime,
    until: datetime,
    min_hours: int,
    max_hours: int,
) -> list[datetime]:
    """Every delivery from `first_day_starts` up to `until`.

    **Derived, not rolled**, for the reason the per-day times are: the
    chain is seeded from (guild, restock) and asking twice gives the
    same answer, so a sweep cannot skip or double a delivery by
    re-deciding when it was due. Nothing is stored except the last one
    applied.

    The first delivery is drawn across the whole of the first day, not
    `min_hours` after midnight - "two jars arrive on the second day"
    should be able to mean the afternoon. Every one after it is a
    uniformly random gap in [min, max] from the one before.

    Bounded by the catch-up window on the caller's side: the walk stops
    at `until`, and `until` is never more than `MAX_CATCHUP_DAYS` past
    the start.
    """
    if min_hours is None or max_hours is None:
        return []
    low, high = min(min_hours, max_hours), max(min_hours, max_hours)
    rng = _seeded(guild_id, restock_id, 0)

    moment = first_day_starts + timedelta(hours=rng.uniform(0, 24))
    times = []
    # A ceiling on the walk as well as on the window, so a row written
    # with a zero-hour interval cannot spin: at the shortest sane gap
    # this is far more deliveries than any catch-up would place.
    for _ in range(MAX_CATCHUP_DAYS * 24 + 24):
        if moment > until:
            break
        times.append(moment)
        moment += timedelta(hours=rng.uniform(low, high) or 1)
    return times


async def _drop_day_one(guild_id: int, restock) -> date | None:
    """The Pacific date this row's drop arrived on this server.

    **Day one is the drop's, not the server's.** `first_day` used to
    count from the first `/enter`, which is right for a row that has
    been live since the house opened - and wrong for one that waits on
    a drop. The beta had been playing for weeks when drop 20 landed, so
    "day 2" was long past and the spice box would have filled to its
    cap of sixteen within one sweep, on the drop's first day, where the
    design has it empty.

    None when the server has not reached the drop, which the caller has
    already excluded, or when it has no pointer history to read.
    """
    arrived = await database.when_drop_arrived(guild_id, restock.since_drop)
    if arrived is None:
        return None
    return (
        arrived.replace(tzinfo=database.timezone.utc)
        .astimezone(database.PACIFIC)
        .date()
    )


async def _slots(guild_id: int) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """The scatter slots, and which room each container sits in.

    Nine rooms and twelve containers, drawn from uniformly - so a container is
    exactly as likely as a whole room, which is what the work order specifies.
    The map comes back too, because a `container` row needs to find its own
    container whether or not anything else is inside it.

    **A container with `scatter_target = no` is left out of the slots
    and kept in the map**, which is the whole distinction: a row that
    names the shipping box still delivers into it, and a row that picks
    a container at random never picks it. The box is the only one. Its
    contents are David's spice order arriving on a schedule, and a used
    baby bottle among them reads as a bug rather than as a joke.
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
    no_scatter: set[str] = set()
    async with session_factory() as session:
        for container_id, _ in containers:
            row = (
                await session.execute(
                    select(
                        database.ThingType.room_id, database.ThingType.scatter_target
                    ).where(database.ThingType.thing_id == container_id)
                )
            ).first()
            if row is None or not row[0]:
                continue
            by_container[container_id] = row[0]
            if not row[1]:
                no_scatter.add(container_id)

    slots = [(room, database.LOOSE_IN_ROOM) for room in rooms]
    slots += [
        (room, container)
        for container, room in sorted(by_container.items())
        if container not in no_scatter
    ]
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

    **Set by the first walk in through the front door, not by building the
    house.** An admin can initialize days before the game opens, and the
    calendar should start when somebody is actually inside to see it.
    Idempotent, so every later entry is a no-op and the first one wins.
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

    # Which drops this server has reached. Two things read it: which
    # rows may fire at all, and the class draw, which must never hand
    # out a toy from a drop that has not opened here.
    arrived = await resolve.arrived_drop_ids(guild_id)
    if not arrived:
        # Nothing has arrived, so nothing may be placed. An empty set is
        # a guild with no drop pointer - one the bot is merely a member
        # of - and the sweep visits every guild it is in, so without this
        # a server where nobody has ever run `/initialize-haunted-house`
        # accumulates ten scattered objects a day in rooms that do not
        # exist.
        return report

    # **Before placing, not after.** What this clears is the backlog a
    # scheduler that ignored drops left behind, and anything a future
    # one gets wrong; a row written by the loop below is this tick's
    # business and the next tick's to tidy if it was a mistake. Sweeping
    # afterwards would mean deleting rows we had just written, which
    # reads as a scatter rate rather than as a rule.
    swept = await database.clear_unreachable_room_contents(
        guild_id,
        arrived,
        await resolve.arrived_rooms(guild_id) | {content_module.CHANNEL_ROOM},
    )
    if swept:
        log.info(
            "Cleared %d unreachable row(s) from rooms in guild %s", swept, guild_id
        )

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
        if restock.since_drop not in arrived:
            # **The column the row has always carried, finally read.**
            # `restocks.tsv` has had `since_drop` since September; it was
            # parsed, validated and stored, and nothing ever looked at
            # it - so every row ran on every server from its first day.
            # Eight used baby bottles a day, which are drop 30 content,
            # were scattering through servers on drop 10: most vanished
            # into rooms that have not opened yet, and the rest sat in
            # the Entryway as objects no word reached, because the
            # parser was right that they are not here yet.
            continue

        last = progress.get(restock.restock_id)

        if restock.interval_min_hours is not None:
            # **An interval row keeps its own clock**, counted from the
            # drop rather than from the server's first day, and ignores
            # `times_per_day` - which is why the file calls that column
            # a placeholder on this row.
            day_one = await _drop_day_one(guild_id, restock)
            if day_one is None:
                continue
            opens = day_one + timedelta(days=max(restock.first_day, 1) - 1)
            floor = max(
                opens, today - timedelta(days=MAX_CATCHUP_DAYS)
            )
            begins, _ = database.pacific_day_bounds_utc(floor)
            due = [
                moment
                for moment in interval_times(
                    guild_id,
                    restock.restock_id,
                    begins,
                    now,
                    restock.interval_min_hours,
                    restock.interval_max_hours,
                )
                if last is None or moment > last
            ]
            if due:
                await _deliver(
                    guild_id, restock, due, slots, container_rooms, rng, arrived, report
                )
                await _record_progress(guild_id, restock.restock_id, max(due))
            continue

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

        await _deliver(
            guild_id, restock, due, slots, container_rooms, rng, arrived, report
        )
        await _record_progress(guild_id, restock.restock_id, max(due))

    if report.placed:
        report.guilds = 1
        log.info(
            "Restock placed %d thing(s) in guild %s", report.count, guild_id
        )
    return report


async def _deliver(
    guild_id: int, restock, due, slots, container_rooms, rng, arrived, report
) -> None:
    """Place one occurrence per moment in `due`.

    Shared by the two schedules - the per-day one and drop 20's
    interval one - because what a delivery *does* has nothing to do
    with how its time was worked out, and the cap, the class draw and
    the arrival notice are all easy to get subtly different twice.
    """
    for _ in sorted(due):
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

        amount = await _room_for(guild_id, room_id, container_id, restock)
        if amount < 1:
            # **Fill toward the cap, never past it.** A better rule
            # than a rate: a quiet server keeps two sitting there
            # and a busy one keeps getting fresh ones. The occurrence
            # is spent either way, so a full channel does not bank
            # placements and dump them when somebody takes one.
            continue

        await _place(guild_id, room_id, container_id, thing_id, amount)
        report.placed.append((guild_id, room_id, container_id, thing_id, amount))
        await telemetry.system(
            guild_id,
            telemetry.RESTOCK_PLACED,
            thing_id=thing_id,
            detail=(
                f"restock={restock.restock_id} room={room_id} "
                f"container={container_id or 'loose'} "
                f"added={amount} "
                f"now={await database.how_many_in_container(guild_id, room_id, container_id, thing_id)}"
            ),
        )
        if restock.arrival_notice:
            # The room hears the delivery land. Collected rather than
            # posted here: `restocking` has no Discord client, and the
            # sweep that calls it does.
            report.announce.append((guild_id, room_id, restock.arrival_notice))


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


async def _room_for(
    guild_id: int, room_id: str, container_id: str, restock
) -> int:
    """How many of this row's thing may be added here, at most `amount`.

    **The cap counts the class, not the row**, where the row names a
    class. The rule is *keep two toys in the channel*, and with
    thirteen toy rows written a per-row reading would allow twenty-six.

    **A row that names one thing is capped on that thing, where it
    lands.** That half was accepted by the loader and never read:
    `max_present` returned early for anything but a class, so the spice
    order's cap of sixteen did nothing and a month-long catch-up filled
    the shipping box to ninety-six. Drop 20 is the first row to depend
    on it.

    **A count rather than a yes or no**, so "fill toward sixteen and
    never exceed it" is exact. The jars arrive two at a time; asking
    "is there room for more" and then placing two put seventeen in a
    box with one space left.

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
        return restock.amount
    cap = restock.max_present
    if restock.config_key:
        # The key means the cap on a row that has one - see
        # `_times_per_day` for the other half of that rule.
        cap = await database.get_setting(guild_id, restock.config_key) or cap

    if restock.thing_id.startswith(content_module.CLASS_PREFIX):
        kind = restock.thing_id[len(content_module.CLASS_PREFIX):]
        present = await database.count_of_type(guild_id, room_id, kind)
    else:
        present = await database.how_many_in_container(
            guild_id, room_id, container_id, restock.thing_id
        )
    return max(0, min(restock.amount, cap - present))


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
        combined.announce.extend(report.announce)
    combined.guilds = len({row[0] for row in combined.placed})
    return combined
