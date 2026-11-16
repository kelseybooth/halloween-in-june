"""The oak's ambient hints: the house pointing at the tree, until somebody climbs it.

Ten lines posted in the Courtyard now and then, which stop for good the
first time anybody on the server gets into the Secret Library.

**This is not the hint rail, and the shared word is the only thing they
have in common.** A `hints` line is private, appended to a reply the
player was getting anyway, retired per player, at most one a message.
These are public, per server, posted on their own thirty seconds later,
and nobody can ask for one. Two mechanisms that happen to be called
hints, which is why this is a module and not a branch in that one.

**What ends them is "has anybody been in", not "has this server had a
ghost".** The work order asked for the first ghost's check by name, and
those are different questions - `database.anyone_holding` says why, and
`ghosts.first_ghost` says why the ghost's own check must stay as it is.

**The order the conditions are asked in is the whole cost of this
feature**, because it hangs off the completion hook and that fires on
every slash command in the game. It is the first ghost's ordering, for
the first ghost's reason: the drop is cheap, the server-level check is
one row and is the switch that turns this off for good, the dice are
free, and only then does anybody pay to find out which room the player
is standing in.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

import database
import resolve
import world

log = logging.getLogger(__name__)

# The drop that opens the library, and so the drop the hints are for.
FROM_DROP = 50

COUNT = 10
KEYS = tuple(f"oak.hint.{number}" for number in range(1, COUNT + 1))

# Where they post, and where the player has to be standing. **Their body,
# not the window they typed in** - the opposite of the first ghost's
# question, and for the opposite reason: that line is ephemeral and
# lands wherever it was asked from, and this one goes to the room
# itself. The thread is picked by the room, so where the command was
# typed cannot move it.
COURTYARD = world.COURTYARD

# Either way in. The tree writes `library_found`, the cabinet writes
# `passage_open`, and either one means the secret is out on this server.
ENDED_BY = (world.LIBRARY_FOUND, world.PASSAGE_OPEN)

ODDS = "oak_hint_odds"
GAP_HOURS = "oak_hint_gap_hours"


@dataclass(frozen=True)
class Due:
    """A hint this server has claimed and not yet posted."""

    key: str
    # The stamp the claim wrote, which is what releases it if the post
    # fails. Carried rather than read back, so a claim that has landed
    # since is never reopened under it.
    stamp: datetime


def line_at(position: int, last_key: str | None) -> str:
    """Which line a server reads at this position.

    **The ten in order, then at random for ever.** The order is the
    writer's: the first five are subtle and the last five point at the
    window, so a server that reads them shuffled gets the plainest hint
    first and the subtlest tenth.

    Never the same line twice running once it is random, which is the
    only thing `last_key` is kept for. With ten lines that is the
    difference between a house that repeats itself and one that does
    not, and it costs one column.
    """
    if position < COUNT:
        return KEYS[position]
    choices = [key for key in KEYS if key != last_key] or list(KEYS)
    return random.choice(choices)


async def due(guild_id: int, *, standing_in, now: datetime | None = None) -> Due | None:
    """Whether a hint should go out after a command, and which one.

    `standing_in` answers which room the player's body is in, and is a
    callable rather than a value because answering costs a read that
    almost every command must not pay - the same bargain
    `ghosts.first_ghost` strikes with `typed_in`, and for the same
    reason.

    The slot is claimed here, before the line is posted, so two
    commands in the same half minute cannot both draw one. The caller
    must then say whether it went out: `posted` or `not_posted`.
    """
    drop = await resolve.current_drop(guild_id)
    if drop is resolve.NO_GAME or drop is None or drop < FROM_DROP:
        return None

    # **One row, and it is false exactly once per server**, which is the
    # note `first_ghost` writes about its own cheap check. After
    # somebody gets in, every command on the server stops here.
    if await database.anyone_holding(guild_id, ENDED_BY):
        return None

    odds = await database.get_setting(guild_id, ODDS)
    # Zero or less turns them off rather than dividing by it. An admin
    # who wants silence has a number that means silence.
    if odds < 1 or random.randrange(odds) != 0:
        return None

    if await standing_in() != COURTYARD:
        return None

    at = now if now is not None else await database.server_now(guild_id)
    gap = await database.get_setting(guild_id, GAP_HOURS)
    claimed = await database.claim_an_oak_hint(
        guild_id, not_before=at - timedelta(hours=max(gap, 0)), now=at
    )
    if claimed is None:
        return None
    position, last_key, stamp = claimed
    return Due(key=line_at(position, last_key), stamp=stamp)


async def posted(guild_id: int, key: str) -> None:
    """Record a hint that went out, and log it.

    The hours since the server reached 50 is what the work order asks
    for beside each line, and it is the number that says whether the
    odds and the gap are right: ten lines over a fortnight is a house
    muttering, ten in an evening is a tutorial.
    """
    await database.finish_an_oak_hint(guild_id, key)
    arrived = await database.when_drop_arrived(guild_id, FROM_DROP)
    now = await database.server_now(guild_id)
    hours = (
        None
        if arrived is None
        else round((now - arrived).total_seconds() / 3600, 1)
    )
    log.info(
        "Guild %s: posted %s in the courtyard, %s hours after drop %s",
        guild_id,
        key,
        "?" if hours is None else hours,
        FROM_DROP,
    )


async def not_posted(guild_id: int, stamp: datetime) -> None:
    """Give the slot back, for a hint that was claimed and never sent."""
    await database.release_an_oak_hint(guild_id, stamp)
    log.info("Guild %s: an oak hint could not post, so the window reopens", guild_id)


async def note_the_first_entry(guild_id: int, user_id: int, state: str | None) -> None:
    """Log how many hints had posted before somebody got into the library.

    **Written on every player's first entry, and every one of them
    carries the same number.** The cursor stops the moment the first
    person is in, because that is the moment the hints stop, so the
    count the second entrant logs is still the count the first one
    arrived at. The earliest of these lines per server is the one the
    work order asks for, and the rest cost a read on the rarest move in
    the game.
    """
    if state not in ENDED_BY:
        return
    so_far = await database.oak_hints_so_far(guild_id)
    log.info(
        "Guild %s: %s is in the library (%s), after %s oak hint(s)",
        guild_id,
        user_id,
        state,
        so_far,
    )
