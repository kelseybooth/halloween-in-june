"""Halloween cat petting bot - MVP (Phase 1).

Slash commands:
  /pet    - pet the cat, increments a persistent per-user counter
  /stats  - show your pet total
"""

import dataclasses
import logging
import os
import random
import sys
from datetime import datetime, time as dt_time, timedelta
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
import gating
import hints
import leaderboard
import house_utils
import phrasing
import qa
import reach
import resolve
import restocking
import states
import triggers

TUTORIAL_SEEN = "tutorial_seen"
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
    "The cat purrs contentedly as you pet her, tail curling like smoke. Is this bonding?",
    "The cat meows and rubs against your leg, eyes glinting in the dark. Maybe you'll be friends.",
    "The cat stretches, blinks slowly at you, and meows fondly.",
]

STANDOFFISH_RESPONSES = [
    "The cat meows admonishingly and turns her back on you. Oh no! You wanted to be friends.",
    "The cat startles, hissing at you. You worry the cat may not like you.",
    "The cat glares at you and gives you a warning bat with her paw. You hope this does not hurt your relationship.",
]

PET_RESPONSES = FRIENDLY_RESPONSES + STANDOFFISH_RESPONSES

# Mood weighting: the cat tires of being pestered. A user arriving with no recent
# pets gets BASE_FRIENDLY_CHANCE; every pet already inside
# database.RECENT_PET_WINDOW subtracts DECAY_PER_RECENT_PET points. Go quiet for
# ten minutes and the window empties, restoring the cat's patience.
BASE_FRIENDLY_CHANCE = 80
DECAY_PER_RECENT_PET = 10

# How often to look for restock occurrences that have come due. Occurrences
# are scattered through the day, so a once-a-day job would deliver eight
# bottles in a heap rather than eight times.
RESTOCK_SWEEP_MINUTES = 10

# How far one reaction moves the relationship meter.
RELATIONSHIP_STEP = 5

# The friendly chance at which a pet is worth nothing in expectation.
# Derived rather than chosen: a pet is worth `+STEP` or `-STEP` on one
# coin flip, so the expected value is `STEP x (2p - 1)` and crosses zero
# at fifty percent whatever the step is. Below this a player is losing
# score by petting, which is what the crowding nudge exists to say.
BREAK_EVEN_CHANCE = 50

# Where `/start-game` puts a server: a channel with a cat in it, and nothing
# else at all. Not a magic number in the command, because drop 0 meaning
# "the beginning" is a fact about the schedule rather than about the command.
FIRST_DROP = 0

DB_ERROR_MESSAGE = (
    "The cat slips into the shadows and you lose track of her. "
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

    Once `BASE_FRIENDLY_CHANCE / DECAY_PER_RECENT_PET` recent pets have piled
    up this is 0 and the cat is reliably standoffish until the window clears -
    eight pets at the numbers above.
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


def _crowding_begins(recent_pets: int) -> bool:
    """Whether this pet is the one that should say to give the cat space.

    **The first pet that loses points on average**, which is the fifth
    inside ten minutes: `friendly_chance` is `80 - 10 x recent`, so this
    pet is weighted at 40% and its expected value turns negative.

    It used to wait for a certainty - the ninth pet, where the chance
    hits zero - on the argument that a warning fired while the odds were
    still even would be crying wolf. The playtest answered that: a
    warning fired four pets after the damage starts tells a player what
    they did wrong too late to not do it, and the nudge is the only
    place the penalty is ever mentioned, because the public line no
    longer reports the meter.

    Tied to the chance rather than to a count of its own, so retuning
    `BASE_FRIENDLY_CHANCE` moves the nudge with it rather than leaving a
    second number to keep in step.

    **Once per window, not once per pet.** Equality rather than
    `<`: `recent` goes up by exactly one per pet, so it passes the
    threshold once per run of petting and again only after the player
    has gone quiet long enough for the window to drain. A nudge on every
    pet from the fifth onward is wallpaper, and so is the image that
    rides with it.
    """
    return (
        friendly_chance(recent_pets)
        < BREAK_EVEN_CHANCE
        <= friendly_chance(recent_pets - 1)
    )


def _is_crowded(recent_pets: int) -> bool:
    """Whether the cat is *currently* tired of this player.

    **The level, where `_crowding_begins` is the edge.** The nudge
    fires once, on the pet that crosses into losing territory, because
    a line on every pet afterwards is wallpaper. The status line
    answers a different question - somebody opening `/stats` wants to
    know where they stand now, and "you crossed over four pets ago" is
    not an answer. Two predicates on one number, and collapsing them
    into one would break whichever half it was collapsed into.
    """
    return friendly_chance(recent_pets) < BREAK_EVEN_CHANCE


def _is_expectant(recent_pets: int) -> bool:
    """The other side of the same line: better than even odds.

    Exactly even is neither, which is why this is strict. A player at
    fifty percent is being told nothing useful in either direction, and
    the two can never both be true - they read one number from opposite
    sides.
    """
    return friendly_chance(recent_pets) > BREAK_EVEN_CHANCE


def _debug_lines(reaction: Reaction, recent: int, relationship: int) -> str:
    """TEMPORARY (testing) diagnostics appended to /pet replies."""
    mood = "friendly" if reaction.friendly else "standoffish"
    delta = RELATIONSHIP_STEP if reaction.friendly else -RELATIONSHIP_STEP
    return (
        "\n\n`[testing]`"
        f"\n`mood:` {mood} ({delta:+d}) - {reaction.chance}% friendly chance"
        f" after {recent} recent pet(s)"
        f"\n`relationship:` {relationship}"
    )


async def _check_achievement_registry() -> None:
    """Report any achievement the file and the registry disagree about.

    Loud, but never fatal. The alternative is an achievement nobody can earn,
    or an award with no name to announce, and either one surfaces weeks later
    as a player asking why nothing happened - so it is logged at error level
    where Railway will show it.

    **It does not stop the bot, and that is deliberate.** Writers edit the
    TSVs through GitHub's web editor, which cannot insert a tab; a mangled
    file or an unwired thirty-sixth row would otherwise crash-loop the deploy
    and take the whole game down, where the rest of the startup path
    deliberately degrades instead - "a writer's typo costs the new text rather
    than the whole game". Enforcement belongs where it can be acted on:
    `python load_content.py --check` exits non-zero, and CI runs it.
    """
    try:
        parsed = content.load_files()
    except content.ContentError:
        # Already reported in full by load_content_at_startup, which ran just
        # before this and kept the content the database already had. Nothing
        # useful to compare the registry against.
        log.error("Could not check the achievement registry: the content files did not parse")
        return

    problems = achievements.registration_problems(parsed.achievement_ids)
    if not problems:
        log.info("All %d achievements are wired up", len(parsed.achievements))
        return
    for problem in problems:
        log.error("%s", problem)
    log.error(
        "%d achievement registration problem(s). The other achievements still "
        "work; run `python load_content.py --check` for the full report.",
        len(problems),
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

    # Date the files, per server, so the interaction log can be read
    # against them. The config history only sees what lives in config,
    # and the numbers that move most often - the restock rates, the
    # relationship deltas when they land, every string - live in TSVs;
    # one row names the whole set at once.
    #
    # Written here rather than at deploy because a content reload that
    # did not come from a deploy is exactly the change a commit hash
    # would miss.
    try:
        version = content.version()
        for guild in bot.guilds:
            if await database.record_content_version(guild.id, version):
                log.info("Guild %s is now on content %s", guild.id, version)
    except SQLAlchemyError:
        log.exception("Could not record the content version")

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


# Every command this file defines, by name, captured before any of them is
# registered anywhere. The decorators put them in the tree's global set;
# `setup_hook` takes them straight back out again, because nothing in this
# game is a global command any more. This dict is what they are added back
# from, one guild at a time.
_DEFINED: dict[str, app_commands.Command] = {}


def _capture_commands(tree) -> dict[str, app_commands.Command]:
    """Snapshot the decorated commands, then clear the global set.

    Called once at startup. After this the tree has no global commands at
    all, and `sync()` with none left is the bulk overwrite that removes
    whatever this bot registered globally in an earlier release - without
    it, every player keeps a stale menu of nine verbs for up to an hour
    and then forever, because nothing would ever replace it.
    """
    defined = {c.name: c for c in tree.get_commands()}
    tree.clear_commands(guild=None)
    return defined


async def register_commands_for(guild, drop: int | None = None, tree=None) -> set[str]:
    """Put exactly this server's command set in place, in one request.

    **Bulk overwrite, not create-and-delete.** `sync` for a guild is a
    single PUT of the whole set, which is one request per advance rather
    than one per command, and stays clear of the per-command create limits
    that `/qa-drop` churn would otherwise walk into.

    Returns the names registered, so a caller can say what just appeared.

    `tree` is an argument because `commands.Bot.tree` is a read-only
    property, and a registration path worth having is a registration path
    worth testing without a gateway connection.
    """
    tree = tree if tree is not None else bot.tree
    if drop is None:
        drop = await resolve.current_drop(guild.id)
    wanted = gating.commands_for(drop, qa=qa.is_test_guild(guild.id))

    missing = wanted - set(_DEFINED)
    if missing:
        # A name in the table that no command answers to. Logged rather
        # than raised: the rest of the set is still worth registering, and
        # a typo here should not leave a server with no commands at all.
        log.error(
            "Guild %s wants commands this bot does not define: %s",
            guild.id,
            ", ".join(sorted(missing)),
        )

    tree.clear_commands(guild=guild)
    for name in sorted(wanted & set(_DEFINED)):
        tree.add_command(_DEFINED[name], guild=guild)
    await tree.sync(guild=guild)

    log.info(
        "Guild %s is on drop %s with %d command(s): %s",
        guild.id,
        drop,
        len(wanted),
        ", ".join(sorted(wanted)),
    )
    return wanted


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

        # Nothing is a global command any more. Which commands exist is a
        # per-server question now - two servers can sit on different drops
        # - so the global set is emptied once here and every guild gets its
        # own in `on_ready`. GUILD_ID is gone with it: per-guild is what
        # this does everywhere, so the local shortcut is the normal path.
        # The buttons under `/stats` outlive the process that sent
        # them: an ephemeral reply can sit open for hours, and a deploy
        # in the middle must not leave it with dead rectangles. Both
        # carry their whole state in the `custom_id`, so registering
        # the classes here is all it takes to answer a click on a
        # message this process never sent.
        self.add_dynamic_items(_OpenLeaderboard, _MyStats)

        global _DEFINED
        _DEFINED = _capture_commands(self.tree)
        await self.tree.sync()
        log.info(
            "Cleared the global command set; %d command(s) defined and "
            "registered per guild",
            len(_DEFINED),
        )

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id: %s)", self.user, self.user.id)

        # Say up front what the haunted house is missing, rather than letting it
        # surface later as an opaque "Missing Access" error mid-command.
        for guild in self.guilds:
            log.info("In guild %r (%s)", guild.name, guild.id)

            # Every server gets the set its own drop calls for. Done on
            # every boot rather than only on a change, because this is the
            # only thing that repairs a guild whose registration failed
            # halfway through an advance.
            try:
                await register_commands_for(guild)
            except discord.HTTPException:
                log.exception("Could not register commands in guild %s", guild.id)

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

    async def on_guild_join(self, guild) -> None:
        """A server that invited the bot has no game and sees `/start-game`.

        Without this a new server would have no commands at all until the
        next restart, because nothing is global any more and registration
        only ever happens per guild.
        """
        log.info("Joined guild %r (%s)", guild.name, guild.id)
        try:
            await register_commands_for(guild)
        except discord.HTTPException:
            log.exception("Could not register commands in new guild %s", guild.id)

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
    return await _room_of_thread(channel) is not None


async def _room_of_thread(channel) -> str | None:
    """Which room this thread *is*, or None if it is not a room thread.

    Duck-typed on `parent` rather than `isinstance(channel, discord.Thread)`:
    a text channel has no parent, so the check is just as tight, and it can be
    exercised without constructing a real Thread.
    """
    parent = getattr(channel, "parent", None)
    name = getattr(channel, "name", None)
    if parent is None or getattr(parent, "name", None) != house_utils.HALLOWEEN_CHANNEL_NAME:
        return None
    try:
        for room_id, room_name in await resolve.all_rooms():
            if room_name == name:
                return room_id
    except SQLAlchemyError:
        log.exception("Could not identify the thread %s", name)
    return None


async def _outside_the_house(interaction, room_id: str) -> str | None:
    """Why `/look`, `/take`, `/drop` and `/use` cannot run here. None to go on.

    **The thread is the room.** Without this the four world verbs answer from
    anywhere in the server: a player standing in the Upstairs Hallway could
    type `/look` in an unrelated channel and be told about the hallway, which
    makes the house a status readout rather than a place.

    Being in *a* room thread is enough, and it is not weaker than checking for
    *the* room. The rooms are private threads created with `invitable=False`,
    and the bot is the only thing that adds or removes anybody - on entry and
    on every move. A player is therefore a member of exactly one room thread
    and cannot type in another. Checking the specific room as well would add
    no protection and one failure mode: a membership bug would strand somebody
    with no room they are allowed to act in.

    Nothing else is gated. `/pet`, `/inventory` and `/stats` are about the
    player rather than the room, and the admin commands have to work before
    any thread exists.
    """
    if await _room_of_thread(interaction.channel) is not None:
        return None

    name = await resolve.room_name(room_id) or "the house"
    return (
        f"That only works inside the house. You're in **{name}** - "
        "open that room's thread and try again."
    )


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


# The cat is everywhere, so `/pet` needs no location check. It resolves in
# all nine rooms and in the Halloween channel, and the public line posts
# wherever the command was run.
#
# Two windows, deliberately separate, because they answer different
# questions. Crowding is between a player and the cat, and fires the first
# time a pet is worth less than nothing - see `_crowding_begins`. The
# public rate
# limit is about noise in a shared room: two lines per player per place
# per thirty minutes.
PUBLIC_PETS = 2
PUBLIC_WINDOW = timedelta(minutes=30)

# (guild, player, place) -> when this window opened, and how many lines it has
# spent. In memory on purpose, like the movement buffer *A Little Bit Lost*
# keeps: a restart hands somebody two more public lines than they were owed,
# which nobody can notice and which costs a table to prevent.
_PUBLIC_PETS: dict[tuple[int, int, int], tuple[datetime, int]] = {}

# The play line's own budget, same shape and deliberately not shared: a
# player who has used up their pet lines should still get one for the
# rarer and better event.
_PUBLIC_PLAYS: dict[tuple[int, int, int], tuple[datetime, int]] = {}

# Where the twelve rotating play refusals live.
REFUSAL_PREFIX = "use_fail.toy."


def forget_public_pets() -> None:
    """Empty the public-pet and public-play windows. For tests."""
    _PUBLIC_PETS.clear()
    _PUBLIC_PLAYS.clear()


def _public_play_line(guild_id: int, user_id: int, place_id: int, now) -> str | None:
    """Whether this play earns a public line. Same rule as the pet one."""
    key = (guild_id, user_id, place_id)
    opened, spent = _PUBLIC_PLAYS.get(key, (None, 0))
    if opened is None or now - opened >= PUBLIC_WINDOW:
        _PUBLIC_PLAYS[key] = (now, 1)
        return "first"
    if spent < PUBLIC_PETS:
        _PUBLIC_PLAYS[key] = (opened, spent + 1)
        return "again"
    return None


def _public_pet_line(guild_id: int, user_id: int, place_id: int, now: datetime) -> str | None:
    """Which public line this pet earns, or None to stay quiet.

    The window opens on the first *line*, not the first pet, so a player can
    never be surprised by which one they get: two get through, the rest are
    silent, and thirty minutes after that first line the next pet is public
    again as a normal first line.

    The bucket is the member and the place. Two people in the same room each
    get their own two; one person moving between rooms gets two in each,
    because those are different audiences. The Halloween channel is its own
    bucket alongside the nine rooms.
    """
    key = (guild_id, user_id, place_id)
    opened, spent = _PUBLIC_PETS.get(key, (None, 0))
    if opened is None or now - opened >= PUBLIC_WINDOW:
        _PUBLIC_PETS[key] = (now, 1)
        return "first"
    if spent < PUBLIC_PETS:
        _PUBLIC_PETS[key] = (opened, spent + 1)
        return "continues"
    return None


async def _announce_pet(interaction, friendly: bool) -> None:
    """The public half: somebody pet the cat, and how it went.

    Posted wherever the command was run, which is what makes the discovery
    argument work - an admin can pet the cat in the Halloween channel on day
    one, before anybody has run `/enter`, and everyone watching learns the
    command exists.

    **It reports the pet, not the relationship.** The branch is the mood
    roll this pet made, and the meter is not read at all.

    This reverses what Phase 2f recommended and what the code correctly
    did until now. 2f branched on the score afterwards, so that the line
    agreed with the boundary the two friendship achievements split on -
    and that boundary no longer exists in that form, because those two
    became one fork evaluated once at two hundred pets. What is left is
    the plainer reading: the room watched somebody pet the cat, and the
    line says how the cat took it.

    It also keeps the score out of public view entirely, which the
    crowding nudge now depends on - that nudge is the only place the
    penalty is ever mentioned.

    The crowding nudge never appears here. It is between that player and the
    cat, and broadcasting it would make it a scolding.
    """
    channel = interaction.channel
    if channel is None or not hasattr(channel, "send"):
        return

    which = _public_pet_line(
        interaction.guild_id, interaction.user.id, getattr(channel, "id", 0),
        await database.server_now(interaction.guild_id),
    )
    if which is None:
        return

    key = (
        "pet.public.continues"
        if which == "continues"
        else "pet.public.friendly" if friendly else "pet.public.standoffish"
    )
    line = await phrasing.default_say(key, player=interaction.user.display_name)
    if line:
        await _post_quietly(channel, line)


async def _move_the_meter(user_id: int, guild_id: int, delta: int) -> int:
    """Touch the cat: stamp the day, then move the score.

    Every way of touching the cat goes through here, which is the point.
    The stamp is what the nightly drift reads, and it happens on the
    attempt rather than on the result - the toy's first offer is a
    guaranteed refusal and the bed refuses inside its window, and a
    player who tried was not absent. Pass `delta=0` for an attempt that
    moved nothing.
    """
    await database.touched_the_cat(
        user_id, guild_id, await database.server_today(guild_id)
    )
    if not delta:
        return await database.get_relationship(user_id, guild_id)
    return await database.adjust_relationship(user_id, guild_id, delta)


async def _fire_relationship(interaction, user_id: int, guild_id: int, score: int) -> None:
    """Let the three thresholds look, wherever the score just moved.

    Separate from `_move_the_meter` because the hook wants an interaction
    to answer privately and the move does not, and because it belongs
    after the command has replied rather than in the middle of it.
    """
    await _fire(
        achievements.Context(
            guild_id=guild_id,
            hook="on_relationship_change",
            user_id=user_id,
            extra={"relationship": score},
        ),
        interaction=interaction,
    )


@bot.tree.command(name="pet", description="Pet the cat.")
@app_commands.guild_only()
async def pet(interaction: discord.Interaction) -> None:
    """One command, two messages: the blurb in private, the event in public.

    The private reply carries the cat's reaction and **no pet count**.
    Progress toward *Making Friends* lives in `/stats` and nowhere else - two
    hundred is better as a surprise than as a countdown, and a visible
    counter turns petting a cat into filling a progress bar.

    A member with no player row can run this, exactly as in v1: the row is
    created, the meter starts, and the pet counts. It is how somebody can
    hold a relationship score having never been in a room, which `/enter`
    then has to handle.
    """
    # Ephemeral now: the blurb is the private half of the pair. Defer first,
    # because the DB round trip can exceed Discord's 3s deadline.
    await interaction.response.defer(ephemeral=True)
    user, guild_id = interaction.user, interaction.guild_id

    try:
        result = await database.increment_pet_count(user.id, guild_id)
        reaction = choose_response(result.recent)
        delta = RELATIONSHIP_STEP if reaction.friendly else -RELATIONSHIP_STEP
        relationship = await _move_the_meter(user.id, guild_id, delta)
    except SQLAlchemyError:
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    message = reaction.text
    crowding_begins = _crowding_begins(result.recent)
    if crowding_begins:
        nudge = await phrasing.default_say("pet.crowding")
        if nudge:
            message = f"{message}\n\n{nudge}"
    if SHOW_DEBUG_INFO:
        message += _debug_lines(reaction, result.recent, relationship)

    # The over-the-shoulder look is exactly what the nudge says in
    # words, and it is the one image tied to something other than an
    # achievement. It rides the private reply, never the public line,
    # for the same reason the words do. The first pet of all gets her
    # instead - and every pet in between gets nothing, because an image
    # seen twice a minute stops being a reward and becomes latency,
    # which is now true by construction: the nudge fires on the pet
    # that crosses into crowding and not on the ones after it.
    # The rail, under the blurb. `hint.something_new` is a candidate on
    # any private cat message, which is how a player who was not in the
    # channel when a drop opened still hears that something arrived.
    # The hooks run first and hold their announcements, so the rail
    # below sees what this pet earned rather than the world as it was a
    # moment before. The player still reads the blurb first - the held
    # announcements go out underneath it.
    earned = await _fire(
        achievements.Context(
            guild_id=interaction.guild_id,
            hook="on_pet",
            user_id=interaction.user.id,
            extra={
                "total": result.total,
                "relationship": relationship,
                "friendly": reaction.friendly,
            },
        ),
        interaction=interaction,
        announce=False,
    )
    earned += await _fire(
        achievements.Context(
            guild_id=guild_id,
            hook="on_relationship_change",
            user_id=user.id,
            extra={"relationship": relationship},
        ),
        interaction=interaction,
        announce=False,
    )

    # A friendly first pet earns *Making First Contact*, and its hint
    # rides that announcement instead - see `HINT_FOR_ACHIEVEMENT`. A
    # standoffish one earns nothing, so its hint has nowhere else to go.
    #
    # **One hint per action, not per message.** An award arriving with
    # a hint on it takes this reply's turn: two nudges across the three
    # messages a first pet already sends is the noise the rail exists
    # to avoid.
    carried = any(a.achievement_id in HINT_FOR_ACHIEVEMENT for a in earned)
    candidates = [] if reaction.friendly else [hints.FIRST_STANDOFFISH]
    message = hints.beneath(
        message,
        None
        if carried
        else await hints.after(guild_id, user.id, *candidates, hints.SOMETHING_NEW),
    )

    art = ART_CROWDING if crowding_begins else (
        ART_FIRST_PET if result.total == 1 else None
    )
    content_, embed = await _with_art(interaction.guild, message, art)
    await interaction.followup.send(content_, embed=embed, ephemeral=True)

    await _announce_pet(interaction, reaction.friendly)
    await _announce_all(earned, interaction=interaction)


async def _reregister(interaction, guild, drop: int | None) -> str:
    """Put the server's command set where its drop says, and name the
    player half for the reply.

    A failure here is reported rather than raised, and caught broadly: the
    drop has already moved and the database is committed, so whatever
    Discord objects to, the honest thing is to say the menu did not follow
    rather than to throw away a committed advance.
    """
    try:
        await register_commands_for(guild, drop)
    except discord.DiscordException:
        log.exception("Could not re-register commands in guild %s", guild.id)
        await interaction.followup.send(
            "The drop moved, but Discord would not take the new command "
            "list. Run the command again, or restart the bot - every boot "
            "re-registers every server.",
            ephemeral=True,
        )
    names = sorted(gating.player_commands_for(drop))
    return ", ".join(f"`/{name}`" for name in names) or "nothing yet"


@bot.tree.command(
    name="start-game",
    description="(Admin) Open drop 0 in a channel. The game lives there from then on.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    channel="Where the game lives. Every public line it ever posts goes here.",
    art_channel="Somewhere to park the cat pictures. Any channel; nobody reads it.",
)
async def start_game(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    art_channel: discord.TextChannel | None = None,
) -> None:
    """Put a server on drop 0, in a named channel.

    **The art is uploaded here**, and that is a fix rather than a
    feature. It used to ride `/initialize-haunted-house`, which also
    builds nine room threads and is therefore registered from drop 3 -
    so on a drop-0 server there was no way to run it, `server_art` was
    empty, and every message took the "degrades to text" path. Four
    images belonging to drops 0 and 1 had never once been seen: the
    first pet, the crowding nudge, and the two petting achievements.

    Only the *threads* have a reason to wait for drop 3. The upload
    moves to the command that opens the game, and
    `/initialize-haunted-house` keeps its own copy for a server that
    started before this change.

    **The channel is an argument rather than a name the bot goes looking
    for.** Servers call it different things, and this one will be renamed
    before launch; a command that is told cannot be wrong.

    **Idempotent in the same channel.** Running it twice reports where the
    server is and changes nothing, which is what an admin who cannot
    remember whether they already ran it deserves.

    **Refused against a second channel.** Moving a running game would
    leave every player's sense of where it lives pointing at the old one,
    and nothing in the game would tell them otherwise. Wiping first with
    `/reset-haunted-house` is the way, and it is deliberately the longer
    way round.
    """
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command only works inside a server.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild

    try:
        current = await resolve.current_drop(guild.id)
        existing = await database.announcement_channel(guild.id)
    except SQLAlchemyError:
        log.exception("Could not read the game's state in %s", guild.id)
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    if current is not None:
        if existing is not None and existing != channel.id:
            where = guild.get_channel(existing)
            await interaction.followup.send(
                "This server's game is already running in "
                + (where.mention if where else "another channel")
                + f", on drop {current}. Moving it would leave every player "
                "looking at the wrong channel, so it is refused. "
                "`/reset-haunted-house` first if you really mean to start "
                "over somewhere else.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"The game is already open in {channel.mention}, on drop "
            f"{current}. Nothing changed.",
            ephemeral=True,
        )
        return

    try:
        await database.set_announcement_channel(guild.id, channel.id)
        await resolve.set_current_drop(guild.id, FIRST_DROP)
        await content_loader.place_arrived(guild.id)
    except (resolve.UnknownDrop, SQLAlchemyError, content.ContentError) as exc:
        log.exception("Could not start the game in %s", guild.id)
        await interaction.followup.send(
            f"The game did not open: {exc}", ephemeral=True
        )
        return

    await qa.clear_forced(guild.id)
    log.info(
        "AUDIT %s (%s) started the game in guild %s, channel %s, at drop %s",
        interaction.user,
        interaction.user.id,
        guild.id,
        channel.id,
        FIRST_DROP,
    )
    opened = await _reregister(interaction, guild, FIRST_DROP)
    lines = [
        f"The game is open in {channel.mention}, on drop {FIRST_DROP}. There "
        f"is a cat there and nothing else.",
        f"- players here can now use {opened}",
        "- `/advance-game` brings the next drop",
        await _stock_the_art(guild, art_channel),
    ]
    await interaction.followup.send("\n".join(lines), ephemeral=True)


async def _stock_the_art(guild, art_channel) -> str:
    """Upload the images, and say what happened, in one line for the reply.

    **A separate channel, because the upload is ten posts.** They are
    never read again - the bot keeps the attachment URL Discord hands
    back and embeds that - so they want somewhere out of the way
    rather than the channel the game lives in.

    Never raises. The game is worth opening without pictures, which is
    the same reasoning that makes every message degrade to text.
    """
    if art_channel is None:
        return (
            "- no art channel given, so the cat pictures are not uploaded and "
            "every message that wants one will be text. Run `/start-game` "
            "again with one to fix that."
        )
    try:
        uploaded, problems = await upload_art(guild, art_channel)
    except Exception:
        log.exception("Could not upload the art in %s", guild.id)
        return "- the cat pictures did not upload, so messages will be text"
    if problems:
        log.warning("Art problems in %s: %s", guild.id, "; ".join(problems))
    return (
        f"- uploaded {uploaded} cat picture(s) to {art_channel.mention}"
        + (f", and {len(problems)} failed" if problems else "")
    )


@bot.tree.command(
    name="advance-game",
    description="(Admin) Move this server forward exactly one drop.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    confirm="Leave this off once to see which drop is next before it opens.",
)
async def advance_game(interaction: discord.Interaction, confirm: bool = False) -> None:
    """One drop forward, and only forward.

    **It names the destination before going there.** Run without `confirm`
    and it says which drop it would open; run again with it and the drop
    opens. Cheaper than a button, and the confirmation says *which* drop
    rather than merely asking twice.

    **Backwards is not here.** That is `/qa-drop` on the test servers, and
    `/reset-haunted-house back_to_drop` everywhere else - which may rewind
    only because it has just wiped the progress that going back would
    otherwise invalidate.
    """
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command only works inside a server.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild

    try:
        current = await resolve.current_drop(guild.id)
    except SQLAlchemyError:
        log.exception("Could not read the drop in %s", guild.id)
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    if current is None:
        await interaction.followup.send(
            "There is no game in this server yet. `/start-game` opens one.",
            ephemeral=True,
        )
        return

    target = current + 1
    if target > resolve.LAST_PLAYABLE_DROP:
        await interaction.followup.send(
            f"Drop {current} is the last one built. There is nothing to "
            "advance into yet.",
            ephemeral=True,
        )
        return

    name = await resolve.drop_name(target)
    titled = f": **{name}**" if name else ""
    if not confirm:
        await interaction.followup.send(
            f"This would move the server from drop {current} to drop "
            f"{target}{titled}, for everybody, now.\nRun it again with "
            "`confirm` set to open it.",
            ephemeral=True,
        )
        return

    try:
        await resolve.set_current_drop(guild.id, target)
        placed = await content_loader.place_arrived(guild.id)
    except (resolve.UnknownDrop, SQLAlchemyError, content.ContentError) as exc:
        log.exception("Could not advance %s to drop %s", guild.id, target)
        await interaction.followup.send(
            f"The drop did not open: {exc}", ephemeral=True
        )
        return

    await qa.clear_forced(guild.id)
    log.info(
        "AUDIT %s (%s) advanced guild %s from drop %s to drop %s",
        interaction.user,
        interaction.user.id,
        guild.id,
        current,
        target,
    )

    announced = await _announce_drop(guild, target)
    lines = [f"Drop {target}{titled} is open."]
    if placed:
        lines.append(f"- put {placed} new thing(s) in place")
    await _reregister(interaction, guild, target)
    arrived = gating.arrivals(current, target)
    if arrived:
        lines.append(
            "- " + ", ".join(f"`/{name}`" for name in sorted(arrived)) + " appeared"
        )
    lines.append(
        "- announced in the channel"
        if announced
        else f"- nothing posted; drop {target} has no announcement line"
    )
    await interaction.followup.send("\n".join(lines), ephemeral=True)


async def _announce_drop(guild, drop_id: int) -> bool:
    """Post a drop's arrival in the channel, if it has a line to post.

    **Two messages, as everywhere else in this game.** The admin's
    ephemeral reply says what the command did - which drop, what got
    placed, whether this posted - and is nobody else's business. The
    drop's own line is in-world and belongs to the server: everyone
    standing in the channel sees the cat swat something across the floor,
    and nothing in it names a drop, a command or an admin.

    The hint that rides beneath it belongs to the hint rail and arrives
    with it. The private firing of that hint stays either way, as the
    fallback for anybody who was not looking at the channel when this
    went out.
    """
    line = await phrasing.default_say(f"drop.{drop_id}.announce")
    if not line:
        return False
    channel_id = await database.announcement_channel(guild.id)
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        log.warning("Guild %s has no channel to announce drop %s in", guild.id, drop_id)
        return False

    # The drop's hint rides the announcement, and **sets nothing**. A
    # channel post has no player attached, and marking everyone as told
    # would kill the private fallback for exactly the people it exists
    # for - whoever was not looking when it went up.
    nudge = await hints.render(hints.SOMETHING_NEW.hint_id)
    await _post_quietly(channel, hints.beneath(line, nudge))
    return True


@bot.tree.command(
    name="reset-haunted-house",
    description="(Admin) Wipe this server's game: progress, achievements, everything.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    confirm="Type this server's name exactly. There is no undo.",
    keep_art="Keep the uploaded cat images, so a reset does not cost ten re-uploads.",
    back_to_drop="Also rewind the game to this drop. Backwards only; leave it out to stay put.",
)
async def reset_haunted_house(
    interaction: discord.Interaction,
    confirm: str,
    keep_art: bool = True,
    back_to_drop: int | None = None,
) -> None:
    """Put one server back to the morning before anybody entered.

    **Scoped to this server.** Every table it clears carries a `guild_id`
    and every delete is filtered on it, so a reset here cannot reach another
    server the bot is also in. That is the whole reason this exists as a
    command rather than a script: `reset_db.py` clears the entire database,
    and `load_content.py --fresh` clears every guild in it.

    **Content is untouched.** Rooms, things, text, achievements and art rows
    are global, reload on every boot, and have nothing to do with what a
    server has done. What comes back afterwards is the starting stock, since
    emptying `room_contents` without re-placing would leave a house with
    nothing in any room.

    **The calendar restarts too.** `initialized_on` lives in `server_config`
    and goes with the rest, so the next `/enter` is day one again - which is
    what makes this useful for testing the drop schedule.

    **The drop and the channel survive by default.** Both live in
    `server_config` and so are cleared with everything else, and both are
    written straight back: wiping everyone's progress is not the same as
    the house never having opened, and re-running `/start-game` plus one
    `/advance-game` per drop after every reset is friction that grows with
    the schedule.

    `back_to_drop` is the way back. It only ever goes **backwards or
    stays** - forward movement belongs to `/advance-game`, which confirms
    and steps once. The rule that makes rewinding safe at all is that it
    comes bundled with the wipe: a player cannot be left holding a drop-1
    achievement on a drop-0 server, because that player has no achievements
    left.

    The threads are left alone. `/initialize-haunted-house` rebuilds those,
    and wanting a clean game is not the same as wanting nine channels
    deleted and recreated.
    """
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command only works inside a server.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild

    # Typing the name is the whole safeguard. Nothing here is recoverable,
    # and a mis-clicked slash command should not end a month of play.
    if confirm.strip() != guild.name:
        await interaction.followup.send(
            f"That will wipe **every** player's progress in this server, and it "
            f"cannot be undone.\n\nRun it again with `confirm` set to exactly "
            f"**{guild.name}**.",
            ephemeral=True,
        )
        return

    try:
        current = await resolve.current_drop(guild.id)
        channel_id = await database.announcement_channel(guild.id)
    except SQLAlchemyError:
        log.exception("Could not read the game's state before resetting %s", guild.id)
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    landing = current
    if back_to_drop is not None:
        if current is None:
            await interaction.followup.send(
                "There is no game in this server to rewind. Run "
                "`/start-game` first.",
                ephemeral=True,
            )
            return
        if back_to_drop > current:
            await interaction.followup.send(
                f"This server is on drop {current}, and `back_to_drop` only "
                f"goes backwards. Use `/advance-game` to move forward - it "
                "goes one drop at a time, on purpose.",
                ephemeral=True,
            )
            return
        if back_to_drop not in await resolve.defined_drop_ids():
            await interaction.followup.send(
                f"There is no drop {back_to_drop} in the content files.",
                ephemeral=True,
            )
            return
        landing = back_to_drop

    keeping = {}
    if keep_art:
        try:
            keeping = await database.art_urls(guild.id)
        except SQLAlchemyError:
            log.exception("Could not read the art before resetting %s", guild.id)

    try:
        cleared = await content_loader.reset_guild(guild.id, drop=landing)
        if channel_id is not None:
            await database.set_announcement_channel(guild.id, channel_id)
        for art_id, url in keeping.items():
            await database.record_art(guild.id, art_id, url)
    except (content.ContentError, SQLAlchemyError) as exc:
        log.exception("Reset failed for %s", guild.id)
        await interaction.followup.send(
            f"The reset did not finish: {exc}. Nothing partial has been left "
            "behind - the whole thing is one transaction.",
            ephemeral=True,
        )
        return

    if landing != current:
        await _reregister(interaction, guild, landing)

    placed = cleared.pop("_placed", 0)
    rows = sum(cleared.values())
    lines = [
        f"**{guild.name}** is back to the morning before anybody entered.",
        f"- cleared {rows} row(s) across {len(cleared)} table(s)",
        f"- put {placed} thing(s) back in the house",
    ]
    if keeping:
        lines.append(f"- kept {len(keeping)} uploaded image(s)")
    if landing is None:
        lines.append("- no game here yet; `/start-game` opens one")
    elif landing == current:
        lines.append(f"- still on drop {landing}, in the same channel")
    else:
        lines.append(f"- rewound from drop {current} to drop {landing}")
    lines.append(
        "- day one starts again on the next `/enter`, and every player will "
        "need to run it"
    )
    if cleared:
        worst = sorted(cleared.items(), key=lambda kv: -kv[1])[:5]
        lines.append("\n" + ", ".join(f"`{name}` {n}" for name, n in worst))

    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.command(
    name="initialize-haunted-house",
    description="(Admin) Rebuild every haunted house thread from scratch.",
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    art_channel="Where to post the ten cat images once. A mod-only channel is fine - "
    "players never need to see it."
)
async def initialize_haunted_house(
    interaction: discord.Interaction,
    art_channel: discord.TextChannel | None = None,
) -> None:
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
        # This is where achievement names get posted, recorded now so the
        # announcement path never has to guess at a channel name.
        #
        # The restock calendar is deliberately *not* started here. Day one is
        # the day the first player runs `/enter`, so a house can be built days
        # before the game opens without the spice jars arriving early.
        await database.set_announcement_channel(interaction.guild_id, channel.id)
    except SQLAlchemyError:
        log.exception("Could not record the announcement channel")

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

    # The art, into a channel the admin picked. Only what is missing, so a
    # re-run costs nothing; and the house is worth building without it,
    # because every message that wants an image degrades to text.
    art_note = None
    if art_channel is not None:
        uploaded, art_problems = await upload_art(interaction.guild, art_channel)
        art_note = f"- uploaded {uploaded} image(s) to {art_channel.mention}"
        result.errors.extend(art_problems)
    else:
        try:
            have = len(await database.art_urls(interaction.guild_id))
        except SQLAlchemyError:
            have = 0
        if have == 0:
            art_note = (
                "- no images uploaded. Re-run with `art_channel` set and the cat "
                "will appear on achievements; until then every message is text."
            )

    lines = [
        f"Haunted House initialized with {result.created} threads in **{interaction.guild.name}**.",
        f"- deleted {result.deleted} existing thread(s)",
        f"- restored {result.restored} player(s) to their current room",
    ]
    if art_note:
        lines.append(art_note)
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


# Art fires on things that happen, never on a state that can flip. An
# achievement has a before and an after and an image marks it once; a
# relationship score or a craving guess is a value that can go back the other
# way an hour later, and an image that blinks on and off with it stops being
# a reward and becomes a status bar.
#
# The mapping lives here rather than in `art.tsv` for the same reason the
# achievement conditions do: the file carries what a writer owns.
# Which achievement's private message carries which hint. Keyed on the
# achievement rather than fired from the action, because the sentence is
# about the award: "you've gotten your first achievement" belongs under
# the line announcing it, not under the pet that happened to earn it.
#
# Only one today, and only the friendly fork: a first standoffish pet
# earns nothing, so its hint has no award to ride and stays on the pet.
FIRST_CONTACT = "making_first_contact"
HINT_FOR_ACHIEVEMENT = {FIRST_CONTACT: hints.FIRST_FRIENDLY}

ART_FOR_ACHIEVEMENT = {
    "making_friends": "black_cat_content",
    "cats_best_friend": "black_cat_content",
    "trying_to_make_friends": "black_cat_disdain",
    "met_the_craving": "black_cat_happy_bowl",
    "charcuterie_board": "black_cat_gorging",
    "bulk_buyer": "black_cat_gorging",
    "the_feline_collection": "black_cat_gorging",
    "follow_your_nose": "black_cat_sniffing",
    "catproof_the_house": "black_cat_bottle",
    # No live trigger in Release 1 - the ghost system is not built - and
    # shipped anyway so the image is there the day the ghosts land.
    "getting_into_the_spirit": "black_cat_startled",
}

ART_FIRST_PET = "black_cat_alert"
ART_CROWDING = "black_cat_suspicious"
ART_DIAPER = "black_cat_sniffing"
# The bot's face on every message she sends. Set by hand in the developer
# portal, and never sent as an embed image: an avatar and a thumbnail of the
# same face six pixels apart looks like a mistake.
ART_AVATAR = "black_cat_icon"

DIAPER = "dirty_diaper"
DIAPER_SEEN = "diaper_seen"


async def _with_art(guild, text: str, art_id: str | None):
    """A message, and the image that marks it if there is one.

    Returns `(content, embed)` for a send. **A missing image degrades to
    text**: if the art was never uploaded, or its URL has rotted, the message
    still goes out. Nothing in the game is load-bearing on a picture.

    One image per embed, because Discord allows a single `image` plus a
    single `thumbnail` and this set never wants both.
    """
    if art_id is None or guild is None:
        return text, None
    try:
        urls = await database.art_urls(guild.id)
    except SQLAlchemyError:
        log.warning("Could not read the art for %s", guild.id, exc_info=True)
        return text, None

    url = urls.get(art_id)
    if not url:
        return text, None

    embed = discord.Embed(description=text)
    embed.set_image(url=url)
    return None, embed


async def _post_quietly(channel, text: str, art_id: str | None = None) -> None:
    """Post without pinging anybody.

    A display name is printed as plain text, so one containing something
    mention-shaped cannot turn into a ping. Applied on every public line that
    names a player.
    """
    content_, embed = await _with_art(getattr(channel, "guild", None), text, art_id)
    try:
        await channel.send(
            content_, embed=embed, allowed_mentions=discord.AllowedMentions.none()
        )
    except discord.HTTPException:
        log.warning("Could not post in %s", getattr(channel, "name", "?"), exc_info=True)


async def _show_tutorial(thread, guild_id: int, user_id: int) -> None:
    """Teach the three verbs, once per player and never again.

    Not gated on petting the cat: a tutorial a player only sees if they happen
    to find the cat is a tutorial some players never see. It teaches `/look`,
    `/take` and `/use` and deliberately not `/pet` - the public line a pet
    posts introduces that command by itself.
    """
    if await states.has(guild_id, user_id, TUTORIAL_SEEN):
        return
    text = await phrasing.default_say("tutorial")
    if not text:
        return
    try:
        await thread.send(text)
    except discord.HTTPException:
        # Better to show it next time than to burn the flag on a failed send.
        log.warning("Could not post the tutorial for %s", user_id, exc_info=True)
        return
    await states.set_player_state(guild_id, user_id, TUTORIAL_SEEN)


async def _arrive_in(thread, guild_id: int, user_id: int, room_id: str) -> None:
    """Add the player to a room's thread and describe it to them."""
    await house_utils.add_player_to_thread(thread, user_id)
    await thread.send(await _look_around(guild_id, user_id, room_id))


@bot.tree.command(
    name="enter",
    description="Enter the haunted house.",
)
@app_commands.guild_only()
async def enter(interaction: discord.Interaction) -> None:
    """Put a member inside the house, or put them back.

    Self-serve, so nobody has to be awake when a latecomer turns up on 14
    October, and there is no reaction handler to build.

    For somebody already playing this is a repair tool rather than an error:
    they land back in the room they were in, not the Entryway. People leave
    threads by hand and need a way back, and that is cheaper than an admin
    command.

    **A player row is not the same as having been inside.** `/pet` creates one
    for anybody who pets the cat in the channel, so a member can have a
    relationship score and no room at all. That case takes the first-time
    path, tutorial included.
    """
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command only works inside a server.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    user, guild_id = interaction.user, interaction.guild_id

    channel = house_utils.find_channel(interaction.guild)
    if channel is None:
        await interaction.followup.send(
            f"There's no #{house_utils.HALLOWEEN_CHANNEL_NAME} channel yet. "
            "An admin needs to create it and run `/initialize-haunted-house`.",
            ephemeral=True,
        )
        return

    # The one place a member types a command before they are inside, so it has
    # to be somewhere they can find: the channel the house was built in.
    if interaction.channel != channel:
        await interaction.followup.send(
            f"Run this in {channel.mention} and I'll let you in.", ephemeral=True
        )
        return

    try:
        state = await database.get_game_state(user.id, guild_id)
        # A row with no room is somebody who petted the cat and never came in.
        returning = state is not None and state.current_room
        room_id = state.current_room if returning else await resolve.starting_room()
        room_name = await resolve.room_name(room_id) if room_id else None
    except SQLAlchemyError:
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    if room_name is None:
        await interaction.followup.send(
            "No rooms are loaded yet. Ask an admin to check the logs.",
            ephemeral=True,
        )
        return

    try:
        thread = await house_utils.get_thread_for_room(channel, room_name)
    except discord.HTTPException:
        log.exception("Could not look up the %s thread", room_name)
        await interaction.followup.send(GENERIC_ERROR_MESSAGE, ephemeral=True)
        return

    if thread is None:
        await interaction.followup.send(
            "The haunted house hasn't been built yet. "
            "Ask an admin to run `/initialize-haunted-house`.",
            ephemeral=True,
        )
        return

    if returning:
        try:
            await _arrive_in(thread, guild_id, user.id, room_id)
        except discord.HTTPException:
            log.exception("Could not put %s back in %s", user.id, room_id)
            await interaction.followup.send(GENERIC_ERROR_MESSAGE, ephemeral=True)
            return
        await interaction.followup.send(
            await phrasing.default_say(
                "enter.returning", room=room_name, thread=thread.mention
            ),
            ephemeral=True,
        )
        return

    try:
        # The Secret Library is not among these: it is found by climbing the
        # oak, which is what puts it in the list.
        await database.start_game(
            user.id, guild_id, room_id, await resolve.rooms_open_at_launch()
        )
        # Day one is the day somebody first walked in, not the day the house
        # was built - an admin can initialize days early. Idempotent, so only
        # the first `/enter` on this server counts.
        opened = await restocking.set_initialized_on(guild_id)
        log.info("Guild %s: day one is %s (first entry by %s)", guild_id, opened, user.id)
    except SQLAlchemyError:
        await interaction.followup.send(GENERIC_ERROR_MESSAGE, ephemeral=True)
        return

    try:
        await _arrive_in(thread, guild_id, user.id, room_id)
    except discord.HTTPException:
        # Undo the enrolment rather than record somebody as inside a house
        # they were never let into.
        log.exception("Failed to place %s in %s; rolling back", user.id, room_id)
        try:
            await database.delete_game_state(user.id, guild_id)
        except SQLAlchemyError:
            log.error("Rollback failed for %s - player may be stuck enrolled", user.id)
        await interaction.followup.send(GENERIC_ERROR_MESSAGE, ephemeral=True)
        return

    await _show_tutorial(thread, guild_id, user.id)

    # Public, in the channel: it builds the sense of a group going in
    # together and shows latecomers a working example of the command.
    await _post_quietly(
        channel,
        await phrasing.default_say("enter.public", player=user.display_name),
    )
    await interaction.followup.send(
        await phrasing.default_say("enter.arrived", thread=thread.mention),
        ephemeral=True,
    )


class _InTheChannel:
    """What `/use` needs of a game state, for a player who has no row.

    `/enter` does not exist at the drops where the channel is the only
    place there is, so nobody standing in it has a `player_game_state`.
    The use path reads exactly one field off it, and inventing a row in
    the database to carry that would be a player record for somebody who
    has not played.
    """

    current_room = content.CHANNEL_ROOM


# Things that are the cat, for the purpose of the nightly drift. Using
# any of them counts as having turned up, whether or not it worked. The
# toy and the food join this set when drops 2 and 3 build them.
CAT_INTERACTIONS = frozenset({world.CAT_BED})


@bot.tree.command(name="use", description="Attempt to use an object.")
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
        # Standing in the channel, which is a room with no player rows in
        # it. Checked before the game state for the same reason `/look`
        # checks it there: at the drops where this is the only place
        # there is, nobody has entered anything.
        if await _in_the_channel(interaction):
            await database.ensure_user_exists(user.id, guild_id)
            state = _InTheChannel()
        else:
            state = await database.get_game_state(user.id, guild_id)
            if state is None:
                await interaction.followup.send(
                    "You're not in the haunted house yet. Use `/enter` first.",
                    ephemeral=True,
                )
                return

            elsewhere = await _outside_the_house(interaction, state.current_room)
            if elsewhere:
                await interaction.followup.send(elsewhere, ephemeral=True)
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
            key = "use_fail.absent" if found.exists_elsewhere else "use_fail.unknown"
            await interaction.followup.send(
                await phrasing.default_say(key, name=thing.strip()), ephemeral=True
            )
            return

        # Reaching for the cat counts as turning up, whether or not it
        # works. The bed refuses inside its window and the toy's first
        # offer is a guaranteed refusal; the drift exists to notice
        # absence, and a player who tried was not absent.
        if found.thing_id in CAT_INTERACTIONS:
            await database.touched_the_cat(
                user.id, guild_id, await database.server_today(guild_id)
            )
        if found.thing_id == world.CAT_BED:
            # Recorded on the attempt, like the stamp above: a player
            # refused because they fluffed it this morning has still
            # learnt what `/use` is, and does not need telling.
            await hints.did(guild_id, user.id, hints.DID_USE_BED)

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

        # **Keyed on `takeable`, not on `/use`.** A thing you could pick
        # up has to be in your hands; a thing you could not is used where
        # it stands and is never carry-checked. Written as a property of
        # the verb instead, this would make every fixture permanently
        # unusable - the cat bed, which nobody can pocket, and the
        # Amazon box in drop 3, whose whole easter egg is `/use` on a
        # thing you were never meant to carry.
        if row.type == world.TOY:
            # Offering a toy counts as having learnt `/use`, whether or
            # not she plays and whether or not they were holding it.
            await hints.did(guild_id, user.id, hints.DID_USE_TOY)

        if row.takeable and found.where is not reach.Where.CARRIED:
            await interaction.followup.send(
                await phrasing.default_say("use_fail.not_carried", name=found.name),
                ephemeral=True,
            )
            await _hold_to_use_hint(interaction, found)
            return

        if row.type == world.TOY:
            await _play_with_toy(interaction, state, found)
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

    **A thing with a refusal written and no success written refuses.** The
    cat is the only one today: `/use cat` should hand the player `/pet`
    rather than the house's "you turn it over in your hands". A writer who
    filled in `use_fail` and left `use` empty has said what they meant, and
    unlike a state change a refusal cannot create a loop or an unreachable
    room - so this one rule is safe to read out of content rather than
    naming the cat in code the way `world` names the lumber.
    """
    user, guild_id = interaction.user, interaction.guild_id

    held = await states.in_force(guild_id, user.id)
    current = sorted(held)[0] if held else resolve.DEFAULT_STATE
    if not await phrasing.say(guild_id, found.thing_id, "use", state=current):
        refusal = await phrasing.say(
            guild_id, found.thing_id, "use_fail", state=current, name=found.name
        )
        if not refusal:
            # **`use.default` assumes something in your hands** - "you
            # turn the {name} over in your hands" is nonsense on a fence
            # or a ditch, and `/use` is one of only two verbs drop 1
            # has, so every scenery noun is one command away from it.
            #
            # **Scenery only, not every `takeable = no` row**, though
            # the argument reads as though it should cover the stove
            # too. Widening it changes shipped drop-3 behaviour: a house
            # fixture with a blank `use` cell falls through to
            # `use.default` *and counts as a use*, which is a contract
            # two tests in `test_verbs.py` pin on purpose because use
            # counts feed achievements. Scenery is new, so confining the
            # refusal to it changes nothing that already works. Widening
            # it is this condition and those two tests, together.
            row_here = await phrasing.thing_row(found.thing_id)
            if row_here is not None and row_here.type in content.SCENERY_TYPES:
                refusal = await phrasing.default_say(
                    "use_fail.fixture", name=found.name
                )
        if refusal:
            await interaction.followup.send(refusal, ephemeral=True)
            return

    # Some things are used up. It has to come off the bag rather than out of
    # the room, so a burrito lying on the floor is eaten only by somebody who
    # picked it up first - and a player who is looking at one rather than
    # carrying it is told to take it, not quietly fed.
    row = await phrasing.thing_row(found.thing_id)
    if row is not None and getattr(row, "consumed_on_use", False):
        if not await database.consume_carried(user.id, guild_id, found.thing_id):
            await interaction.followup.send(
                await phrasing.default_say("use_fail.not_carried", name=found.name),
                ephemeral=True,
            )
            return

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

    # Awarded before the rail reads anything, announced after the reply
    # goes out. A tester who used the cat bed was told *Fluffed to
    # Perfection* was available by the very message that earned it,
    # because the hint was composed while the award was still a moment
    # away.
    earned = await _fire(
        achievements.Context(
            guild_id=guild_id,
            hook="on_use",
            user_id=user.id,
            thing_id=found.thing_id,
            room_id=state.current_room,
        ),
        interaction=interaction,
        announce=False,
    )

    # A use that moved the meter is the case `on_relationship_change`
    # exists for: reaching fifty by fluffing the bed has to be noticed
    # without waiting for the player's next pet.
    if effect and effect.relationship is not None:
        earned += await _fire(
            achievements.Context(
                guild_id=guild_id,
                hook="on_relationship_change",
                user_id=user.id,
                extra={"relationship": effect.relationship},
            ),
            interaction=interaction,
            announce=False,
        )

    privately = True
    if found.thing_id == world.CAT_BED:
        # A successful fluff shakes something out of the bed, once per
        # player ever. The yield is what gives drop 2 something to
        # reach for when the toy is on its cooldown.
        dislodged = None
        if effect is not None and effect.relationship is not None:
            dislodged = await world.dislodge_from_bed(guild_id, user.id)

        if dislodged and await _announce_bed_yield(interaction):
            # **The public line is the whole event now.** It says both
            # halves - something fell out, and the cat took the bed
            # anyway - so the private fluff text underneath it was the
            # same beat told twice.
            #
            # The `BED_YIELD` rung is deliberately *not* spent here. It
            # rides a private message, there is no longer one to ride,
            # and burning it would retire a nudge nobody read. The
            # public line already says something fell out, which is
            # what the hint was for.
            privately = False
        else:
            carried = any(a.achievement_id in HINT_FOR_ACHIEVEMENT for a in earned)
            nudge = hints.BED_YIELD if dislodged else hints.TRY_LOOK
            reply = hints.beneath(
                reply,
                None if carried else await hints.after(guild_id, user.id, nudge),
            )

    if privately:
        await interaction.followup.send(reply, ephemeral=True)
    else:
        await _dismiss(interaction)

    if effect and effect.public:
        await _post_in_room(interaction, state.current_room, reply)

    await _announce_all(earned, interaction=interaction)


async def _fire(context, *, interaction=None, guild=None, announce=True) -> list:
    """Run a hook, award what passed, and announce what this call created.

    One function for all nine hooks, so an achievement cannot be awarded in
    one call site and left unannounced in another - the same reason every
    world-changing use routes through `_finish_use`.

    Everything here is decoration on an action that has already committed, so
    nothing raises: a player who loses an achievement to a Discord hiccup can
    earn it next time, and a player whose `/take` returns an error has lost
    the thing.

    **`announce=False` awards now and announces later**, and the caller
    takes the returned list to `_announce_all` once its own reply has
    gone out. That exists because the hint rail reads what a player has
    earned: a tester who used the cat bed was told a quest was
    available by the very message that completed it, because the reply
    was composed before the award landed. Awarding first and announcing
    second keeps what the player sees in the same order while letting
    the rail see the truth.
    """
    try:
        # Give the context this server's clock unless the caller pinned
        # one. The date-gated achievements read `context.when`, and a
        # test server a week ahead has to be able to reach 31 October
        # without waiting for it.
        if context.now is None:
            context = dataclasses.replace(
                context, now=await database.server_now(context.guild_id)
            )
        earned = await achievements.fire(context)
    except Exception:
        log.exception("Achievement hook %s failed", context.hook)
        return []

    if announce:
        await _announce_all(earned, interaction=interaction, guild=guild)
        return []
    return earned


async def _announce_all(earned, *, interaction=None, guild=None) -> None:
    """Announce a held-back list, in the order it was earned."""
    for award in earned:
        await _announce(award, interaction=interaction, guild=guild)


async def _announce(award, *, interaction=None, guild=None) -> None:
    """Two messages: the earner gets the detail, the server gets the event.

    **The public line carries the name and never the description.** That is
    what lets a secret achievement announce like any other - *Out on a Limb*
    appearing in the channel tells the server there is a tree worth climbing,
    which is the feature. Eighteen quiet hints spread across October, each
    arriving because somebody actually found something.

    The award is already written, so every branch here logs rather than
    raising: an announcement that fails leaves the achievement in place and
    `/stats` still shows it.
    """
    if guild is None and interaction is not None:
        guild = interaction.guild
    if guild is None:
        log.warning("Earned %s with no guild to announce it in", award.achievement_id)
        return

    channel = await _announcement_channel(guild)
    earner = _earner_of(award, interaction, guild)

    if award.user_id is None:
        # A group achievement has no earner, so "somebody earned" is the
        # wrong sentence and there is nobody to write to privately. The
        # server is named instead, and this is the one place the description
        # belongs in public.
        line = await phrasing.default_say(
            "achievement.public.group",
            server=guild.name,
            achievement=award.name,
            description=award.unlock,
        )
    else:
        line = await phrasing.default_say(
            "achievement.public",
            player=earner or "Somebody",
            achievement=award.name,
        )

    # The image rides whichever message carries the description, which is the
    # private one for a player and the public one for a group - a group
    # achievement has no earner and so no private message to put either in.
    art = ART_FOR_ACHIEVEMENT.get(award.achievement_id)
    if channel is not None and line:
        # Plain text and no ping: a display name containing something
        # mention-shaped must not turn into one.
        await _post_quietly(channel, line, art if award.user_id is None else None)

    if award.user_id is None:
        return

    # **No DM, deliberately.** Three achievements fire without an interaction
    # to answer - *Met the Craving* on a reaction, *Passing a Message to
    # David* on a message, and anything on the midnight job - and a bot DM
    # would need a delivery path that can silently fail, a member setting
    # nobody controls, and a second message format to maintain, all for two
    # of them. They get the public line only. The cost is that their earner
    # never reads the description, which is acceptable because both are
    # things the player just deliberately did.
    if interaction is None:
        log.info(
            "No interaction for %s; the public line is the whole announcement",
            award.achievement_id,
        )
        return

    private = await phrasing.default_say(
        "achievement.private", achievement=award.name, description=award.unlock
    )
    if not private:
        return

    # A hint that is about having earned something rides the message
    # that says so, rather than the action that earned it. Attached the
    # same way the art is, from a map keyed on the achievement, because
    # it is the same kind of fact: this award carries this extra.
    nudge = HINT_FOR_ACHIEVEMENT.get(award.achievement_id)
    if nudge is not None:
        private = hints.beneath(
            private, await hints.after(guild.id, award.user_id, nudge, quests=False)
        )

    content_, embed = await _with_art(guild, private, art)
    try:
        await interaction.followup.send(content_, embed=embed, ephemeral=True)
    except discord.HTTPException:
        log.warning("Could not send %s privately", award.achievement_id, exc_info=True)


def _earner_of(award, interaction, guild) -> str | None:
    """The display name to print, without pinging anybody.

    The interaction knows it directly. Off a reaction or a message there is
    no interaction, so the guild's member cache is asked instead - and when
    that misses, the public line still posts with a placeholder rather than
    being dropped, because the event matters more than the name.
    """
    if award.user_id is None:
        return None
    if interaction is not None:
        return interaction.user.display_name
    member = guild.get_member(award.user_id)
    return member.display_name if member is not None else None


async def upload_art(guild, channel) -> tuple[int, list[str]]:
    """Post each image once and keep the URL Discord hands back.

    Only what is missing, so re-running initialization is free rather than
    posting ten more pictures. Returns (uploaded, problems) and never raises:
    the house is worth building even if the art fails, and every message
    degrades to text without it.
    """
    try:
        rows = content.load_files().art
        have = await database.art_urls(guild.id)
    except (content.ContentError, SQLAlchemyError) as exc:
        return 0, [f"could not read the art: {exc}"]

    uploaded, problems = 0, []
    for row in rows:
        if row.art_id in have:
            continue
        path = content.ART_DIR / row.file
        if not path.is_file():
            problems.append(f"{row.art_id}: {row.file} is missing")
            continue
        try:
            posted = await channel.send(
                file=discord.File(path, filename=row.file),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            url = posted.attachments[0].url
        except (discord.HTTPException, IndexError, AttributeError) as exc:
            problems.append(f"{row.art_id}: {exc}")
            continue
        try:
            await database.record_art(guild.id, row.art_id, url)
        except SQLAlchemyError:
            problems.append(f"{row.art_id}: uploaded but not recorded")
            continue
        uploaded += 1

    return uploaded, problems


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


async def _play_with_toy(interaction, state, found) -> None:
    """Offer a toy to the cat, and report how she took it.

    The two refusals read differently on purpose. Inside the cooldown
    she is *finished*, which is the toy's own `use_fail` line; on a
    failed roll she simply declines, which is one of twelve generic
    lines so the most-read string in the drop is not the same string
    every time.

    Every attempt counts as having turned up - successes, ramp refusals
    and cooldown refusals alike - because the nightly drift exists to
    notice absence and the first offer is a guaranteed refusal.
    """
    user, guild_id = interaction.user, interaction.guild_id
    now = await database.server_now(guild_id)
    await database.touched_the_cat(user.id, guild_id, await database.server_today(guild_id))

    _, until = await database.play_state(guild_id, user.id)
    if until is not None and now < until:
        # A refused attempt is not an attempt: the ramp does not move,
        # so nobody can bank four refusals during the cooldown and
        # convert the instant it lifts.
        await interaction.followup.send(
            await phrasing.say(
                guild_id, found.thing_id, "use_fail",
                fallback="use_fail.cooldown",
                name=found.name,
                time=phrasing.approximate_duration(until - now),
            ),
            ephemeral=True,
        )
        return

    effect = await world.play_with(guild_id, user.id, now)
    succeeded = effect.relationship is not None

    if succeeded:
        await database.record_use(user.id, guild_id, found.thing_id)
        reply = await phrasing.say(
            guild_id, found.thing_id, "use",
            fallback="use.default",
            name=found.name,
            player=user.display_name,
        )
    else:
        reply = await _a_play_refusal(found.name)

    # The best moment in the drop, and the only thing that makes other
    # players visible to each other in a phase with no rooms. Refusals
    # stay private: at 3.2 attempts per success the channel would be a
    # wall of a cat declining to move.
    #
    # **A success is public and nothing else.** It used to be both, and
    # the player who had just played with the cat read the same
    # sentence twice - once in the spinner and once in the channel
    # underneath it. The private copy is kept only for the case where
    # the public one did not go out, because the rate limit can still
    # swallow it and a silent success reads as being ignored.
    if succeeded and await _announce_play(interaction, reply):
        await _dismiss(interaction)
    else:
        await interaction.followup.send(reply, ephemeral=True)

    earned = await _fire(
        achievements.Context(
            guild_id=guild_id,
            hook="on_use",
            user_id=user.id,
            thing_id=found.thing_id,
            room_id=state.current_room,
            extra={"played": succeeded, "ramp": effect.tokens.get("ramp", 0)},
        ),
        interaction=interaction,
        announce=False,
    )
    if succeeded:
        earned += await _fire(
            achievements.Context(
                guild_id=guild_id,
                hook="on_relationship_change",
                user_id=user.id,
                extra={"relationship": effect.relationship},
            ),
            interaction=interaction,
            announce=False,
        )
    await _announce_all(earned, interaction=interaction)


async def _dismiss(interaction) -> None:
    """Take back the ephemeral "thinking" placeholder.

    **Needed whenever a public line replaces a private one.** Every
    world verb defers with `thinking=True`, which puts a spinner in
    front of the player that only a followup clears. Simply not sending
    one leaves them looking at it until Discord gives up and says the
    application did not respond - so an action whose whole output is
    public has to withdraw the placeholder rather than ignore it.
    """
    try:
        await interaction.delete_original_response()
    except discord.HTTPException:
        # The reply is already out in the channel; a placeholder that
        # outlives it is untidy, not broken.
        log.warning("Could not withdraw the deferred reply", exc_info=True)


async def _say_in_the_room(interaction, line: str, nudges=()) -> None:
    """Post what happened where the room can read it, and nudge privately.

    **`/take` and `/drop` say one sentence, to everybody.** They used to
    post their whole reply publicly while every written string was
    second person - "You pocket the spice jar" - so the room was told
    that *it* had picked something up. The strings are third person
    now and name the player, which makes one public line correct for
    the player and the room at once. There is no private copy to drift
    from it.

    Hints are the exception and stay private: they are advice to one
    player about what to type next, and the rest of the room neither
    needs them nor should be told how far along somebody else is.

    No rate limit on the line. Unlike petting there is a finite amount
    to pick up and put down, so the room cannot be flooded by somebody
    enjoying themselves.
    """
    channel = interaction.channel
    posted = False
    if channel is not None and hasattr(channel, "send") and line:
        await _post_quietly(channel, line)
        posted = True

    if posted:
        # Nothing private follows, so the deferred placeholder has to be
        # withdrawn or the player is left watching a spinner.
        await _dismiss(interaction)
    else:
        # The room could not be reached. Better the player reads their
        # own name in an ephemeral reply than that the verb appears to
        # have done nothing.
        await interaction.followup.send(line, ephemeral=True)

    for nudge in nudges:
        if nudge:
            await interaction.followup.send(nudge, ephemeral=True)


async def _announce_bed_yield(interaction) -> bool:
    """The bed's one public line. True if it actually went out.

    The work order has it *replacing* the ordinary public fluff post.
    There is nothing to replace: `/use` on a thing is private except
    the staircase plank, so the fluff has never had a public line and
    this is the bed's only one.

    **The caller needs to know whether it posted**, because the private
    fluff text is now suppressed in favour of it. A yield that says
    nothing publicly *and* nothing privately is a fluff that appears to
    have done nothing at all, which is worse than the duplication this
    replaced.
    """
    channel = interaction.channel
    if channel is None or not hasattr(channel, "send"):
        return False
    line = await phrasing.default_say(
        "bed_yield.public", player=interaction.user.display_name
    )
    if not line:
        return False
    await _post_quietly(channel, line)
    return True


async def _a_play_refusal(name: str) -> str:
    """One of the twelve, picked uniformly.

    Numbered keys rather than variants inside one cell: the writers
    review these as tables and `|` is the column delimiter, so the first
    edit would split a refusal in two. A thirteenth is a row.
    """
    texts = await phrasing.defaults_matching(REFUSAL_PREFIX)
    if not texts:
        return await phrasing.default_say("use_fail.default", name=name)
    return phrasing.fill(random.choice(texts), name=name)


async def _announce_play(interaction, line: str) -> bool:
    """The public half of a successful play. True if it went out.

    Its own rate-limit budget rather than the pet line's, so a player
    who has just spent their petting allowance still gets a line for
    the rarer and better event. In practice it will almost never bite:
    the ten-minute cooldown already caps successes at about three per
    half hour.

    **It is now the only half**, which is why the caller is told
    whether it posted. The rate limit can still swallow it, and a
    success that says nothing anywhere would read as the cat ignoring
    you - the one thing a success must never look like.
    """
    channel = interaction.channel
    if channel is None or not hasattr(channel, "send"):
        return False
    which = _public_play_line(
        interaction.guild_id, interaction.user.id, getattr(channel, "id", 0),
        await database.server_now(interaction.guild_id),
    )
    if which is None:
        return False
    await _post_quietly(channel, line)
    return True


async def _hold_to_use_hint(interaction, found) -> None:
    """The rung that fires on being told to pick it up first."""
    line = await hints.after(
        interaction.guild_id, interaction.user.id, hints.HOLD_TO_USE, quests=False
    )
    if line:
        await interaction.followup.send(line, ephemeral=True)


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
        elapsed = await database.server_now(guild_id) - previous
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

    # `has_key` is folded in here: it is derived from the inventory rather
    # than stored, and text keyed on it has to resolve like any other state.
    held = await world.states_for_exit(guild_id, user.id)

    # The oak is the exception to `rooms_unlocked`, and it has to be. The
    # Secret Library is `open_at_launch = no`, so nobody starts with it
    # unlocked - and an exit gated on the state its own use produces is a
    # locked door with the key inside. Climbing the tree is what unlocks the
    # room, so the check cannot come first.
    unreachable = destination not in state.rooms_unlocked and found.thing_id != world.OAK
    if unreachable or world.exit_refused_by(found.thing_id, held):
        await interaction.followup.send(
            await phrasing.say(
                guild_id, found.thing_id, "use_fail", state=world.exit_state(held),
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
        # The discovery is recorded after the move has committed, so a player
        # who could not be moved is not told they found something.
        await world.after_move(guild_id, user.id, found.thing_id)
        if destination not in state.rooms_unlocked:
            await database.unlock_room(user.id, guild_id, destination)
        # `held` is deliberately *not* updated with what was just discovered.
        # 2c.5 resolves a use's text after its effect, so the drawer can be
        # described by the state it produced - but a discovery is the opposite
        # case. The long text is the reveal and is written to be read once;
        # the state it sets is what makes every later use read the short one.
    except SQLAlchemyError:
        try:
            await house_utils.remove_player_from_thread(destination_thread, user.id)
        except discord.HTTPException:
            log.exception("Rollback failed: %s left in %s", user.id, destination)
        await interaction.followup.send(MOVE_ERROR_MESSAGE, ephemeral=True)
        return

    # The move has happened. What follows is presentational, so a failure is
    # logged rather than surfaced - the player is already through the door.
    # A secret exit overrides both lines, because the house defaults give it
    # away twice: "exits via the oak tree" teaches the Courtyard that the tree
    # is a way out, and "arrives from the Secret Library" names the secret
    # outright. The overrides say that somebody moved and nothing else.
    state_now = world.exit_state(held)
    depart = await phrasing.say(
        guild_id, found.thing_id, "move_depart", state=state_now,
        fallback="move.depart",
        player=user.mention, name=found.name, room=origin_name,
    )
    arrive = await phrasing.say(
        guild_id, found.thing_id, "move_arrive", state=state_now,
        fallback="move.arrive",
        player=user.mention, name=found.name, room=origin_name,
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

    # The exit's own words, which no exit has ever printed: every one of the
    # twenty has a `use` line written and players only ever saw "You head to".
    # It is what carries the discovery when somebody climbs the oak, and the
    # state decides whether they get the long version or the short one.
    walked = await phrasing.say(
        guild_id, found.thing_id, "use", state=state_now, name=found.name
    )
    arriving = f"You head to {destination_thread.mention}."
    await interaction.followup.send(
        f"{walked}\n\n{arriving}" if walked else arriving, ephemeral=True
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
        # The channel is a room, and standing in it needs no player row:
        # `/enter` does not exist at the drops where this is the only place
        # there is. Checked before the game state for exactly that reason.
        if await _in_the_channel(interaction):
            if thing is None or not thing.strip():
                await hints.did(guild_id, user.id, hints.DID_LOOK)
                reply = await _look_in_the_channel(guild_id, user.id)
                await interaction.followup.send(
                    hints.beneath(
                        reply,
                        # **The newest drop's hint wins.** A player who
                        # never looked at the bed is eligible for both
                        # on their first `/look`, and only one line
                        # goes per message - so it points at the thing
                        # they have not seen. The bed's is not lost; it
                        # fires on their next look if still unmet.
                        await hints.after(
                            guild_id, user.id, hints.LOOK_TOY, hints.LOOK_SPECIFIC
                        ),
                    ),
                    ephemeral=True,
                )
                return
            await _look_at_one_thing(
                interaction, guild_id, user.id, content.CHANNEL_ROOM, thing
            )
            return

        state = await database.get_game_state(user.id, guild_id)
        if state is None:
            await interaction.followup.send(NOT_IN_ROOM_MESSAGE, ephemeral=True)
            return

        elsewhere = await _outside_the_house(interaction, state.current_room)
        if elsewhere:
            await interaction.followup.send(elsewhere, ephemeral=True)
            return

        if thing is None or not thing.strip():
            await interaction.followup.send(
                await _look_here(guild_id, user.id, state.current_room), ephemeral=True
            )
            return

        await _look_at_one_thing(
            interaction, guild_id, user.id, state.current_room, thing
        )
    except SQLAlchemyError:
        log.exception("Failed to look at %r in guild %s", thing, guild_id)
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)


async def _look_at_one_thing(
    interaction, guild_id: int, user_id: int, room_id: str, thing: str
) -> None:
    """`/look <thing>`, from wherever the player is standing.

    Shared by the nine rooms and the channel. The only thing that differs
    between them is which room is passed in - resolution, the two refusals
    and the art all behave the same, and a second copy of this would be a
    second place for them to drift.
    """
    found = await reach.find(guild_id, user_id, room_id, thing, reach.Scope.REACH)

    if isinstance(found, reach.Ambiguous):
        await interaction.followup.send(
            await phrasing.default_say(
                "ambiguous.match", options=", ".join(found.options)
            ),
            ephemeral=True,
        )
        return

    if isinstance(found, reach.NotFound):
        # Naming the room you are standing in is the same question as
        # `/look` with no argument, and players ask it that way. Checked
        # only after resolution fails, so a thing sharing a word with the
        # room still wins - in the Courtyard `/look kitchen` is the back
        # door, because that is what is in front of you.
        if await _is_this_room(room_id, thing):
            await interaction.followup.send(
                await _look_here(guild_id, user_id, room_id), ephemeral=True
            )
            return

        # One refusal per verb for a word the house does not know:
        # `look_fail.unknown` here, `take_fail.unknown` in /take,
        # `use_fail.unknown` in /use. They used to share one line, which
        # meant any rewrite of it had to read sensibly after all three.
        key = "take_fail.absent" if found.exists_elsewhere else "look_fail.unknown"
        await interaction.followup.send(
            await phrasing.default_say(key, name=thing.strip()), ephemeral=True
        )
        return

    text, art = await _look_at(guild_id, user_id, room_id, found)

    row = await phrasing.thing_row(found.thing_id)
    if found.thing_id == world.CAT_BED:
        # Read *before* the action is recorded: the notice fires on the
        # transition, and `hints.did` is what closes it.
        first_time = not await database.has_been_told(
            guild_id, user_id, hints.DID_LOOK_BED
        )
        await hints.did(guild_id, user_id, hints.DID_LOOK)
        await hints.did(guild_id, user_id, hints.DID_LOOK_BED)
        if first_time:
            # **Not a hint**: italic, no label, and it writes nothing to
            # the told-you table. The row the ladder already wrote for
            # this look is what stops it firing twice.
            #
            # It tells them to look again rather than reprinting the
            # channel: the fuller description arrives on their next
            # `/look`, which is the point of saying something moved.
            #
            # Above the hint, because it reports what happened and the
            # hint recommends what to do next. The rail owns the last
            # line of a message everywhere else and keeps it here.
            thinned = await phrasing.default_say("channel.fog_thins")
            if thinned:
                text = f"{text}\n\n*{thinned}*"
        text = hints.beneath(
            text, await hints.after(guild_id, user_id, hints.TRY_USE)
        )
    elif row is not None and row.type == world.TOY:
        # **The verb, not the verb and a noun.** A player who looked at
        # a crinkle ball has learned what looking at a toy is, so the
        # rail must not go on telling them to look at a feather wand.
        await hints.did(guild_id, user_id, hints.DID_LOOK)
        await hints.did(guild_id, user_id, hints.DID_LOOK_TOY)
        text = hints.beneath(
            text,
            await hints.after(guild_id, user_id, hints.TAKE_TOY, name=found.name),
        )

    content_, embed = await _with_art(interaction.guild, text, art)
    await interaction.followup.send(content_, embed=embed, ephemeral=True)


async def _look_here(guild_id: int, user_id: int, room_id: str) -> str:
    """Looking around, wherever "around" is. The channel is a list; a room
    is its prose and then what is loose in it."""
    if room_id == content.CHANNEL_ROOM:
        return await _look_in_the_channel(guild_id, user_id)
    return await _look_around(guild_id, user_id, room_id)


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


async def _is_this_room(room_id: str, typed: str) -> bool:
    """Whether the player typed the name of the room they are standing in.

    Matched on the id, the whole name, or any word of it, so `library` finds
    the Secret Library and `room` finds the Living Room. Loose on purpose and
    safe because it is: there is exactly one room it could mean, and it is
    only asked after nothing in the room matched.

    Rooms carry no alias column, which is why the words come out of the name.
    """
    name = await resolve.room_name(room_id)
    if name is None:
        return False
    wanted = reach.normalise(typed)
    if not wanted:
        return False
    words = {reach.normalise(w) for w in name.split()}
    return wanted in {reach.normalise(name), reach.normalise(room_id), *words}


SEEN_FRAGMENT = "seen.{room}.{fragment}"

# Underscores rather than asterisks, which is the only part of this that
# is not obvious. Every fragment that will ever be marked has bolding in
# it - bolding is how a scenery noun announces itself - and `*a **b** c*`
# asks a markdown parser to decide where one emphasis ends and the next
# begins. `_` cannot collide with `**` at all. It renders identically,
# and it is one constant if that ever stops being true.
NEW_TO_YOU = "_{text}_"


async def _describe_room(
    guild_id: int,
    user_id: int,
    room_id: str,
    state: str,
    unlocked: frozenset[str] = frozenset(),
) -> str | None:
    """The room's description, with the sentences new to this player in italics.

    **A playtester could not tell which lines they had already read.**
    That is a defect in the staged reveal rather than in the prose, and
    it recurs at every drop that adds a fragment to a room somebody has
    already looked at - so it is answered once here rather than for the
    channel's second stage alone.

    No label and no marker glyph. Italics read as emphasis rather than
    as interface, so the fiction survives and the eye still goes to what
    changed.

    **A first look is never marked.** Otherwise a new player's opening
    `/look` arrives entirely in italics, which says "all of this is new"
    to someone for whom nothing can be old. The rows are written anyway,
    so the second look marks only what actually arrived in between.

    **The state is the hints table**, which is `(guild, player, id)` and
    therefore a per-player boolean store under another name. The
    Functional Spec declined a `player_thing_seen` table; it never had
    to be one. A row per fragment a player has been shown costs rows,
    not schema - a couple of dozen per player across the whole house.

    One thing it does not catch, because fragments are keyed by number:
    a fragment whose *text* changes with the room's state is the same
    fragment, so the Entryway's staircase sentence will not be marked
    when the stairs are repaired. That wants its own answer, and it is
    not this one.
    """
    parts = await resolve.room_fragments(guild_id, room_id, state, unlocked)
    if not parts:
        return None

    prefix = SEEN_FRAGMENT.format(room=room_id, fragment="")
    ids = {
        fragment: SEEN_FRAGMENT.format(room=room_id, fragment=fragment)
        for fragment, _ in parts
    }
    try:
        seen = await database.notices_with_prefix(guild_id, user_id, prefix)
    except SQLAlchemyError:
        # The description is the command's whole answer. Losing the
        # marking is a missing italic; losing the paragraph is a `/look`
        # that did nothing.
        log.exception("Could not read seen fragments in %s for %s", room_id, user_id)
        return " ".join(look for _, look in parts)

    first_look = not seen
    fresh = [fragment for fragment, _ in parts if ids[fragment] not in seen]
    await database.notice_many(guild_id, user_id, (ids[f] for f in fresh))

    return " ".join(
        NEW_TO_YOU.format(text=look)
        if not first_look and fragment in set(fresh)
        else look
        for fragment, look in parts
    )


async def _look_around(guild_id: int, user_id: int, room_id: str) -> str:
    """The room's description, then what is lying about in it."""
    state = await _current_state(guild_id, user_id)
    description = (
        await _describe_room(guild_id, user_id, room_id, state)
        or GENERIC_ROOM_DESCRIPTION
    )

    held = await states.in_force(guild_id, user_id)
    loose = await database.loose_here(guild_id, room_id, held_states=held)
    line = await phrasing.listing(
        loose,
        prefix_key="also_here.prefix",
        budget=phrasing.MESSAGE_LIMIT - len(description) - 2,
    )
    return f"{description}\n\n{line}" if line else description


async def _in_the_channel(interaction) -> bool:
    """Whether this command was run in the channel the game lives in.

    Decided by id alone. A room thread has its own id, distinct from the
    channel it hangs off, so this is already false inside one - and asking
    the id rather than the type keeps it true of anything that behaves like
    the channel, which is what the tests hand it.
    """
    if interaction.guild is None:
        return False
    here = getattr(interaction.channel, "id", None)
    return here is not None and here == await database.announcement_channel(
        interaction.guild_id
    )


async def _unlocked_for(guild_id: int, user_id: int) -> frozenset[str]:
    """Which gated fragments this player can see.

    **One lookup against a table that already exists.** The hint ladder
    records each player's first `/look cat bed` because that is what
    retires `hint.look_specific`; the same row is what thins the fog.
    No new table, no new column, and emphatically not the general
    per-player `present_when`, which is a design programme parked in
    V3.2 and would have cost a staged paragraph the same as the whole
    onboarding corridor.
    """
    if await database.has_been_told(guild_id, user_id, hints.DID_LOOK_BED):
        return frozenset({content.LOOKED_AT_BED})
    return frozenset()


async def _look_in_the_channel(guild_id: int, user_id: int) -> str:
    """The channel: its description, then what is lying in it.

    **It used to have no prose, and that was the answer rather than a
    gap** - a `room_text` row for it was a load error. Playtesters
    found drop 1 empty for exactly that reason: `/look` got them
    excited and then offered one noun. The channel now reads like the
    room-like row it always was, which retires the special case rather
    than adding one.

    **And it lists exactly what the house lists: finite takeables.**
    The rule the house has always followed is that the list carries
    what is loose and the prose names everything else - so the prose
    cannot go stale, and a noun is either on the line or in a sentence
    but never both. The channel strayed from it only because it had no
    prose to name anything with. It has prose now, so the stray is over
    and `/look` here is the same two parts in the same order.

    At drop 1 that means the list is empty and the reply is prose
    alone: the cat bed is named in the first fragment. The list first
    appears in drop 2, carrying the toys, which is what it is for.

    **The cat is not in it.** Her row is `room_id = ALL` rather than the
    channel's, so she falls out of this query for free - which is the
    behaviour the work order asks for and the reason it asks: `/look cat`
    is an easter egg, found rather than signposted, and a list reading
    "a cat, a cat bed" would hand over the only discovery drops 0 and 1
    have.
    """
    held = await states.in_force(guild_id, user_id)
    description = await _describe_room(
        guild_id,
        user_id,
        content.CHANNEL_ROOM,
        await _current_state(guild_id, user_id),
        await _unlocked_for(guild_id, user_id),
    )
    # `room_contents`, and nothing else. A list built from home rooms
    # went on naming a toy that had been picked up, which reads as an
    # endless supply and had testers taking it twice - and the fixture
    # half of it is what this change retires, because a cat bed named
    # in the description and listed underneath it is one noun printed
    # twice.
    entries = await database.loose_here(
        guild_id, content.CHANNEL_ROOM, held_states=held
    )
    line = await phrasing.listing(
        entries,
        # The house's prefix, now that the channel has prose above it.
        # `channel.look_prefix` existed to rename `Also here:` to `Items
        # here:` back when the list was the entire output and "also"
        # referred to nothing. With a description over it the word is
        # true again, and a player who walks into the house next drop
        # meets a line they have already read.
        prefix_key="also_here.prefix",
        budget=phrasing.MESSAGE_LIMIT - len(description or "") - 2,
    )
    if description and line:
        return f"{description}\n\n{line}"
    return description or line or await phrasing.default_say("channel.look_empty")


async def _look_at(
    guild_id: int, user_id: int, room_id: str, found
) -> tuple[str, str | None]:
    """One thing, plus its contents if anything is inside it.

    A carried thing uses `look_carried` where it has one: six things describe
    where they were sitting, which stops being true the moment they are picked
    up. Falling back to `look` is right for everything else.

    **Looking at a source describes the source, not what it hands out.** A
    source and its yield are one thing to the resolver - the only reason
    `/take candy` does not raise an ambiguity prompt - so `found` carries the
    yield's id and name. That is right for taking and using, and wrong for
    looking: the writers described the bed of rosemary and the three cut
    sprigs as a pair, and only one of them had ever been readable. The
    resolution ladder sorts out which is meant, because a carried copy and a
    loose copy both win over the source.
    """
    state = await _current_state(guild_id, user_id)

    description = ""
    if found.where is reach.Where.CARRIED:
        description = await phrasing.say(
            guild_id, found.thing_id, "look_carried", state=state, name=found.name
        )

    looking_at, name = found.thing_id, found.name
    if not description and found.where is reach.Where.SOURCE and found.source_id:
        row = await phrasing.thing_row(found.source_id)
        description = await phrasing.say(
            guild_id, found.source_id, "look", state=state,
            name=row.name if row else found.name,
        )
        if description and row is not None:
            looking_at, name = found.source_id, row.name

    if not description:
        # A source with no look text of its own falls back to its yield's,
        # which is what every source did before this.
        description = await phrasing.say(
            guild_id, found.thing_id, "look", state=state, name=found.name
        )
    if not description:
        description = f"You see {name}."

    # Fires on the look whether the diaper is on the floor or already in the
    # bag, and once ever rather than once per diaper: eight a day scatter
    # through the house and the joke is only funny the first time. One named
    # flag, the same shape as `tutorial_seen` - 2d dropped `player_thing_seen`
    # deliberately and one boolean is not a reason to bring it back.
    art = None
    if found.thing_id == DIAPER and not await states.has(guild_id, user_id, DIAPER_SEEN):
        await states.set_player_state(guild_id, user_id, DIAPER_SEEN)
        art = ART_DIAPER

    inside = await database.loose_here(
        guild_id, room_id, container_id=looking_at,
        held_states=await states.in_force(guild_id, user_id),
    )
    line = await phrasing.listing(
        inside,
        prefix_key="contents.prefix",
        budget=phrasing.MESSAGE_LIMIT - len(description) - 2,
    )
    return (f"{description}\n\n{line}" if line else description), art


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

    # Recorded whether or not the bag has anything in it: the lesson is
    # what `/inventory` is, and a player who has opened an empty bag has
    # had it. This retires `hint.check_inventory`.
    await hints.did(interaction.guild_id, interaction.user.id, hints.DID_INVENTORY)

    if not items:
        await interaction.followup.send(
            await phrasing.default_say("inventory.empty"), ephemeral=True
        )
        return

    # The same rendering as a room listing, so a bag of ten herbs reads the way
    # ten herbs on the floor read. Truncation applies here too: nothing caps how
    # much a player can carry.
    reply = await phrasing.listing(items, prefix_key="inventory.prefix")

    # **Only with something in the bag**, because the hint names one:
    # "like /drop feather wand" is a command they can retype, and there
    # is nothing to put in it when the bag is empty. `items` is already
    # in the order the listing prints, so the example is the first thing
    # they can see.
    reply = hints.beneath(
        reply,
        await hints.after(
            interaction.guild_id,
            interaction.user.id,
            hints.DROP_SOMETHING,
            name=items[0][0],
        ),
    )
    await interaction.followup.send(reply, ephemeral=True)


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


async def _room_to_act_in(interaction) -> tuple[str | None, str | None]:
    """(room, refusal). Exactly one is set.

    `/take` and `/drop` share this: both need the player's room and both are
    refused outside it, and having one function answer both means a verb
    cannot be given the room without also being given the check.

    **The channel is a room, and standing in it needs no player row.**
    `/enter` does not exist at the drops where the channel is the only
    place there is, so a player picking up their first toy has never
    entered anything. Checked before the game state for that reason,
    and here rather than in each verb so `/take` and `/drop` cannot
    disagree about where the channel is.
    """
    if await _in_the_channel(interaction):
        await database.ensure_user_exists(interaction.user.id, interaction.guild_id)
        return content.CHANNEL_ROOM, None
    room_id = await _player_room(interaction)
    if room_id is None:
        return None, NOT_IN_ROOM_MESSAGE
    return room_id, await _outside_the_house(interaction, room_id)


@bot.tree.command(name="take", description="Pick something up.")
@app_commands.guild_only()
@app_commands.describe(thing="What to pick up.")
async def take(interaction: discord.Interaction, thing: str) -> None:
    """Take one copy of something in the room.

    Scoped to the room, never the bag. A player carrying chicken beside the
    salmon cupboard who types `/take cat food` gets the salmon, and is not asked
    a question they could not answer.

    **Deferred privately**, because every reply below it is private now -
    the refusals always were, and the success became so when the room
    got its own third-person line. A public deferral leaves a public
    "thinking" placeholder that only a public followup can resolve, so
    the old mix quietly left one hanging after every refusal.
    """
    await interaction.response.defer(ephemeral=True, thinking=True)
    user, guild_id = interaction.user, interaction.guild_id

    try:
        room_id, elsewhere = await _room_to_act_in(interaction)
        if elsewhere:
            await interaction.followup.send(elsewhere, ephemeral=True)
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
        reply = (
            await phrasing.say(
                guild_id, taken, "take", fallback="take.default",
                name=name, player=user.display_name,
            )
            or f"{user.display_name} takes the {name}."
        )

        # `{name}` here is **the toy they just picked up**, not whichever
        # is lying in the channel: they are holding it, and naming a
        # different one would be nonsense.
        nudges = []
        if taken_row is not None and taken_row.type == world.TOY:
            await hints.did(guild_id, user.id, hints.DID_LOOK_TOY)
            await hints.did(guild_id, user.id, hints.DID_TAKE_TOY)
            nudges.append(
                await hints.after(guild_id, user.id, hints.USE_TOY, name=name)
            )
            # **A second message rather than a second line.** The rail
            # allows one hint per message because two stacked read as a
            # tutorial - but picking up your first object *is* the
            # tutorial moment for carrying, and `/use` is the only rung
            # `/take` can offer, so queueing this one behind it would
            # hold it until the player happened to take a second toy.
            nudges.append(
                await hints.after(
                    guild_id, user.id, hints.CHECK_INVENTORY, quests=False
                )
            )

        # **The line is public and nothing else.** Every written take
        # string is third person and names the player, so there is one
        # sentence and the room is its audience - the player reads it
        # there like everybody else.
        await _say_in_the_room(interaction, reply, nudges)

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
    return await phrasing.default_say("take_fail.unknown", name=typed.strip())


def _no_carrying(row) -> str:
    """Which default explains, to this kind of thing, why it stays put.

    `take_fail.fixture` - "the {name} isn't yours to carry off" - assumes
    an owner, which is true of a fence and a wasp nest and nonsense on
    fog. Terrain gets the line about scale instead. Picked off `type` the
    same way `take_fail.exit` already is, so the content file says which
    joke a row is in rather than the engine holding a list of ids.
    """
    if row.type == content.TERRAIN:
        return "take_fail.terrain"
    return "take_fail.fixture"


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
            fallback=_no_carrying(row), name=found.name,
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
        guild_id, taken, "take_fail", fallback=_no_carrying(capped), name=capped.name
    )


@bot.tree.command(name="drop", description="Put something down.")
@app_commands.guild_only()
@app_commands.describe(thing="What to put down.")
async def drop(interaction: discord.Interaction, thing: str) -> None:
    """Drop one copy of something you are carrying, loose in the room.

    **Deferred privately**, like `/take` and for the same reason: every
    reply below it is private, and a public deferral leaves a public
    "thinking" placeholder that only a public followup resolves. The
    one public thing `/drop` says goes to the room directly.
    """
    await interaction.response.defer(ephemeral=True, thinking=True)
    user, guild_id = interaction.user, interaction.guild_id

    try:
        room_id, elsewhere = await _room_to_act_in(interaction)
        if elsewhere:
            await interaction.followup.send(elsewhere, ephemeral=True)
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

        # Retires `hint.drop_something`. Recorded here rather than
        # inferred from an empty bag, because putting one of three
        # things down is just as much having learnt the verb.
        await hints.did(guild_id, user.id, hints.DID_DROP)

        # The same shape as `/take`: one third-person line, to the room.
        # Putting something down is the half of carrying the room most
        # needs to see - it is how a thing becomes available to anybody
        # else - so it would be the stranger of the two to keep quiet.
        await _say_in_the_room(
            interaction,
            await phrasing.say(
                guild_id, found.thing_id, "drop", fallback="drop.default",
                name=found.name, player=user.display_name,
            )
            or f"{user.display_name} sets the {found.name} down.",
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


# An embed's description allows 4,096 characters where a message allows 2,000.
# Thirty-five names plus thirty-five unlock lines passes 2,000 for a
# completionist, and the failure mode would be the command breaking at the end
# of October for exactly the players who played the most.
EMBED_LIMIT = 4096

# `/stats` used to group earned achievements under three headings and
# order them by `sort_order`. V3 lists them newest first and ungrouped, so
# `KIND_HEADINGS`, `KIND_ORDER` and the `NOTHING_YET` line are gone: the
# empty state is a writer's string in `defaults.tsv` now, and the kind of
# an achievement is no longer something the player is shown.


# The flag the quest notice reads, defined with the rail that reads it.
OPENED_STATS = hints.OPENED_STATS

# What a quest looks like in the list. The prompt carries no terminal full
# stop - every string that gets interpolated into the end of another one
# punctuates nothing - so the line supplies its own.
QUEST_LINE = "**{name}** - {prompt}"


# --------------------------------------------------------------------------
# QA
#
# Registered only in the two test servers, gated to the QA role on top of
# that, every call ephemeral and logged. See `qa.py` for why all three.
# --------------------------------------------------------------------------


@bot.tree.command(name="qa-drop", description="(QA) Jump this server to any drop.")
@app_commands.guild_only()
@app_commands.describe(drop="Which drop to sit on. Forwards or back.")
async def qa_drop(interaction: discord.Interaction, drop: int) -> None:
    """Anywhere, in either direction - the one way back on a test server.

    `/advance-game` goes one forward and confirms; this is what the
    rules are relaxed for, and the relaxation is why a forced drop is
    recorded and flagged in `/qa-inspect`.
    """
    if await qa.refuse(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    was = await resolve.current_drop(interaction.guild_id)
    try:
        await resolve.set_current_drop(interaction.guild_id, drop)
    except resolve.UnknownDrop as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return

    await qa.mark_forced(interaction.guild_id, drop)
    await content_loader.place_arrived(interaction.guild_id)
    await _reregister(interaction, interaction.guild, drop)
    await qa.record(interaction, f"drop {was} -> {drop}")
    await interaction.followup.send(
        f"Drop {was} -> **{drop}**, and the command set with it. "
        f"`/qa-inspect` will say this server was forced.",
        ephemeral=True,
    )


@bot.tree.command(
    name="qa-reset-server",
    description="(QA) Un-start this server, back to before /start-game.",
)
@app_commands.guild_only()
@app_commands.describe(
    confirm="Type this server's name exactly. It wipes everything.",
)
async def qa_reset_server(interaction: discord.Interaction, confirm: str) -> None:
    """Back to the state a server is in before anybody runs `/start-game`.

    **No admin command can reach this.** `/reset-haunted-house` writes
    the drop and the channel straight back, deliberately - wiping
    everyone's progress is not the same as the house never having
    opened - and its `back_to_drop` floors at drop 0, because no drop
    number means "not started". So the first five minutes of a server's
    life could be tested exactly once.

    **It also drops the art**, which is the difference that matters for
    testing the upload: `upload_art` skips any image the server already
    has, so a reset that kept them would report ten uploads and post
    none.

    The work is `reset_guild(drop=None)`, which already described this
    outcome - "passing None leaves the game unstarted, which is a reset
    nobody has run `/start-game` on yet". Nothing new; a second entry
    point into a path the admin reset deliberately never takes.

    QA-only, like the rest of this set, because a command whose purpose
    is to undo a launch has no business existing in a server that is
    playing.
    """
    if await qa.refuse(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild

    # The same safeguard `/reset-haunted-house` uses, for the same
    # reason: nothing here is recoverable, and this one goes further.
    if confirm.strip() != guild.name:
        await interaction.followup.send(
            "That un-starts this server and wipes everything in it - "
            "progress, achievements, the drop, the channel and the uploaded "
            f"images.\n\nRun it again with `confirm` set to exactly "
            f"**{guild.name}**.",
            ephemeral=True,
        )
        return

    was = await resolve.current_drop(guild.id)
    try:
        # `drop=None` is what un-starts it: the wipe takes the pointer
        # with everything else, and nothing is written back.
        cleared = await content_loader.reset_guild(guild.id, drop=None)
        await qa.clear_forced(guild.id)
    except (content.ContentError, SQLAlchemyError) as exc:
        log.exception("qa-reset-server failed for %s", guild.id)
        await interaction.followup.send(
            f"The reset did not finish: {exc}. It is one transaction, so "
            "nothing partial has been left behind.",
            ephemeral=True,
        )
        return

    await _reregister(interaction, guild, None)
    await qa.record(interaction, f"un-started from drop {was}")
    rows = sum(cleared.values())
    await interaction.followup.send(
        f"This server is un-started. Was on drop {was}; {rows} row(s) gone, "
        "including the drop, the channel and the art.\n"
        "- `/start-game <channel> [art_channel]` is the way back in\n"
        "- the threads are untouched, as with every other reset",
        ephemeral=True,
    )


@bot.tree.command(
    name="qa-reset-player", description="(QA) Wipe one player's state in this server."
)
@app_commands.guild_only()
@app_commands.describe(member="Whose progress to erase.")
async def qa_reset_player(
    interaction: discord.Interaction, member: discord.Member
) -> None:
    """One player, back to never having been here.

    **Including the hint rows.** Without them the hint ladder is
    one-shot per tester per server, and the second run through the
    tutorial is silent - which is exactly the thing a tester is usually
    trying to look at twice.
    """
    if await qa.refuse(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    cleared = await database.forget_player(interaction.guild_id, member.id)
    await qa.record(interaction, f"reset {member.id}: {cleared or 'nothing to clear'}")
    await interaction.followup.send(
        f"**{member.display_name}** has never been here.\n"
        + (
            "\n".join(f"- `{name}` {n}" for name, n in sorted(cleared.items()))
            or "- nothing to clear"
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="qa-relationship", description="(QA) Set a player's relationship score."
)
@app_commands.guild_only()
@app_commands.describe(member="Whose meter to set.", score="The exact value.")
async def qa_relationship(
    interaction: discord.Interaction, member: discord.Member, score: int
) -> None:
    """Fifty and two hundred and fifty are days of honest play away."""
    if await qa.refuse(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    await database.ensure_user_exists(member.id, interaction.guild_id)
    was = await database.get_relationship(member.id, interaction.guild_id)
    await database.set_relationship(interaction.guild_id, member.id, score)
    await qa.record(interaction, f"{member.id} relationship {was} -> {score}")

    # The thresholds listen on the score moving, and a score moved by
    # hand is still moved: setting somebody to 250 should hand them
    # *Favorite Human* rather than wait for their next pet.
    await _fire_relationship(interaction, member.id, interaction.guild_id, score)
    await interaction.followup.send(
        f"**{member.display_name}**: {was} -> **{score}**.", ephemeral=True
    )


@bot.tree.command(name="qa-clock", description="(QA) Shift this server's clock.")
@app_commands.guild_only()
@app_commands.describe(days="Days ahead. 0 puts the server back on the real clock.")
async def qa_clock(interaction: discord.Interaction, days: int) -> None:
    """Move every dated behaviour at once.

    The drift, the bed's cooldown, the ten-minute pet window and the
    date-gated achievements all read one clock, which is what makes a
    single number worth having.
    """
    if await qa.refuse(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    if days:
        await database.set_setting(interaction.guild_id, database.CLOCK_KEY, days)
    else:
        await database.clear_setting(interaction.guild_id, database.CLOCK_KEY)

    today = await database.server_today(interaction.guild_id)
    await qa.record(interaction, f"clock {days:+d} days, today is {today}")
    await interaction.followup.send(
        f"This server now thinks it is **{today}**"
        + ("." if days else ", which is the real date."),
        ephemeral=True,
    )


@bot.tree.command(name="qa-midnight", description="(QA) Run the nightly drift now.")
@app_commands.guild_only()
async def qa_midnight(interaction: discord.Interaction) -> None:
    """Settle every night this server owes, without waiting for one."""
    if await qa.refuse(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    changes = await database.run_pending_decay()
    mine = [c for c in changes if c.guild_id == interaction.guild_id]
    await qa.record(interaction, f"midnight: {len(mine)} player(s) drifted")
    await interaction.followup.send(
        "\n".join(
            [f"Settled {len(mine)} player(s) here."]
            + [f"- `{c.user_id}` {c.before} -> {c.after} on {c.day}" for c in mine[:10]]
        ),
        ephemeral=True,
    )


@bot.tree.command(
    name="qa-cooldown", description="(QA) Clear a player's cooldowns and windows."
)
@app_commands.guild_only()
@app_commands.describe(member="Whose cooldowns to forget.")
async def qa_cooldown(
    interaction: discord.Interaction, member: discord.Member
) -> None:
    """The bed's twenty-four hours and the ten-minute pet window.

    The lifetime pet count is left alone: it is progress rather than a
    cooldown, and clearing a window should not cost a tester their
    march on two hundred.
    """
    if await qa.refuse(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    cleared = await database.clear_cooldowns(interaction.guild_id, member.id)
    # The toy's cooldown and ramp are on the player row rather than in
    # `thing_uses`, so they need clearing by name - and the ramp goes
    # with the cooldown, or the next attempt is at whatever percentage
    # the last run left behind.
    await database.clear_play_state(interaction.guild_id, member.id)
    forget_public_pets()
    await qa.record(interaction, f"cleared {cleared} cooldown row(s) for {member.id}")
    await interaction.followup.send(
        f"**{member.display_name}** is off cooldown: {cleared} row(s) cleared, "
        "the play ramp is back to zero, and the public windows are empty.",
        ephemeral=True,
    )


@bot.tree.command(name="qa-state", description="(QA) Set a player's play ramp.")
@app_commands.guild_only()
@app_commands.describe(
    member="Whose ramp to set.",
    ramp="Refusals since their last success. 4 makes the next attempt certain.",
)
async def qa_state(
    interaction: discord.Interaction, member: discord.Member, ramp: int
) -> None:
    """Put the ramp where you need it, without playing to get there.

    This is the argument for a generic state command rather than a
    fixed list of flags: 4 makes the next attempt a guaranteed success,
    0 replays the guaranteed first refusal, and 4 followed by a failure
    is *Impressively Bad Luck* in one call. The whole mechanic, without
    farming it.
    """
    if await qa.refuse(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    if ramp < 0:
        await interaction.followup.send(
            "The ramp counts refusals, so it does not go below zero.",
            ephemeral=True,
        )
        return

    await database.ensure_user_exists(member.id, interaction.guild_id)
    await database.set_play_ramp(interaction.guild_id, member.id, ramp)
    await qa.record(interaction, f"{member.id} ramp -> {ramp}")
    await interaction.followup.send(
        f"**{member.display_name}**'s ramp is {ramp}: the next attempt lands "
        f"{world.play_chance(ramp)}% of the time.",
        ephemeral=True,
    )


@bot.tree.command(name="qa-spawn", description="(QA) Put a thing in the channel.")
@app_commands.guild_only()
@app_commands.describe(thing="Which thing to place, by id or by name.")
async def qa_spawn(interaction: discord.Interaction, thing: str) -> None:
    """Place something without waiting for a restock window.

    It earns its place this release: the toys arrive on a schedule, and
    a tester who has just taken both would otherwise wait for the next
    occurrence to test anything that needs one on the floor.
    """
    if await qa.refuse(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    wanted = thing.strip().lower()
    rows = content.load().things_by_id
    match = next(
        (
            row
            for row in rows.values()
            if row.thing_id.lower() == wanted or row.name.lower() == wanted
        ),
        None,
    )
    if match is None:
        await interaction.followup.send(
            f"There is no thing called `{thing.strip()}`.", ephemeral=True
        )
        return

    await database.place_in_room(
        interaction.guild_id, content.CHANNEL_ROOM, match.thing_id, 1
    )
    await qa.record(interaction, f"spawned {match.thing_id} in the channel")
    await interaction.followup.send(
        f"One **{match.name}** is in the channel. It is exempt from the "
        f"restock cap, like anything a player puts down.",
        ephemeral=True,
    )


@bot.tree.command(name="qa-inspect", description="(QA) Dump a player's state.")
@app_commands.guild_only()
@app_commands.describe(member="Whose state to read.")
async def qa_inspect(
    interaction: discord.Interaction, member: discord.Member
) -> None:
    """Everything about one player, and whether this server is where it
    looks like it is.

    The forced-drop line is the reason this exists: without it somebody
    spends an afternoon debugging a server that is simply not where
    they think it is.
    """
    if await qa.refuse(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    lines = await qa.describe(interaction.guild_id, member.id)
    await interaction.followup.send(
        f"**{member.display_name}**\n" + "\n".join(lines), ephemeral=True
    )


# --------------------------------------------------------------------------
# The two views, and the buttons between them
# --------------------------------------------------------------------------
#
# **The first components in the game.** Everything until now has been a
# command and a reply, so the rules these follow are worth stating once.
#
# *Persistent.* An ephemeral `/stats` can sit open in somebody's client
# for hours, and a deploy in the middle of that must not turn its
# buttons into dead rectangles. So every view has `timeout=None` and
# every button carries its state in its own `custom_id` - there is no
# per-message state held in the process to lose. `DynamicItem` is what
# rebuilds the handler from the id after a restart, which is why the
# page number is in the string rather than in an attribute.
#
# *Edited in place.* Each click updates the same ephemeral message
# rather than sending another, so going back and forth between the two
# views never stacks replies.
#
# *Answered in one round trip.* Discord drops an interaction left
# unanswered for three seconds. Both queries are a few dozen rows on one
# guild, so `edit_message` answers directly rather than deferring first.
BUTTON_PREFIX = "hij"


class _OpenLeaderboard(
    discord.ui.DynamicItem[discord.ui.Button],
    template=rf"{BUTTON_PREFIX}:lb:(?P<page>\d+)",
):
    """Open the leaderboard at one page. Also the Previous and Next buttons.

    One class for all three because they are one action with different
    labels: go to page N. Previous and Next are absent rather than
    greyed when there is nowhere to go - two dead rectangles under a
    one-page board read as something broken.
    """

    def __init__(self, page: int, label: str = "Leaderboard", **kwargs) -> None:
        self.page = page
        super().__init__(
            discord.ui.Button(
                label=label, custom_id=f"{BUTTON_PREFIX}:lb:{page}", **kwargs
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match["page"]), label=item.label or "Leaderboard")

    async def callback(self, interaction: discord.Interaction) -> None:
        await _show_leaderboard(interaction, self.page)


class _MyStats(
    discord.ui.DynamicItem[discord.ui.Button],
    template=rf"{BUTTON_PREFIX}:me",
):
    """Back to the clicker's own stats - never the player they were looking at.

    `/stats @somebody` carries the same footer, and its leaderboard
    carries this: the way back from a stranger's standing is to your
    own, which is the only one that is yours to return to.
    """

    def __init__(self, label: str = "See my stats") -> None:
        super().__init__(
            discord.ui.Button(label=label, custom_id=f"{BUTTON_PREFIX}:me")
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(label=item.label or "See my stats")

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            embed = await _stats_embed(
                interaction.guild, interaction.user, interaction.user
            )
        except SQLAlchemyError:
            await interaction.response.send_message(DB_ERROR_MESSAGE, ephemeral=True)
            return
        await interaction.response.edit_message(embed=embed, view=StatsView())


class StatsView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(_OpenLeaderboard(0))


class LeaderboardView(discord.ui.View):
    def __init__(self, page: int, pages: int) -> None:
        super().__init__(timeout=None)
        self.add_item(_MyStats())
        if page > 0:
            self.add_item(_OpenLeaderboard(page - 1, label="Previous"))
        if page + 1 < pages:
            self.add_item(_OpenLeaderboard(page + 1, label="Next"))


async def _show_leaderboard(interaction: discord.Interaction, page: int) -> None:
    try:
        pages = await leaderboard.pages(interaction.guild)
        page = max(0, min(page, pages - 1))
        body = await leaderboard.lines(interaction.guild, interaction.user.id, page)
    except SQLAlchemyError:
        await interaction.response.send_message(DB_ERROR_MESSAGE, ephemeral=True)
        return

    embed = discord.Embed(
        title=await phrasing.default_say("leaderboard.title"), description=_fit(body)
    )
    if pages > 1:
        embed.set_footer(
            text=await phrasing.default_say(
                "leaderboard.page", page=page + 1, total=pages
            )
        )
    await interaction.response.edit_message(
        embed=embed, view=LeaderboardView(page, pages)
    )


@bot.tree.command(name="stats", description="See what you've earned, and how the cat feels.")
@app_commands.guild_only()
@app_commands.describe(player="Whose stats to look at. Leave blank for your own.")
async def stats(
    interaction: discord.Interaction, player: discord.Member | None = None
) -> None:
    """Everything this player has, privately. Three parts, in order.

    **Ephemeral, always.** It carries unlock descriptions, which are the
    spoilers the public announcement deliberately withholds - posting
    them in the channel would defeat keeping that announcement to a name.

    **The relationship, as a figure and a sentence.** The number stays
    visible and unrounded, and is labelled: a bare integer at the top
    of an embed does not say what it counts. The nine bands beneath it
    are wide enough that the figure still has work to do - a player can
    sit in one of them for days and only the number shows which way
    they are going.

    **And the pet count, which is here because there is nowhere else.**
    2f took it out of `/pet` on the grounds that two hundred is better
    as a surprise than as a countdown, and moved it here; section 7
    lists three parts and does not mention it, which would have deleted
    it from the game rather than moved it. A player chasing *Making
    Friends* with no way to know where they are is a worse trade than a
    number they can ignore.

    **Open quests, only when there are any.** With three public quests in
    the whole plan a player will spend long stretches with none, and a
    standing "No open quests" reads as broken rather than as waiting. The
    string for that exists and nothing reads it, in case testing
    disagrees.

    **Completed achievements, header always** - including when empty,
    because its empty line is the only instruction anywhere in the game.
    With no `/help` and no welcome text, hiding it would leave a first
    `/stats` showing nothing but a number.

    Opening it also marks every quest currently visible as seen, which is
    what stops the notice telling a player about a quest they have just
    read.
    """
    await interaction.response.defer(ephemeral=True)
    subject = player or interaction.user

    try:
        embed = await _stats_embed(interaction.guild, interaction.user, subject)
    except SQLAlchemyError:
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    await interaction.followup.send(
        embed=embed, view=StatsView(), ephemeral=True
    )


async def _stats_embed(guild, viewer, subject) -> discord.Embed:
    """One player's stats, as the viewer is allowed to see them.

    **Two audiences, one command.** Looking at somebody else is the same
    question asked from outside, so it is the same embed with the parts
    that are nobody else's business left out: the open quests, the
    unlock blurbs that are the spoilers `/stats` exists to keep private,
    and every per-player mechanic - the toy ramp, the cooldowns, the pet
    count. What is left is a score, a sentence, a rank and a list of
    names, all of which the room has already watched happen.

    **Neither view carries a count out of a total.** `_earned_lines`
    has always refused one - a player's own list is what they have
    done, not a checklist of what they have not - and the same holds
    from outside, where "nine of twenty-two" would turn somebody else's
    play into a completion percentage. The list of names is the whole
    disclosure.
    """
    guild_id, mine = guild.id, subject.id == viewer.id
    relationship = await database.get_relationship(subject.id, guild_id)

    body = [
        await phrasing.default_say("stats.relationship", score=relationship),
        await _relationship_band(relationship, None if mine else subject),
    ]

    if mine:
        # Directly under the prose, and never on the public view: it is
        # progress rather than result, and it changes minute to minute.
        status = await _status_line(guild_id, subject.id)
        if status:
            body.append(status)
        body.append(
            await phrasing.default_say(
                "stats.pets", count=await database.get_pet_count(subject.id, guild_id)
            )
        )
    else:
        rank = await leaderboard.rank_of(guild, subject.id)
        if rank:
            body.append(await phrasing.default_say("stats.rank", rank=rank))
    body.append("")

    if mine:
        quests = await resolve.open_quests(guild_id, subject.id)
        if quests:
            body.append(f"**{await phrasing.default_say('stats.header.quests')}**")
            body.extend(
                QUEST_LINE.format(name=row.name, prompt=row.prompt) for row in quests
            )
            body.append("")
        await _mark_quests_seen(guild_id, subject.id, quests)

    header = await phrasing.default_say("stats.header.achievements")
    if mine:
        body.append(f"**{header}**")
        body.extend(
            await _earned_lines(guild_id, subject.id)
            or [await phrasing.default_say("stats.achievements.empty")]
        )
    else:
        names = await _earned_names(guild_id, subject.id)
        body.append(f"**{header}**")
        body.extend(
            names
            or [await phrasing.default_say("stats.achievements.empty.other")]
        )

    return discord.Embed(
        title=f"{subject.display_name}'s stats", description=_fit(body)
    )


async def _earned_names(guild_id: int, user_id: int) -> list[str]:
    """The names alone, newest first - no unlock text.

    The unlock line is the spoiler the public announcement withholds, so
    it is the one part of the list that cannot cross to another player's
    view. The name has already been posted to the channel.
    """
    available = await resolve.achievements(guild_id)
    when = {
        **await database.server_achievements_of(guild_id),
        **await database.player_achievements_of(guild_id, user_id),
    }
    rows = [(when[key], key, row) for key, row in available.items() if key in when]
    rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [f"**{row.name}**" for _, _, row in rows]


# What the cat thinks of you, by score. Nine bands, each given as the
# lowest score that reaches it, in descending order so the first match
# wins.
#
# They are contiguous and they cover the whole meter: the bottom band
# runs to the floor at -100, and the top one has no ceiling because the
# meter has none either. The three around zero are narrow because that
# is where a new player spends their first week and where one pet is
# meant to feel like something; the upper ones widen because by then a
# player is measuring in days rather than pets.
RELATIONSHIP_BANDS: tuple[tuple[int, str], ...] = (
    (301, "stats.rel.anywhere"),
    (201, "stats.rel.adores"),
    (151, "stats.rel.claimed"),
    (101, "stats.rel.likes"),
    (51, "stats.rel.may_stay"),
    (6, "stats.rel.warming"),
    (-5, "stats.rel.undecided"),
    (-30, "stats.rel.irritated"),
    (database.RELATIONSHIP_MIN, "stats.rel.unimpressed"),
)


async def _status_line(guild_id: int, user_id: int) -> str | None:
    """What the cat wants from this player right now, in one sentence.

    **Private only.** It is progress rather than result - a standing
    condition that changes minute to minute - and looking at somebody
    else's stats reports what they have done, not what the cat happens
    to think of them this moment.

    Three conditions and six outcomes, from the spec's table. Hungry
    and crowded compose, because they are two separate facts and read
    as two sentences. Expectant and hungry do not: *expectantly with
    hunger in her eyes* is one sentence a writer wrote, and composing
    those two would give *looks at you expectantly. The cat looks at
    you with hunger in her eyes.*

    Expectant and crowded can never coincide, so the table's dash in
    those rows is a fact rather than a convention.

    **The hunger half doubles as the tutorial reminder.** From drop 3
    an un-graduated player opening `/stats` is told the cat is hungry
    right beside the open quest, which is the job the follow-the-player
    nudge would have done before the cat started following everybody.
    """
    recent = await database.recent_pets(user_id, guild_id)
    crowded, expectant = _is_crowded(recent), _is_expectant(recent)
    hungry = await _is_hungry(guild_id, user_id)

    if crowded:
        keys = ["stats.status.hungry"] if hungry else []
        keys.append("stats.status.crowded")
    elif expectant and hungry:
        keys = ["stats.status.expectant_hungry"]
    elif expectant:
        keys = ["stats.status.expectant"]
    elif hungry:
        keys = ["stats.status.hungry"]
    else:
        return None

    said = [await phrasing.default_say(key) for key in keys]
    return " ".join(part for part in said if part) or None


async def _is_hungry(guild_id: int, user_id: int) -> bool:
    """Whether this player could feed the cat right now.

    Eight hours since their last successful feed, or never fed - and
    only from the drop that puts food in the game. Without that gate
    every player at drops 0 to 2 has never fed her, and `/stats` would
    tell all of them she is hungry in a game with nothing to feed her
    with.

    Read off `thing_uses`, which `/use` already writes on a successful
    feed and only on a successful one: a refused use returns before the
    row is touched. Whoever builds feeding owns this function, and the
    id set it reads is the part most likely to be replaced.
    """
    drop = await resolve.current_drop(guild_id)
    if drop is resolve.NO_GAME or drop < world.FEEDING_FROM_DROP:
        return False
    fed = await database.last_used_any(user_id, guild_id, world.CAT_FOOD)
    if fed is None:
        return True
    return await database.server_now(guild_id) - fed >= world.HUNGER_WINDOW


async def _relationship_band(score: int, about=None) -> str:
    """The sentence under the figure.

    Zero has no band of its own any more: it sits inside *still trying
    to decide how she feels about you*, which is a better reading of
    where every player starts and where the drift returns them than a
    sentence about not caring.

    **Nine of these address the player, and `/stats @somebody` does
    not.** Every band was written for the one person reading it, so
    showing Max's to Alice printed *the cat adores you* about somebody
    else - the same mistake the take and drop lines made when they went
    public, found the same way, by reading the output. `about` is the
    player being looked at, and it selects a parallel set that names
    them instead.
    """
    key = next(
        (key for floor, key in RELATIONSHIP_BANDS if score >= floor),
        RELATIONSHIP_BANDS[-1][1],
    )
    if about is None:
        return await phrasing.default_say(key) or ""
    return await phrasing.default_say(
        f"{key}.other", player=about.display_name
    ) or ""


async def _mark_quests_seen(guild_id: int, user_id: int, quests) -> None:
    """Reading the list counts as being told about everything in it.

    Both halves matter. The per-quest rows are what stop the notice
    announcing a quest the player is looking at, and they are also the
    order the list is drawn in next time. The `opened_stats` flag is the
    other half of the condition that graduates the notice from "check
    /stats" to naming the quest inline.
    """
    for row in quests:
        await database.notice(guild_id, user_id, row.achievement_id)
    await database.notice(guild_id, user_id, OPENED_STATS)


async def _earned_lines(guild_id: int, user_id: int) -> list[str]:
    """Every achievement this player has, newest first.

    Nothing about achievements **not** yet earned: no count out of
    forty-two, no locked rows, no progress bars. A secret achievement's
    existence is revealed by somebody earning it, not by this command.

    **Newest first, and no longer grouped by kind.** `sort_order` used to
    drive this and does not any more: a player opens `/stats` because
    something just happened, and the thing that just happened should be
    at the top. *Making First Contact* sits at the bottom forever, which
    is right - it is the oldest thing they did.

    A group achievement appears for every current member with nobody
    named as the earner, because there is no earner. It is dated by when
    the server earned it, so it sorts among a player's own.

    Ties are broken on the id. Two achievements can land from one action
    - carving a pumpkin on 15 October earns two - and in Postgres they
    share a transaction timestamp, so without a tiebreak the same list
    could render in two orders.
    """
    available = await resolve.achievements(guild_id)
    mine = await database.player_achievements_of(guild_id, user_id)
    ours = await database.server_achievements_of(guild_id)
    when = {**ours, **mine}

    rows = [(when[key], key, row) for key, row in available.items() if key in when]
    rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [f"**{row.name}** - {row.unlock}" for _, _, row in rows]


def _fit(lines: list[str]) -> str:
    """Join what fits, and say how much did not.

    Same shape `Also here:` already uses, for the same reason: a player who
    has earned enough to overflow should be told, not silently shown less.
    """
    kept: list[str] = []
    used = 0
    for index, line in enumerate(lines):
        # +1 for the newline that joins it to what came before.
        cost = len(line) + (1 if kept else 0)
        remaining = len(lines) - index
        tail = f"\n…and {remaining} more." if remaining else ""
        if used + cost + len(tail) > EMBED_LIMIT:
            return "\n".join(kept) + f"\n…and {remaining} more."
        kept.append(line)
        used += cost
    return "\n".join(kept)


@bot.event
async def on_app_command_completion(
    interaction: discord.Interaction, command
) -> None:
    """Every finished slash command, for the one achievement that wants them all.

    **The widest hook in the game, and it earns its width.** *Familiar*
    asks whether somebody was in the house on Halloween, and the
    honest answer is any command at all - a player who opened `/stats`
    on the thirty-first was there. Narrowing it to petting would be a
    worse version of the same joke.

    Fired on completion rather than on dispatch, which is the one place
    this differs from the file's note. Two reasons: a command that
    raised did not happen, and announcing an award out of a hook that
    runs *before* the command would put the award above the reply that
    prompted it.

    It swallows everything. This runs after the player already got
    their answer, so a failure here must not turn a command that
    worked into a command that errored - and `_fire` already logs.
    """
    if interaction.guild_id is None:
        return
    try:
        await _fire(
            achievements.Context(
                guild_id=interaction.guild_id,
                hook="on_command",
                user_id=interaction.user.id,
            ),
            interaction=interaction,
        )
    except Exception:
        log.exception("on_command hook failed after %s", getattr(command, "name", "?"))


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
