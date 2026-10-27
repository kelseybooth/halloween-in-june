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

from fake_discord import http_error

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
AN_APPLE = chr(0x1F34E)       # Food as well: the same rung as the broccoli
A_THUMBS_UP = chr(0x1F44D)    # Misc, so the bottom rung

GREETING_FACE = chr(0x1F431)
WRONG_CATEGORY_FACE = chr(0x1F63C)
RIGHT_CATEGORY_FACE = chr(0x1F638)
RIGHT_TYPE_FACE = chr(0x1F440)
WIN_FACE = chr(0x1F63B)
NO_ROOM = chr(0x274C)
PADDING = chr(0x2716)


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

    **And a twenty-first distinct emoji is refused**, which is the rule the
    whole ❌ exists for. Without it here the bot could be tested happily
    adding reactions a real message would reject, and every slot assertion
    in this file would be measuring a cap that is not there.
    """

    CAP = 20

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
            if len(self.reactions) >= self.CAP:
                raise http_error(message="Maximum number of reactions reached")
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
    def order(self):
        """Left to right, the way Discord shows them: first added, first
        shown. Nothing else in this file cares, and the walk below is
        entirely about it."""
        return [r.emoji for r in self.reactions]

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
# Walking the face along
#
# Reactions are shown in the order they were first added, so the cat's face
# stays where the first guess of its rung put it while later guesses land to
# the right of it - and four emoji along it reads as a verdict on somebody
# else's guess. Taking it off and putting it back moves it to the end.
#
# Two calls, so everything here is also about not spending them: only when
# the face is not already last, only when the bot is alone on it, and only
# for a guess that earned the face that is up.
# --------------------------------------------------------------------------


def play(message, emoji):
    """A player's own reaction, on the message before the bot sees it.

    That is the ordering the walk is about and the one `answer` alone does
    not produce: by the time the gateway hands the message over, the guess
    is already sitting to the right of whatever the bot put up last time.
    """
    message.reactions.append(FakeReaction(emoji))
    return emoji


async def test_the_face_walks_along_to_the_newest_guess(server):
    """**Playtest feedback.** Two wrong guesses of the same category and
    type: the 😼 answers both, and belongs beside the second."""
    message = a_message()
    await answer(message, play(message, BROCCOLI))
    assert message.order == [BROCCOLI, WRONG_CATEGORY_FACE]

    await answer(message, play(message, AN_APPLE))

    assert message.order == [BROCCOLI, AN_APPLE, WRONG_CATEGORY_FACE]


async def test_a_worse_guess_does_not_drag_the_face_down_to_it(server):
    """**The thumbs-up case, and the reason the walk is not simply "move
    it after every guess".** The 👀 says somebody got the category and the
    type right. Walked along to sit after a thumbs-up, it would say the
    thumbs-up was the closest anybody has come."""
    message = a_message()
    await answer(message, play(message, ANOTHER_MAMMAL))
    before = list(message.calls)

    await answer(message, play(message, A_THUMBS_UP))

    assert message.order == [ANOTHER_MAMMAL, RIGHT_TYPE_FACE, A_THUMBS_UP]
    assert message.calls == before


async def test_a_better_guess_lands_last_without_any_help(server):
    """The swap puts the new face on the end by itself, so there is
    nothing to walk and no second add."""
    message = a_message()
    await answer(message, play(message, BROCCOLI))

    await answer(message, play(message, ANOTHER_MAMMAL))

    assert message.order == [BROCCOLI, ANOTHER_MAMMAL, RIGHT_TYPE_FACE]
    assert message.calls.count(("add", RIGHT_TYPE_FACE)) == 1


async def test_a_face_already_last_costs_nothing(server):
    """A second player clicking an emoji that is already on the message
    moves nothing, so neither does the bot. Two calls a guess on a busy
    message is the thing worth not spending."""
    message = a_message()
    await answer(message, play(message, BROCCOLI))
    before = list(message.calls)

    await answer(message, BROCCOLI)

    assert message.calls == before


async def test_a_face_a_player_is_also_on_stays_where_it_is(server):
    """Removing the bot's reaction leaves theirs standing, so the position
    does not move and the two calls buy nothing. The walk is a nicety, and
    it is allowed not to happen."""
    message = a_message(others=(WRONG_CATEGORY_FACE,))
    await answer(message, play(message, BROCCOLI))
    before = list(message.calls)

    await answer(message, play(message, AN_APPLE))

    assert message.calls == before
    assert message.order == [WRONG_CATEGORY_FACE, BROCCOLI, AN_APPLE]


async def test_a_closing_message_is_left_alone(server):
    """At nineteen the next thing the bot does is close the message, and
    the ❌ goes to the right of everything anyway. Letting go of a slot to
    reorder a face is a slot the next guess can take."""
    message = a_message(others=crowd(16))
    await answer(message, play(message, BROCCOLI))

    await answer(message, play(message, AN_APPLE))

    assert ("remove", WRONG_CATEGORY_FACE) not in message.calls
    assert message.order[-1] == NO_ROOM


async def test_a_face_that_went_missing_comes_back(server):
    """The walk is a remove and then an add, and Discord can fail between
    them - leaving a message with an answer recorded against it and no
    face on it. The add is unconditional for that reason: the next guess
    of the same rung puts it back."""
    message = a_message()
    await answer(message, play(message, BROCCOLI))
    message.reactions = [r for r in message.reactions if r.emoji != WRONG_CATEGORY_FACE]

    await answer(message, play(message, AN_APPLE))

    assert WRONG_CATEGORY_FACE in message.mine


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
# Closing the message properly
#
# The ❌ means "no more guesses here", and it is only true if the message
# really is full. A message showing it with a slot still open invites
# exactly one more reaction - and that is the one reaction the bot has no
# room left to answer, so the player gets silence from a bot that just
# told them the opposite.
# --------------------------------------------------------------------------


async def test_the_cross_normally_takes_the_last_slot_by_itself(server):
    """Nineteen distinct and the ❌ makes twenty. No padding needed, and
    none added - a ✖ on every closed message would be noise."""
    message = a_message(others=crowd(19))

    await answer(message, BROCCOLI)

    assert NO_ROOM in message.mine
    assert PADDING not in message.showing
    assert len(message.showing) == 20


async def test_a_player_who_got_there_first_with_the_cross_is_padded(server):
    """**The case the ✖ exists for.** Discord merges identical emoji into
    one reaction, so the bot adding a ❌ a player already used joins their
    reaction instead of taking a slot. The message would say "no more
    guesses" at nineteen, with one slot free."""
    message = a_message(others=crowd(18) + [NO_ROOM])
    assert len(message.showing) == 19

    await answer(message, ANOTHER_MAMMAL)

    assert NO_ROOM in message.mine
    assert PADDING in message.mine
    assert len(message.showing) == 20


async def test_the_padding_is_not_put_up_without_the_cross(server):
    """It is not a reaction to anything. A quiet message never sees it."""
    message = a_message(others=crowd(5))

    await answer(message, BROCCOLI)

    assert PADDING not in message.showing


async def test_a_full_message_gets_neither(server):
    """Twenty already. Both adds fail, and the bot asks for nothing it
    cannot have - the ❌ is tried because it is worth a call, the ✖ is
    not tried at all once the count says there is no room."""
    message = a_message(others=crowd(20))

    await answer(message, BROCCOLI)

    assert len(message.showing) == 20


async def test_padding_is_cleared_with_everything_else_the_next_day(server):
    """**Otherwise a message the bot closed stays closed forever.** The ✖
    is in the ladder file, so the stale sweep takes it back along with the
    six - which is the reason it belongs in that file rather than in code,
    where the sweep would have to be told about it separately.

    The message here is a quiet one the bot closed and whose crowd then
    went away, because that is the case where clearing frees real room. A
    busy message closed yesterday is usually still nearly full today: the
    players' own reactions stay, and it closes again straight away.
    """
    message = a_message(others=crowd(3), mine=[NO_ROOM, PADDING])
    # Find day one's mouse, so tomorrow is the cut of meat and the
    # broccoli below is the right category - as in the stale tests above.
    # A written craving stays up until it is found, so merely drawing it
    # would leave tomorrow on the mouse.
    await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)
    await craving.set_message_outcome(
        GUILD_A, message.id, TODAY, craving.OUT_OF_GUESSES
    )

    await answer(message, BROCCOLI, day=TOMORROW)

    assert PADDING not in message.showing
    assert NO_ROOM not in message.showing
    assert message.mine == {RIGHT_CATEGORY_FACE}


async def test_the_padding_is_optional(server, monkeypatch):
    """A content file without the row loads and plays; the bot simply
    cannot close that last gap. Asserted because the validator lets the
    row be missing, and a crash would be a worse answer than a gap."""
    full = await craving.reactions()
    six = {k: v for k, v in full.items() if k != craving.MESSAGE_FULL}

    async def without_padding():
        return six

    monkeypatch.setattr(craving, "reactions", without_padding)
    message = a_message(others=crowd(18) + [NO_ROOM])

    await answer(message, ANOTHER_MAMMAL)

    assert NO_ROOM in message.mine
    assert len(message.showing) == 19


async def test_the_padding_is_never_judged(server):
    """It is a Bot row in the catalogue, excluded like the other six, so a
    player reacting with it gets nothing rather than a cat face."""
    assert await craving.category_of(PADDING) == "Bot"
    assert await craving.judge(GUILD_A, ALICE, PADDING, TODAY) is None


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


async def test_a_win_can_leave_its_own_slot_open(server):
    """**Known, and left alone.** A win swaps out a face the bot owned
    alone, so the message can end at nineteen with a slot free - and no
    ❌, because a win returns before that. A player can fill that slot
    with a guess the bot has no room to answer.

    It is the one gap left and it costs nothing worth closing: the
    message already shows the 😻, which is the best answer there is,
    so the player who guesses into that last slot learns nothing they
    could not already read. Padding it would put a ✖ beside a 😻 and
    tell them the message was *out of guesses*, which is not what
    happened to it. Their guess is still judged, scored and logged.
    """
    message = a_message(others=crowd(17))
    await answer(message, BROCCOLI)
    message.reactions.append(FakeReaction(chr(0x1F920)))

    await answer(message, MOUSE)

    assert message.mine == {WIN_FACE}
    assert len(message.showing) == 19


async def test_the_bot_does_not_ask_a_full_message_for_a_slot(server):
    """The refusal would arrive as an exception and log like a fault, on
    every guess to a message that is merely full - a warning nobody can
    act on, which teaches everybody to skip warnings."""
    message = a_message(others=crowd(20))
    before = list(message.calls)

    await answer(message, BROCCOLI)

    assert message.calls == before
