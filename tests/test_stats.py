"""`/stats`: three parts, in order, and nothing about what has not happened.

Held back from 2c deliberately so it could be built against real
achievement data rather than a stub, and rebuilt in V3 around what a
player actually opens it for.

Two rules do most of the work, and both are about what it withholds:

- **it is ephemeral, always**, because it carries the unlock descriptions
  - the spoilers the public announcement is kept short to avoid
- **it says nothing about unearned achievements** - no count out of
  forty-two, no locked rows, no progress bars. A secret achievement's
  existence is revealed by somebody earning it, not by this command

A quest is the one exception, and only because a quest is the game
telling a player what to do next rather than what they have missed.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A, GUILD_B, HOUSE_DROP
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
import resolve

from test_achievements import an_achievement
from test_loader import a_world

ROOT = "making_first_contact"


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    yield
    achievements.clear()


@pytest.fixture
def halloween():
    return FakeGuild(
        GUILD_A,
        channels=[FakeChannel(name="halloween")],
        members=[FakeMember(ALICE), FakeMember(BOB)],
    )


@pytest.fixture
async def playing(db, halloween):
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
        await db.start_game(who, GUILD_A, "EN", ["EN"])
    await content_loader.load_content(content_module.load_files())
    return db


async def ask(user_id=ALICE, guild=None, guild_id=GUILD_A):
    interaction = FakeInteraction(user_id, guild_id, guild=guild)
    await bot.stats.callback(interaction)
    return interaction


def body(interaction) -> str:
    return interaction.embed.description


async def quest_world(db, *achievement_rows, drop=HOUSE_DROP):
    """A world holding exactly these achievements, at a known drop."""
    parsed = a_world()
    parsed.achievements = list(achievement_rows)
    # The fixture loaded the real house first, so this one drops things
    # that world state still points at. Irrelevant here and noisy to
    # unpick per test.
    await content_loader.load_content(parsed, allow_orphans=True)
    await database.set_setting(GUILD_A, resolve.DROP_KEY, drop)
    return parsed


def a_quest(achievement_id, prompt="Do the thing", requires=ROOT, **kwargs):
    return an_achievement(
        achievement_id,
        kind="public",
        offered=True,
        prompt=prompt,
        requires=requires,
        **kwargs,
    )


# --------------------------------------------------------------------------
# The relationship
# --------------------------------------------------------------------------


async def test_the_figure_is_shown_unrounded_and_labelled(playing, halloween):
    """A bare integer at the top of an embed does not say what it
    counts."""
    await playing.adjust_relationship(ALICE, GUILD_A, 137)

    assert "Cat relationship strength: 137" in body(await ask(guild=halloween))


async def test_the_four_lines_read_as_the_writers_wrote_them(playing, halloween):
    """The status line sits between the prose and the count, which is
    where the spec puts it: directly under the description of the
    relationship.

    This fixture is in the house, so the cat reads as hungry - there is
    food in the game from drop 3 and nobody has fed her.
    """
    await playing.ensure_user_exists(ALICE, GUILD_A)
    await playing.set_relationship(GUILD_A, ALICE, -5)
    await playing.increment_pet_count(ALICE, GUILD_A)

    reply = body(await ask(guild=halloween))

    assert reply.startswith(
        "Cat relationship strength: -5\n"
        "The cat is still trying to decide how she feels about you.\n"
        "Right now, the cat is watching you expectantly with hunger in her eyes.\n"
        "Total pets: 1"
    )


# The writers' nine, as (lowest score in the band, highest, phrase).
BANDS = [
    (-100, -31, "thoroughly unimpressed"),
    (-30, -6, "mildly irritated"),
    (-5, 5, "still trying to decide"),
    (6, 50, "warming up to you"),
    (51, 100, "decided you may stay"),
    (101, 150, "genuinely likes you"),
    (151, 200, "claimed you as her human"),
    (201, 300, "adores you"),
    (301, 9999, "follow you anywhere"),
]


@pytest.mark.parametrize("low, high, phrase", BANDS, ids=[b[2] for b in BANDS])
async def test_both_edges_of_every_band(playing, halloween, low, high, phrase):
    """Both ends of each, because an off-by-one between two bands reads
    as a plausible sentence and nothing else would catch it."""
    for score in (low, high):
        await playing.set_relationship(GUILD_A, ALICE, score)

        assert phrase in body(await ask(guild=halloween)), score


async def test_the_bands_leave_no_gap(playing, halloween):
    """Every score from the floor to well past the top lands in one.

    The meter has no ceiling, so the top band must have none either -
    *Favorite Human* is at 250 and nothing stops a player going past
    it."""
    seen = set()
    for score in list(range(-100, 320)) + [1000]:
        await playing.set_relationship(GUILD_A, ALICE, score)
        reply = body(await ask(guild=halloween))
        matched = [p for _, _, p in BANDS if p in reply]
        assert len(matched) == 1, (score, matched)
        seen.add(matched[0])

    assert len(seen) == len(BANDS)


async def test_zero_is_not_a_band_of_its_own(playing, halloween):
    """It used to be, saying the cat did not care. It now sits inside
    *still trying to decide*, which is a better reading of where every
    player starts and where the drift returns them."""
    await playing.set_relationship(GUILD_A, ALICE, 0)

    assert "still trying to decide" in body(await ask(guild=halloween))


async def test_a_new_player_reads_as_zero_not_as_broken(playing, halloween):
    reply = body(await ask(guild=halloween))

    assert reply.startswith("Cat relationship strength: 0")
    assert "still trying to decide" in reply


async def test_the_pet_count_is_here_because_there_is_nowhere_else(playing, halloween):
    """`/pet` stopped reporting it in 2f so that two hundred would be a
    surprise rather than a countdown, and moved it here. Section 7 lists
    three parts and does not mention it; dropping it would have deleted
    it from the game rather than moved it, and left a player chasing
    *Making Friends* with no way to know where they are."""
    for _ in range(3):
        await playing.increment_pet_count(ALICE, GUILD_A)

    assert "Total pets: 3" in body(await ask(guild=halloween))


async def test_it_reads_zero_on_day_one(playing, halloween):
    assert "Total pets: 0" in body(await ask(guild=halloween))


async def test_the_count_is_per_server(playing, db, halloween):
    await db.ensure_user_exists(ALICE, GUILD_B)
    await db.increment_pet_count(ALICE, GUILD_B)

    assert "Total pets: 0" in body(await ask(guild=halloween))


# --------------------------------------------------------------------------
# Open quests
# --------------------------------------------------------------------------


async def test_the_section_is_absent_when_nothing_is_open(playing, halloween):
    """With three public quests in the whole plan a player will spend
    long stretches with none, and a standing "No open quests" reads as
    broken rather than as waiting."""
    assert "Open Quests" not in body(await ask(guild=halloween))


async def test_the_parked_empty_line_is_never_reached(playing, halloween):
    assert "No open quests" not in body(await ask(guild=halloween))


async def test_a_quest_appears_once_its_prerequisite_is_held(playing, halloween):
    await quest_world(
        playing, an_achievement(ROOT), a_quest("fluffed", prompt="Fluff the bed")
    )
    assert "Open Quests" not in body(await ask(guild=halloween))

    await playing.award_player_achievement(GUILD_A, ALICE, ROOT)

    reply = body(await ask(guild=halloween))
    assert "Open Quests" in reply
    assert "Fluff the bed" in reply


async def test_an_earned_quest_stops_being_open(playing, halloween):
    await quest_world(playing, an_achievement(ROOT), a_quest("fluffed"))
    await playing.award_player_achievement(GUILD_A, ALICE, ROOT)
    await playing.award_player_achievement(GUILD_A, ALICE, "fluffed")

    assert "Open Quests" not in body(await ask(guild=halloween))


async def test_a_quest_from_a_later_drop_is_not_offered(playing, halloween):
    await quest_world(
        playing,
        an_achievement(ROOT),
        a_quest("later", since_drop=2),
        drop=1,
    )
    await playing.award_player_achievement(GUILD_A, ALICE, ROOT)

    assert "Open Quests" not in body(await ask(guild=halloween))


async def test_a_secret_achievement_is_never_a_quest(playing, halloween):
    """`offered` is what makes a quest, not `kind`."""
    await quest_world(
        playing, an_achievement(ROOT), an_achievement("hidden", kind="secret")
    )
    await playing.award_player_achievement(GUILD_A, ALICE, ROOT)

    assert "Open Quests" not in body(await ask(guild=halloween))


async def test_quests_are_newest_first(playing, halloween):
    """A player opens `/stats` just after being told a new quest is
    available, and should not have to read to the bottom for it."""
    await quest_world(
        playing,
        an_achievement(ROOT),
        a_quest("older", prompt="The older one"),
        a_quest("newer", prompt="The newer one"),
    )
    await playing.award_player_achievement(GUILD_A, ALICE, ROOT)
    await database.notice(GUILD_A, ALICE, "older")

    reply = body(await ask(guild=halloween))

    assert reply.index("The newer one") < reply.index("The older one")


async def test_opening_stats_marks_every_visible_quest_seen(playing, halloween):
    """Which is what stops the notice announcing a quest the player is
    looking at."""
    await quest_world(playing, an_achievement(ROOT), a_quest("fluffed"))
    await playing.award_player_achievement(GUILD_A, ALICE, ROOT)

    await ask(guild=halloween)

    assert await database.has_been_told(GUILD_A, ALICE, "fluffed")


async def test_opening_stats_sets_the_flag_the_notice_reads(playing, halloween):
    assert not await database.has_been_told(GUILD_A, ALICE, bot.OPENED_STATS)

    await ask(guild=halloween)

    assert await database.has_been_told(GUILD_A, ALICE, bot.OPENED_STATS)


# --------------------------------------------------------------------------
# Completed achievements
# --------------------------------------------------------------------------


async def test_the_header_is_there_with_nothing_earned(playing, halloween):
    """Its empty line is the only instruction anywhere in the game. With
    no `/help` and no welcome text, hiding it would leave a first
    `/stats` showing nothing but a number."""
    reply = body(await ask(guild=halloween))

    assert "Completed Achievements" in reply
    assert "No completed achievements. Try /pet." in reply


async def test_an_earned_achievement_shows_its_name_and_unlock(playing, halloween):
    await quest_world(
        playing, an_achievement("gourd_job", name="Gourd Job", unlock="Carved it.")
    )
    await playing.award_player_achievement(GUILD_A, ALICE, "gourd_job")

    reply = body(await ask(guild=halloween))

    assert "Gourd Job" in reply and "Carved it." in reply


async def test_an_unearned_achievement_is_absent(playing, halloween):
    await quest_world(playing, an_achievement("gourd_job", name="Gourd Job"))

    assert "Gourd Job" not in body(await ask(guild=halloween))


async def test_newest_first_rather_than_sort_order(playing, halloween):
    """`sort_order` no longer drives this. A player opens `/stats`
    because something just happened, and that should be at the top."""
    await quest_world(
        playing,
        an_achievement("first_one", name="Aardvark", sort_order=10),
        an_achievement("last_one", name="Zebra", sort_order=999),
    )
    await playing.award_player_achievement(GUILD_A, ALICE, "first_one")
    await playing.award_player_achievement(GUILD_A, ALICE, "last_one")

    reply = body(await ask(guild=halloween))

    assert reply.index("Zebra") < reply.index("Aardvark")


async def test_two_from_one_action_render_in_a_stable_order(playing, halloween):
    """They share a timestamp, so without a tiebreak the same list could
    render two ways."""
    await quest_world(
        playing,
        an_achievement("aaa", name="Aaa"),
        an_achievement("zzz", name="Zzz"),
    )
    for key in ("aaa", "zzz"):
        await playing.award_player_achievement(GUILD_A, ALICE, key)

    first = body(await ask(guild=halloween))
    second = body(await ask(guild=halloween))

    assert first == second


# --------------------------------------------------------------------------
# Group achievements, and whose stats these are
# --------------------------------------------------------------------------


async def test_a_group_achievement_shows_for_a_member_who_was_not_there(
    playing, halloween
):
    await quest_world(
        playing, an_achievement("making_a_mess", kind="group", name="Making a Mess")
    )
    await playing.award_server_achievement(GUILD_A, "making_a_mess")

    assert "Making a Mess" in body(await ask(BOB, guild=halloween))


async def test_another_servers_group_achievement_does_not_show(playing, db, halloween):
    await quest_world(playing, an_achievement("making_a_mess", name="Making a Mess"))
    await db.award_server_achievement(GUILD_B, "making_a_mess")

    assert "Making a Mess" not in body(await ask(guild=halloween))


async def test_it_shows_only_the_asking_player(playing, halloween):
    await quest_world(playing, an_achievement("gourd_job", name="Gourd Job"))
    await playing.award_player_achievement(GUILD_A, ALICE, "gourd_job")

    assert "Gourd Job" not in body(await ask(BOB, guild=halloween))


# --------------------------------------------------------------------------
# The shape of the reply
# --------------------------------------------------------------------------


async def test_it_is_ephemeral(playing, halloween):
    assert (await ask(guild=halloween)).was_private


async def test_it_is_an_embed_not_a_message(playing, halloween):
    interaction = await ask(guild=halloween)

    assert interaction.embed is not None
    assert interaction.sent[-1][0] is None


async def test_the_three_parts_come_in_order(playing, halloween):
    await quest_world(
        playing,
        an_achievement(ROOT, name="First Contact"),
        a_quest("fluffed", prompt="Fluff the bed"),
    )
    await playing.award_player_achievement(GUILD_A, ALICE, ROOT)
    await playing.adjust_relationship(ALICE, GUILD_A, 60)

    reply = body(await ask(guild=halloween))

    assert reply.index("60") < reply.index("Open Quests")
    assert reply.index("Open Quests") < reply.index("Completed Achievements")


async def test_a_completionist_does_not_break_the_command(playing, halloween):
    """Forty-two unlock descriptions is more than an embed holds."""
    rows = [an_achievement(f"a{n}", name=f"Name {n}", unlock="x" * 200) for n in range(40)]
    await quest_world(playing, *rows)
    for row in rows:
        await playing.award_player_achievement(GUILD_A, ALICE, row.achievement_id)

    reply = body(await ask(guild=halloween))

    assert len(reply) <= bot.EMBED_LIMIT
