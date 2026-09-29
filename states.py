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
SERVER_STATES = {"stairs_repaired"}
PLAYER_STATES = {
    "has_key",
    "passage_open",
    "library_found",
    "drawer_unjammed",
    # Two flags that gate a message rather than a door: the tutorial fires
    # once ever, and the cat's reaction to a dirty diaper is only funny the
    # first time. Both are the same shape as `drawer_unjammed` - set once,
    # never cleared - which is why neither needs a table of its own.
    "tutorial_seen",
    "diaper_seen",
}

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
