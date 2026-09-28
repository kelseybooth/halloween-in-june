"""The thirty-five conditions, and what each one listens on.

The engine is in `achievements`; this is the content-facing half. Every
function here answers one question - *did that action just earn this?* - and
none of them writes anything. A trigger that mutates game state makes the same
action behave differently depending on what the player had already earned,
which is a bug that only shows up in somebody's second October.

Read this beside the **Achievement Trigger Spec**, which is authoritative for
what fires. Where a predicate departs from it, the docstring says so and why.

Three families do most of the work and are written once:

- **the date-gated seven** share `_on_date`, parameterised by a day test and a
  set of targets, because six fixed dates and one weekday are the same shape
- **the three group achievements** share one per-room read, because all three
  are the same `GROUP BY room_id` with a different `HAVING`
- **the seven blocked** share `_blocked`, which is a predicate that says no.
  They are registered anyway: the loader's both-directions check stays
  meaningful, and cat crossing arriving after launch turns three of them on
  without reopening this phase

Everything else is a singleton, and most are two lines.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import date, datetime, time, timedelta, timezone

import achievements
import alexa
import craving
import database
import states
from achievements import Context

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# The things the conditions name
#
# Ids rather than names, because the code references ids and a writer can
# rename anything without a deploy. `test_triggers.py` asserts every one of
# these exists in the shipped content, which is the check that catches a
# rename here going stale.
# --------------------------------------------------------------------------

STOVE = "stove"
READING_GLASSES = "reading_glasses"
BABY_MONITOR = "baby_monitor"
COSTUME = "costume"
CANDY = "candy"
PUMPKINS = "pumpkins"
CARVING_TOOLS = "carving_tools"
WATERING_CAN = "watering_can"
HERB_GARDEN = "herb_garden"
HERBS = "herbs"
KEURIG = "coffee_maker"
TRASH_CAN = "trash_can"
PASTA_POT = "pasta_pot"
NACHO_CHIPS = "nacho_chips"
FROZEN_BURRITO = "frozen_burrito"
GRAPHITE = "graphite_powder"
# The oak tree in the Courtyard is an exit, not an object - using it moves the
# player into the Secret Library, which is why this listens on `on_move`.
TREE = "CS"
COURTYARD = "CO"

MIRRORS = {"ornate_mirror", "cracked_mirrors", "dresser_mirror"}

CAT_FOOD = {
    "cat_food_chicken",
    "cat_food_salmon",
    "cat_food_tuna",
    "cat_food_gourmet",
    "cat_food_expired",
}
BABY_BOTTLES = {"used_baby_bottle", "sanitized_baby_bottle"}

# The numbers, gathered so a balance pass can find them all in one place.
BULK_BUYER_CANS = 25
CATPROOF_BOTTLES = 5
BURRITOS_EATEN = 10
FRIENDLY_PETS = 200
PERFECT_RELATIONSHIP = database.RELATIONSHIP_MAX
STRENGTH_IN_NUMBERS = 25
MAKING_A_MESS = 200
FELINE_COLLECTION_CANS = 100
LOST_ARRIVALS = 5
LOST_WINDOW = timedelta(minutes=5)


# --------------------------------------------------------------------------
# The 43-hour day
#
# A date achievement's day is not a calendar day. The players run from Japan
# to Hawaii, nineteen hours apart, so any single Pacific calendar day shuts
# somebody out at one end or the other. "On 1 October" means 30 September
# 08:00 Pacific through 2 October 03:00 Pacific - exactly the union of "1
# October in local time" across UTC+9 to UTC-10.
#
# Two consequences to hold in mind. Consecutive windows **overlap by nineteen
# hours**, so through 1 October both the 1 October and 2 October achievements
# are live at once; that is harmless only because they watch different things,
# and it is one more reason the dispatcher must not stop at the first match.
# And no Release 1 window crosses a daylight-saving boundary - US DST ends on
# 1 November - so every October window is wholly PDT.
# --------------------------------------------------------------------------

WINDOW_OPENS = time(8, 0)
WINDOW_CLOSES = time(3, 0)


def window_bounds(day: date) -> tuple[datetime, datetime]:
    """Half-open [open, close) naive-UTC bounds of one achievement's day."""
    opens = datetime.combine(day - timedelta(days=1), WINDOW_OPENS, tzinfo=database.PACIFIC)
    closes = datetime.combine(day + timedelta(days=1), WINDOW_CLOSES, tzinfo=database.PACIFIC)
    return (
        opens.astimezone(timezone.utc).replace(tzinfo=None),
        closes.astimezone(timezone.utc).replace(tzinfo=None),
    )


def in_window(now: datetime, day: date) -> bool:
    opens, closes = window_bounds(day)
    return opens <= now < closes


def _window_is_open(now: datetime, matches: "Callable[[date], bool]") -> bool:
    """Whether any day satisfying `matches` has its window open right now.

    Three candidate days are enough: a window reaches at most one day back and
    one day forward from the local date, so nothing further out can contain
    `now`. This is what lets the Tuesday rule and the six fixed dates run off
    the same function.
    """
    local = now.replace(tzinfo=timezone.utc).astimezone(database.PACIFIC).date()
    for offset in (-1, 0, 1):
        day = local + timedelta(days=offset)
        if matches(day) and in_window(now, day):
            return True
    return False


def on_october(day_of_month: int) -> "Callable[[date], bool]":
    """A fixed October date, in any year.

    Year-agnostic on purpose: pinning 2026 would quietly retire seven
    achievements on 1 January, and "this thing, this day, Pacific" says
    nothing about the year.
    """
    return lambda day: day.month == 10 and day.day == day_of_month


def on_tuesday(day: date) -> bool:
    """Widened like the fixed dates - Monday 08:00 through Wednesday 03:00.

    Without it a player in Japan could only earn *Curbside Pickup* between
    17:00 Tuesday and 17:00 Wednesday their time. The nearest Tuesday windows
    to 1 October close on 30 September at 03:00 and reopen on 5 October at
    08:00, both clear of the 1 October window, so this introduces no collision
    with *Trash Panda*.
    """
    return day.weekday() == 1


def _on_date(matches, targets: set[str], *, source_only: bool = False):
    """One thing (or one of a set), on one day. Six of the seven are this.

    `source_only` is *Green Thumb*'s `on_take` half: taking herbs **from the
    herb garden** is gardening, and picking up a `herbs` somebody dropped in
    the Entryway is scavenging. Both hand the player an identical thing id, so
    the source is what separates them.
    """

    async def predicate(context: Context) -> bool:
        if not _window_is_open(context.when, matches):
            return False
        if source_only and context.hook == "on_take":
            return context.source_id in targets
        return context.thing_id in targets

    return predicate


# --------------------------------------------------------------------------
# A Little Bit Lost
#
# The only achievement whose state is allowed to be ephemeral, and the only
# one where losing it costs a player nothing they can notice. A restart
# forgets where everyone has been; they wander in a circle again.
# --------------------------------------------------------------------------

# (guild_id, user_id) -> the rooms they have arrived in lately.
_ARRIVALS: dict[tuple[int, int], deque] = defaultdict(lambda: deque(maxlen=64))


def forget_arrivals() -> None:
    """Empty the movement buffer. For tests, and nothing else."""
    _ARRIVALS.clear()


async def a_little_bit_lost(context: Context) -> bool:
    """Any one room entered five or more times inside five minutes.

    Arrivals per room, not round trips and not total moves. A player cannot
    enter a room they are already in, so five arrivals costs at least nine
    moves - Bedroom, Kitchen, Courtyard, Kitchen, Living Room, Kitchen,
    Bedroom, Kitchen, Courtyard, Kitchen is five Kitchen arrivals and earns it.
    The starting room is not an arrival.
    """
    if context.room_id is None:
        return False

    now = context.when
    trail = _ARRIVALS[(context.guild_id, context.user_id)]
    trail.append((context.room_id, now))

    cutoff = now - LOST_WINDOW
    while trail and trail[0][1] < cutoff:
        trail.popleft()

    return sum(1 for room, _ in trail if room == context.room_id) >= LOST_ARRIVALS


# --------------------------------------------------------------------------
# The three group achievements
#
# All three are one `GROUP BY room_id` with a different `HAVING`, and none of
# them names a room. They count `room_contents`, not history: a server that
# reaches 200 and then takes things out keeps it, and a server that reaches
# 199 twice earns nothing. Both correct.
# --------------------------------------------------------------------------


def _group(test):
    async def predicate(context: Context) -> bool:
        totals = await database.room_totals(context.guild_id, CAT_FOOD)
        return any(test(room) for room in totals)

    return predicate


strength_in_numbers = _group(lambda room: room.most_of_one >= STRENGTH_IN_NUMBERS)
making_a_mess = _group(lambda room: room.total >= MAKING_A_MESS)
# Both numbers from the **same** room: 120 cans spread over two rooms that
# each hold 200 things earns nothing.
the_feline_collection = _group(
    lambda room: room.total >= MAKING_A_MESS and room.cat_food >= FELINE_COLLECTION_CANS
)


# --------------------------------------------------------------------------
# The blocked seven
# --------------------------------------------------------------------------


def _blocked(why: str):
    """A predicate that always says no, for a system that does not exist.

    Registered rather than omitted so the both-directions check stays
    meaningful, and so the system arriving later is a registration change
    rather than a reopened phase.
    """

    async def predicate(context: Context) -> bool:
        return False

    predicate.blocked_on = why
    return predicate


# --------------------------------------------------------------------------
# The singletons
# --------------------------------------------------------------------------


def _used(thing_id: str):
    """A successful `/use` of one thing, with no other condition."""

    async def predicate(context: Context) -> bool:
        return context.thing_id == thing_id

    return predicate


async def somethings_cooking(context: Context) -> bool:
    """A successful `/use` of the stove, and nothing more.

    The `requires` gate has already proved the player is carrying the herbs,
    the chocolate and the spice - an unmet requirement refuses the use and
    never reaches this hook. So this does not re-read the inventory, and it
    cannot disagree with the command about whether the conditions were met.
    """
    return context.thing_id == STOVE


async def gourd_job(context: Context) -> bool:
    """Carving a pumpkin, which means holding the tools while using them."""
    if context.thing_id != PUMPKINS:
        return False
    return await database.carried_of(context.user_id, context.guild_id, CARVING_TOOLS) > 0


async def follow_your_nose(context: Context) -> bool:
    """`drawer_unjammed` is set for this player.

    Reads the state rather than the action, so it is true on every later use
    as well - which costs nothing, because the award is idempotent and only a
    first award announces.
    """
    return await states.has(context.guild_id, context.user_id, "drawer_unjammed")


async def out_on_a_limb(context: Context) -> bool:
    """Climbing the oak tree in the Courtyard into the Secret Library.

    **Listens on `on_move`, where the spec says `on_use`.** The tree is an
    exit, and using an exit moves the player - `/use tree` never reaches the
    `on_use` hook at all. Same action, same moment, the hook the code actually
    fires.
    """
    return context.thing_id == TREE


async def not_so_picky_eater(context: Context) -> bool:
    """Ten frozen burritos, cumulative, no time limit.

    The count is read back rather than tracked here: `thing_uses.use_count` is
    already incremented by the time the hook runs.
    """
    if context.thing_id != FROZEN_BURRITO:
        return False
    used = await database.use_count_of(context.user_id, context.guild_id, FROZEN_BURRITO)
    return used >= BURRITOS_EATEN


async def charcuterie_board(context: Context) -> bool:
    """All five flavours at once.

    Fragile in a known way - drop a can to make room and the set breaks - and
    that is accepted, because every flavour comes from a source that cannot
    run out. The alternative, "has ever held each of the five", would have
    cost a table written on every `/take`, and nothing else needed it.
    """
    return await database.carries_all(
        context.user_id, context.guild_id, sorted(CAT_FOOD)
    )


async def catproof_the_house(context: Context) -> bool:
    """Five baby bottles at once, clean and dirty counted together.

    So a player who sanitizes what they collect does not lose progress.
    """
    held = await database.carried_total_of(
        context.user_id, context.guild_id, BABY_BOTTLES
    )
    return held >= CATPROOF_BOTTLES


async def bulk_buyer(context: Context) -> bool:
    """Twenty-five cans of cat food, summed across flavours."""
    held = await database.carried_total_of(context.user_id, context.guild_id, CAT_FOOD)
    return held >= BULK_BUYER_CANS


async def making_friends(context: Context) -> bool:
    """Two hundred pets while the relationship was above zero."""
    pets = await database.pets_while_relationship(
        context.user_id, context.guild_id, positive=True
    )
    return pets >= FRIENDLY_PETS


async def trying_to_make_friends(context: Context) -> bool:
    """Two hundred pets while the relationship was at or below zero.

    Zero counts here rather than toward *Making Friends*, which is the
    boundary the Story Bible was revised to state. It matters on day one: a
    new player starts the game at a relationship the first pet reads.
    """
    pets = await database.pets_while_relationship(
        context.user_id, context.guild_id, positive=False
    )
    return pets >= FRIENDLY_PETS


async def cats_best_friend(context: Context) -> bool:
    """A perfect relationship, which stays true forever once it is true.

    The standing condition the idempotent award exists for: without it this
    would re-announce on every `/pet` for the rest of October.
    """
    relationship = context.extra.get("relationship")
    if relationship is None:
        relationship = await database.get_relationship(context.user_id, context.guild_id)
    return relationship >= PERFECT_RELATIONSHIP


async def passing_a_message_to_david(context: Context) -> bool:
    """Asking Alexa to remind David about the auto-delivery.

    The same test the handler used to choose her reply, so the achievement and
    the answer cannot disagree about what counts.
    """
    said = context.extra.get("content") or ""
    return alexa.is_addressed(said) and alexa.is_message_for_david(said)


async def met_the_craving(context: Context) -> bool:
    """The reaction matched the day's craving emoji."""
    guess = context.extra.get("guess")
    return guess is not None and guess.verdict == craving.CORRECT


# --------------------------------------------------------------------------
# Registration
#
# One call per achievement, in the order the trigger spec lists them, so the
# two documents can be read side by side.
# --------------------------------------------------------------------------


def register_all() -> None:
    """Wire every one of the thirty-five. Idempotent per process."""
    if achievements.registered_ids():
        return

    add = achievements.register

    # Group - all three on one hook, all three the same query.
    add("strength_in_numbers", "on_drop", strength_in_numbers)
    add("making_a_mess", "on_drop", making_a_mess)
    add("the_feline_collection", "on_drop", the_feline_collection)

    # Public
    add("passing_a_message_to_david", "on_message", passing_a_message_to_david)
    add("charcuterie_board", "on_take", charcuterie_board)
    add("found_the_specs", "on_use", _used(READING_GLASSES))
    add("somethings_cooking", "on_use", somethings_cooking)
    add("unsticking_the_situation", "on_cross", _blocked("cat crossing"))
    add("catproof_the_house", "on_take", catproof_the_house)
    add("return_to_sender", "on_cross", _blocked("cat crossing"))
    add("it_takes_a_village", "on_cross", _blocked("cat crossing"))
    add("gourd_job", "on_use", gourd_job)
    add("follow_your_nose", "on_use", follow_your_nose)
    add("baby_talk", "on_use", _used(BABY_MONITOR))
    add("dressed_for_the_season", "on_use", _used(COSTUME))
    add("met_the_craving", "on_reaction", met_the_craving)
    add("forwarding_address", "on_use", _blocked("the letter"))

    # Secret
    add("a_little_bit_lost", "on_move", a_little_bit_lost)
    add("out_on_a_limb", "on_move", out_on_a_limb)
    add("bulk_buyer", "on_take", bulk_buyer)
    add("making_friends", "on_pet", making_friends)
    add("trying_to_make_friends", "on_pet", trying_to_make_friends)
    add("cats_best_friend", "on_pet", cats_best_friend)
    add("signed_sealed_delivered", "on_use", _blocked("the doorbell"))
    add("brewing_trouble", "on_use", _on_date(on_october(1), {KEURIG}))
    add("trash_panda", "on_use", _on_date(on_october(1), {TRASH_CAN}))
    add("say_cheese", "on_use", _on_date(on_october(2), MIRRORS))
    # The one that shapes the signature: three things across two hooks.
    add(
        "green_thumb",
        ("on_use", "on_take"),
        _on_date(
            on_october(15),
            {WATERING_CAN, PUMPKINS, HERB_GARDEN},
            source_only=True,
        ),
    )
    add("nacho_average_ghost", "on_use", _on_date(on_october(21), {NACHO_CHIPS}))
    add("using_your_noodle", "on_use", _on_date(on_october(25), {PASTA_POT}))
    add("getting_into_the_spirit", "on_use", _blocked("the ghost system"))
    add("ghostbuster", "on_use", _blocked("the ghost system"))
    add("breaking_into_the_halloween_candy", "on_use", _used(CANDY))
    add("curbside_pickup", "on_use", _on_date(on_tuesday, {TRASH_CAN}))
    add("not_so_picky_eater", "on_use", not_so_picky_eater)
