"""One rail for every nudge the game gives.

Quest notices and tutorial hints are the same shape - a line appended to
a message the player was getting anyway - so they share one store and one
dispatcher rather than growing two of each.

**The invariant that covers every precondition: never recommend an action
the player has already taken.** Write it once here and the per-hint
conditions come for free, including one the copy deck does not state: a
player whose first `/look` is `/look cat bed` would otherwise be told to
try `/look cat bed`.

It works because an action is recorded *before* the hints are considered,
and because a hint is retired two ways that are written down the same
way - by being shown, and by being made moot. Both are a row in
`player_notices`, so nothing can resurface as advice to do something
already done.

**At most one line per message.** One action can satisfy several
triggers, and two hints stacked under one reply read as a tutorial
rather than a nudge.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import database
import gating
import resolve
import telemetry

log = logging.getLogger(__name__)

# How a hint renders. The label is not part of the writer's string, so
# the strings stay readable in `defaults.tsv` and the styling is in one
# place when somebody wants it changed.
LAYOUT = "*Hint: {text}*"

# What a player has done, recorded so a hint can be made moot by it.
# Looking and using are not otherwise written down anywhere - a look
# leaves no trace in the database at all - so the rail keeps its own
# record rather than inferring one from `thing_uses`.
DID_LOOK = "did.look"
DID_LOOK_BED = "did.look_cat_bed"
DID_USE_BED = "did.use_cat_bed"

# Drop 2's actions count **the verb, not the verb and a noun**. Two toys
# draw against the same two channel slots, so a player who looked at a
# crinkle ball has learned what looking at a toy is and must not be told
# to look at a feather wand. Recording `did.look_toy` rather than
# `did.look_feather_wand` is what makes that true for free.
DID_LOOK_TOY = "did.look_toy"
DID_TAKE_TOY = "did.take_toy"
DID_USE_TOY = "did.use_toy"

# Carrying, which drop 2 also teaches. Both are the verb alone for the
# same reason the toy markers are: a player who has opened their bag
# once knows what `/inventory` is, whatever was in it.
DID_INVENTORY = "did.inventory"
DID_DROP = "did.drop"

# Drop 10's two actions, in and out. Recorded so neither hint is ever
# given to somebody who has already done what it recommends - the
# module's one invariant, which is the only reason these markers exist.
# Reading the house's own description, which is one of the three ways a
# player comes to know the house is there. Not a hint's `recommends` -
# nothing ever tells anybody to look at the house - but the same table
# and the same shape, because it answers the same kind of question.
DID_LOOK_HOUSE = "did.look_house"
# Trying the front door and finding it locked. A third way of knowing
# the house is there, and the most certain of them: nobody types `/go
# house` at a road that has never mentioned one by accident.
DID_TRY_HOUSE = "did.try_house"
DID_GO_HOUSE = "did.go_house"
DID_GO_ROAD = "did.go_road"

# The flag `/stats` sets, half of the condition that graduates the quest
# notice from pointing at `/stats` to naming the quest inline.
OPENED_STATS = "opened_stats"

# How many quests a player must have been offered before the notice
# starts naming them. **Not reachable in Phase 3a** - only two public
# quests exist before drop 2 - so the graduated string ships unexercised
# by design rather than by accident.
GRADUATES_AT = 3


@dataclass(frozen=True)
class Hint:
    """One nudge: what it says, and everything that makes it wrong.

    `recommends` is the action the hint tells the player to take. When
    they take it the hint is retired whether or not they ever saw it,
    which is what stops the rail advising somebody to do a thing they
    did yesterday.

    `needs_commands` and `needs_thing` are the other half, and they
    exist because the first version of this did not have them: a tester
    on drop 0 was told *"There is something new here. Try /look"* when
    there was nothing new and `/look` was not in their slash menu.

    **A hint that names a command or a thing declares it here**, and the
    rail checks both against the same gates the game itself uses - the
    command tables in `gating`, and whether the thing's drop has
    arrived. Writing the drop number on the hint instead would have
    duplicated knowledge `gating` already owns, and gone stale the first
    time a drop moved.
    """

    hint_id: str
    recommends: str | None = None
    needs_commands: tuple[str, ...] = ()
    needs_thing: str | None = None
    # A hint about toys cannot name one: the two draw against the same
    # two channel slots, so a hint naming a wand can point at a ball.
    # This asks instead for *a* takeable toy to exist here, and the
    # text's `{name}` is filled from whichever one is present.
    needs_a_toy: bool = False


CAT_BED = "cat_bed"
TOY = "toy"
# The two exits drop 10 adds, by the ids `things.tsv` gives them.
# Literals here like the two above rather than `world.HOUSE`, because this
# module sits under the game rules rather than beside them.
HOUSE = "house"
FRONT_DOOR = "front_door"

FIRST_FRIENDLY = Hint("hint.first_friendly", needs_commands=("stats",))
FIRST_STANDOFFISH = Hint("hint.first_standoffish", needs_commands=("stats",))
SOMETHING_NEW = Hint(
    "hint.something_new",
    recommends=DID_LOOK,
    needs_commands=("look",),
    # The something that is new *is* the bed. Without this the hint
    # fires the moment `/look` exists, which on a server QA has moved
    # by hand need not be the moment there is anything to look at.
    needs_thing=CAT_BED,
)
LOOK_SPECIFIC = Hint(
    "hint.look_specific",
    recommends=DID_LOOK_BED,
    needs_commands=("look",),
    needs_thing=CAT_BED,
)
TRY_USE = Hint(
    "hint.try_use",
    recommends=DID_USE_BED,
    needs_commands=("use",),
    needs_thing=CAT_BED,
)
TRY_LOOK = Hint(
    "hint.try_look",
    recommends=DID_LOOK_BED,
    needs_commands=("look",),
    needs_thing=CAT_BED,
)

# Drop 2. Four rungs that teach looking, taking and using on a toy, and
# one that fires on being told to pick it up first.
#
# **None of them names a toy**, for the reason in `needs_a_toy`. Their
# order in `ALL` is not the ladder - the ladder is each rung's
# `recommends` being the next one's precondition, so a player who skips
# ahead is never told to do something they have already done.
LOOK_TOY = Hint(
    "hint.look_toy",
    recommends=DID_LOOK_TOY,
    needs_commands=("look",),
    needs_a_toy=True,
)
TAKE_TOY = Hint(
    "hint.take_toy",
    recommends=DID_TAKE_TOY,
    needs_commands=("take",),
    needs_a_toy=True,
)
USE_TOY = Hint(
    "hint.use_toy",
    recommends=DID_USE_TOY,
    needs_commands=("use",),
    needs_a_toy=True,
)
# **No `needs_a_toy`, unlike the rungs above it.** Those fire on a look
# around and have to ask for a toy to exist, because they have nothing else
# to name. This one fires on a refusal, so the caller already knows which
# thing was turned away and passes its name in. Asking for a toy as well
# would gate a lesson about a can of cat food on whether a feather wand
# happened to be lying in the channel - and until the name was passed in,
# that wand is what the hint named.
HOLD_TO_USE = Hint(
    "hint.hold_to_use",
    needs_commands=("take",),
)
# Fires on the fluff that dislodges something, so it needs no toy in the
# channel to be true - the fluff has just put one there.
BED_YIELD = Hint("hint.bed_yield", recommends=DID_LOOK, needs_commands=("look",))

# The two carrying rungs. Neither needs a toy in the channel: the first
# fires on a toy the player is already holding, and the second names
# whatever is in their bag.
CHECK_INVENTORY = Hint(
    "hint.check_inventory",
    recommends=DID_INVENTORY,
    needs_commands=("inventory",),
)
# `{name}` is the first thing in their bag, passed in by the caller.
# Naming something they are holding is the point: "like /drop feather
# wand" is a command they can retype, where "/drop <thing>" is a syntax
# lesson.
DROP_SOMETHING = Hint(
    "hint.drop_something",
    recommends=DID_DROP,
    needs_commands=("drop",),
)

# Drop 10. **The rail is how the way in is taught**, now that `#welcome`
# is retired - it told every new player to run `/enter`, and there is no
# `/enter`.
#
# The two gates it declares are the drop, twice over and in the module's
# own terms: `/go` is drop 10's command and the house is drop 10's thing,
# so neither a server that is early nor a QA server moved by hand can be
# told to walk through a door that is not there.
#
# The condition the rail cannot express - *Fluffed to Perfection* - is the
# caller's, in `/look`. It is the bed, which means the player has met the
# cat and done something for her; before that they are still on drop 1's
# lesson and a second place to go is one thing too many.
GO_HOUSE = Hint(
    "hint.go_house",
    recommends=DID_GO_HOUSE,
    needs_commands=("go",),
    needs_thing=HOUSE,
)

# **The way back out, and the rung the retired tutorial was carrying.**
# Its third bullet was the only lesson the rail could not give before drop
# 10 - there was no exit anywhere to teach movement on - and it named the
# wide doorway, which does not arrive until drop 30.
#
# It matters more than it looks. The bed and the toys stay in the channel,
# so a player who cannot find the way out loses the daily fluff, which is
# the whole relationship engine at this drop.
#
# It rides the private line that says they are inside, because that is the
# message a player who has just walked in was getting anyway.
GO_ROAD = Hint(
    "hint.go_road",
    recommends=DID_GO_ROAD,
    needs_commands=("go",),
    needs_thing=FRONT_DOOR,
)

ALL = (
    FIRST_FRIENDLY,
    FIRST_STANDOFFISH,
    SOMETHING_NEW,
    LOOK_SPECIFIC,
    TRY_USE,
    TRY_LOOK,
    LOOK_TOY,
    TAKE_TOY,
    USE_TOY,
    HOLD_TO_USE,
    BED_YIELD,
    CHECK_INVENTORY,
    DROP_SOMETHING,
    GO_HOUSE,
    GO_ROAD,
)

# Which hints a given action can make unnecessary, worked out once.
_RETIRED_BY: dict[str, tuple[str, ...]] = {
    action: tuple(h.hint_id for h in ALL if h.recommends == action)
    for action in {h.recommends for h in ALL if h.recommends}
}


async def did(guild_id: int, user_id: int, action: str) -> None:
    """Record an action, and retire anything that would recommend it.

    Called before the hints for that message are considered, which is
    what makes the invariant hold without a condition per hint: by the
    time anything is chosen, what the player just did is already a
    reason not to suggest it.
    """
    await database.notice(guild_id, user_id, action)
    for hint_id in _RETIRED_BY.get(action, ()):
        await database.notice(guild_id, user_id, hint_id)


async def reachable(guild_id: int, hint: Hint) -> bool:
    """Whether this hint's advice is possible on this server yet.

    Asked of the same gates the game uses rather than of a drop number
    written on the hint: the command tables decide what a player can
    type, and `since_drop` decides what exists. A hint pointing past
    either is not early, it is wrong.
    """
    if hint.needs_commands:
        drop = await resolve.current_drop(guild_id)
        if not set(hint.needs_commands) <= gating.player_commands_for(drop):
            return False
    if hint.needs_thing:
        if hint.needs_thing not in await resolve.visible_thing_ids(guild_id):
            return False
    if hint.needs_a_toy and await a_takeable_toy(guild_id) is None:
        return False
    return True


async def a_takeable_toy(guild_id: int) -> str | None:
    """The name of a takeable toy in the channel, or None if there is none.

    **Takeable only.** These rungs teach looking, taking and using on
    something you pick up, and the Amazon box is a fixture: offering it
    as the subject of *Try /take* would refuse with `take_fail.fixture`,
    and looking at it must not count as having learnt the lesson.

    Resolved when the hint fires rather than when the drop opens,
    because which toy is in the channel changes as players take them.
    """
    import content as content_module

    present = await database.present_of_type(
        guild_id, content_module.CHANNEL_ROOM, TOY
    )
    return present[0] if present else None


async def pick(
    guild_id: int, user_id: int, *candidates: Hint, name: str | None = None
) -> str | None:
    """The one hint to append to this message, or None to stay quiet.

    Candidates are offered in priority order and the first eligible one
    wins. Choosing it records it, so the same hint never arrives twice,
    and the ones passed over are left untouched - a hint that lost to a
    better one this time is still waiting next time.

    A hint that is not reachable yet is passed over **without being
    recorded**, which is the difference between "not yet" and "already
    said": it has to still be waiting when its drop opens.
    """
    for hint in candidates:
        if hint.recommends and await database.has_been_told(
            guild_id, user_id, hint.recommends
        ):
            continue
        if not await reachable(guild_id, hint):
            continue
        tokens = {}
        if name:
            # Whatever the caller is talking about: the toy just picked
            # up, or the first thing in the bag. It wins over the
            # lookup below, which cannot know either.
            tokens["name"] = name
        elif hint.needs_a_toy:
            # Filled now rather than at the drop: the rungs that teach
            # looking and taking name whichever toy is in the channel.
            tokens["name"] = await a_takeable_toy(guild_id) or "toy"
        if not await database.notice(guild_id, user_id, hint.hint_id):
            continue
        # **Which rung fired, in the log.** The rail is a bet about
        # discoverability that it cannot settle on its own: a player
        # who reads the bed's description and does nothing might have
        # missed the prose or might have missed the verb, and those
        # want opposite fixes. A hint row before an action says the
        # rail carried them; an action with no hint before it says the
        # prose did its job.
        await telemetry.record(
            guild_id,
            action=telemetry.HINT,
            user_id=user_id,
            outcome=telemetry.SUCCESS,
            detail=hint.hint_id,
        )
        return await render(hint.hint_id, **tokens)
    return None


async def render(hint_id: str, **tokens) -> str | None:
    """A hint's own words, wrapped in the label and the italics."""
    import phrasing

    text = await phrasing.default_say(hint_id, **tokens)
    return LAYOUT.format(text=text) if text else None


async def quest_notice(guild_id: int, user_id: int) -> str | None:
    """Tell this player a quest has opened, if one has since last time.

    **Computed rather than tracked.** Work out what is visible now,
    compare against what they have been told, and the difference is the
    news. That covers the achievement case and the overnight
    drop-advance case in one path, and reuses the visibility helper
    `/stats` needs anyway - there is no event to subscribe to and
    nothing to keep in step.

    It graduates. Until the player has been offered `GRADUATES_AT`
    quests **and** opened `/stats` at least once it points them there;
    after that it names the quest, because by then they know what the
    screen is and the round trip is the annoying part.
    """
    quests = await resolve.open_quests(guild_id, user_id)
    if not quests:
        return None

    told = await database.notice_order(guild_id, user_id)
    fresh = [row for row in quests if row.achievement_id not in told]
    if not fresh:
        return None

    newest = fresh[0]
    graduated = await _graduated(guild_id, user_id, told)
    line = (
        await render(
            "hint.new_quest.named",
            quest_name=newest.name,
            quest_prompt=newest.prompt or "",
        )
        if graduated
        else await render("hint.new_quest")
    )

    for row in fresh:
        await database.notice(guild_id, user_id, row.achievement_id)
    return line


async def _graduated(guild_id: int, user_id: int, told: dict[str, int]) -> bool:
    """Whether this player has seen enough quests to be named one.

    **Counts quests, not notices.** The told-you table holds hints,
    action markers and flags as well as quests, so `len(told)` reached
    three the moment a player had looked at the bed and opened
    `/stats` - and a tester on their first quest was handed "Fluffed to
    Perfection: Give the cat a cozy nap spot" instead of being pointed
    at the screen that would explain it.

    A quest is an achievement the files offer, so the count is the told
    ids that are offered achievements and nothing else.
    """
    offered = {
        row.achievement_id
        for row in (await resolve.achievements(guild_id)).values()
        if row.offered
    }
    attained = len(set(told) & offered)
    return attained >= GRADUATES_AT and await database.has_been_told(
        guild_id, user_id, OPENED_STATS
    )


async def after(
    guild_id: int,
    user_id: int,
    *candidates: Hint,
    quests: bool = True,
    name: str | None = None,
) -> str | None:
    """The whole rail for one message: a hint, or a quest notice, or
    nothing.

    Hints come first. The two that fire on a first pet already say to
    check `/stats` for open quests, so a quest notice behind one of them
    would be the same sentence twice in a row.
    """
    try:
        line = await pick(guild_id, user_id, *candidates, name=name)
        if line is None and quests:
            line = await quest_notice(guild_id, user_id)
        return line
    except Exception:
        # Decoration on a message the player was getting anyway. A rail
        # that fails must cost a nudge, never the reply it rides on.
        log.exception("Hint rail failed for %s in guild %s", user_id, guild_id)
        return None


def beneath(message: str, line: str | None) -> str:
    """Put a hint under a message, or leave the message alone."""
    return f"{message}\n\n{line}" if line else message
