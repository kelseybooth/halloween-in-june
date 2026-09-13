"""Haunted house layout and Discord thread management (Phase 2).

Every room exists as two threads whose names differ only by a leading article:
cohort A sees "Entryway", cohort B sees "The Entryway". Players are not told this;
it exists so mods can tell at a glance which cohort a thread belongs to.
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

COHORTS = ("A", "B")

# Canonical room names, in the order the spec lists them.
ROOMS = [
    "Dining Room",
    "Entryway",
    "Living Room",
    "Kitchen",
    "Courtyard",
    "Secret Library",
    "Upstairs Hallway",
    "Bedroom",
    "Nursery",
]

STARTING_ROOM = "Entryway"

ROOM_NAMES_A = list(ROOMS)
ROOM_NAMES_B = [f"The {room}" for room in ROOMS]

class Exit(NamedTuple):
    """One way out of a room.

    An exit is a *thing* - the same kind of thing as an object in a room - whose
    effect, when used, is to move the player to another room. That is why its
    fields share the `thing` vocabulary: `thing_id` is the stable identifier code
    and tests refer to ("EL") and never changes; `thing` is what players see - the
    description announced when the exit is taken and what they can type to use
    it. Phase 3 replaces each placeholder with real copy ("blue door"); only the
    `thing=` argument in the graph changes.

    Today /use handles only exits. In Phase 3 it resolves any thing - exit or
    object - and dispatches on what kind it is: "/use blue door" moves the player,
    "/use cat food" does whatever the design says cat food does.
    """

    thing_id: str
    thing: str
    destination: str


def _exit(thing_id: str, destination: str, thing: str | None = None) -> Exit:
    """Build an Exit; the description defaults to `<thing_id>_desc` until Phase 3.

    The default is deliberately obvious placeholder text, so any exit a writer has
    not yet named stands out in play rather than passing for finished copy.
    """
    return Exit(thing_id, thing if thing is not None else f"{thing_id}_desc", destination)


# Exits keyed by thing_id. Codes are the first letter of the current room plus the
# first letter of the destination. resolve_exit matches case-insensitively against
# the thing_id, the description, and the destination room name, so any of those
# work as input.
NAVIGATION_GRAPH: dict[str, dict[str, Exit]] = {
    "Dining Room": {
        "DK": _exit("DK", "Kitchen"),
        "DE": _exit("DE", "Entryway"),
    },
    "Entryway": {
        "ED": _exit("ED", "Dining Room"),
        "EL": _exit("EL", "Living Room"),
        "EH": _exit("EH", "Upstairs Hallway"),
    },
    "Living Room": {
        "LE": _exit("LE", "Entryway"),
        "LS": _exit("LS", "Secret Library"),
    },
    "Kitchen": {
        "KD": _exit("KD", "Dining Room"),
        "KH": _exit("KH", "Upstairs Hallway"),
        "KC": _exit("KC", "Courtyard"),
    },
    "Courtyard": {
        "CK": _exit("CK", "Kitchen"),
        "CS": _exit("CS", "Secret Library"),
    },
    "Secret Library": {
        "SL": _exit("SL", "Living Room"),
        "SC": _exit("SC", "Courtyard"),
    },
    # HE was missing from the spec's original diagram, which gave Entryway an exit
    # up (EH) with no way back down. Confirmed as an oversight rather than a
    # one-way door, and added to the spec to match.
    "Upstairs Hallway": {
        "HK": _exit("HK", "Kitchen"),
        "HB": _exit("HB", "Bedroom"),
        "HN": _exit("HN", "Nursery"),
        "HE": _exit("HE", "Entryway"),
    },
    "Bedroom": {"BH": _exit("BH", "Upstairs Hallway")},
    "Nursery": {"NH": _exit("NH", "Upstairs Hallway")},
}


class InitResult(NamedTuple):
    """What one run of initialize_threads did."""

    deleted: int
    created: int
    restored: int
    errors: list[str]


def get_thread_name(room_name: str, cohort: str) -> str:
    """Thread name for a room in a given cohort: "Entryway" or "The Entryway"."""
    if cohort not in COHORTS:
        raise ValueError(f"unknown cohort {cohort!r}; expected one of {COHORTS}")
    return f"The {room_name}" if cohort == "B" else room_name


def all_thread_names() -> list[str]:
    """Every thread name the house needs - 9 rooms x 2 cohorts, in creation order."""
    return [get_thread_name(room, cohort) for room in ROOMS for cohort in COHORTS]


def resolve_exit(current_room: str, user_input: str) -> Exit | None:
    """Resolve what a player typed to an exit from their room, or None if no match.

    Matching ignores case and surrounding whitespace, and accepts the thing_id
    ("EL"), the description ("EL_desc", later "blue door"), or the destination
    room name ("living room"). Whatever they typed, the returned Exit carries the
    canonical description, which is what the exit message announces.
    """
    exits = NAVIGATION_GRAPH.get(current_room)
    if not exits:
        return None

    needle = user_input.strip().lower()
    if not needle:
        return None

    for exit_ in exits.values():
        if needle in (exit_.thing_id.lower(), exit_.thing.lower(), exit_.destination.lower()):
            return exit_
    return None


def find_exit(current_room: str, user_input: str) -> str | None:
    """Destination room for what a player typed, or None. See resolve_exit."""
    resolved = resolve_exit(current_room, user_input)
    return resolved.destination if resolved else None


def validate_graph() -> list[str]:
    """Return a list of structural problems with NAVIGATION_GRAPH; empty means sound.

    Run as a startup self-check so a typo in the layout surfaces immediately rather
    than as a player hitting a dead end mid-game.
    """
    problems: list[str] = []
    known = set(ROOMS)

    for room in ROOMS:
        if room not in NAVIGATION_GRAPH:
            problems.append(f"{room} has no entry in NAVIGATION_GRAPH")

    for room, exits in NAVIGATION_GRAPH.items():
        if room not in known:
            problems.append(f"NAVIGATION_GRAPH has unknown room {room!r}")
        for thing_id, exit_ in exits.items():
            if thing_id != exit_.thing_id:
                problems.append(f"{room}: key {thing_id!r} does not match its exit's id {exit_.thing_id!r}")
            destination = exit_.destination
            if destination not in known:
                problems.append(f"{room}/{thing_id} leads to unknown room {destination!r}")
                continue
            # The spec states every exit is bidirectional.
            returns = {e.destination for e in NAVIGATION_GRAPH.get(destination, {}).values()}
            if room not in returns:
                problems.append(f"{room} -> {destination} has no return exit")

    # Within one room, no two exits may share a description or a player's input
    # would be ambiguous. (Across rooms it is fine: the player is only ever in one.)
    for room, exits in NAVIGATION_GRAPH.items():
        things = [e.thing.lower() for e in exits.values()]
        for dup in {t for t in things if things.count(t) > 1}:
            problems.append(f"{room} has two exits described as {dup!r}")

    # Every room must be reachable from the start, or a player could be stranded.
    seen, queue = {STARTING_ROOM}, [STARTING_ROOM]
    while queue:
        for exit_ in NAVIGATION_GRAPH.get(queue.pop(), {}).values():
            if exit_.destination not in seen:
                seen.add(exit_.destination)
                queue.append(exit_.destination)
    for room in known - seen:
        problems.append(f"{room} is unreachable from {STARTING_ROOM}")

    return problems


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
    locations: list[tuple[int, str, str]],
) -> InitResult:
    """Delete every thread in the channel and recreate the full set of 18.

    `locations` is (user_id, cohort, current_room) for each player with game state.
    After the threads exist, each player is re-added to the thread for the room they
    were in, which is what makes the command rerunnable without stranding anyone -
    the database, not Discord, is the source of truth for who belongs where.
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
    for name in all_thread_names():
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
    for user_id, cohort, room in locations:
        try:
            name = get_thread_name(room, cohort)
        except ValueError as exc:
            errors.append(f"player {user_id}: {exc}")
            continue

        thread = threads.get(name)
        if thread is None:
            errors.append(f"player {user_id}: thread {name!r} was not created")
            continue

        try:
            await thread.add_user(discord.Object(id=user_id))
            restored += 1
        except discord.HTTPException as exc:
            errors.append(f"could not restore player {user_id} to {name!r}: {exc}")
            log.warning("Failed to restore player %s to %s", user_id, name, exc_info=True)

    log.info(
        "Haunted House initialized with %d threads in %s (deleted %d, restored %d players)",
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


async def unarchive_all(channel: discord.TextChannel) -> tuple[int, list[str]]:
    """Revive every archived house thread. Returns (revived count, errors).

    Discord's longest auto-archive is 7 days, so a room with no traffic for a week
    would archive and drop out of the channel's active list. Running this on a
    schedule keeps all 18 rooms permanently open.
    """
    wanted = set(all_thread_names())
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


async def get_thread_by_room_and_cohort(
    channel: discord.TextChannel, room_name: str, cohort: str
) -> discord.Thread | None:
    """Find the thread for a room/cohort pair by name.

    Searches archived threads as well as active ones: `channel.threads` omits
    archived threads, so an active-only lookup would fail during the window between
    a thread archiving and the next keep-alive pass reviving it.
    """
    name = get_thread_name(room_name, cohort)
    for thread in await _existing_threads(channel):
        if thread.name == name:
            return thread
    return None
