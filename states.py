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
SERVER_STATES = {"stairs_repaired", "stairs_upper", "house_unlocked"}
PLAYER_STATES = {
    "has_key",
    "passage_open",
    "library_found",
    "drawer_unjammed",
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


def in_priority_order(held: "set[str] | frozenset[str]") -> tuple[str, ...]:
    """The states this player holds, most specific first.

    Handed to the resolvers whole rather than collapsed to one, because
    `_best` already walks a sequence: it tries each state in turn and
    falls through to `default`. Passing one state meant an entity with
    text for a *different* held state fell back to `default` and the
    writers' row was never read.
    """
    ranked = {state: index for index, state in enumerate(STATE_PRIORITY)}
    return tuple(
        sorted(held, key=lambda state: (ranked.get(state, len(ranked)), state))
    )


def required_things(requires: str | None) -> list[str]:
    """The thing ids a `requires` cell names, pipe separated as aliases are.

    `requires` is not a state and does not produce one. It gates `/use` in
    `bot`: an unmet requirement refuses the whole use and replies with the
    thing's `use_fail`, so there is no text keyed on it and nothing recorded.
    """
    if not requires:
        return []
    return [part.strip() for part in requires.split("|") if part.strip()]


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
