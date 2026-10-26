"""What the bot puts on a message, and when it takes it off again.

`craving.judge` decides what a guess earned; this is the half that turns that
into reactions, and almost all of it exists because of one Discord rule: a bot
may put each emoji on a message **once**. So the bot cannot answer each guess.
It carries the message's best answer so far and replaces it when a guess beats
it, which makes the displayed outcome a piece of state with three ways to be
wrong - stale from yesterday, beaten by a worse guess, or occupying the last
reaction slot that a win needed.

The fake message below models the rule that makes the third one hard: removing
the bot's reaction frees a slot *only* if the bot was the only one who clicked
it. A player who also clicked keeps the emoji on the message with their count,
and a bot keeping its own tally would drift from Discord within a day.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from conftest import ALICE, GUILD_A

import bot as bot_module
import content as content_module
import content_loader
import craving
import database


TODAY = date(2026, 10, 20)
# The second day a server plays, which is the cut of meat: Food, Protein.
# Named rather than inferred, because the stale-message tests below depend
# on today's answer and tomorrow's being in different categories.
TOMORROW = TODAY + timedelta(days=1)

MOUSE = chr(0x1F401)          # day one, every time
ANOTHER_MAMMAL = chr(0x1F430) # rabbit face: Prey, Mammal
A_BIRD = chr(0x1F414)         # chicken: Prey, Bird
BROCCOLI = chr(0x1F966)       # Food, so the wrong category today

GREETING_FACE = chr(0x1F431)
WRONG_CATEGORY_FACE = chr(0x1F63C)
RIGHT_CATEGORY_FACE = chr(0x1F638)
RIGHT_TYPE_FACE = chr(0x1F440)
WIN_FACE = chr(0x1F63B)
NO_ROOM = chr(0x274C)


class FakeReaction:
    def __init__(self, emoji, *, me=False, count=1):
        self.emoji = emoji
        self.me = me
        self.count = count


class FakeMessage:
    """Just enough of a Discord message to be wrong in the same ways.

    `add_reaction` and `remove_reaction` act on the live list the way the
    gateway does: adding an emoji somebody already used joins their reaction
    rather than making a second one, and removing the bot's leaves the
    reaction standing if anybody else is on it.
    """

    def __init__(self, guild, message_id=1, *, others=(), mine=()):
        self.guild = guild
        self.id = message_id
        self.reactions = [FakeReaction(e) for e in others]
        self.reactions += [FakeReaction(e, me=True) for e in mine]
        self.calls = []

    def _find(self, emoji):
        return next((r for r in self.reactions if r.emoji == emoji), None)

    async def add_reaction(self, emoji):
        self.calls.append(("add", emoji))
        found = self._find(emoji)
        if found is None:
            self.reactions.append(FakeReaction(emoji, me=True))
        elif not found.me:
            found.me = True
            found.count += 1

    async def remove_reaction(self, emoji, _user):
        self.calls.append(("remove", emoji))
        found = self._find(emoji)
        if found is None or not found.me:
            return
        found.me = False
        found.count -= 1
        if found.count == 0:
            self.reactions.remove(found)

    @property
    def showing(self):
        return {r.emoji for r in self.reactions}

    @property
    def mine(self):
        return {r.emoji for r in self.reactions if r.me}


class FakeGuildId:
    def __init__(self, guild_id):
        self.id = guild_id


@pytest.fixture
async def server(db, monkeypatch):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await content_loader.load_content(content_module.load_files())
    # `_answer_guess` names the bot when it takes a reaction back off.
    monkeypatch.setattr(bot_module.bot, "_connection", bot_module.bot._connection, raising=False)
    return db


def a_message(message_id=1, *, others=(), mine=()):
    return FakeMessage(FakeGuildId(GUILD_A), message_id, others=others, mine=mine)


async def answer(message, emoji, day=TODAY):
    """Judge one guess and let the bot put its answer on the message."""
    guess = await craving.judge(GUILD_A, ALICE, emoji, day)
    assert guess is not None, f"{emoji} was not judged at all"
    await bot_module._answer_guess(message, guess, day)
    return guess


# --------------------------------------------------------------------------
# One guess at a time
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "guess, face",
    [
        (chr(0x1F697), GREETING_FACE),    # a car: not in the game
        (BROCCOLI, WRONG_CATEGORY_FACE),  # Food, and today is Prey
        (A_BIRD, RIGHT_CATEGORY_FACE),    # Prey, and today is a Mammal
        (ANOTHER_MAMMAL, RIGHT_TYPE_FACE),
        (MOUSE, WIN_FACE),
    ],
)
async def test_each_rung_gets_its_own_face(server, guess, face):
    message = a_message()

    await answer(message, guess)

    assert message.mine == {face}


async def test_the_answer_is_remembered_against_the_message(server):
    message = a_message()

    await answer(message, A_BIRD)

    assert await craving.message_outcome(
        GUILD_A, message.id, TODAY
    ) == craving.RIGHT_CATEGORY


# --------------------------------------------------------------------------
# Only a better guess changes the message
# --------------------------------------------------------------------------


async def test_a_better_guess_replaces_the_face(server):
    message = a_message()
    await answer(message, BROCCOLI)

    await answer(message, ANOTHER_MAMMAL)

    assert message.mine == {RIGHT_TYPE_FACE}
    assert ("remove", WRONG_CATEGORY_FACE) in message.calls


async def test_a_worse_guess_changes_nothing(server):
    """**The 👀 after the 😻 is the case that matters.** The message shows
    how close anybody has got, so a later bad guess must not walk it back."""
    message = a_message()
    await answer(message, MOUSE)
    before = list(message.calls)

    await answer(message, BROCCOLI)

    assert message.mine == {WIN_FACE}
    assert message.calls == before


async def test_the_same_rung_twice_costs_nothing(server):
    """Two calls per change, and the rate limit is per message. Re-adding
    what is already there is the cheapest thing to get wrong."""
    message = a_message()
    await answer(message, A_BIRD)
    before = list(message.calls)

    await answer(message, A_BIRD)

    assert message.calls == before


async def test_two_messages_keep_their_own_answers(server):
    first, second = a_message(1), a_message(2)

    await answer(first, MOUSE)
    await answer(second, BROCCOLI)

    assert first.mine == {WIN_FACE}
    assert second.mine == {WRONG_CATEGORY_FACE}


# --------------------------------------------------------------------------
# Yesterday's answers
# --------------------------------------------------------------------------


async def test_an_old_messages_faces_are_cleared_before_judging(server):
    """**A 😻 left overnight points at the wrong emoji.** The craving rolls
    over at midnight and the reactions do not, so the first guess to land
    on an old message clears what the bot left there before answering.

    Today is the mouse and tomorrow is the cut of meat, so the rabbit is a
    win-adjacent near miss today and the wrong category entirely tomorrow -
    which is the whole point: the face has to come *down*, and a rule that
    only ever replaced a worse answer with a better one would leave it up.
    """
    message = a_message()
    await answer(message, MOUSE, day=TODAY)
    assert message.mine == {WIN_FACE}

    await answer(message, ANOTHER_MAMMAL, day=TOMORROW)

    assert message.mine == {WRONG_CATEGORY_FACE}


async def test_clearing_does_not_touch_a_players_own_reaction(server):
    """The bot takes back its own six and nothing else. A player who
    reacted with 🥦 yesterday still has 🥦 there today."""
    message = a_message(others=[BROCCOLI])
    await answer(message, MOUSE, day=TODAY)

    await answer(message, BROCCOLI, day=TOMORROW)

    assert BROCCOLI in message.showing
    assert message.mine == {RIGHT_CATEGORY_FACE}


async def test_a_message_judged_today_is_not_cleared(server):
    message = a_message()
    await answer(message, A_BIRD)
    assert ("remove", RIGHT_CATEGORY_FACE) not in message.calls

    await answer(message, ANOTHER_MAMMAL)

    assert message.calls.count(("remove", RIGHT_CATEGORY_FACE)) == 1


# --------------------------------------------------------------------------
# The twentieth slot
# --------------------------------------------------------------------------


def crowd(n, *, start=0x1F600):
    """`n` distinct emoji nobody in this game cares about."""
    return [chr(start + i) for i in range(n)]


async def test_a_full_message_is_marked_with_a_cross(server):
    """Nineteen distinct emoji on it, and a losing guess. The twentieth
    slot says there is no twenty-first, because a message that silently
    stops accepting reactions looks like a broken bot."""
    message = a_message(others=crowd(19))

    await answer(message, BROCCOLI)

    assert NO_ROOM in message.mine


async def test_a_quiet_message_is_not(server):
    message = a_message(others=crowd(5))

    await answer(message, BROCCOLI)

    assert NO_ROOM not in message.mine


async def test_a_win_takes_the_last_slot_itself(server):
    """A correct guess at nineteen still gets its 😻, and no ❌ goes with
    it - there would be no room for both, and the cat is the better of
    the two things to end the message on."""
    message = a_message(others=crowd(19))

    await answer(message, MOUSE)

    assert WIN_FACE in message.mine
    assert NO_ROOM not in message.mine


async def test_a_face_the_bot_owns_alone_frees_its_slot_when_replaced(server):
    """Seventeen others plus the bot's own 😼 is eighteen. Nobody else is
    on the 😼, so upgrading it to 😸 is a swap and the message is still
    eighteen - with room for another guess."""
    message = a_message(others=crowd(17))
    await answer(message, BROCCOLI)
    assert len(message.showing) == 18

    await answer(message, A_BIRD)

    assert len(message.showing) == 18
    assert NO_ROOM not in message.mine


async def test_a_face_a_player_also_clicked_does_not_free_a_slot(server):
    """**The case a remembered tally gets wrong, and the pair to the test
    above.** The same eighteen emoji, and the only difference is that a
    player is also on the 😼. So removing the bot's leaves it standing,
    the upgrade to 😸 grows the message to nineteen rather than holding at
    eighteen, and that is the guess the ❌ follows.
    """
    message = a_message(others=crowd(17) + [WRONG_CATEGORY_FACE])
    await answer(message, BROCCOLI)
    assert len(message.showing) == 18

    await answer(message, A_BIRD)

    assert WRONG_CATEGORY_FACE in message.showing
    assert RIGHT_CATEGORY_FACE in message.mine
    assert NO_ROOM in message.mine
    assert len(message.showing) == 20


async def test_a_full_message_does_not_spend_its_last_slot_on_a_face(server):
    """**Nineteen already, so the 👀 never goes up.** It would fill the
    twentieth slot and leave the ❌ nowhere to go - and a 👀 nobody can
    follow up on is a worse last word than "no more guesses here"."""
    message = a_message(others=crowd(19))

    await answer(message, ANOTHER_MAMMAL)

    assert message.mine == {NO_ROOM}
    assert len(message.showing) == 20


# --------------------------------------------------------------------------
# What is not a guess
# --------------------------------------------------------------------------


async def test_the_bots_own_face_is_not_answered(server):
    """Reacting with the cat's own 😻 earns nothing and changes nothing.
    Judging it would let a player read the answer out of what came back."""
    message = a_message()

    assert await craving.judge(GUILD_A, ALICE, WIN_FACE, TODAY) is None
    assert message.calls == []


# --------------------------------------------------------------------------
# The row each guess leaves
#
# `outcome` stays two-valued, as it is for every other action: a win is a
# success and every other rung is a refusal. That reads oddly for a 👀 and
# it is the right shape, because the column's one job is to answer "did it
# work" across all of them. Which rung it was goes in `reason`.
# --------------------------------------------------------------------------


async def logged(db):
    async with db._require_session()() as session:
        return list(
            (
                await session.scalars(
                    select(database.InteractionLog)
                    .where(database.InteractionLog.action == database.CRAVING_GUESS)
                    .order_by(database.InteractionLog.id)
                )
            ).all()
        )


async def guess_through_the_handler(message, emoji, day=TODAY):
    guess = await craving.judge(GUILD_A, ALICE, emoji, day)
    await bot_module._log_guess(GUILD_A, ALICE, emoji, guess)
    return guess


async def test_a_win_is_a_success_worth_five(server):
    await guess_through_the_handler(a_message(), MOUSE)

    row, = await logged(server)
    assert row.outcome == database.SUCCESS
    assert row.reason == craving.WIN
    assert row.relationship_delta == 5
    assert row.score_after == 5


async def test_a_near_miss_is_a_refusal_naming_its_rung(server):
    await guess_through_the_handler(a_message(), ANOTHER_MAMMAL)

    row, = await logged(server)
    assert row.outcome == database.REFUSED
    assert row.reason == craving.RIGHT_TYPE
    assert row.relationship_delta == 0


async def test_the_emoji_is_on_the_row(server):
    """The useful report is not how often players win. It is what they
    guess when they are close, which is the only evidence of whether the
    categories read the way the writers meant them to."""
    await guess_through_the_handler(a_message(), A_BIRD)

    row, = await logged(server)
    assert A_BIRD in row.detail
    assert craving.RIGHT_CATEGORY in row.detail


async def test_a_win_that_paid_nothing_says_so(server):
    """Still a success - they won - and the delta is the figure that
    moved, which is nothing."""
    await guess_through_the_handler(a_message(), MOUSE)

    await guess_through_the_handler(a_message(2), MOUSE)

    second = (await logged(server))[1]
    assert second.outcome == database.SUCCESS
    assert second.relationship_delta == 0


async def test_every_guess_leaves_exactly_one_row(server):
    for emoji in (chr(0x1F697), BROCCOLI, A_BIRD, ANOTHER_MAMMAL, MOUSE):
        await guess_through_the_handler(a_message(), emoji)

    rows = await logged(server)
    assert [row.reason for row in rows] == [
        craving.GREETING,
        craving.WRONG_CATEGORY,
        craving.RIGHT_CATEGORY,
        craving.RIGHT_TYPE,
        craving.WIN,
    ]


async def test_the_drop_is_filled_in(server):
    """The slicer every telemetry question starts with."""
    await guess_through_the_handler(a_message(), MOUSE)

    row, = await logged(server)
    assert row.drop is not None
