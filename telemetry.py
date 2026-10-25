"""Writing to the interaction log, from the places that know what happened.

The log itself is a table in `database`; this is the layer above it that
fills in the two things every row wants and no call site should have to
remember - the server's drop, and the fact that **a telemetry failure may
never reach the player**.

That second one is the whole reason this module is thin rather than
absent. Every function here is called from inside a command handler, most
of them inside the handler's `except SQLAlchemyError` block, and a raise
from a logging call would be caught there and reported as "something went
wrong" for a pet that had already happened. So nothing here raises. A row
that cannot be written is a row nobody reads in a month; a row that throws
is a bug the player sees now.
"""

import logging

import database
import resolve

from database import (  # noqa: F401 - the vocabulary, re-exported for call sites
    ABSENT,
    AMBIGUOUS,
    COOLDOWN,
    DROP,
    FULL_HANDS,
    HINT,
    LOOK,
    NOT_CARRIED,
    NOT_HELD,
    NOT_TAKEABLE,
    NO_GAME_YET,
    ONCE_A_DAY,
    PET,
    PLAYER,
    RAMP,
    RECOVERY,
    REFUSED,
    REQUIRES_MISSING,
    SUCCESS,
    SYSTEM,
    TAKE,
    UNKNOWN,
    UNKNOWN_NOUN,
    USE,
    WRONG_ROOM,
)

log = logging.getLogger(__name__)


async def drop_of(guild_id: int) -> int | None:
    """The server's drop, or None if it has no game or the read fails.

    Stored on every row even though it is joinable from the config
    history, because it is the slicer every question starts with and it
    costs an integer.
    """
    try:
        return await resolve.current_drop(guild_id)
    except Exception:  # pragma: no cover - a drop read that fails is not news
        log.exception("Could not read the drop for guild %s while logging", guild_id)
        return None


async def record(guild_id: int, *, action: str, **fields) -> int | None:
    """One row, with the drop filled in. Returns its id, or None."""
    if "drop" not in fields:
        fields["drop"] = await drop_of(guild_id)
    return await database.log_interaction(guild_id, action=action, **fields)


async def succeeded(
    guild_id: int, user_id: int | None, action: str, **fields
) -> int | None:
    """Something a player did that worked."""
    return await record(
        guild_id, action=action, user_id=user_id, outcome=SUCCESS, **fields
    )


async def refused(
    guild_id: int, user_id: int | None, action: str, *, reason: str, **fields
) -> int | None:
    """Something a player tried that the game said no to.

    `reason` is not optional, which is the point of the function. A
    refusal with no reason is a row that says players are bouncing off
    the game without saying off what, and that is the half worth
    having.
    """
    return await record(
        guild_id,
        action=action,
        user_id=user_id,
        outcome=REFUSED,
        reason=reason,
        relationship_delta=0,
        **fields,
    )


async def recoveries(changes) -> None:
    """One system row per score the midnight job moved.

    **The reason the nightly job is in this table at all.** Across a
    staged release it is the clock, not anything a player does, that
    moves most scores - so a log of player actions alone would show
    meters drifting for no recorded reason, and every per-pet number
    read against them would be wrong.

    Called from all three places that settle recoveries - the nightly
    loop, the catch-up at boot, and the QA command - because a score
    that moved while the bot was down moved just the same.
    """
    for change in changes:
        await record(
            change.guild_id,
            action=RECOVERY,
            user_id=change.user_id,
            actor=SYSTEM,
            outcome=SUCCESS,
            relationship_delta=change.after - change.before,
            score_after=change.after,
            detail=f"day={change.day}",
        )


async def system(guild_id: int, action: str, **fields) -> int | None:
    """Something the world did on its own.

    The nightly recovery is the one that matters: across a staged
    release it is the clock, not anything a player does, that moves
    most scores, and a log of player actions alone cannot see it.
    `user_id` is still set when a system row is about one player.
    """
    return await record(guild_id, action=action, actor=SYSTEM, **fields)
