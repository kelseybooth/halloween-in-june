"""The ghost of the day: who is wearing the bedsheet, and who could be.

One player a day is secretly the ghost. This module picks them, at the
Pacific changeover, from the players who were here the day before - and
stores the pick, because every clue the spirit board will give out is
spelled from the name the ghost had at the moment they were chosen.

**The pick is a row, including on the days with no ghost.** A day where
too few players were eligible writes a row with no ghost in it rather
than no row at all, and that is what makes the pick idempotent. The
nightly job can run twice and `/qa-midnight` settles every night a
server owes, so "have we already picked for this day" has to be a
question the database can answer. Without it, a second run at noon
would take the sheet off whoever had it and hand it to somebody else
halfway through their day.

The answer is enforced by `(guild_id, day)` being the primary key and
by the insert reporting whether it wrote, rather than by the read at
the top of `pick_for` - which is a fast path, and which a mutation run
showed no test depends on.

**Eligible means three things at once**, and the stored count means all
three: the player has entered the house, they ran at least one command
on the previous Pacific day, and they are still in the server. The
third is not bookkeeping - a ghost who has left cannot be named by
anybody, so a day that picked one would be a day nobody could win.

**Repeats are allowed.** The same player may be the ghost two days
running; the design says so, and a pick that avoided yesterday's ghost
would itself be a clue on a quiet server.

What this does not do yet: the bedsheet, the haunting, the spirit board
and the reveal. The pick is the half that has to be right first,
because every one of those reads the row it writes. See the drop 50
work order, part 2.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import database
import telemetry

log = logging.getLogger(__name__)

# The default lives in `database.CONFIG_KEYS`, which is also what
# `/admin_config` validates against - one list, so a key cannot be
# settable but unread, or read with a different default than the
# command reports.
MIN_PLAYERS = "ghost_min_players"


@dataclass(frozen=True)
class Pick:
    """What one changeover decided, for the logs and the tests."""

    day: date
    # None on a day with no ghost, which is a decision rather than a
    # failure: `eligible` says how close the server came to one.
    user_id: int | None
    display_name: str | None
    username: str | None
    eligible: int
    minimum: int

    @property
    def skipped(self) -> bool:
        return self.user_id is None


async def pick_for(
    guild_id: int,
    day: date,
    *,
    name_of,
    now: datetime | None = None,
) -> Pick | None:
    """Choose this server's ghost for `day`, or record that nobody is.

    `day` is the day beginning, and eligibility reads the day before it -
    the one that just ended. `name_of(user_id)` returns that member's
    `(display_name, username)`, or None if they are no longer in the
    server; it is passed in rather than looked up here so that this
    module needs nothing from discord.py.

    Returns None if this server already has a row for `day`.

    **The guard is the primary key, not that read.** The read is a fast
    path - it skips an eligible sweep and a name resolution for every
    call after the first - but deleting it leaves every test green,
    checked with a mutation rather than assumed. What actually refuses
    a second pick is `record_daily_ghost`: it inserts with `ON CONFLICT
    DO NOTHING` and reports whether it wrote, so two changeovers
    racing cannot both come away believing they picked, which they
    could if the read were the only thing in the way.
    """
    if await database.daily_ghost(guild_id, day) is not None:
        return None

    minimum = await database.get_setting(guild_id, MIN_PLAYERS)
    active = await database.players_active_on(guild_id, day - timedelta(days=1))

    # Names are resolved before the minimum is applied, rather than
    # after the choice. Resolving afterwards would mean a server of
    # three where one has left reports three eligible and then either
    # picks somebody no clue can spell, or re-rolls under a count that
    # has stopped being true.
    nameable: dict[int, tuple[str, str]] = {}
    for user_id in active:
        names = name_of(user_id)
        if names is not None:
            nameable[user_id] = names

    if len(nameable) < minimum:
        pick = Pick(day, None, None, None, len(nameable), minimum)
    else:
        # Sorted first, so the choice is drawn from a stable sequence: a
        # dict's order is its insertion order, which is the database's
        # row order, and a test that patches `random.choice` should be
        # choosing from the same list twice.
        chosen = random.choice(sorted(nameable))
        display_name, username = nameable[chosen]
        pick = Pick(day, chosen, display_name, username, len(nameable), minimum)

    stored = await database.record_daily_ghost(
        guild_id,
        day,
        user_id=pick.user_id,
        display_name=pick.display_name,
        username=pick.username,
        eligible=pick.eligible,
        now=now,
    )
    if not stored:
        # Another changeover landed between the read at the top and this
        # write. Theirs stands, for the same reason that read exists.
        log.info(
            "Ghost for %s in guild %s was already picked; keeping that one",
            day,
            guild_id,
        )
        return None

    await telemetry.system(
        guild_id,
        telemetry.GHOST_PICKED,
        user_id=pick.user_id,
        detail=(
            f"day={day} eligible={pick.eligible} minimum={pick.minimum} "
            f"{'skipped' if pick.skipped else 'picked'}"
        ),
    )
    if pick.skipped:
        log.info(
            "No ghost for %s in guild %s: %d eligible, %d needed",
            day,
            guild_id,
            pick.eligible,
            pick.minimum,
        )
    else:
        log.info(
            "Ghost for %s in guild %s is %s, from %d eligible",
            day,
            guild_id,
            pick.user_id,
            pick.eligible,
        )
    return pick
