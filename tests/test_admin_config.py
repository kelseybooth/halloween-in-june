"""`/admin_config`, and the command list 2c settles on.

Slash commands cost about an hour of propagation to change, so the list is
registered once at the end of the phase with every change batched. The tests
at the bottom pin the shape of that list, because getting it wrong is an hour
of stale signatures rather than a redeploy.
"""

import pytest

from conftest import ALICE, GUILD_A, GUILD_B
from fake_discord import FakeInteraction

import bot
import content as content_module
import content_loader
import database
import restocking


async def configure(key, value, user_id=ALICE, guild_id=GUILD_A):
    interaction = FakeInteraction(user_id, guild_id)
    await bot.admin_config.callback(interaction, key, value)
    return interaction


@pytest.fixture
async def server(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    return db


# --------------------------------------------------------------------------
# Setting a value
# --------------------------------------------------------------------------


async def test_a_setting_can_be_changed(server):
    interaction = await configure("planks_required", 4)

    assert await database.get_setting(GUILD_A, "planks_required") == 4
    assert "4" in interaction.reply
    assert interaction.was_private


async def test_the_reply_says_what_it_was(server):
    await configure("planks_required", 4)
    interaction = await configure("planks_required", 6)

    assert "was 4" in interaction.reply


async def test_an_unset_setting_reads_as_its_default(server):
    default = database.CONFIG_KEYS["planks_required"][0]
    assert await database.get_setting(GUILD_A, "planks_required") == default


async def test_keys_are_case_insensitive_and_trimmed(server):
    await configure("  PLANKS_REQUIRED  ", 3)
    assert await database.get_setting(GUILD_A, "planks_required") == 3


async def test_settings_are_per_server(db):
    for guild in (GUILD_A, GUILD_B):
        await db.ensure_user_exists(ALICE, guild)
    await configure("planks_required", 3, guild_id=GUILD_A)

    assert await database.get_setting(GUILD_A, "planks_required") == 3
    assert await database.get_setting(GUILD_B, "planks_required") == (
        database.CONFIG_KEYS["planks_required"][0]
    )


# --------------------------------------------------------------------------
# Refusing
# --------------------------------------------------------------------------


async def test_an_unknown_key_is_refused_and_the_real_ones_listed(server):
    interaction = await configure("planks_requried", 4)  # transposed

    assert "no setting called" in interaction.reply
    for key in database.CONFIG_KEYS:
        assert key in interaction.reply


async def test_an_unknown_key_writes_nothing(server):
    await configure("nonsense", 4)

    async with server._require_session()() as session:
        from sqlalchemy import func, select

        rows = await session.scalar(
            select(func.count()).select_from(database.ServerConfig)
        )
    assert rows == 0


@pytest.mark.parametrize("value", [0, -1, -100])
async def test_a_value_below_one_is_refused(server, value):
    """Zero would stop the thing it controls from ever happening, which is
    almost certainly not what the admin meant."""
    interaction = await configure("bottles_per_day", value)

    assert "at least 1" in interaction.reply
    assert await database.get_setting(GUILD_A, "bottles_per_day") == (
        database.CONFIG_KEYS["bottles_per_day"][0]
    )


async def test_an_unreadable_stored_value_falls_back_to_the_default(server):
    """Somebody hand-edits a row; the command should not take a feature down."""
    async with server._require_session()() as session:
        session.add(
            database.ServerConfig(guild_id=GUILD_A, key="planks_required", value="lots")
        )
        await session.commit()

    assert await database.get_setting(GUILD_A, "planks_required") == (
        database.CONFIG_KEYS["planks_required"][0]
    )


# --------------------------------------------------------------------------
# It works mid-game
# --------------------------------------------------------------------------


async def test_lowering_the_plank_target_below_what_is_placed_says_so(server):
    """The staircase opens in 2c.5. An admin lowering the number and seeing
    nothing happen would file that as a bug, so the reply says it first."""
    await database.record_use(ALICE, GUILD_A, "lumber")
    interaction = await configure("planks_required", 1)

    assert "already placed a plank" in interaction.reply
    assert "does not open yet" in interaction.reply


async def test_no_such_note_when_the_target_is_not_met(server):
    interaction = await configure("planks_required", 8)
    assert "already placed" not in interaction.reply


async def test_changing_bottles_per_day_changes_what_the_scheduler_places(server):
    """The setting has to reach the thing it configures, not just the table."""
    await content_loader.load_content(content_module.load_files())
    await restocking.set_initialized_on(GUILD_A)
    await configure("bottles_per_day", 2)

    from datetime import datetime, timedelta

    day = database.pacific_today()
    end = (
        datetime.combine(day, datetime.max.time(), tzinfo=database.PACIFIC)
        .astimezone(database.timezone.utc)
        .replace(tzinfo=None)
    )
    report = await restocking.run_for_guild(GUILD_A, now=end)
    bottles = [row for row in report.placed if row[3] == "used_baby_bottle"]

    assert len(bottles) == 2


async def test_the_registry_is_the_only_place_defaults_live(server):
    """One list, so a key cannot be settable but unread, or read with a
    different default than the command reports."""
    assert restocking.CONFIG_DEFAULTS == {
        key: default for key, (default, _) in database.CONFIG_KEYS.items()
    }


# --------------------------------------------------------------------------
# The command list
# --------------------------------------------------------------------------


def commands():
    return {c.name: c for c in bot.bot.tree.get_commands()}


def test_there_are_ten_commands():
    """Registered in one sync at the end of 2c. Changing this list later costs
    an hour of propagation and stale signatures in between."""
    assert len(commands()) == 10


def test_the_two_testing_tools_are_gone():
    """Obsolete the moment the loader landed in 2b, held back so their removal
    could go in this one registration."""
    assert "add-thing" not in commands()
    assert "add-room-desc" not in commands()


@pytest.mark.parametrize(
    "name",
    ["pet", "stats", "look", "inventory", "take", "drop", "use", "enter-entryway"],
)
def test_the_player_commands_are_registered(name):
    assert name in commands()


@pytest.mark.parametrize("name", ["initialize-haunted-house", "admin_config"])
def test_the_admin_commands_are_registered(name):
    cmd = commands()[name]
    assert cmd.default_permissions and cmd.default_permissions.administrator


def test_stats_takes_no_options():
    """Adding the member argument later costs another re-sync. That is a known
    cost, and better than an option that exists and refuses."""
    assert commands()["stats"].parameters == []


@pytest.mark.parametrize("name, option", [("take", "thing"), ("drop", "thing"), ("use", "thing")])
def test_the_verbs_take_one_required_thing(name, option):
    params = commands()[name].parameters
    assert [p.name for p in params] == [option]
    assert params[0].required


def test_look_takes_an_optional_thing():
    param = commands()["look"].parameters[0]
    assert param.name == "thing"
    assert not param.required
