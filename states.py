"""States, and the gates that depend on them.

A state is something that has become true: the staircase is repaired, this
player has unjammed the drawer. Content carries two things keyed on them - text
per state, which `resolve` handles, and *visibility* per state, which is
`present_when` and lives here.

Two scopes, and the split is a design decision rather than an accident. A
server state changes the house for everyone, because collective labour earns a
collective reward. A player state changes it for one person, because the
discovery *is* the content - making the jammed drawer server-wide would mean
only the first player ever found it.

`present_when` supports one negation, `!stairs_repaired` on lumber, which is
how a thing disappears once its job is done.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

import content
import database

log = logging.getLogger(__name__)

# Every state the engine knows how to set. content.py validates `present_when`
# against the same names, so a typo in a gate is caught at load rather than
# becoming content that never appears.
# **Both are collective labour earning a collective reward**, which is
# the rule that decides server over player. The staircase takes a plank
# from several people; the front door takes one key, found by one person
# and turned once, and it opens for everybody afterwards.
# `stairs_upper` is drop 20's: the last fifth of the staircase, where
# the steps stop being reachable from the floor. It is a state rather
# than a number read from the count because three different things read
# it the way they read any other state - the lumber's text, the
# staircase's text and the Entryway's seventh fragment - and none of
# them should have to know what 80% of `staircase_planks` is.
#
# Permanent like the other two. A server that lowers `staircase_planks`
# after reaching it keeps it, which is correct: those planks are in.
SERVER_STATES = {"stairs_repaired", "stairs_upper", "house_unlocked", "collar_on"}
PLAYER_STATES = {
    "has_key",
    "passage_open",
    "library_found",
    "drawer_unjammed",
    # The bedroom sash, once a player has rubbed graphite into the
    # runners. Per player and set once, the same shape as the drawer,
    # and for a sharper reason: the sentence that opens the window is
    # the only place the ivy outside it is named, so a window opened
    # for everybody would be a route nobody was told about.
    "window_open",
    # Two flags that gate a message rather than a door. The cat's reaction
    # to a dirty diaper is only funny the first time; both are the same
    # shape as `drawer_unjammed` - set once, never cleared - which is why
    # neither needs a table of its own.
    #
    # **Nothing sets `tutorial_seen` any more.** The tutorial was retired
    # with `/enter` at drop 10, as the copy deck had already settled: the
    # hint rail and the gating replace it. The state stays registered
    # because every player who saw it has a row that names it, and an
    # unknown state is a row that fails to load.
    "tutorial_seen",
    "diaper_seen",
}

# **Which state's text wins when a player holds several.**
#
# Until drop 20 it did not come up: no entity had text for two states a
# player could hold at once, and the callers took `sorted(held)[0]` to
# be deterministic rather than right. Drop 20 broke that by adding
# `stairs_upper` to a server that already holds `house_unlocked` - and
# `house_unlocked` sorts first, so the staircase, the lumber and the
# Entryway's seventh fragment all kept describing a ruin while the
# repair was most of the way up.
#
# Later beats earlier, which is the only general rule that fits: a
# state is something that has become true, so the most recent one is
# the most specific description of the world. `stairs_repaired` beats
# `stairs_upper` beats everything that was already true.
#
# Unknown states sort last, alphabetically, so a state added here
# without a thought about priority still resolves the same way twice.
STATE_PRIORITY = (
    # **First, over `stairs_repaired`, and the ivy is why.** A player who
    # has opened the bedroom window holds both, and the courtyard ivy is
    # written for each: `stairs_repaired` says it climbs to a shut sash
    # with no catch on the outside, `window_open` says they haul
    # themselves in over the sill. Ordered the other way round, opening
    # the window would change nothing a player could see from below -
    # they would climb up to the window they had just opened and be told
    # it was shut.
    #
    # Consistent with the rule rather than an exception to it: the most
    # recent thing to have become true is the most specific description
    # of the world, and the sash moved after the staircase did.
    # **Newest first, and nothing yet depends on it.** The cat is the
    # only entity with a `collar_on` row and she has no text for any
    # other state, so no resolution today can be decided by where this
    # sits. It goes first because the rule says the most recent thing
    # to have become true is the most specific description of the
    # world, and the collar went on after the sash went up - not
    # because anything would read differently the other way round.
    "collar_on",
    "window_open",
    "stairs_repaired",
    "stairs_upper",
    "library_found",
    "passage_open",
    "drawer_unjammed",
    "house_unlocked",
    "has_key",
    "diaper_seen",
    "tutorial_seen",
)


def in_priority_order(
    held: "set[str] | frozenset[str]", room_id: str | None = None
) -> tuple[str, ...]:
    """The states this player holds, most specific first.

    Handed to the resolvers whole rather than collapsed to one, because
    `_best` already walks a sequence: it tries each state in turn and
    falls through to `default`. Passing one state meant an entity with
    text for a *different* held state fell back to `default` and the
    writers' row was never read.

    **The room wins over all of them, when the caller knows it.** A
    state says what has become true of the house and a room says where
    this player is standing, and the one entity written both ways is
    the ladder - six climbs, one per room, and nothing about the
    staircase or the front door changes what you can see from the top
    of it. If a thing ever wants a line for a state *and* a room at
    once, this is the line to argue with.

    Callers that have no room pass none and get exactly what they got
    before. `/go` is one: an exit stands in one room by definition, so
    asking which room the player is in answers nothing.
    """
    ranked = {state: index for index, state in enumerate(STATE_PRIORITY)}
    ordered = tuple(
        sorted(held, key=lambda state: (ranked.get(state, len(ranked)), state))
    )
    if room_id is None:
        return ordered
    return (f"{content.ROOM_STATE_PREFIX}{room_id}", *ordered)


def required_things(requires: str | None) -> list[str]:
    """The parts a `requires` cell names, pipe separated as aliases are.

    `requires` is not a state and does not produce one. It gates `/use` in
    `bot`: an unmet requirement refuses the whole use and replies with the
    thing's `use_fail`, so there is no text keyed on it and nothing recorded.

    A part is usually one thing id and may be an `any of` group - see
    `alternatives`. The parts are returned as written, because the
    caller's refusal text is keyed on what the cell asked for and the
    cell's own order decides which missing part it is about.
    """
    return content.requires_parts(requires)


def alternatives(part: str) -> list[str]:
    """The thing ids one `requires` part will accept, any one of which does.

    `|` is and, `/` is or: `can_opener|cat_bowl` wants both, and
    `used_baby_bottle/sanitized_baby_bottle` wants either. One part, so
    the group is still one requirement for ordering and for the refusal.

    **The split exists because a name cannot do it.** A requirement is
    already met by any thing of the same name, which is how three cat
    bowls answer one `cat_bowl` - but the two bottles are called
    different things on purpose, a used one and a sanitized one, and a
    gate that wanted "a bottle, either kind" had no way to say so.
    Renaming them to match would have been a lie about the objects to
    get a lie past the gate.
    """
    return content.requires_alternatives(part)


def passes(gate: str | None, held: set[str]) -> bool:
    """Whether a `present_when` gate is satisfied by the states in force.

    No gate means always present, which is almost everything. A leading `!`
    inverts: lumber carries `!stairs_repaired` and vanishes once the staircase
    is done.
    """
    if not gate:
        return True
    wanted = gate.strip()
    if wanted.startswith("!"):
        return wanted[1:] not in held
    return wanted in held


async def in_force(guild_id: int, user_id: int) -> set[str]:
    """Every state in force for this player: the server's, plus their own."""
    return await database.states_of(guild_id, user_id)


async def set_server_state(guild_id: int, state: str) -> bool:
    """Make a state true for a whole server. False if it already was.

    Permanent, and idempotent: the staircase does not un-repair, and the
    hundredth plank does not re-announce it.
    """
    if state not in SERVER_STATES:
        raise ValueError(f"{state!r} is not a server state")

    session_factory = database._require_session()
    insert = database._upsert_statement()
    async with session_factory() as session:
        existing = await session.scalar(
            select(database.ServerState.state).where(
                database.ServerState.guild_id == guild_id,
                database.ServerState.state == state,
            )
        )
        if existing is not None:
            return False
        await session.execute(
            insert(database.ServerState)
            .values(guild_id=guild_id, state=state)
            .on_conflict_do_nothing(
                index_elements=[database.ServerState.guild_id, database.ServerState.state]
            )
        )
        await session.commit()

    log.info("Server %s: %s is now true for everyone", guild_id, state)
    return True


async def set_player_state(guild_id: int, user_id: int, state: str) -> bool:
    """Make a state true for one player. False if it already was."""
    if state not in PLAYER_STATES:
        raise ValueError(f"{state!r} is not a player state")

    session_factory = database._require_session()
    insert = database._upsert_statement()
    async with session_factory() as session:
        existing = await session.scalar(
            select(database.PlayerState.state).where(
                database.PlayerState.guild_id == guild_id,
                database.PlayerState.user_id == user_id,
                database.PlayerState.state == state,
            )
        )
        if existing is not None:
            return False
        await session.execute(
            insert(database.PlayerState)
            .values(guild_id=guild_id, user_id=user_id, state=state)
            .on_conflict_do_nothing(
                index_elements=[
                    database.PlayerState.guild_id,
                    database.PlayerState.user_id,
                    database.PlayerState.state,
                ]
            )
        )
        await session.commit()

    log.info("Guild %s, player %s: %s is now true", guild_id, user_id, state)
    return True


async def has(guild_id: int, user_id: int, state: str) -> bool:
    return state in await in_force(guild_id, user_id)
