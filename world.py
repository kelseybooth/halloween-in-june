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
import telemetry
import resolve
import states
import telemetry

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
RAMP_STEP = 25

# All three live in config, because all three are numbers a beta would
# plausibly retune - and a tuning change made in code leaves no dated
# trace, so the interaction rows from before and after it cannot be
# told apart. These are the key names; the values and their defaults
# are in `database.CONFIG_KEYS`.
PLAY_COOLDOWN_SETTING = "toy_cooldown_minutes"
TOY_BASE_SETTING = "toy_base_points"
TOY_DECAY_SETTING = "toy_daily_decay_percent"


async def play_cooldown(guild_id: int) -> timedelta:
    """How long the cat needs after a play, for this server."""
    minutes = await database.get_setting(guild_id, PLAY_COOLDOWN_SETTING)
    return timedelta(minutes=minutes)


def play_value(nth: int, base: int, decay_percent: int) -> int:
    """What the `nth` successful play of a player's day is worth.

    Each play pays a fixed fraction of the one before it, so the day
    runs 10, 8, 6, 4, 3, 2, 2, 1, 1, 1, 1 and then nothing - thirty
    nine points in all, most of them in the first hour of playing.

    **A curve rather than a cap**, and the difference is what a player
    sees. A cap pays full value and then abruptly pays nothing, which
    reads as the game breaking; this tails off, so the eleventh play
    paying one point is obviously the same rule as the second paying
    eight. Nothing announces it and nothing needs to.

    The zero at the end is the curve reaching it, not a separate rule.
    A play worth nothing is still a play: it lands, it resets the
    ramp, it is recorded, and it counts toward *Tireless*.

    **Rounded half up, not with `round`.** Python rounds halves to the
    nearest even number, so a fifty per cent decay would pay 20, 10, 5
    and then 2 - because `round(2.5)` is 2. The shipped curve has one
    half in it and lands on 8 either way, so this changes nothing
    today and stops the dials surprising whoever turns them.
    """
    return int(base * (decay_percent / 100) ** (nth - 1) + 0.5)


async def toy_base_points(guild_id: int) -> int:
    """What this server pays for the first play of a player's day."""
    return await database.get_setting(guild_id, TOY_BASE_SETTING)


async def toy_decay_percent(guild_id: int) -> int:
    """What each play is worth as a percentage of the one before it."""
    return await database.get_setting(guild_id, TOY_DECAY_SETTING)


# Feeding. **A set of ids rather than a type or a column**, and that is
# still the thing here worth revisiting. There is no `food` type, the
# five cans are `object` like everything else carriable, and `requires`
# stopped marking them the day the salmon got its pull-tab. An explicit
# list beats a prefix match, which would sweep in the seven
# `cat_food_stash_*` sources.
#
# The expired can is a can of cat food and is **not** a feed, and the
# split is load-bearing rather than tidy. She takes one breath of it and
# walks away: it does not satisfy her hunger, so it must not stamp the
# timer; it earns no *Room Service* and opens no room; and it posts no
# public line, because nothing was fed. Everything that asks "is this a
# meal" reads `FEEDS`; only the two questions that are really about the
# object - is this a can, and does reaching for one count as turning up
# - read `CAT_FOOD`.
CAT_FOOD_EXPIRED = "cat_food_expired"
FEEDS = frozenset({
    "cat_food_chicken",
    "cat_food_salmon",
    "cat_food_tuna",
    "cat_food_gourmet",
})
CAT_FOOD = FEEDS | {CAT_FOOD_EXPIRED}
HUNGER_WINDOW = timedelta(hours=8)

# What a feed is worth: parity with a toy success, for an action that
# comes round twice a day instead of every ten minutes. The number is
# here beside the bed's fifteen rather than in a content column -
# `relationship_delta` on `things.tsv` is drop 40's work, and moving
# four constants out of code is not a thing to do halfway.
FEED_POINTS = 10

# Her bowl, which every flavor requires. It is a fixture in the
# Entryway, so the requirement is met from the room rather than from
# the bag - see `database.requirements_met`.
CAT_BOWL = "cat_bowl"

# Before this drop there is no food in the game, so every player has
# never been fed and would read as permanently hungry. The gate is what
# stops `/stats` promising a mechanic that does not exist yet.
#
# **Ten, not three, since the 26 October renumbering.** Drop 3 became the
# craving game and the house moved to 10, which is where the cat food
# rows live. Left at 3 this would have announced a hungry cat seven drops
# before there was anything to feed her with.
FEEDING_FROM_DROP = 10

# The craving game. Nothing announces it, and nothing in `/stats` mentions
# it before this - the hint is the whole of the game's visible surface, so
# showing it in a server where no craving is being drawn would be a clue
# pointing at nothing.
CRAVING_FROM_DROP = 3


def play_chance(ramp: int) -> int:
    """Percentage chance that this attempt lands, from the ramp."""
    return min(100, max(0, RAMP_STEP * ramp))
PLANKS_SETTING = "staircase_planks"
STAIRS_REPAIRED = "stairs_repaired"

# The last fifth of the staircase is out of reach from the floor. At the
# default ninety that is plank 72, where `stairs_upper` is set and the
# repair stops until somebody brings the ladder, which is drop 30.
#
# A fraction rather than a number so that a QA server with
# `staircase_planks = 5` reaches the same moment at plank 4 instead of
# never reaching it at all.
STAIRS_UPPER = "stairs_upper"
WITHIN_REACH = 0.8

# The ladder. One per server, carried anywhere by anybody, and the only
# way to reach the top fifth of the staircase.
#
# **Its `yields` is a label, not a behaviour.** `wasp_nest_piece` is
# written in the ladder's `yields` cell so the loader counts the piece
# as a thing players can obtain - without it the piece is content with
# quantity zero and no way in, which the checker calls unreachable. The
# engine must not read it as a yield: a climb produces a piece on the
# road and nowhere else, and `/take ladder` produces a ladder.
LADDER = "ladder"
NEST_PIECE = "wasp_nest_piece"

# Where the wasp nest is: over the road, which is the channel.
ROAD = content_module.CHANNEL_ROOM

# How often she gets to the top first, in percent, and how long she
# keeps it afterwards. Play, with the claws tucked in - no relationship
# points either way, which is why nothing here touches the meter.
CAT_TAKES_IT_PERCENT = 10
GUARDED_MINUTES = 5

# How long a carrier may go quiet before the ladder is set down where
# they stand. It only ever happens to somebody who picked it up and
# stopped playing *without climbing it*, because every climb sets it
# down - and the cost of that is the last eighteen planks stalling for
# the whole server.
IDLE_HOURS = 24

# The ladder's two rows that are not about a room. Neither is a state
# in the `states` sense: nothing holds them and nothing sets them. They
# are conditions of one object, read by id and state together.
CAT_CLIMB = "cat"
GUARDED = "guarded"

# The third thing a climb reports, beside those two. Not a text row -
# no line changes because the ladder was on your shoulder - but the log
# wants it, because "was it carried" is how often anybody fetches the
# ladder rather than climbing one somebody else left standing.
CARRIED = "carried"

# The kitchen trash can. A container players throw things into, fish
# things out of, and empty - three mechanics on one fixture, and the
# only `/take` in the game that does something other than pick a thing
# up.
TRASH_CAN = "trash_can"

# Where a one-of-a-kind thing may not be put back. The Secret Library
# is excluded because a player who has not found it could never get the
# thing back, which would turn taking the trash out into a way of
# destroying the one thing the bin is not allowed to destroy.
NO_PUTTING_BACK_IN = ("SE",)

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


# The road and the house, which is the pair of exits drop 10 adds: the house
# across the road, and the front door back out of it.
HOUSE = "house"
FRONT_DOOR = "front_door"

# The house starts locked, for the whole server, and one brass key opens
# it for the whole server. **A server state rather than a player one**,
# for the reason the staircase is: the work is collective and so is the
# reward. Turning it is a one-way door, like every other state.
#
# The door being locked is what makes drop 10 a thing players do
# together rather than nine people doing the same thing in parallel. The
# key falls out of the cat bed, taking it is public, and whoever has it
# has to be asked.
HOUSE_UNLOCKED = "house_unlocked"
HOUSE_KEY = "house_key"
HOUSE_FROM_DROP = 10

# How long after a key falls before the bed will give up another. The
# spare exists because the first finder can go quiet - they take the key
# and never come back, and without this the server is locked out of the
# house for good by one person's Tuesday.
#
# **A day rather than an hour**, because the point is insurance and not
# supply: a key an hour would make the first one worthless and the
# cooperation the door exists to create pointless. And it stops for good
# the moment the door opens, so a server that solved it never sees a
# second one.
KEY_INTERVAL = timedelta(hours=24)

# The Entryway's inner doorways, which do not exist for a player who has
# not fed the cat. Drop 10 is one room and one task; without this a
# player who walks in at drop 30 is handed four rooms before they have
# learnt what one is for.
#
# **This is the only per-player gate on an exit in the game, and it is
# safe for exactly one reason: feeding can always be completed inside the
# Entryway.** The cat is in every room, the bowl is a fixture here, and
# the salmon stash behind the coat tree never runs out - so a player
# behind the gate is always one `/look`, one `/take` and one `/use` from
# being past it. Nobody can be stranded. If a later drop ever makes
# feeding need something the Entryway cannot supply, this gate becomes a
# locked door with the key on the other side of it, and it has to go.
#
# The front door is deliberately not in here. Leaving is always allowed.
FEEDING_GATED_EXITS = frozenset({"ED", "EL", "EH"})


# Exits no `rooms_unlocked` check applies to, for three different reasons.
#
# The front door, because leaving is always allowed: the feeding gate on the
# Entryway's other exits is there to stop a player being handed nine rooms at
# once, and stepping back outside cannot overwhelm anybody.
#
# The house, because it is the exit that enrols people - a player on the road
# has no row to have unlocked anything in yet.
#
# The oak, because an exit gated on the state its own use produces is a locked
# door with the key inside, and nobody would ever find the library.
UNGATED_EXITS = frozenset({OAK, HOUSE, FRONT_DOOR})


# Most specific first. `_best` takes the first of these an entity actually has
# a row for, so the same list works for every exit: a player who has opened
# the passage reads the open cabinet, and asked about the oak the list falls
# past both to the oak's own `library_found` row.
EXIT_STATES = (HOUSE_UNLOCKED, PASSAGE_OPEN, HAS_KEY, LIBRARY_FOUND)


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

    Three doors, and the front one is not like the other two. The
    cabinet and the passage are shut per player, because the discovery
    is the content; the house is shut for everybody at once and opens
    for everybody at once, so the state behind it is the server's.

    The oak is deliberately not here: an exit gated on the state its own
    use produces is a locked door with the key inside. **The front door
    looks like exactly that and is not**, because the key does not come
    from inside the house - it comes out of the cat bed, on the road,
    where anybody can reach it.
    """
    if thing_id == HOUSE:
        return HOUSE_UNLOCKED not in held
    if thing_id == CABINET:
        return HAS_KEY not in held
    if thing_id == BACK_OF_CABINET:
        return PASSAGE_OPEN not in held
    return False


def use_refused_by(thing_id: str, held: set[str]) -> bool:
    """Whether a use is refused outright by the states in force.

    `exit_refused_by` for things that are not doors, and it has one
    member: the brass key, once the door it opens is open.

    **It has to be code, and the content shows why.** The key's
    `house_unlocked` row carries a refusal and no success, which is
    normally how a writer says "this stops working" - but text
    resolution falls past an empty cell to the next state and then to
    `default`, and the key's `default` row is the one with the success
    in it. So the row would be read straight through and the door
    unlocked a second time. Every other thing written this way has the
    blank on `default`, where there is nothing left to fall to.
    """
    return thing_id == HOUSE_KEY and HOUSE_UNLOCKED in held


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
    # Whether the cat played, which is **not** the same question as
    # whether the score moved. A play past the day's cap does
    # everything a play does except pay, so a handler reading success
    # off `relationship` would show it the refusal copy and hold the
    # public line back - the opposite of what the cap is for.
    played: bool = False
    # Whether this feed was the player's first, which is what the
    # Entryway's one-time notice rides on. Reported rather than asked
    # for afterwards: by the time the handler could ask, the flag is
    # already written and the answer is always yes.
    first_feed: bool = False
    # The state to read this thing's line from, when the use itself
    # decided which line it was. Everything else keys its text on where
    # the player is standing and what the house has become; the ladder
    # keys one line on a coin toss, and the toss happens here.
    text_state: str | None = None
    # Whatever a predicate needs to know about this use that the thing
    # id and the room cannot say. *Hive Five* is the case: a climb on
    # the road knocks a piece off the nest and a climb the cat won does
    # not, and both are `on_use` of the ladder in the road.
    extra: dict = field(default_factory=dict)

    @property
    def changed_the_world(self) -> bool:
        return self.announce is not None


async def planks(guild_id: int) -> tuple[int, int]:
    """(placed, required) for this server's staircase.

    Counted by plank rather than by player. It was by distinct player
    while the cooldown was 48 rolling hours and ten people finished the
    job; drop 20 makes it ninety planks at one per player per day, so a
    server of 27 takes about three and a half days and the people who
    turn up twice as often do not finish it alone.
    """
    placed = await database.total_uses_of(guild_id, LUMBER)
    required = await database.get_setting(guild_id, PLANKS_SETTING)
    return placed, required


def reachable_from_the_floor(required: int) -> int:
    """How many planks go in before the top steps are out of reach.

    Rounded down, so a five-plank QA server stops at four and a
    ninety-plank one at seventy-two.
    """
    return int(required * WITHIN_REACH)


async def check_staircase(guild_id: int) -> bool:
    """Move the staircase on if this plank was the one that did it.

    Two thresholds now, and they are checked in the order they happen.
    `stairs_upper` is the last fifth, where the work stops being
    something a person can reach from the floor; `stairs_repaired` is
    the end of it.

    Called after each plank and again whenever `staircase_planks`
    changes, which is what makes lowering the target finish a stalled
    staircase rather than leaving it stuck one plank short of a number
    nobody can reach. Lowering it past a threshold already crossed is
    why both are plain `>=` tests on the count rather than anything
    that watches for the moment of crossing.

    Returns True only when the staircase *finished* on this call, which
    is what the public line and the lumber's own reply read.
    """
    placed, required = await planks(guild_id)
    if placed >= reachable_from_the_floor(required):
        if await states.set_server_state(guild_id, STAIRS_UPPER):
            # Only on the crossing. `set_server_state` returns True the
            # once, which is what keeps this one row and not one per
            # plank laid against a staircase that has already stopped.
            await telemetry.system(
                guild_id,
                telemetry.STAIRS_UPPER_REACHED,
                detail=(
                    f"n={placed} total={required} "
                    f"players={await database.distinct_users_of(guild_id, LUMBER)}"
                ),
            )
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

    if thing_id == LADDER:
        return await _climb_the_ladder(guild_id, user_id, room_id)

    if thing_id == CAT_BED:
        return await _fluff_the_bed(guild_id, user_id)

    if thing_id in FEEDS:
        return await _feed_the_cat(guild_id, user_id)

    if thing_id == HOUSE_KEY:
        return await _unlock_the_front_door(guild_id)

    return None


async def _climb_the_ladder(
    guild_id: int, user_id: int, room_id: str, rng=None
) -> Effect:
    """Climb it, which always ends with it standing in the room.

    Three things happen here and the order matters.

    **It is set down first, whatever else follows.** Climbing a ladder
    you are carrying means putting it down and going up it, so a
    carried ladder leaves the bag on every climb including the one the
    cat wins. That is also the whole reason the idle sweep below is
    rare: a player who uses the ladder at all has already let go of it.

    **Then the cat gets her roll**, one climb in ten. She replaces the
    room's line rather than adding to it - the player never gets to the
    top - which is why no nest piece falls on a climb she takes, and
    why the line comes back as a state for the handler to read rather
    than as text. Nothing touches the relationship meter: the swat is
    play with the claws in, and the design is explicit that it pays
    nothing either way.

    **Then the road, and only the road.** Every other climb is for the
    view. The nest hangs over the channel and never runs out, so a
    piece lands on the floor there for anybody to pick up - the cat
    bed's pattern, and for the cat bed's reason: it goes into the room
    rather than the bag, where the next person along can have it
    instead.

    **What it reports.** Three facts go back in `extra` - whether the
    ladder was being carried, whether the cat took it, and whether a
    piece of nest fell - because all three are questions about one
    `/use` of one thing, and the handler writes them into that use's
    own log row. A second row per climb would be two records of one
    event, which is how a count ends up doubled.
    """
    carried = await database.drop_into_room(user_id, guild_id, room_id, LADDER)
    facts = {CARRIED: carried, CAT_CLIMB: False, NEST_PIECE: False}

    if (rng or random).randint(1, 100) <= CAT_TAKES_IT_PERCENT:
        until = await database.server_now(guild_id) + timedelta(
            minutes=GUARDED_MINUTES
        )
        await database.lock_thing(guild_id, LADDER, until)
        return Effect(text_state=CAT_CLIMB, extra={**facts, CAT_CLIMB: True})

    if room_id != ROAD:
        return Effect(extra=facts)

    await database.place_in_room(guild_id, ROAD, NEST_PIECE, 1)
    return Effect(extra={**facts, NEST_PIECE: True})


async def ladder_is_guarded(guild_id: int) -> bool:
    """Whether the cat is still sitting on it.

    Asked by `/take` and `/use` before either does anything, and
    answered out of the lock rather than out of the content: a timed
    lock is not a state, so there is no row for `_state_refusal` to
    find and the two refusals the writers wrote for `guarded` have to
    be fetched by name.
    """
    return await database.thing_is_locked(guild_id, LADDER)


async def set_down_forgotten_ladders(
    guild_ids: "list[int]",
) -> list[tuple[int, int, str]]:
    """Take the ladder off anybody who has been holding it for a day.

    Returns (guild, player, room) for each one actually set down, so the
    caller can say so in the room it landed in. Only rows that moved
    are reported: two sweeps overlapping would otherwise announce the
    same ladder twice, and the move is what decides, not the query.

    **The only thing in the game that can be hoarded**, which is the
    whole justification for a sweep. Everything else a player carries
    is theirs or inexhaustible; the ladder is one object the last
    eighteen planks of a shared staircase need.
    """
    moved = []
    for guild_id in guild_ids:
        quiet_since = await database.server_now(guild_id) - timedelta(hours=IDLE_HOURS)
        for user_id, room_id in await database.idle_carriers(
            guild_id, LADDER, quiet_since
        ):
            if await database.drop_into_room(user_id, guild_id, room_id, LADDER):
                await telemetry.system(
                    guild_id, telemetry.LADDER_ABANDONED, detail=f"room={room_id}"
                )
                moved.append((guild_id, user_id, room_id))
    return moved


@dataclass
class TrashRun:
    """What taking the bag out to the curb actually did.

    Two lists, because the two halves read differently to a player. The
    deleted things are gone and nothing says which; the one-of-a-kind
    ones are somewhere else in the house, and the only hint is a clink
    on the steps. The caller needs the second list to know whether to
    say even that much.
    """

    deleted: list[tuple[str, int]] = field(default_factory=list)
    # (thing_id, room_id, container_id) for each one put back.
    put_back: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def was_empty(self) -> bool:
        return not self.deleted and not self.put_back


async def renewable_things() -> set[str]:
    """Everything the house can make another of, by any route it has.

    The test the trash can applies, and the only one: a thing the house
    produces again costs the server nothing when it goes out to the
    curb, so it goes. Cat food, candy, spice jars, bottles, diapers,
    toys, herbs, pieces of wasp nest - all of those come back.

    **`type:` rows are expanded here**, because this is the layer that
    knows what the prefix means. The toy restock names `type:toy`, so
    every toy is renewable including the ones whose drop has not landed:
    a toy thrown away now and restockable in a fortnight is still a
    thing the house can make more of.

    Global rather than per server. It is a fact about the content files,
    and two servers cannot disagree about whether the house has a
    cupboard full of salmon.
    """
    named = await database.things_the_house_makes()
    renewable = set()
    for thing_id in named:
        if thing_id.startswith(content_module.CLASS_PREFIX):
            kind = thing_id[len(content_module.CLASS_PREFIX) :]
            renewable |= await database.thing_ids_of_type(kind)
        else:
            renewable.add(thing_id)
    return renewable


async def places_to_put_things_back(guild_id: int) -> list[tuple[str, str]]:
    """(room, container) for every container a thing could be put back in.

    **Containers only, never a bare floor.** The clink on the steps is
    the whole of the hint, and a music box lying in the middle of the
    Entryway would be found by the next person to type `/look` rather
    than by anybody looking for it. Tucked inside something, it has to
    be searched for.

    Three exclusions. A container with `scatter_target = no` is out -
    the same column and the same reason the restock scatter reads it:
    the shipping box holds David's spice order, and the trash can is
    where the thing has just come from. The Secret Library is out
    because a player who has not found it could never get the thing
    back. And a container whose drop has not arrived is out, because a
    thing put there is a thing in a room nobody can reach.
    """
    arrived = await resolve.arrived_drop_ids(guild_id)
    return sorted(
        (room_id, thing_id)
        for thing_id, room_id, scatter, since_drop in (
            await database.containers_in_rooms()
        )
        if room_id
        and scatter
        and thing_id != TRASH_CAN
        and room_id not in NO_PUTTING_BACK_IN
        and since_drop in arrived
    )


async def take_the_trash_out(guild_id: int, room_id: str, rng=None) -> TrashRun:
    """Empty the trash can: delete what is replaceable, rehome what is not.

    **The brass key is in the second group on purpose.** Before the
    front door opens, the cat bed's spare is the only other one - so
    throwing the only key away would lock a server out of its own house
    until the bed happened to drop another.

    Nothing is put back if there is nowhere to put it, which a server
    whose drop has opened no container could manage. The thing is
    deleted in that case rather than left in limbo, and what the player
    reads is the same either way: the clink is not a promise about where
    anything went.
    """
    inside = await database.empty_container(guild_id, room_id, TRASH_CAN)
    if not inside:
        return TrashRun()

    renewable = await renewable_things()
    destinations = await places_to_put_things_back(guild_id)
    run = TrashRun()
    for thing_id, count in inside:
        if thing_id in renewable or not destinations:
            run.deleted.append((thing_id, count))
            continue
        # One at a time, each drawn separately. Two copies of a
        # one-of-a-kind thing is not a case the content has, and the
        # loop reads the same if it ever does.
        for _ in range(count):
            where, container = (rng or random).choice(destinations)
            await database.place_in_room(
                guild_id, where, thing_id, 1, container_id=container
            )
            run.put_back.append((thing_id, where, container))
    log.info(
        "Guild %s took the trash out: deleted %s, put back %s",
        guild_id,
        run.deleted,
        run.put_back,
    )
    return run


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

    **The brass key comes out first, and instead.** While the front door
    is locked the bed is the only source of one, so a fluff that could
    produce a key produces a key and nothing else - and it does so
    without spending this player's one toy, which they can still have on
    a later fluff. The key is the server's business and the toy is
    theirs, and a fluff that quietly swapped one for the other would
    cost somebody a toy for being first to the bed.
    """
    key = await _a_key_falls_out(guild_id, user_id)
    if key:
        return key

    if await database.has_been_told(guild_id, user_id, BED_STASH):
        return None
    arrived = await resolve.arrived_drop_ids(guild_id)
    pool = await database.stock_of_type(TOY, arrived)
    if not pool:
        # No toys here yet, so there is nothing in the bed to find. The
        # flag stays unset: this player gets theirs when drop 2 opens.
        return None

    thing_id = (rng or random).choice(pool)
    await database.place_in_room(guild_id, content_module.CHANNEL_ROOM, thing_id, 1)
    await database.notice(guild_id, user_id, BED_STASH)
    log.info("The bed gave %s to %s in guild %s", thing_id, user_id, guild_id)
    return thing_id


async def _a_key_falls_out(guild_id: int, user_id: int) -> str | None:
    """Drop a brass key on the road, if one is due. Its id, or None.

    Three conditions, and each rules out a different kind of nonsense.
    **The drop**, because before 10 there is no house for it to open.
    **The door still being locked**, because a key is insurance against
    being shut out and there is nothing to be shut out of afterwards.
    And **a day since the last one**, which is what makes the second key
    a spare rather than a supply.

    **The clock comes off the log rather than a column**, which is the
    thing here most worth arguing with. Normally that is the wrong way
    round - `interaction_log` started empty on servers that had already
    been played, which is why *Tireless* counts `thing_uses` instead.
    It is right here because the mechanic and the log start together:
    no key has ever fallen on any server, so there is no history for an
    empty table to misrepresent. The row is written here beside the
    placement rather than by the caller, so the two cannot come apart.
    """
    drop = await resolve.current_drop(guild_id)
    if drop is resolve.NO_GAME or drop < HOUSE_FROM_DROP:
        return None
    if HOUSE_UNLOCKED in await states.in_force(guild_id, user_id):
        return None

    last = await database.last_logged_at(guild_id, database.KEY_DROPPED)
    if last is not None and await database.server_now(guild_id) - last < KEY_INTERVAL:
        return None

    await database.place_in_room(
        guild_id, content_module.CHANNEL_ROOM, HOUSE_KEY, 1
    )
    await telemetry.system(
        guild_id,
        database.KEY_DROPPED,
        user_id=user_id,
        thing_id=HOUSE_KEY,
        outcome=database.SUCCESS,
        detail="first" if last is None else "spare",
    )
    log.info(
        "Guild %s: a brass key fell out of the bed for %s", guild_id, user_id
    )
    return HOUSE_KEY


async def play_with(guild_id: int, user_id: int, now, rng=None) -> Effect:
    """Offer a toy, and see whether the cat is in the mood.

    **Not keyed on which toy.** Every row with `type = toy` behaves
    identically; the ramp, the cooldown and the award all belong to the
    player. That is what keeps the eleven toys still in the bank a
    content change rather than an engine one.

    A success pays what `play_value` says the day's nth play is worth,
    resets the ramp and starts the cooldown. A refusal advances the
    ramp one rung and starts nothing, so the next offer is likelier -
    which is the whole mechanic, and the reason the refusal copy
    promises nothing while leaving the retry open.

    **Far enough down the curve a success pays nothing, and is still a
    success.** It resets the ramp, starts the cooldown, records the
    use and reads to the player exactly as any other play does. The
    falling value is deliberately invisible: a player who has had
    eleven plays today is not told that the twelfth is free, because
    the point of the curve is that there is no edge to notice.
    """
    ramp, _ = await database.play_state(guild_id, user_id)
    # Resolved at call time, not bound as a default: a default argument
    # captures this module's `random` when the function is defined, so
    # patching `world.random` would leave the default pointing at the
    # original and the roll would quietly stay real.
    roll = (rng or random).random()
    succeeded = roll * 100 < play_chance(ramp)

    cooldown_until = None
    if succeeded:
        cooldown_until = now + await play_cooldown(guild_id)
    landed = await database.record_play(
        guild_id, user_id, succeeded=succeeded, cooldown_until=cooldown_until
    )
    if not succeeded:
        return Effect(tokens={"ramp": landed}, public=False)

    # Counted before it is valued, because the count is what the value
    # is a function of. `nth` rides along in the tokens so the handler
    # can log where on the curve this play fell - which is the whole
    # question the curve raises: where do players stop.
    nth = await database.count_toy_play(
        guild_id, user_id, await database.server_today(guild_id)
    )
    paid = play_value(
        nth, await toy_base_points(guild_id), await toy_decay_percent(guild_id)
    )
    tokens = {"ramp": 0, "play": nth}

    # Nothing to report but the play itself: the meter did not move, so
    # there is no new score and no delta for the relationship hook to
    # fire on. The handler is what writes the zero into the log, where
    # a zero beside `success` is a play that paid nothing rather than a
    # refusal.
    if not paid:
        return Effect(tokens=tokens, public=True, played=True)

    score = await database.adjust_relationship(user_id, guild_id, paid)
    return Effect(
        tokens=tokens, public=True, played=True, relationship=score, delta=paid
    )


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


async def _feed_the_cat(guild_id: int, user_id: int) -> Effect:
    """Ten points, and the first time, the room opens up.

    **The gate is written here rather than beside the achievement**, even
    though they fire on the same event. `fed_the_cat` is read on every
    `/look` in the Entryway and on every move out of it, and a predicate
    that had to join the awards table to answer it would be a second
    shape of the same question. One flag, one source, one query.

    Nothing is consumed here: `consumed_on_use` takes the can, in
    `_finish_use`, which is where every other use loses what it spent.
    """
    score = await database.adjust_relationship(user_id, guild_id, FEED_POINTS)
    # `notice` reports the transition, which is the whole of "the first
    # feed": the handler needs it to decide whether the room has just
    # opened, and asking afterwards would always say yes.
    first = await database.notice(guild_id, user_id, content_module.FED_THE_CAT)
    return Effect(relationship=score, delta=FEED_POINTS, first_feed=first)


async def _unlock_the_front_door(guild_id: int) -> Effect:
    """Turn the key, for everybody.

    **Reached only while the door is locked**, and that falls out of the
    content rather than being checked here: the key's `house_unlocked`
    row has no `use` text, so `/use key` on an open door is refused
    before any effect runs. One rule, written once, in the one place a
    writer can see it.

    No relationship points. The door is a puzzle the server solves, not
    something done for the cat, and paying for it would make the second
    key-holder's failed attempt feel like a loss.
    """
    opened = await states.set_server_state(guild_id, HOUSE_UNLOCKED)
    if opened:
        log.info("Guild %s: the front door is unlocked", guild_id)
    return Effect(public=False)


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
