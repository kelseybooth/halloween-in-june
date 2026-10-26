"""Alexa, and the cat's craving of the day.

Neither is a slash command. The logic lives outside the Discord handlers so it
can be tested without a gateway, and what is tested here is the logic; the
handlers are thin wrappers over it.

The craving rules that matter are the ones that look like bugs until you read
the reasoning. A player scores a day **once**, however many times they react.
A late guess still scores, because the tally measures showing up rather than
solving, and the answer being visible once the cat appears is not a gap to
close. A win that paid nothing still shows the cat, because the reaction is a
function of the emoji and the day and cannot be a function of who is looking.
And nothing is private, because a reaction carries no interaction token.

**Day one is the mouse**, every time, on every server: the first five cravings
are written rather than rolled. That is a feature of the game and it is also
what lets most of this file name the answer instead of drawing one and working
backwards from it.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import alexa
import content as content_module
import content_loader
import craving
import database


TODAY = date(2026, 10, 20)

# The written opening week, as emoji. Spelled by codepoint rather than by
# literal so that a terminal, an editor or a diff tool that mangles one is a
# mangled test rather than a mangled assertion nobody can see.
MOUSE = chr(0x1F401)
CUT_OF_MEAT = chr(0x1F969)
BROCCOLI = chr(0x1F966)
FISH = chr(0x1F41F)
EGG = chr(0x1F95A)


@pytest.fixture
async def server(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(BOB, GUILD_A)
    await content_loader.load_content(content_module.load_files())
    return db


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


async def test_the_opening_week_is_scripted(server):
    """The first five cravings a server draws are written, not rolled.

    A beta server's first day should not be able to open on a 🫑. The
    script is the writers', and this asserts the emoji rather than the
    names so that a rename in the catalogue that loses one is a failure
    here rather than a silent fall-through to random.
    """
    drawn = [
        await craving.craving_for(GUILD_A, TODAY + timedelta(days=n))
        for n in range(5)
    ]

    assert drawn == [MOUSE, CUT_OF_MEAT, BROCCOLI, FISH, EGG]


async def test_the_script_is_counted_in_draws_not_in_days(server):
    """A day nobody plays is not spent.

    The craving is drawn on first use, so a quiet server has no row for
    that day at all. Counting the calendar instead of the rows would mean
    a server that opens on a Friday and is next touched on a Tuesday skips
    four of its five written cravings.
    """
    assert await craving.craving_for(GUILD_A, TODAY) == MOUSE
    far = TODAY + timedelta(days=30)

    assert await craving.craving_for(GUILD_A, far) == CUT_OF_MEAT


async def test_the_draw_takes_over_after_the_script(server):
    for n in range(len(craving.SCRIPTED_CRAVINGS)):
        await craving.craving_for(GUILD_A, TODAY + timedelta(days=n))

    after = await craving.craving_for(GUILD_A, TODAY + timedelta(days=5))

    assert after in await craving._pool()


async def test_every_scripted_craving_is_drawable(server):
    """Each name has to resolve to exactly one emoji the cat can want.

    Resolved through the loaded file rather than through the parser, so
    this is the same lookup the game does at run time.
    """
    pool = set(await craving._pool())
    for name in craving.SCRIPTED_CRAVINGS:
        found = [e.emoji for e in await _filed() if e.name == name]
        assert len(found) == 1, f"{name} resolves to {found}"
        assert found[0] in pool


async def test_the_same_day_gives_the_same_craving(server):
    """Stored rather than derived: a derived one would move under the players
    if a writer edited the emoji file mid-day."""
    first = await craving.craving_for(GUILD_A, TODAY)
    assert await craving.craving_for(GUILD_A, TODAY) == first


async def test_the_craving_is_only_ever_drawable(server):
    """A plate as the cat's craving of the day is a strange day, and a
    craving nobody's emoji picker has is an unwinnable one."""
    pool = set(await craving._pool())
    for n in range(60):
        drawn = await craving.craving_for(GUILD_A, TODAY + timedelta(days=n))
        assert drawn in pool


async def test_every_server_draws_its_own_script(server, db):
    """Two servers on different days of their own lives, not of the calendar."""
    await db.ensure_user_exists(ALICE, GUILD_B)
    await craving.craving_for(GUILD_A, TODAY)
    await craving.craving_for(GUILD_A, TODAY + timedelta(days=1))

    assert await craving.craving_for(GUILD_B, TODAY) == MOUSE


# --------------------------------------------------------------------------
# The craving: the five rungs
# --------------------------------------------------------------------------


async def test_the_right_emoji_wins(server):
    guess = await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    assert guess.outcome == craving.WIN
    assert guess.won is True
    assert guess.credited is True
    assert guess.first is True


async def test_the_right_type_is_the_narrowest_near_miss(server):
    """Day one is the mouse, which is Prey/Mammal. Another mammal is as
    close as a losing guess gets."""
    other = await _one(category="Prey", type="Mammal", other_than=MOUSE)

    guess = await craving.judge(GUILD_A, ALICE, other, TODAY)

    assert guess.outcome == craving.RIGHT_TYPE


async def test_the_right_category_and_the_wrong_type(server):
    bird = await _one(category="Prey", type="Bird")

    guess = await craving.judge(GUILD_A, ALICE, bird, TODAY)

    assert guess.outcome == craving.RIGHT_CATEGORY


async def test_a_game_category_that_is_not_todays(server):
    """Food is a real category and today is Prey, so this is a guess at the
    game rather than a guess at nothing."""
    guess = await craving.judge(GUILD_A, ALICE, BROCCOLI, TODAY)

    assert guess.outcome == craving.WRONG_CATEGORY


@pytest.mark.parametrize("category", ["Adjacent", "Toy"])
async def test_the_two_categories_that_can_never_win(server, category):
    """A mug and a ball of yarn are both in the game and neither is ever
    the answer, so the best either can earn is the 😼."""
    guess = await craving.judge(GUILD_A, ALICE, await _one(category=category), TODAY)

    assert guess.outcome == craving.WRONG_CATEGORY


async def test_something_that_is_not_food_at_all(server):
    guess = await craving.judge(GUILD_A, ALICE, "\N{AUTOMOBILE}", TODAY)

    assert guess.outcome == craving.GREETING


async def test_an_emoji_the_file_has_never_heard_of(server):
    """A skin-tone variant or a server's custom emote. The list does not
    carry either, and both get the friendly 🐱 like any other stranger."""
    guess = await craving.judge(GUILD_A, ALICE, "\N{THUMBS UP SIGN}\U0001F3FD", TODAY)

    assert guess.outcome == craving.GREETING


async def test_an_unrelated_emoji_in_the_file_reads_the_same_way(server):
    """**What the new catalogue changed.** The file used to hold only the
    edible emoji, so "not in the file" and "nothing to do with food" were
    the same condition - a car fell through to the friendly answer by
    being absent. The file holds all 1,927 now, so a car is a `Misc` row,
    and judging on type alone would score it as a wrong guess at food.

    A player cannot tell those two apart and should not be able to, so
    the category is what decides it."""
    shrimp = chr(0x1F990)

    assert await craving.category_of(shrimp) == "Misc"
    assert (await craving.judge(GUILD_A, ALICE, shrimp, TODAY)).outcome == craving.GREETING


async def test_a_cat_emoji_is_a_greeting_rather_than_a_guess(server):
    """The cat category is in the file and out of the game. Reacting to the
    cat with a cat is a thing people do and it is not a guess at dinner."""
    black_cat = chr(0x1F408) + chr(0x200D) + chr(0x2B1B)

    assert await craving.category_of(black_cat) == "Cat"
    assert (
        await craving.judge(GUILD_A, ALICE, black_cat, TODAY)
    ).outcome == craving.GREETING


async def test_the_bots_own_reactions_are_not_judged_at_all(server):
    """**None, not an outcome.** Those six are the bot's own replies, and
    answering one would let a player walk the ladder backwards off the
    answers - react with 😻, be told something, and read the answer out of
    what came back. The player did not guess, so nothing happens: no
    reaction, no telemetry row."""
    for row in await craving.reactions():
        emoji = (await craving.reactions())[row].emoji
        assert await craving.judge(GUILD_A, ALICE, emoji, TODAY) is None


async def test_a_variation_selector_does_not_stop_a_match(server):
    """Discord hands back some emoji with U+FE0F and some without, and the
    catalogue carries one on 158 of its rows. Normalising both sides the
    same way is what stops one emoji silently never matching."""
    guess = await craving.judge(GUILD_A, ALICE, MOUSE + "️", TODAY)

    assert guess.outcome == craving.WIN


# --------------------------------------------------------------------------
# What a win is worth
# --------------------------------------------------------------------------


async def test_a_win_pays_the_configured_points(server):
    before = await database.get_relationship(ALICE, GUILD_A)

    guess = await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    assert guess.points == await database.get_setting(GUILD_A, "craving_points") == 5
    assert await database.get_relationship(ALICE, GUILD_A) == before + 5
    assert guess.score_after == before + 5


async def test_retuning_the_points_changes_what_a_win_pays(server):
    """In config rather than in code, like the toy and the bed, so a
    number retuned mid-beta leaves a dated trace."""
    await database.set_setting(GUILD_A, "craving_points", 9)

    guess = await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    assert guess.points == 9
    assert await database.get_relationship(ALICE, GUILD_A) == 9


async def test_the_second_win_of_the_day_still_shows_the_cat(server):
    """**Credited and won are separate on purpose.** The display is a
    function of the emoji and the day and nothing else, because Discord
    cannot show one message two ways. So a player who already scored gets
    the 😻 again, and is paid nothing for it."""
    await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    again = await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    assert again.won is True
    assert again.credited is False
    assert again.points == 0
    assert await database.get_relationship(ALICE, GUILD_A) == 5


async def test_a_guesser_who_has_never_run_a_command_still_scores(server, db):
    """A reaction is the one way into the game that does not go through a
    slash command, so there may be no `users` row to move. Without one,
    the points would be reported as paid and go nowhere."""
    stranger = 100000000000000009

    guess = await craving.judge(GUILD_A, stranger, MOUSE, TODAY)

    assert guess.points == 5
    assert await database.get_relationship(stranger, GUILD_A) == 5


async def test_a_losing_guess_pays_nothing(server):
    await craving.judge(GUILD_A, ALICE, BROCCOLI, TODAY)

    assert await database.get_relationship(ALICE, GUILD_A) == 0


# --------------------------------------------------------------------------
# The tally
# --------------------------------------------------------------------------


async def test_a_correct_guess_scores_the_day(server):
    await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    assert await craving.tally(GUILD_A, ALICE) == 1


async def test_guessing_twice_in_a_day_scores_once(server):
    """Removing and re-adding a reaction, or reacting on a second bot message,
    must not score twice."""
    for _ in range(5):
        await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    assert await craving.tally(GUILD_A, ALICE) == 1


async def test_a_second_day_scores_again(server):
    for day in (TODAY, TODAY + timedelta(days=1)):
        answer = await craving.craving_for(GUILD_A, day)
        await craving.judge(GUILD_A, ALICE, answer, day)

    assert await craving.tally(GUILD_A, ALICE) == 2


async def test_a_wrong_guess_scores_nothing(server):
    await craving.judge(GUILD_A, ALICE, BROCCOLI, TODAY)

    assert await craving.tally(GUILD_A, ALICE) == 0


async def test_a_late_guess_still_scores(server):
    """The tally measures taking part, not winning a race. Once the cat is up
    the answer is visible to anyone who looks, and that is not a gap to close."""
    await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    late = await craving.judge(GUILD_A, BOB, MOUSE, TODAY)

    assert late.credited is True
    assert late.first is False
    assert await craving.tally(GUILD_A, BOB) == 1


async def test_only_the_first_finder_is_recorded_as_first(server):
    assert (await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)).first is True
    assert (await craving.judge(GUILD_A, BOB, MOUSE, TODAY)).first is False


async def test_the_day_is_marked_found(server):
    assert await craving.already_found(GUILD_A, TODAY) is False

    await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    assert await craving.already_found(GUILD_A, TODAY) is True


async def test_found_today_is_per_player(server):
    """What `/stats` asks. One player solving it does not take the hint
    away from everybody else."""
    await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    assert await craving.found_today(GUILD_A, ALICE, TODAY) is True
    assert await craving.found_today(GUILD_A, BOB, TODAY) is False


async def test_found_today_resets_with_the_day(server):
    await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)
    tomorrow = TODAY + timedelta(days=1)

    assert await craving.found_today(GUILD_A, ALICE, tomorrow) is False


async def test_tallies_are_per_server(db):
    for guild in (GUILD_A, GUILD_B):
        await db.ensure_user_exists(ALICE, guild)
    await content_loader.load_content(content_module.load_files())

    await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    assert await craving.tally(GUILD_A, ALICE) == 1
    assert await craving.tally(GUILD_B, ALICE) == 0


async def test_a_player_who_never_guessed_has_no_tally(server):
    assert await craving.tally(GUILD_A, ALICE) == 0


# --------------------------------------------------------------------------
# The ladder
# --------------------------------------------------------------------------


async def test_the_ladder_comes_out_of_the_content_file(server):
    ladder = await craving.reactions()

    assert set(ladder) == set(content_module.CRAVING_OUTCOMES)
    assert ladder[craving.WIN].emoji == chr(0x1F63B)
    assert ladder[craving.GREETING].emoji == chr(0x1F431)


async def test_the_rungs_climb(server):
    ladder = await craving.reactions()
    ranks = [craving.rank_of(name, ladder) for name in content_module.CRAVING_LADDER]

    assert ranks == sorted(ranks) == [1, 2, 3, 4, 5]


async def test_the_end_of_a_message_is_not_a_rung(server):
    """**Zero, with "nothing yet".** ❌ is not an answer a later guess has
    to beat: a message that has run out of room can still earn its 😻 in
    the last slot, and a ladder rank would stop that."""
    ladder = await craving.reactions()

    assert craving.rank_of(craving.OUT_OF_GUESSES, ladder) == 0
    assert craving.rank_of(None, ladder) == 0


def test_the_cap_leaves_the_bot_a_slot():
    """Discord allows 20 distinct reactions. Without spending the last one on
    "no more guesses here", a correct guess in the final slot would leave the
    bot no room to answer."""
    assert craving.MAX_REACTIONS == 20


# --------------------------------------------------------------------------
# What one message is showing
# --------------------------------------------------------------------------


MESSAGE = 700000000000000001


async def test_a_message_starts_with_nothing_on_it(server):
    assert await craving.message_outcome(GUILD_A, MESSAGE, TODAY) is None
    assert await craving.is_stale(GUILD_A, MESSAGE, TODAY) is False


async def test_a_messages_outcome_is_remembered(server):
    await craving.set_message_outcome(GUILD_A, MESSAGE, TODAY, craving.RIGHT_TYPE)

    assert await craving.message_outcome(GUILD_A, MESSAGE, TODAY) == craving.RIGHT_TYPE


async def test_yesterdays_outcome_reads_as_nothing_and_as_stale(server):
    """**The reason the day is stored at all.** A 😻 left on last night's
    message points at yesterday's answer, which is a lie told to anybody
    scrolling up. It has to read as nothing to compare against *and* as
    something to clear, which are two different questions."""
    yesterday = TODAY - timedelta(days=1)
    await craving.set_message_outcome(GUILD_A, MESSAGE, yesterday, craving.WIN)

    assert await craving.message_outcome(GUILD_A, MESSAGE, TODAY) is None
    assert await craving.is_stale(GUILD_A, MESSAGE, TODAY) is True


async def test_outcomes_are_per_message(server):
    await craving.set_message_outcome(GUILD_A, MESSAGE, TODAY, craving.WIN)

    assert await craving.message_outcome(GUILD_A, MESSAGE + 1, TODAY) is None


async def test_outcomes_are_per_server(server, db):
    """Two servers can post the same message id only in theory, and the
    key carries the guild anyway - because every other table here does,
    and a reset scoped to one server has to reach this one."""
    await craving.set_message_outcome(GUILD_A, MESSAGE, TODAY, craving.WIN)

    assert await craving.message_outcome(GUILD_B, MESSAGE, TODAY) is None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def _filed():
    """Every row of the emoji file, as the game loaded it."""
    session_factory = database._require_session()
    async with session_factory() as session:
        return list(await session.scalars(select(database.EmojiGroup)))


async def _one(*, category, type=None, other_than=None):
    """Any emoji filed under this category, and optionally this type."""
    for row in await _filed():
        if row.category != category or row.excluded:
            continue
        if type is not None and row.type != type:
            continue
        if row.emoji != other_than:
            return row.emoji
    raise AssertionError(f"the file has no {category}/{type} to guess with")
