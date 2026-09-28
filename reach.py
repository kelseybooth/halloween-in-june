"""Working out which thing a player meant, and which copy of it to act on.

Every command that names a thing runs the same two passes. Pass one settles
*which thing*; pass two settles *which copy*. The functional spec calls this the
most reused piece of logic in the bot, so it is built once, here, and the verbs
call into it rather than each growing their own version.

Two rules carry most of the weight.

**Scope is set before pass one runs, and it depends on the verb.** A command can
only act on things it could act on, so the candidate set is narrowed first and
both passes work inside it. `/take` never sees the bag; `/drop` never sees the
room. Widening either is the easiest way to reintroduce the bug in Scope below.

**A source and the object it yields are one thing.** The chicken stash under the
sofa and a can of chicken in your bag are the same thing in two places. Without
this a player standing by the stash holding a can is asked "chicken or chicken?"
every time.
"""

from __future__ import annotations

import enum
import unicodedata
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

import database
import resolve
import states


class Scope(enum.Enum):
    """Which places a verb is allowed to act on.

    The bug this exists to prevent: a player carrying chicken, standing beside
    the salmon cupboard, types `/take cat food`. With the bag in scope, pass one
    sees two things and asks "chicken or salmon?" - and if they say chicken,
    there is no chicken in the room to take. The question was never answerable.
    Scoped to the room there is one candidate and the salmon goes in the bag.
    `/drop` has the same fault mirrored.
    """

    ROOM = "room"  # /take
    CARRIED = "carried"  # /drop
    REACH = "reach"  # /use, /look - carried first, then the room


class Where(enum.Enum):
    """Which of the three places a copy was found in, in pass-two order."""

    CARRIED = "carried"
    ROOM = "room"
    SOURCE = "source"


@dataclass(frozen=True)
class Found:
    """One thing, and the copy of it the verb should act on."""

    thing_id: str
    name: str
    where: Where
    count: int
    container_id: str | None = None
    # Set when the copy is a source: the object it hands over, which is what the
    # player ends up holding and whose `take` text the reply uses.
    yields: str | None = None
    # And which source it was. `thing_id` cannot answer that: a source and its
    # yield are filed as one thing, so taking herbs from the herb garden and
    # picking up herbs somebody dropped both report `thing_id = "herbs"`. Only
    # the first is gardening, which is the distinction *Green Thumb* turns on.
    source_id: str | None = None

    @property
    def is_source(self) -> bool:
        return self.where is Where.SOURCE


@dataclass(frozen=True)
class Ambiguous:
    """Several distinct things matched. Nothing is acted on until one is named."""

    options: list[str]


@dataclass(frozen=True)
class NotFound:
    """Nothing in scope matched.

    `exists_elsewhere` distinguishes a name the game knows from one it does not,
    which is the difference between "You don't see a spice jar here" and not
    recognising the word at all. `carried` marks the case `/take` needs: nothing
    in the room, but the player is already holding one, where take_fail.absent
    would be a lie.
    """

    typed: str
    exists_elsewhere: bool = False
    carried: bool = False


Resolution = Found | Ambiguous | NotFound


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Players type "Alexa," and "blue-door" and "the cat food". Matching on the raw
    string would refuse all three, and each refusal reads like the thing is not
    there rather than like a typo.
    """
    folded = unicodedata.normalize("NFKD", text).casefold()
    kept = [c if c.isalnum() or c.isspace() else " " for c in folded]
    return " ".join("".join(kept).split())


def _names_of(name: str, aliases) -> set[str]:
    return {normalise(n) for n in (name, *(aliases or [])) if n and normalise(n)}


@dataclass
class _Candidate:
    """A thing in reach, with every copy of it that was found."""

    thing_id: str
    name: str
    names: set[str]
    copies: dict[Where, tuple[int, str | None]]  # where -> (count, container)
    yields: str | None = None
    # The source that put the SOURCE copy here, set with it and never apart.
    source_id: str | None = None


async def _gather(
    guild_id: int, user_id: int, room_id: str, scope: Scope, today: date | None
) -> dict[str, _Candidate]:
    """Everything in scope, grouped into one entry per distinct thing.

    Grouping is by the object a thing resolves to: a source is filed under what
    it yields, so the stash and the can it hands out are one candidate. That is
    what stops the "chicken or chicken?" prompt.
    """
    visible = await resolve.visible_thing_ids(guild_id, today=today)
    # Gates are per player, so two people standing in the same room can be
    # looking at different things - one has unjammed the drawer and one has not.
    held = await states.in_force(guild_id, user_id)
    session_factory = database._require_session()

    async with session_factory() as session:
        in_room = (
            await session.execute(
                select(
                    database.ThingType.thing_id,
                    database.ThingType.name,
                    database.ThingType.aliases,
                    database.ThingType.type,
                    database.ThingType.yields,
                    database.ThingType.contained_in,
                    database.ThingType.present_when,
                    database.ThingType.quantity,
                ).where(database.ThingType.room_id == room_id)
            )
        ).all()

        stock = {
            row[0]: (row[1], row[2])
            for row in await session.execute(
                select(
                    database.RoomContents.thing_id,
                    database.RoomContents.count,
                    database.RoomContents.container_id,
                ).where(
                    database.RoomContents.guild_id == guild_id,
                    database.RoomContents.room_id == room_id,
                    database.RoomContents.count > 0,
                )
            )
        }

        carried = {
            row[0]: row[1]
            for row in await session.execute(
                select(
                    database.PlayerInventory.thing_id, database.PlayerInventory.count
                ).where(
                    database.PlayerInventory.guild_id == guild_id,
                    database.PlayerInventory.user_id == user_id,
                    database.PlayerInventory.count > 0,
                )
            )
        }

        # Sources are filed under what they yield, so those objects have to be
        # looked up too - they are usually roomless and hold no stock, so nothing
        # else here would fetch them, and the group would end up displaying the
        # furniture's name instead of the object's.
        wanted = (
            set(stock)
            | set(carried)
            | {row[0] for row in in_room}
            | {row[4] for row in in_room if row[3] == "source" and row[4]}
        )
        rows = (
            await session.execute(
                select(
                    database.ThingType.thing_id,
                    database.ThingType.name,
                    database.ThingType.aliases,
                    database.ThingType.type,
                    database.ThingType.yields,
                    database.ThingType.present_when,
                ).where(database.ThingType.thing_id.in_(wanted or {""}))
            )
        ).all()
        details = {row[0]: row[:5] for row in rows}
        gates = {row[0]: row[5] for row in rows}

    candidates: dict[str, _Candidate] = {}

    def entry(key: str, name: str, names: set[str], yields: str | None = None) -> _Candidate:
        found = candidates.get(key)
        if found is None:
            found = _Candidate(thing_id=key, name=name, names=set(names), copies={}, yields=yields)
            candidates[key] = found
        else:
            found.names |= names
            found.yields = found.yields or yields
        return found

    include_room = scope in (Scope.ROOM, Scope.REACH)
    include_bag = scope in (Scope.CARRIED, Scope.REACH)

    if include_bag:
        for thing_id, count in carried.items():
            if thing_id not in visible or thing_id not in details:
                continue
            _, name, aliases, _kind, _y = details[thing_id]
            entry(thing_id, name, _names_of(name, aliases)).copies[Where.CARRIED] = (
                count,
                None,
            )

    if include_room:
        for thing_id, (count, container) in stock.items():
            if thing_id not in visible or thing_id not in details:
                continue
            if not states.passes(gates.get(thing_id), held):
                continue
            _, name, aliases, _kind, _y = details[thing_id]
            entry(thing_id, name, _names_of(name, aliases)).copies[Where.ROOM] = (
                count,
                container or None,
            )

        for thing_id, name, aliases, kind, yields, contained_in, gate, quantity in in_room:
            if thing_id not in visible or not states.passes(gate, held):
                continue
            if kind == "source" and yields:
                # Filed under what it hands over, so the stash and its cans are
                # one thing. The source's own names match it too.
                target = details.get(yields)
                display = target[1] if target else name
                names = _names_of(name, aliases)
                if target:
                    names |= _names_of(target[1], target[2])
                candidate = entry(yields, display, names, yields=yields)
                if Where.SOURCE not in candidate.copies:
                    # Set together, so the id always names the source this copy
                    # actually came from. Two sources of one yield in one room
                    # would collapse here, and the first would win - no content
                    # does that today, and the reply would be identical anyway.
                    candidate.copies[Where.SOURCE] = (1, contained_in or None)
                    candidate.source_id = thing_id
            elif kind in ("fixture", "exit"):
                entry(thing_id, name, _names_of(name, aliases)).copies.setdefault(
                    Where.ROOM, (1, contained_in or None)
                )
            elif kind == "object" and quantity is None:
                # `quantity = many` is a shared pool rather than stock - lumber
                # is the only one. It is never placed in room_contents, so
                # without this it would be unreachable and /use lumber could
                # never fire at all.
                entry(thing_id, name, _names_of(name, aliases)).copies.setdefault(
                    Where.ROOM, (1, contained_in or None)
                )
            elif kind == "object" and thing_id not in stock:
                # An object with a room but no stock row left: taken, and gone.
                continue

    return candidates


async def _exists_anywhere(typed: str) -> bool:
    """Whether the game knows this word at all, without saying where.

    Confirming a thing exists somewhere is fine; naming its room would give away
    the Secret Library and the jammed drawer before anyone has found them.
    """
    needle = normalise(typed)
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(database.ThingType.name, database.ThingType.aliases)
        )
        return any(needle in _names_of(name, aliases) for name, aliases in rows)


async def find(
    guild_id: int,
    user_id: int,
    room_id: str,
    typed: str,
    scope: Scope,
    *,
    today: date | None = None,
) -> Resolution:
    """Resolve what a player typed to one thing and one copy of it.

    Returns Found, Ambiguous, or NotFound. Callers branch on the type rather
    than re-deriving any of this.
    """
    needle = normalise(typed)
    if not needle:
        return NotFound(typed=typed)

    candidates = await _gather(guild_id, user_id, room_id, scope, today)
    matches = [c for c in candidates.values() if needle in c.names]

    # Pass one: which thing. More than one and nothing is acted on.
    if len(matches) > 1:
        return Ambiguous(options=sorted(c.name for c in matches))

    if not matches:
        carried_elsewhere = False
        if scope is Scope.ROOM:
            # /take needs to tell "there isn't one here" from "you already have
            # it", because take_fail.absent would be a lie in the second case.
            bag = await _gather(guild_id, user_id, room_id, Scope.CARRIED, today)
            carried_elsewhere = any(needle in c.names for c in bag.values())
        return NotFound(
            typed=typed,
            exists_elsewhere=await _exists_anywhere(typed),
            carried=carried_elsewhere,
        )

    # Pass two: which copy. First hit down the ladder wins.
    candidate = matches[0]
    order = (
        (Where.CARRIED, Where.ROOM, Where.SOURCE)
        if scope is not Scope.ROOM
        else (Where.ROOM, Where.SOURCE)
    )
    for where in order:
        if where not in candidate.copies:
            continue
        count, container = candidate.copies[where]
        return Found(
            thing_id=candidate.thing_id,
            name=candidate.name,
            where=where,
            count=count,
            container_id=container,
            yields=candidate.yields if where is Where.SOURCE else None,
            source_id=candidate.source_id if where is Where.SOURCE else None,
        )

    return NotFound(typed=typed, exists_elsewhere=await _exists_anywhere(typed))
