"""Alexa, and the cat's craving of the day.

Neither is a slash command. The logic lives outside the Discord handlers so it
can be tested without a gateway, and what is tested here is the logic; the
handlers are thin wrappers over it.

The craving rules that matter are the ones that look like bugs until you read
the reasoning. A player scores a day **once**, however many times they react.
A late guess still scores, because the tally measures showing up rather than
solving, and the answer being visible once the cat appears is not a gap to
close. And nothing is private, because a reaction carries no interaction token.
"""

from datetime import date, timedelta

import pytest

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import alexa
import content as content_module
import content_loader
import craving
import database


TODAY = date(2026, 10, 20)
YESTERDAY = TODAY - timedelta(days=1)


@pytest.fixture
async def server(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(BOB, GUILD_A)
    await content_loader.load_content(content_module.load_files())
    return db


async def a_guess_in(group_of, *, same: bool):
    """An emoji in, or not in, the craving's subgroup."""
    pool = await craving._pool()
    return next(e for e, g in pool if (g == group_of) is same and e != group_of)


# --------------------------------------------------------------------------
# Alexa: who she answers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "alexa",
        "Alexa",
        "ALEXA!",
        "alexa, what time is it",
        "hey alexa",
        "ok alexa play something",
        "okay alexa",
    ],
)
def test_she_answers_when_spoken_to(text):
    assert alexa.is_addressed(text)


@pytest.mark.parametrize(
    "text",
    [
        "ask alexa about it",
        "the alexa is blinking",
        "I wonder what alexa thinks",
        "",
        "hello",
    ],
)
def test_she_ignores_people_talking_about_her(text):
    """Talking about a speaker is not talking to one."""
    assert not alexa.is_addressed(text)


# --------------------------------------------------------------------------
# Alexa: the message for David
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "alexa remind david to cancel the delivery",
        "alexa remember the subscription",
        "alexa, the order — remind him?",
        "alexa please remind david about that subscribe thing",
        "alexa the delivery, remember to tell him",
    ],
)
def test_both_halves_in_any_order_count(text):
    """A player should not have to guess a phrasing."""
    assert alexa.is_message_for_david(text)


@pytest.mark.parametrize(
    "text",
    [
        "alexa remind me about dinner",       # asking, but not about the order
        "alexa cancel the delivery",          # about it, but not asking
        "alexa what is a subscription",
        "alexa",
    ],
)
def test_one_half_is_not_enough(text):
    assert not alexa.is_message_for_david(text)


def test_reminder_is_covered_by_remind():
    """`remind` is a prefix of `reminder`, so the list needs only the stem."""
    assert alexa.is_message_for_david("alexa set a reminder about the order")


def test_costco_is_not_a_trigger_word():
    """Deliberately absent: the standing order is no longer described as a
    Costco subscription anywhere in the content, so a player reading the to-do
    list has no reason to type it."""
    assert not alexa.is_message_for_david("alexa cancel the costco run")
    assert "costco" not in " ".join(alexa._ABOUT + alexa._ASKING)


def test_punctuation_and_case_do_not_matter():
    assert alexa.is_message_for_david("ALEXA!! Remind David — the DELIVERY?!")


# --------------------------------------------------------------------------
# The craving: drawing it
# --------------------------------------------------------------------------


async def test_a_craving_is_drawn_on_first_use(server):
    assert await craving.craving_for(GUILD_A, TODAY) is not None


async def test_the_same_day_gives_the_same_craving(server):
    """Stored rather than derived: a derived one would move under the players
    if a writer edited the emoji file mid-day."""
    first = await craving.craving_for(GUILD_A, TODAY)
    assert await craving.craving_for(GUILD_A, TODAY) == first


async def test_the_craving_is_drawn_from_the_drawable_pool(server):
    drawn = await craving.craving_for(GUILD_A, TODAY)
    assert drawn in {e for e, _ in await craving._pool()}


async def test_a_plate_is_never_the_craving(server):
    """Dishware is in the group but is not food, and a plate as the cat's
    craving of the day is a strange day."""
    drawable = {e for e, _ in await craving._pool()}
    for day_offset in range(60):
        drawn = await craving.craving_for(GUILD_A, TODAY + timedelta(days=day_offset))
        assert drawn in drawable


async def test_every_server_gets_its_own_craving(server, db):
    await db.ensure_user_exists(ALICE, GUILD_B)
    a = await craving.craving_for(GUILD_A, TODAY)
    b = await craving.craving_for(GUILD_B, TODAY)

    assert a is not None and b is not None  # independent draws, may coincide


async def test_a_new_day_draws_again(server):
    today = await craving.craving_for(GUILD_A, TODAY)
    tomorrow = await craving.craving_for(GUILD_A, TODAY + timedelta(days=1))

    assert today is not None and tomorrow is not None


# --------------------------------------------------------------------------
# The craving: judging a guess
# --------------------------------------------------------------------------


async def test_the_right_emoji_is_correct(server):
    answer = await craving.craving_for(GUILD_A, TODAY)
    guess = await craving.judge(GUILD_A, ALICE, answer, TODAY)

    assert guess.verdict == craving.CORRECT
    assert guess.credited is True
    assert guess.first is True


async def test_the_same_subgroup_earns_the_narrowing_signal(server):
    answer = await craving.craving_for(GUILD_A, TODAY)
    group = await craving.subgroup_of(answer)
    near = next(e for e, g in await craving._pool() if g == group and e != answer)

    assert (await craving.judge(GUILD_A, ALICE, near, TODAY)).verdict == craving.SAME_GROUP


async def test_a_different_subgroup_is_just_wrong(server):
    answer = await craving.craving_for(GUILD_A, TODAY)
    group = await craving.subgroup_of(answer)
    far = next(e for e, g in await craving._pool() if g != group)

    assert (await craving.judge(GUILD_A, ALICE, far, TODAY)).verdict == craving.WRONG


async def test_a_plate_is_a_legal_guess_that_never_matches(server):
    """It resolves to a known subgroup and simply never wins, which is what
    keeping `drawable` separate from `subgroup` buys."""
    guess = await craving.judge(GUILD_A, ALICE, "\N{FORK AND KNIFE WITH PLATE}", TODAY)

    assert guess.verdict == craving.WRONG
    assert guess.credited is False


async def test_something_that_is_not_food_at_all(server):
    guess = await craving.judge(GUILD_A, ALICE, "\N{AUTOMOBILE}", TODAY)
    assert guess.verdict == craving.NOT_FOOD


async def test_a_variation_selector_does_not_stop_a_match(server):
    """Discord hands back some emoji with U+FE0F and some without. Normalising
    both sides the same way is what stops one emoji silently never matching."""
    answer = await craving.craving_for(GUILD_A, TODAY)
    guess = await craving.judge(GUILD_A, ALICE, answer + "️", TODAY)

    assert guess.verdict == craving.CORRECT


# --------------------------------------------------------------------------
# The tally
# --------------------------------------------------------------------------


async def test_a_correct_guess_scores_the_day(server):
    answer = await craving.craving_for(GUILD_A, TODAY)
    await craving.judge(GUILD_A, ALICE, answer, TODAY)

    assert await craving.tally(GUILD_A, ALICE) == 1


async def test_guessing_twice_in_a_day_scores_once(server):
    """Removing and re-adding a reaction, or reacting on a second bot message,
    must not score twice."""
    answer = await craving.craving_for(GUILD_A, TODAY)
    for _ in range(5):
        await craving.judge(GUILD_A, ALICE, answer, TODAY)

    assert await craving.tally(GUILD_A, ALICE) == 1


async def test_a_second_day_scores_again(server):
    for day in (YESTERDAY, TODAY):
        answer = await craving.craving_for(GUILD_A, day)
        await craving.judge(GUILD_A, ALICE, answer, day)

    assert await craving.tally(GUILD_A, ALICE) == 2


async def test_a_wrong_guess_scores_nothing(server):
    answer = await craving.craving_for(GUILD_A, TODAY)
    group = await craving.subgroup_of(answer)
    far = next(e for e, g in await craving._pool() if g != group)

    await craving.judge(GUILD_A, ALICE, far, TODAY)
    assert await craving.tally(GUILD_A, ALICE) == 0


async def test_a_late_guess_still_scores(server):
    """The tally measures taking part, not winning a race. Once the cat is up
    the answer is visible to anyone who looks, and that is not a gap to close."""
    answer = await craving.craving_for(GUILD_A, TODAY)
    await craving.judge(GUILD_A, ALICE, answer, TODAY)

    late = await craving.judge(GUILD_A, BOB, answer, TODAY)

    assert late.credited is True
    assert late.first is False
    assert await craving.tally(GUILD_A, BOB) == 1


async def test_only_the_first_finder_is_recorded_as_first(server):
    answer = await craving.craving_for(GUILD_A, TODAY)

    assert (await craving.judge(GUILD_A, ALICE, answer, TODAY)).first is True
    assert (await craving.judge(GUILD_A, BOB, answer, TODAY)).first is False


async def test_the_day_is_marked_found(server):
    assert await craving.already_found(GUILD_A, TODAY) is False

    answer = await craving.craving_for(GUILD_A, TODAY)
    await craving.judge(GUILD_A, ALICE, answer, TODAY)

    assert await craving.already_found(GUILD_A, TODAY) is True


async def test_tallies_are_per_server(db):
    for guild in (GUILD_A, GUILD_B):
        await db.ensure_user_exists(ALICE, guild)
    await content_loader.load_content(content_module.load_files())

    answer = await craving.craving_for(GUILD_A, TODAY)
    await craving.judge(GUILD_A, ALICE, answer, TODAY)

    assert await craving.tally(GUILD_A, ALICE) == 1
    assert await craving.tally(GUILD_B, ALICE) == 0


async def test_a_player_who_never_guessed_has_no_tally(server):
    assert await craving.tally(GUILD_A, ALICE) == 0


# --------------------------------------------------------------------------
# The reaction budget
# --------------------------------------------------------------------------


def test_the_cap_leaves_the_bot_a_slot():
    """Discord allows 20 distinct reactions. Without spending the last one on
    "no more guesses here", a correct guess in the final slot would leave the
    bot no room to answer."""
    assert craving.MAX_REACTIONS == 20


def test_the_three_answers_are_distinct():
    assert len({craving.RIGHT_GROUP, craving.FOUND, craving.NO_ROOM}) == 3
