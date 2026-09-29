"""Turning a thing and a verb into the line a player reads.

Three steps, in this order: the thing's own text for its current state, then the
house default for that verb, then nothing. A blank cell in the content files is
not an error - it is the writer saying "the ordinary line is fine here", which
is why most things have no `take` text and only 22 of 142 rows fill it.

Tokens are filled last. Unknown tokens are left alone rather than raising: a
writer's typo should show up in the reply as `{nmae}` for someone to notice and
fix, not take the command down.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from sqlalchemy import select

import database
from typing import Sequence

import resolve

log = logging.getLogger(__name__)

_TOKEN = re.compile(r"\{(\w+)\}")


def fill(template: str | None, **tokens) -> str:
    """Substitute {name}, {n}, {time} and the rest. Unknown tokens stay put."""
    if not template:
        return ""

    def swap(match: re.Match) -> str:
        key = match.group(1)
        if key in tokens and tokens[key] is not None:
            return str(tokens[key])
        return match.group(0)

    return _TOKEN.sub(swap, template)


def approximate_duration(remaining: timedelta) -> str:
    """A rough, readable remaining time for {time}.

    Deliberately vague. "about 18 hours" is what a person would say, and a
    precise countdown invites players to sit and watch it.
    """
    seconds = max(0, int(remaining.total_seconds()))
    if seconds < 90:
        return "a minute"
    minutes = seconds // 60
    if minutes < 60:
        return f"about {minutes} minutes"
    hours = round(minutes / 60)
    if hours < 24:
        return f"about {hours} hour{'s' if hours != 1 else ''}"
    days = round(hours / 24)
    return f"about {days} day{'s' if days != 1 else ''}"


async def thing_row(thing_id: str):
    """The content row for a thing: its flags, its type, what it yields."""
    session_factory = database._require_session()
    async with session_factory() as session:
        return (
            await session.execute(
                select(database.ThingType).where(database.ThingType.thing_id == thing_id)
            )
        ).scalar_one_or_none()


async def say(
    guild_id: int,
    thing_id: str,
    column: str,
    *,
    fallback: str | None = None,
    state: "str | Sequence[str]" = resolve.DEFAULT_STATE,
    **tokens,
) -> str:
    """The thing's own text for this verb, or the house default, filled in.

    `fallback` is a key in defaults.tsv. Returning an empty string when neither
    exists is deliberate: the caller decides whether silence is acceptable, and
    for most verbs it is not.
    """
    written = await resolve.thing_text(guild_id, thing_id, column, state)
    if not written and fallback:
        written = await resolve.default_text(fallback)
    return fill(written, **tokens)


async def default_say(key: str, **tokens) -> str:
    """A house string by key, filled in."""
    return fill(await resolve.default_text(key), **tokens)


# --------------------------------------------------------------------------
# Listings
# --------------------------------------------------------------------------

# Discord refuses a message over 2,000 characters. Ten scattered objects a day
# and nothing removing them until somebody takes one means a busy room reaches
# that inside a fortnight, so the listing is cut rather than the send failing.
MESSAGE_LIMIT = 2000


async def listing(
    entries: list[tuple[str, int]], *, prefix_key: str, budget: int = MESSAGE_LIMIT
) -> str:
    """Render "Also here: nacho chips, herbs x10" from (name, count) pairs.

    Empty in, empty out: a room with nothing loose gets no line at all rather
    than a line saying so. Four of the nine rooms are in that state at launch,
    which is correct - everything portable there is tucked inside something.

    Over budget, the listing is cut and the count of what was dropped is
    appended. Truncating is not a precaution for later: it ships with the
    scheduler that causes it.
    """
    if not entries:
        return ""

    prefix = await resolve.default_text(prefix_key) or ""
    separator = await resolve.default_text("also_here.separator") or ", "
    multiple = await resolve.default_text("also_here.entry_multiple") or "{name} x{n}"

    rendered = [
        fill(multiple, name=name, n=count) if count > 1 else name
        for name, count in entries
    ]

    kept: list[str] = []
    length = len(prefix)
    for index, entry in enumerate(rendered):
        addition = len(entry) + (len(separator) if kept else 0)
        # Leave room for the truncation clause, which is only needed if
        # something is actually left out.
        remaining = len(rendered) - index
        reserve = 0 if remaining == 1 else 60
        if length + addition + reserve > budget:
            break
        kept.append(entry)
        length += addition

    if len(kept) == len(rendered):
        return prefix + separator.join(kept)

    dropped = len(rendered) - len(kept)
    tail = await default_say("also_here.truncated", more=dropped)
    return prefix + separator.join(kept) + separator + tail
