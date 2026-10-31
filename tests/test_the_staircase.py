"""Drop 20: the grand staircase, which the whole server repairs together.

Ninety planks, one per player per day, counted per server. It is the
game's first shared job with a number attached, and nearly everything
here follows from that one sentence.

**Why planks and not people.** It counted distinct players until drop
20, when ten of them finished it and the wait between turns was 48
rolling hours. Ninety at one a day means a server of 27 takes about
three and a half days, and the 18 most active players cannot quietly
finish it on their own in an afternoon.

**Why it stops at 72.** The last fifth of the stairs is out of reach
from the floor. The ladder arrives in drop 30, so drop 20 ships the
stopping point without the thing that passes it: the repair reaches
`stairs_upper` and waits there, on purpose, and the prose says so.

The drop matters in this file, so every test sets it. At drop 20 the
lumber's `stairs_upper` row has a refusal and no success text; the drop
30 row has the ladder's success text, and a test standing on drop 50
would be testing next drop's staircase.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember
from test_loader import a_thing, a_world

import achievements
import bot
import content as content_module
import content_loader
import database
import resolve
import states
import triggers
import world


THIS_DROP = 20

# A phrase out of `stairs.repaired.public`, which is what the room reads
# when the last plank goes in. Not the whole line: it opens with
# `{player}`, and the fake's display names are long numbers.
FINISHED = "The grand staircase is whole again"


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.register_all()
    triggers.forget_arrivals()
    yield
    achievements.clear()


@pytest.fixture(autouse=True)
def forget_admissions():
    bot._ADMITTING.clear()
    yield
    bot._ADMITTING.clear()


@pytest.fixture
async def hall(db):
    """Drop 20, the front door open, Alice and Bob in the Entryway.

    Both have fed the cat. The repair does not require it - a player who
    guesses "lumber" can lay a plank, which drop 20 decided on purpose -
    but the room text does, and a fixture that left them unfed would
    make every description assertion here fail on a condition none of
    these tests is about. `test_feeding` owns that gate.
    """
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    await content_loader.load_content(content_module.load_files())
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, THIS_DROP)
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    for who in (ALICE, BOB):
        await db.start_game(who, GUILD_A, "EN", await resolve.rooms_open_at_launch())
        await db.notice(GUILD_A, who, content_module.FED_THE_CAT)
    return db, guild, halloween, rooms


def thread(hall, room_name):
    _, _, halloween, _ = hall
    return next(t for t in halloween.threads if t.name == room_name)


async def run(hall, command, arg=None, *, who=ALICE):
    _, guild, _, rooms = hall
    interaction = FakeInteraction(
        who, GUILD_A, guild=guild, channel=thread(hall, rooms["EN"])
    )
    args = () if arg is None else (arg,)
    await command.callback(interaction, *args)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


async def plank(hall, who=ALICE) -> str:
    """What the player was told privately, which on a success is nothing.

    A laid plank is posted to the room and sent to nobody - see
    `posted` below. Everything this still returns is a refusal.
    """
    return replies(await run(hall, bot.use, "lumber", who=who))


def posted(hall) -> str:
    """What the Entryway thread has seen.

    The staircase is the game's only public `/use`, and since 30 October
    it is public *only*: the private copy said the same sentence to
    somebody standing in the room reading both.
    """
    return "\n".join(thread(hall, hall[3]["EN"]).posted)


async def a_day_later(db, days=1):
    await db.set_setting(GUILD_A, database.CLOCK_KEY, days)


async def target(db, planks):
    """A smaller staircase, so a test can reach its end in a few calls."""
    await db.set_setting(GUILD_A, world.PLANKS_SETTING, planks)


# --------------------------------------------------------------------------
# The count
# --------------------------------------------------------------------------


async def test_a_plank_is_counted(hall):
    await plank(hall)

    placed, _ = await world.planks(GUILD_A)
    assert placed == 1


async def test_the_count_is_planks_and_not_people(hall):
    """**The change drop 20 made.** Two players, two planks, and the
    count is two either way - so this would pass under the old rule as
    well. What distinguishes them is the next test."""
    await plank(hall)
    await plank(hall, who=BOB)

    placed, _ = await world.planks(GUILD_A)
    assert placed == 2


async def test_the_same_player_on_two_days_counts_twice(hall):
    """Under the old distinct-player rule this stayed at one forever,
    which is what made ten players enough to finish the staircase."""
    db, *_ = hall
    await plank(hall)
    await a_day_later(db)

    await plank(hall)

    placed, _ = await world.planks(GUILD_A)
    assert placed == 2


async def test_the_default_target_is_ninety(hall):
    _, required = await world.planks(GUILD_A)
    assert required == 90


async def test_a_plank_pays_no_relationship(hall):
    """It is work done on the house, not attention paid to the cat.

    Worth pinning because *Are You David?* arrived in the same drop: if
    a plank paid points, a server could hammer its way to a thousand.
    """
    db, *_ = hall
    before = await db.get_relationship(ALICE, GUILD_A)

    await plank(hall)

    assert await db.get_relationship(ALICE, GUILD_A) == before


# --------------------------------------------------------------------------
# One a day
# --------------------------------------------------------------------------


async def test_a_second_plank_the_same_day_is_refused(hall):
    """**The "about" belongs to the token, not to the sentence.**

    `{time}` renders as "about 14 hours" on its own, so the cell that
    wrote its own *about* in front of it read "want about about 14
    hours" for ten days. This assertion was true before and after,
    which is exactly how it got there - a prefix is not a sentence.
    """
    await plank(hall)
    reply = await plank(hall)

    assert "muscles will want about" in reply
    assert "about about" not in reply


async def test_and_does_not_count(hall):
    await plank(hall)
    await plank(hall)

    placed, _ = await world.planks(GUILD_A)
    assert placed == 1


async def test_tomorrow_it_works_again(hall):
    db, *_ = hall
    await plank(hall)
    await a_day_later(db)
    await plank(hall)

    assert posted(hall).count("hammers it into place") == 2


async def test_the_limit_is_per_player(hall):
    """Alice using her turn does not spend Bob's."""
    await plank(hall)

    assert "muscles" not in await plank(hall, who=BOB)


# --------------------------------------------------------------------------
# What the count looks like
# --------------------------------------------------------------------------


async def test_the_use_reports_the_count_on_its_own_line(hall):
    await plank(hall)

    assert "\n1 of 90 repairs done." in posted(hall)


async def test_looking_at_the_lumber_reports_it_too(hall):
    """The open question drop 20 answered: between planks a player had
    no way to see where the work had got to."""
    await plank(hall)

    reply = replies(await run(hall, bot.look, "lumber"))

    assert "\n1 of 90 repairs done." in reply


async def test_looking_at_the_staircase_reports_it_too(hall):
    await plank(hall)

    reply = replies(await run(hall, bot.look, "staircase"))

    assert "\n1 of 90 repairs done." in reply


async def test_a_look_that_never_asked_for_the_count_is_untouched(hall):
    """The filling is driven by the text asking for it, so everything
    else in the house costs one substring test and no queries."""
    reply = replies(await run(hall, bot.look, "mirror"))

    assert "repairs done" not in reply
    assert "{n}" not in reply


async def test_no_token_survives_into_a_reply(hall):
    """The failure this whole change existed to fix: before it, the
    lumber's look showed players a literal `{n} of {total}`."""
    await plank(hall)

    for subject in ("lumber", "staircase"):
        assert "{" not in replies(await run(hall, bot.look, subject))


# --------------------------------------------------------------------------
# The top steps
# --------------------------------------------------------------------------


async def test_the_upper_state_arrives_at_four_fifths(hall):
    """Five planks, so the threshold is four. Rounded down, which is
    what makes a QA server reach the same moment as a real one."""
    db, *_ = hall
    await target(db, 5)

    for day in range(3):
        await a_day_later(db, day)
        await plank(hall)
        assert not await states.has(GUILD_A, ALICE, world.STAIRS_UPPER), day

    await a_day_later(db, 3)
    await plank(hall)

    assert await states.has(GUILD_A, ALICE, world.STAIRS_UPPER)


async def test_and_the_staircase_is_not_repaired_by_it(hall):
    db, *_ = hall
    await target(db, 5)
    for day in range(4):
        await a_day_later(db, day)
        await plank(hall)

    assert not await states.has(GUILD_A, ALICE, world.STAIRS_REPAIRED)


async def test_the_next_plank_is_refused_for_the_steps(hall):
    db, *_ = hall
    await target(db, 5)
    for day in range(4):
        await a_day_later(db, day)
        await plank(hall)
    await a_day_later(db, 5)

    assert "too high to fix without something to stand on" in await plank(hall)


async def test_the_count_stops_there(hall):
    db, *_ = hall
    await target(db, 5)
    for day in range(4):
        await a_day_later(db, day)
        await plank(hall)
    await a_day_later(db, 5)
    await plank(hall)

    placed, _ = await world.planks(GUILD_A)
    assert placed == 4


async def test_the_steps_are_the_reason_even_for_a_player_who_already_laid_one(hall):
    """**The ordering this drop had to fix.**

    A player who has already used their turn today, in `stairs_upper`,
    was told their muscles needed a rest - which is a true sentence
    about them and the wrong answer about the staircase. "Not at all"
    outranks "not again yet", because only one of them is about this
    player, and a server reading the cooldown line would conclude the
    repair was still going.
    """
    db, *_ = hall
    await target(db, 5)
    for day in range(3):
        await a_day_later(db, day)
        await plank(hall)
    await a_day_later(db, 3)
    await plank(hall, who=BOB)  # the fourth plank, which sets the state
    assert await states.has(GUILD_A, ALICE, world.STAIRS_UPPER)

    # Alice already laid hers today, before the state changed.
    reply = await plank(hall)

    assert "too high to fix" in reply
    assert "muscles" not in reply


async def test_the_room_says_the_stairs_are_mostly_mended(hall):
    db, *_ = hall
    await target(db, 5)
    for day in range(4):
        await a_day_later(db, day)
        await plank(hall)

    reply = replies(await run(hall, bot.look))

    assert "mended most of the way up" in reply
    assert "is a ruin" not in reply


async def test_going_up_runs_out_of_steps(hall):
    db, *_ = hall
    await target(db, 5)
    for day in range(4):
        await a_day_later(db, day)
        await plank(hall)

    reply = replies(await run(hall, bot.go, "staircase"))

    assert "before the steps run out" in reply


async def test_drop_20_cannot_finish_the_staircase(hall):
    """The drop's own limit, stated as a test. Four fifths of the work
    is all that is reachable, so no amount of hammering gets there."""
    db, *_ = hall
    await target(db, 5)
    for day in range(12):
        await a_day_later(db, day)
        await plank(hall)
        await plank(hall, who=BOB)

    placed, _ = await world.planks(GUILD_A)
    assert placed == 4
    assert not await states.has(GUILD_A, ALICE, world.STAIRS_REPAIRED)


# --------------------------------------------------------------------------
# Public, and public only
# --------------------------------------------------------------------------


async def test_a_laid_plank_is_posted_and_not_sent(hall):
    """**Both halves of the change in one assertion.** The line goes to
    the room, and the player who typed `/use lumber` is told nothing -
    they are standing in the room, so the private copy was the same
    sentence twice in two messages.
    """
    said = await plank(hall)

    assert "hammers it into place" in posted(hall)
    assert said == ""


async def test_the_line_names_the_player(hall):
    """It read "you haul a plank over to the staircase", posted under a
    mention - so everybody else in the Entryway read a sentence
    addressed to them about a plank they had not laid."""
    await plank(hall)

    assert posted(hall).startswith(
        f"{FakeMember(ALICE).display_name} hauls a plank"
    )
    assert "You haul" not in posted(hall)


async def test_the_post_is_not_prefixed_with_a_mention(hall):
    """The line says who. A mention in front of it read "@Alice Alice
    hauls a plank", and pinged the room for each of ninety boards."""
    await plank(hall)

    assert "<@" not in posted(hall)


async def test_a_refused_plank_is_still_private(hall):
    """Only the success is collective. A player inside their own daily
    cooldown has told the room nothing, and the room should not hear
    about it."""
    await plank(hall)
    before = posted(hall)

    assert "muscles will want" in await plank(hall)
    assert posted(hall) == before


async def test_the_finish_line_goes_to_the_room(hall):
    """The most collective moment the game has. `effect.announce` rides
    the same line, so it is posted now rather than read by whoever
    happened to lay the last board.

    **A one-plank target is what makes this reachable.**
    `reachable_from_the_floor(1)` is zero, so the first plank crosses
    both thresholds at once. That is also why the ladder gate drop 30
    added does not stop it: the gate reads `stairs_upper` as it stood
    *before* this plank, and the plank that crosses into it is by
    definition one somebody could still reach from the floor.

    **The line is the writers' since 30 October.** It was a sentence
    typed into `world._place_a_plank` while `stairs.repaired.public`
    sat in the deck unread - the shipping box's failure in another
    costume - so the assertion moved to the row that was always
    supposed to carry it.
    """
    db, *_ = hall
    await target(db, 1)

    await plank(hall)

    assert FINISHED in posted(hall)


async def test_and_the_next_plank_does_not_say_so_again(hall):
    db, *_ = hall
    await target(db, 1)
    await plank(hall)

    await plank(hall, who=BOB)

    assert posted(hall).count(FINISHED) == 1


# **The `stairs_upper` cell has no runtime test here, and had none before
# this change either.** It is the drop 30 row, laid from the ladder, and
# this fixture is drop 20. `_check_a_public_use_names_the_player` holds
# it to naming the player whatever its state, which is the part this
# change could have broken.


def a_lumber_world(use_text):
    world = a_world(a_thing("lumber", type="object"))
    for row in world.thing_text:
        if row.entity_id == "lumber":
            row.text["use"] = use_text
    return world


def test_a_lumber_use_text_has_to_name_the_player():
    """**The guarantee that would otherwise lapse in silence.**

    Nothing in the files says this `use` is posted rather than sent, so
    a writer rewriting the cell in the second person - which is correct
    for every other `use` in the game - would put "you haul a plank"
    back in front of a room full of people, and nothing would complain.
    """
    problems = content_module.validate(
        a_lumber_world("You haul a plank over and hammer it in.")
    )

    assert any("lumber" in problem for problem in problems)


def test_and_a_third_person_one_is_fine():
    problems = content_module.validate(
        a_lumber_world("{player} hauls a plank over and hammers it in.")
    )

    assert not any("lumber" in problem for problem in problems)
