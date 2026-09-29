"""Getting into the house, and the clock that starts when somebody does.

Until 2f nothing put a person in the first thread. `/enter-entryway` existed
and no document said what it did; `/enter` is that command renamed, specified,
and given the repair case it needed.

The edge worth naming: **a player row is not the same as having been
inside.** `/pet` creates one for anybody who pets the cat in the channel, so a
member can hold a relationship score and have no room at all. The repair
branch has nowhere to send them, so they take the first-time path.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember, a_room_thread

import bot
import content as content_module
import content_loader
import database
import resolve
import restocking
import states


@pytest.fixture
async def built(db):
    """The house built, and nobody inside it yet."""
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    await content_loader.load_content(content_module.load_files())
    halloween.add_active(*[name for _, name in await resolve.all_rooms()])
    return db, guild, halloween


async def enter(built, who=ALICE, channel=None):
    _, guild, halloween = built
    interaction = FakeInteraction(
        who, GUILD_A, guild=guild, channel=halloween if channel is None else channel
    )
    await bot.enter.callback(interaction)
    return interaction


def thread_named(built, name):
    _, _, halloween = built
    return next(t for t in halloween.threads if t.name == name)


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


# --------------------------------------------------------------------------
# The command is one command
# --------------------------------------------------------------------------


def test_the_command_is_called_enter():
    assert bot.enter.name == "enter"


def test_the_old_name_is_gone():
    """A rename, not a second door in. Two commands that both enrol a player
    is how one of them quietly stops being maintained."""
    assert {c.name for c in bot.bot.tree.get_commands()} >= {"enter"}
    assert "enter-entryway" not in {c.name for c in bot.bot.tree.get_commands()}


# --------------------------------------------------------------------------
# A member who has never been inside
# --------------------------------------------------------------------------


async def test_a_new_member_lands_in_the_entryway(built):
    db, *_ = built

    await enter(built)

    assert (await db.get_game_state(ALICE, GUILD_A)).current_room == "EN"


async def test_they_are_added_to_the_thread_and_shown_the_room(built):
    await enter(built)

    entryway = thread_named(built, "Entryway")
    assert ALICE in entryway.added_users
    assert any("Entryway" in (line or "") or "coat rack" in (line or "")
               for line in entryway.posted)


async def test_the_reply_points_at_the_thread(built):
    interaction = await enter(built)

    assert thread_named(built, "Entryway").mention in replies(interaction)
    assert interaction.was_private


async def test_entering_announces_in_the_channel(built):
    _, _, halloween = built

    await enter(built)

    assert any("discovered a house" in line for line in halloween.posted)


async def test_the_announcement_pings_nobody(built):
    """Display name as plain text, so a name containing something
    mention-shaped cannot turn into a ping."""
    _, _, halloween = built

    await enter(built)

    assert f"<@{ALICE}>" not in " ".join(halloween.posted)


# --------------------------------------------------------------------------
# The tutorial
# --------------------------------------------------------------------------


async def test_the_tutorial_fires_on_arrival(built):
    await enter(built)

    posted = " ".join(thread_named(built, "Entryway").posted)
    assert "/look coat rack" in posted
    assert "/take cat food" in posted
    assert "/use wide doorway" in posted


async def test_the_tutorial_fires_once_and_never_again(built):
    await enter(built)
    before = list(thread_named(built, "Entryway").posted)

    await enter(built)

    new = thread_named(built, "Entryway").posted[len(before):]
    assert not any("/look coat rack" in line for line in new)


async def test_the_tutorial_flag_is_stored(built):
    await enter(built)

    assert await states.has(GUILD_A, ALICE, "tutorial_seen")


async def test_the_tutorial_does_not_teach_pet(built):
    """The public line a pet posts introduces that command by itself, and a
    fourth bullet is a bullet nobody reads."""
    await enter(built)

    posted = " ".join(thread_named(built, "Entryway").posted)
    assert "/pet" not in posted


@pytest.mark.parametrize(
    "verb, example",
    [("look", "coat rack"), ("take", "cat food"), ("use", "wide doorway")],
)
async def test_every_tutorial_example_works_on_day_one(built, verb, example):
    """Run, not assumed. An example that refuses on the first morning is
    worse than no example."""
    db, guild, _ = built
    await enter(built)
    interaction = FakeInteraction(
        ALICE, GUILD_A, guild=guild, channel=a_room_thread("Entryway")
    )

    await getattr(bot, verb).callback(interaction, example)

    reply = replies(interaction)
    for refusal in ("don't see", "Whatever that is", "Nothing happens",
                    "can't be taken", "can't be used", "not much to look at"):
        assert refusal not in reply, reply


# --------------------------------------------------------------------------
# A player who is already inside
# --------------------------------------------------------------------------


async def test_a_returning_player_goes_back_to_their_own_room(built):
    """Not the Entryway. Somebody leaves a thread by hand and needs a way
    back, and this is cheaper than an admin command."""
    db, *_ = built
    await enter(built)
    await db.update_current_room(ALICE, GUILD_A, "KI")

    await enter(built)

    assert (await db.get_game_state(ALICE, GUILD_A)).current_room == "KI"
    assert ALICE in thread_named(built, "Kitchen").added_users


async def test_a_returning_player_is_told_where_they_are(built):
    db, *_ = built
    await enter(built)
    await db.update_current_room(ALICE, GUILD_A, "KI")

    interaction = await enter(built)

    assert "Kitchen" in replies(interaction)


async def test_returning_does_not_announce_again(built):
    _, _, halloween = built
    await enter(built)
    before = len(halloween.posted)

    await enter(built)

    assert len(halloween.posted) == before


# --------------------------------------------------------------------------
# The edge: a row from petting, and no room
# --------------------------------------------------------------------------


async def test_petting_in_the_channel_creates_a_row_with_no_room(built):
    """v1 behaviour, unchanged, and the reason the repair branch cannot just
    read the row."""
    db, guild, halloween = built
    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)

    await bot.pet.callback(interaction)

    assert await db.get_pet_count(ALICE, GUILD_A) == 1
    assert await db.get_game_state(ALICE, GUILD_A) is None


async def test_that_player_takes_the_first_time_path(built):
    db, guild, halloween = built
    await bot.pet.callback(
        FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    )

    await enter(built)

    assert (await db.get_game_state(ALICE, GUILD_A)).current_room == "EN"
    assert await states.has(GUILD_A, ALICE, "tutorial_seen")


async def test_that_player_keeps_the_relationship_they_built(built):
    db, guild, halloween = built
    await bot.pet.callback(
        FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    )
    before = await db.get_relationship(ALICE, GUILD_A)

    await enter(built)

    assert await db.get_relationship(ALICE, GUILD_A) == before


# --------------------------------------------------------------------------
# The two refusals
# --------------------------------------------------------------------------


async def test_entering_from_the_wrong_channel_points_at_the_right_one(built):
    from fake_discord import somewhere_else

    _, _, halloween = built
    interaction = await enter(built, channel=somewhere_else("general"))

    assert halloween.mention in replies(interaction)
    assert interaction.was_private


async def test_the_wrong_channel_enrols_nobody(built):
    from fake_discord import somewhere_else

    db, *_ = built
    await enter(built, channel=somewhere_else("general"))

    assert await db.get_game_state(ALICE, GUILD_A) is None


async def test_entering_before_the_house_is_built_refuses_cleanly(db):
    """Refuses, rather than erroring or enrolling somebody into a room with
    no thread."""
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(GUILD_A, channels=[halloween], members=[FakeMember(ALICE)])
    await content_loader.load_content(content_module.load_files())
    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)

    await bot.enter.callback(interaction)

    assert "hasn't been built" in replies(interaction)
    assert await db.get_game_state(ALICE, GUILD_A) is None


# --------------------------------------------------------------------------
# Day one
# --------------------------------------------------------------------------


async def test_building_the_house_does_not_start_the_clock(built):
    """An admin can initialize on 29 September and open on 1 October."""
    assert await restocking.initialized_on(GUILD_A) is None


async def test_the_first_entry_starts_the_clock(built):
    await enter(built)

    assert await restocking.initialized_on(GUILD_A) == database.pacific_today()


async def test_the_second_entry_does_not_move_it(built):
    """Whoever is first decides the calendar, and nobody after them can
    change it."""
    await enter(built)
    day_one = await restocking.initialized_on(GUILD_A)

    await enter(built, who=BOB)

    assert await restocking.initialized_on(GUILD_A) == day_one


async def test_a_refused_entry_does_not_start_the_clock(built):
    from fake_discord import somewhere_else

    await enter(built, channel=somewhere_else("general"))

    assert await restocking.initialized_on(GUILD_A) is None
