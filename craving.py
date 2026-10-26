"""The cat's craving of the day.

One food emoji a day, the same for everyone on a server, guessed by reacting
to anything the bot has posted. The bot answers with reactions of its own:
👀 for the right type, 😻 when somebody finds it, and ❌ when the message
has run out of room.

Two design points are load-bearing and easy to undo by accident.

**One craving per server, not per player.** The whole point is that players can
tell each other. Everything that looks like an anti-copying measure - a cutoff,
a first-finder-only rule - would work against that, and the spec says so
explicitly. The tally measures showing up, not solving.

**A player scores a day once.** Not once per message, not once per reaction.
Removing and re-adding 🍇 does not score twice, and neither does reacting on a
second bot message the same day.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

import content as content_module
import database

log = logging.getLogger(__name__)

# What the bot reacts with.
RIGHT_GROUP = "\N{EYES}"
FOUND = "\N{SMILING CAT FACE WITH HEART-SHAPED EYES}"
NO_ROOM = "\N{CROSS MARK}"

# Discord merges identical emoji into one reaction with a count, and caps a
# message at 20 distinct ones. The bot needs a slot left to answer in, so the
# 20th is spent saying "no more guesses here" rather than on another guess.
MAX_REACTIONS = 20


class Verdict(str):
    """What a guess earned. A str subclass so it logs and compares readably."""


CORRECT = Verdict("correct")
SAME_GROUP = Verdict("same_group")
WRONG = Verdict("wrong")
NOT_FOOD = Verdict("not_food")


@dataclass(frozen=True)
class Guess:
    verdict: Verdict
    craving: str
    credited: bool = False
    first: bool = False


def normalise(emoji: str) -> str:
    """Strip the variation selector, as the content loader does on the way in.

    Discord hands back some emoji with U+FE0F and some without. Normalising
    both sides once, in the same way, is what stops a single emoji silently
    never matching.
    """
    return content_module.normalise_emoji(emoji)


async def _pool() -> list[tuple[str, str]]:
    """(emoji, type) for everything that can be the craving."""
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(database.EmojiGroup.emoji, database.EmojiGroup.type).where(
                database.EmojiGroup.drawable.is_(True)
            )
        )
        return [(row[0], row[1]) for row in rows]


# The categories that are in the file but not in the game. A guess filed
# under one of these is the friendly nothing - the same answer an emoji
# the file has never heard of gets, because to a player there is no
# difference between the two and there should not be.
#
# `Bot` is in here because those six are the bot's own replies. Judging
# one would let a player walk the ladder backwards off the answers.
NON_GAME_CATEGORIES = frozenset({"Misc", "Cat", "Bot"})


async def category_of(emoji: str) -> str | None:
    """Which game category an emoji is filed under, or None if the file
    has never heard of it.

    **The file now holds every emoji, not just the edible ones**, which
    changed what "not in the file" means. A car used to be absent and so
    read as unrelated by default; it is a `Misc` row now, and without
    this it would score as a wrong guess at food instead.
    """
    session_factory = database._require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(database.EmojiGroup.category).where(
                database.EmojiGroup.emoji == normalise(emoji)
            )
        )


async def type_of(emoji: str) -> str | None:
    """Which game type an emoji belongs to, or None if the file has never
    heard of it.

    A plate answers here even though it can never be the craving, which is
    what lets it be a legal guess that simply never matches.

    **This was the Unicode subgroup until the catalogue arrived**, and the
    rename is not cosmetic: the old grouping decided the game by accident,
    putting dishware inside Food & Drink. The writers' type is the thing the
    ladder is meant to compare.
    """
    session_factory = database._require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(database.EmojiGroup.type).where(
                database.EmojiGroup.emoji == normalise(emoji)
            )
        )


async def craving_for(guild_id: int, day: date | None = None, *, rng=random) -> str | None:
    """The craving for one server on one day, drawn once and then remembered.

    Drawn on first use rather than on a schedule, so a server that nobody
    touches costs nothing and a server that wakes at noon still gets a day.
    """
    day = day or await database.server_today(guild_id)
    session_factory = database._require_session()
    insert = database._upsert_statement()

    async with session_factory() as session:
        existing = await session.scalar(
            select(database.CravingDay.emoji).where(
                database.CravingDay.guild_id == guild_id,
                database.CravingDay.day == day,
            )
        )
        if existing:
            return existing

    pool = await _pool()
    if not pool:
        log.warning("No drawable emoji loaded; the craving cannot be drawn")
        return None

    chosen = rng.choice(pool)[0]
    async with session_factory() as session:
        # ON CONFLICT DO NOTHING, then read back: two reactions arriving in the
        # same instant must not end up with two different cravings for one day.
        await session.execute(
            insert(database.CravingDay)
            .values(guild_id=guild_id, day=day, emoji=chosen)
            .on_conflict_do_nothing(
                index_elements=[database.CravingDay.guild_id, database.CravingDay.day]
            )
        )
        await session.commit()
        settled = await session.scalar(
            select(database.CravingDay.emoji).where(
                database.CravingDay.guild_id == guild_id,
                database.CravingDay.day == day,
            )
        )
    return settled


async def already_found(guild_id: int, day: date | None = None) -> bool:
    day = day or await database.server_today(guild_id)
    session_factory = database._require_session()
    async with session_factory() as session:
        return (
            await session.scalar(
                select(database.CravingDay.found_by).where(
                    database.CravingDay.guild_id == guild_id,
                    database.CravingDay.day == day,
                )
            )
        ) is not None


async def _mark_found(guild_id: int, user_id: int, day: date) -> bool:
    """Record who got there first. False if somebody already had."""
    session_factory = database._require_session()
    async with session_factory() as session:
        from sqlalchemy import update

        result = await session.execute(
            update(database.CravingDay)
            .where(
                database.CravingDay.guild_id == guild_id,
                database.CravingDay.day == day,
                database.CravingDay.found_by.is_(None),
            )
            .values(found_by=user_id, found_at=await database.server_now(guild_id))
        )
        await session.commit()
        return bool(result.rowcount)


async def credit(guild_id: int, user_id: int, day: date) -> bool:
    """Score this player for this day. False if they already had it.

    The comparison is on the day rather than a flag, so removing a reaction and
    adding it again, or reacting on a second bot message, both fall through.
    """
    session_factory = database._require_session()
    insert = database._upsert_statement()

    async with session_factory() as session:
        last = await session.scalar(
            select(database.CravingTally.last_credited_day).where(
                database.CravingTally.guild_id == guild_id,
                database.CravingTally.user_id == user_id,
            )
        )
        if last == day:
            return False

        await session.execute(
            insert(database.CravingTally)
            .values(guild_id=guild_id, user_id=user_id, days=1, last_credited_day=day)
            .on_conflict_do_update(
                index_elements=[
                    database.CravingTally.guild_id,
                    database.CravingTally.user_id,
                ],
                set_={
                    "days": database.CravingTally.days + 1,
                    "last_credited_day": day,
                },
            )
        )
        await session.commit()
    return True


async def tally(guild_id: int, user_id: int) -> int:
    """How many distinct days this player has found the craving on."""
    session_factory = database._require_session()
    async with session_factory() as session:
        return (
            await session.scalar(
                select(database.CravingTally.days).where(
                    database.CravingTally.guild_id == guild_id,
                    database.CravingTally.user_id == user_id,
                )
            )
        ) or 0


async def judge(
    guild_id: int, user_id: int, emoji: str, day: date | None = None
) -> Guess:
    """Score one guess, and credit the player if it was right.

    A correct guess always credits, whether the player was first or twentieth.
    Once the 😻 is up the answer is visible to anyone who looks, so a late
    reaction is copying rather than solving - and that is not a gap to close.
    The tally measures taking part.
    """
    day = day or await database.server_today(guild_id)
    craving = await craving_for(guild_id, day)
    if craving is None:
        return Guess(verdict=WRONG, craving="")

    guessed = normalise(emoji)
    if guessed == craving:
        first = await _mark_found(guild_id, user_id, day)
        scored = await credit(guild_id, user_id, day)
        return Guess(verdict=CORRECT, craving=craving, credited=scored, first=first)

    category = await category_of(guessed)
    if category is None or category in NON_GAME_CATEGORIES:
        return Guess(verdict=NOT_FOOD, craving=craving)

    theirs = await type_of(guessed)
    if theirs is None:
        return Guess(verdict=NOT_FOOD, craving=craving)

    ours = await type_of(craving)
    if theirs == ours:
        return Guess(verdict=SAME_GROUP, craving=craving)
    return Guess(verdict=WRONG, craving=craving)
