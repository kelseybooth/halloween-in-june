"""Halloween cat petting bot - MVP (Phase 1).

Slash commands:
  /pet    - pet the cat, increments a persistent per-user counter
  /stats  - show your pet total
"""

import logging
import os
import random
import sys
from datetime import time as dt_time, timedelta
from typing import NamedTuple

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError

import achievements
import alexa
import content
import content_loader
import craving
import database
import house_utils
import phrasing
import reach
import resolve
import restocking
import states
import triggers
import world

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    stream=sys.stdout,  # Railway captures stdout for its log dashboard
)
log = logging.getLogger("catbot")

# Append the relationship score, the mood weighting that produced this reaction,
# and the pet count to every /pet reply. A local testing aid: it shows players
# the dice behind the cat, which is exactly what the mechanic relies on not
# doing. Off in anything players can reach.
#
# test_debug_output_is_off asserts this is False, so turning it on for a local
# session and forgetting fails the suite before the push rather than after.
SHOW_DEBUG_INFO = False

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

# How often to look for restock occurrences that have come due. Occurrences
# are scattered through the day, so a once-a-day job would deliver eight
# bottles in a heap rather than eight times.
RESTOCK_SWEEP_MINUTES = 10

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


async def _check_achievement_registry() -> None:
    """Refuse to serve commands if the file and the registry disagree.

    Loud beats silent. The alternative is an achievement nobody can earn, or
    an award with no name to announce, and either one surfaces weeks later as
    a player asking why nothing happened.
    """
    parsed = content.load_files()
    problems = achievements.registration_problems(parsed.achievement_ids)
    if not problems:
        log.info("All %d achievements are wired up", len(parsed.achievements))
        return
    for problem in problems:
        log.error("%s", problem)
    raise RuntimeError(
        f"{len(problems)} achievement registration problem(s); see the log above"
    )


async def load_content_at_startup() -> None:
    """Load the content files, and keep serving the old content if they are bad.

    This is how Railway gets content: the files ship with the code, and there is
    no shell there to run load_content.py from.

    A bad file does not stop the bot. Whatever is in the content tables came from
    the last good load and still works, so a writer's typo costs the new text
    rather than the whole game - "a half-loaded house is worse than a stale one"
    cuts this way too. The failure is logged at error level, and
    `python load_content.py --check` reports it in full.

    Orphans are ignored here rather than refused, for the same reason: refusing
    would let a thing removed from the files take the bot down at the next
    restart, which is worse than a stale row nobody can see. Each one is logged,
    and the script reports them properly.
    """
    try:
        parsed = content.load()
    except content.ContentError as exc:
        log.error(
            "Content files did not load, so the database keeps the content it "
            "already had. Run `python load_content.py --check` for the full "
            "report. %s",
            exc,
        )
        return

    try:
        report = await content_loader.load_content(parsed, allow_orphans=True)
    except SQLAlchemyError:
        log.exception("Content load failed against the database")
        return

    log.info("Content loaded. %s", report.summary().replace(chr(10), " | "))

    # Positions were stored as room names before 2b and as room ids after. This
    # needs the rooms in place to translate against, so it runs here rather than
    # with the schema migrations.
    try:
        await database.migrate_room_names_to_ids()
    except SQLAlchemyError:
        log.exception("Could not migrate player positions to room ids")
    for orphan in report.orphans_ignored:
        log.warning(
            "Thing %r is gone from the content files but world state still refers "
            "to it; run load_content.py to see who holds it",
            orphan,
        )


class CatBot(commands.Bot):
    def __init__(self) -> None:
        # Slash commands need no privileged intents, but Alexa does: without
        # message_content every message arrives with an empty body and she
        # never answers anybody. It is enabled in the developer portal, which
        # is necessary and not sufficient - it has to be asked for here too.
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        """Runs once before the gateway connects - open the DB and register commands."""
        await database.init_db()

        # The layout is content now, so a broken one is caught by the loader's
        # validation rather than by a separate graph check here.
        await load_content_at_startup()

        # Wire the thirty-five conditions, then check both directions against
        # the file. A row nobody registered can never be announced, and a
        # trigger with no row would award something with no name - neither
        # raises at runtime, so a mismatch stops the boot instead.
        triggers.register_all()
        await _check_achievement_registry()

        # Settle any nights the bot was offline for before serving commands.
        caught_up = await database.run_pending_decay()
        if caught_up:
            log.info("Startup decay settled %d relationship(s)", len(caught_up))
        nightly_decay.start()
        keep_threads_alive.start()
        restock_sweep.start()

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

    for guild in bot.guilds:
        # No player and no interaction: whatever listens here is looking at the
        # server rather than at somebody's action.
        await _fire(
            achievements.Context(guild_id=guild.id, hook="on_midnight"),
            guild=guild,
        )


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
    try:
        # One read for the whole sweep: the room list is the same everywhere, and
        # it has to match what initialize_threads built or rooms archive and stay
        # archived a week after launch.
        room_names = await resolve.room_names()
    except SQLAlchemyError:
        log.exception("Keep-alive sweep could not read the room list")
        return

    if not room_names:
        return

    for guild in bot.guilds:
        channel = house_utils.find_channel(guild)
        if channel is None:
            continue
        try:
            revived, errors = await house_utils.unarchive_all(channel, room_names)
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


@tasks.loop(minutes=RESTOCK_SWEEP_MINUTES)
async def restock_sweep() -> None:
    """Place whatever the restock schedules say has come due.

    Runs often rather than at a fixed hour, because occurrences are scattered
    through the day - eight bottles arrive at eight different moments, and a
    once-a-day job would deliver them in a heap at midnight.

    Nothing is lost between sweeps or across a restart: each schedule records
    the last occurrence it applied, and the next sweep asks what should have
    happened since. A bot that was down for a day places that day's arrivals
    when it comes back rather than skipping them.
    """
    guild_ids = [guild.id for guild in bot.guilds]
    if not guild_ids:
        return

    try:
        report = await restocking.run_all(guild_ids)
    except SQLAlchemyError:
        log.exception("Restock sweep failed")
        return

    if report.placed:
        log.info("%s", report.summary())


@restock_sweep.before_loop
async def _before_restock() -> None:
    await bot.wait_until_ready()


# --------------------------------------------------------------------------
# Two event handlers that are not commands
#
# Neither registers a slash command, which is why the command list stays at
# ten. Talking to a speaker by typing `/use alexa` would be a strange way to
# talk to a speaker, and a reaction carries no interaction token at all.
# --------------------------------------------------------------------------

# The thing whose text Alexa speaks with, and the state she uses once a player
# has asked her to pass the message on.
ALEXA_THING = "alexa"
ALEXA_REMINDED = "reminded"


async def _is_game_thread(channel) -> bool:
    """Whether this is one of the house's room threads.

    Scoped deliberately: Alexa answering in every channel of the server would
    make her a nuisance rather than a fixture in the rooms.
    """
    if not isinstance(channel, discord.Thread):
        return False
    parent = channel.parent
    if parent is None or parent.name != house_utils.HALLOWEEN_CHANNEL_NAME:
        return False
    try:
        return channel.name in set(await resolve.room_names())
    except SQLAlchemyError:
        log.exception("Could not check whether %s is a game thread", channel.name)
        return False


@bot.event
async def on_message(message: discord.Message) -> None:
    """Answer anybody talking to the smart speaker.

    Nothing is stored. The handler reads what was typed, decides which of two
    replies it earns, and forgets it - the Message Content intent changes what
    the bot receives, not what it keeps.
    """
    if message.author.bot or message.guild is None:
        return

    if not alexa.is_addressed(message.content):
        return
    if not await _is_game_thread(message.channel):
        return

    try:
        if alexa.is_message_for_david(message.content):
            # The words for this live in the content files as a `reminded`
            # state row on alexa. Until a writer adds one, she falls back to
            # her stock non-answer rather than the bot inventing dialogue.
            reply = await phrasing.say(
                message.guild.id, ALEXA_THING, "use", state=ALEXA_REMINDED
            )
            if not reply:
                log.warning(
                    "No `%s` state text for %s: a player asked Alexa to pass the "
                    "message to David and got her stock reply instead. One row in "
                    "thing_text.tsv fixes it.",
                    ALEXA_REMINDED,
                    ALEXA_THING,
                )
                reply = await phrasing.say(message.guild.id, ALEXA_THING, "use")
        else:
            reply = await phrasing.say(message.guild.id, ALEXA_THING, "use")
    except SQLAlchemyError:
        log.exception("Could not read Alexa's text")
        return

    if reply:
        try:
            await message.channel.send(reply)
        except discord.HTTPException:
            log.warning("Could not answer as Alexa", exc_info=True)

    await _fire(
        achievements.Context(
            guild_id=message.guild.id,
            hook="on_message",
            user_id=message.author.id,
            extra={"content": message.content},
        ),
        guild=message.guild,
    )


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
    """Judge a guess at the cat's craving.

    Raw rather than on_reaction_add: the latter only fires for messages still
    in the bot's cache, so every guess on anything posted before the last
    restart would do nothing at all and nobody would know why.
    """
    if payload.guild_id is None or payload.user_id == bot.user.id:
        return

    channel = bot.get_channel(payload.channel_id)
    if channel is None:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.HTTPException:
        return

    # Only on the bot's own messages: reacting to another player's line is a
    # conversation, not a guess.
    if message.author.id != bot.user.id:
        return

    try:
        guess = await craving.judge(
            payload.guild_id, payload.user_id, str(payload.emoji)
        )
    except SQLAlchemyError:
        log.exception("Could not judge a craving guess")
        return

    await _answer_guess(message, guess)

    # No interaction token here, so an earned description arrives by DM. It is
    # the same reason the craving's own confirmation is a public reaction.
    await _fire(
        achievements.Context(
            guild_id=payload.guild_id,
            hook="on_reaction",
            user_id=payload.user_id,
            extra={"emoji": str(payload.emoji), "guess": guess},
        ),
        guild=getattr(channel, "guild", None),
    )


async def _answer_guess(message: discord.Message, guess) -> None:
    """React with the bot's answer, if it has not already said it.

    Checks whether *the bot* is among a reaction's users rather than whether
    the emoji is present: a player can add any of the three by hand, and
    Discord merges identical emoji into one reaction with a count.
    """
    mine = {str(r.emoji) for r in message.reactions if r.me}

    async def react(emoji: str) -> None:
        if emoji in mine:
            return
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            log.warning("Could not add %s", emoji, exc_info=True)

    if guess.verdict is craving.CORRECT or guess.verdict == craving.CORRECT:
        # Public by design - a reaction carries no interaction token, so there
        # is no private confirmation available. The cat is the confirmation.
        await react(craving.FOUND)
        return

    if guess.verdict == craving.SAME_GROUP:
        await react(craving.RIGHT_GROUP)
        return

    # Discord caps a message at 20 distinct reactions. Spend the last one
    # saying "no more guesses here", or a correct guess in the final slot
    # would leave the bot no room to answer.
    if craving.FOUND not in mine and len(message.reactions) >= craving.MAX_REACTIONS - 1:
        await react(craving.NO_ROOM)


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

    await _fire(
        achievements.Context(
            guild_id=interaction.guild_id,
            hook="on_pet",
            user_id=interaction.user.id,
            extra={"total": result.total, "relationship": relationship},
        ),
        interaction=interaction,
    )


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
        rooms = await resolve.all_rooms()
        names_by_id = dict(rooms)
        # (user_id, room name) - house_utils works in thread names, not room ids.
        locations = [
            (user_id, names_by_id[room_id])
            for user_id, room_id in await database.get_all_player_locations(
                interaction.guild_id
            )
            if room_id in names_by_id
        ]
    except SQLAlchemyError:
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    if not rooms:
        await interaction.followup.send(
            "No rooms are loaded. The content files have not been read yet - "
            "check the logs, or run `python load_content.py --check`.",
            ephemeral=True,
        )
        return

    try:
        # Restock day numbers count from here, so a server that never records
        # this never restocks.
        await restocking.set_initialized_on(interaction.guild_id)
        # And this is where achievement names get posted, recorded now so the
        # announcement path never has to guess at a channel name.
        await database.set_announcement_channel(interaction.guild_id, channel.id)
    except SQLAlchemyError:
        log.exception("Could not record the initialization date")

    try:
        result = await house_utils.initialize_threads(
            channel, [name for _, name in rooms], locations
        )
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
    """Enrol the player and place them in the Entryway thread."""
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

    # Check the Entryway thread exists before enrolling anyone: enrolling a
    # player and then discovering the house was never built would leave them
    # marked as inside a room that does not exist.
    try:
        start_id = await resolve.starting_room()
        start_name = await resolve.room_name(start_id) if start_id else None
        if start_name is None:
            await interaction.followup.send(
                "No rooms are loaded yet. Ask an admin to check the logs.",
                ephemeral=True,
            )
            return
        thread = await house_utils.get_thread_for_room(channel, start_name)
    except discord.HTTPException:
        log.exception("Could not look up the Entryway thread")
        await interaction.followup.send(GENERIC_ERROR_MESSAGE, ephemeral=True)
        return

    if thread is None:
        await interaction.followup.send(
            "The haunted house hasn't been built yet. "
            "Ask an admin to run `/initialize-haunted-house`.",
            ephemeral=True,
        )
        return

    try:
        # Everything open at launch starts unlocked. The Secret Library does not:
        # it is found by climbing the oak and coming in through the window, and
        # the mechanism that records that is 2c.
        enrolled = await database.start_game(
            user.id,
            interaction.guild_id,
            start_id,
            await resolve.rooms_open_at_launch(),
        )
    except SQLAlchemyError:
        await interaction.followup.send(GENERIC_ERROR_MESSAGE, ephemeral=True)
        return

    if not enrolled:
        await interaction.followup.send("You're already in the haunted house!", ephemeral=True)
        return

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
    """Use something: an exit, a transform, something on a cooldown, or anything else.

    Four branches, taken in order. The reply is always private - a use is a
    small private moment, and making every one public would bury the thread.
    Movement is the exception in that it *also* posts in both rooms, because
    the people standing there need to see someone leave.

    What is deliberately absent is the two uses that change the world. Placing
    a plank counts toward nothing yet and graphite unjams nothing; both are
    Phase 2c.5, along with the public reply that placing a plank earns.
    """
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command only works inside a server.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    user, guild_id = interaction.user, interaction.guild_id

    try:
        state = await database.get_game_state(user.id, guild_id)
        if state is None:
            await interaction.followup.send(
                "You're not in the haunted house yet. Use `/enter-entryway` first.",
                ephemeral=True,
            )
            return

        found = await reach.find(guild_id, user.id, state.current_room, thing, reach.Scope.REACH)

        if isinstance(found, reach.Ambiguous):
            await interaction.followup.send(
                await phrasing.default_say(
                    "ambiguous.match", options=", ".join(found.options)
                ),
                ephemeral=True,
            )
            return

        if isinstance(found, reach.NotFound):
            key = "use_fail.absent" if found.exists_elsewhere else "unknown.noun"
            await interaction.followup.send(
                await phrasing.default_say(key, name=thing.strip()), ephemeral=True
            )
            return

        row = await phrasing.thing_row(found.thing_id)
        if row is None:
            await interaction.followup.send(
                await phrasing.default_say("use_fail.absent", name=found.name),
                ephemeral=True,
            )
            return

        wanted = states.required_things(row.requires)
        if wanted and not await database.carries_all(user.id, guild_id, wanted):
            # A gate, not a branch: it answers whether this player can do the
            # thing at all, so it is checked before working out what the thing
            # does. A refused use is not a use - nothing is recorded, nothing
            # is consumed, and no world effect fires.
            await interaction.followup.send(
                await phrasing.say(
                    guild_id, found.thing_id, "use_fail",
                    fallback="use_fail.default", name=found.name,
                ),
                ephemeral=True,
            )
            return

        if row.type == "exit":
            await _use_exit(interaction, state, found, row)
            return

        if row.transforms_to:
            await _use_transform(interaction, state, found, row)
            return

        if row.use_cooldown_hours:
            await _use_with_cooldown(interaction, state, found, row)
            return

        await _finish_use(interaction, state, found)
    except SQLAlchemyError:
        log.exception("Failed to use %r in guild %s", thing, guild_id)
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)


async def _finish_use(interaction, state, found) -> None:
    """Record the use, apply anything it changes, and say what happened.

    Every successful use comes through here, so the world effects cannot be
    wired into one branch and forgotten in another - and so the single public
    `/use` is decided in one place rather than by each branch remembering.
    """
    user, guild_id = interaction.user, interaction.guild_id
    await database.record_use(user.id, guild_id, found.thing_id)

    effect = await world.after_use(guild_id, user.id, found.thing_id, state.current_room)
    tokens = dict(effect.tokens) if effect else {}

    # The text is resolved *after* the effect, so a use that changes a state
    # can be described by the state it produced rather than the one it left.
    held = await states.in_force(guild_id, user.id)
    current = sorted(held)[0] if held else resolve.DEFAULT_STATE

    reply = await phrasing.say(
        guild_id, found.thing_id, "use", state=current,
        fallback="use.default", name=found.name, **tokens,
    )
    if effect and effect.announce:
        reply = f"{reply}\n\n{effect.announce}" if reply else effect.announce

    await interaction.followup.send(reply, ephemeral=True)

    if effect and effect.public:
        await _post_in_room(interaction, state.current_room, reply)

    await _fire(
        achievements.Context(
            guild_id=guild_id,
            hook="on_use",
            user_id=user.id,
            thing_id=found.thing_id,
            room_id=state.current_room,
        ),
        interaction=interaction,
    )


async def _fire(context, *, interaction=None, guild=None) -> None:
    """Run a hook, award what passed, and announce what this call created.

    One function for all nine hooks, so an achievement cannot be awarded in
    one call site and left unannounced in another - the same reason every
    world-changing use routes through `_finish_use`.

    Everything here is decoration on an action that has already committed, so
    nothing raises: a player who loses an achievement to a Discord hiccup can
    earn it next time, and a player whose `/take` returns an error has lost
    the thing.
    """
    try:
        earned = await achievements.fire(context)
    except Exception:
        log.exception("Achievement hook %s failed", context.hook)
        return

    for award in earned:
        await _announce(award, interaction=interaction, guild=guild)


async def _announce(award, *, interaction=None, guild=None) -> None:
    """The name in public, the description to the earner and nobody else.

    The award is already written. An announcement failure leaves it in place -
    `/stats` still shows it - which is why every branch here logs rather than
    raising.
    """
    if guild is None and interaction is not None:
        guild = interaction.guild
    if guild is None:
        log.warning("Earned %s with no guild to announce it in", award.achievement_id)
        return

    channel = await _announcement_channel(guild)
    if channel is not None:
        try:
            # The name only, including for a secret achievement - the name
            # appearing is itself the hint that something is there to find.
            await channel.send(award.name)
        except discord.HTTPException:
            log.warning("Could not announce %s", award.achievement_id, exc_info=True)

    if award.user_id is None:
        # A group achievement has no earner, so the description goes nowhere.
        # It still shows in every current member's /stats.
        return

    if interaction is not None:
        try:
            await interaction.followup.send(award.unlock, ephemeral=True)
        except discord.HTTPException:
            log.warning("Could not send %s privately", award.achievement_id, exc_info=True)
        return

    # No interaction token - a reaction or a message carries none - so the
    # description goes by DM. People close their DMs, and that is not an
    # error: /stats holds the description permanently. Never fall back to
    # posting it publicly, which would spoil a secret achievement for everyone.
    member = guild.get_member(award.user_id)
    if member is None:
        log.info("Player %s is not cached; no DM for %s", award.user_id, award.achievement_id)
        return
    try:
        await member.send(award.unlock)
    except discord.HTTPException:
        log.info(
            "Could not DM %s about %s; /stats still has it",
            award.user_id,
            award.achievement_id,
        )


async def _announcement_channel(guild):
    """Where this server's achievement names go.

    The channel the house was initialized in, by id rather than by name, so a
    rename does not silently stop the announcements. A server initialized
    before the id was recorded falls back to the name lookup.
    """
    try:
        channel_id = await database.announcement_channel(guild.id)
    except SQLAlchemyError:
        log.exception("Could not read the announcement channel for %s", guild.id)
        return None

    if channel_id is not None:
        channel = guild.get_channel(channel_id)
        if channel is not None:
            return channel
        log.warning("Announcement channel %s is gone in %s", channel_id, guild.id)
    return house_utils.find_channel(guild)


async def _post_in_room(interaction, room_id: str, message: str) -> None:
    """Echo a use into the room thread. Only the staircase does this."""
    if interaction.guild is None:
        return
    channel = house_utils.find_channel(interaction.guild)
    if channel is None:
        return
    try:
        name = await resolve.room_name(room_id)
        thread = await house_utils.get_thread_for_room(channel, name)
        if thread is not None:
            await thread.send(f"{interaction.user.mention} {message}")
    except (discord.HTTPException, SQLAlchemyError):
        # The use has already happened; failing to announce it is cosmetic.
        log.warning("Could not post a public use in %s", room_id, exc_info=True)


async def _use_transform(interaction, state, found, row) -> None:
    """One thing becomes another, in the room that allows it.

    The only row using this is the used baby bottle, which needs a sink and hot
    water. Outside the Kitchen its own use_fail explains why.
    """
    user, guild_id = interaction.user, interaction.guild_id

    if row.transform_room and state.current_room != row.transform_room:
        await interaction.followup.send(
            await phrasing.say(
                guild_id, found.thing_id, "use_fail",
                fallback="use_fail.default", name=found.name,
            ),
            ephemeral=True,
        )
        return

    if not await database.transform_carried(
        user.id, guild_id, found.thing_id, row.transforms_to
    ):
        # Resolution found it in the room rather than the bag: a transform acts
        # on what you are holding, so there is nothing to consume.
        await interaction.followup.send(
            await phrasing.say(
                guild_id, found.thing_id, "use_fail",
                fallback="use_fail.default", name=found.name,
            ),
            ephemeral=True,
        )
        return

    await _finish_use(interaction, state, found)


async def _use_with_cooldown(interaction, state, found, row) -> None:
    """A thing that cannot be used again for a while.

    Only lumber, at 48 hours. The refusal carries {time}, and a refused use is
    not a use: nothing is recorded, so the window does not slide forward every
    time somebody tries.
    """
    user, guild_id = interaction.user, interaction.guild_id
    window = timedelta(hours=row.use_cooldown_hours)

    previous = await database.last_used(user.id, guild_id, found.thing_id)
    if previous is not None:
        elapsed = database._utcnow() - previous
        if elapsed < window:
            await interaction.followup.send(
                await phrasing.say(
                    guild_id, found.thing_id, "use_fail",
                    fallback="use_fail.cooldown",
                    name=found.name,
                    time=phrasing.approximate_duration(window - elapsed),
                ),
                ephemeral=True,
            )
            return

    await _finish_use(interaction, state, found)


async def _use_exit(interaction, state, found, row) -> None:
    """Move the player through an exit into the adjoining room.

    Ordering note: the spec's numbered steps post the exit message and remove
    the player before adding them to the destination, but its error handling
    requires that a failed add must not have already removed them. The latter
    wins - the player is added to the destination first, so any failure leaves
    them exactly where they were.
    """
    user, guild_id = interaction.user, interaction.guild_id
    destination = row.destination_room_id

    if destination not in state.rooms_unlocked:
        await interaction.followup.send(
            await phrasing.say(
                guild_id, found.thing_id, "use_fail",
                fallback="use_fail.default", name=found.name,
            ),
            ephemeral=True,
        )
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
        destination_name = await resolve.room_name(destination)
        origin_name = await resolve.room_name(state.current_room)
        destination_thread = await house_utils.get_thread_for_room(channel, destination_name)
        origin_thread = await house_utils.get_thread_for_room(channel, origin_name)
    except (discord.HTTPException, SQLAlchemyError):
        log.exception("Could not look up room threads")
        await interaction.followup.send(MOVE_ERROR_MESSAGE, ephemeral=True)
        return

    if destination_thread is None:
        await interaction.followup.send(
            f"I couldn't find the thread for {destination_name or destination}. "
            "Ask an admin to run `/initialize-haunted-house`.",
            ephemeral=True,
        )
        return

    # Add before removing: if this fails the player has not been moved or
    # removed from anywhere, so they are where they started and can retry.
    try:
        await house_utils.add_player_to_thread(destination_thread, user.id)
    except discord.HTTPException:
        log.exception("Failed to add %s to %s", user.id, destination)
        await interaction.followup.send(MOVE_ERROR_MESSAGE, ephemeral=True)
        return

    try:
        await database.update_current_room(user.id, guild_id, destination)
        await database.record_use(user.id, guild_id, found.thing_id)
    except SQLAlchemyError:
        try:
            await house_utils.remove_player_from_thread(destination_thread, user.id)
        except discord.HTTPException:
            log.exception("Rollback failed: %s left in %s", user.id, destination)
        await interaction.followup.send(MOVE_ERROR_MESSAGE, ephemeral=True)
        return

    # The move has happened. What follows is presentational, so a failure is
    # logged rather than surfaced - the player is already through the door.
    depart = await phrasing.default_say(
        "move.depart", player=user.mention, name=found.name, room=origin_name
    )
    arrive = await phrasing.default_say(
        "move.arrive", player=user.mention, name=found.name, room=origin_name
    )

    if origin_thread is not None:
        try:
            await origin_thread.send(depart)
        except discord.HTTPException:
            log.warning("Could not post departure in %s", origin_name, exc_info=True)
        try:
            await house_utils.remove_player_from_thread(origin_thread, user.id)
        except discord.HTTPException:
            log.warning("Could not remove %s from %s", user.id, origin_name, exc_info=True)

    try:
        await destination_thread.send(arrive)
    except discord.HTTPException:
        log.warning("Could not post arrival in %s", destination_name, exc_info=True)

    await interaction.followup.send(
        f"You head to {destination_thread.mention}.", ephemeral=True
    )

    await _fire(
        achievements.Context(
            guild_id=guild_id,
            hook="on_move",
            user_id=user.id,
            thing_id=found.thing_id,
            room_id=destination,
        ),
        interaction=interaction,
    )


GENERIC_ROOM_DESCRIPTION = "You see a room."
NOT_IN_ROOM_MESSAGE = "You must be in a room to look around."
CANT_LOOK_MESSAGE = "You can't look at that."
INVENTORY_ERROR_MESSAGE = "Couldn't retrieve your inventory. Try again."


@bot.tree.command(name="look", description="Look around the room, or at a specific thing.")
@app_commands.guild_only()
@app_commands.describe(thing="What to look at. Leave empty to look around the room.")
async def look(interaction: discord.Interaction, thing: str | None = None) -> None:
    """Three shapes: the room, a thing, or a container and what is inside it.

    Always private. `/look` can be typed anywhere in the server and a public
    reply would leak descriptions to people who are not playing; it also keeps
    a busy room thread from filling with everyone looking around. And it is
    what lets one player see the unjammed drawer while another does not.
    """
    await interaction.response.defer(ephemeral=True, thinking=True)
    user, guild_id = interaction.user, interaction.guild_id

    try:
        state = await database.get_game_state(user.id, guild_id)
        if state is None:
            await interaction.followup.send(NOT_IN_ROOM_MESSAGE, ephemeral=True)
            return

        if thing is None or not thing.strip():
            await interaction.followup.send(
                await _look_around(guild_id, user.id, state.current_room), ephemeral=True
            )
            return

        found = await reach.find(
            guild_id, user.id, state.current_room, thing, reach.Scope.REACH
        )

        if isinstance(found, reach.Ambiguous):
            await interaction.followup.send(
                await phrasing.default_say(
                    "ambiguous.match", options=", ".join(found.options)
                ),
                ephemeral=True,
            )
            return

        if isinstance(found, reach.NotFound):
            key = "take_fail.absent" if found.exists_elsewhere else "unknown.noun"
            await interaction.followup.send(
                await phrasing.default_say(key, name=thing.strip()), ephemeral=True
            )
            return

        await interaction.followup.send(
            await _look_at(guild_id, user.id, state.current_room, found), ephemeral=True
        )
    except SQLAlchemyError:
        log.exception("Failed to look at %r in guild %s", thing, guild_id)
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)


async def _current_state(guild_id: int, user_id: int) -> str:
    """Which state's text this player sees.

    Nothing sets a state in 2c, so this is always `default` today - the
    staircase and the drawer are 2c.5. The plumbing is here so that when states
    start being set, the text follows without another pass over /look.

    A player holding two states that both have text for the same entity is
    unspecified in the Functional Spec. Sorting makes the choice deterministic
    rather than dependent on row order, which is the least surprising thing to
    do until somebody rules on it.
    """
    held = await database.states_of(guild_id, user_id)
    return sorted(held)[0] if held else resolve.DEFAULT_STATE


async def _look_around(guild_id: int, user_id: int, room_id: str) -> str:
    """The room's description, then what is lying about in it."""
    state = await _current_state(guild_id, user_id)
    description = await resolve.room_look(guild_id, room_id, state) or GENERIC_ROOM_DESCRIPTION

    held = await states.in_force(guild_id, user_id)
    loose = await database.loose_here(guild_id, room_id, held_states=held)
    line = await phrasing.listing(
        loose,
        prefix_key="also_here.prefix",
        budget=phrasing.MESSAGE_LIMIT - len(description) - 2,
    )
    return f"{description}\n\n{line}" if line else description


async def _look_at(guild_id: int, user_id: int, room_id: str, found) -> str:
    """One thing, plus its contents if anything is inside it.

    A carried thing uses `look_carried` where it has one: six things describe
    where they were sitting, which stops being true the moment they are picked
    up. Falling back to `look` is right for everything else.
    """
    state = await _current_state(guild_id, user_id)

    description = ""
    if found.where is reach.Where.CARRIED:
        description = await phrasing.say(
            guild_id, found.thing_id, "look_carried", state=state, name=found.name
        )
    if not description:
        description = await phrasing.say(
            guild_id, found.thing_id, "look", state=state, name=found.name
        )
    if not description:
        description = f"You see {found.name}."

    inside = await database.loose_here(
        guild_id, room_id, container_id=found.thing_id,
        held_states=await states.in_force(guild_id, user_id),
    )
    line = await phrasing.listing(
        inside,
        prefix_key="contents.prefix",
        budget=phrasing.MESSAGE_LIMIT - len(description) - 2,
    )
    return f"{description}\n\n{line}" if line else description


@bot.tree.command(name="inventory", description="See what you're carrying.")
@app_commands.guild_only()
async def inventory(interaction: discord.Interaction) -> None:
    """List the player's carried things in this server, grouped and counted."""
    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        items = await database.get_carried(interaction.user.id, interaction.guild_id)
    except SQLAlchemyError:
        await interaction.followup.send(INVENTORY_ERROR_MESSAGE, ephemeral=True)
        return

    if not items:
        await interaction.followup.send(
            await phrasing.default_say("inventory.empty"), ephemeral=True
        )
        return

    # The same rendering as a room listing, so a bag of ten herbs reads the way
    # ten herbs on the floor read. Truncation applies here too: nothing caps how
    # much a player can carry.
    await interaction.followup.send(
        await phrasing.listing(items, prefix_key="inventory.prefix"), ephemeral=True
    )


# --------------------------------------------------------------------------
# /take and /drop
#
# Both are thin. Resolution decides which thing and which copy, the refusal
# tables below decide whether the verb may act, and phrasing.py decides what
# the reply says. Anything else living here would be logic the other verbs
# then need their own copy of.
# --------------------------------------------------------------------------


async def _player_room(interaction: discord.Interaction) -> str | None:
    state = await database.get_game_state(interaction.user.id, interaction.guild_id)
    return state.current_room if state else None


@bot.tree.command(name="take", description="Pick something up.")
@app_commands.guild_only()
@app_commands.describe(thing="What to pick up.")
async def take(interaction: discord.Interaction, thing: str) -> None:
    """Take one copy of something in the room.

    Scoped to the room, never the bag. A player carrying chicken beside the
    salmon cupboard who types `/take cat food` gets the salmon, and is not asked
    a question they could not answer.
    """
    await interaction.response.defer(thinking=True)
    user, guild_id = interaction.user, interaction.guild_id

    try:
        room_id = await _player_room(interaction)
        if room_id is None:
            await interaction.followup.send(NOT_IN_ROOM_MESSAGE, ephemeral=True)
            return

        found = await reach.find(guild_id, user.id, room_id, thing, reach.Scope.ROOM)

        if isinstance(found, reach.Ambiguous):
            await interaction.followup.send(
                await phrasing.default_say(
                    "ambiguous.match", options=", ".join(found.options)
                ),
                ephemeral=True,
            )
            return

        if isinstance(found, reach.NotFound):
            await interaction.followup.send(
                await _take_refusal(guild_id, found, thing), ephemeral=True
            )
            return

        row = await phrasing.thing_row(found.thing_id)
        refusal = await _cannot_take(guild_id, user.id, found, row)
        if refusal:
            await interaction.followup.send(refusal, ephemeral=True)
            return

        # A source hands over what it yields and is not itself consumed; a
        # finite object moves out of the room. Either way the player ends up
        # holding `taken`, whose text the reply uses.
        taken = found.yields or found.thing_id
        if found.is_source:
            await database.take_from_source(user.id, guild_id, taken)
        elif not await database.take_from_room(
            user.id, guild_id, room_id, found.container_id or database.LOOSE_IN_ROOM,
            found.thing_id,
        ):
            # Somebody else took the last one between resolving and acting.
            await interaction.followup.send(
                await phrasing.default_say("take_fail.absent", name=found.name),
                ephemeral=True,
            )
            return

        taken_row = await phrasing.thing_row(taken)
        name = taken_row.name if taken_row else found.name
        await interaction.followup.send(
            await phrasing.say(
                guild_id, taken, "take", fallback="take.default", name=name
            )
            or f"You take the {name}.",
        )

        # `source_id` is what separates gardening from scavenging: taking herbs
        # from the herb garden earns Green Thumb, picking up a herbs somebody
        # dropped in the Entryway does not, and both hand over an identical
        # thing id.
        await _fire(
            achievements.Context(
                guild_id=guild_id,
                hook="on_take",
                user_id=user.id,
                thing_id=taken,
                source_id=found.source_id,
                room_id=room_id,
            ),
            interaction=interaction,
        )
    except SQLAlchemyError:
        log.exception("Failed to take %r in guild %s", thing, guild_id)
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)


async def _take_refusal(guild_id: int, found: reach.NotFound, typed: str) -> str:
    """Why nothing was taken, when resolution found nothing to take.

    The order matters: already-carrying is checked before absent, because
    take_fail.absent would be a lie to someone holding the thing.
    """
    if found.carried:
        return await phrasing.default_say("take_fail.already_carried", name=typed.strip())
    if found.exists_elsewhere:
        return await phrasing.default_say("take_fail.absent", name=typed.strip())
    return await phrasing.default_say("unknown.noun", name=typed.strip())


async def _cannot_take(
    guild_id: int, user_id: int, found: reach.Found, row
) -> str | None:
    """The refusal table, in the spec's order. None means go ahead."""
    if row is None:
        return await phrasing.default_say("take_fail.absent", name=found.name)

    if row.type == "exit":
        return await phrasing.default_say("take_fail.exit", name=found.name)

    # A source is never takeable itself; what matters is whether its yield is.
    if not found.is_source and not row.takeable:
        return await phrasing.say(
            guild_id, found.thing_id, "take_fail",
            fallback="take_fail.fixture", name=found.name,
        )

    # The cap applies to what the player ends up holding, which for a source is
    # the thing it yields rather than the source itself.
    taken = found.yields or found.thing_id
    capped = await phrasing.thing_row(taken) if found.is_source else row
    if capped is None or capped.max_per_player is None:
        return None

    held = await database.carried_of(user_id, guild_id, taken)
    if held < capped.max_per_player:
        return None
    return await phrasing.say(
        guild_id, taken, "take_fail", fallback="take_fail.fixture", name=capped.name
    )


@bot.tree.command(name="drop", description="Put something down.")
@app_commands.guild_only()
@app_commands.describe(thing="What to put down.")
async def drop(interaction: discord.Interaction, thing: str) -> None:
    """Drop one copy of something you are carrying, loose in the room."""
    await interaction.response.defer(thinking=True)
    user, guild_id = interaction.user, interaction.guild_id

    try:
        room_id = await _player_room(interaction)
        if room_id is None:
            await interaction.followup.send(NOT_IN_ROOM_MESSAGE, ephemeral=True)
            return

        found = await reach.find(guild_id, user.id, room_id, thing, reach.Scope.CARRIED)

        if isinstance(found, reach.Ambiguous):
            await interaction.followup.send(
                await phrasing.default_say(
                    "ambiguous.match", options=", ".join(found.options)
                ),
                ephemeral=True,
            )
            return

        if isinstance(found, reach.NotFound):
            await interaction.followup.send(
                await phrasing.default_say("drop_fail.not_carried", name=thing.strip()),
                ephemeral=True,
            )
            return

        row = await phrasing.thing_row(found.thing_id)
        if row is not None and not row.droppable:
            # The flag refuses; the written line says why. Both things set this
            # have their own drop_fail written.
            await interaction.followup.send(
                await phrasing.say(
                    guild_id, found.thing_id, "drop_fail",
                    fallback="drop_fail.undroppable", name=found.name,
                ),
                ephemeral=True,
            )
            return

        if not await database.drop_into_room(user.id, guild_id, room_id, found.thing_id):
            await interaction.followup.send(
                await phrasing.default_say("drop_fail.not_carried", name=found.name),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            await phrasing.say(
                guild_id, found.thing_id, "drop", fallback="drop.default", name=found.name
            )
            or f"You set the {found.name} down.",
        )

        await _fire(
            achievements.Context(
                guild_id=guild_id,
                hook="on_drop",
                user_id=user.id,
                thing_id=found.thing_id,
                room_id=room_id,
            ),
            interaction=interaction,
        )
    except SQLAlchemyError:
        log.exception("Failed to drop %r in guild %s", thing, guild_id)
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)


@bot.tree.command(
    name="admin_config",
    description="(Admin) Change a per-server setting.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    key="Which setting to change.",
    value="Its new value. Whole numbers only.",
)
async def admin_config(interaction: discord.Interaction, key: str, value: int) -> None:
    """Retune a server's numbers without a deploy.

    Usable mid-game by design: a server that set the staircase at ten planks
    and then drew four players needs the number lowered, not the release
    abandoned.

    The key is free text validated against a registry rather than a dropdown.
    A Literal would give a nicer picker, but changing a slash command's
    signature costs an hour of propagation, and adding the next setting should
    not cost that.
    """
    await interaction.response.defer(ephemeral=True, thinking=True)

    name = key.strip().lower()
    if name not in database.CONFIG_KEYS:
        known = "\n".join(
            f"- `{k}` — {description} (default {default})"
            for k, (default, description) in sorted(database.CONFIG_KEYS.items())
        )
        await interaction.followup.send(
            f"There's no setting called `{key.strip()}`. The ones there are:\n{known}",
            ephemeral=True,
        )
        return

    if value < 1:
        await interaction.followup.send(
            f"`{name}` has to be at least 1. Setting it to {value} would stop "
            "the thing it controls from ever happening, which is probably not "
            "what you meant.",
            ephemeral=True,
        )
        return

    try:
        previous = await database.get_setting(interaction.guild_id, name)
        await database.set_setting(interaction.guild_id, name, value)
    except SQLAlchemyError:
        log.exception("Could not set %s in guild %s", name, interaction.guild_id)
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    note = ""
    if name == world.PLANKS_SETTING:
        # Lowering the target below the planks already placed finishes the
        # staircase now, rather than leaving it stuck one short of a number
        # nobody can reach.
        try:
            opened = await world.check_staircase(interaction.guild_id)
            placed, _ = await world.planks(interaction.guild_id)
        except SQLAlchemyError:
            opened, placed = False, None
        if opened:
            note = (
                f"\n\n{placed} player(s) had already placed a plank, which meets "
                "the new target — the staircase is finished."
            )

    await interaction.followup.send(
        f"`{name}` is now **{value}** (was {previous}).{note}", ephemeral=True
    )


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
