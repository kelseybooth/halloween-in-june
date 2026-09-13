"""Halloween cat petting bot - MVP (Phase 1).

Slash commands:
  /pet    - pet the cat, increments a persistent per-user counter
  /stats  - show your pet total
"""

import logging
import os
import random
import sys
from datetime import time as dt_time
from typing import NamedTuple

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError

import database
import house_utils

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    stream=sys.stdout,  # Railway captures stdout for its log dashboard
)
log = logging.getLogger("catbot")

# TEMPORARY (testing): append the relationship score, the mood weighting that
# produced this reaction, and the pet count to every /pet reply. Flip to False
# to return to the plain response, or delete the _debug_lines() call below.
SHOW_DEBUG_INFO = True

# Placeholder copy - writers will replace these in Phase 2.
FRIENDLY_RESPONSES = [
    "The cat purrs contentedly as you pet it, tail curling like smoke.",
    "The cat meows and rubs against your leg, eyes glinting in the dark.",
    "The cat stretches, blinks slowly at you, and vanishes for just a second.",
]

STANDOFFISH_RESPONSES = [
    "The cat meows incessantly until you pet it again.",
    "The cat startles, hissing at you.",
    "The cat gives you a warning bat with its paw.",
]

PET_RESPONSES = FRIENDLY_RESPONSES + STANDOFFISH_RESPONSES

# Mood weighting: the cat tires of being pestered. A user arriving with no recent
# pets gets BASE_FRIENDLY_CHANCE; every pet already inside
# database.RECENT_PET_WINDOW subtracts DECAY_PER_RECENT_PET points. Go quiet for
# ten minutes and the window empties, restoring the cat's patience.
BASE_FRIENDLY_CHANCE = 70
DECAY_PER_RECENT_PET = 10

# How far one reaction moves the relationship meter.
RELATIONSHIP_STEP = 5

DB_ERROR_MESSAGE = (
    "The cat slipped into the shadows and I lost track of it. "
    "Something went wrong reaching the database - please try again in a moment."
)

GENERIC_ERROR_MESSAGE = "An error occurred. Try again."
MOVE_ERROR_MESSAGE = "An error occurred while moving between rooms. Try again."


class Reaction(NamedTuple):
    """A chosen response plus the weighting that produced it."""

    text: str
    friendly: bool
    chance: int


def friendly_chance(recent_pets: int) -> int:
    """Percentage chance of a friendly response, floored at zero.

    From the 7th recent pet onward this is 0 and the cat is reliably standoffish
    until the window clears.
    """
    return max(0, BASE_FRIENDLY_CHANCE - DECAY_PER_RECENT_PET * recent_pets)


def choose_response(recent_pets: int, rng=random) -> Reaction:
    """Pick a response, weighted by how much this user has been pestering the cat.

    `rng` is injectable so the weighting can be exercised deterministically.
    """
    chance = friendly_chance(recent_pets)
    if rng.random() * 100 < chance:
        return Reaction(rng.choice(FRIENDLY_RESPONSES), True, chance)
    return Reaction(rng.choice(STANDOFFISH_RESPONSES), False, chance)


def _debug_lines(reaction: Reaction, recent: int, relationship: int) -> str:
    """TEMPORARY (testing) diagnostics appended to /pet replies."""
    mood = "friendly" if reaction.friendly else "standoffish"
    delta = RELATIONSHIP_STEP if reaction.friendly else -RELATIONSHIP_STEP
    return (
        "\n\n`[testing]`"
        f"\n`mood:` {mood} ({delta:+d}) - {reaction.chance}% friendly chance"
        f" after {recent} recent pet(s)"
        f"\n`relationship:` {relationship} / {database.RELATIONSHIP_MAX}"
    )


class CatBot(commands.Bot):
    def __init__(self) -> None:
        # Slash commands need no privileged intents; defaults keep the bot lightweight.
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self) -> None:
        """Runs once before the gateway connects - open the DB and register commands."""
        await database.init_db()

        # A broken layout would surface as a player hitting a dead end mid-game,
        # so check it once at startup instead.
        for problem in house_utils.validate_graph():
            log.error("Navigation graph problem: %s", problem)

        # Settle any nights the bot was offline for before serving commands.
        caught_up = await database.run_pending_decay()
        if caught_up:
            log.info("Startup decay settled %d relationship(s)", len(caught_up))
        nightly_decay.start()
        keep_threads_alive.start()

        # Global syncs can take up to an hour to propagate. Setting GUILD_ID copies
        # the commands into one server instead, where they appear immediately - much
        # faster to iterate on locally. Leave it unset in production.
        guild_id = os.getenv("GUILD_ID", "").strip()
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d command(s) to guild %s (instant)", len(synced), guild_id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d command(s) globally (may take up to an hour)", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id: %s)", self.user, self.user.id)

        # Say up front what the haunted house is missing, rather than letting it
        # surface later as an opaque "Missing Access" error mid-command.
        for guild in self.guilds:
            # Logged so GUILD_ID can be set without hunting for it in Discord's UI.
            log.info("In guild %r (GUILD_ID=%s)", guild.name, guild.id)

            channel = house_utils.find_channel(guild)
            if channel is None:
                log.info(
                    "%s has no #%s channel yet - create it before running "
                    "/initialize-haunted-house",
                    guild.name,
                    house_utils.HALLOWEEN_CHANNEL_NAME,
                )
                continue
            missing = house_utils.missing_permissions(channel)
            if missing:
                log.warning(
                    "In %s, the bot is missing these permissions on #%s: %s. "
                    "Grant them or the haunted house commands will fail.",
                    guild.name,
                    channel.name,
                    ", ".join(missing),
                )

        log.info("Ready - try /pet in your server")

    async def close(self) -> None:
        """Graceful shutdown: stop the scheduler, release the pool, then disconnect."""
        nightly_decay.cancel()
        keep_threads_alive.cancel()
        await database.close_db()
        await super().close()


bot = CatBot()


# discord.py handles the timezone maths, waking the loop at 00:00 Pacific whether
# that is currently PST or PDT.
@tasks.loop(time=dt_time(hour=0, minute=0, tzinfo=database.PACIFIC))
async def nightly_decay() -> None:
    """Drift idle players back toward a neutral relationship each midnight."""
    try:
        changes = await database.run_pending_decay()
        for change in changes:
            log.info(
                "Decay %s: user %s in guild %s: %s -> %s",
                change.day,
                change.user_id,
                change.guild_id,
                change.before,
                change.after,
            )
    except SQLAlchemyError:
        # Already logged with a traceback; swallow so the loop survives to retry
        # tomorrow rather than dying permanently on one bad night.
        log.error("Nightly decay run failed; will retry at the next midnight")


@nightly_decay.before_loop
async def _before_nightly_decay() -> None:
    await bot.wait_until_ready()


# Discord's longest auto-archive is 7 days, so a daily sweep is comfortably ahead
# of any room going quiet long enough to archive.
@tasks.loop(hours=24)
async def keep_threads_alive() -> None:
    """Keep every haunted house thread permanently open.

    Rooms are meant to stay available regardless of how long they sit idle, and
    Discord offers no auto-archive setting long enough to express that, so archived
    rooms are revived here instead.
    """
    for guild in bot.guilds:
        channel = house_utils.find_channel(guild)
        if channel is None:
            continue
        try:
            revived, errors = await house_utils.unarchive_all(channel)
        except discord.Forbidden:
            log.warning("No permission to manage threads in #%s (%s)", channel.name, guild.name)
            continue
        except discord.HTTPException:
            log.exception("Keep-alive sweep failed in %s", guild.name)
            continue

        for err in errors:
            log.warning("Keep-alive: %s", err)
        if revived:
            log.info("Keep-alive revived %d thread(s) in %s", revived, guild.name)


@keep_threads_alive.before_loop
async def _before_keep_alive() -> None:
    await bot.wait_until_ready()


@bot.tree.command(name="pet", description="Pet the cat.")
@app_commands.guild_only()
async def pet(interaction: discord.Interaction) -> None:
    # Defer first: the DB round trip can exceed Discord's 3s interaction deadline.
    await interaction.response.defer()
    try:
        result = await database.increment_pet_count(interaction.user.id, interaction.guild_id)
        reaction = choose_response(result.recent)
        delta = RELATIONSHIP_STEP if reaction.friendly else -RELATIONSHIP_STEP
        relationship = await database.adjust_relationship(interaction.user.id, interaction.guild_id, delta)
    except SQLAlchemyError:
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    message = f"{reaction.text}\n\nTotal pets: {result.total}"
    if SHOW_DEBUG_INFO:
        message += _debug_lines(reaction, result.recent, relationship)
    await interaction.followup.send(message)


@bot.tree.command(
    name="initialize-haunted-house",
    description="(Admin) Rebuild every haunted house thread from scratch.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def initialize_haunted_house(interaction: discord.Interaction) -> None:
    """Delete and recreate all 18 room threads, restoring players to their rooms.

    Rerunnable by design: players are re-added afterwards from the database, so a
    rebuild does not strand anyone in a thread that no longer exists.
    """
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command only works inside a server.", ephemeral=True
        )
        return

    # Deleting and creating 18 threads takes far longer than Discord's 3s deadline.
    await interaction.response.defer(ephemeral=True, thinking=True)

    channel = house_utils.find_channel(interaction.guild)
    if channel is None:
        await interaction.followup.send(
            f"I couldn't find a #{house_utils.HALLOWEEN_CHANNEL_NAME} channel. "
            "Create it first, then run this again.",
            ephemeral=True,
        )
        return

    missing = house_utils.missing_permissions(channel)
    if missing:
        await interaction.followup.send(
            f"I'm missing these permissions on #{channel.name}:\n"
            + "\n".join(f"- {name}" for name in missing)
            + "\n\nGrant them to my role there, then run this again.",
            ephemeral=True,
        )
        return

    try:
        locations = await database.get_all_player_locations(interaction.guild_id)
        # Room rows hold writer descriptions; make sure each room has one to
        # fill in. Existing descriptions are never overwritten by a rebuild.
        await database.seed_rooms(interaction.guild_id, house_utils.ROOMS)
    except SQLAlchemyError:
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    try:
        result = await house_utils.initialize_threads(channel, locations)
    except discord.Forbidden:
        log.exception("Missing permissions to manage threads in #%s", channel.name)
        await interaction.followup.send(
            f"I don't have permission to manage threads in #{channel.name}. "
            "I need Manage Threads and Create Private Threads there.",
            ephemeral=True,
        )
        return
    except discord.HTTPException:
        log.exception("Thread initialization failed")
        await interaction.followup.send(
            "Something went wrong talking to Discord. Check the logs and try again.",
            ephemeral=True,
        )
        return

    lines = [
        f"Haunted House initialized with {result.created} threads in **{interaction.guild.name}**.",
        f"- deleted {result.deleted} existing thread(s)",
        f"- restored {result.restored} player(s) to their current room",
    ]
    if result.errors:
        lines.append(f"\n**{len(result.errors)} problem(s):**")
        # Discord caps messages at 2000 characters; show a few and log the rest.
        lines.extend(f"- {err}" for err in result.errors[:5])
        if len(result.errors) > 5:
            lines.append(f"- ...and {len(result.errors) - 5} more (see logs)")

    await interaction.followup.send("\n".join(lines), ephemeral=True)


@initialize_haunted_house.error
async def _initialize_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    """Turn the permission check failure into a clear message rather than a traceback."""
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You need to be a server administrator to run this.", ephemeral=True
        )
        return
    raise error


# TODO(Phase 3): remove this command. It exists so testers can self-onboard without
# an admin; a proper game start flow replaces it.
@bot.tree.command(
    name="enter-entryway",
    description="Enter the haunted house and begin in the Entryway.",
)
@app_commands.guild_only()
async def enter_entryway(interaction: discord.Interaction) -> None:
    """Enrol the player, assign a cohort, and place them in their Entryway thread."""
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command only works inside a server.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    user = interaction.user

    channel = house_utils.find_channel(interaction.guild)
    if channel is None:
        await interaction.followup.send(
            f"There's no #{house_utils.HALLOWEEN_CHANNEL_NAME} channel yet. "
            "An admin needs to create it and run `/initialize-haunted-house`.",
            ephemeral=True,
        )
        return

    # The cohort is chosen by the database to keep this server's groups balanced,
    # so it is not known until enrolment. Check that BOTH Entryway threads exist
    # first: enrolling a player and then discovering the house was never built
    # would leave them marked as inside a room that does not exist.
    try:
        entryways = {
            cohort: await house_utils.get_thread_by_room_and_cohort(
                channel, house_utils.STARTING_ROOM, cohort
            )
            for cohort in house_utils.COHORTS
        }
    except discord.HTTPException:
        log.exception("Could not look up the Entryway threads")
        await interaction.followup.send(GENERIC_ERROR_MESSAGE, ephemeral=True)
        return

    if any(thread is None for thread in entryways.values()):
        await interaction.followup.send(
            "The haunted house hasn't been built yet. "
            "Ask an admin to run `/initialize-haunted-house`.",
            ephemeral=True,
        )
        return

    try:
        # All rooms start unlocked during the testing phase; Phase 3 gates them
        # behind puzzles and this becomes just the starting room.
        cohort = await database.start_game(
            user.id, interaction.guild_id, house_utils.STARTING_ROOM, list(house_utils.ROOMS)
        )
    except SQLAlchemyError:
        await interaction.followup.send(GENERIC_ERROR_MESSAGE, ephemeral=True)
        return

    if cohort is None:
        await interaction.followup.send("You're already in the haunted house!", ephemeral=True)
        return

    thread = entryways[cohort]

    try:
        await house_utils.add_player_to_thread(thread, user.id)
        await thread.send(
            f"Welcome, {user.mention}! You arrive at the entrance to the haunted "
            "house. The cat appears at your side."
        )
    except discord.HTTPException:
        # Undo the enrolment so the player can retry, rather than being recorded as
        # inside a house they were never actually let into.
        log.exception("Failed to place %s in the Entryway; rolling back", user.id)
        try:
            await database.delete_game_state(user.id, interaction.guild_id)
        except SQLAlchemyError:
            log.error("Rollback failed for %s - player may be stuck enrolled", user.id)
        await interaction.followup.send(GENERIC_ERROR_MESSAGE, ephemeral=True)
        return

    await interaction.followup.send(
        f"You've entered the haunted house! Head to {thread.mention} to begin.",
        ephemeral=True,
    )


@bot.tree.command(name="use", description="Attempt to use an object or exit.")
@app_commands.guild_only()
@app_commands.describe(thing="The object or exit to use.")
async def use(interaction: discord.Interaction, thing: str) -> None:
    """Move the player through an exit into the adjoining room.

    Ordering note: the spec's numbered steps post the exit message and remove the
    player before adding them to the destination, but its error handling requires
    that a failed add must not have already removed them. The latter wins - the
    player is added to the destination first, so any failure leaves them exactly
    where they were.
    """
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command only works inside a server.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    user = interaction.user

    try:
        state = await database.get_game_state(user.id, interaction.guild_id)
    except SQLAlchemyError:
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    if state is None:
        await interaction.followup.send(
            "You're not in the haunted house yet. Use `/enter-entryway` first.",
            ephemeral=True,
        )
        return

    chosen_exit = house_utils.resolve_exit(state.current_room, thing)
    if chosen_exit is None:
        await interaction.followup.send("You don't see that exit here.", ephemeral=True)
        return

    destination = chosen_exit.destination
    if destination not in state.rooms_unlocked:
        await interaction.followup.send("You can't access that room yet.", ephemeral=True)
        return

    channel = house_utils.find_channel(interaction.guild)
    if channel is None:
        await interaction.followup.send(
            f"There's no #{house_utils.HALLOWEEN_CHANNEL_NAME} channel. "
            "Ask an admin to run `/initialize-haunted-house`.",
            ephemeral=True,
        )
        return

    try:
        destination_thread = await house_utils.get_thread_by_room_and_cohort(
            channel, destination, state.cohort
        )
        origin_thread = await house_utils.get_thread_by_room_and_cohort(
            channel, state.current_room, state.cohort
        )
    except discord.HTTPException:
        log.exception("Could not look up room threads")
        await interaction.followup.send(MOVE_ERROR_MESSAGE, ephemeral=True)
        return

    if destination_thread is None:
        await interaction.followup.send(
            f"I couldn't find the thread for {destination}. "
            "Ask an admin to run `/initialize-haunted-house`.",
            ephemeral=True,
        )
        return

    # Add before removing: if this fails, the player has not been moved or removed
    # from anywhere, so they are exactly where they started and can retry.
    try:
        await house_utils.add_player_to_thread(destination_thread, user.id)
    except discord.HTTPException:
        log.exception("Failed to add %s to %s", user.id, destination)
        await interaction.followup.send(MOVE_ERROR_MESSAGE, ephemeral=True)
        return

    try:
        await database.update_current_room(user.id, interaction.guild_id, destination)
    except SQLAlchemyError:
        # Undo the add so Discord and the database do not disagree about where
        # this player is.
        try:
            await house_utils.remove_player_from_thread(destination_thread, user.id)
        except discord.HTTPException:
            log.exception("Rollback failed: %s left in %s", user.id, destination)
        await interaction.followup.send(MOVE_ERROR_MESSAGE, ephemeral=True)
        return

    # From here the move has happened. The remaining steps are presentational, so
    # a failure is logged rather than surfaced - the player has already moved.
    if origin_thread is not None:
        try:
            await origin_thread.send(f"{user.mention} exits via {chosen_exit.thing}.")
        except discord.HTTPException:
            log.warning("Could not post exit message in %s", state.current_room, exc_info=True)

        try:
            await house_utils.remove_player_from_thread(origin_thread, user.id)
        except discord.HTTPException:
            log.warning("Could not remove %s from %s", user.id, state.current_room, exc_info=True)

    try:
        await destination_thread.send(f"{user.mention} enters {destination}")
    except discord.HTTPException:
        log.warning("Could not post entry message in %s", destination, exc_info=True)

    await interaction.followup.send(
        f"You head to {destination_thread.mention}.", ephemeral=True
    )


GENERIC_ROOM_DESCRIPTION = "You see a room."
NOT_IN_ROOM_MESSAGE = "You must be in a room to look around."
CANT_LOOK_MESSAGE = "You can't look at that."
INVENTORY_ERROR_MESSAGE = "Couldn't retrieve your inventory. Try again."


@bot.tree.command(name="look", description="Look around the room, or at a specific thing.")
@app_commands.guild_only()
@app_commands.describe(thing="What to look at. Leave empty to look around the room.")
async def look(interaction: discord.Interaction, thing: str | None = None) -> None:
    """Describe the player's current room, or one thing in it or in their bag.

    Replies are ephemeral: /look can be typed in any channel of the server, and a
    public reply would leak room and thing descriptions to people who are not
    playing. It also keeps a busy room thread from filling with everyone's looks.
    """
    await interaction.response.defer(ephemeral=True, thinking=True)
    user = interaction.user

    try:
        state = await database.get_game_state(user.id, interaction.guild_id)
    except SQLAlchemyError:
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    if state is None:
        await interaction.followup.send(NOT_IN_ROOM_MESSAGE, ephemeral=True)
        return

    if thing is None or not thing.strip():
        try:
            description = await database.get_room_description(
                interaction.guild_id, state.current_room
            )
        except SQLAlchemyError:
            await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
            return
        await interaction.followup.send(description or GENERIC_ROOM_DESCRIPTION, ephemeral=True)
        return

    try:
        found = await database.look_at_thing(
            user.id, interaction.guild_id, state.current_room, thing
        )
    except SQLAlchemyError:
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    if found is None:
        await interaction.followup.send(CANT_LOOK_MESSAGE, ephemeral=True)
        return

    # A thing with no description yet still exists; say so rather than send nothing.
    text = found.description or f"You see {thing.strip()}."
    if found.count > 1:
        text += f" There are {found.count}."
    await interaction.followup.send(text, ephemeral=True)


@bot.tree.command(name="inventory", description="See what you're carrying.")
@app_commands.guild_only()
async def inventory(interaction: discord.Interaction) -> None:
    """List the player's carried things in this server, grouped and counted."""
    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        items = await database.get_inventory(interaction.user.id, interaction.guild_id)
    except SQLAlchemyError:
        await interaction.followup.send(INVENTORY_ERROR_MESSAGE, ephemeral=True)
        return

    if not items:
        await interaction.followup.send("Your inventory is empty.", ephemeral=True)
        return

    lines = ["Your inventory:"]
    lines.extend(f"- {name} ({count})" for name, count in items)
    lines.append(f"\nTotal items: {sum(count for _, count in items)}")
    await interaction.followup.send("\n".join(lines), ephemeral=True)


# --- Admin helpers for populating content without touching the database -------
# TESTING TOOLS, not the long-term source of content. Game mechanics depend on
# specific things existing in specific rooms, which hand entry per server cannot
# guarantee; Phase 3+ loads every server's rooms, things and exit descriptions
# from one content file (see LOOK_COMMAND_SPEC.md, "Content Loading"). Keep these
# as debugging aids until then, and consider removing them after.
#
# Both act on the admin's *current room*, so an admin walks to a room and
# describes it or drops things into it from inside the game.


@bot.tree.command(
    name="add-thing",
    description="(Admin, testing) Place a thing in the room you're standing in.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    name="What players will type to look at it, e.g. 'cat food'.",
    description="What they see when they look. Optional.",
)
async def add_thing(
    interaction: discord.Interaction, name: str, description: str | None = None
) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)

    if not name.strip():
        await interaction.followup.send("The thing needs a name.", ephemeral=True)
        return

    try:
        state = await database.get_game_state(interaction.user.id, interaction.guild_id)
        if state is None:
            await interaction.followup.send(
                "Enter the house first (`/enter-entryway`) and walk to the room "
                "you want to place it in.",
                ephemeral=True,
            )
            return
        thing_id = await database.add_thing(
            interaction.guild_id, state.current_room, name, description
        )
    except SQLAlchemyError:
        await interaction.followup.send(GENERIC_ERROR_MESSAGE, ephemeral=True)
        return

    await interaction.followup.send(
        f"Placed **{name.strip()}** in {state.current_room} (thing_id {thing_id}).",
        ephemeral=True,
    )


@bot.tree.command(
    name="add-room-desc",
    description="(Admin, testing) Set the description of the room you're standing in.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(description="What players see when they /look here.")
async def add_room_desc(interaction: discord.Interaction, description: str) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        state = await database.get_game_state(interaction.user.id, interaction.guild_id)
        if state is None:
            await interaction.followup.send(
                "Enter the house first (`/enter-entryway`) and walk to the room "
                "you want to describe.",
                ephemeral=True,
            )
            return
        await database.set_room_description(
            interaction.guild_id, state.current_room, description.strip()
        )
    except SQLAlchemyError:
        await interaction.followup.send(GENERIC_ERROR_MESSAGE, ephemeral=True)
        return

    await interaction.followup.send(
        f"Description set for **{state.current_room}**. Try `/look`.", ephemeral=True
    )


@add_thing.error
@add_room_desc.error
async def _content_admin_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You need to be a server administrator to run this.", ephemeral=True
        )
        return
    raise error


@bot.tree.command(name="stats", description="See how many times you've petted the cat.")
@app_commands.guild_only()
async def stats(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    try:
        count = await database.get_pet_count(interaction.user.id, interaction.guild_id)
        relationship = await database.get_relationship(interaction.user.id, interaction.guild_id)
    except SQLAlchemyError:
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    if count == 0:
        await interaction.followup.send(
            "You haven't petted the cat yet. Try `/pet` - it's waiting for you."
        )
        return

    await interaction.followup.send(
        f"Your cat petting stats:\nTotal pets: {count}\nRelationship: {relationship}"
    )


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    """Catch-all so an unexpected failure never leaves the user staring at 'thinking...'."""
    log.exception("Unhandled error in command %s", interaction.command, exc_info=error)
    message = "Something went wrong. Please try again."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        log.error("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
        sys.exit(1)

    try:
        bot.run(token, log_handler=None)  # log_handler=None: reuse our logging config
    except discord.LoginFailure:
        log.error("Discord rejected the token. Check DISCORD_TOKEN in your .env file.")
        sys.exit(1)
    except database.StartupError as exc:
        # Say exactly what to do instead of burying it in a traceback.
        log.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
