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

from database import (  # noqa: F401 - the vocabulary, re-exported for call site
    ABSENT,
    ALREADY_ARRIVED,
    ALREADY_DONE,
    AMBIGUOUS,
    ARMS_FULL,
    CATNIP,
    COOLDOWN,
    CRASHED,
    CRAVING_GUESS,
    DB_ERROR,
    DROP,
    FEED,
    FULL_HANDS,
    GHOST_PICKED,
    GUARDED,
    HAUNTED,
    HINT,
    KEY_DROPPED,
    ABANDONED,
    LOOK,
    MOVE,
    NOT_AN_EXIT,
    NOT_CARRIED,
    NOT_HELD,
    NOT_HUNGRY,
    NOT_TAKEABLE,
    NO_BOWL,
    NO_GAME_YET,
    NO_OPENER,
    ONCE_A_DAY,
    PET,
    PLAYER,
    RAMP,
    RECOVERY,
    REFUSED,
    REQUIRES_MISSING,
    RESTOCK_PLACED,
    SUCCESS,
    STAIRS_UPPER_REACHED,
    SYSTEM,
    TAKE,
    THIS_ROOM,
    THREAD_REMOVED,
    THREW_AWAY,
    TOY_CARRIED_OFF,
    TRASH_EMPTIED,
    UNKNOWN,
    UNKNOWN_NOUN,
    UNLOCK,
    USE,
    WRONG_PLACE,
    WRONG_STATE,
    WRONG_ROOM,
    WRONG_TIME_AND_PLACE,
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
    """One row, with the drop filled in. Returns its id, or None.

    `**fields` are `log_interaction`'s, unchanged. The one worth naming
    here is `typed`: a row about a thing a player named should carry the
    word they used for it, which is `found.typed` and is passed by hand
    at every site, because this layer cannot see it. The verbs that have
    a `reach.Found` in scope all do; anything that logs about a thing
    nobody typed leaves it alone, which is right rather than an
    oversight - a restock, the nightly recovery, and a throw into the
    bin, where the thing was picked off a menu.
    """
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


async def crashed(
    guild_id: int,
    user_id: int | None,
    *,
    command: str,
    error: BaseException,
    typed: str | None = None,
) -> int | None:
    """A command that died rather than finishing or refusing.

    **The row this table could not write.** `succeeded` and `refused`
    are both downstream of whatever line raised, so a crash was the one
    thing that happened in the game and left nothing behind - and an
    absence reads exactly like a command nobody ran. The only way into
    the 9 November failure was to replay a playtester's `/look` against
    the live database by hand; one row saying `look`, `TypeError` and
    what they typed would have been the first thing anybody looked at.

    **Swallows everything, not just `SQLAlchemyError`.** The rest of
    this module is called from inside a command handler, where a raise
    would be caught and reported as "something went wrong" for a pet
    that had already happened. This one is called from the catch-all
    handler itself, where a raise is a failure inside an error handler -
    which asyncio reports as *Task exception was never retrieved*, a
    second traceback for every first one, in a log that is by then
    already struggling. There is nothing left to escalate to.

    `outcome` is deliberately left null: `success` and `refused` are the
    two answers a verb can give, and the action is already the answer
    here.
    """
    try:
        return await record(
            guild_id,
            action=CRASHED,
            user_id=user_id,
            reason=type(error).__name__[:32],
            detail=f"command={command}",
            typed=typed,
        )
    except Exception:  # pragma: no cover - see above; there is no caller to tell
        log.exception(
            "Could not log the crash in %s for guild %s", command, guild_id
        )
        return None


async def db_error(
    guild_id: int,
    user_id: int | None,
    *,
    command: str,
    error: BaseException,
    typed: str | None = None,
) -> int | None:
    """A command the database refused, which apologised and gave up.

    **The silence `crashed` did not cover.** The handlers that catch
    `SQLAlchemyError` do the decent thing by the player - a sentence
    saying the database is the problem, rather than the catch-all's
    shrug - and then returned without writing anything down. So the
    better-behaved failure was the more invisible one, and six of
    those handlers did not even log a traceback.

    `reason` is the SQLAlchemy exception's class name, which is the
    difference between a pool that is exhausted and a statement that
    is wrong. `outcome` is left null for the same reason `crashed`
    leaves it null: `success` and `refused` are answers a verb gives,
    and this is not the verb answering.

    **Swallows everything, and this one has a reason `crashed` does
    not.** It is called from inside a handler that has already decided
    what the player is told and has already told them. A raise here
    would escape that handler, reach the catch-all, and be written
    down as a `crashed` row for a command that did not crash - so the
    failure mode of the row this exists to write is a row that lies.
    """
    try:
        return await record(
            guild_id,
            action=DB_ERROR,
            user_id=user_id,
            reason=type(error).__name__[:32],
            detail=f"command={command}",
            typed=typed,
        )
    except Exception:
        log.exception(
            "Could not log the database refusal in %s for guild %s",
            command,
            guild_id,
        )
        return None


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
