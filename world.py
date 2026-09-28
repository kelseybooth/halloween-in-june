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
