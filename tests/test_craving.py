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

import io
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import alexa
import content as content_module
import content_loader
import craving
import database
import resolve
import world


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


SCRIPT = [MOUSE, CUT_OF_MEAT, BROCCOLI, FISH, EGG]


async def play_the_script(days=range(5), who=ALICE):
    """Find each written craving in turn, one a day, and report them."""
    found = []
    for n in days:
        day = TODAY + timedelta(days=n)
        answer = await craving.craving_for(GUILD_A, day)
        found.append(answer)
        await craving.judge(GUILD_A, who, answer, day)
    return found


async def test_the_opening_week_is_scripted(server):
    """Found one a day, the five come up in the written order.

    A beta server's first day should not be able to open on a 🫑. The
    script is the writers', and this asserts the emoji rather than the
    names so that a rename in the catalogue that loses one is a failure
    here rather than a silent fall-through to random.
    """
    assert await play_the_script() == SCRIPT


async def test_a_written_craving_stays_up_until_it_is_found(server):
    """**The point of the five.** They are the game teaching itself, and
    a player who has never seen the ladder work needs to see one craving
    found. Rolling them past at midnight would let a quiet server burn
    the written week without playing it, and arrive at the random draw
    having never had a win.
    """
    for n in range(10):
        assert await craving.craving_for(GUILD_A, TODAY + timedelta(days=n)) == MOUSE


async def test_finding_it_is_what_moves_the_script_on(server):
    await craving.craving_for(GUILD_A, TODAY)
    tomorrow = TODAY + timedelta(days=1)
    assert await craving.craving_for(GUILD_A, tomorrow) == MOUSE

    await craving.judge(GUILD_A, ALICE, MOUSE, tomorrow)

    assert await craving.craving_for(
        GUILD_A, tomorrow + timedelta(days=1)
    ) == CUT_OF_MEAT


async def test_the_day_it_is_found_keeps_its_craving(server):
    """Finding the mouse at two in the afternoon does not change what the
    cat wanted this morning. The day's row is already written, and the
    next draw is tomorrow's."""
    assert await craving.craving_for(GUILD_A, TODAY) == MOUSE

    await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    assert await craving.craving_for(GUILD_A, TODAY) == MOUSE


async def test_a_near_miss_does_not_move_the_script_on(server):
    """Only a win counts. A 👀 is not finding it."""
    await craving.craving_for(GUILD_A, TODAY)
    await craving.judge(GUILD_A, ALICE, chr(0x1F430), TODAY)  # rabbit: right type

    assert await craving.craving_for(GUILD_A, TODAY + timedelta(days=1)) == MOUSE


async def test_the_script_is_not_spent_by_a_day_nobody_plays(server):
    """The craving is drawn on first use, so a quiet server has no row
    for that day at all - and now, no win either. Both halves point the
    same way: the written week is spent by playing it."""
    far = TODAY + timedelta(days=30)

    assert await craving.craving_for(GUILD_A, far) == MOUSE


async def test_the_script_restarts_after_a_reset(server):
    """Counting found rows rather than keeping an index is what buys
    this: clearing `craving_days` puts a server back at the mouse, which
    is what a reset should do and what a playtester expects."""
    await play_the_script(days=range(2))
    assert await craving.craving_for(GUILD_A, TODAY + timedelta(days=2)) == BROCCOLI

    await content_loader.reset_guild(GUILD_A, drop=world.CRAVING_FROM_DROP)

    assert await craving.craving_for(GUILD_A, TODAY) == MOUSE


async def test_a_mid_day_advance_does_not_cost_the_opening(server):
    """**The question that prompted the sticky script.**

    Advancing to drop 3 at eleven at night used to be able to spend the
    mouse on twenty minutes almost nobody saw. It cannot now: the mouse
    is up until somebody finds it, so a short evening is just a short
    evening and the opening carries into the next day intact.
    """
    await resolve.set_current_drop(GUILD_A, 3)

    assert await craving.craving_for(GUILD_A, TODAY) == MOUSE
    assert await craving.craving_for(GUILD_A, TODAY + timedelta(days=1)) == MOUSE


async def test_the_draw_takes_over_after_the_script(server):
    """**And it rolls at midnight from then on, found or not.** A random
    draw can be genuinely hard - a type with thirty members, or a
    category line the writers and the players read differently - and a
    game that cannot move past a bad day is worse than one that forgets
    it."""
    await play_the_script()
    sixth = TODAY + timedelta(days=5)

    first_random = await craving.craving_for(GUILD_A, sixth)
    nobody_found_it = await craving.craving_for(GUILD_A, sixth + timedelta(days=1))

    pool = await craving._pool()
    assert first_random in pool and nobody_found_it in pool


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
# Before the game opens
# --------------------------------------------------------------------------


@pytest.mark.parametrize("drop", [0, 1, 2])
async def test_a_server_before_drop_three_is_not_playing(server, drop):
    """**Nothing at all, not a losing answer.** A reaction on a drop 1
    server is a player reacting to a message. Judging it would draw that
    server a craving, pay five points and leave a `craving_days` row dated
    before the game existed - invisibly, because nothing announces the
    game and the only sign would be a 🐱 coming back."""
    await resolve.set_current_drop(GUILD_A, drop)

    assert await craving.is_open(GUILD_A) is False
    assert await craving.judge(GUILD_A, ALICE, MOUSE, TODAY) is None


async def test_nothing_is_drawn_for_a_server_that_is_not_playing(server):
    await resolve.set_current_drop(GUILD_A, 2)

    await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    assert await craving.tally(GUILD_A, ALICE) == 0
    assert await database.get_relationship(ALICE, GUILD_A) == 0


async def test_the_game_opens_on_the_drop_it_was_built_for(server):
    await resolve.set_current_drop(GUILD_A, world.CRAVING_FROM_DROP)

    assert world.CRAVING_FROM_DROP == 3
    assert await craving.is_open(GUILD_A) is True


async def test_a_server_with_no_game_is_not_playing(server):
    """`current_drop` is None there, not zero, and comparing None to a
    drop number raises rather than reading as early."""
    unstarted = 900000000000000999

    assert await craving.is_open(unstarted) is False


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
    """Discord hands back some emoji with U+FE0F and some without.

    **Both sides, which is the half that is easy to miss.** Stripping
    only what Discord sends would still fail for the catalogue rows that
    carry the selector themselves: those would load with it, and a bare
    reaction would never match them. The loader normalises on the way in
    and the judge normalises every guess, through the same function, so
    the two cannot drift apart.

    Written as `chr(0xFE0F)` rather than pasted, because the character
    is invisible and a test whose subject cannot be seen in the diff is
    a test somebody will delete by accident.
    """
    guess = await craving.judge(GUILD_A, ALICE, MOUSE + chr(0xFE0F), TODAY)

    assert guess.outcome == craving.WIN


async def test_the_catalogues_own_selectors_are_stripped_on_the_way_in(server):
    """The file's side of the same problem, read off the file.

    A row that arrives still carrying its selector is unmatchable by a
    bare reaction, and nothing else would say so - that one emoji out of
    1,927 would simply never be guessable.
    """
    carried = [
        row["emoji"] for row in _catalogue_rows() if chr(0xFE0F) in row["emoji"]
    ]
    assert carried, "no catalogue row carries a selector; has the file changed?"

    for raw in carried:
        assert await craving.entry(raw) is not None, raw
        assert await craving.entry(raw.replace(chr(0xFE0F), "")) is not None, raw


async def test_a_zero_width_joiner_is_left_alone(server):
    """**Not every invisible character is noise.** The joiner is what
    makes the black cat a black cat rather than a cat beside a black
    square, so stripping it would merge two different emoji into one."""
    black_cat = chr(0x1F408) + chr(0x200D) + chr(0x2B1B)
    plain_cat = chr(0x1F408)

    assert content_module.normalise_emoji(black_cat) == black_cat
    assert await craving.entry(black_cat) is not None
    assert await craving.entry(plain_cat) is not None


# --------------------------------------------------------------------------
# Two emoji, one animal
# --------------------------------------------------------------------------


MOUSE_FACE = chr(0x1F42D)
RABBIT = chr(0x1F407)
RABBIT_FACE = chr(0x1F430)


async def test_the_mouse_face_wins_when_the_cat_wants_the_mouse(server):
    """**What a player means.** The mouse face is the mouse to anybody
    not reading the Unicode names, and being told "right type, wrong
    emoji" for the face of the thing the cat wants reads as the game
    being broken rather than as a near miss."""
    guess = await craving.judge(GUILD_A, ALICE, MOUSE_FACE, TODAY)

    assert guess.outcome == craving.WIN
    assert guess.credited is True


async def test_the_pair_scores_once_between_them(server):
    """One animal, so one win. Guessing both is not two days' worth."""
    await craving.judge(GUILD_A, ALICE, MOUSE_FACE, TODAY)

    again = await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    assert again.won is True and again.credited is False
    assert await craving.tally(GUILD_A, ALICE) == 1


async def test_either_half_moves_the_script_on(server):
    """Finding it with the face is finding it."""
    await craving.judge(GUILD_A, ALICE, MOUSE_FACE, TODAY)

    assert await craving.craving_for(
        GUILD_A, TODAY + timedelta(days=1)
    ) == CUT_OF_MEAT


async def test_the_rabbit_is_the_other_pair(server):
    """Two pairs today, and the second is the evidence that the first is
    not a special case hiding in the data."""
    face = await craving.entry(RABBIT_FACE)

    assert face is not None and face.same_as == RABBIT


async def test_an_alias_is_never_the_craving_itself(server):
    """Out of the pool, so the cat wants the mouse and never the mouse
    face - which is what stops the mouse being twice as likely as the
    rat, and the cat wanting one animal two different ways."""
    pool = await craving._pool()

    assert MOUSE in pool and MOUSE_FACE not in pool
    assert RABBIT in pool and RABBIT_FACE not in pool


async def test_a_mouse_guessed_on_a_rabbit_day_is_still_a_near_miss(server):
    """The alias folds the pair together, not the type. A mouse face on
    a rabbit day is the right type and the wrong animal, which is
    exactly what it is."""
    await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)  # spend day one
    rabbit_day = TODAY + timedelta(days=1)
    # Set the rabbit by hand: the script's second craving is the meat.
    session_factory = database._require_session()
    async with session_factory() as session:
        await session.execute(
            database.CravingDay.__table__.insert().values(
                guild_id=GUILD_A, day=rabbit_day, emoji=RABBIT
            )
        )
        await session.commit()

    guess = await craving.judge(GUILD_A, ALICE, MOUSE_FACE, rabbit_day)

    assert guess.outcome == craving.RIGHT_TYPE


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


async def test_a_guess_is_not_a_cat_interaction(server):
    """**Deliberately, and the one that is easiest to break by accident.**
    `last_cat_interaction_date` is what stops the overnight drift and what
    *Lucky Black Cat* reads, and every other way of touching the cat
    stamps it - a pet, the bed, the toy, a can, successful or refused.

    A reaction is not touching the cat. Stamping it would mean a player
    could hold off the drift from their phone without playing, and would
    hand out a holiday achievement to anybody who reacted to a message on
    the right day.
    """
    assert await database.last_cat_interaction(GUILD_A, ALICE) is None

    await craving.judge(GUILD_A, ALICE, MOUSE, TODAY)

    assert await database.last_cat_interaction(GUILD_A, ALICE) is None


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


def _catalogue_rows():
    """The writers' catalogue, straight off disk."""
    import csv

    with io.open(
        content_module.CONTENT_DIR / "emoji-catalogue-v18.csv",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        return list(csv.DictReader(handle))


async def _filed():
    """Every row of the emoji file, as the game loaded it."""
    session_factory = database._require_session()
    async with session_factory() as session:
        return list(await session.scalars(select(database.EmojiGroup)))


async def _one(*, category, type=None, other_than=None):
    """Any emoji filed under this category, and optionally this type.

    Aliases are skipped. The mouse face is filed under Prey/Mammal like
    the mouse it answers for, so a helper reaching for "another mammal"
    could hand back the one guess that wins - which would make the
    near-miss test pass or fail on row order.
    """
    for row in await _filed():
        if row.category != category or row.excluded or row.same_as:
            continue
        if type is not None and row.type != type:
            continue
        if row.emoji != other_than:
            return row.emoji
    raise AssertionError(f"the file has no {category}/{type} to guess with")

