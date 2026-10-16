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
import resolve

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
    """One nudge: the string it renders, and what makes it unnecessary.

    `recommends` is the action the hint tells the player to take. When
    they take it the hint is retired whether or not they ever saw it,
    which is what stops the rail advising somebody to do a thing they
    did yesterday.
    """

    hint_id: str
    recommends: str | None = None


FIRST_FRIENDLY = Hint("hint.first_friendly")
FIRST_STANDOFFISH = Hint("hint.first_standoffish")
SOMETHING_NEW = Hint("hint.something_new", recommends=DID_LOOK)
LOOK_SPECIFIC = Hint("hint.look_specific", recommends=DID_LOOK_BED)
TRY_USE = Hint("hint.try_use", recommends=DID_USE_BED)
TRY_LOOK = Hint("hint.try_look", recommends=DID_LOOK_BED)

ALL = (FIRST_FRIENDLY, FIRST_STANDOFFISH, SOMETHING_NEW, LOOK_SPECIFIC, TRY_USE, TRY_LOOK)

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


async def pick(guild_id: int, user_id: int, *candidates: Hint) -> str | None:
    """The one hint to append to this message, or None to stay quiet.

    Candidates are offered in priority order and the first eligible one
    wins. Choosing it records it, so the same hint never arrives twice,
    and the ones passed over are left untouched - a hint that lost to a
    better one this time is still waiting next time.
    """
    for hint in candidates:
        if hint.recommends and await database.has_been_told(
            guild_id, user_id, hint.recommends
        ):
            continue
        if not await database.notice(guild_id, user_id, hint.hint_id):
            continue
        return await render(hint.hint_id)
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
    graduated = len(told) >= GRADUATES_AT and await database.has_been_told(
        guild_id, user_id, OPENED_STATS
    )
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


async def after(
    guild_id: int, user_id: int, *candidates: Hint, quests: bool = True
) -> str | None:
    """The whole rail for one message: a hint, or a quest notice, or
    nothing.

    Hints come first. The two that fire on a first pet already say to
    check `/stats` for open quests, so a quest notice behind one of them
    would be the same sentence twice in a row.
    """
    try:
        line = await pick(guild_id, user_id, *candidates)
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
