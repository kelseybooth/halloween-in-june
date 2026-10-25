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
import random
from dataclasses import dataclass, field
from datetime import timedelta

import content as content_module
import database
import resolve
import states

log = logging.getLogger(__name__)

# The staircase: one plank per distinct player, counted from thing_uses.
LUMBER = "lumber"

# The cat bed, and what fluffing it is worth. Fifteen is three friendly
# pets, for an action a player can only take once a day - deliberately
# the better rate, because it is the one interaction that cannot go
# wrong and the one the cat visibly enjoys.
CAT_BED = "cat_bed"
BED_FLUFF = 15

# What the bed has given this player, recorded once and never again.
# The flag is the whole detection: "their first fluff in drop 2" rather
# than "their first fluff ever", which every drop 1 tester has already
# spent - and drop 1 testers are exactly who is on the server when drop
# 2 opens.
BED_STASH = "bed_stash_given"

# The toys. A class, never a list of ids: the cap, the ramp and three
# achievements all count toys by type, so a thirteenth toy stays a row
# in a spreadsheet rather than an engine change.
TOY = "toy"

# What a successful play is worth, and how the odds of one climb. The
# ramp is a count of refusals since the last success, so the chance runs
# 0, 25, 50, 75, 100 per cent - the first offer always fails and the
# fifth always lands, which is why four refusals running is the rarest
# thing *Impressively Bad Luck* can ask for and five is impossible.
TOY_PLAY = 10
RAMP_STEP = 25
PLAY_COOLDOWN = timedelta(minutes=10)


# Feeding, which drop 3 builds. Only the hunger window is read today,
# by the `/stats` status line, which has to be able to say the cat
# wants feeding before anything can feed her.
#
# **A set of ids rather than a type or a column**, and that is the one
# thing here worth revisiting. There is no `food` type, the five cans
# are `object` like everything else carriable, and `requires =
# can_opener` stops marking them the day the salmon gets its pull-tab.
# Whoever builds feeding should give them a real marker and delete
# this; until then an explicit list beats a prefix match, which would
# sweep in the seven `cat_food_stash_*` sources.
CAT_FOOD = frozenset({
    "cat_food_chicken",
    "cat_food_salmon",
    "cat_food_tuna",
    "cat_food_gourmet",
    "cat_food_expired",
})
HUNGER_WINDOW = timedelta(hours=8)

# Before this drop there is no food in the game, so every player has
# never been fed and would read as permanently hungry. The gate is what
# stops `/stats` promising a mechanic that does not exist yet.
FEEDING_FROM_DROP = 3


def play_chance(ramp: int) -> int:
    """Percentage chance that this attempt lands, from the ramp."""
    return min(100, max(0, RAMP_STEP * ramp))
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

    tokens: dict[str, object] = field(default_factory=dict)
    public: bool = False
    announce: str | None = None
    # The player's score after this use moved it, for the handler to fire
    # `on_relationship_change` on. None when the use did not touch it,
    # which is every use but one.
    relationship: int | None = None
    # What it moved by. Carried alongside the result rather than left
    # for the handler to infer, because the interaction log wants both
    # and only this module knows which constant was applied.
    delta: int | None = None

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

    if thing_id == CAT_BED:
        return await _fluff_the_bed(guild_id, user_id)

    return None


async def dislodge_from_bed(guild_id: int, user_id: int, rng=None) -> str | None:
    """Shake a toy out of the cat bed, the first time this player can.

    It fills the hole drop 2 opened: without it the channel holds toys
    and nothing else, and a player who plays one into its cooldown has
    nothing left to reach for.

    **Onto the floor, not into the bag.** That teaches `/take`, which is
    the drop's whole lesson - fluff the bed, something falls out, pick
    it up. It is public, so the next person along can take it instead,
    and it needs no new placement code.

    **Bounded by construction**: one object per player, ever, so it
    cannot silt the channel however many players a server has. And
    exempt from the restock cap by not going through the scheduler -
    a player who was given a third toy has a third toy.
    """
    if await database.has_been_told(guild_id, user_id, BED_STASH):
        return None
    arrived = await resolve.arrived_drop_ids(guild_id)
    pool = await database.ids_of_type(TOY, arrived)
    if not pool:
        # No toys here yet, so there is nothing in the bed to find. The
        # flag stays unset: this player gets theirs when drop 2 opens.
        return None

    thing_id = (rng or random).choice(pool)
    await database.place_in_room(guild_id, content_module.CHANNEL_ROOM, thing_id, 1)
    await database.notice(guild_id, user_id, BED_STASH)
    log.info("The bed gave %s to %s in guild %s", thing_id, user_id, guild_id)
    return thing_id


async def play_with(guild_id: int, user_id: int, now, rng=None) -> Effect:
    """Offer a toy, and see whether the cat is in the mood.

    **Not keyed on which toy.** Every row with `type = toy` behaves
    identically; the ramp, the cooldown and the award all belong to the
    player. That is what keeps the eleven toys still in the bank a
    content change rather than an engine one.

    A success pays `TOY_PLAY`, resets the ramp and starts the cooldown.
    A refusal advances the ramp one rung and starts nothing, so the next
    offer is likelier - which is the whole mechanic, and the reason the
    refusal copy promises nothing while leaving the retry open.
    """
    ramp, _ = await database.play_state(guild_id, user_id)
    # Resolved at call time, not bound as a default: a default argument
    # captures this module's `random` when the function is defined, so
    # patching `world.random` would leave the default pointing at the
    # original and the roll would quietly stay real.
    roll = (rng or random).random()
    succeeded = roll * 100 < play_chance(ramp)

    landed = await database.record_play(
        guild_id,
        user_id,
        succeeded=succeeded,
        cooldown_until=now + PLAY_COOLDOWN if succeeded else None,
    )
    if not succeeded:
        return Effect(tokens={"ramp": landed}, public=False)

    score = await database.adjust_relationship(user_id, guild_id, TOY_PLAY)
    return Effect(tokens={"ramp": 0}, public=True, relationship=score, delta=TOY_PLAY)


async def _fluff_the_bed(guild_id: int, user_id: int) -> Effect:
    """Fifteen points, once a day, for shaking out a cushion.

    The bed is a shared fixture with a per-player cooldown: everyone can
    fluff it, nobody can fluff it twice. The cooldown itself is the
    ordinary `use_cooldown_hours` path - rolling 24 hours rather than a
    Pacific day, which is what that column already meant and what the
    design accepted rather than coding around.

    No state is set and nothing is consumed. The bed in the channel on
    the last day of October is the same bed as on the first.
    """
    score = await database.adjust_relationship(user_id, guild_id, BED_FLUFF)
    return Effect(relationship=score, delta=BED_FLUFF)


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
