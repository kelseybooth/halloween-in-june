"""The cat's craving of the day.

Every day the cat wants one food or one prey animal, the same for everyone on
a server. Players guess by reacting with an emoji on anything the bot has
posted, and the bot answers with a cat face that says how close they were.
Nothing announces the game. The first clue is a 🐱 coming back at a heart on
somebody's achievement.

Four design points are load-bearing and easy to undo by accident.

**One craving per server, not per player.** The whole point is that players
can tell each other. Everything that looks like an anti-copying measure - a
cutoff, a first-finder-only rule - works against that. The 5 points are small
*because* copying is easy, not in spite of it.

**The answer is a function of the emoji and the day, and of nothing else.** A
player who already scored still gets 😻 for clicking the answer again. Making
the display depend on who is looking would mean the same message showing
different things to different people, which Discord cannot do anyway.

**A player scores a day once.** Not once per message, not once per reaction.
Removing and re-adding 🥦 does not score twice, and neither does reacting on a
second bot message the same day.

**The bot's reactions describe the message, not the guess.** Discord allows
each emoji once per message, so a message carries its best answer so far and
a guess only changes it by beating that rank. Which means the message's
outcome is state, and it is kept per day: a 😻 left overnight would point at
yesterday's answer.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select, update

import content as content_module
import database
import resolve
import world

log = logging.getLogger(__name__)

# The five rungs, worst to best, and the two things that are not rungs.
# Unpacked from the content module rather than written out again, because
# these strings are the join between the game and `craving_reactions.tsv`
# and a second copy is a second thing to keep in step.
GREETING, WRONG_CATEGORY, RIGHT_CATEGORY, RIGHT_TYPE, WIN = (
    content_module.CRAVING_LADDER
)
# ❌ ends a message; ✖ pads out the slot the ❌ could not take when a
# player had already reacted with it. Neither is an answer, and neither has
# a rank.
OUT_OF_GUESSES = content_module.OUT_OF_GUESSES
MESSAGE_FULL = content_module.MESSAGE_FULL

# Discord merges identical emoji into one reaction with a count, and caps a
# message at 20 distinct ones. The bot needs a slot left to answer in, so the
# 20th is spent saying "no more guesses here" rather than on another guess.
MAX_REACTIONS = 20

# The categories that are in the file but not in the game. A guess filed
# under one of these is the friendly nothing - the same answer an emoji
# the file has never heard of gets, because to a player there is no
# difference between the two and there should not be.
#
# `Bot` is in here because those are the bot's own replies. They are
# `excluded` as well, which is the gate that actually stops them, but a
# category that reads as a guess would be a quiet way back in.
NON_GAME_CATEGORIES = frozenset({"Misc", "Cat", "Bot"})

# The written opening week, by CLDR short name, out of the module that
# validates it. Counted by rows in `craving_days` rather than by the
# calendar, so a day nobody plays is not spent: the script is the first five
# cravings this server draws, whenever they happen.
SCRIPTED_CRAVINGS = content_module.SCRIPTED_CRAVINGS

POINTS_SETTING = "craving_points"


async def is_open(guild_id: int) -> bool:
    """Whether this server is playing the craving game at all.

    **Checked before anything is drawn.** A reaction on a drop 1 server is
    a player reacting to a message, not a guess, and judging it would draw
    that server a craving, pay out five points and leave a `craving_days`
    row dated before the game existed - all invisibly, because nothing
    about the game is announced and the only sign would be a 🐱.
    """
    drop = await resolve.current_drop(guild_id)
    return drop is not resolve.NO_GAME and drop >= world.CRAVING_FROM_DROP


@dataclass(frozen=True)
class Guess:
    """One judged guess.

    `outcome` is what the ladder said, and drives the bot's reaction.
    `credited` is whether it moved the relationship, which only a win does
    and only the first one a player makes in a day. The two are separate
    because the second win of the day still shows 😻.
    """

    outcome: str
    craving: str
    credited: bool = False
    first: bool = False
    points: int = 0
    score_after: int | None = None

    @property
    def won(self) -> bool:
        return self.outcome == WIN


def normalise(emoji: str) -> str:
    """Strip the variation selector, as the content loader does on the way in.

    Discord hands back some emoji with U+FE0F and some without, and the
    catalogue is not consistent either - 158 of its rows carry one. Doing it
    once on both sides is what stops a single emoji silently never matching.
    """
    return content_module.normalise_emoji(emoji)


# --------------------------------------------------------------------------
# The emoji file
# --------------------------------------------------------------------------


async def entry(emoji: str) -> database.EmojiGroup | None:
    """The catalogue row for one emoji, or None if it has never heard of it.

    **The file holds every emoji now, not just the edible ones**, which
    changed what "not in the file" means. A car used to be absent and so read
    as unrelated by default; it is a `Misc` row today. Both still have to
    read the same, because a player cannot tell them apart.
    """
    session_factory = database._require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(database.EmojiGroup).where(
                database.EmojiGroup.emoji == normalise(emoji)
            )
        )


async def category_of(emoji: str) -> str | None:
    row = await entry(emoji)
    return row.category if row else None


async def type_of(emoji: str) -> str | None:
    """Which game type an emoji belongs to.

    A plate answers here even though it can never be the craving, which is
    what lets it be a legal guess that simply never matches.

    **This was the Unicode subgroup until the catalogue arrived**, and the
    rename is not cosmetic: the old grouping decided the game by accident,
    putting dishware inside Food & Drink. The writers' type is the thing the
    ladder is meant to compare.
    """
    row = await entry(emoji)
    return row.type if row else None


# --------------------------------------------------------------------------
# The ladder
# --------------------------------------------------------------------------


async def reactions() -> dict[str, database.CravingReaction]:
    """`craving_reactions.tsv`, keyed by outcome."""
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = await session.scalars(select(database.CravingReaction))
        return {row.outcome: row for row in rows}


async def reaction_for(outcome: str) -> str | None:
    """The emoji the bot answers `outcome` with."""
    row = (await reactions()).get(outcome)
    return row.emoji if row else None


def rank_of(outcome: str | None, ladder: dict[str, database.CravingReaction]) -> int:
    """Where an outcome sits on the ladder; 0 for nothing and for the end.

    `out_of_guesses` ranks 0 along with "no answer yet", which is correct
    rather than convenient: ❌ is not an answer a later guess has to beat,
    and a message that has one can still earn a 😻 in its last slot.
    """
    row = ladder.get(outcome or "")
    return row.progression if row and row.progression is not None else 0


# --------------------------------------------------------------------------
# Today's craving
# --------------------------------------------------------------------------


async def _pool() -> list[str]:
    """Every emoji the craving may be drawn from."""
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = await session.scalars(
            select(database.EmojiGroup.emoji).where(
                database.EmojiGroup.drawable.is_(True)
            )
        )
        return list(rows)


async def _scripted(session, guild_id: int) -> str | None:
    """The opening week's craving, if this server is still inside it."""
    drawn = await session.scalar(
        select(database.func.count())
        .select_from(database.CravingDay)
        .where(database.CravingDay.guild_id == guild_id)
    )
    if drawn is None or drawn >= len(SCRIPTED_CRAVINGS):
        return None

    wanted = SCRIPTED_CRAVINGS[drawn]
    return await session.scalar(
        select(database.EmojiGroup.emoji).where(
            database.EmojiGroup.name == wanted,
            database.EmojiGroup.drawable.is_(True),
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
        chosen = await _scripted(session, guild_id)

    if chosen is None:
        pool = await _pool()
        if not pool:
            log.warning("No drawable emoji loaded; the craving cannot be drawn")
            return None
        chosen = rng.choice(pool)

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


async def found_today(guild_id: int, user_id: int, day: date | None = None) -> bool:
    """Whether this player has already found today's craving.

    What `/stats` asks before deciding whether to say the cat is craving
    something. Per player, where `already_found` is per server: one player
    solving it does not take the hint away from everybody else.
    """
    day = day or await database.server_today(guild_id)
    session_factory = database._require_session()
    async with session_factory() as session:
        return (
            await session.scalar(
                select(database.CravingTally.last_credited_day).where(
                    database.CravingTally.guild_id == guild_id,
                    database.CravingTally.user_id == user_id,
                )
            )
        ) == day


async def _mark_found(guild_id: int, user_id: int, day: date) -> bool:
    """Record who got there first. False if somebody already had."""
    session_factory = database._require_session()
    async with session_factory() as session:
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


# --------------------------------------------------------------------------
# What one message is showing
# --------------------------------------------------------------------------


async def message_outcome(guild_id: int, message_id: int, day: date) -> str | None:
    """The best answer this message is showing *today*, or None.

    A row from an earlier day reads as None, which is what makes the first
    guess of the day on an old message clear it rather than compare against
    it. The caller is what removes the stale reactions; this only says that
    there are some.
    """
    session_factory = database._require_session()
    async with session_factory() as session:
        row = await session.get(database.CravingMessage, (guild_id, message_id))
    if row is None or row.day != day:
        return None
    return row.outcome


async def is_stale(guild_id: int, message_id: int, day: date) -> bool:
    """Whether this message carries the bot's answers from an earlier day."""
    session_factory = database._require_session()
    async with session_factory() as session:
        row = await session.get(database.CravingMessage, (guild_id, message_id))
    return row is not None and row.day != day


async def set_message_outcome(
    guild_id: int, message_id: int, day: date, outcome: str
) -> None:
    session_factory = database._require_session()
    insert = database._upsert_statement()
    async with session_factory() as session:
        await session.execute(
            insert(database.CravingMessage)
            .values(
                guild_id=guild_id, message_id=message_id, day=day, outcome=outcome
            )
            .on_conflict_do_update(
                index_elements=[
                    database.CravingMessage.guild_id,
                    database.CravingMessage.message_id,
                ],
                set_={"day": day, "outcome": outcome},
            )
        )
        await session.commit()


# --------------------------------------------------------------------------
# Judging
# --------------------------------------------------------------------------


async def judge(
    guild_id: int, user_id: int, emoji: str, day: date | None = None
) -> Guess | None:
    """Score one guess, and credit the player if it was right.

    None means the guess was not a guess: the server is not playing yet, or
    the emoji is one of the bot's own and judging those would let a
    player walk the ladder backwards off the answers. The caller does
    nothing at all with it - no reaction, no telemetry row - because the
    player did not play.

    A win always shows 😻, whether the player is first or twentieth and
    whether they have already scored today. Only the day's first win credits
    them. Once the 😻 is up the answer is visible to anyone who looks, so a
    late reaction is copying rather than solving - and that is not a gap to
    close. The tally measures taking part.
    """
    if not await is_open(guild_id):
        return None

    day = day or await database.server_today(guild_id)
    guessed = normalise(emoji)

    row = await entry(guessed)
    if row is not None and row.excluded:
        return None

    craving = await craving_for(guild_id, day)
    if craving is None:
        return None

    if row is None or row.category in NON_GAME_CATEGORIES:
        return Guess(outcome=GREETING, craving=craving)

    if guessed == craving:
        first = await _mark_found(guild_id, user_id, day)
        scored = await credit(guild_id, user_id, day)
        points, score = 0, None
        if scored:
            points = await database.get_setting(guild_id, POINTS_SETTING)
            # A player can guess without ever having run a command, so
            # there may be no `users` row to move. `adjust_relationship`
            # updates by primary key and would otherwise move nothing and
            # report it as though it had.
            await database.ensure_user_exists(user_id, guild_id)
            score = await database.adjust_relationship(user_id, guild_id, points)
        return Guess(
            outcome=WIN,
            craving=craving,
            credited=scored,
            first=first,
            points=points,
            score_after=score,
        )

    wanted = await entry(craving)
    if wanted is None or row.category != wanted.category:
        return Guess(outcome=WRONG_CATEGORY, craving=craving)
    if row.type != wanted.type:
        return Guess(outcome=RIGHT_CATEGORY, craving=craving)
    return Guess(outcome=RIGHT_TYPE, craving=craving)
