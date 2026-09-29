"""The two uses that change the world.

Everything else `/use` does is private and reversible: you read a thing, you
stir a thing, nothing about the house is different afterwards. These two are
not. Placing a plank moves a server-wide counter and eventually opens a
staircase for everyone; graphite unjams a drawer for one person, permanently.

**The rule that sets a state lives in code, not in content.** The files carry
the text per state and the `present_when` gate; they never say how a state is
reached. That is why there is no `sets_state` column and should not be one -
the moment content can set state, a writer can create an unreachable state or
a loop, and neither is visible in a spreadsheet.

Both effects are keyed on thing ids, which is the honest version of the same
rule: two named things do two specific things, written here where a reader can
find them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import database
import states

log = logging.getLogger(__name__)

# The staircase: one plank per distinct player, counted from thing_uses.
LUMBER = "lumber"
PLANKS_SETTING = "planks_required"
STAIRS_REPAIRED = "stairs_repaired"

# The jammed drawer: graphite, and only in the hallway it is jammed in.
GRAPHITE = "graphite_powder"
DRAWER_ROOM = "UH"
DRAWER_UNJAMMED = "drawer_unjammed"


# The Secret Library. Two ways in, and the order they happen in is structural
# rather than enforced: the keys hang inside, so a player cannot hold one until
# they have already climbed the oak.
OAK = "CS"                 # Courtyard -> Secret Library. Usable by anybody.
CABINET = "LS"             # Living Room -> Secret Library. Needs a key.
BACK_OF_CABINET = "SL"     # Secret Library -> Living Room. Needs the passage.
SECRET_LIBRARY = "SE"
SKELETON_KEY = "skeleton_key"

LIBRARY_FOUND = "library_found"
PASSAGE_OPEN = "passage_open"
HAS_KEY = "has_key"


# Most specific first. `_best` takes the first of these an entity actually has
# a row for, so the same list works for every exit: a player who has opened
# the passage reads the open cabinet, and asked about the oak the list falls
# past both to the oak's own `library_found` row.
EXIT_STATES = (PASSAGE_OPEN, HAS_KEY, LIBRARY_FOUND)


def exit_state(held: set[str]) -> tuple[str, ...]:
    """The states to resolve an exit's text against, in priority order."""
    return tuple(state for state in EXIT_STATES if state in held)


async def has_key(guild_id: int, user_id: int) -> bool:
    """Whether this player is carrying a skeleton key.

    **Derived, never stored.** The key is `droppable = no`, `cross_weight = 0`
    and `max_per_player = 1`, so once taken it can never leave: it cannot be
    put down, the cat cannot send it to Dimension B, and a second cannot be
    acquired. A stored flag would be a second copy of a fact that cannot
    change, and the two could only ever drift apart.
    """
    return await database.carried_of(user_id, guild_id, SKELETON_KEY) > 0


async def states_for_exit(guild_id: int, user_id: int) -> set[str]:
    """The states that decide what an exit says and whether it opens.

    `has_key` is folded in here rather than written to `player_states`, so
    text keyed on it resolves exactly as text keyed on a stored state does.
    Nothing else has to know the difference.
    """
    held = set(await states.in_force(guild_id, user_id))
    if await has_key(guild_id, user_id):
        held.add(HAS_KEY)
    return held


def exit_refused_by(thing_id: str, held: set[str]) -> bool:
    """Whether this exit is shut for a player holding these states.

    Only the two secret doors are ever shut. The oak is deliberately not here:
    an exit gated on the state its own use produces is a locked door with the
    key inside, and nobody would ever find the library.
    """
    if thing_id == CABINET:
        return HAS_KEY not in held
    if thing_id == BACK_OF_CABINET:
        return PASSAGE_OPEN not in held
    return False


async def after_move(guild_id: int, user_id: int, thing_id: str) -> str | None:
    """Apply whatever using this exit discovers. The state set, or None.

    The same split as `after_use`: content carries the text per state, code
    decides when a state becomes true.
    """
    if thing_id == OAK:
        if await states.set_player_state(guild_id, user_id, LIBRARY_FOUND):
            return LIBRARY_FOUND
    elif thing_id == CABINET:
        if await states.set_player_state(guild_id, user_id, PASSAGE_OPEN):
            return PASSAGE_OPEN
    return None


@dataclass
class Effect:
    """What a world-changing use did, for the handler to phrase and route."""

    tokens: dict[str, object]
    public: bool = False
    announce: str | None = None

    @property
    def changed_the_world(self) -> bool:
        return self.announce is not None


async def planks(guild_id: int) -> tuple[int, int]:
    """(placed, required) for this server's staircase.

    Counted by distinct player rather than by uses: the staircase is one plank
    per person however many times they swing.
    """
    placed = await database.distinct_users_of(guild_id, LUMBER)
    required = await database.get_setting(guild_id, PLANKS_SETTING)
    return placed, required


async def check_staircase(guild_id: int) -> bool:
    """Open the staircase if enough different players have placed a plank.

    Called after each plank and again whenever `planks_required` changes, which
    is what makes lowering the target finish a stalled staircase rather than
    leaving it stuck one plank short of a number nobody can reach.
    """
    placed, required = await planks(guild_id)
    if placed < required:
        return False
    return await states.set_server_state(guild_id, STAIRS_REPAIRED)


async def after_use(
    guild_id: int, user_id: int, thing_id: str, room_id: str
) -> Effect | None:
    """Apply whatever a successful use changes. None for ordinary things."""
    if thing_id == LUMBER:
        return await _place_a_plank(guild_id)

    if thing_id == GRAPHITE and room_id == DRAWER_ROOM:
        return await _unjam_the_drawer(guild_id, user_id)

    return None


async def _place_a_plank(guild_id: int) -> Effect:
    """Count the plank, and open the staircase if that was the last one.

    The reply carries {n} and {total} either way, so a player always knows
    where the work has got to.

    This is the game's only public `/use`: the staircase is collective, and the
    others in the room need to see it happen rather than hear about it later.
    """
    opened = await check_staircase(guild_id)
    placed, required = await planks(guild_id)

    return Effect(
        tokens={"n": placed, "total": required},
        public=True,
        announce=(
            "The staircase is finished. It holds."
            if opened
            else None
        ),
    )


async def _unjam_the_drawer(guild_id: int, user_id: int) -> Effect:
    """Free the desk's bottom drawer, for this player and nobody else.

    Per player because the discovery is the content. Server-wide would mean
    only the first person ever found the smell, the drawer or what is in it.
    """
    await states.set_player_state(guild_id, user_id, DRAWER_UNJAMMED)
    return Effect(tokens={}, public=False)
