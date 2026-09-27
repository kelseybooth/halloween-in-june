"""Discord thread management for the haunted house.

Creating threads, deleting them, and moving players in and out. Nothing here
knows what the house looks like: the room list and the navigation graph moved
into the content files in phase 2b, and callers pass room names in.

That split is the point. A room being renamed, added or removed is a content
change; how a thread gets created is not.
"""

import logging
from typing import NamedTuple

import discord

log = logging.getLogger(__name__)

# The channel the house lives in. Must already exist - the bot does not create it.
HALLOWEEN_CHANNEL_NAME = "halloween"

# Discord accepts only 60, 1440, 4320 or 10080 minutes, so one week is the longest
# auto-archive it will take. The house is meant never to archive, so this is a
# backstop rather than the real policy: keep_threads_alive() revives anything that
# slips through, which is what actually keeps the rooms open indefinitely.
THREAD_AUTO_ARCHIVE_MINUTES = 10080

class InitResult(NamedTuple):
    """What one run of initialize_threads did."""

    deleted: int
    created: int
    restored: int
    errors: list[str]


# What the bot needs in #halloween, mapped to the labels Discord shows in its
# permission UI, so a warning can name what to tick rather than an attribute.
REQUIRED_PERMISSIONS = {
    "view_channel": "View Channel",
    "read_message_history": "Read Message History",
    "manage_threads": "Manage Threads",
    "create_private_threads": "Create Private Threads",
    "send_messages_in_threads": "Send Messages in Threads",
}


def find_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """The #halloween text channel, or None if the server has no such channel."""
    return discord.utils.get(guild.text_channels, name=HALLOWEEN_CHANNEL_NAME)


def missing_permissions(channel: discord.TextChannel) -> list[str]:
    """Permissions the bot still needs in this channel, by their Discord UI names.

    Checked up front because the failures otherwise surface mid-run as opaque
    "50001 Missing Access" errors that do not say which permission is absent.
    """
    me = channel.guild.me
    if me is None:
        return []
    allowed = channel.permissions_for(me)
    return [label for attr, label in REQUIRED_PERMISSIONS.items() if not getattr(allowed, attr, False)]


async def _existing_threads(channel: discord.TextChannel) -> list[discord.Thread]:
    """Active and archived threads in the channel.

    Archived threads are fetched separately: they do not appear in `channel.threads`,
    and leaving them behind would collide with the names we are about to create.
    """
    threads = list(channel.threads)
    seen = {thread.id for thread in threads}

    for private in (True, False):
        try:
            async for thread in channel.archived_threads(private=private, limit=None):
                if thread.id not in seen:
                    seen.add(thread.id)
                    threads.append(thread)
        except discord.Forbidden:
            # Expected and actionable, so say what to fix rather than dumping a
            # traceback the reader has to decode - this repeats on every sweep.
            log.warning(
                "Cannot list %s archived threads in #%s: the bot needs the "
                "'Read Message History' and 'Manage Threads' permissions there. "
                "Active threads still work; archived ones are being skipped.",
                "private" if private else "public",
                channel.name,
            )
        except discord.HTTPException:
            log.warning(
                "Could not list archived threads (private=%s)", private, exc_info=True
            )

    return threads


async def initialize_threads(
    channel: discord.TextChannel,
    room_names: list[str],
    locations: list[tuple[int, str]],
) -> InitResult:
    """Delete every thread in the channel and recreate one per room.

    `room_names` comes from the content files; `locations` is (user_id, room name)
    for each player with game state. After the threads exist, each player is
    re-added to the thread for the room they were in, which is what makes the
    command rerunnable without stranding anyone - the database, not Discord, is
    the source of truth for who belongs where.

    Deleting everything first is also how a server migrates: threads for rooms
    that no longer exist go with the rest, and only current rooms come back.
    """
    errors: list[str] = []

    existing = await _existing_threads(channel)
    deleted = 0
    for thread in existing:
        try:
            await thread.delete()
            deleted += 1
        except discord.HTTPException as exc:
            errors.append(f"could not delete thread {thread.name!r}: {exc}")
            log.warning("Failed to delete thread %s", thread.name, exc_info=True)

    threads: dict[str, discord.Thread] = {}
    for name in room_names:
        try:
            thread = await channel.create_thread(
                name=name,
                type=discord.ChannelType.private_thread,
                auto_archive_duration=THREAD_AUTO_ARCHIVE_MINUTES,
                invitable=False,  # only the bot decides who joins
            )
            threads[name] = thread
        except discord.HTTPException as exc:
            errors.append(f"could not create thread {name!r}: {exc}")
            log.error("Failed to create thread %s", name, exc_info=True)

    restored = 0
    for user_id, room in locations:
        thread = threads.get(room)
        if thread is None:
            errors.append(f"player {user_id}: thread {room!r} was not created")
            continue

        try:
            await thread.add_user(discord.Object(id=user_id))
            restored += 1
        except discord.HTTPException as exc:
            errors.append(f"could not restore player {user_id} to {room!r}: {exc}")
            log.warning("Failed to restore player %s to %s", user_id, room, exc_info=True)

    log.info(
        "Haunted house initialized with %d thread(s) in %s (deleted %d, restored %d players)",
        len(threads),
        channel.guild.name,
        deleted,
        restored,
    )
    return InitResult(deleted=deleted, created=len(threads), restored=restored, errors=errors)


async def add_player_to_thread(thread: discord.Thread, player_id: int) -> None:
    """Invite a player into a private thread."""
    await thread.add_user(discord.Object(id=player_id))


async def remove_player_from_thread(thread: discord.Thread, player_id: int) -> None:
    """Remove a player from a private thread."""
    await thread.remove_user(discord.Object(id=player_id))


async def unarchive_all(
    channel: discord.TextChannel, room_names: list[str]
) -> tuple[int, list[str]]:
    """Revive every archived house thread. Returns (revived count, errors).

    Discord's longest auto-archive is 7 days, so a room with no traffic for a week
    would archive and drop out of the channel's active list. Running this on a
    schedule keeps every room permanently open.

    `room_names` is the same list initialize_threads was given, so the set revived
    cannot drift from the set built. Miss that and the rooms quietly vanish a week
    after launch.
    """
    wanted = set(room_names)
    revived = 0
    errors: list[str] = []

    for thread in await _existing_threads(channel):
        if thread.name not in wanted or not thread.archived:
            continue
        try:
            # A locked thread cannot be unarchived without also unlocking it.
            if thread.locked:
                await thread.edit(archived=False, locked=False)
            else:
                await thread.edit(archived=False)
            revived += 1
        except discord.HTTPException as exc:
            errors.append(f"could not revive thread {thread.name!r}: {exc}")
            log.warning("Failed to unarchive thread %s", thread.name, exc_info=True)

    if revived:
        log.info("Revived %d archived house thread(s) in #%s", revived, channel.name)
    return revived, errors


async def get_thread_for_room(
    channel: discord.TextChannel, room_name: str
) -> discord.Thread | None:
    """Find a room's thread by name.

    Searches archived threads as well as active ones: `channel.threads` omits
    archived threads, so an active-only lookup would fail during the window between
    a thread archiving and the next keep-alive pass reviving it.
    """
    for thread in await _existing_threads(channel):
        if thread.name == room_name:
            return thread
    return None
