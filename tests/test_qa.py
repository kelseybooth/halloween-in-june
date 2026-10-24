"""The QA commands, and the three gates on them.

The gates are not redundant and each test here says which one it is
about. **Registration** keeps them out of the live server's menu, so a
member there cannot find out `/qa-relationship` exists. **The role**
stops a curious member of a test server setting their own score to 250.
**The log line** means that when a server turns out not to be where
somebody thought it was, there is a record of who moved it.

The last of those is the reason `/qa-inspect` exists at all: a forced
drop has to be visibly forced, or somebody spends an afternoon debugging
a server that is simply not where they think it is.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A, HOUSE_DROP
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
import gating
import qa
import resolve
import triggers

TEST_GUILD = sorted(qa.TEST_GUILDS)[0]


@pytest.fixture
async def testing(db, registrations):
    """A test server, with a QA log channel and a tester who holds the role.

    `registrations` because the commands that move a server's drop
    re-register the slash menu, which wants a gateway. The patch
    records the call instead, so these stay about the drop.
    """
    achievements.clear()
    triggers.register_all()
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    qa_log = FakeChannel(name=qa.LOG_CHANNEL)
    guild = FakeGuild(
        TEST_GUILD,
        name="Test Server",
        channels=[halloween, qa_log],
        members=[FakeMember(ALICE, roles=["qa"]), FakeMember(BOB)],
    )
    await database.set_announcement_channel(TEST_GUILD, halloween.id)
    await database.set_setting(TEST_GUILD, resolve.DROP_KEY, 1)
    await database.ensure_user_exists(BOB, TEST_GUILD)
    yield db, guild, halloween, qa_log
    achievements.clear()


def qa_call(guild, command, who=ALICE, roles=("qa",)):
    return FakeInteraction(
        who, guild.id, guild=guild, channel=guild.text_channels[0],
        roles=roles, command=command,
    )


def member(guild, user_id=BOB):
    return guild.get_member(user_id)


# --------------------------------------------------------------------------
# Gate one: they do not exist in the live server
# --------------------------------------------------------------------------


def test_the_live_server_is_not_a_test_server():
    assert not qa.is_test_guild(GUILD_A)
    assert qa.is_test_guild(TEST_GUILD)


def test_they_are_registered_in_the_test_servers_only():
    """Both directions. "Absent from the live server" is also true of a
    bot that registered nothing anywhere."""
    live = gating.commands_for(1, qa=False)
    test = gating.commands_for(1, qa=True)

    assert not (live & set(gating.QA_COMMANDS))
    assert set(gating.QA_COMMANDS) <= test


def test_a_test_server_has_them_before_the_game_starts():
    """Resetting a player is most useful when there is nothing to reset."""
    assert set(gating.QA_COMMANDS) <= gating.commands_for(None, qa=True)


def test_every_name_in_the_qa_list_is_a_command_that_exists():
    defined = {c.name for c in bot.bot.tree.get_commands()}

    assert set(gating.QA_COMMANDS) <= defined


# --------------------------------------------------------------------------
# Gate two: the role
# --------------------------------------------------------------------------


async def test_without_the_role_nothing_happens(testing):
    _, guild, _, _ = testing
    interaction = qa_call(guild, "qa-drop", roles=())

    await bot.qa_drop.callback(interaction, 0)

    assert await resolve.current_drop(TEST_GUILD) == 1
    assert "role" in interaction.reply


async def test_the_refusal_is_private(testing):
    _, guild, _, _ = testing
    interaction = qa_call(guild, "qa-drop", roles=())

    await bot.qa_drop.callback(interaction, 0)

    assert interaction.was_private


async def test_an_administrator_is_not_exempt(testing):
    """The role is cheap to grant, and moving a server's drop should be
    a deliberate act by somebody who is testing."""
    _, guild, _, _ = testing
    interaction = qa_call(guild, "qa-drop", roles=("admin",))

    await bot.qa_drop.callback(interaction, 3)

    assert await resolve.current_drop(TEST_GUILD) == 1


# --------------------------------------------------------------------------
# Gate three: the log
# --------------------------------------------------------------------------


async def test_every_call_writes_one_line(testing):
    _, guild, _, qa_log = testing

    await bot.qa_drop.callback(qa_call(guild, "qa-drop"), 0)

    assert len(qa_log.posted) == 1
    assert "qa-drop" in qa_log.posted[0]


async def test_the_line_names_who_ran_it(testing):
    _, guild, _, qa_log = testing

    await bot.qa_clock.callback(qa_call(guild, "qa-clock"), 3)

    assert str(ALICE) in qa_log.posted[0]


async def test_a_refused_call_logs_nothing(testing):
    _, guild, _, qa_log = testing

    await bot.qa_drop.callback(qa_call(guild, "qa-drop", roles=()), 0)

    assert qa_log.posted == []


async def test_a_missing_log_channel_does_not_stop_the_command(testing):
    """The audit trail loses its convenience; the tester keeps their
    command."""
    _, guild, _, qa_log = testing
    guild.text_channels.remove(qa_log)

    await bot.qa_clock.callback(qa_call(guild, "qa-clock"), 2)

    assert await database.clock_offset(TEST_GUILD) == 2


# --------------------------------------------------------------------------
# /qa-drop
# --------------------------------------------------------------------------


async def test_it_jumps_forwards(testing):
    _, guild, _, _ = testing

    await bot.qa_drop.callback(qa_call(guild, "qa-drop"), HOUSE_DROP)

    assert await resolve.current_drop(TEST_GUILD) == HOUSE_DROP


async def test_and_backwards_which_nothing_else_does(testing):
    _, guild, _, _ = testing

    await bot.qa_drop.callback(qa_call(guild, "qa-drop"), 0)

    assert await resolve.current_drop(TEST_GUILD) == 0


async def test_a_drop_that_does_not_exist_is_refused(testing):
    _, guild, _, _ = testing
    interaction = qa_call(guild, "qa-drop")

    await bot.qa_drop.callback(interaction, 99)

    assert await resolve.current_drop(TEST_GUILD) == 1
    assert "No drop 99" in interaction.reply


async def test_jumping_brings_the_command_set_with_it(testing):
    _, guild, _, _ = testing

    await bot.qa_drop.callback(qa_call(guild, "qa-drop"), 0)

    assert "look" not in gating.commands_for(
        await resolve.current_drop(TEST_GUILD), qa=True
    )


# --------------------------------------------------------------------------
# A forced drop is visibly forced
# --------------------------------------------------------------------------


async def test_a_forced_drop_is_recorded(testing):
    _, guild, _, _ = testing

    await bot.qa_drop.callback(qa_call(guild, "qa-drop"), 0)

    assert await qa.forced_drop(TEST_GUILD) == 0


async def test_inspect_says_so_loudly(testing):
    """The reason this command exists."""
    _, guild, _, _ = testing
    await bot.qa_drop.callback(qa_call(guild, "qa-drop"), 0)
    interaction = qa_call(guild, "qa-inspect")

    await bot.qa_inspect.callback(interaction, member(guild))

    assert "forced" in interaction.reply


async def test_an_unforced_server_says_nothing_about_it(testing):
    _, guild, _, _ = testing
    interaction = qa_call(guild, "qa-inspect")

    await bot.qa_inspect.callback(interaction, member(guild))

    assert "forced" not in interaction.reply


async def test_advancing_properly_clears_the_mark(testing):
    """The server is where it says it is again."""
    _, guild, _, _ = testing
    await bot.qa_drop.callback(qa_call(guild, "qa-drop"), 0)

    await bot.advance_game.callback(qa_call(guild, "advance-game"), True)

    assert await qa.forced_drop(TEST_GUILD) is None


# --------------------------------------------------------------------------
# /qa-relationship, /qa-clock, /qa-midnight, /qa-cooldown
# --------------------------------------------------------------------------


async def test_setting_a_score_sets_it_exactly(testing):
    _, guild, _, _ = testing

    await bot.qa_relationship.callback(qa_call(guild, "qa-relationship"), member(guild), 250)

    assert await database.get_relationship(BOB, TEST_GUILD) == 250


async def test_a_score_set_by_hand_still_earns_the_threshold(testing):
    """Two hundred and fifty is days of honest play away, which is the
    whole reason for this command - and it should hand over *Favorite
    Human* rather than wait for a pet that may never come."""
    _, guild, _, _ = testing

    await bot.qa_relationship.callback(qa_call(guild, "qa-relationship"), member(guild), 250)

    earned = await database.player_achievements_of(TEST_GUILD, BOB)
    assert "favorite_human" in earned


async def test_the_clock_moves_every_dated_thing_at_once(testing):
    _, guild, _, _ = testing

    await bot.qa_clock.callback(qa_call(guild, "qa-clock"), 7)

    today = await database.server_today(TEST_GUILD)
    assert (today - database.pacific_today()).days == 7


async def test_zero_puts_it_back_on_the_real_clock(testing):
    _, guild, _, _ = testing
    await bot.qa_clock.callback(qa_call(guild, "qa-clock"), 7)

    await bot.qa_clock.callback(qa_call(guild, "qa-clock"), 0)

    assert await database.server_today(TEST_GUILD) == database.pacific_today()


async def test_midnight_no_longer_moves_anybodys_score(testing):
    """**The drift is withdrawn**, so the pair of commands a tester
    used to reach for - jump the clock, settle the nights - now settles
    nothing. It still fires `on_midnight`, which is the half worth
    keeping: nothing listens on it yet and the bottle scatter and the
    craving roll both will.
    """
    _, guild, _, _ = testing
    await database.set_relationship(TEST_GUILD, BOB, 100)
    await bot.qa_clock.callback(qa_call(guild, "qa-clock"), 3)

    interaction = qa_call(guild, "qa-midnight")
    await bot.qa_midnight.callback(interaction)

    assert await database.get_relationship(BOB, TEST_GUILD) == 100
    assert "no scores moved" in interaction.sent[-1][0]


async def test_clearing_cooldowns_lets_the_bed_be_fluffed_again(testing):
    _, guild, halloween, _ = testing
    bob = FakeInteraction(BOB, TEST_GUILD, guild=guild, channel=halloween)
    await bot.use.callback(bob, "cat bed")

    await bot.qa_cooldown.callback(qa_call(guild, "qa-cooldown"), member(guild))

    again = FakeInteraction(BOB, TEST_GUILD, guild=guild, channel=halloween)
    await bot.use.callback(again, "cat bed")
    assert "shake out the cushion" in again.reply


async def test_clearing_cooldowns_keeps_the_pet_count(testing):
    """It is progress, not a cooldown. A tester clearing a window should
    not lose their march on two hundred."""
    _, guild, _, _ = testing
    for _ in range(5):
        await database.increment_pet_count(BOB, TEST_GUILD)

    await bot.qa_cooldown.callback(qa_call(guild, "qa-cooldown"), member(guild))

    assert await database.get_pet_count(BOB, TEST_GUILD) == 5


# --------------------------------------------------------------------------
# /qa-reset-player
# --------------------------------------------------------------------------


async def test_resetting_a_player_clears_the_hint_rows(testing):
    """**The half that is easy to forget and the half that matters.**
    Without it the hint ladder is one-shot per tester per server, and
    the second run through the tutorial is silent."""
    _, guild, halloween, _ = testing
    bob = FakeInteraction(BOB, TEST_GUILD, guild=guild, channel=halloween)
    await bot.look.callback(bob, None)
    assert await database.notice_order(TEST_GUILD, BOB)

    await bot.qa_reset_player.callback(qa_call(guild, "qa-reset-player"), member(guild))

    assert await database.notice_order(TEST_GUILD, BOB) == {}


async def test_the_whole_ladder_replays(testing):
    _, guild, halloween, _ = testing
    first = FakeInteraction(BOB, TEST_GUILD, guild=guild, channel=halloween)
    await bot.look.callback(first, None)

    await bot.qa_reset_player.callback(qa_call(guild, "qa-reset-player"), member(guild))

    again = FakeInteraction(BOB, TEST_GUILD, guild=guild, channel=halloween)
    await bot.look.callback(again, None)
    assert "Try /look cat bed" in again.reply


async def test_it_clears_progress_too(testing):
    _, guild, _, _ = testing
    await database.set_relationship(TEST_GUILD, BOB, 90)
    await database.award_player_achievement(TEST_GUILD, BOB, "making_first_contact")

    await bot.qa_reset_player.callback(qa_call(guild, "qa-reset-player"), member(guild))

    assert await database.player_achievements_of(TEST_GUILD, BOB) == {}
    assert await database.get_relationship(BOB, TEST_GUILD) == 0


async def test_it_leaves_the_server_alone(testing):
    """Resetting one tester must not un-repair the staircase for
    everybody."""
    _, guild, _, _ = testing
    await database.award_server_achievement(TEST_GUILD, "making_a_mess")

    await bot.qa_reset_player.callback(qa_call(guild, "qa-reset-player"), member(guild))

    assert "making_a_mess" in await database.server_achievements_of(TEST_GUILD)
    assert await resolve.current_drop(TEST_GUILD) == 1


async def test_it_leaves_other_players_alone(testing):
    _, guild, _, _ = testing
    await database.ensure_user_exists(ALICE, TEST_GUILD)
    await database.set_relationship(TEST_GUILD, ALICE, 70)

    await bot.qa_reset_player.callback(qa_call(guild, "qa-reset-player"), member(guild))

    assert await database.get_relationship(ALICE, TEST_GUILD) == 70


# --------------------------------------------------------------------------
# Drop 2: the ramp, and a way to put a toy on the floor
# --------------------------------------------------------------------------


async def test_the_ramp_can_be_set_directly(testing):
    """The argument for a generic state command: 4 makes the next
    attempt certain, 0 replays the guaranteed first refusal, and 4
    followed by a failure is *Impressively Bad Luck* in one call."""
    _, guild, _, _ = testing

    await bot.qa_state.callback(qa_call(guild, "qa-state"), member(guild), 4)

    assert (await database.play_state(TEST_GUILD, BOB))[0] == 4


async def test_a_negative_ramp_is_refused(testing):
    _, guild, _, _ = testing
    interaction = qa_call(guild, "qa-state")

    await bot.qa_state.callback(interaction, member(guild), -1)

    assert "does not go below zero" in interaction.reply


async def test_clearing_cooldowns_resets_the_ramp(testing):
    """Or the next attempt is at whatever percentage the last run left
    behind, which is the sort of thing that wastes an afternoon."""
    _, guild, _, _ = testing
    await bot.qa_state.callback(qa_call(guild, "qa-state"), member(guild), 3)

    await bot.qa_cooldown.callback(qa_call(guild, "qa-cooldown"), member(guild))

    ramp, until = await database.play_state(TEST_GUILD, BOB)
    assert (ramp, until) == (0, None)


async def test_a_toy_can_be_spawned(testing):
    _, guild, _, _ = testing
    interaction = qa_call(guild, "qa-spawn")

    await bot.qa_spawn.callback(interaction, "feather wand")

    import content as content_module

    present = await database.present_of_type(
        TEST_GUILD, content_module.CHANNEL_ROOM, "toy"
    )
    assert "feather wand" in present


async def test_spawning_something_that_does_not_exist_is_refused(testing):
    _, guild, _, _ = testing
    interaction = qa_call(guild, "qa-spawn")

    await bot.qa_spawn.callback(interaction, "jetpack")

    assert "no thing called" in interaction.reply


async def test_resetting_a_player_clears_the_play_state(testing):
    """The ramp and the cooldown live on the player row, so they go
    with it - but it is worth asserting rather than assuming, because
    a tester whose ramp survived a reset would see the wrong odds."""
    _, guild, _, _ = testing
    await bot.qa_state.callback(qa_call(guild, "qa-state"), member(guild), 3)

    await bot.qa_reset_player.callback(qa_call(guild, "qa-reset-player"), member(guild))

    assert (await database.play_state(TEST_GUILD, BOB))[0] == 0

# --------------------------------------------------------------------------
# Un-starting a server
#
# The state before `/start-game` was unreachable by any command. The
# admin reset writes the drop and the channel straight back on purpose,
# and its `back_to_drop` floors at drop 0 because no drop number means
# "not started" - so the first five minutes of a server's life could be
# tested exactly once per server.
# --------------------------------------------------------------------------


async def reset_server(testing, confirm=None):
    _, guild, _, _ = testing
    interaction = qa_call(guild, "qa-reset-server")
    await bot.qa_reset_server.callback(interaction, confirm or guild.name)
    return interaction


async def test_it_un_starts_the_server(testing):
    """**The whole point.** `current_drop` is None afterwards, which is
    the one state `/start-game` will act on."""
    assert await resolve.current_drop(TEST_GUILD) == 1

    await reset_server(testing)

    assert await resolve.current_drop(TEST_GUILD) is resolve.NO_GAME


async def test_the_whole_round_trip_including_the_art(testing):
    """**What somebody testing the first five minutes actually needs**,
    and the reason this command exists: un-start, then start again and
    watch the pictures arrive.

    It is also the assertion that would fail if the drop pointer were
    closed rather than deleted - a shut window reads as "started once,
    then stopped", and `/start-game` refuses that.
    """
    db, guild, halloween, _ = testing
    assets = FakeChannel(name="bot-testing")
    guild.text_channels.append(assets)
    await db.record_art(TEST_GUILD, "black_cat_alert", "https://example/old.png")

    await reset_server(testing)

    starting = FakeInteraction(ALICE, TEST_GUILD, guild=guild, channel=halloween)
    await bot.start_game.callback(starting, halloween, assets)

    assert await resolve.current_drop(TEST_GUILD) == 0
    assert len(await db.art_urls(TEST_GUILD)) == 10
    assert "uploaded 10 cat picture(s)" in starting.sent[-1][0]


async def test_the_art_goes_too(testing):
    """**The difference that matters for the upload.** `upload_art`
    skips any image a server already has, so a reset that kept them
    would report ten uploads and post none."""
    db, _, _, _ = testing
    await db.record_art(TEST_GUILD, "black_cat_alert", "https://example/a.png")

    await reset_server(testing)

    assert await db.art_urls(TEST_GUILD) == {}


async def test_the_channel_goes_too(testing):
    """Every other reset writes it back. This one means "never
    started", and a server that was never started does not know where
    it lives."""
    db, _, _, _ = testing

    await reset_server(testing)

    assert await db.announcement_channel(TEST_GUILD) is None


async def test_it_takes_the_progress_with_it(testing):
    db, _, _, _ = testing
    await db.adjust_relationship(BOB, TEST_GUILD, 40)
    await db.award_player_achievement(TEST_GUILD, BOB, "making_first_contact")

    await reset_server(testing)

    assert await db.get_relationship(BOB, TEST_GUILD) == 0
    assert await db.player_achievements_of(TEST_GUILD, BOB) == {}


async def test_the_wrong_name_changes_nothing(testing):
    """The same safeguard the admin reset uses, and this one goes
    further than it does."""
    interaction = await reset_server(testing, confirm="not the server")

    assert await resolve.current_drop(TEST_GUILD) == 1
    assert "Run it again with" in interaction.sent[-1][0]


async def test_it_leaves_no_forced_drop_behind(testing):
    """A forced pointer on an un-started server would have
    `/qa-inspect` report an override on a game that does not exist."""
    await qa.mark_forced(TEST_GUILD, 1)

    await reset_server(testing)

    assert await qa.forced_drop(TEST_GUILD) is None


async def test_it_is_logged_like_every_other_qa_call(testing):
    _, _, _, qa_log = testing

    await reset_server(testing)

    assert any("qa-reset-server" in line for line in qa_log.posted)


async def test_somebody_without_the_role_cannot(testing):
    _, guild, _, _ = testing
    interaction = qa_call(guild, "qa-reset-server", roles=())

    await bot.qa_reset_server.callback(interaction, guild.name)

    assert await resolve.current_drop(TEST_GUILD) == 1

