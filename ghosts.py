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
import resolve
import states
import telemetry

log = logging.getLogger(__name__)

# The default lives in `database.CONFIG_KEYS`, which is also what
# `/admin_config` validates against - one list, so a key cannot be
# settable but unread, or read with a different default than the
# command reports.
MIN_PLAYERS = "ghost_min_players"
MAX_CHARS = "haunt_max_chars"

BEDSHEET = "bedsheet"

# The one room that arrives for a server and not for a player, which
# is why the picker has to ask about it separately.
LIBRARY = "SE"

# **And the state is not the room.** Asking whether `SE` is in force
# for a player is a question that is always answered no, so the first
# draft of this dropped the library from every picker - including the
# picker of a ghost who had climbed the oak. Two names, because they
# are two things: a room this player can reach, and the per-player
# state that says they found it.
LIBRARY_FOUND = "library_found"

# The drop the whole system belongs to. **The gate `pick_for` was
# missing**: without it a server on drop 20 picks a ghost every night,
# which is invisible while nothing reads the rows and wrong the moment
# the bedsheet exists - a sheet handed to somebody thirty drops before
# the library it comes off a shelf in.
#
# A constant, like `world.HOUSE_FROM_DROP` beside the key it gates,
# rather than a read of the bedsheet's own `since_drop`. The two could
# drift, so they are pinned against each other in
# `test_the_gate_matches_the_bedsheet_s_own_drop` - cheaper than an
# async content lookup on a path that runs after every command.
FROM_DROP = 50

# Said on the ghost's next command after the pick, and on the old
# ghost's next command after they stop being it.
ARRIVED = "ghost.new"
GONE = "ghost.gone"


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
    drop = await resolve.current_drop(guild_id)
    if drop is resolve.NO_GAME or drop is None or drop < FROM_DROP:
        return None
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


async def hand_over(
    guild_id: int, user_id: int, *, now: datetime | None = None
) -> str | None:
    """Reconcile one player's hands against today's row.

    Returns the defaults key to say to them, or None if nothing moved.

    **Lazy, on their next command, rather than pushed at the
    changeover.** The design asks for exactly that - *the ghost's next
    command after the pick* - and it is also the only version that
    works: at midnight the bot has a guild and a row, not an
    interaction, so there is nowhere to put the sentence. A player who
    is the ghost and never runs a command never learns it, which is
    correct, because they were never going to haunt either.

    It is self-healing for the same reason. A night the pick did not
    run, a bot restarted mid-evening, a sheet left in the hands of
    somebody who stopped being the ghost three days ago - every one of
    those is repaired by the next command that player runs, because
    this compares the hand against the row rather than trusting a
    handover that was supposed to have happened.

    **Two directions, never both.** Being today's ghost without the
    sheet means it arrives; holding the sheet without being today's
    ghost means it goes. A player who is the ghost two days running
    matches neither and keeps it without a word, which is right: they
    were not told anything, because nothing changed.
    """
    drop = await resolve.current_drop(guild_id)
    if drop is resolve.NO_GAME or drop is None or drop < FROM_DROP:
        return None

    row = await database.daily_ghost(
        guild_id, await database.server_today(guild_id)
    )
    theirs = row is not None and row.user_id == user_id
    holding = await database.carried_of(user_id, guild_id, BEDSHEET) > 0

    if theirs and not holding:
        await database.place_in_hands(guild_id, user_id, BEDSHEET, now=now)
        return ARRIVED
    if holding and not theirs:
        await database.take_from_hands(guild_id, user_id, BEDSHEET)
        return GONE
    return None


async def rooms_to_haunt(guild_id: int, user_id: int) -> list[str]:
    """The rooms this ghost could drift into, in the house's own order.

    **Where the ghost could be, not where they are.** A haunting is
    not a move: the sheet goes over their head and the shape appears
    somewhere, so standing in the Kitchen is no reason to be unable to
    haunt the Nursery. What it is not is a way to see rooms that do
    not exist yet.

    So: every room that has arrived on this server, and the Secret
    Library only if this player has found it. The library is the one
    room in the house that arrives for a server and not for a player,
    and putting it in the list for a ghost who has never climbed the
    oak would be the game telling them it is there.
    """
    arrived = await resolve.arrived_rooms(guild_id)
    if LIBRARY_FOUND not in await states.in_force(guild_id, user_id):
        arrived.discard(LIBRARY)
    order = [room_id for room_id, _ in await resolve.all_rooms()]
    return [room_id for room_id in order if room_id in arrived]


def trimmed(whisper: str, limit: int) -> str:
    """The whisper as it will be posted.

    Trimmed rather than refused. Discord's own text box takes a
    `max_length`, so a player cannot submit an over-long whisper
    through the modal at all - this is the server-side half, and the
    only way to reach it is a client that ignored the box's limit.
    Answering that with a refusal would mean writing a line nobody
    will ever read; cutting it is the same decision the modal already
    made, applied twice.
    """
    return whisper.strip()[:limit]


async def record_haunting(
    guild_id: int,
    user_id: int,
    room_id: str,
    whisper: str,
) -> None:
    """Write the haunting down: the author, the room and the words.

    Two writes, and they answer different questions. The log row is
    the admin's copy and the count *Boo Who?* and the spirit board
    both read. `record_use` is what makes this a use of the bedsheet,
    which is what *Getting into the Spirit* fires on - and it keeps
    the sheet in the same bookkeeping as everything else a player
    uses, rather than inventing a second idea of what using a thing
    means.
    """
    await database.record_use(user_id, guild_id, BEDSHEET, room_id=room_id)
    await telemetry.succeeded(
        guild_id,
        user_id,
        telemetry.HAUNTED,
        thing_id=BEDSHEET,
        detail=whisper,
    )
