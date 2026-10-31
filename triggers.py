"""The thirty-five conditions, and what each one listens on.

The engine is in `achievements`; this is the content-facing half. Every
function here answers one question - *did that action just earn this?* - and
none of them writes anything. A trigger that mutates game state makes the same
action behave differently depending on what the player had already earned,
which is a bug that only shows up in somebody's second October.

Read this beside the **Achievement Trigger Spec**, which is authoritative for
what fires. Where a predicate departs from it, the docstring says so and why.

Three families do most of the work and are written once:

- **the dated three** read the same 43-hour window. *Curbside Pickup* is
  "this thing, on this day" and is the last user of `_on_date`; the two
  holidays have no thing behind them and read `_window_is_open` directly.
  There were nine - six fixed October dates came off on 21 and 30 October,
  and `Date-restricted achievements.md` is authoritative for which
  achievements check a date at all
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
import phrasing
import states
import world
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
# A piece of the wasp nest, knocked down by climbing the ladder on the
# road. The id is the key the climb reports under, which is why this
# names a thing the predicate never looks up.
NEST_PIECE = "wasp_nest_piece"
DIRTY_DIAPER = "dirty_diaper"
KITCHEN = "KI"
# The key the look reports under when it was this player's first in the
# room. Written by the handler, because a predicate that set a flag of
# its own would be deciding something as well as answering.
FIRST_LOOK = "first_look"
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
CAT_BED = "cat_bed"
FRIENDLY_PETS = 200

# The four score thresholds, in the order a player meets them.
PAW_IN_THE_DOOR = 50
PERFECT_RELATIONSHIP = database.PERFECT_RELATIONSHIP  # 100
FAVORITE_HUMAN = 250
# Drop 20, and the first threshold named after something in the house
# rather than after the cat: by a thousand points you are keeping her
# the way David did, and the joke only lands once his name is on the
# packing slip in the hall.
ARE_YOU_DAVID = 1000
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

    Year-agnostic on purpose: pinning 2026 would quietly retire the
    dated achievements on 1 January, and "this thing, this day,
    Pacific" says nothing about the year.
    """
    return lambda day: day.month == 10 and day.day == day_of_month


def on_tuesday(day: date) -> bool:
    """Widened like the fixed dates - Monday 08:00 through Wednesday 03:00.

    Without it a player in Japan could only earn *Curbside Pickup* between
    17:00 Tuesday and 17:00 Wednesday their time. The nearest Tuesday windows
    to 1 October close on 30 September at 03:00 and reopen on 5 October at
    08:00, both clear of the 1 October window - which used to matter, because
    *Trash Panda* watched the same trash can on 1 October. It has no date now,
    so the collision this was written against cannot happen.
    """
    return day.weekday() == 1


# --------------------------------------------------------------------------
# The two October holidays
#
# Both are drop 0, both secret, and neither fits `_on_date`, whose whole
# job is "this thing, on this day" - these have no thing behind them.
#
# They run on the same machinery as the Release 1 seven, which is worth
# saying out loud because the writers specified their windows in UTC and
# the engine computes them from Pacific. 27 October comes out as 26 Oct
# 15:00 to 28 Oct 10:00 UTC and 31 October as 30 Oct 15:00 to 1 Nov 11:00
# UTC, both exactly as the file's notes ask for. The second crosses the
# end of daylight saving, which `window_bounds` gets right by converting
# a Pacific wall-clock time rather than subtracting a fixed offset - and
# it is the first window in the game that does, which dates the note at
# the top of this file saying none of them do.
# --------------------------------------------------------------------------

BLACK_CAT_DAY = 27
HALLOWEEN = 31


async def _is_the_cat(thing_id: str | None) -> bool:
    """Whether using this thing is reaching for the cat.

    The bed, any toy, and any of the cans. Toys by *type*, so a
    thirteenth toy stays a row in a spreadsheet - the same rule the cap
    and the ramp already follow.
    """
    if thing_id is None:
        return False
    if thing_id == world.CAT_BED or thing_id in world.CAT_FOOD:
        return True
    row = await phrasing.thing_row(thing_id)
    return row is not None and row.type == world.TOY


async def lucky_black_cat(context: Context) -> bool:
    """Any cat interaction on Black Cat Day.

    **Any pet counts, friendly or not**, which is the point: this is
    for spending the day with her, not for her enjoying it. The same
    reasoning as the nightly drift, which also stamps on the attempt -
    the toy's first offer is a guaranteed refusal and the bed refuses
    inside its own window.
    """
    if not _window_is_open(context.when, on_october(BLACK_CAT_DAY)):
        return False
    return context.hook == "on_pet" or await _is_the_cat(context.thing_id)


async def familiar(context: Context) -> bool:
    """Being there at all on Halloween.

    No thing and no verb, which makes it the widest condition in the
    file and is the whole joke: somebody who opens `/stats` on 31
    October spent Halloween in a haunted house with a black cat.
    Making them prove it by petting her would be a narrower and worse
    version of the same idea.
    """
    return _window_is_open(context.when, on_october(HALLOWEEN))


def _on_thing(targets: set[str]):
    """One thing (or one of a set), on any day at all.

    **What a dated achievement becomes when the date comes off.** The
    writers retired six of the dates - the rooms three of them need open
    at drop 30, which is after their days had passed, so a dated version
    could not be earned this year by anybody. `Date-restricted
    achievements.md` carries the decision and the reasoning.

    The `since_drop` gate still applies, and for *Self-Reflection* it is the
    whole of what is left: drop 20 opened the Entryway's mirror, and the
    two other mirrors arrive with drops 40 and 50.
    """

    async def predicate(context: Context) -> bool:
        return context.thing_id in targets

    return predicate


async def hive_five(context: Context) -> bool:
    """A climb that knocked a piece off the wasp nest.

    **Read off what the climb reported, not off the thing and the
    room.** Every climb on the road is `on_use` of the ladder in `CH`,
    and only some of them drop a piece: one in ten the cat gets to the
    top first and the climber never reaches the nest. The handler
    passes what actually happened, so this asks that.

    Picking a piece up is not this. It is `on_take` and this listens on
    `on_use`, which is the distinction the file asks for in words -
    somebody else's piece off the floor of the road is scavenging, not
    a climb.

    Awarded once by `_award`, so the predicate does not count. Every
    later climb that drops a piece passes this and creates nothing.
    """
    return bool(context.extra.get(NEST_PIECE))


async def trash_panda(context: Context) -> bool:
    """Anything taken out of the trash can, the first time.

    **Read off the container and not the thing.** Everything that can
    go in the bin can also be picked up off a floor somewhere, so the
    thing id says nothing - it is where the player's hand went that
    makes it going through the trash. Which is why the take hook
    carries the container at all.

    Somebody else's rubbish counts, and that is the file's own wording:
    *went through the trash and came out with something*. Nothing in it
    asks whose.
    """
    return context.container_id == TRASH_CAN


async def bin_looking_for_you(context: Context) -> bool:
    """A dirty diaper carried into the Kitchen, on the first look.

    **One chance, ever**, which is what makes it a secret. Walking into
    a room prints nothing, so a player's first `/look` in the Kitchen is
    the moment they first see the trash can - and if they are not
    holding a diaper then, they never get another go. Diapers have been
    turning up since drop 3 and the carried one already says the player
    has started planning where to put it down; this pays that off.

    The first-look half is reported by the handler rather than asked
    here, because asking would mean writing the flag from a predicate -
    and a predicate that decides as well as answers cannot be run twice
    safely. Nothing else in this file writes anything.
    """
    if context.room_id != KITCHEN or not context.extra.get(FIRST_LOOK):
        return False
    if context.user_id is None:
        return False
    return bool(
        await database.carried_of(context.user_id, context.guild_id, DIRTY_DIAPER)
    )


async def board_meeting(context: Context) -> bool:
    """The plank that finished the staircase.

    **Reads the recipients, which is the same question.** The handler
    puts a list of everybody who laid a plank on the use that crossed
    the line and on no other, so "is there a list" and "did the
    staircase just finish" are one condition - and the predicate stays
    the pure answer it is supposed to be.

    What makes this row different from the other three group ones is
    where the award lands rather than when it fires: *Strength in
    Numbers* goes to the server and names nobody, and this goes to the
    people who did the work. `achievements._award` holds that
    distinction; this only says the moment.
    """
    return bool(context.recipients)


def _on_date(matches, targets: set[str], *, source_only: bool = False):
    """One thing (or one of a set), on one day. *Curbside Pickup* alone.

    It was six of the seven. Five of those lost their dates - the three
    one-liners became `_on_thing`, *Green Thumb* became three parts with
    no day at all, and *Trash Panda* is waiting on a trash can that
    holds things - and this is kept rather than inlined because the
    window machinery it stands on is shared with the two holidays and
    is the part worth having one of.

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
# Green Thumb
#
# The only achievement assembled out of several different actions rather
# than counted or triggered by one, which is what makes it the only one
# that needs to remember anything between commands.
# --------------------------------------------------------------------------

GREEN_THUMB_PARTS = (WATERING_CAN, PUMPKINS, HERB_GARDEN)


async def green_thumb(context: Context) -> bool:
    """Watered, picked and carved. Any order, any days, no date.

    It was 15 October and could not be earned: the Courtyard opens at
    drop 30 and the carving tools at drop 40, both after the day had
    passed. `Date-restricted achievements.md` took the date off and
    replaced it with the thing the deck wanted all along - three jobs a
    gardener does, in whatever order a player gets to them.

    **Three `thing_uses` rows, which is the whole of the state.** Using
    the watering can and carving a pumpkin each stamp one through
    `record_use`; drawing herbs stamps one for the **herb garden**,
    because `take_from_source` is the only path that yields herbs from
    it and the garden's row carries no other meaning. Nothing new is
    stored and nothing is counted - twenty waterings are still one part.

    **The source is what separates gardening from scavenging**, and it
    does it by what gets written rather than by a test here: herbs
    somebody dropped in the Entryway come out of the room, not out of
    the garden, so they stamp nothing and cannot complete a part.

    **No early-out on the thing being used**, though one would save a
    query on every unrelated `/use` in the game. The condition this
    achievement has is "all three parts done" and nothing else, and a
    guard reading "...and this action was one of them" would be a
    second condition that the file does not ask for - true only because
    the third part is always the action that completes it. The read is
    one indexed select on three ids, and `fire` already runs a dozen
    predicates that touch the database.
    """
    done = await database.which_of_these_used(
        context.user_id, context.guild_id, GREEN_THUMB_PARTS
    )
    return len(done) == len(GREEN_THUMB_PARTS)


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


def _by_hand(why: str):
    """A predicate that always says no, for an award nobody plays for.

    Registered rather than omitted for the same reason `_blocked` is -
    the both-directions check only means something if every row has a
    trigger - but it says the opposite thing, and the difference is
    worth a second function rather than a comment on the first.
    `_blocked` is a promise: the system arrives and the predicate gets
    written. This is permanent. The award marks something that happened
    once, to the people it happened to, and no play should ever produce
    another one.
    """

    async def predicate(context: Context) -> bool:
        return False

    predicate.by_hand = why
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


async def _two_hundred_pets_in(context: Context) -> bool:
    """Whether this player has petted the cat enough for the fork.

    **"At least two hundred", not "exactly the two hundredth".** A check
    that only fired on the 200th pet would be lost forever if the bot were
    down, or if two pets raced, and the player would never earn either
    half of a pair they had plainly qualified for.
    """
    total = context.extra.get("total")
    if total is None:
        total = await database.get_pet_count(context.user_id, context.guild_id)
    return total >= FRIENDLY_PETS


async def _already_forked(context: Context) -> bool:
    """Whether this player holds the other half of the fork.

    The two are mutually exclusive, and the only way to guarantee it is
    for each to refuse while the other is held: both become true the
    moment the count is reached, and which one lands depends on the sign
    at that moment.
    """
    held = await database.player_achievements_of(context.guild_id, context.user_id)
    return bool({"making_friends", "trying_to_make_friends"} & set(held))


async def making_friends(context: Context) -> bool:
    """Two hundred pets, and the cat likes you at the end of them.

    **One counter, evaluated once**, rather than two tallies of qualifying
    pets. It used to count only the pets made while the meter was above
    zero, which meant a player could pet two hundred times and earn
    neither - half on each side of the line and neither tally reaching the
    target. Now the count is every pet, and the sign *after* the pet that
    reaches it decides which of the two fires.
    """
    if await _already_forked(context) or not await _two_hundred_pets_in(context):
        return False
    return await _score(context) > 0


async def trying_to_make_friends(context: Context) -> bool:
    """Two hundred pets, and the cat still does not.

    Zero counts here rather than toward *Making Friends* - the boundary
    the Story Bible was revised to state, and the one the new player
    starting at zero makes real.
    """
    if await _already_forked(context) or not await _two_hundred_pets_in(context):
        return False
    return await _score(context) <= 0


async def _score(context: Context) -> int:
    """This player's relationship, from the event if it carried one.

    The three thresholds all read it, and all three are standing
    conditions - true forever once true - which is what the idempotent
    award exists for. Without it each would re-announce every time the
    score moved for the rest of October.
    """
    score = context.extra.get("relationship")
    if score is None:
        score = await database.get_relationship(context.user_id, context.guild_id)
    return score


# Four refusals running. The fifth attempt is at 100%, so five in a row
# has probability exactly zero and four is the rarest thing that can be
# asked for - 0.75 x 0.5 x 0.25, or 9.4%.
BAD_LUCK_RAMP = 4

TIRELESS_PLAYS = 25

# Two, not one. The first play that pays nothing can be an accident of
# a long afternoon; coming back for a second is the thing the
# achievement is about.
PURRSISTENT_PLAYS = 2


# Twenty-five feeds. At eight hours between them that is a fortnight of
# showing up twice a day, which reads as devotion rather than as a
# grind - and the grind was the objection the number survived.
BOWL_HALF_EMPTY_FEEDS = 25


async def room_service(context: Context) -> bool:
    """A successful feed, of any flavor.

    Not "the *first* feed", though that is what the quest says: the
    awards table already grants each achievement once, so a predicate
    that tried to say "first" would be asking a question somebody else
    has already answered. *Fluffed to Perfection* is the same shape.

    The expired can cannot earn it. She takes one breath of it and walks
    away, so it is not in `FEEDS` and nothing here has to say so.
    """
    return context.thing_id in world.FEEDS


async def bowl_half_empty(context: Context) -> bool:
    """Twenty-five feeds, any flavor, cumulative.

    Counted from `thing_uses`, like *Tireless*, and for the reason that
    settled *Tireless*: the interaction log started empty on a server
    that had already been played, so a count derived from it would have
    quietly reset every veteran to zero.

    "Twenty-five or more and not held", never "exactly the
    twenty-fifth", so a feed that races or lands while the bot is down
    does not lose the achievement for good.
    """
    if context.thing_id not in world.FEEDS:
        return False
    fed = await database.uses_of_any(
        context.user_id, context.guild_id, world.FEEDS
    )
    return fed >= BOWL_HALF_EMPTY_FEEDS


async def persuasive(context: Context) -> bool:
    """The first toy play that works."""
    return bool(context.extra.get("played"))


async def impressively_bad_luck(context: Context) -> bool:
    """Four refusals in a row.

    **The ramp already is the consecutive-refusal count**, so this needs
    no counter of its own: it starts at zero, advances only on a failed
    attempt, and resets on a success. Attempts inside the cooldown
    advance nothing, so they cannot contribute - which is the right
    behaviour and falls out rather than needing a rule.
    """
    if context.extra.get("played"):
        return False
    return (context.extra.get("ramp") or 0) >= BAD_LUCK_RAMP


async def tireless(context: Context) -> bool:
    """Twenty-five successful plays, any toy, cumulative.

    Successes rather than attempts: at 3.2 attempts per success that is
    about eighty attempts of honest play, and counting attempts would
    reward the spamming the ramp and the crowding penalty exist to
    discourage.

    "Twenty-five or more and not held", never "exactly the
    twenty-fifth" - the same shape as the two-hundred-pet fork, and for
    the same reason: a check that can only fire on one exact play is
    lost for good if that play races or the bot is down for it.
    """
    return await database.toy_plays(context.guild_id, context.user_id) >= TIRELESS_PLAYS


async def purrsistent(context: Context) -> bool:
    """Two successful plays, ever, that were worth nothing.

    The far end of the day's curve, where a play still lands and still
    counts toward *Tireless* but no longer moves the meter. Nothing
    tells a player they have got there - the curve tails off rather
    than stopping - so this is for the ones who kept going anyway.

    **Lifetime rather than daily.** Two in one afternoon and two a
    fortnight apart are the same gesture, and a daily counter would
    make the second one depend on which the player happened to be.

    "Two or more and not held", like the other thresholds, so that a
    play which races or lands while the bot is down costs a day rather
    than the award.
    """
    if not context.extra.get("played"):
        return False
    plays = await database.free_toy_plays(context.guild_id, context.user_id)
    return plays >= PURRSISTENT_PLAYS


async def making_first_contact(context: Context) -> bool:
    """The first pet that rolls friendly, and the spine of drop 0.

    "First" needs no state: the award is idempotent, so this can be true
    of every friendly pet for the rest of October and still land once.

    Reads the roll rather than the score, because the score is the same
    either way on a brand-new player - they start at nothing, and what
    makes this a moment is that the cat let them.
    """
    return bool(context.extra.get("friendly"))


async def a_paw_in_the_door(context: Context) -> bool:
    """Fifty, and the first quest in the game."""
    return await _score(context) >= PAW_IN_THE_DOOR


async def cats_best_friend(context: Context) -> bool:
    """A hundred: as fond of you as the game has a name for."""
    return await _score(context) >= PERFECT_RELATIONSHIP


async def favorite_human(context: Context) -> bool:
    """Two hundred and fifty, which the meter has no ceiling for a reason."""
    return await _score(context) >= FAVORITE_HUMAN


async def are_you_david(context: Context) -> bool:
    """A thousand, and deliberately `>=` rather than a crossing.

    Drop 20 opens on servers where players are already past it - the
    beta's leaders were over a thousand before the achievement existed -
    and a trigger that watched for the moment the score *passed* a
    thousand would never fire for any of them. The standing condition
    lands on their next pet, toy, bed or feed instead.

    A plank is not a cat interaction and pays no relationship, so the
    staircase cannot award this however long somebody hammers.
    """
    return await _score(context) >= ARE_YOU_DAVID


async def passing_a_message_to_david(context: Context) -> bool:
    """Asking Alexa to remind David about the auto-delivery.

    The same test the handler used to choose her reply, so the achievement and
    the answer cannot disagree about what counts.
    """
    said = context.extra.get("content") or ""
    return alexa.is_addressed(said) and alexa.is_message_for_david(said)


async def met_the_craving(context: Context) -> bool:
    """The reaction matched the day's craving emoji.

    Any win, not only a scoring one. A player who already took their five
    points today and clicks the answer again has still met the craving, and
    the award is a one-off that cannot fire twice anyway.
    """
    guess = context.extra.get("guess")
    return guess is not None and guess.won


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

    # Awarded by hand, to the playtesters who went at a dirty diaper
    # the parser would not admit existed. On the widest hook there is,
    # because that is where their `/look`, `/take` and `/use` went -
    # though it never fires, which is the point.
    add("bug_catcher", "on_command", _by_hand("awarded by hand, never by play"))

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

    # The two October holidays. `lucky_black_cat` listens on both ways
    # to reach her - `on_pet` for petting, `on_use` for the bed, the toy
    # and the cans. `familiar` listens on the hook that fires for every
    # command there is, which is the only hook it could use.
    add("lucky_black_cat", ("on_pet", "on_use"), lucky_black_cat)
    add("familiar", "on_command", familiar)

    # Drop 0 and drop 1: the proof of concept's own four.
    add("making_first_contact", "on_pet", making_first_contact)
    add("fluffed_to_perfection", "on_use", _used(CAT_BED))
    add("tireless", "on_use", tireless)
    # Drop 2 and drop 3. Final copy, no content yet - registered for the
    # same reason the letter and the doorbell are, so that building the
    # toy is a registration change rather than a reopened phase.
    add("persuasive", "on_use", persuasive)
    add("impressively_bad_luck", "on_use", impressively_bad_luck)
    add("purrsistent", "on_use", purrsistent)
    # Drop 10: feeding, and the pair that counts it. The first feed and
    # the twenty-fifth, which the copy deck writes as a deliberate pair.
    add("room_service", "on_use", room_service)
    add("bowl_half_empty", "on_use", bowl_half_empty)

    # Secret
    add("a_little_bit_lost", "on_move", a_little_bit_lost)
    add("out_on_a_limb", "on_move", out_on_a_limb)
    add("bulk_buyer", "on_take", bulk_buyer)
    add("making_friends", "on_pet", making_friends)
    add("trying_to_make_friends", "on_pet", trying_to_make_friends)
    # The three thresholds, all on the hook that fires wherever the score
    # moves rather than on `on_pet`. Reaching 50 by fluffing the bed is
    # the case that proves the difference.
    add("a_paw_in_the_door", "on_relationship_change", a_paw_in_the_door)
    add("cats_best_friend", "on_relationship_change", cats_best_friend)
    add("favorite_human", "on_relationship_change", favorite_human)
    add("are_you_david", "on_relationship_change", are_you_david)
    add("signed_sealed_delivered", "on_use", _blocked("the doorbell"))
    add("brewing_trouble", "on_use", _on_thing({KEURIG}))
    # The trash can holds things now, so this is a predicate rather than
    # a promise. It was blocked for two releases: parked at drop 99 and
    # gated on a day it could never match, then honestly blocked on 30
    # October when the date came off.
    add("trash_panda", "on_take", trash_panda)
    # No longer World Smile Day. Any mirror, any day, any year - the one
    # of the six undated ones whose room is already open.
    add("self_reflection", "on_use", _on_thing(MIRRORS))
    # The one that shapes the signature: three parts across two hooks.
    add("green_thumb", ("on_use", "on_take"), green_thumb)
    add("nacho_average_ghost", "on_use", _on_thing({NACHO_CHIPS}))
    add("using_your_noodle", "on_use", _on_thing({PASTA_POT}))
    add("getting_into_the_spirit", "on_use", _blocked("the ghost system"))
    add("ghostbuster", "on_use", _blocked("the ghost system"))
    add("breaking_into_the_halloween_candy", "on_use", _used(CANDY))
    # **`on_take`, not `on_use`.** `/use trash can` opens the menu for
    # throwing something away; taking the trash out is `/take trash
    # can`, which is what "took the trash out on a Tuesday" has always
    # meant. The trigger moved with the mechanic.
    add("curbside_pickup", "on_take", _on_date(on_tuesday, {TRASH_CAN}))
    add("not_so_picky_eater", "on_use", not_so_picky_eater)
    # The last of the three that moved to drop 30 ahead of their
    # mechanics. It was never registered at all before that - `NEVER`
    # buys a row the right to be unwired, and this one sat at 99 for
    # exactly that reason - then blocked for two releases, and now the
    # staircase can be finished and the award has a shape.
    add("board_meeting", "on_use", board_meeting)
    add("hive_five", "on_use", hive_five)
    add("bin_looking_for_you", "on_look", bin_looking_for_you)
