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
}

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
    since_release: int
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
class TextRow:
    entity_id: str
    state: str
    since_release: int
    text: dict[str, str]


@dataclass
class Content:
    """Every content file, parsed. Validity is a separate question - see validate()."""

    rooms: list[Room] = field(default_factory=list)
    room_text: list[TextRow] = field(default_factory=list)
    things: list[Thing] = field(default_factory=list)
    thing_text: list[TextRow] = field(default_factory=list)
    defaults: dict[str, str] = field(default_factory=dict)

    @property
    def rooms_by_id(self) -> dict[str, Room]:
        return {r.room_id: r for r in self.rooms}

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
    for row in _rows(path, (id_column, "state", "since_release")):
        out.append(
            TextRow(
                entity_id=row[id_column].strip(),
                state=_text(row.get("state")) or "default",
                since_release=_int(row.get("since_release"), default=1) or 1,
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
                since_release=_int(row.get("since_release"), default=1) or 1,
                sort_order=_int(row.get("sort_order"), default=0) or 0,
            )
        )

    content.room_text = _text_rows(base / FILES["room_text"], "room_id", ("look",))
    content.thing_text = _text_rows(base / FILES["thing_text"], "thing_id", THING_TEXT_COLUMNS)

    for row in _rows(base / FILES["defaults"], ("key", "text")):
        content.defaults[row["key"].strip()] = row["text"]

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

    A roomless object is one that is never placed - it comes into being when a
    source yields it or another thing transforms into it. If neither happens, it
    is unreachable: no check on dangling references catches this, because every
    reference it makes is fine. It simply never appears in the game.
    """
    produced = {t.yields for t in content.things if t.yields}
    produced |= {t.transforms_to for t in content.things if t.transforms_to}

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


def load(directory: Path | None = None) -> Content:
    """Parse and validate. Raises ContentError listing everything wrong."""
    content = load_files(directory)
    problems = validate(content)
    if problems:
        raise ContentError(problems)
    return content
