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
from dataclasses import dataclass, field

from sqlalchemy import select

import content
import database
import resolve
import states
import telemetry


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
    # Set when the thing was reached through a typo rather than one of its own
    # words, as "what was typed → what it matched". Carried so a caller can log
    # it and a wrong guess can be found afterwards.
    fuzzy: str | None = None

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


# How far a typo may sit from the word it meant, and it depends on how long the
# word is. Two edits is the rule the work order gave, and on a long word it is
# the right one: *crincle ball*, *feather wamd*, *cat ber* are all one edit from
# what they meant, and two leaves room for the ones nobody has typed yet.
#
# **On a short word two edits is too many,** because it is most of the word.
# `wire` is two edits from `dirt`, so the fence's own word was reaching the
# road's dirt - a wrong answer to a word three players typed, which is worse
# than the refusal it replaced. Every typo in the beta log that is correctable
# at all is a single edit away, so tightening the short band costs none of them.
FUZZY_DISTANCE = 2
FUZZY_DISTANCE_SHORT = 1

# Where "short" ends. At seven characters two edits is under a third of the
# word, which is the point at which a correction stops being a guess.
FUZZY_LONG_WORD = 7

# Short words are left alone. At three letters two edits is most of the word,
# and *toi* sits that close to *toy* and to several other things at once, so a
# guess there is a coin flip wearing the clothes of understanding.
FUZZY_MIN_LENGTH = 4


def _tolerance(typed: str) -> int:
    """How many edits to forgive in a word this long."""
    return FUZZY_DISTANCE if len(typed) >= FUZZY_LONG_WORD else FUZZY_DISTANCE_SHORT


def _distance(typed: str, word: str, limit: int) -> int | None:
    """Levenshtein distance between two words, or None once it passes `limit`.

    Bailing out early is what keeps this cheap enough to run on every miss: the
    length check alone settles most pairs, and the row loop stops as soon as
    every cell is already too far.
    """
    if abs(len(typed) - len(word)) > limit:
        return None

    previous = list(range(len(word) + 1))
    for i, a in enumerate(typed, start=1):
        current = [i]
        for j, b in enumerate(word, start=1):
            current.append(
                min(
                    previous[j] + 1,  # delete
                    current[j - 1] + 1,  # insert
                    previous[j - 1] + (a != b),  # substitute
                )
            )
        if min(current) > limit:
            return None
        previous = current

    return previous[-1] if previous[-1] <= limit else None


def _nearest(typed: str, candidates) -> tuple[_Candidate, str] | None:
    """The one thing a typo must have meant, or None if that is not clear.

    "Not clear" covers both halves of the rule and the second half is the one
    that matters: nothing close enough, or **two things equally close**. Acting
    on a tie would do something to a thing the player never named, which is a
    worse outcome than a refusal they can read and retype.

    Distance is taken per thing rather than per word, because one thing owns
    several words and only its best one should speak for it.
    """
    if len(typed) < FUZZY_MIN_LENGTH:
        return None

    limit = _tolerance(typed)
    scored = []
    for candidate in candidates:
        near = [
            (distance, name)
            for name in candidate.names
            if (distance := _distance(typed, name, limit)) is not None
        ]
        if near:
            # Sorted, not just min-ed, so a thing with two equally close words
            # picks the same one every time rather than whichever the set
            # happened to yield first.
            distance, name = min(near)
            scored.append((distance, candidate, name))

    if not scored:
        return None

    closest = min(distance for distance, _, _ in scored)
    tied = [(c, name) for distance, c, name in scored if distance == closest]
    return tied[0] if len(tied) == 1 else None


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
    # The same words as `names`, kept apart as well as merged. A source and
    # its yield share most of their vocabulary - `cat food`, `salmon` - and
    # the merge is what stops `/take cat food` asking "chicken or chicken?".
    # But some words belong to one of them alone: `pack` is the pack and not
    # a can out of it. Pass two needs to tell those apart, and `names` has
    # thrown the distinction away by the time it gets there.
    source_names: set[str] = field(default_factory=set)
    yield_names: set[str] = field(default_factory=set)


async def _gather(
    guild_id: int, user_id: int, room_id: str, scope: Scope
) -> dict[str, _Candidate]:
    """Everything in scope, grouped into one entry per distinct thing.

    Grouping is by the object a thing resolves to: a source is filed under what
    it yields, so the stash and the can it hands out are one candidate. That is
    what stops the "chicken or chicken?" prompt.
    """
    visible = await resolve.visible_thing_ids(guild_id)
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
                ).where(
                    # `ALL` is a room nobody stands in: it marks a thing that
                    # is present everywhere. Alexa is the only one, and until
                    # this clause existed no query ever matched her, so the
                    # smart speaker declared to be in every room was reachable
                    # in none of them.
                    database.ThingType.room_id.in_([room_id, content.EVERYWHERE])
                )
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
                mine = _names_of(name, aliases)
                theirs = _names_of(target[1], target[2]) if target else set()
                candidate = entry(yields, display, mine | theirs, yields=yields)
                # Merged above, and kept apart here. Both are needed: the
                # merge is what makes the stash and its cans one thing, and
                # the split is what lets a word only one of them answers to
                # pick that one.
                candidate.source_names |= mine
                candidate.yield_names |= theirs
                if Where.SOURCE not in candidate.copies:
                    # Set together, so the id always names the source this copy
                    # actually came from. Two sources of one yield in one room
                    # would collapse here, and the first would win - no content
                    # does that today, and the reply would be identical anyway.
                    candidate.copies[Where.SOURCE] = (1, contained_in or None)
                    candidate.source_id = thing_id
            elif kind in {"fixture", "exit"} | content.SCENERY_TYPES:
                # Scenery resolves exactly as a fixture does: no stock row,
                # never takeable, always there. It is listed here rather
                # than left to fall through because falling through is
                # silent - the word is bolded in the prose, the player
                # types it, and the house says there is no such thing.
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


async def missing_requirements(
    guild_id: int, user_id: int, room_id: str, thing_ids: list[str]
) -> list[str]:
    """Which of these the player cannot satisfy, in the cell's own order.

    **`requires` used to mean "in your bag", and now means "to hand".**
    A thing you could pick up still has to be carried - that is what the
    can opener is, and the rule has not moved. A thing you could not is
    satisfied by standing in the room with it, which is how the cat bowl
    works: it is a fixture on the Entryway floor, nobody can pocket it,
    and a feed that demanded it in the bag could never happen at all. So
    the split is `takeable`, the column that already says whether a thing
    is the sort you hold.

    **The order of the answer is the order of the cell**, because the
    caller has one refusal string and has to decide which missing item
    it is about. `can_opener|cat_bowl` names the opener first, so a
    player in the kitchen with no bowl hears about the bowl only once
    the opener is in their hand.

    A thing that is everywhere counts as present, which is the cat and
    the smart speaker today. A fixture whose `present_when` this player
    does not hold does not: it is not in the room as far as they can
    tell, and a requirement met by something invisible is a gate with no
    visible way through it.
    """
    if not thing_ids:
        return []
    held_states = await states.in_force(guild_id, user_id)
    session_factory = database._require_session()
    async with session_factory() as session:
        carried = {
            row[0]
            for row in await session.execute(
                select(database.PlayerInventory.thing_id).where(
                    database.PlayerInventory.user_id == user_id,
                    database.PlayerInventory.guild_id == guild_id,
                    database.PlayerInventory.thing_id.in_(thing_ids),
                    database.PlayerInventory.count > 0,
                )
            )
        }
        standing = {
            thing_id
            for thing_id, present_when in await session.execute(
                select(
                    database.ThingType.thing_id, database.ThingType.present_when
                ).where(
                    database.ThingType.thing_id.in_(thing_ids),
                    database.ThingType.takeable.is_(False),
                    database.ThingType.room_id.in_([room_id, content.EVERYWHERE]),
                )
            )
            if states.passes(present_when, held_states)
        }
    to_hand = carried | standing
    return [thing_id for thing_id in thing_ids if thing_id not in to_hand]


async def find(
    guild_id: int,
    user_id: int,
    room_id: str,
    typed: str,
    scope: Scope,
    *,
    action: str | None = None,
    fuzzy: bool = True,
) -> Resolution:
    """Resolve what a player typed to one thing and one copy of it.

    Returns Found, Ambiguous, or NotFound. Callers branch on the type rather
    than re-deriving any of this.

    `action` is the verb this is resolving for, and exists only so that a typo
    corrected on the way through can be logged against it. Left out, nothing is
    logged and the resolution is identical.

    `fuzzy=False` asks for the exact pass alone. `/look` needs that, because it
    has something to try between the two: the name of the room the player is
    standing in, which has to outrank a correction and not be stolen by one.
    """
    needle = normalise(typed)
    if not needle:
        return NotFound(typed=typed)

    candidates = await _gather(guild_id, user_id, room_id, scope)
    matches = [c for c in candidates.values() if needle in c.names]
    # What pass two asks about. It is the typed word, unless a typo was
    # forgiven below - then it is the word that was meant, because `packk`
    # belongs to the source for the same reason `pack` does.
    word = needle

    # Pass one: which thing. More than one and nothing is acted on.
    if len(matches) > 1:
        return Ambiguous(options=sorted(c.name for c in matches))

    correction = None
    if not matches:
        # Pass one again, this time forgiving a typo - and only ever after the
        # exact pass has failed, so a word somebody spelled correctly can never
        # lose to somebody else's near miss.
        near = _nearest(needle, candidates.values()) if fuzzy else None
        if near is None:
            carried_elsewhere = False
            if scope is Scope.ROOM:
                # /take needs to tell "there isn't one here" from "you already
                # have it", because take_fail.absent would be a lie in the
                # second case.
                bag = await _gather(guild_id, user_id, room_id, Scope.CARRIED)
                carried_elsewhere = any(needle in c.names for c in bag.values())
            return NotFound(
                typed=typed,
                exists_elsewhere=await _exists_anywhere(typed),
                carried=carried_elsewhere,
            )

        matched, matched_name = near
        matches = [matched]
        word = matched_name
        correction = f"{needle}→{matched_name}"
        if action is not None:
            # Logged from here rather than from the verbs, because this is the
            # only place that knows a correction happened at all - and it is
            # logged whether or not the verb then goes on to refuse, since a
            # wrong guess is just as findable either way.
            await telemetry.record(
                guild_id, action=action, user_id=user_id, detail=f"fuzzy={correction}"
            )

    # Pass two: which copy. First hit down the ladder wins.
    candidate = matches[0]
    order = (
        (Where.CARRIED, Where.ROOM, Where.SOURCE)
        if scope is not Scope.ROOM
        else (Where.ROOM, Where.SOURCE)
    )

    # **A word only the source answers to means the source.** `pack` is the
    # pack of salmon and not a can out of it, so `/look pack` describes the
    # pack even with a loose can on the floor - and `/take pack` records the
    # stash, which is what tells a harvest from a pickup and what *Green
    # Thumb* turns on. Both were going to the can, because the ladder below
    # was written for the words they share and never asked which kind this
    # was.
    #
    # A shared word - `salmon`, `cat food` - keeps the ladder exactly as it
    # was: the copy in your hands, then the one on the floor, then the
    # source. The player who says `cat food` holding a can means that can.
    if (
        Where.SOURCE in candidate.copies
        and word in candidate.source_names
        and word not in candidate.yield_names
    ):
        order = (Where.SOURCE,) + tuple(w for w in order if w is not Where.SOURCE)
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
            fuzzy=correction,
        )

    return NotFound(typed=typed, exists_elsewhere=await _exists_anywhere(typed))
