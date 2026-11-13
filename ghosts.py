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

**And the board is the other half of the same row.** The pick stores a
name so that the clues can be spelled from it all day; everything under
*the spirit board* below spells them. Nobody is told who the ghost is -
the board gives one letter and one yes-or-no a day, per player - so the
only way to the name is several players comparing what they were each
given.

**And the day gets an ending.** At the next changeover, before the new
pick, `reveal_for` says what the channel should be told about the day
that just closed: who the ghost was and how many players named them, or
- for a ghost who never haunted - that somebody wore the sheet and
nobody is going to be told who. A day nobody wore it is not mentioned
at all, because there would be no name for the board to keep.

*Boo Who?*, the award for haunting all day and getting away with it, is
the other thing that reads a day rather than a command. It is not here:
it lives in `triggers` with every other predicate, reads these rows
through `database`, and asks this module for nothing.
"""

from __future__ import annotations

import hashlib
import logging
import random
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from collections.abc import Sequence
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

# The channel, under the name the rest of the house uses for it.
CHANNEL = "CH"

# **Two forms, because the picker shows a name and the modal finishes a
# sentence.** `rooms.tsv` calls the channel "the channel", which is what
# a player standing in it reads. The haunt picker is a list of places to
# drift into from outside, and outside is where the house has always
# called it the road - `_say_in_room` says so in its own docstring.
#
# The second form exists because `ghost.haunt.modal.title` is
# "Haunt the {room}" and `ghost.haunt.private` is "You drift into the
# {room}". Every other room in the house is a bare noun that reads
# correctly after "the"; the channel is the only name carrying its own
# article, so those two lines have rendered "the the channel" since the
# picker shipped. One name for the list, one for after a "the", and both
# read.
#
# **The list form is capitalised and carries no article**, because the
# list is a list: "Entryway", "Dining Room", "Nursery". "the road" was
# the only lowercase entry in it and the only one beginning with a word
# the others left out, which read as a mistake rather than as a place.
ROAD_IN_A_LIST = "Road"
ROAD_AFTER_THE = "road"

# The first option in the picker, which is no single room. A room id is
# two uppercase letters everywhere in the house, so one character cannot
# collide with one now or after a drop adds a room.
EVERYWHERE = "*"


async def haunt_names(room_id: str) -> tuple[str, str]:
    """What to call one room in the picker, and after the word "the".

    The pair is the same string for every room but the channel, and
    callers use both halves rather than choosing, so that a second room
    that ever needs its own article has one place to say so.
    """
    if room_id == CHANNEL:
        return ROAD_IN_A_LIST, ROAD_AFTER_THE
    name = await resolve.room_name(room_id) or room_id
    return name, name

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

# **Said once per server, ever.** The line the very first ghost gets
# instead of `ARRIVED`, because they are not being told about a pick
# that happened at midnight - the sheet slides off a shelf in front of
# them.
#
# It used to open *as you climb in*, which was written for the oak and
# then stopped being true twice over. The line lands on the ghost's
# first command from *inside* the library rather than on the climb that
# brought them, because that is the first reply that can appear in the
# room the sentence is about; and a QA tester who came through the
# cabinet never climbed anything in the first place.
#
# It opens *behind you* now, which covers both doors and the beat in
# between - something behind you could have happened a moment ago. The
# design tab's copy table still carries the older wording.
FIRST = "ghost.first"

# Said on the ghost's next command after the pick, and on the old
# ghost's next command after they stop being it.
ARRIVED = "ghost.new"
GONE = "ghost.gone"

# What the channel is told at the changeover about the day that ended,
# and the difference between the three is the whole of the reveal's
# judgement. A ghost who haunted is named, with the number of players
# who worked it out. A ghost who never haunted is not named: the quiet
# line says somebody wore the sheet and the board is keeping it to
# itself, which is also why a day *nobody* wore it says nothing at all
# - there would be no name to keep.
REVEAL_NAMED = "ghost.reveal.named"
REVEAL_NOBODY = "ghost.reveal.nobody"
REVEAL_QUIET = "ghost.reveal.quiet"

# The fixture the other half of the day is played on. It stands in the
# Secret Library and is not takeable, so `/use spirit board` already
# asks the only two questions that matter - are you in the library, and
# has the library arrived - before this module sees it. Nothing here
# checks again.
SPIRIT_BOARD = "spirit_board"

# **The most places the planchette will circle**, and so the most
# letters of the name the board will ever spell. A clue is one letter
# and the count of circles is where in the name it sits, which only
# works as a shared puzzle if the count is a small number two players
# can compare out loud. Eight is the design's cap.
MAX_PLACES = 8

# Every line the board can say, by defaults key. Named here rather than
# spelled at each site because two of them are said from more than one
# place and all of them are the writers' copy: a key that drifts is a
# board that silently answers nothing.
ASK_CLUE = "board.ask.clue"
ASK_GHOST = "board.ask.ghost"
ASK_NO_LETTERS = "board.ask.no_letters"
ASK_ALREADY = "board.ask.already"
NAME_YES = "board.name.yes"
NAME_NO = "board.name.no"
NAME_SELF = "board.name.self"
NAME_NON_PLAYER = "board.name.non_player"
NAME_ALREADY = "board.name.already"
NAME_NOT_YET = "board.name.not_yet"
NO_GHOST = "board.no_ghost"

# The two lines nobody wrote for this. The design gives the board's
# look, both answers and every refusal, but not the sentence the
# buttons arrive under or the one above the member picker - and a
# Discord message cannot be only controls. Both are placeholders in
# the house's voice, in `defaults.tsv` where a writer can replace them
# without touching code.
MENU = "board.menu"
NAME_WHO = "board.name.who"


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


@dataclass(frozen=True)
class Reveal:
    """One line for the channel, as a defaults key and its arguments.

    Shaped like `Answer` and deliberately not the same class. An answer
    is private, goes to the player who pressed a button, and can be
    worth an award. This is the server's, goes out with no interaction
    behind it, and can never earn anybody anything.
    """

    key: str
    args: dict = field(default_factory=dict)


async def reveal_for(guild_id: int, *, now: datetime | None = None) -> Reveal | None:
    """What to post about the day that just ended, or None to say nothing.

    **Runs before `pick_for`, every changeover.** The two read
    different rows - this one yesterday's, the pick today's - so the
    order is not protecting against an overwrite today. It is the
    design's order, and keeping to it means the reveal can never be
    written against a row the pick has just decided.

    Three silences, and they are three different things:

    * **No row for yesterday.** This server was not playing part 2
      then. Nothing happened, so nothing is announced.
    * **A row with no ghost.** The pick looked and found too few
      eligible players. Nobody wore the sheet, so the quiet line would
      be untrue - it says the board is keeping a name to itself, and
      there is no name.
    * **Already revealed.** `claim_the_reveal` lost the race, and the
      stamp is what stops a second changeover telling the channel the
      same thing twice.

    Past those: a ghost who never haunted gets the quiet line and is
    not named, amended into the design on 11 November so that nobody is
    called out for a day they did not play. A ghost who did haunt is
    named, with the count of players who named them right or with the
    line that says nobody did.

    **The claim is taken before the line is handed back**, so a caller
    that then fails to post has spent the night's reveal. That is the
    cheaper failure. The other order loses the stamp instead of the
    post, and the next changeover names yesterday's ghost again, a day
    after the day it was about.
    """
    drop = await resolve.current_drop(guild_id)
    if drop is resolve.NO_GAME or drop is None or drop < FROM_DROP:
        return None

    yesterday = await database.server_today(guild_id) - timedelta(days=1)
    row = await database.daily_ghost(guild_id, yesterday)
    if row is None or row.user_id is None:
        return None
    if not await database.claim_the_reveal(guild_id, yesterday, now=now):
        log.info("Guild %s had already revealed the ghost for %s", guild_id, yesterday)
        return None

    if not await database.hauntings_on(guild_id, row.user_id, yesterday):
        log.info(
            "Guild %s: the ghost for %s never haunted, so the name is kept",
            guild_id,
            yesterday,
        )
        return Reveal(REVEAL_QUIET)

    named = await database.named_the_ghost_on(guild_id, yesterday)
    log.info(
        "Guild %s: revealing %s as the ghost for %s, named by %d",
        guild_id,
        row.user_id,
        yesterday,
        named,
    )
    if not named:
        return Reveal(REVEAL_NOBODY, {"name": row.display_name})
    return Reveal(REVEAL_NAMED, {"name": row.display_name, "count": named})


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


async def first_ghost(
    guild_id: int,
    user_id: int,
    *,
    display_name: str,
    username: str,
    typed_in: Callable[[], Awaitable[str | None]],
    now: datetime | None = None,
) -> str | None:
    """The one pick that is not random: whoever reaches the library first.

    Returns the defaults key to say to them, or None if this is not
    that moment. The sheet is in their hands by the time it returns.

    `typed_in` answers which room the command was typed in, and is a
    callable rather than a value because answering costs reads that
    almost every caller must not pay - see the gate itself below.

    **The condition is "has this server ever had a ghost", not "has
    anybody found the library".** Those are the same question on every
    server players will ever see - both parts launch together there, so
    the first entry and the start of the ghost system are the same
    event - and they are different on QA, where Part 1 was tested on
    its own for days. A library found during that testing must not
    spend the server's one unmissable moment, and `daily_ghosts` is
    the table that cannot know about it: it is Part 2's, and every
    server starts with no rows in it. So nothing is stored for this and
    nothing is wiped.

    **It asks about entry, not discovery.** A tester who found the
    library during Part 1 and walks back into it still triggers it,
    which is the behaviour QA needs: the first thing anybody does in
    the library after the system is live is the thing that starts it.
    It also means a player standing in the library when the drop
    advances starts it on their next command, which is the same
    sentence and the same truth.

    **And it asks where the command was typed, not only where the
    player is.** Those agree for every command in the game except the
    one that matters here: a player climbing the oak types under the
    tree and arrives in the library, so at the moment this first has
    an answer their body is inside and their window is the Courtyard.
    The line is ephemeral - it has to be, because who is wearing the
    sheet is the whole game - and Discord puts an ephemeral reply in
    the channel it was asked from. Told on the climb, the library's
    one unmissable moment arrives under a tree.

    So the sheet waits for their first command from inside, which is
    the first reply that can land in the room the sentence is about.
    They are already there and already pinged: the arrival line is
    what admits them to the thread, so the next thing they type is
    almost always typed in it.

    A day the nightly pick skipped is taken over rather than left
    alone, because a day with nobody in it is a day with no ghost -
    see `database.claim_first_ghost`, where that is one `WHERE`.

    The names are the ones the player has right now, passed in by the
    caller from the member who just ran the command. That is both the
    most current source and the only one that needs no cache lookup:
    unlike the nightly pick, this player is demonstrably here.
    """
    drop = await resolve.current_drop(guild_id)
    if drop is resolve.NO_GAME or drop is None or drop < FROM_DROP:
        return None

    # First, because it is the cheap one and because it is false exactly
    # once per server. Every command after that first ghost exists
    # stops here without reading a room.
    if await database.ever_had_a_ghost(guild_id):
        return None

    state = await database.get_game_state(user_id, guild_id)
    if state is None or state.current_room != LIBRARY:
        return None

    # **Asked last, because it is the expensive one.** Which room a
    # command was typed in is a channel lookup and the whole room list,
    # on the hook that runs after every command in the game - so it is
    # a callable, and nothing above this line has had to pay for it.
    # Everything that gets this far is a command run from inside the
    # library on a server that has never had a ghost, which is a
    # handful of commands once per server.
    #
    # A window that is not the library leaves the moment unspent rather
    # than failing it. That is the whole difference between late and
    # missed, and the server only has one of these.
    window = await typed_in()
    if window != LIBRARY:
        log.info(
            "Guild %s: %s is in the library but typed in %s, so the sheet waits",
            guild_id,
            user_id,
            window,
        )
        return None

    today = await database.server_today(guild_id)
    claimed = await database.claim_first_ghost(
        guild_id,
        today,
        user_id=user_id,
        display_name=display_name,
        username=username,
        now=now,
    )
    if not claimed:
        # Somebody else walked in during this command, or the night's
        # pick landed between the two reads above. Theirs stands, and
        # this player is told nothing - which is correct: nothing
        # happened to them.
        log.info(
            "Guild %s already had a ghost by the time %s reached the library",
            guild_id,
            user_id,
        )
        return None

    await database.place_in_hands(guild_id, user_id, BEDSHEET, now=now)
    await telemetry.system(
        guild_id,
        telemetry.GHOST_PICKED,
        user_id=user_id,
        detail=f"day={today} first ghost, no minimum",
    )
    log.info("The first ghost in guild %s is %s", guild_id, user_id)
    return FIRST

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
    rooms: Sequence[str],
    whisper: str,
) -> None:
    """Write the haunting down: the author, the rooms and the words.

    Two writes, and they answer different questions. The log row is
    the admin's copy and the count *Boo Who?* and the spirit board
    both read. `record_use` is what makes this a use of the bedsheet,
    which is what *Getting into the Spirit* fires on - and it keeps
    the sheet in the same bookkeeping as everything else a player
    uses, rather than inventing a second idea of what using a thing
    means.

    **One haunting, however many rooms the shape reached.** This takes
    a list rather than a room so that the all-rooms option is not a
    special case anybody can forget: one call, one row, whether the
    list holds one room or nine. *Boo Who?* wants the ghost haunting
    three times across a day, and a press that wrote nine rows would
    hand it over in one - "haunted the house all day" has to cost a
    day.

    **A room per use, or none.** `record_use` writes `last_used_at`
    and `last_used_room` as one fact, and the honest answer for a
    shape that was in every room at once is that it was in no
    particular one. Its own docstring allows the null and warns
    against coalescing, which is the trap here: keeping the last real
    room would say the sheet was last used somewhere it was not.
    """
    places = list(rooms)
    await database.record_use(
        user_id,
        guild_id,
        BEDSHEET,
        room_id=places[0] if len(places) == 1 else None,
    )
    await telemetry.succeeded(
        guild_id,
        user_id,
        telemetry.HAUNTED,
        thing_id=BEDSHEET,
        detail=(
            whisper
            if len(places) == 1
            else f"every room ({len(places)}): {whisper}"
        ),
    )
# --------------------------------------------------------------------------
# The spirit board
# --------------------------------------------------------------------------

# **Letters that carry their stroke inside the codepoint.** Folding is
# `NFKD` and then dropping the combining marks, which turns E-acute into
# E and handles every accent anybody is likely to have - but a slashed
# o and a barred l do not decompose at all, so without this they would
# read as non-letters and end the word. Bjorn would be spelled BJ.
#
# Only the one-for-one ones are here. A-E, O-E and sharp s are
# deliberately left out: each would turn one place in the name into two,
# and the count of circles is the player's only evidence of where in the
# name they are, so a letter that silently costs two places is worse
# than a word that ends early.
_FOLDED = str.maketrans(
    {
        "ø": "o", "Ø": "O",  # slashed o
        "ł": "l", "Ł": "L",  # barred l
        "đ": "d", "Đ": "D",  # barred d
        "ħ": "h", "Ħ": "H",  # barred h
        "ŧ": "t", "Ŧ": "T",  # barred t
        "ı": "i", "İ": "I",  # dotless and dotted i
    }
)

# Skipped inside a word instead of ending it, which is the design's one
# exception and the reason it exists: Mary-Beth is one name and so is
# O'Brien, and a board that stopped at MARY would be giving a clue to a
# name nobody has. Both the typewriter and the curly apostrophe, because
# phones produce the curly one.
_JOINERS = "-‐‑'‘’ʼ"

# Written out, because the line says *circles the board three times*
# rather than *3 times*. One entry per place, which is why `MAX_PLACES`
# and this tuple are checked against each other in the tests rather
# than merely both being eight.
_CIRCLES = (
    "once",
    "twice",
    "three times",
    "four times",
    "five times",
    "six times",
    "seven times",
    "eight times",
)


def circles(place: int) -> str:
    """How the line says a number of times round the board."""
    return _CIRCLES[place - 1]


def _folded(name: str) -> str:
    """The name with its accents taken off."""
    decomposed = unicodedata.normalize("NFKD", name.translate(_FOLDED))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _first_word(name: str) -> str:
    """The spellable first word of one name, in capitals, at most eight.

    Three rules, in this order, and the order is the whole function:

    * **Before the first letter, nothing counts.** A leading emoji, a
      bracket, a space are all skipped, so a crescent moon in front of
      Jess does not make the name unspellable.
    * **A joiner is skipped**, so Mary-Beth and O'Brien stay one word.
    * **Anything else ends the word**, once there is a word to end. A
      space, a pipe, an underscore, a digit - the name is over, which is
      what makes *Kate (Ollie's mom)* spell KATE and not KATEOLLIESMOM.

    And it stops at `MAX_PLACES` whatever comes next, so the planchette
    never circles more than eight times.
    """
    letters: list[str] = []
    for ch in _folded(name):
        if ch.isascii() and ch.isalpha():
            letters.append(ch.upper())
            if len(letters) == MAX_PLACES:
                break
        elif ch in _JOINERS:
            continue
        elif letters:
            break
    return "".join(letters)


def letters_of(display_name: str | None, username: str | None) -> str:
    """What the board can spell, from the names stored at the pick.

    The display name first, and the username only if the display name
    has no A-to-Z letters in it at all - an all-emoji name, or one
    written in a script this board has no letters for. Discord
    usernames are letters, digits, dots and underscores, so the same
    three rules applied to one gives *kate_s.92* as KATE.

    Returns "" when neither spells anything, which is a real answer
    rather than an error: the board has a line for a name that does not
    spell, and the day still had a ghost.
    """
    for name in (display_name, username):
        if not name:
            continue
        word = _first_word(name)
        if word:
            return word
    return ""


def place_for(day: date, guild_id: int, user_id: int, places: int) -> int:
    """Which place in the name this player is given today, from 1.

    **A hash, so it cannot be rerolled and does not have to be
    stored.** Three things go in - the day, the server and the player -
    and the same three always come out at the same place, so pressing
    the button again after a bot restart, or on a day the row was
    rewritten, gives the player the letter they already had. Storing a
    draw instead would mean a row per player per day whose only job is
    to repeat itself.

    `sha256` rather than `hash()`, which is salted per process: the
    built-in would hand the same player a different letter after a
    deploy, which is the one thing this must not do.

    Different players usually land on different places, and sometimes
    two land on the same one. That is not a flaw to fix - the game is
    comparing notes, and a collision costs a pair of players one letter
    between them, not the day.
    """
    seed = f"{day.isoformat()}:{guild_id}:{user_id}".encode()
    digest = hashlib.sha256(seed).digest()
    return int.from_bytes(digest[:8], "big") % places + 1


@dataclass(frozen=True)
class Answer:
    """One thing the board says, and whether it was worth an award.

    `key` is a defaults key and `args` its format arguments, so the
    board's whole vocabulary stays in the content files and this module
    decides only which line is true. `earned` is set on a right guess
    alone: it is what tells the caller to fire the hook *Ghostbuster*
    listens on, and keeping it here rather than re-deriving it in `bot`
    means the award and the YES cannot disagree.
    """

    key: str
    args: dict = field(default_factory=dict)
    earned: bool = False


async def _ghost_today(guild_id: int):
    """The day, and the row if there is a ghost in it.

    Returns `(day, row)` with the row None when there is nobody to ask
    about - which covers two different servers that look the same to a
    player. One has not picked yet; the other picked nobody because too
    few were eligible. Both get GOODBYE. The difference is kept in the
    pick's own log row, where an admin can see it.

    The day comes back with the row because every caller needs both and
    `server_today` is a config read: asking twice in one button press
    is two reads to answer one question.
    """
    today = await database.server_today(guild_id)
    row = await database.daily_ghost(guild_id, today)
    if row is None or row.user_id is None:
        return today, None
    return today, row


async def _answered(guild_id: int, user_id: int, action: str, **fields) -> None:
    """Write down that the board answered this player today.

    Two writes, like a haunting. `record_use` makes it a use of the
    board - which is what keeps it in the same bookkeeping as every
    other thing a player uses - and the log row is what the once-a-day
    limit is counted from.

    **The limit is derived rather than stored**, which is safe here for
    the reason it usually is not: a board use has never existed before
    this release, so there is no incomplete past to count across. Every
    clue the board has ever given is a row.
    """
    await database.record_use(user_id, guild_id, SPIRIT_BOARD, room_id=LIBRARY)
    await telemetry.succeeded(
        guild_id, user_id, action, thing_id=SPIRIT_BOARD, **fields
    )


async def ask_the_board(guild_id: int, user_id: int) -> Answer:
    """*Ask the board*: one letter of the ghost's name, once a day.

    The order of the refusals is the design's. A day with no ghost is
    answered before the day's turn is looked at, because there is
    nothing to spend it on; after that, a player who has already asked
    is told so whoever the ghost is.

    **The ghost asking gets the joke line and spends their turn.** They
    could not have learnt anything from a letter of their own name, but
    a board that let them press it all day would be a board that
    behaved differently for the ghost, and anybody watching over a
    shoulder would notice.
    """
    today, row = await _ghost_today(guild_id)
    if row is None:
        return Answer(NO_GHOST)

    if await database.player_actions_on(
        guild_id, user_id, today, telemetry.BOARD_ASK
    ):
        return Answer(ASK_ALREADY)

    if user_id == row.user_id:
        await _answered(guild_id, user_id, telemetry.BOARD_ASK, detail="the ghost")
        return Answer(ASK_GHOST)

    letters = letters_of(row.display_name, row.username)
    if not letters:
        await _answered(
            guild_id, user_id, telemetry.BOARD_ASK, detail="nothing to spell"
        )
        return Answer(ASK_NO_LETTERS)

    place = place_for(today, guild_id, user_id, len(letters))
    letter = letters[place - 1]
    await _answered(
        guild_id,
        user_id,
        telemetry.BOARD_ASK,
        detail=f"place={place}/{len(letters)} letter={letter}",
    )
    return Answer(ASK_CLUE, {"count": circles(place), "letter": letter})


async def _turn_to_name(guild_id: int, user_id: int):
    """The row to guess against, and the refusal if there is one.

    Returns `(row, refusal)`, exactly one of which is useful. Both
    halves of *Name the ghost* go through here - the button, which
    checks before opening the picker, and the picker's own callback,
    which checks again - so there is one place that decides whether a
    guess is possible and one list of reasons it is not.

    **Checked twice on purpose.** A picker can sit open for minutes: a
    player who is told *nothing has stirred* and waits for a noise must
    be able to come back, and a player who guessed in another window
    meanwhile must not get a second turn.
    """
    today, row = await _ghost_today(guild_id)
    if row is None:
        return None, Answer(NO_GHOST)

    if await database.player_actions_on(
        guild_id, user_id, today, telemetry.BOARD_GUESS
    ):
        return row, Answer(NAME_ALREADY)

    # The *nothing has stirred* line, and the turn is not spent. Until
    # the ghost has haunted, naming them would be guessing at a day
    # nobody has played yet.
    if not await database.hauntings_on(guild_id, row.user_id, today):
        return row, Answer(NAME_NOT_YET)
    return row, None


async def ready_to_name(guild_id: int, user_id: int) -> Answer | None:
    """The refusal to give before the member picker opens, or None.

    What this saves is a player choosing a suspect out of a list of
    everybody they know and then being told the board was never going
    to answer today.
    """
    _, refusal = await _turn_to_name(guild_id, user_id)
    return refusal


async def name_the_ghost(guild_id: int, user_id: int, suspect_id: int) -> Answer:
    """*Name the ghost*: one yes-or-no a day, and YES earns the award.

    **Two refusals here that spend nothing**, and they are here rather
    than in `_turn_to_name` because they are about the name that came
    back: Discord's picker lists everybody in the server, so it cannot
    hide the player themselves or somebody who has never entered the
    house. Being unable to leave them out of the list is exactly why
    picking one costs nothing.

    Everything else is a guess: it is written down right or wrong, and
    only one a day. A right one does not end the ghost's day - they
    keep the sheet and can keep haunting, and everybody else can still
    guess - because the thing being rewarded is working it out, not
    getting there first.
    """
    row, refusal = await _turn_to_name(guild_id, user_id)
    if refusal is not None:
        return refusal

    if suspect_id == user_id:
        return Answer(NAME_SELF)
    if await database.get_game_state(suspect_id, guild_id) is None:
        return Answer(NAME_NON_PLAYER)

    right = suspect_id == row.user_id
    detail = f"named={suspect_id}"
    if right:
        await _answered(guild_id, user_id, telemetry.BOARD_GUESS, detail=detail)
        return Answer(NAME_YES, earned=True)

    # A wrong guess is a refusal in the log and a use of the board in
    # the bookkeeping, the same split the cat's craving makes: the row
    # that says what the player tried is the one worth tuning on, and
    # `outcome` is the column that says whether it worked.
    await database.record_use(user_id, guild_id, SPIRIT_BOARD, room_id=LIBRARY)
    await telemetry.refused(
        guild_id,
        user_id,
        telemetry.BOARD_GUESS,
        reason="wrong",
        thing_id=SPIRIT_BOARD,
        detail=detail,
    )
    return Answer(NAME_NO)
