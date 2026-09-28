"""`/stats`: what a player has earned, and nothing about what they have not.

Held back from 2c deliberately so it could be built against real achievement
data rather than a stub. Two rules do most of the work here, and both are
about what the command withholds:

- **it is ephemeral, always**, because it carries the unlock descriptions -
  the spoilers the public announcement is kept short to avoid
- **it says nothing about unearned achievements** - no count out of
  thirty-five, no locked rows, no progress bars. A secret achievement's
  existence is revealed by somebody earning it, not by this command
"""

import pytest

from conftest import ALICE, BOB, GUILD_A, GUILD_B
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import craving
import database
import triggers

from test_achievements import an_achievement
from test_loader import a_thing, a_world


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


def fields(interaction) -> dict[str, str]:
    return {f.name: f.value for f in interaction.embed.fields}


# --------------------------------------------------------------------------
# The empty state, which a player sees on day one
# --------------------------------------------------------------------------


async def test_a_new_player_gets_an_invitation_not_an_error(playing, halloween):
    interaction = await ask(guild=halloween)

    assert "Nothing here yet" in body(interaction)


async def test_the_counts_show_even_with_nothing_earned(playing, halloween):
    """Pet count and craving tally are the two things a day-one player has,
    so leaving them out would make the empty state emptier than it is."""
    interaction = await ask(guild=halloween)

    assert fields(interaction) == {
        "Pets": "0",
        "Relationship": str(database.RELATIONSHIP_START),
        "Cravings found": "0",
    }


async def test_the_empty_state_names_no_achievement(playing, halloween):
    """Not even a count out of thirty-five: that would tell a new player
    exactly how much they have not found."""
    interaction = await ask(guild=halloween)

    assert "35" not in body(interaction)
    assert "Gourd Job" not in body(interaction)


# --------------------------------------------------------------------------
# Ephemeral, always
# --------------------------------------------------------------------------


async def test_it_is_ephemeral(playing, halloween):
    interaction = await ask(guild=halloween)

    assert interaction.was_private


async def test_it_is_ephemeral_even_when_empty(playing, halloween):
    """The deferral decides it, before anything is known about the player."""
    interaction = await ask(guild=halloween)

    assert interaction.defer_kwargs.get("ephemeral") is True


async def test_it_is_an_embed_not_a_message(playing, halloween):
    """Thirty-five names plus thirty-five unlock lines passes a message's
    2,000-character cap, and it would break for exactly the players who
    played the most."""
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")
    interaction = await ask(guild=halloween)

    assert interaction.embed is not None


# --------------------------------------------------------------------------
# What it shows
# --------------------------------------------------------------------------


async def test_an_earned_achievement_shows_its_name_and_unlock(playing, halloween):
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")

    text = body(await ask(guild=halloween))
    assert "Gourd Job" in text
    assert "Carved a pumpkin in the courtyard" in text


async def test_an_unearned_achievement_is_absent(playing, halloween):
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")

    text = body(await ask(guild=halloween))
    assert "Say Cheese" not in text


async def test_the_kinds_are_grouped_and_labelled(playing, halloween):
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")
    await database.award_player_achievement(GUILD_A, ALICE, "say_cheese")
    await database.award_server_achievement(GUILD_A, "making_a_mess")

    text = body(await ask(guild=halloween))
    assert text.index("**Achievements**") < text.index("**Secret achievements**")
    assert text.index("**Secret achievements**") < text.index("**Server achievements**")


async def test_a_kind_with_nothing_earned_gets_no_heading(playing, halloween):
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")

    text = body(await ask(guild=halloween))
    assert "Secret achievements" not in text


async def test_within_a_kind_they_follow_sort_order(playing, halloween):
    """The column exists for this, and row order in the file is not it."""
    parsed = a_world(a_thing("candle"))
    parsed.achievements = [
        an_achievement("last_one", name="Zebra", sort_order=90),
        an_achievement("first_one", name="Aardvark", sort_order=10),
    ]
    await content_loader.load_content(parsed, fresh=True)
    for key in ("last_one", "first_one"):
        await database.award_player_achievement(GUILD_A, ALICE, key)

    text = body(await ask(guild=halloween))
    assert text.index("Aardvark") < text.index("Zebra")


async def test_the_craving_tally_is_here(playing, halloween):
    """It belongs here so the daily game outlives the achievement that
    rewards it once."""
    await craving.credit(GUILD_A, ALICE, database.pacific_today())

    assert fields(await ask(guild=halloween))["Cravings found"] == "1"


# --------------------------------------------------------------------------
# Group achievements
# --------------------------------------------------------------------------


async def test_a_group_achievement_shows_for_a_member_who_was_not_there(
    playing, halloween
):
    """Nobody earned it, so everybody has it."""
    await database.award_server_achievement(GUILD_A, "making_a_mess")

    assert "Making a Mess" in body(await ask(BOB, guild=halloween))


async def test_a_group_achievement_names_no_earner(playing, halloween):
    await database.award_server_achievement(GUILD_A, "making_a_mess")

    text = body(await ask(guild=halloween))
    assert "Making a Mess" in text
    assert "earned by" not in text.lower()


async def test_a_group_achievement_is_marked_as_a_server_one(playing, halloween):
    await database.award_server_achievement(GUILD_A, "making_a_mess")

    assert "**Server achievements**" in body(await ask(guild=halloween))


async def test_another_server_s_group_achievement_does_not_show(playing, db, halloween):
    await db.ensure_user_exists(ALICE, GUILD_B)
    await database.award_server_achievement(GUILD_B, "making_a_mess")

    assert "Making a Mess" not in body(await ask(guild=halloween))


# --------------------------------------------------------------------------
# Your own stats only
# --------------------------------------------------------------------------


async def test_it_shows_only_the_asking_player(playing, halloween):
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")

    assert "Gourd Job" not in body(await ask(BOB, guild=halloween))


async def test_the_same_player_in_another_server_starts_over(playing, db, halloween):
    await db.ensure_user_exists(ALICE, GUILD_B)
    await content_loader.load_content(content_module.load_files())
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")

    other = FakeGuild(GUILD_B, channels=[], members=[FakeMember(ALICE)])
    assert "Nothing here yet" in body(await ask(guild=other, guild_id=GUILD_B))


# --------------------------------------------------------------------------
# Drop resolution, and the long case
# --------------------------------------------------------------------------


async def test_an_achievement_from_an_unarrived_drop_is_not_listed(playing, db, halloween):
    """It does not exist on this server yet. Awarding one is impossible, but
    a row left over from a `--fresh` in the wrong order must not render."""
    parsed = a_world(a_thing("candle"))
    parsed.achievements = [an_achievement("gourd_job", since_drop=9)]
    await content_loader.load_content(parsed, fresh=True)
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")

    assert "Nothing here yet" in body(await ask(guild=halloween))


async def test_a_completionist_does_not_break_the_command(playing, halloween):
    """All thirty-five at once, which is what the embed limit is for."""
    triggers.register_all()
    for key in achievements.registered_ids():
        await database.award_player_achievement(GUILD_A, ALICE, key)

    text = body(await ask(guild=halloween))
    assert len(text) <= bot.EMBED_LIMIT
    assert "Not-So-Picky Eater" in text


async def test_overflow_says_how_much_was_left_out(playing, halloween):
    """Same shape `Also here:` uses: a player who has earned enough to
    overflow is told, not silently shown less."""
    parsed = a_world(a_thing("candle"))
    parsed.achievements = [
        an_achievement(f"long_{n}", name=f"Name {n}", unlock="x" * 300, sort_order=n)
        for n in range(30)
    ]
    await content_loader.load_content(parsed, fresh=True)
    for n in range(30):
        await database.award_player_achievement(GUILD_A, ALICE, f"long_{n}")

    text = body(await ask(guild=halloween))
    assert len(text) <= bot.EMBED_LIMIT
    assert "more." in text


async def test_overflow_keeps_the_earliest_rather_than_truncating_mid_line(
    playing, halloween
):
    parsed = a_world(a_thing("candle"))
    parsed.achievements = [
        an_achievement(f"long_{n}", name=f"Name {n}", unlock="x" * 300, sort_order=n)
        for n in range(30)
    ]
    await content_loader.load_content(parsed, fresh=True)
    for n in range(30):
        await database.award_player_achievement(GUILD_A, ALICE, f"long_{n}")

    text = body(await ask(guild=halloween))
    assert "**Name 0**" in text
    assert text.rstrip().endswith("more.")
