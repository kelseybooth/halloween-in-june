"""Thread creation, rebuild and the keep-alive sweep, against a fake Discord.

The rebuild is the migration path phase 2a relies on: admins re-run
`/initialize-haunted-house` and the house comes back correct. These tests are
what say it is safe to tell them that.
"""

import pytest

import house_utils
from fake_discord import FakeChannel, FakeThread


ALL_NAMES = house_utils.all_thread_names()


# --------------------------------------------------------------------------
# Building the house
# --------------------------------------------------------------------------


async def test_a_fresh_channel_gets_the_full_set():
    channel = FakeChannel()
    result = await house_utils.initialize_threads(channel, [])

    assert result.created == len(ALL_NAMES)
    assert channel.created == ALL_NAMES
    assert result.errors == []


async def test_threads_are_created_private_and_not_invitable():
    """Only the bot decides who joins a room."""
    import discord

    channel = FakeChannel()
    await house_utils.initialize_threads(channel, [])

    for thread in channel.threads:
        assert thread.type == discord.ChannelType.private_thread
        assert thread.invitable is False
        assert thread.auto_archive_duration == house_utils.THREAD_AUTO_ARCHIVE_MINUTES


async def test_rebuilding_deletes_what_was_there_first():
    channel = FakeChannel().add_active(*ALL_NAMES)
    result = await house_utils.initialize_threads(channel, [])

    assert result.deleted == len(ALL_NAMES)
    assert result.created == len(ALL_NAMES)


async def test_rebuilding_twice_leaves_eighteen_not_thirty_six():
    """The idempotence phase 2a asks for: run it again, get the same house."""
    channel = FakeChannel()
    await house_utils.initialize_threads(channel, [])
    await house_utils.initialize_threads(channel, [])

    assert len(channel.threads) == len(ALL_NAMES)
    assert sorted(t.name for t in channel.threads) == sorted(ALL_NAMES)


async def test_rebuilding_after_a_half_finished_run_still_lands_on_eighteen():
    """An admin re-running after a partial failure must not accumulate rooms."""
    channel = FakeChannel().add_active("Entryway", "The Entryway", "Kitchen")
    await house_utils.initialize_threads(channel, [])

    assert len(channel.threads) == len(ALL_NAMES)


async def test_archived_threads_are_deleted_too():
    """They are invisible in `channel.threads` but their names still collide."""
    channel = FakeChannel(archived=["Entryway", "The Entryway"])
    result = await house_utils.initialize_threads(channel, [])

    assert result.deleted == 2


async def test_stray_threads_that_are_not_rooms_are_also_cleared():
    channel = FakeChannel().add_active("general chat", "spoilers")
    result = await house_utils.initialize_threads(channel, [])

    assert result.deleted == 2
    assert sorted(t.name for t in channel.threads) == sorted(ALL_NAMES)


# --------------------------------------------------------------------------
# Putting the players back
# --------------------------------------------------------------------------


async def test_players_are_restored_to_the_room_they_were_in():
    channel = FakeChannel()
    locations = [(111, "A", "Kitchen"), (222, "B", "Bedroom")]
    result = await house_utils.initialize_threads(channel, locations)

    assert result.restored == 2
    by_name = {t.name: t for t in channel.threads}
    assert by_name["Kitchen"].added_users == [111]
    assert by_name["The Bedroom"].added_users == [222]


async def test_a_players_cohort_decides_which_copy_of_the_room_they_return_to():
    channel = FakeChannel()
    await house_utils.initialize_threads(channel, [(111, "B", "Kitchen")])

    by_name = {t.name: t for t in channel.threads}
    assert by_name["The Kitchen"].added_users == [111]
    assert by_name["Kitchen"].added_users == []


async def test_several_players_in_one_room_all_come_back():
    channel = FakeChannel()
    locations = [(111, "A", "Kitchen"), (222, "A", "Kitchen"), (333, "A", "Kitchen")]
    result = await house_utils.initialize_threads(channel, locations)

    assert result.restored == 3
    by_name = {t.name: t for t in channel.threads}
    assert by_name["Kitchen"].added_users == [111, 222, 333]


async def test_nobody_in_the_house_means_nobody_to_restore():
    result = await house_utils.initialize_threads(FakeChannel(), [])
    assert result.restored == 0


# --------------------------------------------------------------------------
# When Discord says no
# --------------------------------------------------------------------------


async def test_a_failed_creation_is_reported_and_the_rest_continue():
    channel = FakeChannel()
    channel.create_fails = {"Kitchen"}
    result = await house_utils.initialize_threads(channel, [])

    assert result.created == len(ALL_NAMES) - 1
    assert any("Kitchen" in e for e in result.errors)
    assert "The Kitchen" in channel.created  # the others still went up


async def test_a_player_whose_room_failed_to_build_is_reported_not_dropped_silently():
    channel = FakeChannel()
    channel.create_fails = {"Kitchen"}
    result = await house_utils.initialize_threads(channel, [(111, "A", "Kitchen")])

    assert result.restored == 0
    assert any("111" in e for e in result.errors)


async def test_a_player_with_an_impossible_cohort_is_reported():
    channel = FakeChannel()
    result = await house_utils.initialize_threads(channel, [(111, "Z", "Kitchen")])

    assert result.restored == 0
    assert any("111" in e for e in result.errors)


async def test_a_failed_deletion_does_not_stop_the_rebuild():
    channel = FakeChannel().add_active("Entryway", "Kitchen")
    channel.delete_fails = {"Entryway"}
    result = await house_utils.initialize_threads(channel, [])

    assert result.deleted == 1
    assert any("Entryway" in e for e in result.errors)
    assert result.created == len(ALL_NAMES)


async def test_missing_permission_to_page_archived_threads_is_survivable():
    """Active threads still work; the sweep logs what to fix and carries on."""
    channel = FakeChannel().add_active("Entryway")
    channel.archived_forbidden = True

    result = await house_utils.initialize_threads(channel, [])
    assert result.created == len(ALL_NAMES)


# --------------------------------------------------------------------------
# The keep-alive sweep
#
# Discord's longest auto-archive is 7 days, so without this the rooms quietly
# vanish a week after launch. Step 4 must keep it, resized from 18 to 9.
# --------------------------------------------------------------------------


async def test_an_archived_room_is_revived():
    channel = FakeChannel(archived=["Kitchen"])
    revived, errors = await house_utils.unarchive_all(channel)

    assert revived == 1
    assert errors == []
    assert channel.archived_list[0].archived is False


async def test_every_archived_room_is_revived():
    channel = FakeChannel(archived=ALL_NAMES)
    revived, _ = await house_utils.unarchive_all(channel)
    assert revived == len(ALL_NAMES)


async def test_an_active_room_is_left_alone():
    channel = FakeChannel().add_active("Kitchen")
    revived, _ = await house_utils.unarchive_all(channel)
    assert revived == 0


async def test_a_locked_thread_is_unlocked_as_well_as_revived():
    """Discord refuses to unarchive a locked thread without also unlocking it."""
    locked = FakeThread("Kitchen", archived=True, locked=True)
    channel = FakeChannel(archived=[locked])

    revived, errors = await house_utils.unarchive_all(channel)

    assert revived == 1
    assert locked.archived is False
    assert locked.locked is False


async def test_a_thread_that_is_not_a_room_is_not_revived():
    channel = FakeChannel(archived=["old announcements"])
    revived, _ = await house_utils.unarchive_all(channel)
    assert revived == 0


async def test_a_failed_revival_is_reported_and_the_rest_continue():
    channel = FakeChannel(archived=["Kitchen", "Bedroom"])
    channel.edit_fails = {"Kitchen"}

    revived, errors = await house_utils.unarchive_all(channel)

    assert revived == 1
    assert any("Kitchen" in e for e in errors)


async def test_the_sweep_covers_exactly_the_rooms_the_house_builds():
    """If the two lists ever disagree, rooms archive and never come back."""
    channel = FakeChannel(archived=ALL_NAMES + ["something else"])
    revived, _ = await house_utils.unarchive_all(channel)
    assert revived == len(ALL_NAMES)


# --------------------------------------------------------------------------
# Permission reporting
# --------------------------------------------------------------------------


def test_a_fully_permitted_channel_reports_nothing_missing():
    channel = FakeChannel().with_permissions(
        **{attr: True for attr in house_utils.REQUIRED_PERMISSIONS}
    )
    assert house_utils.missing_permissions(channel) == []


def test_a_missing_permission_is_named_as_discord_labels_it():
    """The 50001 error does not say which permission; this has to."""
    flags = {attr: True for attr in house_utils.REQUIRED_PERMISSIONS}
    flags["manage_threads"] = False
    channel = FakeChannel().with_permissions(**flags)

    assert house_utils.missing_permissions(channel) == ["Manage Threads"]


def test_every_missing_permission_is_listed():
    channel = FakeChannel().with_permissions(
        **{attr: False for attr in house_utils.REQUIRED_PERMISSIONS}
    )
    assert sorted(house_utils.missing_permissions(channel)) == sorted(
        house_utils.REQUIRED_PERMISSIONS.values()
    )


def test_an_absent_bot_member_reports_nothing_rather_than_crashing():
    channel = FakeChannel()
    channel.guild.me = None
    assert house_utils.missing_permissions(channel) == []
