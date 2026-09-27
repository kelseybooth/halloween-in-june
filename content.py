"""Reading and validating the content files.

The house is content, not code. Nine rooms, twenty exits and every object come
out of five tab-separated files in `creative content/`, which writers edit
directly. This module parses them and checks them; `content_loader.py` is what
puts them in a database.

Parsing and validation are deliberately separate from the database. A writer can
be told their file is wrong without a database existing, CI can check the shipped
content on every push, and the loader can refuse to write a single row until the
whole set is known good - a half-loaded house is worse than a stale one.
"""

from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# Where the files live, relative to the repository root.
CONTENT_DIR = Path(__file__).resolve().parent / "creative content"

FILES = {
    "rooms": "rooms.tsv",
    "room_text": "room_text.tsv",
    "things": "things.tsv",
    "thing_text": "thing_text.tsv",
    "defaults": "defaults.tsv",
    "drops": "drops.tsv",
    "restocks": "restocks.tsv",
    "emoji_groups": "emoji_groups.tsv",
}

# How a drop arrives. `date` is answered by the calendar every time it is asked and
# stores nothing; `event` and `manual` are recorded per guild the first time they
# fire, because a condition that stops being true must not un-ship content.
DROP_TRIGGERS = {"date", "event", "manual"}

# A `date` drop whose date is this arrives the moment a server initializes.
LAUNCH = "launch"

# Conditions an `event` drop may name. Release 1 ships none; the registry exists so
# the second one needs no migration, and so a typo in the file is caught at load
# rather than becoming a drop that never arrives.
KNOWN_DROP_EVENTS: set[str] = set()

# The Unicode subgroup holding plates, chopsticks and the like. It is inside the
# Food & Drink group but is not food, so nothing in it can be the craving. Note
# the name: it is `dishware`, not `food-dishware`, and guessing wrong makes every
# plate drawable without failing anything.
DISHWARE_SUBGROUP = "dishware"

# Where a restock puts what it adds. `container` names one; `random` draws a slot
# from every room and every container at equal probability.
RESTOCK_PLACEMENTS = {"container", "random"}

# The four kinds of thing. `exit` moves a player; `source` is an inexhaustible
# supply that yields objects; `object` can be carried; `fixture` is scenery that
# exists so `/look` works on anything the prose mentions.
THING_TYPES = {"object", "fixture", "exit", "source"}

# A room_id every server has, used by things that exist everywhere (the Alexa).
EVERYWHERE = "ALL"

# Text columns, in the order a resolver falls back through them.
THING_TEXT_COLUMNS = (
    "look",
    "look_carried",
    "use",
    "take",
    "drop",
    "use_fail",
    "take_fail",
    "drop_fail",
)


class ContentError(Exception):
    """The content files are not loadable. Carries every problem, not just the first."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        count = len(problems)
        listed = "\n".join(f"  - {p}" for p in problems)
        super().__init__(f"{count} problem(s) in the content files:\n{listed}")


@dataclass(frozen=True)
class Room:
    room_id: str
    name: str
    sort_order: int
    open_at_launch: bool


@dataclass(frozen=True)
class Thing:
    thing_id: str
    name: str
    aliases: tuple[str, ...]
    type: str
    room_id: str | None
    quantity: int | None  # None means `many` - a shared pool with no count
    takeable: bool
    droppable: bool
    cross_weight: int
    max_per_player: int | None
    requires: str | None
    present_when: str | None
    transforms_to: str | None
    transform_room: str | None
    yields: str | None
    destination_room_id: str | None
    contained_in: str | None
    use_cooldown_hours: int | None
    since_drop: int
    sort_order: int

    @property
    def is_exit(self) -> bool:
        return self.type == "exit"

    @property
    def is_source(self) -> bool:
        return self.type == "source"

    @property
    def names(self) -> tuple[str, ...]:
        """Everything a player could type to mean this thing."""
        return (self.name,) + self.aliases


@dataclass(frozen=True)
class Drop:
    """One entry in the unlock calendar.

    A drop is a moment when content becomes visible; a release is a deployment.
    One release can carry a dozen drops that arrive over the following weeks,
    which is why nothing in the database records a release number.
    """

    drop_id: int
    trigger: str
    date: str | None
    event: str | None
    name: str
    notes: str | None

    @property
    def arrives_at_launch(self) -> bool:
        return self.trigger == "date" and (self.date or "").lower() == LAUNCH


@dataclass(frozen=True)
class Restock:
    """A scheduled top-up: what reappears, where, and how often.

    The third way a thing enters the world, alongside being placed in a room and
    being yielded by a source. Several things exist only through this - the
    bottles and the diapers are never placed anywhere at load.
    """

    restock_id: int
    thing_id: str
    placement: str
    container: str | None
    amount: int
    times_per_day: int
    first_day: int
    every_n_days: int
    window_start: str
    window_end: str
    config_key: str | None
    since_drop: int
    notes: str | None


@dataclass(frozen=True)
class EmojiGroup:
    """One emoji, its Unicode subgroup, and whether it can be the craving.

    Splitting the pool from the grouping is what makes the dishware rule fall
    out rather than needing a special case: the craving is drawn only from
    drawable rows, but a player who reacts with a plate still resolves to a
    known subgroup and simply never matches.
    """

    emoji: str
    subgroup: str
    drawable: bool


@dataclass(frozen=True)
class TextRow:
    entity_id: str
    state: str
    since_drop: int
    text: dict[str, str]


@dataclass
class Content:
    """Every content file, parsed. Validity is a separate question - see validate()."""

    rooms: list[Room] = field(default_factory=list)
    room_text: list[TextRow] = field(default_factory=list)
    things: list[Thing] = field(default_factory=list)
    thing_text: list[TextRow] = field(default_factory=list)
    defaults: dict[str, str] = field(default_factory=dict)
    drops: list[Drop] = field(default_factory=list)
    restocks: list[Restock] = field(default_factory=list)
    emoji_groups: list[EmojiGroup] = field(default_factory=list)

    @property
    def rooms_by_id(self) -> dict[str, Room]:
        return {r.room_id: r for r in self.rooms}

    @property
    def drops_by_id(self) -> dict[int, Drop]:
        return {d.drop_id: d for d in self.drops}

    @property
    def restocked_thing_ids(self) -> set[str]:
        return {r.thing_id for r in self.restocks}

    @property
    def craving_pool(self) -> list[EmojiGroup]:
        """The emoji a craving may be drawn from."""
        return [e for e in self.emoji_groups if e.drawable]

    @property
    def things_by_id(self) -> dict[str, Thing]:
        return {t.thing_id: t for t in self.things}

    def exits_from(self, room_id: str) -> list[Thing]:
        return [t for t in self.things if t.is_exit and t.room_id == room_id]


# --------------------------------------------------------------------------
# Cell coercion
#
# Blank means "unset" everywhere, which is what lets a writer leave a cell empty
# and take the house default. Each helper turns a blank into None or a stated
# fallback rather than into an empty string, so downstream code never has to ask
# which kind of empty it is looking at.
# --------------------------------------------------------------------------


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _bool(value: str | None, *, default: bool = False) -> bool:
    raw = _text(value)
    if raw is None:
        return default
    return raw.lower() in {"yes", "y", "true", "1"}


def _int(value: str | None, *, default: int | None = None) -> int | None:
    raw = _text(value)
    if raw is None:
        return default
    return int(raw)


def normalise_emoji(value: str) -> str:
    """Strip the variation selector so the file and a reaction compare equal.

    Discord hands back some emoji with U+FE0F and some without, and the file
    contains whichever form Unicode calls fully-qualified. Normalising once on
    load - rather than at each comparison - is what stops the two disagreeing
    invisibly for a single emoji nobody thinks to test.
    """
    return unicodedata.normalize("NFC", value.strip()).replace("\ufe0f", "")


def _aliases(value: str | None) -> tuple[str, ...]:
    raw = _text(value)
    if raw is None:
        return ()
    return tuple(a.strip() for a in raw.split("|") if a.strip())


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def _rows(path: Path, expected: tuple[str, ...]) -> list[dict[str, str]]:
    """Read one TSV, checking its header before trusting any row."""
    if not path.exists():
        raise ContentError([f"{path.name} is missing from {path.parent}"])

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        header = tuple(reader.fieldnames or ())
        missing = [c for c in expected if c not in header]
        if missing:
            raise ContentError([f"{path.name} has no {', '.join(missing)} column(s)"])

        rows = []
        for number, row in enumerate(reader, start=2):
            # A short row leaves trailing keys as None; a long one collects the
            # overflow under the restkey. Both mean a stray or missing tab, which
            # silently shifts every later column.
            if None in row:
                raise ContentError(
                    [f"{path.name} line {number} has more fields than the header"]
                )
            rows.append(row)
        return rows


def _text_rows(path: Path, id_column: str, columns: tuple[str, ...]) -> list[TextRow]:
    out = []
    for row in _rows(path, (id_column, "state", "since_drop")):
        out.append(
            TextRow(
                entity_id=row[id_column].strip(),
                state=_text(row.get("state")) or "default",
                since_drop=_int(row.get("since_drop"), default=1) or 1,
                text={c: row[c].strip() for c in columns if _text(row.get(c))},
            )
        )
    return out


def load_files(directory: Path | None = None) -> Content:
    """Parse all five files. Raises ContentError on anything unreadable.

    Structural problems that stop parsing (a missing file, a shifted column) are
    raised here. Problems of meaning - a thing pointing at a room that does not
    exist - are validate()'s job, so a writer gets all of them at once.
    """
    base = Path(directory) if directory else CONTENT_DIR
    content = Content()

    for row in _rows(base / FILES["rooms"], ("room_id", "name")):
        content.rooms.append(
            Room(
                room_id=row["room_id"].strip(),
                name=row["name"].strip(),
                sort_order=_int(row.get("sort_order"), default=0) or 0,
                open_at_launch=_bool(row.get("open_at_launch"), default=True),
            )
        )

    for row in _rows(base / FILES["things"], ("thing_id", "name", "type")):
        quantity_raw = _text(row.get("quantity"))
        content.things.append(
            Thing(
                thing_id=row["thing_id"].strip(),
                name=row["name"].strip(),
                aliases=_aliases(row.get("aliases")),
                type=(_text(row.get("type")) or "").lower(),
                room_id=_text(row.get("room_id")),
                quantity=None if quantity_raw == "many" else _int(quantity_raw, default=1),
                takeable=_bool(row.get("takeable")),
                droppable=_bool(row.get("droppable"), default=True),
                cross_weight=_int(row.get("cross_weight"), default=0) or 0,
                max_per_player=_int(row.get("max_per_player")),
                requires=_text(row.get("requires")),
                present_when=_text(row.get("present_when")),
                transforms_to=_text(row.get("transforms_to")),
                transform_room=_text(row.get("transform_room")),
                yields=_text(row.get("yields")),
                destination_room_id=_text(row.get("destination_room_id")),
                contained_in=_text(row.get("contained_in")),
                use_cooldown_hours=_int(row.get("use_cooldown_hours")),
                since_drop=_int(row.get("since_drop"), default=1) or 1,
                sort_order=_int(row.get("sort_order"), default=0) or 0,
            )
        )

    content.room_text = _text_rows(base / FILES["room_text"], "room_id", ("look",))
    content.thing_text = _text_rows(base / FILES["thing_text"], "thing_id", THING_TEXT_COLUMNS)

    for row in _rows(base / FILES["defaults"], ("key", "text")):
        content.defaults[row["key"].strip()] = row["text"]

    for row in _rows(base / FILES["drops"], ("drop_id", "trigger")):
        content.drops.append(
            Drop(
                drop_id=_int(row.get("drop_id"), default=0) or 0,
                trigger=(_text(row.get("trigger")) or "").lower(),
                date=_text(row.get("date")),
                event=_text(row.get("event")),
                name=_text(row.get("name")) or "",
                notes=_text(row.get("notes")),
            )
        )

    for row in _rows(base / FILES["restocks"], ("restock_id", "thing_id", "placement")):
        content.restocks.append(
            Restock(
                restock_id=_int(row.get("restock_id"), default=0) or 0,
                thing_id=row["thing_id"].strip(),
                placement=(_text(row.get("placement")) or "").lower(),
                container=_text(row.get("container")),
                amount=_int(row.get("amount"), default=1) or 1,
                times_per_day=_int(row.get("times_per_day"), default=1) or 1,
                first_day=_int(row.get("first_day"), default=1) or 1,
                every_n_days=_int(row.get("every_n_days"), default=1) or 1,
                window_start=_text(row.get("window_start")) or "00:00",
                window_end=_text(row.get("window_end")) or "23:59",
                config_key=_text(row.get("config_key")),
                since_drop=_int(row.get("since_drop"), default=1) or 1,
                notes=_text(row.get("notes")),
            )
        )

    for row in _rows(base / FILES["emoji_groups"], ("emoji", "subgroup")):
        emoji = normalise_emoji(row["emoji"])
        if not emoji:
            continue
        content.emoji_groups.append(
            EmojiGroup(
                emoji=emoji,
                subgroup=(_text(row.get("subgroup")) or "").lower(),
                drawable=_bool(row.get("drawable"), default=True),
            )
        )

    return content


# --------------------------------------------------------------------------
# Validation
#
# Every check returns problems rather than raising, so one bad file produces one
# complete report instead of a game of whack-a-mole. These all pass against the
# shipped content today; their value is on the next load, after a writer has
# edited something.
# --------------------------------------------------------------------------


def validate(content: Content) -> list[str]:
    """Every reason this content could not be loaded. Empty means it is sound."""
    problems: list[str] = []
    rooms = content.rooms_by_id
    things = content.things_by_id

    problems += _check_duplicates(content)
    problems += _check_rooms(content, rooms)
    problems += _check_references(content, rooms, things)
    problems += _check_containers(content, things)
    problems += _check_aliases(content)
    problems += _check_text_coverage(content, rooms, things)
    problems += _check_exits(content, rooms)
    problems += _check_reachable_rooms(content, rooms)
    problems += _check_obtainable_things(content, things)
    problems += _check_states(content, things)
    problems += _check_drops(content)
    problems += _check_drop_references(content)
    problems += _check_restocks(content, things)
    problems += _check_sources_are_named_in_prose(content, rooms)
    problems += _check_emoji_groups(content)
    return problems


def _check_duplicates(content: Content) -> list[str]:
    problems = []
    for label, ids in (
        ("room", [r.room_id for r in content.rooms]),
        ("thing", [t.thing_id for t in content.things]),
    ):
        seen = set()
        for identifier in ids:
            if identifier in seen:
                problems.append(f"duplicate {label} id {identifier!r}")
            seen.add(identifier)
    return problems


def _check_rooms(content: Content, rooms: dict[str, Room]) -> list[str]:
    problems = []
    for room in content.rooms:
        if not room.room_id:
            problems.append("a room has a blank room_id")
        if not room.name:
            problems.append(f"room {room.room_id} has no name")
    names = [r.name.lower() for r in content.rooms]
    for name in {n for n in names if names.count(n) > 1}:
        problems.append(f"two rooms are both called {name!r}; thread names would collide")
    return problems


def _check_references(
    content: Content, rooms: dict[str, Room], things: dict[str, Thing]
) -> list[str]:
    """Nothing may point at a room or thing that does not exist."""
    problems = []
    for thing in content.things:
        if thing.type not in THING_TYPES:
            problems.append(
                f"thing {thing.thing_id} has type {thing.type!r}; "
                f"expected one of {', '.join(sorted(THING_TYPES))}"
            )
        if thing.room_id and thing.room_id != EVERYWHERE and thing.room_id not in rooms:
            problems.append(f"thing {thing.thing_id} is in unknown room {thing.room_id!r}")
        for column in ("transform_room", "destination_room_id"):
            target = getattr(thing, column)
            if target and target not in rooms:
                problems.append(
                    f"thing {thing.thing_id}: {column} {target!r} is not a room"
                )
        for column in ("transforms_to", "yields", "contained_in"):
            target = getattr(thing, column)
            if target and target not in things:
                problems.append(
                    f"thing {thing.thing_id}: {column} {target!r} is not a thing"
                )
    return problems


def _check_containers(content: Content, things: dict[str, Thing]) -> list[str]:
    """Containment is one level deep, and host and contents share a room."""
    problems = []
    for thing in content.things:
        host_id = thing.contained_in
        if not host_id:
            continue
        host = things.get(host_id)
        if host is None:
            continue  # already reported by _check_references
        if host.contained_in:
            problems.append(
                f"thing {thing.thing_id} is inside {host_id}, which is itself inside "
                f"{host.contained_in}; containment is one level only"
            )
        if host.room_id and thing.room_id and host.room_id != thing.room_id:
            problems.append(
                f"thing {thing.thing_id} is in room {thing.room_id} but its container "
                f"{host_id} is in {host.room_id}"
            )
    return problems


def _check_aliases(content: Content) -> list[str]:
    """Within one room, no two things may answer to the same word.

    Across rooms it is fine - a player is only ever in one. Roomless objects are
    excluded: several cat food flavours deliberately share "cat food", and an
    ambiguous match in a bag is resolved by asking, not by refusing to load.
    """
    problems = []
    seen: dict[tuple[str, str], list[str]] = {}
    for thing in content.things:
        if not thing.room_id:
            continue
        for name in thing.names:
            seen.setdefault((thing.room_id, name.lower()), []).append(thing.thing_id)
    for (room_id, name), owners in sorted(seen.items()):
        if len(set(owners)) > 1:
            problems.append(
                f"in room {room_id}, {name!r} could mean any of {', '.join(sorted(set(owners)))}"
            )
    return problems


def _check_text_coverage(
    content: Content, rooms: dict[str, Room], things: dict[str, Thing]
) -> list[str]:
    """Every entity needs a default text row, and no text row may be an orphan."""
    problems = []

    for rows, known, label, default_column in (
        (content.room_text, rooms, "room", "look"),
        (content.thing_text, things, "thing", "look"),
    ):
        by_entity: dict[str, set[str]] = {}
        for row in rows:
            if row.entity_id not in known:
                problems.append(f"{label}_text has a row for unknown {label} {row.entity_id!r}")
                continue
            by_entity.setdefault(row.entity_id, set()).add(row.state)
        for entity_id in known:
            states = by_entity.get(entity_id)
            if not states:
                problems.append(f"{label} {entity_id} has no text row")
            elif "default" not in states:
                problems.append(
                    f"{label} {entity_id} has text for {', '.join(sorted(states))} "
                    "but no default state"
                )

    for row in content.thing_text:
        if row.entity_id in things and row.state == "default" and default_column not in row.text:
            problems.append(f"thing {row.entity_id} has no default look text")

    return problems


def _check_exits(content: Content, rooms: dict[str, Room]) -> list[str]:
    """Exits need somewhere to go, and the spec says every one is bidirectional."""
    problems = []
    exits = [t for t in content.things if t.is_exit]

    pairs = set()
    for exit_ in exits:
        if not exit_.destination_room_id:
            problems.append(f"exit {exit_.thing_id} has no destination_room_id")
            continue
        if not exit_.room_id:
            problems.append(f"exit {exit_.thing_id} is not in any room")
            continue
        if exit_.destination_room_id == exit_.room_id:
            problems.append(f"exit {exit_.thing_id} leads back into its own room")
        if exit_.takeable:
            problems.append(f"exit {exit_.thing_id} is marked takeable")
        pairs.add((exit_.room_id, exit_.destination_room_id))

    for origin, destination in sorted(pairs):
        if (destination, origin) not in pairs:
            problems.append(
                f"{origin} leads to {destination} with no exit back; "
                "a player taking it would be stranded"
            )
    return problems


def _check_reachable_rooms(content: Content, rooms: dict[str, Room]) -> list[str]:
    """Every room must be walkable from the start, locked or not.

    A locked room is still reachable in the graph sense - it is opened later.
    A room with no exits leading to it is a content bug nobody would notice
    until a player failed to find it.
    """
    if not content.rooms:
        return []
    start = next((r.room_id for r in content.rooms if r.open_at_launch), content.rooms[0].room_id)

    adjacency: dict[str, set[str]] = {r.room_id: set() for r in content.rooms}
    for exit_ in content.things:
        if exit_.is_exit and exit_.room_id in adjacency and exit_.destination_room_id:
            adjacency[exit_.room_id].add(exit_.destination_room_id)

    seen, queue = {start}, [start]
    while queue:
        for destination in adjacency.get(queue.pop(), ()):
            if destination not in seen:
                seen.add(destination)
                queue.append(destination)

    return [
        f"room {room_id} cannot be reached from {start}"
        for room_id in sorted(set(adjacency) - seen)
    ]


def _check_obtainable_things(content: Content, things: dict[str, Thing]) -> list[str]:
    """Nothing may exist that no player could ever hold.

    A roomless object is one that is never placed at load. It comes into being
    three ways: a source yields it, another thing transforms into it, or a
    restock schedule puts it somewhere. If none of those happens it is
    unreachable, and no check on dangling references catches that - every
    reference it makes is fine. It simply never appears in the game.
    """
    produced = {t.yields for t in content.things if t.yields}
    produced |= {t.transforms_to for t in content.things if t.transforms_to}
    produced |= content.restocked_thing_ids

    problems = []
    for thing in content.things:
        placed = bool(thing.room_id) and thing.quantity != 0
        if placed or thing.thing_id in produced:
            continue
        problems.append(
            f"thing {thing.thing_id} is in no room and nothing yields or transforms "
            "into it, so no player could ever obtain it"
        )
    return problems


def _check_states(content: Content, things: dict[str, Thing]) -> list[str]:
    """A `present_when` gate must name a state something can actually reach.

    A state nobody sets means content that never appears. States are set by the
    engine rather than declared in the files, so this checks the two places a
    state name is written down agree: a gate, and a text row for that state.
    """
    text_states = {row.state for row in content.thing_text} | {
        row.state for row in content.room_text
    }
    # Server and player states the engine owns. Listed here so a typo in a gate
    # is caught; extend this when the engine learns a new state.
    engine_states = {
        "stairs_repaired",
        "drawer_unjammed",
        "has_key",
        "passage_open",
        "library_found",
    }
    known = text_states | engine_states

    problems = []
    for thing in content.things:
        gate = thing.present_when
        if not gate:
            continue
        name = gate.lstrip("!")
        if name not in known:
            problems.append(
                f"thing {thing.thing_id} is gated on state {name!r}, which nothing sets "
                "and no text row describes"
            )
    return problems


def _check_drops(content: Content) -> list[str]:
    """The calendar has to be answerable: every drop needs a way to arrive."""
    problems = []
    seen = set()
    for drop in content.drops:
        if drop.drop_id in seen:
            problems.append(f"duplicate drop_id {drop.drop_id}")
        seen.add(drop.drop_id)

        if drop.trigger not in DROP_TRIGGERS:
            problems.append(
                f"drop {drop.drop_id} has trigger {drop.trigger!r}; "
                f"expected one of {', '.join(sorted(DROP_TRIGGERS))}"
            )
            continue

        if drop.trigger == "date" and not drop.date:
            problems.append(f"drop {drop.drop_id} is date-triggered but has no date")
        if drop.trigger == "event":
            if not drop.event:
                problems.append(f"drop {drop.drop_id} is event-triggered but names no event")
            elif drop.event not in KNOWN_DROP_EVENTS:
                problems.append(
                    f"drop {drop.drop_id} waits on event {drop.event!r}, which the engine "
                    "does not know how to fire; add it to KNOWN_DROP_EVENTS or fix the name"
                )
    return problems


def _check_drop_references(content: Content) -> list[str]:
    """Content waiting on a drop that does not exist would never appear."""
    known = set(content.drops_by_id)
    problems = []

    def check(label: str, identifier: str, since_drop: int) -> None:
        if since_drop not in known:
            problems.append(
                f"{label} {identifier} waits for drop {since_drop}, which is not in drops.tsv"
            )

    for thing in content.things:
        check("thing", thing.thing_id, thing.since_drop)
    for row in content.room_text:
        check("room_text row for", row.entity_id, row.since_drop)
    for row in content.thing_text:
        check("thing_text row for", row.entity_id, row.since_drop)
    for restock in content.restocks:
        check("restock", str(restock.restock_id), restock.since_drop)
    return problems


def _check_restocks(content: Content, things: dict[str, Thing]) -> list[str]:
    """A schedule must name a real thing and a reachable place to put it."""
    problems = []
    seen = set()
    for restock in content.restocks:
        label = f"restock {restock.restock_id}"
        if restock.restock_id in seen:
            problems.append(f"duplicate restock_id {restock.restock_id}")
        seen.add(restock.restock_id)

        if restock.thing_id not in things:
            problems.append(f"{label} restocks {restock.thing_id!r}, which is not a thing")

        if restock.placement not in RESTOCK_PLACEMENTS:
            problems.append(
                f"{label} has placement {restock.placement!r}; "
                f"expected one of {', '.join(sorted(RESTOCK_PLACEMENTS))}"
            )
        elif restock.placement == "container":
            if not restock.container:
                problems.append(f"{label} places into a container but names none")
            elif restock.container not in things:
                problems.append(
                    f"{label} places into {restock.container!r}, which is not a thing"
                )
        elif restock.container:
            problems.append(
                f"{label} scatters at random but also names container "
                f"{restock.container!r}; leave that cell empty"
            )

        for field_name in ("amount", "times_per_day", "every_n_days", "first_day"):
            value = getattr(restock, field_name)
            if value < 1:
                problems.append(f"{label} has {field_name}={value}; must be at least 1")

        for field_name in ("window_start", "window_end"):
            value = getattr(restock, field_name)
            if not _is_clock_time(value):
                problems.append(f"{label} has {field_name}={value!r}; expected HH:MM")

        if (
            _is_clock_time(restock.window_start)
            and _is_clock_time(restock.window_end)
            and restock.window_start > restock.window_end
        ):
            problems.append(
                f"{label} has a window from {restock.window_start} to {restock.window_end}, "
                "which ends before it starts"
            )
    return problems


def _is_clock_time(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return False
    hours, minutes = int(parts[0]), int(parts[1])
    return 0 <= hours <= 23 and 0 <= minutes <= 59


def _check_sources_are_named_in_prose(content: Content, rooms: dict[str, Room]) -> list[str]:
    """A source is never listed, so the prose that reveals it has to name it.

    Nothing takeable and finite appears in room prose - the engine lists those, so
    the prose cannot go stale. Sources are the exception in the other direction:
    they are inexhaustible, no listing anywhere shows one, and a player who is not
    told about it has no way to find it. Content that fails this check is
    unreachable rather than merely unpolished, which is why it is an error.

    Where to look, and what counts as naming it, both follow the 2b work order: a
    contained source must be named in its container's `look` or `use`, a
    free-standing one in its room's `look`, in either case for the same state.
    Either the source's own name, one of its aliases, or the name of the thing it
    yields will do - "a bowl of candy" reveals the candy bowl.
    """
    room_look: dict[tuple[str, str], str] = {}
    for row in content.room_text:
        room_look[(row.entity_id, row.state)] = row.text.get("look", "").lower()

    thing_prose: dict[tuple[str, str], str] = {}
    for row in content.thing_text:
        key = (row.entity_id, row.state)
        thing_prose[key] = " ".join(
            (thing_prose.get(key, ""), row.text.get("look", ""), row.text.get("use", ""))
        ).lower()

    things = content.things_by_id
    problems = []
    for thing in content.things:
        if not thing.is_source:
            continue

        state = thing.present_when.lstrip("!") if thing.present_when else "default"
        if thing.contained_in:
            prose = thing_prose.get((thing.contained_in, state), "")
            where = f"the look or use text of {thing.contained_in}"
        elif thing.room_id:
            prose = room_look.get((thing.room_id, state), "")
            where = f"the description of room {thing.room_id}"
        else:
            continue

        wanted = list(thing.names)
        produced = things.get(thing.yields or "")
        if produced is not None:
            wanted.append(produced.name)

        if not any(name.lower() in prose for name in wanted if name):
            problems.append(
                f"source {thing.thing_id} is named nowhere in {where}; it is never listed, "
                "so no player could learn it is there"
            )
    return problems


def _check_emoji_groups(content: Content) -> list[str]:
    """The craving lookup has to be usable: unique, grouped, and non-empty.

    Emoji are compared after normalisation, so uniqueness has to hold after it
    too - two rows differing only by a variation selector would both answer for
    the same reaction, and which one won would depend on row order.
    """
    problems = []

    seen = set()
    for row in content.emoji_groups:
        if row.emoji in seen:
            problems.append(
                f"emoji {row.emoji!r} appears twice once variation selectors are "
                "normalised; one row would silently shadow the other"
            )
        seen.add(row.emoji)
        if not row.subgroup:
            problems.append(f"emoji {row.emoji!r} has no subgroup")

    if content.emoji_groups and not content.craving_pool:
        problems.append(
            "no emoji is drawable, so the daily craving could never be drawn"
        )
    return problems


def load(directory: Path | None = None) -> Content:
    """Parse and validate. Raises ContentError listing everything wrong."""
    content = load_files(directory)
    problems = validate(content)
    if problems:
        raise ContentError(problems)
    return content
