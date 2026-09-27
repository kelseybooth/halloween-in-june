"""Putting the content files into the database.

`content.py` reads and checks the files; this puts them in a database and places
what needs placing. The two are separate so that checking does not require a
database, and so that this can refuse to write a single row until the whole set
is known good - a half-loaded house is worse than a stale one.

The load is in two halves, and they behave completely differently.

**Content is global and replaced wholesale.** Rooms, things, their text, the
defaults, the drop calendar and the restock schedules are the same in every
server and are never mutated at runtime, so replacing them cannot destroy
anything a player did.

**World state is per guild and is left alone.** The loader touches it exactly
once per thing: the first time a server sees it, to put it where the files say
it starts. After that the room belongs to the players. If somebody took the
nacho chips, a reload must not put them back on the counter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import delete, select

import content as content_module
import database
import resolve
from content import Content

log = logging.getLogger(__name__)

# World-state tables cleared by --fresh, children before parents so the foreign
# keys hold. server_config goes too: it carries the date restock day numbers
# count from, and a fresh world has to restart that clock.
_WORLD_TABLES = (
    "player_inventory",
    "room_contents",
    "player_states",
    "server_states",
    "thing_uses",
    "server_drops",
    "server_restocks",
    "server_config",
)


class OrphanedThings(Exception):
    """The files dropped a thing that world state still refers to.

    Loud beats silent. The alternative is an inventory pointing at a thing that
    no longer exists and a `/inventory` that renders blanks, which surfaces as a
    player bug days later rather than as a failed load now.
    """

    def __init__(self, held: dict[str, list[int]], in_rooms: dict[str, list[str]]) -> None:
        self.held = held
        self.in_rooms = in_rooms
        lines = []
        for thing_id, holders in sorted(held.items()):
            who = ", ".join(str(h) for h in sorted(holders))
            lines.append(f"  - {thing_id} is carried by {len(holders)} player(s): {who}")
        for thing_id, rooms in sorted(in_rooms.items()):
            lines.append(f"  - {thing_id} is in {', '.join(sorted(rooms))}")
        super().__init__(
            "These things are gone from the content files but world state still "
            "refers to them:\n"
            + "\n".join(lines)
            + "\n\nRestore them, or re-run with --allow-orphans to load anyway."
        )


@dataclass
class LoadReport:
    """What one load did, for the CLI to print and the tests to assert on."""

    content_rows: dict[str, int] = field(default_factory=dict)
    guilds: list[int] = field(default_factory=list)
    placed: int = 0
    already_present: int = 0
    waiting_on_drops: int = 0
    orphans_ignored: list[str] = field(default_factory=list)
    fresh: bool = False

    def summary(self) -> str:
        counts = ", ".join(f"{n} {name}" for name, n in sorted(self.content_rows.items()))
        lines = [f"content: {counts}"]
        if self.fresh:
            lines.append("world state: wiped (--fresh)")
        if self.guilds:
            line = (
                f"placed {self.placed} thing(s) across {len(self.guilds)} server(s); "
                f"{self.already_present} already present and left alone"
            )
            if self.waiting_on_drops:
                line += f"; {self.waiting_on_drops} waiting on a later drop"
            lines.append(line)
        else:
            lines.append("no servers in the database yet; nothing to place")
        if self.orphans_ignored:
            lines.append(
                f"ignored {len(self.orphans_ignored)} orphaned thing(s): "
                + ", ".join(sorted(self.orphans_ignored))
            )
        return "\n".join(lines)


def _rows_for(parsed: Content) -> dict[str, list[dict]]:
    """Every content table's rows, keyed by table name, ready to insert."""
    return {
        "room_types": [
            {
                "room_id": r.room_id,
                "name": r.name,
                "sort_order": r.sort_order,
                "open_at_launch": r.open_at_launch,
            }
            for r in parsed.rooms
        ],
        "thing_types": [
            {
                "thing_id": t.thing_id,
                "name": t.name,
                "aliases": list(t.aliases),
                "type": t.type,
                "room_id": t.room_id,
                "quantity": t.quantity,
                "takeable": t.takeable,
                "droppable": t.droppable,
                "cross_weight": t.cross_weight,
                "max_per_player": t.max_per_player,
                "requires": t.requires,
                "present_when": t.present_when,
                "transforms_to": t.transforms_to,
                "transform_room": t.transform_room,
                "yields": t.yields,
                "destination_room_id": t.destination_room_id,
                "contained_in": t.contained_in,
                "use_cooldown_hours": t.use_cooldown_hours,
                "since_drop": t.since_drop,
                "sort_order": t.sort_order,
            }
            for t in parsed.things
        ],
        "room_text": [
            {
                "room_id": r.entity_id,
                "state": r.state,
                "since_drop": r.since_drop,
                "look": r.text.get("look"),
            }
            for r in parsed.room_text
        ],
        "thing_text": [
            {
                "thing_id": r.entity_id,
                "state": r.state,
                "since_drop": r.since_drop,
                **{column: r.text.get(column) for column in content_module.THING_TEXT_COLUMNS},
            }
            for r in parsed.thing_text
        ],
        "defaults": [{"key": k, "text": v} for k, v in parsed.defaults.items()],
        "drops": [
            {
                "drop_id": d.drop_id,
                "trigger": d.trigger,
                "date": d.date,
                "event": d.event,
                "name": d.name,
                "notes": d.notes,
            }
            for d in parsed.drops
        ],
        "emoji_groups": [
            {"emoji": e.emoji, "subgroup": e.subgroup, "drawable": e.drawable}
            for e in parsed.emoji_groups
        ],
        "restocks": [
            {
                "restock_id": r.restock_id,
                "thing_id": r.thing_id,
                "placement": r.placement,
                "container": r.container,
                "amount": r.amount,
                "times_per_day": r.times_per_day,
                "first_day": r.first_day,
                "every_n_days": r.every_n_days,
                "window_start": r.window_start,
                "window_end": r.window_end,
                "config_key": r.config_key,
                "since_drop": r.since_drop,
                "notes": r.notes,
            }
            for r in parsed.restocks
        ],
    }


def things_to_place(parsed: Content) -> list[tuple[str, str, str, int, int]]:
    """(room_id, container_id, thing_id, count, since_drop) for placeable things.

    Only finite objects. A source is inexhaustible and is not stock, a fixture is
    scenery, and an exit is a door - none of them move, so none belong in
    room_contents. Anything roomless starts nowhere: it arrives when a source
    yields it, something transforms into it, or a restock scatters it.

    `since_drop` rides along because whether a thing may be placed *yet* depends
    on the server, not on the file - see _arrived_drops.
    """
    placements = []
    for thing in parsed.things:
        if thing.type != "object" or not thing.room_id:
            continue
        if thing.quantity in (None, 0):
            continue
        placements.append(
            (
                thing.room_id,
                thing.contained_in or database.LOOSE_IN_ROOM,
                thing.thing_id,
                thing.quantity,
                thing.since_drop,
            )
        )
    return placements


async def _arrived_drops(session, guild_id: int, parsed: Content, today) -> set[int]:
    """Which drops have arrived on this server, judged from the files in hand.

    Deliberately not resolve.arrived_drop_ids: that reads the drops table, which
    this transaction has just rewritten and not yet committed. The parsed
    calendar is the same data and is already here.
    """
    recorded = {
        row[0]
        for row in await session.execute(
            select(database.ServerDrop.drop_id).where(
                database.ServerDrop.guild_id == guild_id
            )
        )
    }
    arrived = set()
    for drop in parsed.drops:
        if drop.trigger == "date":
            if resolve._has_date_arrived(drop.date, today):
                arrived.add(drop.drop_id)
        elif drop.drop_id in recorded:
            arrived.add(drop.drop_id)
    return arrived


async def _known_guilds(session) -> list[int]:
    """Every guild the database has seen, whether or not anyone has played."""
    rows = await session.execute(select(database.User.guild_id).distinct())
    return sorted({row[0] for row in rows})


async def _find_orphans(session, known_ids: set[str]):
    """World state pointing at things the files no longer define."""
    held: dict[str, list[int]] = {}
    rows = await session.execute(
        select(database.PlayerInventory.thing_id, database.PlayerInventory.user_id).where(
            database.PlayerInventory.count > 0
        )
    )
    for thing_id, user_id in rows:
        if thing_id not in known_ids:
            held.setdefault(thing_id, []).append(user_id)

    in_rooms: dict[str, list[str]] = {}
    rows = await session.execute(
        select(database.RoomContents.thing_id, database.RoomContents.room_id).where(
            database.RoomContents.count > 0
        )
    )
    for thing_id, room_id in rows:
        if thing_id not in known_ids:
            in_rooms.setdefault(thing_id, []).append(room_id)

    return held, in_rooms


async def _wipe_world_state(session) -> None:
    for table in _WORLD_TABLES:
        await session.execute(database.Base.metadata.tables[table].delete())


async def _replace_content(session, rows: dict[str, list[dict]]) -> dict[str, int]:
    """Delete and rewrite every content table.

    Safe precisely because nothing mutates these at runtime: there is no player
    state here to lose. Children are cleared before parents so a foreign key
    added later does not turn this into a puzzle.
    """
    counts = {}
    order = (
        "thing_text",
        "room_text",
        "restocks",
        "thing_types",
        "room_types",
        "drops",
        "defaults",
        "emoji_groups",
    )
    for table in order:
        await session.execute(database.Base.metadata.tables[table].delete())
    for table in reversed(order):
        payload = rows[table]
        if payload:
            await session.execute(database.Base.metadata.tables[table].insert(), payload)
        counts[table] = len(payload)
    return counts


async def _place_for_guild(
    session, guild_id: int, placements, arrived: set[int]
) -> tuple[int, int, int]:
    """Put a server's starting stock in place, once and only once per thing.

    "Once" is judged per thing rather than per server, so a thing added to the
    files later reaches a server that has been running for weeks. A thing this
    server already knows - still in a room, in somebody's bag, or taken and its
    row left at zero - is left exactly as it is.

    A thing whose drop has not arrived here is skipped rather than placed. Since
    placement is judged per thing and the loader runs on every boot, it lands by
    itself on the first start after the drop comes due - no migration, no deploy.
    """
    seen_in_rooms = await session.execute(
        select(database.RoomContents.thing_id).where(database.RoomContents.guild_id == guild_id)
    )
    seen_in_bags = await session.execute(
        select(database.PlayerInventory.thing_id).where(
            database.PlayerInventory.guild_id == guild_id
        )
    )
    known = {row[0] for row in seen_in_rooms} | {row[0] for row in seen_in_bags}

    placed = skipped = waiting = 0
    for room_id, container_id, thing_id, count, since_drop in placements:
        if thing_id in known:
            skipped += 1
            continue
        if since_drop not in arrived:
            waiting += 1
            continue
        session.add(
            database.RoomContents(
                guild_id=guild_id,
                room_id=room_id,
                container_id=container_id,
                thing_id=thing_id,
                count=count,
            )
        )
        known.add(thing_id)
        placed += 1
    return placed, skipped, waiting


async def load_content(
    parsed: Content | None = None,
    *,
    guild_ids: list[int] | None = None,
    allow_orphans: bool = False,
    fresh: bool = False,
) -> LoadReport:
    """Load the content files into the database. One transaction, all or nothing.

    `parsed` defaults to reading and validating the files, which raises
    ContentError listing everything wrong rather than writing a partial house.
    `guild_ids` defaults to every server the database has seen.

    Raises OrphanedThings if world state refers to a thing the files no longer
    define, unless `allow_orphans`. With `fresh`, world state is wiped first and
    everything is placed again - the testing path, and the migration path while
    production holds only test data.
    """
    if parsed is None:
        parsed = content_module.load()

    report = LoadReport(fresh=fresh)
    placements = things_to_place(parsed)
    known_ids = {t.thing_id for t in parsed.things}

    session_factory = database._require_session()
    async with session_factory() as session:
        if fresh:
            await _wipe_world_state(session)
        else:
            held, in_rooms = await _find_orphans(session, known_ids)
            if held or in_rooms:
                if not allow_orphans:
                    raise OrphanedThings(held, in_rooms)
                report.orphans_ignored = sorted(set(held) | set(in_rooms))
                log.warning(
                    "Loading with %d orphaned thing(s): %s",
                    len(report.orphans_ignored),
                    ", ".join(report.orphans_ignored),
                )

        report.content_rows = await _replace_content(session, _rows_for(parsed))

        guilds = guild_ids if guild_ids is not None else await _known_guilds(session)
        report.guilds = list(guilds)
        today = database.pacific_today()
        for guild_id in guilds:
            arrived = await _arrived_drops(session, guild_id, parsed, today)
            placed, skipped, waiting = await _place_for_guild(
                session, guild_id, placements, arrived
            )
            report.placed += placed
            report.already_present += skipped
            report.waiting_on_drops += waiting

        await session.commit()

    log.info(
        "Content loaded: %s row(s) across %d table(s); placed %d thing(s) in %d server(s)",
        sum(report.content_rows.values()),
        len(report.content_rows),
        report.placed,
        len(report.guilds),
    )
    return report
