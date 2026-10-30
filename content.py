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
import hashlib
import os
import re
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
    "craving_reactions": "craving_reactions.tsv",
    "achievements": "achievements.tsv",
    "art": "art.tsv",
}

# Where the artwork lives on disk. Structure rather than content, which is why
# the files sit outside `creative content` - a writer edits the alt text, not
# the PNGs.
ART_DIR = Path(__file__).resolve().parent / "artwork"

# What an achievement's award is scoped to. `group` is the odd one: it lands in
# server_achievements, has no earner and sends its description to nobody.
ACHIEVEMENT_KINDS = {"public", "secret", "group"}

# How a drop arrives. `date` is answered by the calendar every time it is asked and
# stores nothing; `event` and `manual` are recorded per guild the first time they
# fire, because a condition that stops being true must not un-ship content.
DROP_TRIGGERS = {"date", "event", "manual"}

# `since_drop` for content that is written but not scheduled. Eight
# achievements wait on systems nobody has built - crossing, the
# doorbell, the ghosts, the letter, the craving - and a real drop
# number would promise a date their trigger cannot keep.
#
# **It has to be a value the loader knows about rather than a number
# chosen to be large.** Arrival is a set membership test against the
# drops the calendar defines, so *any* undefined number never arrives -
# which means a row parked deliberately and a row with a typo in it
# behave identically and neither says anything. Naming one value is
# what lets the check below refuse the other.
NEVER = 99

# A `date` drop whose date is this arrives the moment a server initializes.
LAUNCH = "launch"

# The Halloween channel, which is a room everywhere except in the ways that
# make a room a room. It has no exits, no prose and no place in any listing:
# `/look` there prints what is present and nothing else. It exists so the cat
# bed can have an ordinary `room_id` and `/use` can resolve through the
# ordinary path, rather than the channel being a special case in every verb.
CHANNEL_ROOM = "CH"

# Conditions an `event` drop may name. Release 1 ships none; the registry exists so
# the second one needs no migration, and so a typo in the file is caught at load
# rather than becoming a drop that never arrives.
KNOWN_DROP_EVENTS: set[str] = set()

# The category the bot's own reaction emoji sit in. They are in the file so
# that the writers can see and swap them, and `excluded` keeps them out of the
# game: a player reacting with one is reacting with the bot's own answer, and
# judging it would let them read the ladder backwards.
BOT_CATEGORY = "Bot"

# What a guess can earn, best last. **The game branches on these
# strings**, so they are the game's vocabulary rather than the writers' - the
# emoji beside each one in `craving_reactions.tsv` is theirs to change, and
# the slug is not. Declared here because this is the module that checks the
# file, and `craving` imports it rather than keeping a second copy that could
# drift from the one the validator enforces.
#
# `OUT_OF_GUESSES` is deliberately outside `CRAVING_LADDER`. It has no rank:
# a message that has run out of reaction slots is not a better answer than
# a win, it is the end of the message.
#
# `MESSAGE_FULL` is not an answer at all. It is padding: the bot puts it up
# only when the ❌ failed to take the twentieth slot, which happens when a
# player had already reacted with the ❌ themselves and the bot's own add
# merely joined their reaction. Without it the message would sit at
# nineteen with the ❌ showing and a slot still free - and the one guess
# that fits in that slot is the one the bot has no room left to answer.
#
# **Optional, and the only outcome that is.** A file without it loads and
# plays; the bot simply cannot close that last gap.
CRAVING_LADDER = ("greeting", "wrong_category", "right_category", "right_type", "win")
OUT_OF_GUESSES = "out_of_guesses"
MESSAGE_FULL = "message_full"
REQUIRED_CRAVING_OUTCOMES = CRAVING_LADDER + (OUT_OF_GUESSES,)
CRAVING_OUTCOMES = REQUIRED_CRAVING_OUTCOMES + (MESSAGE_FULL,)

# What the cat wants on the first five days a server plays, before the draw
# takes over. **By CLDR short name, which is the catalogue's own column**, so
# that a writer who renames or removes one of them gets a content error
# instead of a game that quietly falls back to random on day one.
#
# Here rather than in `craving` because this is the module that validates it
# and `craving` imports this one, not the other way round.
SCRIPTED_CRAVINGS = ("mouse", "cut of meat", "broccoli", "fish", "egg")

# Where a restock puts what it adds. `container` names one; `room` names one
# room; `random` draws a slot from every room and every container at equal
# probability. The column that names the target is `destination` - it was
# `container` until drop 2, and stopped being accurate the moment a restock
# could target a room.
RESTOCK_PLACEMENTS = {"container", "room", "random"}

# A restock's `thing_id` may name a class rather than a thing: `type:toy`
# means draw uniformly among the things of that type that are eligible to
# be placed. One row then keeps the channel stocked with any toy, and a
# thirteenth toy needs no restock change.
CLASS_PREFIX = "type:"

# What a player must have done for a fragment to be visible to them.
# Each one is a notice id as well as a gate name, and they are the same
# string on purpose: the gate is read straight off the per-player
# notices table, so a second name would be a second thing to keep in
# step. Adding one is a line here and a branch in `bot._unlocked_for`,
# and doing one without the other fails `_check_visibility_gates`.
LOOKED_AT_BED = "looked_at_bed"

# Drop 10's two. `fed_the_cat` opens the Entryway past its first
# sentence and unlocks its inner doorways; `knows_house` is what puts
# the house into the road's prose, and is held by anybody who has
# earned *Purrsuasive*, looked at the house, or been inside it.
FED_THE_CAT = "fed_the_cat"
KNOWS_HOUSE = "knows_house"

VISIBILITY_GATES = {LOOKED_AT_BED, FED_THE_CAT, KNOWS_HOUSE}

# The five kinds of thing. `exit` moves a player; `source` is an
# inexhaustible supply that yields objects; `object` can be carried;
# `fixture` is scenery that exists so `/look` works on anything the prose
# mentions; `toy` is an object the cat plays with, and is its own type
# because the restock cap, the play ramp and three achievements all count
# toys as a class rather than by name.
THING_TYPES = {"object", "fixture", "exit", "source", "toy", "scenery", "terrain"}

# Scenery is the outdoors: things that exist so `/look` works on what the
# prose points at, and that can never be picked up or used. A class
# rather than a list of ids, so the loader's checks and any later
# outdoor set join it without naming rows.
SCENERY = "scenery"

# Terrain is scenery that nobody built: ground, weather, the marks left
# in mud. It behaves as scenery in every respect but one - the refusal
# when a player tries to take it. `take_fail.fixture` reads "the {name}
# isn't yours to carry off," which is right for a thing somebody owns
# and nonsense for fog, so terrain falls to `take_fail.terrain` instead.
#
# **A type rather than a list of ids** because the split recurs: the
# Courtyard and the oak want the same line, and `take_fail.exit` is
# already chosen off `type` in exactly this way. Everywhere else in the
# engine, test `SCENERY_TYPES` and not `SCENERY` - a bare comparison
# against one of them is how terrain silently stops being outdoors.
TERRAIN = "terrain"

SCENERY_TYPES = frozenset({SCENERY, TERRAIN})

# Toys are carried and dropped like any other object.
CARRIABLE_TYPES = {"object", "toy"}

# A room_id every server has, used by things that exist everywhere (the Alexa).
EVERYWHERE = "ALL"

# Where a toy's rotating play refusals live. Two prefixes in one family:
# this plus `any.` is every line any toy can draw, and this plus a
# `thing_id` is one toy's own. The generic twelve are numbered under
# `any` rather than directly under the family because a bare
# `use_fail.toy.` would match both pools at once, and the picker reads
# each of them with a plain prefix match.
TOY_REFUSAL_PREFIX = "use_fail.toy."
ANY_TOY_REFUSAL_PREFIX = TOY_REFUSAL_PREFIX + "any."

# Text columns, in the order a resolver falls back through them.
THING_TEXT_COLUMNS = (
    "look",
    "look_carried",
    "use",
    "take",
    "drop",
    "use_fail",
    # **The clock's refusal, where it differs from the state's.**
    # Blank on all but the lumber's two `stairs_upper` rows, and blank
    # means "use `use_fail`", which is what every other thing with a
    # cooldown wants. The two parted company in drop 20: in
    # `stairs_upper` the lumber's `use_fail` says the top steps are out
    # of reach, which is true for everybody, and a player who has
    # simply already laid a plank today needs the other sentence.
    "use_fail_cooldown",
    "take_fail",
    "drop_fail",
    # Per-exit overrides for the lines a move posts in the rooms it leaves and
    # enters. Blank on every row but the four secret exits, which fall back to
    # `move.depart` and `move.arrive` in defaults.tsv like everything else.
    "move_depart",
    "move_arrive",
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
    # Used up when used. Last in the list and defaulted, so the many
    # places that build a Thing without one keep working - almost
    # nothing in the house is consumable.
    consumed_on_use: bool = False
    # Once per Pacific day rather than once per N hours. A different
    # kind of cooldown, not a different length of one.
    use_cooldown_daily: bool = False
    # **May a randomly scattered thing land in this one?** Default yes,
    # because almost everything open is fair game and the scatter is
    # most of what makes the house feel lived in. The shipping box says
    # no: its contents are a delivery on a schedule, and a used baby
    # bottle turning up among David's spice jars reads as a bug rather
    # than as a joke. A restock row that *names* the box still fills it
    # - this is only about the ones that pick a container at random.
    scatter_target: bool = True
    # **Does standing in the room with it count as having it to hand?**
    # Default no, which is the rule `requires` has always had for a
    # thing somebody could pick up: the can opener has to be carried.
    # The ladder is the exception the column exists for - it is takeable
    # and it is also furniture while it is propped against the stairs,
    # so a player laying a plank beside it should not have to pick it up
    # first. Nothing sets it until the ladder arrives in drop 30.
    to_hand_in_room: bool = False

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
    destination: str | None
    max_present: int | None
    amount: int
    times_per_day: int
    first_day: int
    every_n_days: int
    window_start: str
    window_end: str
    config_key: str | None
    since_drop: int
    notes: str | None
    # A `defaults.tsv` key posted in the room when this row delivers, or
    # blank for the rows nobody is told about. The spice jars have one:
    # players who have not fed the cat share the Entryway thread and
    # cannot see the box in their room text yet, so the notice is their
    # first sign of it - vague enough to read as a tease.
    #
    # Last and defaulted, like `consumed_on_use` on a thing: the rows
    # built by hand in the tests outnumber the ones that want these.
    arrival_notice: str | None = None
    # **A gap between deliveries, instead of a count per day.** The two
    # are alternatives: a row with these ignores `times_per_day` and
    # schedules the next delivery a uniformly random stretch after the
    # last. The spice order wants it because it should feel like a van
    # turning up rather than like a clock striking - four fixed times a
    # day is a pattern players learn and then wait on.
    interval_min_hours: int | None = None
    interval_max_hours: int | None = None


@dataclass(frozen=True)
class EmojiGroup:
    """One emoji, where the game files it, and whether it can be the craving.

    **Category and type, not the Unicode subgroup.** The file used to carry
    Unicode's own grouping, which decided the game by accident - dishware
    happened to sit inside Food & Drink, so plates had to be special-cased out
    of the craving pool. The writers' catalogue sorts every emoji for the game
    instead: a category (Food, Prey, Adjacent, Toy, Cat, Misc, Bot) and a type
    within it, which is exactly the pair the reaction ladder judges a guess by.

    Splitting the pool from the grouping is what keeps a losing guess legible.
    The craving is drawn only from drawable rows, but a player who reacts with
    a plate still resolves to a known category and type and simply never
    matches - a straight no rather than an error.
    """

    emoji: str
    code: str
    name: str
    category: str
    type: str
    drawable: bool
    excluded: bool
    # The emoji this one answers for, or "" if it answers for itself. Two
    # pairs today: the 🐭 is the 🐁 and the 🐰 is the 🐇. To a player those
    # are one animal, and being told "right type, wrong emoji" for the
    # face of the thing the cat wants reads as the game being broken.
    same_as: str = ""


@dataclass(frozen=True)
class CravingReaction:
    """One rung of the ladder: what the bot reacts with, and how good it is.

    **In a file so the writers can swap a face without a release.** The
    outcome slugs are the game's, and the code branches on them; the emoji
    and the prose beside them are the writers'.

    `progression` is what makes the ladder a ladder. Discord lets the bot put
    each emoji on a message only once, so its reactions describe the message
    rather than each guess: a message carries its best answer so far, and a
    guess only changes it by beating that rank. `out_of_guesses` has no rank
    at all - it is not a better answer, it is the end of the message - so it
    is `None` rather than another rung.
    """

    outcome: str
    progression: int | None
    emoji: str
    code: str
    meaning: str
    when: str


@dataclass(frozen=True)
class Art:
    """One image, and the words a screen reader gets instead of it.

    `alt` matters more than usual here: a black cat on a transparent
    background is invisible to a screen reader and nearly invisible in some
    Discord themes, so it is the one column in this file a writer owns.
    """

    art_id: str
    file: str
    alt: str
    notes: str | None


@dataclass(frozen=True)
class Achievement:
    """A name, a description, and which drop they arrive at.

    No trigger. The conditions involve counts, time windows, sets and
    cross-table joins, so each lives as a function beside the hook it listens
    on; this row carries only what a writer owns and can edit without opening
    the repository.
    """

    achievement_id: str
    kind: str
    name: str
    unlock: str
    since_drop: int
    sort_order: int
    notes: str | None
    # A public achievement with a visibility prerequisite *is* a quest.
    # `offered` is whether a player is shown it before earning it,
    # `prompt` is the prospective wording, and `requires` is the one
    # achievement they must already hold for it to appear.
    offered: bool = False
    prompt: str | None = None
    requires: str | None = None


@dataclass(frozen=True)
class TextRow:
    entity_id: str
    state: str
    since_drop: int
    text: dict[str, str]
    # Which sentence of a room's paragraph this is, and what a player
    # must have done to see it. Both are the channel's two-stage
    # description; every other row in the game is fragment 0 with no
    # gate and reads exactly as it did.
    fragment: int = 0
    visible_when: str | None = None


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
    craving_reactions: list[CravingReaction] = field(default_factory=list)
    achievements: list[Achievement] = field(default_factory=list)
    art: list[Art] = field(default_factory=list)

    @property
    def rooms_by_id(self) -> dict[str, Room]:
        return {r.room_id: r for r in self.rooms}

    @property
    def drops_by_id(self) -> dict[int, Drop]:
        return {d.drop_id: d for d in self.drops}

    @property
    def restocked_thing_ids(self) -> set[str]:
        """Every thing a restock schedule could place.

        **A class selector is expanded**, which is the difference
        between this and the column it reads. A row may name one thing
        - `used_baby_bottle` - or a class, `type:toy`, and the second
        kind can place any thing of that type. Without expanding it,
        the only route to a toy reads as no route at all, and
        `_check_obtainable_things` calls a restock-only toy
        unreachable.
        """
        # **A class expands to what a schedule could place**, which is
        # the takeable things of that kind - the same pool
        # `database.stock_of_type` draws from. A toy nobody can carry
        # stands where the files put it, so `type:toy` is not a route to
        # the shipping box and must not be read as one.
        by_type: dict[str, set[str]] = {}
        for thing in self.things:
            if not thing.takeable:
                continue
            by_type.setdefault(thing.type, set()).add(thing.thing_id)

        ids: set[str] = set()
        for restock in self.restocks:
            if restock.thing_id.startswith(CLASS_PREFIX):
                ids |= by_type.get(restock.thing_id[len(CLASS_PREFIX):], set())
            else:
                ids.add(restock.thing_id)
        return ids

    @property
    def craving_pool(self) -> list[EmojiGroup]:
        """The emoji a craving may be drawn from."""
        return [e for e in self.emoji_groups if e.drawable]

    @property
    def reaction_for_outcome(self) -> dict[str, CravingReaction]:
        return {r.outcome: r for r in self.craving_reactions}

    @property
    def art_by_id(self) -> dict[str, Art]:
        return {a.art_id: a for a in self.art}

    @property
    def achievement_ids(self) -> set[str]:
        """Every achievement the files name, across all drops."""
        return {a.achievement_id for a in self.achievements}

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


def _since_drop(row: dict[str, str]) -> int:
    """Which drop a content row waits for, defaulting to the first one.

    Its own function because of one character. This used to read
    `_int(...) or 1`, and the `or` was harmless for as long as there was no
    drop 0 - V3 starts numbering at 0, which is falsy, so every drop-0 row
    was silently rewritten to drop 1. That made the cat invisible in the
    one drop she is the whole of.
    """
    value = _int(row.get("since_drop"))
    return 1 if value is None else value


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
                since_drop=_since_drop(row),
                text={c: row[c].strip() for c in columns if _text(row.get(c))},
                fragment=_int(row.get("fragment"), default=0) or 0,
                visible_when=_text(row.get("visible_when")),
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
                consumed_on_use=_bool(row.get("consumed_on_use")),
                use_cooldown_daily=_bool(row.get("use_cooldown_daily")),
                scatter_target=_bool(row.get("scatter_target"), default=True),
                to_hand_in_room=_bool(row.get("to_hand_in_room")),
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
                since_drop=_since_drop(row),
                sort_order=_int(row.get("sort_order"), default=0) or 0,
            )
        )

    content.room_text = _text_rows(base / FILES["room_text"], "room_id", ("look",))
    content.thing_text = _text_rows(base / FILES["thing_text"], "thing_id", THING_TEXT_COLUMNS)

    for row in _rows(base / FILES["defaults"], ("key", "text")):
        # A TSV cell cannot hold a newline, and the welcome copy wants
        # paragraphs. One escape, expanded on read: a literal backslash-n in
        # the file becomes a line break. Nothing else is interpreted, so a
        # backslash anywhere else survives untouched.
        content.defaults[row["key"].strip()] = row["text"].replace("\\n", "\n")

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
                destination=_text(row.get("destination")),
                max_present=_int(row.get("max_present")),
                amount=_int(row.get("amount"), default=1) or 1,
                times_per_day=_int(row.get("times_per_day"), default=1) or 1,
                first_day=_int(row.get("first_day"), default=1) or 1,
                every_n_days=_int(row.get("every_n_days"), default=1) or 1,
                window_start=_text(row.get("window_start")) or "00:00",
                window_end=_text(row.get("window_end")) or "23:59",
                config_key=_text(row.get("config_key")),
                arrival_notice=_text(row.get("arrival_notice")),
                interval_min_hours=_int(row.get("interval_min_hours")),
                interval_max_hours=_int(row.get("interval_max_hours")),
                since_drop=_since_drop(row),
                notes=_text(row.get("notes")),
            )
        )

    for row in _rows(base / FILES["emoji_groups"], ("emoji", "category", "type")):
        emoji = normalise_emoji(row["emoji"])
        if not emoji:
            continue
        content.emoji_groups.append(
            EmojiGroup(
                emoji=emoji,
                code=_text(row.get("code")) or "",
                name=_text(row.get("name")) or "",
                # Kept in the writers' casing. These are read back in reports
                # and in `/qa-inspect` far more often than they are compared,
                # and `Fast Food` reads better there than `fast food`.
                category=_text(row.get("category")) or "",
                type=_text(row.get("type")) or "",
                drawable=_bool(row.get("drawable"), default=False),
                excluded=_bool(row.get("excluded"), default=False),
                same_as=normalise_emoji(row.get("same_as") or ""),
            )
        )

    for row in _rows(
        base / FILES["craving_reactions"], ("outcome", "emoji")
    ):
        outcome = _text(row.get("outcome"))
        if not outcome:
            continue
        content.craving_reactions.append(
            CravingReaction(
                outcome=outcome,
                # Blank is a real value here and not a missing one, so it
                # cannot default to 0: zero would sort `out_of_guesses`
                # below every rung and make it the thing a message falls
                # back to rather than the thing that ends it.
                progression=_int(row.get("progression"), default=None),
                emoji=normalise_emoji(row.get("emoji") or ""),
                code=_text(row.get("code")) or "",
                meaning=_text(row.get("meaning")) or "",
                when=_text(row.get("when")) or "",
            )
        )

    for row in _rows(
        base / FILES["achievements"], ("achievement_id", "kind", "name", "unlock")
    ):
        achievement_id = _text(row.get("achievement_id"))
        if not achievement_id:
            continue
        content.achievements.append(
            Achievement(
                achievement_id=achievement_id,
                kind=(_text(row.get("kind")) or "").lower(),
                name=_text(row.get("name")) or "",
                unlock=_text(row.get("unlock")) or "",
                since_drop=_since_drop(row),
                sort_order=_int(row.get("sort_order"), default=0) or 0,
                notes=_text(row.get("notes")),
                offered=_bool(row.get("offered")),
                prompt=_text(row.get("prompt")),
                requires=_text(row.get("requires")),
            )
        )

    for row in _rows(base / FILES["art"], ("art_id", "file", "alt")):
        art_id = _text(row.get("art_id"))
        if not art_id:
            continue
        content.art.append(
            Art(
                art_id=art_id,
                file=_text(row.get("file")) or "",
                alt=_text(row.get("alt")) or "",
                notes=_text(row.get("notes")),
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
    problems += _check_restocks(content, things, rooms)
    problems += _check_sources_are_named_in_prose(content, rooms)
    problems += _check_no_hand_written_bolding(content)
    problems += _check_scenery_is_named_in_prose(content)
    problems += _check_unlisted_things_are_named_in_prose(content)
    problems += _check_scenery_aliases_are_unique(content)
    problems += _check_visibility_gates(content)
    problems += _check_public_lines_name_the_player(content)
    problems += _check_a_public_use_names_the_player(content)
    problems += _check_other_lines_are_not_second_person(content)
    problems += _check_emoji_groups(content)
    problems += _check_craving_reactions(content)
    problems += _check_scripted_cravings(content)
    problems += _check_achievements(content)
    problems += _check_quests(content)
    problems += _check_art(content)
    problems += _check_consumables(content)
    problems += _check_cooldowns(content)
    problems += _check_toy_refusals(content)
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

    # Text rows are keyed on (entity, state, since_drop) in the database, and
    # that key is a unique constraint. Two rows sharing it got as far as the
    # INSERT before this check existed, which is a load that dies at startup
    # over something the files could have said at `--check` time. It is easy
    # to do accidentally: move a thing's drop-1 and drop-2 rows to the same
    # drop and they collide.
    for label, rows in (("room_text", content.room_text),
                        ("thing_text", content.thing_text)):
        seen = set()
        for row in rows:
            key = (row.entity_id, row.state, row.since_drop, row.fragment)
            if key in seen:
                problems.append(
                    f"{label} has two rows for {row.entity_id} in state "
                    f"{row.state!r} at drop {row.since_drop}, fragment "
                    f"{row.fragment}; the database keeps one row per "
                    "entity, state, drop and fragment"
                )
            seen.add(key)
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
        # `requires` is pipe separated, like aliases, and every part has to be
        # a real thing or the requirement can never be satisfied.
        for part in (thing.requires or "").split("|"):
            wanted = part.strip()
            if wanted and wanted not in things:
                problems.append(
                    f"thing {thing.thing_id}: requires {wanted!r}, which is not a thing"
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
    """Within one room, no two *things* may answer to the same word.

    Across rooms it is fine - a player is only ever in one. Two exceptions,
    and both come down to whether sharing a word is a mistake or the point.

    Roomless objects are excluded: several cat food flavours deliberately
    share "cat food", and an ambiguous match in a bag is resolved by asking,
    not by refusing to load.

    **Exits are excluded from each other**, for the same reason one layer up.
    A room can honestly contain two doorways, and its own prose will call them
    both doorways - the Entryway has an arched one to the Dining Room and a
    wide one to the Living Room. Refusing the load would force the writers to
    take the shared word off both, which leaves a player typing a word the
    room just used at them and being told the house has no such thing.
    Asking is the better answer and `ambiguous.match` already exists to ask.

    **Toys are excluded from each other** on the same grounds, from drop 2.
    The feather wand and the crinkle ball both answer to `toy` and `cat
    toy` deliberately: a player told only that there is a toy in the
    channel will type exactly that, and both rows have to be reachable by
    it. Asking which is the right answer, and it is the first time the
    ambiguity prompt fires on something a player carries.

    An exit or a toy sharing a word with an *object* is still an error.
    That is the case that is almost always a slip rather than a choice,
    and the resolution ladder would answer it by scope rather than by
    asking.
    """
    things = content.things_by_id
    problems = []
    seen: dict[tuple[str, str], list[str]] = {}
    for thing in content.things:
        if not thing.room_id:
            continue
        for name in thing.names:
            seen.setdefault((thing.room_id, name.lower()), []).append(thing.thing_id)
    for (room_id, name), owners in sorted(seen.items()):
        distinct = sorted(set(owners))
        if len(distinct) <= 1:
            continue
        kinds = {things[key].type for key in distinct if key in things}
        # Exits may share a word with each other, and so may toys. Both
        # are cases where sharing is the point rather than a slip: a room
        # can honestly hold two doorways, and the channel holds two toys
        # that a player who was told "there is a toy" will both reach for
        # by typing `toy`. `ambiguous.match` exists to ask which.
        if kinds <= {"exit"} or kinds <= {"toy"}:
            continue
        problems.append(
            f"in room {room_id}, {name!r} could mean any of {', '.join(distinct)}"
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

    **The channel used to be exempt, and the exemption was a ban.** No exit
    could lead to it and none out of it, because it was where players already
    were rather than somewhere they walked to. Drop 10 makes it a place with a
    door: the road has a house across it, the house has a front door back out,
    and both are ordinary exits. So the channel is an ordinary node here, and
    it has to be reachable like everything else - which is the stronger check
    of the two. Delete the two exits and this fails, where the old rule would
    have called the deletion correct.
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


# A fourth way a roomless thing comes into being, and the only one the
# files cannot show: code puts it there. One member, and it should stay
# small - every id in here is a thing whose existence a reader of the
# spreadsheets cannot account for.
#
# The brass key falls out of the cat bed, once for the server and then at
# most once a day while the front door is still locked, in
# `world.dislodge_from_bed`. It has no room because it has no home: until
# somebody fluffs the bed there is no key anywhere.
PLACED_BY_CODE = frozenset({"house_key"})


def _check_obtainable_things(content: Content, things: dict[str, Thing]) -> list[str]:
    """Nothing may exist that no player could ever hold.

    A roomless object is one that is never placed at load. It comes into being
    three ways: a source yields it, another thing transforms into it, or a
    restock schedule puts it somewhere. If none of those happens it is
    unreachable, and no check on dangling references catches that - every
    reference it makes is fine. It simply never appears in the game.

    A fourth way, `PLACED_BY_CODE`, is the one the files cannot show.
    """
    produced = {t.yields for t in content.things if t.yields}
    produced |= {t.transforms_to for t in content.things if t.transforms_to}
    produced |= content.restocked_thing_ids
    produced |= PLACED_BY_CODE

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
    """Content waiting on a drop that does not exist would never appear.

    **Silently.** Arrival is `since_drop in arrived`, and `arrived` is
    built from the drops the calendar defines - so a row pointing at a
    drop nobody has written is not late, it is unreachable, and nothing
    logs it. The 21 October achievement renumbering put twenty-three
    rows at drops 4 to 7 while `drops.tsv` stopped at 3, and the only
    symptom was a test asking why an achievement could not be earned.

    **Any row may say `NEVER`, and only `NEVER`.** That is what
    separates a row parked on purpose from a row with a typo in it, and
    the distinction is what this check is for - an unknown drop is
    unreachable either way, so the file has to say which it meant.

    It was achievements alone until drop 20, on the reasoning that they
    were the only rows whose triggers might not exist yet. Drop 20 found
    the other half of that: Alexa and the bulletin board are written,
    and the notes feature they need is not, so the thing, its text rows
    and the room fragment that names them are all parked together. A
    rule that covered only the achievement would have forced the writers
    either to ship them or to delete them.
    """
    known = set(content.drops_by_id)
    problems = []

    def check(label: str, identifier: str, since_drop: int) -> None:
        if since_drop != NEVER and since_drop not in known:
            problems.append(
                f"{label} {identifier} waits for drop {since_drop}, which is not in drops.tsv"
            )

    for thing in content.things:
        check("thing", thing.thing_id, thing.since_drop)
    for row in content.achievements:
        check("achievement", row.achievement_id, row.since_drop)
    for row in content.room_text:
        check("room_text row for", row.entity_id, row.since_drop)
    for row in content.thing_text:
        check("thing_text row for", row.entity_id, row.since_drop)
    for restock in content.restocks:
        check("restock", str(restock.restock_id), restock.since_drop)
    return problems


def _check_restocks(
    content: Content, things: dict[str, Thing], rooms: dict[str, Room]
) -> list[str]:
    """A schedule must name a real thing and a reachable place to put it."""
    problems = []
    seen = set()
    for restock in content.restocks:
        label = f"restock {restock.restock_id}"
        if restock.restock_id in seen:
            problems.append(f"duplicate restock_id {restock.restock_id}")
        seen.add(restock.restock_id)

        if restock.thing_id.startswith(CLASS_PREFIX):
            # A class selector: draw uniformly among the things of that
            # type. Checked against the vocabulary rather than the id list,
            # and against there being anything to draw - a selector with an
            # empty pool is a schedule that silently places nothing.
            wanted = restock.thing_id[len(CLASS_PREFIX):]
            if wanted not in THING_TYPES:
                problems.append(
                    f"{label} draws from {wanted!r}, which is not a kind of thing"
                )
            elif not any(t.type == wanted for t in content.things):
                problems.append(f"{label} draws from {wanted!r}, of which there are none")
        elif restock.thing_id not in things:
            problems.append(f"{label} restocks {restock.thing_id!r}, which is not a thing")

        if restock.placement not in RESTOCK_PLACEMENTS:
            problems.append(
                f"{label} has placement {restock.placement!r}; "
                f"expected one of {', '.join(sorted(RESTOCK_PLACEMENTS))}"
            )
        elif restock.placement == "container":
            if not restock.destination:
                problems.append(f"{label} places into a container but names none")
            elif restock.destination not in things:
                problems.append(
                    f"{label} places into {restock.destination!r}, which is not a thing"
                )
        elif restock.placement == "room":
            if not restock.destination:
                problems.append(f"{label} places into a room but names none")
            elif restock.destination not in rooms:
                problems.append(
                    f"{label} places into {restock.destination!r}, which is not a room"
                )
        elif restock.destination:
            problems.append(
                f"{label} scatters at random but also names destination "
                f"{restock.destination!r}; leave that cell empty"
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
        if not row.category or not row.type:
            problems.append(
                f"emoji {row.emoji!r} has no category or no type; the ladder "
                "judges a guess by both, so a blank one cannot be scored"
            )
        if row.excluded and row.drawable:
            problems.append(
                f"emoji {row.emoji!r} is both excluded and drawable, so the "
                "craving could be an emoji the bot refuses to judge"
            )

    if content.emoji_groups and not content.craving_pool:
        problems.append(
            "no emoji is drawable, so the daily craving could never be drawn"
        )
    return problems + _check_emoji_aliases(content)


def _check_emoji_aliases(content: Content) -> list[str]:
    """An alias has to answer for something real, and answer for it fully.

    All four of these load fine and go wrong only in play: a dangling
    alias makes one emoji unguessable, a chain makes the answer depend on
    which row is read first, a cross-type alias makes the 👀 lie about
    what it narrowed to, and a drawable alias puts the same craving in
    the pool twice under two faces.
    """
    problems = []
    filed = {row.emoji: row for row in content.emoji_groups}

    for row in content.emoji_groups:
        if not row.same_as:
            continue
        target = filed.get(row.same_as)
        if target is None:
            problems.append(
                f"emoji {row.emoji!r} is the same as {row.same_as!r}, which is "
                "not in the file"
            )
            continue
        if target.same_as:
            problems.append(
                f"emoji {row.emoji!r} is the same as {row.same_as!r}, which is "
                "itself the same as something else; chains are not resolved"
            )
        if (row.category, row.type) != (target.category, target.type):
            problems.append(
                f"emoji {row.emoji!r} is the same as {row.same_as!r} but is "
                f"filed under {row.category}/{row.type} rather than "
                f"{target.category}/{target.type}, so the ladder would "
                "disagree with itself about a guess that wins"
            )
        if row.drawable:
            problems.append(
                f"emoji {row.emoji!r} is drawable and is also the same as "
                f"{row.same_as!r}, so the cat could want one craving two ways"
            )
        if not target.drawable:
            problems.append(
                f"emoji {row.emoji!r} answers for {row.same_as!r}, which the "
                "cat can never want - so neither of them can ever win"
            )
    return problems


def _check_craving_reactions(content: Content) -> list[str]:
    """Every outcome present, each with its own emoji, and the ladder in
    order.

    Every one of these is a way the file can be wrong while still loading,
    and each of them breaks the game silently rather than loudly: a missing
    row makes one answer unreachable, a shared emoji makes two answers
    indistinguishable, and a rank out of order makes a better guess refuse
    to replace a worse one.
    """
    if not content.craving_reactions:
        return []

    problems = []
    by_outcome = content.reaction_for_outcome

    missing = [name for name in REQUIRED_CRAVING_OUTCOMES if name not in by_outcome]
    if missing:
        problems.append(
            f"craving_reactions.tsv has no row for {', '.join(missing)}; the "
            "bot would have nothing to answer that guess with"
        )

    unknown = sorted(set(by_outcome) - set(CRAVING_OUTCOMES))
    if unknown:
        problems.append(
            f"craving_reactions.tsv names outcome(s) {', '.join(unknown)}, which "
            "the game has no branch for"
        )

    seen: dict[str, str] = {}
    for row in content.craving_reactions:
        if not row.emoji:
            problems.append(f"craving outcome {row.outcome} has no emoji to react with")
        elif row.emoji in seen:
            problems.append(
                f"craving outcomes {seen[row.emoji]} and {row.outcome} both react "
                f"with {row.emoji!r}, so the two answers would be indistinguishable"
            )
        else:
            seen[row.emoji] = row.outcome

    ranks = [
        by_outcome[name].progression
        for name in CRAVING_LADDER
        if name in by_outcome
    ]
    if any(rank is None for rank in ranks):
        problems.append(
            "every rung of the ladder needs a progression; without one a guess "
            "cannot be compared to the answer already on the message"
        )
    elif ranks != sorted(ranks) or len(set(ranks)) != len(ranks):
        problems.append(
            f"the craving ladder's progressions are {ranks}, which is not "
            "increasing - a better guess would not replace a worse one"
        )

    for name in (OUT_OF_GUESSES, MESSAGE_FULL):
        end = by_outcome.get(name)
        if end is not None and end.progression is not None:
            problems.append(
                f"{name} has progression {end.progression}; it is the end of a "
                "message rather than a rung, and a rank would let it outrank a win"
            )

    # All of them are in the catalogue as `Bot`, excluded from guessing.
    # Without this a player could react with the bot's own 😻 and be told
    # they were right, which is the ladder read backwards off the answers.
    filed = {row.emoji: row for row in content.emoji_groups}
    for row in content.craving_reactions:
        entry = filed.get(row.emoji)
        if entry is None:
            problems.append(
                f"the bot reacts with {row.emoji!r} for {row.outcome}, but the "
                "emoji file has never heard of it"
            )
        elif not entry.excluded:
            problems.append(
                f"the bot reacts with {row.emoji!r} for {row.outcome}, but that "
                "emoji is not excluded, so a player could guess with it"
            )
    return problems


def _check_scripted_cravings(content: Content) -> list[str]:
    """The written opening week has to name five emoji the cat can want.

    A name that resolves to nothing, to two rows, or to one that is not
    drawable is a day the game opens on something unwinnable or on a random
    draw nobody asked for - and in every one of those cases the file still
    loads, so nothing else would say so.
    """
    if not content.emoji_groups:
        return []

    problems = []
    for name in SCRIPTED_CRAVINGS:
        matches = [row for row in content.emoji_groups if row.name == name]
        if not matches:
            problems.append(
                f"the opening week wants {name!r}, which is not a CLDR short "
                "name in the emoji file"
            )
        elif len(matches) > 1:
            problems.append(
                f"the opening week wants {name!r}, and {len(matches)} rows of "
                "the emoji file are called that"
            )
        elif not matches[0].drawable:
            problems.append(
                f"the opening week wants {name!r}, which is not drawable - the "
                "cat would crave something nobody can react with"
            )
    return problems


def _check_achievements(content: Content) -> list[str]:
    """The ninth file, checked for the four ways a writer can break it.

    Not checked here: that every achievement has a registered trigger and
    every trigger an achievement. That is the check worth having - it catches
    a thirty-sixth achievement nobody wired up, and an id renamed while half
    the awards quietly stop landing - but it needs the trigger registry, which
    is not content. It lives with the dispatcher and runs on the same load.

    A blank `name` or `unlock` is an error rather than a defaulted blank. Every
    other text column in the project falls back to `defaults.tsv`; these two
    have nowhere to fall back to, and an achievement that announces an empty
    string is worse than a load that refuses to start.
    """
    problems = []

    seen = set()
    for row in content.achievements:
        key = (row.achievement_id, row.since_drop)
        if key in seen:
            problems.append(
                f"achievement {row.achievement_id} appears twice at drop "
                f"{row.since_drop}; which name won would depend on row order"
            )
        seen.add(key)

        if row.kind not in ACHIEVEMENT_KINDS:
            problems.append(
                f"achievement {row.achievement_id}: kind {row.kind!r} is not one of "
                + ", ".join(sorted(ACHIEVEMENT_KINDS))
            )
        if not row.name:
            problems.append(f"achievement {row.achievement_id} has no name")
        if not row.unlock:
            problems.append(f"achievement {row.achievement_id} has no unlock text")

    return problems


def _check_consumables(content: Content) -> list[str]:
    """Nothing may be used up that a player cannot get again.

    Consuming is the only thing in the game that destroys an object, so this
    is the one place a content edit can take something away permanently. The
    reading glasses are `quantity = 1` with no source: marking them consumed
    would let the first player who tried them on delete them from that server
    for the rest of October, and no other check would notice.

    A thing is safe if a source yields it, something transforms into it, or a
    restock puts it back.
    """
    produced = {t.yields for t in content.things if t.yields}
    produced |= {t.transforms_to for t in content.things if t.transforms_to}
    produced |= content.restocked_thing_ids

    problems = []
    for thing in content.things:
        if not thing.consumed_on_use:
            continue
        if thing.type != "object":
            problems.append(
                f"thing {thing.thing_id} is consumed on use but is a "
                f"{thing.type}, which is never in anybody's bag"
            )
        elif thing.thing_id not in produced:
            problems.append(
                f"thing {thing.thing_id} is consumed on use and nothing yields, "
                "transforms into or restocks it, so using it would destroy it "
                "for good"
            )
    return problems


def _check_toy_refusals(content: Content) -> list[str]:
    """A toy's own play refusal has to name a toy that exists.

    **This one fails silently by construction.** The pool is found by
    prefix, so a key nothing matches is not an error at runtime - the
    toy draws from the generic twelve, the player reads a perfectly good
    refusal, and the custom lines are never seen by anybody. The four
    the writers wrote for the shipping box sat in the deck unreachable
    for a month for want of the per-thing lookup; a typo in the id now
    fails the same way and just as quietly, which is what this is for.

    `any` is the generic pool and owns no thing. A numeric owner is the
    old flat `use_fail.toy.5` shape, which this also catches.
    """
    toys = {thing.thing_id for thing in content.things if thing.type == "toy"}
    problems = []
    for key in sorted(content.defaults):
        if not key.startswith(TOY_REFUSAL_PREFIX):
            continue
        owner = key[len(TOY_REFUSAL_PREFIX) :].split(".")[0]
        if owner == "any" or owner in toys:
            continue
        problems.append(
            f"default {key} is a play refusal for '{owner}', which is not a "
            "toy; the pool is matched by prefix, so nothing would ever read "
            "it and nothing would say so"
        )
    return problems


def _check_cooldowns(content: Content) -> list[str]:
    """A thing has one kind of cooldown, or none. Never two.

    They are different questions, not two settings of one: hours is a
    rolling window from the last use, and daily is a calendar boundary
    everybody crosses together. A row carrying both would answer to
    whichever branch the dispatcher happened to test first, which is a
    decision nobody made and nothing records.
    """
    return [
        f"thing {thing.thing_id} has both use_cooldown_hours and "
        "use_cooldown_daily; a rolling window and a calendar day are "
        "different rules, so pick one"
        for thing in content.things
        if thing.use_cooldown_daily and thing.use_cooldown_hours
    ]


def _check_quests(content: Content) -> list[str]:
    """The three columns that turn an achievement into a quest.

    A quest the player cannot read is worse than no quest, and a `requires`
    naming nothing is a quest that can never appear - neither raises at
    runtime, which is exactly why they are caught here.
    """
    problems = []
    known = {a.achievement_id for a in content.achievements}
    for row in content.achievements:
        if row.offered and not row.prompt:
            problems.append(
                f"achievement {row.achievement_id} is offered as a quest but "
                "has no prompt, so it would appear in /stats as a blank line"
            )
        if row.prompt and row.prompt.rstrip().endswith("."):
            problems.append(
                f"achievement {row.achievement_id} has a prompt ending in a "
                "full stop; the quest notice puts it at the end of its own "
                "sentence and would double the stop"
            )
        if row.requires and row.requires not in known:
            problems.append(
                f"achievement {row.achievement_id} requires "
                f"{row.requires!r}, which is not an achievement"
            )
        if row.requires == row.achievement_id:
            problems.append(f"achievement {row.achievement_id} requires itself")
    return problems


def _check_art(content: Content) -> list[str]:
    """Every row names a file that is actually there, and says what it shows.

    The file check is the one worth having. An image is uploaded once at
    initialization and referenced by URL forever, so a row pointing at a
    missing PNG fails in an admin command on somebody else's server, hours
    after anyone could connect it to the row that caused it.

    A blank `alt` is an error rather than a defaulted blank, for the same
    reason a blank achievement name is: there is nothing to fall back to, and
    an image with no alt text is invisible to the people who need it most.
    """
    problems = []

    seen = set()
    for row in content.art:
        if row.art_id in seen:
            problems.append(f"art {row.art_id} appears twice")
        seen.add(row.art_id)

        if not row.file:
            problems.append(f"art {row.art_id} names no file")
        elif not (ART_DIR / row.file).is_file():
            problems.append(
                f"art {row.art_id}: {row.file!r} is not in {ART_DIR.name}/"
            )
        if not row.alt:
            problems.append(f"art {row.art_id} has no alt text")

    return problems


# A bolded noun in the prose is a promise that `/look` will answer to it.
# Nothing else in the house is bolded - the writers use italics for
# emphasis - so this pattern can be read as "the writer pointed at
# something" rather than guessed at.
_BOLDED = re.compile(r"\*\*(.+?)\*\*")


# --------------------------------------------------------------------------
# Marking the nouns
#
# **The engine bolds; the files do not.** Bolding is the only signal that
# a noun can be typed, and a hand-written pair of asterisks is a claim
# about the world that only the engine can check: a word is typeable
# when something in the room answers to it, which depends on the room,
# the drop and what the player has unlocked. So the prose is written
# plain and marked on the way out.
#
# The pure half of that lives here, in the module with no project
# imports, because two callers need exactly the same rule and they are
# on opposite sides of the import graph: `reach`, which marks against
# what a player can reach, and the checks below, which ask the files
# whether every thing in a room is named somewhere a player will read.
# It was written twice before this, and the two copies disagreed inside
# an afternoon.
# --------------------------------------------------------------------------


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Players type "Alexa," and "blue-door" and "the cat food". Matching on
    the raw string would refuse all three, and each refusal reads like the
    thing is not there rather than like a typo. `reach` resolves what was
    typed against the same function, which is what makes a marked word a
    promise: if it is bold, typing it works.
    """
    folded = unicodedata.normalize("NFKD", text).casefold()
    kept = [c if c.isalnum() or c.isspace() else " " for c in folded]
    return " ".join("".join(kept).split())


# **The cat is never marked, and she is the only thing that never is.**
# Every other rule here is about what a word means; this one is about how
# often it turns up. She is in reach in every room and the subject of most
# sentences in the game, so marking her everywhere spends the emphasis that
# should be pointing at the wasp nest and the cat bed. She needs no
# advertising either: `/pet` is on the command list, and a player who has
# read one line about her knows she is there.
#
# It lives here rather than in `reach` because the checks below have to
# agree with it: a thing nothing may ever mark cannot be required to be
# marked somewhere.
NEVER_MARKED = frozenset({"eunoia"})


def markable(name: str, names) -> set[str]:
    """Which of a thing's words may be bolded for it.

    Its own name always, and any alias of two words or more. **A
    single-word alias is a convenience for the parser, not a noun a
    sentence is about**: the front door answers to "out", the road to
    "mud", the farm stand to "wood", a can of food to "can". Marking
    those bolds half the words in a paragraph and teaches none of them.

    A longer alias is specific enough to be the thing - "plank bin",
    "door-hardware manual" - and is how a thing still gets marked when
    the prose never says its name.
    """
    own = normalise(name)
    marked = {own} if own else set()
    marked.update(
        phrase
        for phrase in (normalise(n) for n in names)
        if phrase and " " in phrase
    )
    return marked


# Which gaps may sit inside one phrase. A name can be written with a
# hyphen or an apostrophe and still be one noun - "door-hardware manual",
# "cat's bowl" - but a full stop or a comma ends it, so a window that
# spans one is two phrases that happen to be adjacent.
_INSIDE_A_PHRASE = set(" -'’")




def _words(text: str) -> list[tuple[int, int, str]]:
    """(start, end) for every run of letters or digits, in order."""
    return [(m.start(), m.end()) for m in re.finditer(r"[^\W_]+", text)]


def _one_phrase(text: str, start: int, end: int, words: list[tuple[int, int]]) -> bool:
    """Whether the words between these offsets read as a single phrase."""
    inside = [w for w in words if w[0] >= start and w[1] <= end]
    for (_, left), (right, _) in zip(inside, inside[1:]):
        if set(text[left:right]) - _INSIDE_A_PHRASE:
            return False
    return True


def _phrases_in(text: str, longest: int) -> set[str]:
    """Every phrase of up to `longest` words that `mark` could bold here.

    The same windows `mark` sweeps, under the same two rules - never
    inside an existing pair of asterisks, and the words must read as one
    phrase - normalised and collected in one pass.

    **It exists because the windows do not depend on the phrase.**
    `marked_in_room` asks "is this thing pointed at anywhere here" of
    every phrase in a room against every sentence in it, and asking it
    through `mark` re-swept the sentence once per phrase: ten thousand
    full sweeps for ten rooms, which was 4.6 of the 4.6 seconds
    `validate` spent on the files. Enumerating the windows once and
    looking the phrases up in the result asks the same question of the
    same rules.

    **Nothing here consumes the text, and that is what makes it
    equivalent.** `mark` takes the longest phrase first and then refuses
    any span inside one it has already taken, so answering this question
    by simulating a single `mark` over every phrase at once - the
    optimisation it obviously looks like - gives a different answer:
    "cat food" nested inside "tuna cat food" comes back unmarked, where
    asking about it on its own says marked. Windows here are collected
    independently, so both land in the set and the nested phrase is
    still found. Anything that reintroduces consuming breaks this, and
    it will pass a casual reading on the way.

    **A window of k word-runs always normalises to k words**, which is
    the invariant `longest` rests on: `_words` matches runs of letters
    and digits and `normalise` keeps every one of them, so
    "door-hardware manual" is three of each and "cat's" is two. A phrase
    longer than `longest` therefore cannot answer any window, and
    sweeping wider would only turn up phrases nobody can look up. A
    change to `normalise` that dropped a token would narrow this sweep
    silently.
    """
    words = _words(text)
    found: set[str] = set()
    for size in range(min(longest, len(words)), 0, -1):
        for i in range(len(words) - size + 1):
            start, end = words[i][0], words[i + size - 1][1]
            if text[max(0, start - 2):start] == "**" or text[end:end + 2] == "**":
                continue
            if not _one_phrase(text, start, end, words):
                continue
            found.add(normalise(text[start:end]))
    return found


def mark(
    text: str,
    known: dict[str, str],
    *,
    names: "frozenset[str] | set[str]" = frozenset(),
    already: set[str] | None = None,
) -> str:
    """Bold each phrase in `text` that `known` maps to a thing.

    **A thing's own name wins over any alias of it**, which is what
    `names` is for, and it is not a preference - it is the difference
    between marking the right word and the wrong one. The farm stand's
    prose reads "Empty shelves line the back … still offers sweet corn,
    blueberries and brown eggs", and `shelves` answers to all four. A
    sweep that only took the longest phrase first marked **sweet corn**,
    spent the shelves' one mark on it, and left the word "shelves" plain
    - advertising produce that has not been there for years and leaving
    "blueberries" unmarked between two that were.

    So names are offered first, in one pass, and aliases get what is
    left in a second. Within a pass the longest phrase wins, so "cat
    bowl" beats "bowl"; once per thing, because the second mention of
    the sofa is the same sofa and bolding it again is only louder; and
    never inside an existing pair of asterisks, so running this twice
    changes nothing.

    `already` carries "once per thing" across more than one call, and is
    updated as marks are made. A room's description is five rows and one
    paragraph, so the sentence that names the road second is reading the
    same road the first one marked.

    Matching is done on `normalise`d windows of words rather than on the
    raw string, which is what lets the files say "door-hardware manual"
    and the parser say `door hardware manual` and both mean the one thing.
    """
    if not text or not known:
        return text
    words = _words(text)
    longest = max(len(phrase.split()) for phrase in known)
    marked = set() if already is None else already
    # **A thing bolded here already counts as marked.** Nothing in the
    # files is hand-marked any more, so this is not for the writers: it
    # is what makes running the marker over its own output a no-op, and
    # it is what kept the transition honest. While the asterisks were
    # still in the files, "dirt **road**" could not be re-marked as one
    # phrase - the asterisks sit inside the window - so the road went
    # unregistered and the next fragment bolded "road" a second time.
    for phrase in _bolded_in(text):
        thing_id = known.get(normalise(phrase))
        if thing_id is not None:
            marked.add(thing_id)
    spans: list[tuple[int, int]] = []
    for wanted_a_name in (True, False):
        for size in range(min(longest, len(words)), 0, -1):
            for i in range(len(words) - size + 1):
                start, end = words[i][0], words[i + size - 1][1]
                if any(not (end <= a or start >= b) for a, b in spans):
                    continue
                if text[max(0, start - 2):start] == "**" or text[end:end + 2] == "**":
                    continue
                if not _one_phrase(text, start, end, words):
                    continue
                phrase = normalise(text[start:end])
                if (phrase in names) is not wanted_a_name:
                    continue
                thing_id = known.get(phrase)
                if thing_id is None or thing_id in marked:
                    continue
                marked.add(thing_id)
                spans.append((start, end))
    for start, end in sorted(spans, reverse=True):
        text = f"{text[:start]}**{text[start:end]}**{text[end:]}"
    return text


def marked_in_room(content: "Content") -> dict[str, set[str]]:
    """Which things the marker would bold somewhere a player reads, by room.

    **The prose of a room is more than the room's own paragraph.** It is
    the fragments plus the look and use text of everything standing in
    it, and a noun bolded in any of them teaches the same word - the
    ditch and the ruts are named by the road's description, the wasp
    nest by the branches'. So "is it ever pointed at here" is one
    question asked across all of it.

    This is the files' half of what `reach.mark_nouns` does per player.
    It cannot be the same function - that one needs a database and this
    one must not - but it is the same `markable` rule and the same
    ambiguity rule underneath, which is the only way the check and the
    behaviour can be held together.
    """
    rooms = [room.room_id for room in content.rooms]
    # room -> phrase -> the things here that answer to it
    answers: dict[str, dict[str, set[str]]] = {}
    for thing in content.things:
        if not thing.room_id or thing.thing_id in NEVER_MARKED:
            continue
        where = rooms if thing.room_id == EVERYWHERE else [thing.room_id]
        for room_id in where:
            here = answers.setdefault(room_id, {})
            for phrase in markable(thing.name, thing.names):
                here.setdefault(phrase, set()).add(thing.thing_id)

    prose = {
        room_id: _prose_of_room(content, room_id)
        for room_id in {row.entity_id for row in content.room_text}
        | {
            thing.room_id
            for thing in content.things
            if thing.room_id and thing.room_id != EVERYWHERE
        }
    }

    marked: dict[str, set[str]] = {}
    for room_id, texts in prose.items():
        here = answers.get(room_id, {})
        # Only the words one thing answers to; a shared word is a prompt
        # rather than a mark, so it teaches nothing and is not counted.
        known = {p: next(iter(v)) for p, v in here.items() if len(v) == 1}
        found = marked.setdefault(room_id, set())
        if not known:
            continue
        longest = max(len(phrase.split()) for phrase in known)
        for text in texts:
            if not text:
                continue
            # **A phrase the writer bolded by hand is already spent.**
            # `mark` registers it before the sweep begins and then
            # declines to mark the same thing twice, so asking through
            # `mark` answered no for it - and this has to answer no too.
            spent = {normalise(phrase) for phrase in _bolded_in(text)}
            for phrase in (known.keys() & _phrases_in(text, longest)) - spent:
                found.add(known[phrase])
    return marked


def _prose_of_room(content: "Content", room_id: str) -> list[str]:
    """Every sentence a player standing in this room can read.

    The room's own fragments, and the look and use text of the things
    standing in it. A noun bolded in any of them teaches the same word.
    """
    texts = [
        row.text.get("look") or ""
        for row in content.room_text
        if row.entity_id == room_id
    ]
    things = content.things_by_id
    for row in content.thing_text:
        thing = things.get(row.entity_id)
        if thing is None or thing.room_id != room_id:
            continue
        texts += [row.text.get("look") or "", row.text.get("use") or ""]
    return [text for text in texts if text]


def _says(text: str, phrase: str) -> bool:
    """Whether this prose contains this phrase as whole words.

    Asked through `mark` rather than with a regular expression of its
    own, so that the one thing the checker promises - the marker will
    bold this - is answered by the marker.
    """
    return mark(text, {phrase: "it"}) != text


def _bolded_in(text: str) -> list[str]:
    """Every phrase the writer bolded, lowercased and tidied.

    Trailing punctuation is stripped because a sentence can end on a
    bolded noun - `**fence**.` is the fence, and a check that said
    otherwise would teach the writers to avoid bolding at a full stop.
    """
    return [
        phrase.strip().strip(".,;:!?'\"").lower()
        for phrase in _BOLDED.findall(text or "")
    ]


# The verbs whose success line is posted to the room rather than sent to
# the player who typed it. Both are read by everybody present, so both
# have to name whoever acted.
PUBLIC_VERBS = ("take", "drop")

# And the one `use` that is posted rather than sent. The staircase is
# collective, so the whole room reads the line instead of the player
# who laid the board - which `world` decides, not the files, so the
# id is named here the way `world` names it there.
PUBLIC_USE_THINGS = frozenset({"lumber"})


def _check_public_lines_name_the_player(content: Content) -> list[str]:
    """A `take` or `drop` string must say who did it.

    **These two are the only texts in the game with an audience other
    than the person who typed the command**, and for a release they did
    not know it: every one was written in the second person - "You
    pocket the spice jar" - and posted to the room, which told everyone
    present that *they* had picked something up.

    All thirty-two were rewritten. This is what stops the thirty-third
    arriving in the old voice, which is the easy mistake to make: every
    other text in these files is second person and correct to be.

    Checked on `{player}` rather than on the absence of "you", because
    the token is the thing that makes the line true for its audience,
    and a writer who has used it has understood who is reading.
    """
    return [
        f"{row.entity_id} has a {verb} text with no {{player}} in it: "
        f"{verb} lines are posted to the room, so they name who acted "
        "rather than addressing them as 'you'"
        for row in content.thing_text
        for verb in PUBLIC_VERBS
        if row.text.get(verb) and "{player}" not in row.text[verb]
    ]


def _check_a_public_use_names_the_player(content: Content) -> list[str]:
    """The staircase's `use` text has the room for its audience.

    **The third text in the game that is read by somebody other than the
    player who typed the command**, and the newest: the plank's line
    stopped being sent privately on 30 October and is now posted to the
    room and nowhere else. The check above has held `take` and `drop` to
    this since the release where all thirty-two of them said "you" to a
    room full of people; a `use` in that voice would do the same thing
    to everybody standing in the Entryway.

    Named by id rather than derived, because nothing in the files says
    which uses are public - `world._place_a_plank` does, and this is the
    only one.
    """
    return [
        f"{row.entity_id} has a use text with no {{player}} in it, and its "
        "use is posted to the room: name who laid the plank rather than "
        "addressing whoever reads it as 'you'"
        for row in content.thing_text
        if row.entity_id in PUBLIC_USE_THINGS
        and row.text.get("use")
        and "{player}" not in row.text["use"]
    ]


def _check_other_lines_are_not_second_person(content: Content) -> list[str]:
    """A default keyed `.other` is about a third party, so it cannot say "you".

    **The same mistake as the take and drop lines, one file along.**
    Every relationship band was written for the one person reading it,
    and `/stats @somebody` shows them to a second person about a third:
    *the cat adores you*, printed under Max's name, to Alice. The fix
    was a parallel set of nine; this is what stops the tenth arriving in
    the first person's voice.

    The suffix is the whole rule, so it costs nothing to extend: any key
    ending `.other` is a line about somebody who is not reading it.
    Checked on "you" rather than on the presence of a token, because
    unlike a `take` line these are not all required to name anybody -
    *the cat is mildly irritated* is correct for either audience and
    needs no substitution.
    """
    return [
        f"default {key!r} ends in .other, so it is shown to somebody about "
        "another player, but it says 'you': write it about them instead"
        for key, text in content.defaults.items()
        if key.endswith(".other")
        and re.search(r"\byou(r|rs|rself)?\b", text, re.IGNORECASE)
    ]


def _check_visibility_gates(content: Content) -> list[str]:
    """`visible_when` must name a gate the engine actually answers.

    **The enum has one member, which is exactly why this check exists.**
    A typo in that one word does not raise anything: the fragment loads,
    the gate never matches, and the sentence is invisible to every
    player forever. Nothing logs it and no test that does not know the
    text would notice.

    The second member, whenever somebody needs one, is a line in
    `VISIBILITY_GATES` and a branch in `bot._unlocked_for`. Adding it in
    one place and not the other fails here.
    """
    return [
        f"room text for {row.entity_id} fragment {row.fragment} is gated on "
        f"{row.visible_when!r}, which is not a visibility gate; the gates are "
        f"{', '.join(sorted(VISIBILITY_GATES))}"
        for row in content.room_text
        if row.visible_when and row.visible_when not in VISIBILITY_GATES
    ]


def _check_scenery_aliases_are_unique(content: Content) -> list[str]:
    """A scenery word must mean one thing anywhere a player could stand.

    Stricter than `_check_aliases`, and only for scenery. That check is
    scoped to one room because a player is only ever standing in one, and
    the house leans on it: `doorway` names twelve different exits, `cat
    food` nine rows, and every one of those is deliberate.

    **Scenery cannot have quite that latitude, for two reasons.** The bag
    travels, so a word that is also something a player can pick up is
    ambiguous the moment anyone walks outdoors holding one - that is how
    `wire` on the fence would have collided with the copper wire the day
    drop 3 let a player carry it into the channel. And the channel is
    the first outdoors of several: drop 3 brings an outdoor Entryway,
    drop 5 a Courtyard, and the field may one day hold Christmas trees,
    at which point `tree` means two things in one view. A duplicate
    resolves to whichever row sorts first and logs nothing.

    **But those two reasons name a scope, and it is not the whole
    table.** This check first read "must mean nothing else anywhere",
    which is wider than either argument supports and wider than the
    house can bear: the stand's `shelves` collide with the Library's,
    the Sewing Room's and the Nursery's, its `bin` with the Kitchen
    trash can, its `board` with the bulletin board - every one of them a
    fixture bolted to a room the channel has no view of, and `/look` is
    scoped to the room the player is in. Enforcing it there would have
    cost the stand its shelves to protect against a confusion no player
    could have.

    So the scope is what can actually share a view: things that can be
    carried into the room, and things already in it. `wire` still fails
    on the carriable copper wire; a Christmas tree in the field would
    still fail on anything else outdoors with it.
    """
    # Only two kinds of row can turn up beside a piece of scenery: one a
    # player carried in, and one that lives there.
    travellers: dict[str, set[str]] = {}
    residents: dict[str, dict[str, set[str]]] = {}
    for thing in content.things:
        for name in thing.names:
            word = name.lower()
            if thing.takeable:
                travellers.setdefault(word, set()).add(thing.thing_id)
            if thing.room_id:
                residents.setdefault(thing.room_id, {}).setdefault(
                    word, set()
                ).add(thing.thing_id)

    problems = []
    for thing in content.things:
        if thing.type not in SCENERY_TYPES:
            continue
        here = residents.get(thing.room_id, {})
        for name in thing.names:
            word = name.lower()
            clash = (travellers.get(word, set()) | here.get(word, set()))
            others = sorted(clash - {thing.thing_id})
            if others:
                problems.append(
                    f"scenery {thing.thing_id} answers to {word!r}, and so "
                    f"does {', '.join(others)}; a scenery word has to mean "
                    "one thing in any view it can appear in"
                )
    return problems


def _check_no_hand_written_bolding(content: Content) -> list[str]:
    """No asterisks in the prose. The engine puts them there.

    **This check replaced one that did the opposite.** Until the marker
    existed, bolding was written by hand and a checker stood over it
    making sure every bolded word named something real in that room at
    that drop. It caught typos and deleted rows, and it could not catch
    the rest: a word that should have been bolded and was not is
    invisible to a rule that only reads what is already marked, and a
    room's worth of nouns went unmarked for a release because nobody
    noticed the absence of something.

    So the prose is plain now and `mark` bolds it on the way out, which
    makes a hand-written pair of asterisks a claim competing with the
    engine's. Two marks on one thing, or a mark on a word the engine
    knows is ambiguous, and the player is being promised something that
    is not true. Easier to say: the files do not do this any more.

    Emphasis that is not a noun has nowhere to live here, and that is
    deliberate - the three places the game does emphasise are house
    strings in `defaults.tsv`, which this does not touch.
    """
    problems = []
    for row in content.room_text:
        if "**" in (row.text.get("look") or ""):
            problems.append(
                f"room {row.entity_id} fragment {row.fragment} has bolding "
                "written into it; the engine marks the nouns now, so take "
                "the asterisks out and it will bold what it can reach"
            )
    for row in content.thing_text:
        for field_name in ("look", "use"):
            if "**" in (row.text.get(field_name) or ""):
                problems.append(
                    f"{row.entity_id} {field_name} text has bolding written "
                    "into it; the engine marks the nouns now, so take the "
                    "asterisks out and it will bold what it can reach"
                )
    return problems


def parked_achievements(content: Content) -> set[str]:
    """Achievement ids written but not scheduled.

    `NEVER` is not a drop; it is the file saying "approved, not yet".
    These rows can never be awarded, so they are the ones allowed to
    have no trigger behind them yet - see
    `achievements.registration_problems`.
    """
    return {
        row.achievement_id for row in content.achievements if row.since_drop == NEVER
    }


def naming_notes(content: Content) -> list[str]:
    """Things the prose points at by an alias rather than by their name.

    **Not a problem, and deliberately not one.** The marker takes an
    alias of two words or more when a thing's own name is not in the
    sentence, so these all work: the firewood bin is reached through
    "plank bin", and a player who types either gets it.

    It is worth printing anyway. A name that differs from what the prose
    calls the thing is a small debt - it reads oddly in the spreadsheet,
    it is the thing most likely to go stale when the prose is rewritten,
    and four of these were the only marks lost when bolding moved to the
    engine. A list a writer can work through beats a wall they have to
    argue with, which is why this is printed rather than raised.
    """
    marked = marked_in_room(content)
    notes = []
    for thing in content.things:
        if not thing.room_id or thing.room_id == EVERYWHERE:
            continue
        if thing.thing_id not in marked.get(thing.room_id, set()):
            continue
        own = normalise(thing.name)
        texts = _prose_of_room(content, thing.room_id)
        if any(_says(text, own) for text in texts):
            continue
        reached = sorted(
            phrase
            for phrase in markable(thing.name, thing.names)
            if phrase != own and any(_says(text, phrase) for text in texts)
        )
        notes.append(
            f"{thing.room_id} {thing.thing_id}: the prose never says "
            f"{thing.name!r}; it is reached by {reached}"
        )
    return notes


def _check_unlisted_things_are_named_in_prose(content: Content) -> list[str]:
    """What the engine will not list, some sentence has to name.

    **The rule the house has always followed, written down.** `Also
    here:` carries finite takeables and nothing else, because the engine
    knows where those are and the prose would go stale naming them. Every
    other kind of thing in a room is the room, and the description is
    what reveals it. Sources have had that enforced since 2b and scenery
    since drop 1's channel; fixtures are the third kind and the only one
    the loader never checked, which worked only because the writers
    happened to name all ninety-odd of them.

    The channel was the exception and is not one any more: it listed its
    fixtures while it had no prose to name them with, and now that it has
    prose it lists what every other room lists.

    **Asked of `takeable`, not of `fixture`.** The rule is about the
    listing, and the listing goes by whether a thing can be carried - so
    reading the kind instead held only while the two agreed. The
    shipping box is the row where they parted: a `toy`, because the cat
    plays with it, and furniture to the engine, which is why the
    Entryway's own prose has always described it against the wall. Keyed
    on the kind, the box would have slipped out of this check on the day
    its type changed, and the guarantee would have lapsed in silence.

    The reading glasses come in the same way, and the three kinds that
    have their own stricter checks stay out.

    **Naming, not bolding** - unlike scenery. Bolding is the stronger
    contract and the house will want it before drop 3 opens, but no house
    room text is bolded yet, so requiring it here would fail on every
    room and stop the boot over work that is scheduled rather than
    missing. This check pins the half that is already true, and tightens
    to bolding when the writers' pass lands.

    Named in the room's own description, or in the `look` or `use` of
    something else whose home is that room - the nesting the house is
    built on, where `road.look` reveals the ruts and `branches.look` the
    wasp nest.
    """
    # Keyed by the room and by who wrote the sentence, because a thing
    # may not reveal itself: half the fixtures in the house say their own
    # name somewhere in their own `look`, and counting that would pass
    # every row in the table while proving nothing.
    readable: dict[str, dict[str, list[str]]] = {}
    for row in content.room_text:
        readable.setdefault(row.entity_id, {}).setdefault("", []).append(
            row.text.get("look", "")
        )

    things = content.things_by_id
    for row in content.thing_text:
        thing = things.get(row.entity_id)
        if thing is None or not thing.room_id:
            continue
        here = readable.setdefault(thing.room_id, {}).setdefault(row.entity_id, [])
        here += [row.text.get("look") or "", row.text.get("use") or ""]

    problems = []
    for thing in content.things:
        if thing.takeable or not thing.room_id:
            continue
        if thing.type in {"exit", "source"} | SCENERY_TYPES:
            # Each of these is already held to something stricter: an
            # exit is reached by `/go` and listed among them, a source
            # must be named in its container's text for the right state,
            # and scenery must be bolded rather than merely named.
            continue
        if thing.room_id == EVERYWHERE:
            continue
        others = readable.get(thing.room_id, {})
        prose = " ".join(
            line
            for writer, lines in others.items()
            if writer != thing.thing_id
            for line in lines
        ).lower()
        if not any(re.search(rf"\b{re.escape(name.lower())}\b", prose)
                   for name in thing.names):
            problems.append(
                f"{thing.type} {thing.thing_id} is named nowhere a player "
                f"in room {thing.room_id} can read; only takeables are "
                "listed, so no player could learn it is there"
            )
    return problems


def _check_scenery_is_named_in_prose(content: Content) -> list[str]:
    """Scenery is never listed, so the prose that reveals it has to bold it.

    The same argument as `_check_sources_are_named_in_prose`, one type
    along. Scenery was added so that `/look` answers to what the
    description points at, and the item list carries finite takeables
    and nothing else - a channel listing "a road, a fog, a ditch, a cat
    bed" buries the one noun worth typing. Which leaves bolding as the
    only way a player learns the ditch is there.
    An unbolded scenery row is not merely unpolished: it is a row no
    player will ever reach.

    It may be bolded by its room, or by another thing in the same room -
    the ditch and the ruts are named by the road's own description, the
    wasp nest by the branches. That is the intended shape: a few nouns
    in the paragraph, each opening onto two or three more.
    """
    marked = marked_in_room(content)

    problems = []
    for thing in content.things:
        if thing.type not in SCENERY_TYPES or not thing.room_id:
            continue
        if thing.thing_id in marked.get(thing.room_id, set()):
            continue
        reachable = markable(thing.name, thing.names)
        problems.append(
            f"nothing in room {thing.room_id} names scenery "
            f"{thing.thing_id} in a word the engine can bold, so no player "
            f"could learn it is there; it would answer to {sorted(reachable)}"
            if reachable
            else f"scenery {thing.thing_id} has no markable name at all"
        )
    return problems


def version(directory: Path | None = None) -> str:
    """A short name for exactly this set of content files.

    **The config history only sees what lives in config**, and the
    numbers that will move most often - the per-thing relationship
    deltas, the restock rates, every string - live in TSVs instead. So
    a content deploy writes one row too, and that row dates every file
    at once.

    Railway's commit hash where there is one, because it names a diff
    somebody can read. A digest of the files themselves otherwise,
    which covers local runs and, more usefully, a content reload that
    did not come from a deploy at all - the case a commit hash alone
    would miss.
    """
    sha = os.getenv("RAILWAY_GIT_COMMIT_SHA", "").strip()
    if sha:
        return f"git:{sha[:12]}"

    digest = hashlib.sha256()
    for path in sorted((directory or CONTENT_DIR).glob("*.tsv")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return f"files:{digest.hexdigest()[:12]}"


def load(directory: Path | None = None) -> Content:
    """Parse and validate. Raises ContentError listing everything wrong."""
    content = load_files(directory)
    problems = validate(content)
    if problems:
        raise ContentError(problems)
    return content
