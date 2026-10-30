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
import time
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
import telemetry
import triggers

import world

load_dotenv()

# **A single log record cannot be longer than this.**
#
# Written after a night when the bot went silent on every server and the
# logs could not say why. Discord sat behind a Cloudflare block (error
# 1015, an IP-level ban), and Cloudflare answers a blocked request with
# an HTML page rather than JSON. `discord.HTTPException` carries the
# response body in its message, our handlers log the exception with its
# traceback, and so every refused command printed the whole page: about
# a hundred and ten lines each.
#
# Three testers retrying a command was enough to pass Railway's ceiling
# of 500 log lines a second, at which point Railway starts dropping
# them - *"Messages dropped: 235"*. The logging was not a side effect of
# the outage; it was actively destroying the evidence of the outage
# while it happened.
#
# Capping the record rather than special-casing Cloudflare: the next
# oversized body will come from somewhere else, and a rule that only
# knows about today's page would not catch it. Head and tail are both
# kept because the useful parts of a traceback are at both ends - the
# exception type at the bottom, our own frames at the top.
LOG_RECORD_LIMIT = 2000
LOG_RECORD_TAIL = 500


class CappedFormatter(logging.Formatter):
    """A formatter that refuses to emit a record longer than the cap."""

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if len(text) <= LOG_RECORD_LIMIT:
            return text
        dropped = len(text) - LOG_RECORD_LIMIT
        head = text[: LOG_RECORD_LIMIT - LOG_RECORD_TAIL]
        return (
            f"{head}\n"
            f"    ... {dropped} characters dropped by the log cap ...\n"
            f"{text[-LOG_RECORD_TAIL:]}"
        )


_log_handler = logging.StreamHandler(sys.stdout)  # Railway captures stdout
_log_handler.setFormatter(
    CappedFormatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
)
logging.basicConfig(level=logging.INFO, handlers=[_log_handler])
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

# What the game does for somebody the field has left behind. The cat
# tires of them more slowly, and the ones furthest back start warmer.
#
# **Both are read off the leaderboard's own standings**, so where a
# player sees themselves and how the game treats them cannot disagree,
# and a player who climbs out loses the help on their next pet rather
# than at some boundary of its own.
SLOW_DECAY_PER_PET = 5
CATCHING_UP_BONUS = 20


class Standing(NamedTuple):
    """How the field is treating this player, as two numbers.

    Passed in rather than looked up inside `friendly_chance`, which is
    pure and is called by four things that must all see the same
    answer - the mood roll, the crowding nudge and the two halves of
    the status line. One of them reading a different chance from the
    others is how `/stats` starts lying about the cat.
    """

    decay_per_pet: int = DECAY_PER_RECENT_PET
    bonus: int = 0


# Everybody who is not behind, which on a level server is everybody.
LEVEL = Standing()


async def standing_of(guild, user_id: int) -> Standing:
    """What this player's place in the field is worth to them."""
    if guild is None:
        return LEVEL
    behind, well_behind = await leaderboard.behind_the_field(guild, user_id)
    return Standing(
        decay_per_pet=SLOW_DECAY_PER_PET if behind else DECAY_PER_RECENT_PET,
        bonus=CATCHING_UP_BONUS if well_behind else 0,
    )

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


def friendly_chance(recent_pets: int, standing: Standing = LEVEL) -> int:
    """Percentage chance of a friendly response, clamped to 0 and 100.

    Eight recent pets takes a level player to zero, and the cat is
    reliably standoffish until the window clears.

    `standing` is what the field is worth: a player in the bottom
    thirty per cent loses half as much per pet, and one in the bottom
    tenth starts twenty points up. Clamped at the top because those
    two together open at a hundred, and a chance above it would make
    the ramp read as longer than it is.
    """
    chance = (
        BASE_FRIENDLY_CHANCE + standing.bonus - standing.decay_per_pet * recent_pets
    )
    return max(0, min(100, chance))


def choose_response(
    recent_pets: int, rng=random, standing: Standing = LEVEL
) -> Reaction:
    """Pick a response, weighted by how much this user has been pestering the cat.

    `rng` is injectable so the weighting can be exercised deterministically.
    """
    chance = friendly_chance(recent_pets, standing)
    if rng.random() * 100 < chance:
        return Reaction(rng.choice(FRIENDLY_RESPONSES), True, chance)
    return Reaction(rng.choice(STANDOFFISH_RESPONSES), False, chance)


def _crowding_begins(recent_pets: int, standing: Standing = LEVEL) -> bool:
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
        friendly_chance(recent_pets, standing)
        < BREAK_EVEN_CHANCE
        <= friendly_chance(recent_pets - 1, standing)
    )


def _is_crowded(recent_pets: int, standing: Standing = LEVEL) -> bool:
    """Whether the cat is *currently* tired of this player.

    **The level, where `_crowding_begins` is the edge.** The nudge
    fires once, on the pet that crosses into losing territory, because
    a line on every pet afterwards is wallpaper. The status line
    answers a different question - somebody opening `/stats` wants to
    know where they stand now, and "you crossed over four pets ago" is
    not an answer. Two predicates on one number, and collapsing them
    into one would break whichever half it was collapsed into.
    """
    return friendly_chance(recent_pets, standing) < BREAK_EVEN_CHANCE


def _is_expectant(recent_pets: int, standing: Standing = LEVEL) -> bool:
    """The other side of the same line: better than even odds.

    Exactly even is neither, which is why this is strict. A player at
    fifty percent is being told nothing useful in either direction, and
    the two can never both be true - they read one number from opposite
    sides.
    """
    return friendly_chance(recent_pets, standing) > BREAK_EVEN_CHANCE


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

    problems = achievements.registration_problems(
        parsed.achievement_ids, parked=content.parked_achievements(parsed)
    )
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
        # Slash commands need no privileged intents, but two other things
        # do, and both are enabled in the developer portal as well as
        # here - the portal is necessary and not sufficient, and asking
        # for one the portal has not granted makes the login itself fail.
        #
        # **message_content**, or every message arrives with an empty
        # body and Alexa never answers anybody.
        #
        # **members**, because the leaderboard asks `guild.get_member`
        # whether each player is still in the server, to leave the ones
        # who have gone off it. Without this intent that cache holds
        # almost nobody, every player reads as departed, and a server
        # with three testers on it reports that too few people have met
        # the cat. It is also what fills in a name on an achievement
        # announced by the midnight job, where there is no interaction
        # to read one from.
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
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

        # Settle any days the bot was down for, before serving commands:
        # a weekend offline must not cost somebody their climb back.
        caught_up = await database.run_pending_recovery()
        await telemetry.recoveries(caught_up)
        if caught_up:
            log.info("Startup settled %d recovering score(s)", len(caught_up))
        nightly_job.start()
        keep_threads_alive.start()
        restock_sweep.start()
        thread_sweep.start()

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

            # **Nobody stands in a room that does not exist.** The
            # channel is a location now, and it is the one that is always
            # there - so a player left in a room this server has not
            # reached comes back out to the road. On every boot rather
            # than once, because the same repair covers a renumbered drop.
            try:
                moved = await _send_everybody_somewhere_real(guild.id)
            except SQLAlchemyError:
                log.exception("Could not check where players stand in %s", guild.id)
            else:
                if moved:
                    log.info(
                        "Put %d player(s) in %s back out on the road", moved, guild.name
                    )

            # **Once at startup, and before the loop's clock starts.** A
            # build that was down for a weekend comes back to whatever
            # memberships it missed, and nothing else would notice them
            # for an hour.
            try:
                _LAST_SWEPT[guild.id] = time.monotonic()
                stray = await _sweep_threads(guild)
            except discord.HTTPException:
                log.exception("Startup sweep failed in %s", guild.id)
            else:
                if stray:
                    log.info(
                        "Startup sweep took %d player(s) out of threads in %s",
                        stray,
                        guild.name,
                    )

            channel = await _game_channel(guild)
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
        nightly_job.cancel()
        keep_threads_alive.cancel()
        thread_sweep.cancel()
        await database.close_db()
        await super().close()


bot = CatBot()


# discord.py handles the timezone maths, waking the loop at 00:00 Pacific whether
# that is currently PST or PDT.
@tasks.loop(time=dt_time(hour=0, minute=0, tzinfo=database.PACIFIC))
async def nightly_job() -> None:
    """Midnight, Pacific. Softens grudges, then fires `on_midnight`.

    **Only the upward half of the old drift runs here.** Affection no
    longer fades during an absence; a score at or below the recovery
    threshold still climbs back toward neutral, whether or not that
    player turned up. See `database.apply_daily_recovery`.

    Nothing listens on `on_midnight` yet. The hook fires anyway,
    because the bottle scatter and the craving roll are both meant to.
    """
    try:
        settled = await database.run_pending_recovery()
        await telemetry.recoveries(settled)
        for change in settled:
            log.info(
                "Recovery %s: user %s in guild %s: %s -> %s",
                change.day,
                change.user_id,
                change.guild_id,
                change.before,
                change.after,
            )
    except SQLAlchemyError:
        # Already logged with a traceback; swallow so the loop survives
        # to retry tomorrow rather than dying on one bad night.
        log.error("Nightly recovery failed; will retry at the next midnight")

    for guild in bot.guilds:
        # No player and no interaction: whatever listens here is looking at the
        # server rather than at somebody's action.
        await _fire(
            achievements.Context(guild_id=guild.id, hook="on_midnight"),
            guild=guild,
        )


@nightly_job.before_loop
async def _before_nightly_job() -> None:
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
        channel = await _game_channel(guild)
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


# **A tick, not the interval.** `thread_sweep_minutes` is a per-guild
# config value and one loop serves every server, so the loop wakes often
# and each guild is swept on its own clock. A tick that finds nothing due
# is two dictionary lookups and a config read.
SWEEP_TICK_MINUTES = 1
_LAST_SWEPT: dict[int, float] = {}


@tasks.loop(minutes=SWEEP_TICK_MINUTES)
async def thread_sweep() -> None:
    """Every so often, make each room thread hold exactly its own players.

    The backup layer. `on_thread_member_join` is what fixes a stray
    membership the moment it happens; this is for the ones that happened
    while the bot was down, which is the half nobody can be careful about.
    """
    for guild in bot.guilds:
        try:
            minutes = await database.get_setting(guild.id, "thread_sweep_minutes")
        except SQLAlchemyError:
            log.exception("Could not read the sweep interval for %s", guild.id)
            continue

        now = time.monotonic()
        if now < _LAST_SWEPT.get(guild.id, 0.0) + max(int(minutes or 0), 1) * 60:
            continue
        _LAST_SWEPT[guild.id] = now

        removed = await _sweep_threads(guild)
        if removed:
            log.info("Sweep took %d player(s) out of threads in %s", removed, guild.name)


@thread_sweep.before_loop
async def _before_thread_sweep() -> None:
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

    for guild in bot.guilds:
        if any(_slid_into_the_channel(guild.id, row) for row in report.placed):
            await _announce_arrival(guild)

    await _announce_deliveries(report)


async def _announce_deliveries(report) -> None:
    """Tell each room what landed in it, once per delivery.

    **Everybody in the thread hears it, fed or not.** A player who has
    not fed the cat cannot see the shipping box in their room text yet,
    and they are standing in the Entryway thread all the same - so the
    notice is the first they know of it. The line is deliberately vague
    about what arrived, which turns that from a leak into a tease.

    Cosmetic, like every other public line: a delivery that has already
    landed is not undone by failing to mention it.
    """
    for guild_id, room_id, key in report.announce:
        guild = bot.get_guild(guild_id)
        if guild is None:
            continue
        try:
            line = await phrasing.default_say(key)
            if not line:
                continue
            channel = await _game_channel(guild)
            if channel is None:
                continue
            name = await resolve.room_name(room_id)
            thread = await house_utils.get_thread_for_room(channel, name)
            if thread is not None:
                await thread.send(line)
        except (discord.HTTPException, SQLAlchemyError):
            log.warning(
                "Could not announce a delivery in %s of guild %s",
                room_id,
                guild_id,
                exc_info=True,
            )


def _slid_into_the_channel(guild_id: int, placed) -> bool:
    """Whether this placement is a thing now lying on the channel floor.

    Loose in the room, not tucked inside something: a bottle that
    appears in a box in the corner has not slid anywhere, and the line
    this gates claims it has. No shipped schedule does that today -
    this is the sentence staying true if one ever does.
    """
    its_guild, room_id, container_id, _, _ = placed
    return (
        its_guild == guild_id
        and room_id == content.CHANNEL_ROOM
        and not container_id
    )


async def _announce_arrival(guild) -> None:
    """Say in the channel that something new is on the floor.

    **The same words the cat bed arrived with, from a key of its own.**
    `drop.1.announce` is about drop 1 specifically; a writer reaching
    for it should not silently reword every toy arrival for the rest of
    the game, so the text is duplicated on purpose and the two can
    drift apart when a writer wants them to.

    **Once per sweep, however many things arrived.** The line never
    names what came, so it reads the same for one toy or two - whereas
    two identical sentences back to back read as a bug rather than as
    two toys. A bot that was down for a day places everything it owed
    in a single sweep, which is where that really happens.

    **Whatever arrived, not toys only.** Drop 2's channel is filled by
    the toy row, but drop 3 scatters bottles and diapers over every
    room and can land one here. The line does not name what came, so
    it is as true of a bottle as of a toy - and the alternative is a
    thing appearing in front of everyone standing there in silence.

    No hint rides this one. `SOMETHING_NEW` is the hint for a drop
    opening up, and a toy arriving on a Tuesday is not news of that
    kind.
    """
    channel_id = await database.announcement_channel(guild.id)
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        # A server that never finished setup. The thing is placed and
        # waiting either way; only the notice is lost.
        return

    line = await phrasing.default_say("channel.arrival")
    if line:
        await _post_quietly(channel, line)


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


async def _is_game_thread(channel, guild) -> bool:
    """Whether this is one of the house's room threads.

    Scoped deliberately: Alexa answering in every channel of the server would
    make her a nuisance rather than a fixture in the rooms.
    """
    return await _room_of_thread(channel, guild) is not None


async def _hangs_off_the_game_channel(channel, guild) -> bool:
    """Whether this thread is one of the game channel's own.

    **Asked by id, because the channel is not always called #halloween.**
    `_game_channel` learned that once already - the lookup by name found
    nothing on a server that had called its channel anything else - and
    these two checks were left behind still matching on the name. One
    half knowing the channel and the other half not is worse than either
    being wrong alone: the house is found by id, so its threads are
    there and get pointed at, while every verb typed inside one is
    refused as the wrong window. A player standing in the Entryway was
    told their body was in the Entryway.

    The name stays underneath as the floor, for the same reason it is the
    floor in `_game_channel`: a server with nothing recorded has to keep
    working, and #halloween is the only answer there has ever been for
    one of those.
    """
    parent = getattr(channel, "parent", None)
    if parent is None:
        return False
    game = await _game_channel(guild) if guild is not None else None
    if game is not None:
        return getattr(parent, "id", None) == getattr(game, "id", None)
    return getattr(parent, "name", None) == house_utils.HALLOWEEN_CHANNEL_NAME


async def _room_of_thread(channel, guild) -> str | None:
    """Which room this thread *is*, or None if it is not a room thread.

    Duck-typed on `parent` rather than `isinstance(channel, discord.Thread)`:
    a text channel has no parent, so the check is just as tight, and it can be
    exercised without constructing a real Thread.
    """
    name = getattr(channel, "name", None)
    if not await _hangs_off_the_game_channel(channel, guild):
        return None
    try:
        for room_id, room_name in await resolve.all_rooms():
            if room_name == name:
                return room_id
    except SQLAlchemyError:
        log.exception("Could not identify the thread %s", name)
    return None


# **The joins the bot makes itself.** Admitting somebody to a room thread
# is a mention, and Discord answers it with the same join event an admin
# adding them by hand produces - so without this every move would race its
# own arrival line: the event lands, the row still says the room they left,
# and the handler throws them out of the one they just walked into.
#
# A deadline rather than a flag to clear. There is no `finally` that can be
# trusted to run on every path out of a move, and the failure mode of a
# forgotten flag is a thread that is never policed again; the failure mode
# of a stale deadline is half a minute of not policing one thread, after
# which the sweep catches it anyway.
_ADMITTING: dict[tuple[int, int], float] = {}
_ADMITTING_WINDOW = 30.0


def _admitting(thread_id: int, user_id: int) -> bool:
    deadline = _ADMITTING.get((thread_id, user_id))
    return deadline is not None and deadline > time.monotonic()


def _admit(thread_id: int, user_id: int) -> None:
    now = time.monotonic()
    for key, deadline in list(_ADMITTING.items()):
        if deadline <= now:
            del _ADMITTING[key]
    _ADMITTING[(thread_id, user_id)] = now + _ADMITTING_WINDOW


def _me() -> int | None:
    """The bot's own id, or None before the gateway has told it.

    Asked rather than assumed: the sweep runs at startup, and a crash
    there would take the whole boot with it.
    """
    return getattr(bot.user, "id", None)


def _staff(guild, user_id: int) -> bool:
    """Whether this member can see every private thread anyway.

    Removing them would fail, and then fail again on the next sweep, for
    as long as they are an admin.
    """
    member = guild.get_member(user_id)
    if member is None:
        return False
    permissions = getattr(member, "guild_permissions", None)
    return bool(
        getattr(permissions, "manage_threads", False)
        or getattr(permissions, "administrator", False)
    )


async def _evict(guild, thread, room_id: str, user_id: int, why: str) -> bool:
    """Take one player out of one thread, and write down that it happened."""
    try:
        await house_utils.remove_player_from_thread(thread, user_id)
    except discord.HTTPException:
        log.warning("Could not remove %s from %s", user_id, room_id, exc_info=True)
        return False
    await telemetry.system(
        guild.id,
        telemetry.THREAD_REMOVED,
        user_id=user_id,
        outcome=telemetry.SUCCESS,
        detail=f"thread={room_id} why={why}",
    )
    return True


async def _sweep_threads(guild) -> int:
    """Put every room thread's membership back to the players in that room.

    **The second of two layers, and the slower one.** The join handler
    fixes most mistakes the moment they happen; this is the backup for
    whatever the bot missed while it was restarting or rate-limited, which
    is exactly the half that cannot be covered by being careful.

    The Secret Library is swept like every other room - discovery is per
    player, and the thread is what keeps it that way.

    The channel is not here at all. Nobody can be removed from it, and
    nobody needs to be: being able to read it is not a claim about where
    anybody is standing.
    """
    channel = await _game_channel(guild)
    if channel is None:
        return 0

    try:
        rooms = [
            (room_id, name)
            for room_id, name in await resolve.all_rooms()
            if room_id != content.CHANNEL_ROOM
        ]
        standing = await database.locations_in(guild.id)
    except SQLAlchemyError:
        log.exception("Thread sweep could not read where players are")
        return 0

    removed = 0
    for room_id, name in rooms:
        try:
            thread = await house_utils.get_thread_for_room(channel, name)
            if thread is None:
                continue
            here = await house_utils.members_of(thread)
        except discord.HTTPException:
            log.warning("Thread sweep could not read %s", name, exc_info=True)
            continue

        for user_id in here:
            if user_id == _me() or standing.get(user_id) == room_id:
                continue
            if _admitting(thread.id, user_id) or _staff(guild, user_id):
                continue
            removed += await _evict(guild, thread, room_id, user_id, "sweep")
    return removed


async def _put_them_back(guild, location: str, user) -> None:
    """Re-admit a player to their own room's thread if they have left it.

    **A pointer at a thread you are not in opens nothing**, so the refusal
    that sends somebody back to their room is useless at exactly the
    moment it matters most. A bare mention re-admits them silently, which
    is the same mechanism the arrival line uses.

    The sweep deliberately does not do this. An hourly mention in every
    room somebody has walked out of is noise; here it is one line, once,
    on a command they just typed.
    """
    if guild is None or location == content.CHANNEL_ROOM:
        return
    channel = await _game_channel(guild)
    if channel is None:
        return
    try:
        thread = await _place_for(channel, location, await resolve.room_name(location))
        if thread is None or user.id in await house_utils.members_of(thread):
            return
        _admit(thread.id, user.id)
        await thread.send(user.mention)
    except (discord.HTTPException, SQLAlchemyError):
        log.warning("Could not put %s back in %s", user.id, location, exc_info=True)


@bot.event
async def on_thread_member_join(member) -> None:
    """Somebody is in a room thread. Decide whether they should be.

    The fast half of the two layers: a player added by hand, or one who
    reached a thread some other way, is out again before they have read
    anything. The sweep behind it is for what this misses.
    """
    thread = getattr(member, "thread", None)
    guild = getattr(thread, "guild", None)
    if thread is None or guild is None or member.id == _me():
        return
    if _admitting(thread.id, member.id):
        return

    try:
        room_id = await _room_of_thread(thread, guild)
        if room_id is None:
            return
        state = await database.get_game_state(member.id, guild.id)
    except SQLAlchemyError:
        log.exception("Could not check whether %s belongs in %s", member.id, thread.id)
        return

    location = state.current_room if state else content.CHANNEL_ROOM
    if location == room_id or _staff(guild, member.id):
        return
    await _evict(guild, thread, room_id, member.id, "join")


def _where_typed(interaction) -> str:
    """What to write in the log about where a command came from."""
    return getattr(interaction.channel, "name", None) or "elsewhere"


async def _typed_where_they_stand(interaction, location: str) -> bool:
    """Whether this command was typed in the place the player's body is.

    **Asked as "is this their room", not "which room is this".** The two
    differ only for a thread the game does not own, and that is the case
    that matters: anywhere else in the server is nowhere, which is a third
    answer rather than a missing one. A verb typed in #general is as wrong
    as one typed in the Kitchen by somebody standing in the Nursery, and
    gets the same reply.
    """
    if location == content.CHANNEL_ROOM:
        return await _in_the_channel(interaction)
    if await _in_the_channel(interaction):
        return False

    channel = interaction.channel
    if not await _hangs_off_the_game_channel(channel, interaction.guild):
        return False
    return await resolve.room_name(location) == getattr(channel, "name", None)


async def _wrong_place_line(interaction, location: str, key: str) -> str:
    """Where your body actually is, as a link you can click.

    **It points rather than explains.** The rule - one location, and the
    verbs follow it - is not something a player needs taught; what they
    need is the way back to the window they can act in, which is their
    room's thread, or the channel when they are outside.
    """
    # A command with no guild cannot be answered with a link to one. It
    # should not be reachable - every one of these is `guild_only` - but
    # the refusal is the last thing standing between a player and silence.
    channel = (
        await _game_channel(interaction.guild) if interaction.guild is not None else None
    )
    place = None
    if channel is not None:
        try:
            place = await _place_for(
                channel, location, await resolve.room_name(location)
            )
        except (discord.HTTPException, SQLAlchemyError):
            log.warning("Could not find %s to point at", location, exc_info=True)
    # A room whose thread is missing is a server an admin has to repair, and
    # the name still says where they are - better than refusing with nothing.
    where = (
        place.mention
        if place is not None
        else f"**{await resolve.room_name(location) or location}**"
    )
    return await phrasing.default_say(key, thread=where)


async def _place_to_act_in(interaction, verb: str, *, key: str = "wrong_place.default"):
    """(state, refusal). Exactly one is set.

    **One location decides everything.** A player's body is in exactly one
    place - the road, or one room of the house - and the five world verbs
    act on that place. Where the command was typed decides only whether
    they may: a `/look` from the wrong window is the same question asked
    from the wrong room, not a different question with its own answer.

    That is the change drop 10 made. Before it, typing in the channel *was*
    standing in the channel, and the house was the set of threads you had
    been added to; a player in the Kitchen could `/look` in the channel and
    be shown the road. Now the row says where they are and the window has
    to agree with it.

    `state` is the player's own row, or the channel stand-in for somebody
    who has never been inside - so `state.current_room` is always a place,
    and no caller has to spell "no row" as a third case.
    """
    user, guild_id = interaction.user, interaction.guild_id
    state = await database.get_game_state(user.id, guild_id) or _InTheChannel()

    if not await _typed_where_they_stand(interaction, state.current_room):
        # **Logged here rather than by each verb.** It is one row shape
        # across six commands, and the question it answers is about the
        # interface: how often anybody plays from the wrong window, and
        # which verb they were holding when they did.
        await telemetry.refused(
            guild_id,
            user.id,
            telemetry.WRONG_PLACE,
            reason=telemetry.WRONG_ROOM,
            detail=(
                f"command={verb} in={_where_typed(interaction)} "
                f"at={state.current_room}"
            ),
        )
        await _put_them_back(interaction.guild, state.current_room, user)
        return None, await _wrong_place_line(interaction, state.current_room, key)

    # Somebody playing in the channel with no row: `/take` has to have one
    # to write against. Done here rather than in each verb so the five
    # cannot disagree about when a player starts existing.
    if isinstance(state, _InTheChannel):
        await database.ensure_user_exists(user.id, guild_id)
    return state, None


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
    if not await _is_game_thread(message.channel, message.guild):
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

    # Every bot, not only this one. A webhook or another app reacting is
    # not a player, and judging it would put the cat's answer on a message
    # nobody guessed at.
    if payload.member is not None and payload.member.bot:
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
        day = await database.server_today(payload.guild_id)
        guess = await craving.judge(
            payload.guild_id, payload.user_id, str(payload.emoji), day
        )
    except SQLAlchemyError:
        log.exception("Could not judge a craving guess")
        return

    # None is one of the bot's own faces coming back at it. Not a guess, so
    # no answer and no telemetry row - the player did not play.
    if guess is None:
        return

    await _answer_guess(message, guess, day)
    await _log_guess(payload.guild_id, payload.user_id, payload.emoji, guess)

    # No interaction token here, so there is no private description to send.
    # It is the same reason the craving's own confirmation is a reaction.
    await _fire(
        achievements.Context(
            guild_id=payload.guild_id,
            hook="on_reaction",
            user_id=payload.user_id,
            extra={"emoji": str(payload.emoji), "guess": guess},
        ),
        guild=getattr(channel, "guild", None),
    )


async def _log_guess(guild_id: int, user_id: int, emoji, guess) -> None:
    """One row per judged guess, win or miss.

    **The ladder rung goes in `detail`, not in `outcome`.** This column is
    two-valued everywhere else in the table and a five-valued one here would
    mean no query could ask "did it work" across actions. So a win is a
    success and everything else is a refusal - which reads oddly for a 👀,
    and is the right shape for the one question the column answers.

    The emoji rides along because the useful report is not how often players
    win. It is what they guess when they are close, which is the only
    evidence of whether the categories read the way the writers meant.
    """
    detail = f"emoji={emoji} outcome={guess.outcome}"
    if guess.won:
        # `points` is 0 on a win the player has already been paid for
        # today, which is the figure the row should carry: they won, and
        # it moved nothing.
        await telemetry.succeeded(
            guild_id,
            user_id,
            telemetry.CRAVING_GUESS,
            reason=guess.outcome,
            relationship_delta=guess.points,
            score_after=guess.score_after,
            detail=detail,
        )
    else:
        await telemetry.refused(
            guild_id,
            user_id,
            telemetry.CRAVING_GUESS,
            reason=guess.outcome,
            detail=detail,
        )


async def _answer_guess(message: discord.Message, guess, day) -> None:
    """Put the cat's answer on the message, and say when it is full.

    **The reactions describe the message, not the guess.** Discord allows the
    bot each emoji only once per message, so it cannot answer every reaction
    individually. The message carries its best answer so far and a guess only
    changes it by beating that rank - a 👀 after a 😻 changes nothing.

    **Nothing here counts slots from memory.** Removing the bot's reaction
    frees a slot only when the bot was the only one who clicked it; if a
    player also did, the emoji stays on the message with their count. So the
    live reaction list is read every time and the bot's own two operations
    are applied to a copy of it, which is the only way the twentieth slot
    can be reasoned about at all.

    **Not queued, and bounded per message rather than lucky.**
    Remove-then-add costs two calls, and both things that spend them are
    capped by something other than the number of guesses: an outcome only
    changes by beating the message's current rank, which can happen five
    times in a day, and the walk below only fires when something has
    landed to the right of the cat's face, which needs one of the
    message's twenty slots. Twenty-five changes a message a day, then,
    however many people react to it.

    **The day's total is not bounded here**, and a cap per message is the
    wrong unit to be reassured by in any case: the game is played on every
    message the bot has ever posted, in every room at once, and the limit
    this would run into is per channel. What keeps it comfortable is the
    arrival rate rather than the cap - guesses come in at human speed, and
    discord.py backs off on a 429 by itself.
    """
    ladder = await craving.reactions()
    guild_id = message.guild.id

    # The order they were first added in, which is the order Discord
    # shows them in and the only reason the walk below is possible.
    order = [str(r.emoji) for r in message.reactions]
    mine = {str(r.emoji) for r in message.reactions if r.me}
    # The ones the bot can actually take back off the message.
    sole = {str(r.emoji) for r in message.reactions if r.me and r.count == 1}
    distinct = {str(r.emoji) for r in message.reactions}

    async def add(emoji: str) -> None:
        if emoji in mine:
            return
        # **Do not ask for what cannot be given.** A twenty-first distinct
        # emoji is refused, and the refusal arrives as an exception that
        # logs like a fault - on every guess to a message that is simply
        # full, which is a warning nobody can act on and everybody learns
        # to skip. Joining a reaction already on the message needs no
        # slot, so that is still worth the call.
        if emoji not in distinct and len(distinct) >= craving.MAX_REACTIONS:
            return
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            log.warning("Could not add %s", emoji, exc_info=True)
            return
        mine.add(emoji)
        distinct.add(emoji)

    async def take_back(emoji: str) -> None:
        if emoji not in mine:
            return
        try:
            await message.remove_reaction(emoji, bot.user)
        except discord.HTTPException:
            log.warning("Could not remove %s", emoji, exc_info=True)
            return
        mine.discard(emoji)
        if emoji in sole:
            distinct.discard(emoji)

    # **Yesterday's answers are lies.** The craving rolls over at midnight
    # and the reactions do not, so a 😻 left on an old message points at the
    # wrong emoji today. The first guess to land on one clears what the bot
    # left there before judging anything.
    if await craving.is_stale(guild_id, message.id, day):
        for row in ladder.values():
            await take_back(row.emoji)

    # **The last slot is the ❌'s, and a win's.** A message with nineteen
    # distinct emoji on it has one left, and the next guess would fill it
    # with the player's own emoji and leave the bot no room to answer - so
    # the bot spends it saying there is no twenty-first, rather than on a
    # 👀 that would be the last thing anybody could ever add. A correct
    # guess is the exception: the cat is a better thing to close on.
    full = len(distinct) >= craving.MAX_REACTIONS - 1

    shown = await craving.message_outcome(guild_id, message.id, day)
    answer = ladder.get(guess.outcome)
    beats = craving.rank_of(guess.outcome, ladder) > craving.rank_of(shown, ladder)
    if answer is not None and beats and (guess.won or not full):
        beaten = ladder.get(shown or "")
        if beaten is not None:
            await take_back(beaten.emoji)
        await add(answer.emoji)
        await craving.set_message_outcome(guild_id, message.id, day, guess.outcome)
    elif answer is not None and guess.outcome == shown and not full:
        # **The answer walks along to sit after the guess that earned it.**
        # Reactions are shown in the order they were first added, so the
        # cat's face stays where the first guess of its rung put it while
        # later guesses land to the right of it - and it reads as a verdict
        # on an emoji three along. Taking it off and putting it back moves
        # it to the end. Playtest feedback.
        #
        # **Only for a guess that earned the face already up.** A worse
        # guess must not drag it along: a 👀 that followed a thumbs-up
        # would say the thumbs-up was the closest anybody has come.
        #
        # Only when the bot is alone on the face, because otherwise the
        # removal leaves the player's reaction standing and the position
        # does not move - and only when the face is not already last, which
        # is what makes this cost nothing on the common re-guess.
        if answer.emoji in sole and order and order[-1] != answer.emoji:
            await take_back(answer.emoji)
        # Unconditional, and a no-op while the face is still up: it is also
        # what puts the face back if a previous walk lost the remove-add
        # race and left the message with no answer on it at all.
        await add(answer.emoji)

    if guess.won:
        return
    # Read again: the answer above may have taken the nineteenth slot
    # itself, and whether its swap freed one depends on whether a player
    # was also on the emoji it replaced.
    end = ladder.get(craving.OUT_OF_GUESSES)
    if end is None or len(distinct) < craving.MAX_REACTIONS - 1:
        return
    await add(end.emoji)

    # **The ❌ does not always take a slot.** A player can react with it
    # themselves, and then the bot's own add just joins their reaction and
    # the count does not move - leaving a message that says "no more
    # guesses" with one slot still open, and the guess that fills it is
    # the one the bot has no room left to answer.
    #
    # So: if the ❌ is up and the message is not full, pad it. One is
    # enough. A player who has pre-empted both of the bot's closing emoji
    # has spent two of the twenty slots to buy themselves one unanswered
    # reaction, and defending against that costs more than it saves.
    padding = ladder.get(craving.MESSAGE_FULL)
    if padding is not None and len(distinct) < craving.MAX_REACTIONS:
        await add(padding.emoji)


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
    one, before anybody has gone into the house, and everyone watching
    learns the command exists.

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
    hold a relationship score having never been in a room, which the way
    into the house then has to handle.
    """
    # Ephemeral now: the blurb is the private half of the pair. Defer first,
    # because the DB round trip can exceed Discord's 3s deadline.
    await interaction.response.defer(ephemeral=True)
    user, guild_id = interaction.user, interaction.guild_id

    try:
        # **The cat is wherever the player is, but the hand is not.** She
        # follows everybody, so no check asks where she is - and the hand
        # doing the petting is attached to a body that is in one room. Its
        # own line says so, rather than reading as a bug.
        _, refusal = await _place_to_act_in(interaction, "pet", key="wrong_place.pet")
        if refusal:
            await interaction.followup.send(refusal, ephemeral=True)
            return

        drop = await telemetry.drop_of(guild_id)
        result = await database.increment_pet_count(user.id, guild_id, drop=drop)
        # Read before the meter moves, so it is this player's place
        # coming into the pet rather than the one it leaves them in.
        standing = await standing_of(interaction.guild, user.id)
        reaction = choose_response(result.recent, standing=standing)
        delta = RELATIONSHIP_STEP if reaction.friendly else -RELATIONSHIP_STEP
        relationship = await _move_the_meter(user.id, guild_id, delta)
        # The row was opened inside the pet's own transaction, before
        # the roll that decides what the pet was worth. This is the
        # other half of it. A standoffish pet is not a refusal - the
        # command did what it does - so the sign of the delta is what
        # separates the two moods, and nothing else needs to.
        await database.close_interaction(
            result.log_id, relationship_delta=delta, score_after=relationship
        )
    except SQLAlchemyError:
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    message = reaction.text
    crowding_begins = _crowding_begins(result.recent, standing)
    if crowding_begins:
        # **The crossing speaks for itself, so it replaces the response on
        # either roll.** Each line reports the pet and the warning in one
        # breath - one has her flattening her ears and pulling away, the
        # other has her enjoying it despite the risk - so neither needs the
        # response above it, and printing both narrated one moment twice.
        #
        # It was a single line for both moods, appended, and a player asked
        # why one pet had answered them twice. They had rolled friendly on
        # the fifth: she rubbed against their leg, and the paragraph under it
        # said she had flattened her ears and left.
        nudge = await phrasing.default_say(
            "pet.crowding.friendly"
            if reaction.friendly
            else "pet.crowding.standoffish"
        )
        if nudge:
            message = nudge
    if SHOW_DEBUG_INFO:
        message += _debug_lines(reaction, result.recent, relationship)

    # The over-the-shoulder look is exactly what the *standoffish* nudge
    # says in words, and it is the one image tied to something other than
    # an achievement. It rides the private reply, never the public line,
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

    # **The image goes with the standoffish crossing only.** It is a picture
    # of her pulling away, which is what that line says in words. On a
    # friendly crossing she did not pull away: the pet landed and the score
    # went up, so the picture would contradict it the same way the shared
    # line did. That crossing carries its warning in words alone.
    art = (
        ART_CROWDING
        if crowding_begins and not reaction.friendly
        else (ART_FIRST_PET if result.total == 1 else None)
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

    # **The next drop the files define, not one more.** The drops are
    # numbered in tens above 3, so adding one lands between them and an
    # admin on drop 3 could never reach drop 10.
    try:
        target = await resolve.next_drop_after(current)
    except SQLAlchemyError:
        log.exception("Could not read the drop calendar in %s", guild.id)
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    if target is None or target > resolve.LAST_PLAYABLE_DROP:
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
    and goes with the rest, so the next walk in through the front door is
    day one again - which is what makes this useful for testing the drop
    schedule.

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
        "- day one starts again the next time somebody goes into the house, "
        "and everybody is back out on the road"
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

    channel = await _game_channel(interaction.guild)
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


async def _post_quietly(
    channel, text: str, art_id: str | None = None, *, ping: int | None = None
) -> None:
    """Post without pinging anybody, bar one player the caller names.

    A display name is printed as plain text, so one containing something
    mention-shaped cannot turn into a ping. Applied on every public line that
    names a player.

    **`ping` is an id rather than a flag**, so the one mention that is
    allowed through is the one the caller built. Everything else in the
    text stays inert - a display name on a line that also carries a real
    mention is no more dangerous than it was before.
    """
    content_, embed = await _with_art(getattr(channel, "guild", None), text, art_id)
    # **Everything off, then the one id back on.** The constructor's own
    # defaults are permissive - everyone and roles both start True - so a
    # mention built the short way would let an achievement name carrying
    # an @everyone through on a line meant to ping one player.
    mentions = (
        discord.AllowedMentions(
            everyone=False, roles=False, replied_user=False,
            users=[discord.Object(id=ping)],
        )
        if ping is not None
        else discord.AllowedMentions.none()
    )
    try:
        await channel.send(content_, embed=embed, allowed_mentions=mentions)
    except discord.HTTPException:
        log.warning("Could not post in %s", getattr(channel, "name", "?"), exc_info=True)


class _InTheChannel:
    """What `/use` needs of a game state, for a player who has no row.

    Nobody standing in the channel is required to have a
    `player_game_state`: before drop 10 the channel is the whole game, and
    a row for somebody who has only petted the cat would be a player
    record for somebody who has not played.

    **`rooms_unlocked` is empty rather than absent**, because the move path
    reads it now. The house exit is in `world.UNGATED_EXITS` for exactly
    this reason - the way in is the exit that enrols people, so an empty
    set is the honest answer and not a refusal.
    """

    current_room = content.CHANNEL_ROOM
    rooms_unlocked = ()


# Things that are the cat, for the purpose of the nightly drift. Using
# any of them counts as having turned up, whether or not it worked. The
# toy and the food join this set when drops 2 and 3 build them.
# Reaching for the cat, for the nightly drift's purposes. The expired
# can is in here along with the four she will eat: the drift asks
# whether somebody turned up, and offering her something is turning up
# however it goes.
CAT_INTERACTIONS = frozenset({world.CAT_BED}) | world.CAT_FOOD


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
        state, refusal = await _place_to_act_in(interaction, "use")
        if refusal:
            await interaction.followup.send(refusal, ephemeral=True)
            return

        found = await reach.find(
            guild_id, user.id, state.current_room, thing, reach.Scope.REACH,
            action=telemetry.USE,
        )

        if isinstance(found, reach.Ambiguous):
            await interaction.followup.send(
                await phrasing.default_say(
                    "ambiguous.match", options=", ".join(found.options)
                ),
                ephemeral=True,
            )
            await _turned_away(
                interaction, telemetry.USE, telemetry.AMBIGUOUS, detail=thing
            )
            return

        if isinstance(found, reach.NotFound):
            key = "use_fail.absent" if found.exists_elsewhere else "use_fail.unknown"
            await interaction.followup.send(
                await phrasing.default_say(key, name=thing.strip()), ephemeral=True
            )
            # The typed word is the point of the row. A thing that is
            # somewhere else is a player who knows the game and is in
            # the wrong room; a word the game has never heard of is a
            # player telling you what they expected to find.
            await _turned_away(
                interaction,
                telemetry.USE,
                telemetry.ABSENT if found.exists_elsewhere else telemetry.UNKNOWN,
                detail=thing.strip(),
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
            await _turned_away(
                interaction, telemetry.USE, telemetry.ABSENT, thing_id=found.thing_id
            )
            return

        if found.thing_id in await _exits_not_earned(guild_id, user.id):
            # Before the requirements gate and before the branch on type,
            # because it is the one refusal that says the thing is not
            # there at all.
            await _no_such_doorway(interaction, found, thing)
            return

        held_now = await states.in_force(guild_id, user.id)
        if world.use_refused_by(found.thing_id, held_now):
            # A use whose effect has already happened. Resolved against
            # the states in full rather than against one of them,
            # because the refusal only exists on the state that caused
            # it - which is the whole of why this gate is in code.
            await interaction.followup.send(
                await phrasing.say(
                    guild_id, found.thing_id, "use_fail",
                    state=sorted(held_now),
                    fallback="use_fail.default", name=found.name,
                ),
                ephemeral=True,
            )
            await _turned_away(
                interaction,
                telemetry.USE,
                telemetry.ALREADY_DONE,
                thing_id=found.thing_id,
            )
            return

        wanted = states.required_things(row.requires)
        missing = await reach.missing_requirements(
            guild_id, user.id, state.current_room, wanted
        )

        # **Feeding asks about the cat before it asks about the kit**,
        # and that order is the only place two gates are visible to a
        # player. A sated cat turning down a can is the mechanic
        # working; a missing bowl is a puzzle. Sending somebody across
        # the house to find a bowl for a cat who would not have eaten
        # anyway is a wasted trip the game chose for them.
        if found.thing_id in world.FEEDS and await _a_feed_refusal(
            interaction, found, missing
        ):
            return

        if missing:
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
            await _turned_away(
                interaction,
                telemetry.USE,
                telemetry.REQUIRES_MISSING,
                thing_id=found.thing_id,
                detail=row.requires,
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
            # **The rung rides the refusal rather than following it as a
            # second ephemeral message.** One command, one answer - two
            # bubbles for one `/use` read as two separate things having
            # happened.
            #
            # And it is told what was refused. `{name}` is otherwise filled
            # from whatever takeable toy is in the channel, so a player
            # turned away from a can of cat food was told to pick up the
            # feather wand.
            await interaction.followup.send(
                hints.beneath(
                    await phrasing.default_say(
                        "use_fail.not_carried", name=found.name
                    ),
                    await hints.after(
                        guild_id,
                        user.id,
                        hints.HOLD_TO_USE,
                        quests=False,
                        name=found.name,
                    ),
                ),
                ephemeral=True,
            )
            await _turned_away(
                interaction,
                telemetry.USE,
                telemetry.NOT_CARRIED,
                thing_id=found.thing_id,
            )
            return

        if row.type == world.TOY:
            await _play_with_toy(interaction, state, found)
            return

        if row.transforms_to:
            await _use_transform(interaction, state, found, row)
            return

        # **"Not at all" is answered before "not again yet".**
        #
        # A refusal written for the state the world is in outranks the
        # cooldown, because they answer different questions and only one
        # of them is about this player. In `stairs_upper` the lumber has
        # a refusal and no success text - the top steps are out of reach
        # from the floor until somebody brings the ladder - so a player
        # who already laid a plank today must be told about the steps,
        # not about their muscles. Reading the clock first told
        # half the server the wrong reason the staircase had stopped.
        #
        # It hands over to `_finish_use` rather than repeating the
        # refusal, which is the one place that knows how a use is turned
        # down, and the condition is deliberately narrow: a written
        # refusal *and* no success beside it. A thing with neither still
        # goes through its cooldown and falls through to `use.default`,
        # which is what every thing without state-specific text does.
        forbidden = await _state_refusal(
            guild_id, user.id, found.thing_id, found.name
        )
        if forbidden:
            await interaction.followup.send(forbidden, ephemeral=True)
            await _turned_away(
                interaction,
                telemetry.USE,
                telemetry.WRONG_STATE,
                thing_id=found.thing_id,
            )
            return

        if row.use_cooldown_daily:
            await _use_once_a_day(interaction, state, found, row)
            return

        if row.use_cooldown_hours:
            await _use_with_cooldown(interaction, state, found, row)
            return

        await _finish_use(interaction, state, found)
    except SQLAlchemyError:
        log.exception("Failed to use %r in guild %s", thing, guild_id)
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)


async def _a_feed_refusal(interaction, found, missing: list[str]) -> bool:
    """Turn a feed down if anything about it is wrong. True if it did.

    Four answers in two pairs, and the pairs are independent questions:
    is she hungry, and is the kit to hand.

    **Hunger is read first.** Not hungry and no bowl in the room is
    `feed.wrong_time_and_place` - the can is wrong twice over, and the
    line says so. Not hungry with the bowl right there is
    `feed.not_hungry`, which is the bed's register: she is fine, come
    back later, nothing is broken.

    **Hungry and short of something** falls to the flavor's own
    `use_fail`, which is the one string a writer has for it, so the
    reason is logged rather than written: the bowl points at the
    Entryway and the opener at the kitchen, and which one players hit
    says which room they are stuck outside of.

    Nothing is consumed and no timer is stamped on any of these paths -
    a refused feed costs the player nothing but the command. The
    `last_cat_interaction_date` stamp is the exception, and it is
    already written further up: offering food to a cat who will not eat
    is still showing up.
    """
    user, guild_id = interaction.user, interaction.guild_id

    if not await _is_hungry(guild_id, user.id):
        no_bowl = world.CAT_BOWL in missing
        line = await phrasing.default_say(
            "feed.wrong_time_and_place" if no_bowl else "feed.not_hungry"
        )
        reason = (
            telemetry.WRONG_TIME_AND_PLACE if no_bowl else telemetry.NOT_HUNGRY
        )
    elif missing:
        line = await phrasing.say(
            guild_id, found.thing_id, "use_fail",
            fallback="use_fail.default", name=found.name,
        )
        reason = (
            telemetry.NO_BOWL
            if missing[0] == world.CAT_BOWL
            else telemetry.NO_OPENER
        )
    else:
        return False

    await interaction.followup.send(line, ephemeral=True)
    await _turned_away(
        interaction, telemetry.FEED, reason, thing_id=found.thing_id
    )
    return True


async def _turned_away(interaction, action: str, reason: str, **fields) -> None:
    """Log a refusal the player has just been told about.

    A wrapper this thin earns its place by how often it is called: every
    gate in `/use`, `/take` and `/drop` ends in a `followup.send` and a
    `return`, and a refusal nobody logged is the one shape of row the
    whole table exists to collect.
    """
    await telemetry.refused(
        interaction.guild_id, interaction.user.id, action, reason=reason, **fields
    )


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
    current = states.in_priority_order(held) if held else resolve.DEFAULT_STATE
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
            await _turned_away(
                interaction,
                telemetry.USE,
                telemetry.NOT_CARRIED,
                thing_id=found.thing_id,
            )
            return

    await database.record_use(user.id, guild_id, found.thing_id)

    effect = await world.after_use(guild_id, user.id, found.thing_id, state.current_room)
    # Every use that is not an exit or a toy arrives here, including
    # the three cooldown paths, which is why this is the one place a
    # plain success is logged rather than four.
    #
    # **A can is logged as a feed and not also as a use**, for the
    # reason a move is logged once: two rows for one event is how a
    # count ends up doubled. All five cans, not only the four she eats
    # - the question the action answers is how often anybody offers her
    # anything, and the expired one is an offer.
    await telemetry.succeeded(
        guild_id,
        user.id,
        telemetry.FEED if found.thing_id in world.CAT_FOOD else telemetry.USE,
        thing_id=found.thing_id,
        relationship_delta=effect.delta if effect else None,
        score_after=effect.relationship if effect else None,
    )
    tokens = dict(effect.tokens) if effect else {}

    # The text is resolved *after* the effect, so a use that changes a state
    # can be described by the state it produced rather than the one it left.
    held = await states.in_force(guild_id, user.id)
    current = states.in_priority_order(held) if held else resolve.DEFAULT_STATE

    reply = await phrasing.say(
        guild_id, found.thing_id, "use", state=current,
        fallback="use.default", name=found.name, **tokens,
    )
    # The use path already has the numbers in `tokens`, so it needs the
    # break and not the lookup.
    if "n" in tokens and "total" in tokens:
        reply = _count_on_its_own_line(reply, tokens["n"], tokens["total"])
    # Marked before anything is appended to it. What follows the reply -
    # an achievement, a relationship line, the hint rail - is the game
    # talking about itself rather than about the room, and nothing in it
    # is a noun to type.
    try:
        reply = await reach.mark_nouns(
            guild_id, user.id, state.current_room, reply,
            except_for=found.thing_id,
        )
    except SQLAlchemyError:
        log.exception("Could not mark the nouns in %s's use text", found.thing_id)
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

        # Every successful fluff says so in the room. The yield line
        # below is the exception rather than an addition: it already
        # opens on the fluff - *as {player} fluffs the cat bed,
        # something falls out* - so posting both would narrate the same
        # action twice in consecutive messages.
        if dislodged == world.HOUSE_KEY:
            # **Public and private both, unlike the toy yield**, which
            # suppresses its private half because the two said the same
            # thing. Here the addendum asks for `hint.bed_yield` on the
            # fluff that drops a key, and a hint rides a private
            # message, so there has to be one for it to ride.
            #
            # It is the right call on its own as well. The key is the
            # server's only way into the house, and a line saying one
            # exists is worth saying twice where a thirteenth crinkle
            # ball is not.
            await _announce_bed_yield(interaction, key=True)
            reply = hints.beneath(
                reply, await hints.after(guild_id, user.id, hints.BED_YIELD)
            )
        elif dislodged and await _announce_bed_yield(interaction):
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
            await _announce_bed_fluff(interaction)
            carried = any(a.achievement_id in HINT_FOR_ACHIEVEMENT for a in earned)
            nudge = hints.BED_YIELD if dislodged else hints.TRY_LOOK
            reply = hints.beneath(
                reply,
                None if carried else await hints.after(guild_id, user.id, nudge),
            )
    elif found.thing_id == world.HOUSE_KEY:
        # The road watches somebody unlock the front door, which is the
        # single most consequential thing anybody does at drop 10: every
        # other player's `/go house` starts working because of it.
        await _announce_unlock(interaction)
    elif found.thing_id in world.FEEDS:
        # Public and private both, the bed's arrangement rather than the
        # toy's: the room sees that she was fed, and the person who fed
        # her gets the can's own text, which is about her and not about
        # them.
        await _announce_feed(interaction)
        if effect is not None and effect.first_feed:
            # **The Entryway's `channel.fog_thins`**, and marked the same
            # way: italic, no label, written once and never again. The
            # room has been one sentence until now because the player
            # was watching the cat; she is eating, so they look up.
            #
            # **Unless there is nothing to look up at.** The line
            # describes the foyer opening, and the fragments it opens
            # into are written for drop 20 - so on a drop-10 server it
            # promised a room that would not arrive for a release, and
            # the player's next `/look` showed them the same single
            # sentence they had already read.
            #
            # Asked of the room rather than written as `drop > 10`: the
            # condition is "feeding reveals a sentence here", the
            # content files are what decide when that becomes true, and
            # a number copied into code is a second answer that can go
            # stale. It costs one extra pair of reads on the rarest
            # event a player has - the first feed happens once each.
            opened = await resolve.gate_reveals_more(
                guild_id,
                state.current_room,
                content.FED_THE_CAT,
                await _current_state(guild_id, user.id),
                await _unlocked_for(guild_id, user.id),
            )
            settled = await phrasing.default_say("en_settles") if opened else None
            if settled:
                reply = f"{reply}\n\n*{settled}*"

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

    channel = await _game_channel(guild)
    earner = _earner_of(award, interaction, guild)

    # **The ones with no private half @mention their earner.** An
    # achievement earned through a command answers the player directly, so
    # the public line is for everybody else and a printed name is the
    # right weight. A reaction has no interaction to answer - *Met the
    # Craving* is the one players meet - and there the public line is the
    # whole announcement, which a player not watching the channel will
    # simply miss. Playtest feedback, and the same three cases the no-DM
    # note below is about.
    ping = award.user_id if interaction is None else None

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
        # A mention needs no member cache and has no placeholder: the id
        # is on the award itself, so the line that pings is also the one
        # that can never come out as "Somebody earned".
        line = await phrasing.default_say(
            "achievement.public",
            player=f"<@{ping}>" if ping is not None else (earner or "Somebody"),
            achievement=award.name,
        )

    # The image rides whichever message carries the description, which is the
    # private one for a player and the public one for a group - a group
    # achievement has no earner and so no private message to put either in.
    art = ART_FOR_ACHIEVEMENT.get(award.achievement_id)
    if channel is not None and line:
        # Plain text otherwise: a display name containing something
        # mention-shaped must not turn into one.
        await _post_quietly(
            channel, line, art if award.user_id is None else None, ping=ping
        )

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


async def _send_everybody_somewhere_real(guild_id: int) -> int:
    """Put every player whose room this server has not got back on the road.

    The valid places are the channel and the rooms whose text has arrived.
    The channel is added here rather than asked of `arrived_rooms`, because
    standing on the road is valid from drop 0 - before its own first
    fragment, which arrives with drop 1.
    """
    valid = await resolve.arrived_rooms(guild_id) | {content.CHANNEL_ROOM}
    return await database.send_players_home(guild_id, valid, content.CHANNEL_ROOM)


async def _game_channel(guild):
    """This server's game channel: the house, its threads and its announcements.

    The channel the house was initialized in, by id rather than by name, so a
    rename does not silently stop the game. A server initialized before the id
    was recorded falls back to the name lookup.

    Every caller goes through here rather than matching on the name. Matching
    found nothing on a server whose channel is called anything but #halloween,
    and the failure surfaced as "ask an admin to run
    `/initialize-haunted-house`" - which names the wrong cause and sends the
    admin to a command that cannot help.
    """
    # A database that cannot be read falls through to the name rather than
    # giving up: the name is what every server used before the id existed, so
    # it is the floor rather than a second failure. Giving up here would stop
    # movement on a server that a rename had never touched.
    channel_id = None
    try:
        channel_id = await database.announcement_channel(guild.id)
    except SQLAlchemyError:
        log.exception("Could not read the game channel for %s", guild.id)

    if channel_id is not None:
        channel = guild.get_channel(channel_id)
        if channel is not None:
            return channel
        log.warning("Game channel %s is gone in %s", channel_id, guild.id)
    return house_utils.find_channel(guild)


async def _place_for(channel, room_id: str, room_name: str | None):
    """Where a room's public lines go: its thread, or the channel itself.

    **The channel is a place now.** Every room in the house is a private
    thread, and the road is the channel the game was started in - so a move
    between the two has a thread on one side and a channel on the other,
    and what the move needs of either is only somewhere to post.

    None when the room should have a thread and has not got one, which is
    the caller's cue to send somebody to an admin.
    """
    if room_id == content.CHANNEL_ROOM:
        return channel
    return await house_utils.get_thread_for_room(channel, room_name)


async def _post_in_room(interaction, room_id: str, message: str) -> None:
    """Echo a use into the room thread. Only the staircase does this."""
    if interaction.guild is None:
        return
    channel = await _game_channel(interaction.guild)
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
        await _turned_away(
            interaction, telemetry.USE, telemetry.COOLDOWN, thing_id=found.thing_id
        )
        return

    effect = await world.play_with(guild_id, user.id, now)
    # **Read off the play, not off the score.** Far enough down the
    # day's curve a play pays nothing, and inferring success from the
    # meter moving would turn exactly those plays into refusals: the
    # wrong copy, no public line, and the ramp advancing on a play
    # that landed.
    succeeded = effect.played

    # **Logged as a refusal, though no gate refused it.** The cat
    # declining is the mechanic working rather than a player bouncing
    # off a locked door - but it reads as a refusal to them, and the
    # rung is what makes a run of them interpretable: four in a row at
    # rungs 0 to 3 is the design, four at rung 0 is it broken.
    #
    # `rung_after`, not `rung`, because the ramp has already advanced
    # by the time the effect comes back. The rung this offer was
    # actually rolled at is one less, and naming the column for what it
    # holds is cheaper than an off-by-one nobody notices for a month.
    if succeeded:
        await database.record_use(user.id, guild_id, found.thing_id)
        # **Every play logged with what it actually paid, zeros
        # included.** A play at the tail of the curve is worth zero,
        # and that is known rather than unknown - null is reserved for
        # rows that cannot say, like the ones carried over from
        # `pet_events`. The score has to be read on those, because the
        # meter did not move and the effect has nothing to report.
        #
        # `play=` is which of the day's plays this was, which is the
        # question the curve raises and cannot answer from the delta
        # alone: two players both earning one point are in very
        # different places if one is on their eighth play and the
        # other on their eleventh.
        paid = effect.delta or 0
        standing = effect.relationship
        if standing is None:
            standing = await database.get_relationship(user.id, guild_id)
        await telemetry.succeeded(
            guild_id,
            user.id,
            telemetry.USE,
            thing_id=found.thing_id,
            relationship_delta=paid,
            score_after=standing,
            detail=f"play={effect.tokens.get('play')}",
        )
        reply = await phrasing.say(
            guild_id, found.thing_id, "use",
            fallback="use.default",
            name=found.name,
            player=user.display_name,
        )
    else:
        await telemetry.refused(
            guild_id,
            user.id,
            telemetry.USE,
            reason=telemetry.RAMP,
            thing_id=found.thing_id,
            detail=f"rung_after={effect.tokens.get('ramp')}",
        )
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
    # The score, not the play: a capped play moved nothing, and a hook
    # that watches the meter has nothing to look at.
    if effect.relationship is not None:
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


async def _announce_bed_fluff(interaction) -> None:
    """The room watches somebody fluff the bed.

    **Public and private both**, which is the opposite of the call the
    toy got: a play that posts publicly suppresses its private copy,
    because the two said the same thing. Here they do not. The public
    line reports the event to the room; the private one is the thing's
    own `use` text, which describes the cat climbing in and watching
    the operation, and is written to the person who did it.

    Never raises and never blocks the fluff. The score has already
    moved by the time this runs, and a channel that will not take the
    line must not turn a successful use into a failed command.
    """
    channel = interaction.channel
    if channel is None or not hasattr(channel, "send"):
        return
    line = await phrasing.default_say(
        "bed_fluff.public", player=interaction.user.display_name
    )
    if line:
        await _post_quietly(channel, line)


async def _announce_unlock(interaction) -> None:
    """The road watches the front door come open.

    Posted on every successful `/use` of the key, which is only ever
    the one that opened it: `world.use_refused_by` turns the rest away
    before anything reaches here.
    """
    channel = interaction.channel
    if channel is None or not hasattr(channel, "send"):
        return
    line = await phrasing.default_say(
        "unlock.public", player=interaction.user.display_name
    )
    if line:
        await _post_quietly(channel, line)


async def _announce_feed(interaction) -> None:
    """The room watches somebody feed the cat.

    `_announce_bed_fluff`'s twin down to the shape, and one line in
    `defaults.tsv` rather than one per flavor: the room sees that she
    was fed, not what out of. The flavor is in the private text, which
    is where the player who opened the can is.

    Never raises and never blocks the feed. The score has already moved
    and the can is already gone by the time this runs.
    """
    channel = interaction.channel
    if channel is None or not hasattr(channel, "send"):
        return
    line = await phrasing.default_say(
        "feed.public", player=interaction.user.display_name
    )
    if line:
        await _post_quietly(channel, line)


async def _announce_bed_yield(interaction, key: bool = False) -> bool:
    """The bed's one public line. True if it actually went out.

    `key` picks the other one. A brass key falling out of a cushion is
    a different event from a toy falling out of it - it is heard rather
    than seen, and it is the thing the whole server is waiting on - so
    it gets its own sentence rather than the generic one with a noun
    swapped in.

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
        "bed_yield.key.public" if key else "bed_yield.public",
        player=interaction.user.display_name,
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


async def _state_refusal(
    guild_id: int, user_id: int, thing_id: str, name: str
) -> str | None:
    """The refusal a held state writes for a thing it forbids outright.

    **Read one state at a time, most specific first.** The first state
    that writes anything at all about using this thing decides it: a
    success means allowed, and a refusal with no success means refused.
    A state that is silent is passed over, which is what lets
    `house_unlocked` have nothing to say about lumber.

    `default` is walked last, so a thing whose ordinary row is a refusal
    with no success - the cat, the crumbled staircase - is turned down
    here too. That was already `_finish_use`'s rule; doing it here as
    well is what puts it in front of the cooldown and in front of `/go`.

    Returns the text rather than a flag, because the two callers send it
    themselves: `/use` must not spend a turn on a refused use, and
    `/go` must not move anybody.
    """
    held = await states.in_force(guild_id, user_id)
    for state in (*states.in_priority_order(held), resolve.DEFAULT_STATE):
        if await resolve.thing_text_in_state(guild_id, thing_id, "use", state):
            return None
        refusal = await resolve.thing_text_in_state(
            guild_id, thing_id, "use_fail", state
        )
        if refusal:
            return phrasing.fill(refusal, name=name)
    return None


async def _use_once_a_day(interaction, state, found, row) -> None:
    """A thing that can be used once per Pacific day, not once per N hours.

    **The boundary is the one the midnight job already keeps**, which is
    the whole reason this is a different kind of cooldown rather than a
    length of the other one. A rolling twenty-four hours drifts: fluff
    the bed at nine tonight and the next chance is nine tomorrow, so
    anybody who takes their turn at the first opportunity loses a few
    minutes a day forever, and somebody who fluffs just before midnight
    loses nearly the whole of the next day. A calendar day resets for
    everyone at the same instant.

    Per player, like the hours path: `thing_uses` is keyed on (player,
    thing), so the bed is a shared fixture everybody gets one turn at.

    The refusal still carries {time}, now meaning the time until
    midnight, because the default string asks for it and a player who
    is told "not yet" deserves to know how long.

    **Which refusal, in three steps.** `use_fail_cooldown` first, then
    `use_fail`, then the house default. The middle one is where every
    thing with a cooldown kept its line until drop 20, and still does -
    the cat bed has no `use_fail_cooldown` and reads exactly as it
    always has. The first exists because the staircase's `stairs_upper`
    rows need `use_fail` for something else: it says the top steps are
    out of reach, which is true for the whole server, where this
    sentence is about one player's arms.
    """
    user, guild_id = interaction.user, interaction.guild_id

    previous = await database.last_used(user.id, guild_id, found.thing_id)
    if previous is not None:
        today = await database.server_today(guild_id)
        opened, closes = database.pacific_day_bounds_utc(today)
        if previous >= opened:
            held = await states.in_force(guild_id, user.id)
            current = (
                states.in_priority_order(held) if held else resolve.DEFAULT_STATE
            )
            left = phrasing.approximate_duration(
                closes - await database.server_now(guild_id)
            )
            refusal = await phrasing.say(
                guild_id, found.thing_id, "use_fail_cooldown",
                state=current, name=found.name, time=left,
            )
            if not refusal:
                refusal = await phrasing.say(
                    guild_id, found.thing_id, "use_fail",
                    fallback="use_fail.cooldown",
                    state=current, name=found.name, time=left,
                )
            await interaction.followup.send(refusal, ephemeral=True)
            await _turned_away(
                interaction,
                telemetry.USE,
                telemetry.ONCE_A_DAY,
                thing_id=found.thing_id,
            )
            return

    await _finish_use(interaction, state, found)


async def _use_with_cooldown(interaction, state, found, row) -> None:
    """A thing that cannot be used again for a while.

    Only lumber, at 48 hours - the bed moved to the daily path above. The
    refusal carries {time}, and a refused use is not a use: nothing is
    recorded, so the window does not slide forward every time somebody
    tries.
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
            await _turned_away(
                interaction, telemetry.USE, telemetry.COOLDOWN, thing_id=found.thing_id
            )
            return

    await _finish_use(interaction, state, found)


async def _no_such_doorway(interaction, found, typed: str) -> None:
    """Answer as though the doorway were a word nobody wrote.

    **Not the doorway's own line and not `use_fail.default`.** Either
    would confirm the arch is there and say only that it will not open,
    which is a locked door rather than a room that has not opened yet.

    **The player's own word, not the doorway's name.** `/go dining room`
    resolves to the arch, because the room's name is one of the arch's
    aliases - so a refusal built from the thing it found would answer
    "you don't see an arched doorway here" to somebody who never
    mentioned an arch, and name the doorway in the act of denying it.
    That is why this is called from the verbs and not from `_use_exit`:
    the verbs have the word, and the mover does not.
    """
    await interaction.followup.send(
        await phrasing.default_say("use_fail.absent", name=typed.strip()),
        ephemeral=True,
    )
    await _turned_away(
        interaction, telemetry.MOVE, telemetry.ABSENT, thing_id=found.thing_id
    )


async def _exits_not_earned(guild_id: int, user_id: int) -> frozenset[str]:
    """The Entryway's inner doorways, for a player who has not fed the cat.

    Empty for everybody else, which is every player on a server past
    drop 10's first week and every one of the nine other rooms.

    **The only per-player gate on an exit in the game**, and safe for
    one reason, written out beside the set in `world`: feeding can
    always be completed inside the Entryway, so nobody behind this gate
    is stuck behind it.
    """
    if await database.has_been_told(guild_id, user_id, content.FED_THE_CAT):
        return frozenset()
    return world.FEEDING_GATED_EXITS


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

    # Three exits are exceptions to `rooms_unlocked`, and `UNGATED_EXITS`
    # says why each one is. The oak is the old one: the Secret Library is
    # `open_at_launch = no`, so nobody starts with it unlocked, and climbing
    # the tree is what unlocks the room - so the check cannot come first.
    # The house and the front door are drop 10's, and the reasons differ
    # again; both are written down beside the set.
    unreachable = (
        destination not in state.rooms_unlocked
        and found.thing_id not in world.UNGATED_EXITS
    )
    if unreachable or world.exit_refused_by(found.thing_id, held):
        if found.thing_id == world.HOUSE:
            # **Trying the door is knowing the house is there**, and the
            # most certain of the three ways of knowing: nobody types
            # `/go house` at a road that has never mentioned one by
            # accident. Written on the refusal rather than on the move,
            # because while the door is locked the refusal is all
            # anybody gets - and a player who could not read about the
            # house afterwards would have no way back to it.
            await hints.did(guild_id, user.id, hints.DID_TRY_HOUSE)
        await interaction.followup.send(
            await phrasing.say(
                guild_id, found.thing_id, "use_fail", state=world.exit_state(held),
                fallback="use_fail.default", name=found.name,
            ),
            ephemeral=True,
        )
        return

    # **After the gates above, not before them.** Those two carry their
    # own consequences - the front door's refusal is what teaches a
    # player the house is there - so this only catches an exit they
    # would otherwise have walked through.
    #
    # Drop 20's staircase is the first exit refused by a state rather
    # than by a lock: the Upstairs Hallway is `open_at_launch`, so
    # nothing in `rooms_unlocked` was ever going to stop anybody
    # climbing a staircase with whole steps missing.
    forbidden = await _state_refusal(guild_id, user.id, found.thing_id, found.name)
    if forbidden:
        await interaction.followup.send(forbidden, ephemeral=True)
        await _turned_away(
            interaction,
            telemetry.MOVE,
            telemetry.WRONG_STATE,
            thing_id=found.thing_id,
        )
        return

    channel = await _game_channel(interaction.guild)
    if channel is None:
        await interaction.followup.send(
            f"There's no #{house_utils.HALLOWEEN_CHANNEL_NAME} channel. "
            "Ask an admin to run `/initialize-haunted-house`.",
            ephemeral=True,
        )
        return

    origin = state.current_room
    # **Either end can be the channel**, and exactly one of them can: the
    # road is reachable only from the Entryway and the Entryway only from
    # the road. Everything below is written against places rather than
    # threads for that reason.
    leaving_the_house = destination == content.CHANNEL_ROOM
    coming_inside = origin == content.CHANNEL_ROOM

    try:
        destination_name = await resolve.room_name(destination)
        origin_name = await resolve.room_name(origin)
        destination_place = await _place_for(channel, destination, destination_name)
        origin_place = await _place_for(channel, origin, origin_name)
    except (discord.HTTPException, SQLAlchemyError):
        log.exception("Could not look up where this move happens")
        await interaction.followup.send(MOVE_ERROR_MESSAGE, ephemeral=True)
        return

    if destination_place is None:
        await interaction.followup.send(
            f"I couldn't find the thread for {destination_name or destination}. "
            "Ask an admin to run `/initialize-haunted-house`.",
            ephemeral=True,
        )
        return

    # A secret exit overrides both lines, because the house defaults give it
    # away twice: "exits via the oak tree" teaches the Courtyard that the tree
    # is a way out, and "arrives from the Secret Library" names the secret
    # outright. The overrides say that somebody moved and nothing else.
    #
    # **A mention is a key going in, and a signpost coming out.** Walking
    # into a room, it is what admits the player to the private thread the
    # line is posted in - no mention, no room. Walking out onto the road
    # there is no lock to open, and for a while that was taken to mean no
    # mention was wanted: a public ping for stepping outside read as
    # noise. It is the opposite in practice. The player has just been
    # removed from the thread they were reading and the next thing to
    # happen to them happens in a channel they may not be looking at, so
    # the ping is the only thing pointing at where they now are.
    #
    # The departure line still carries a plain name. It is for the people
    # left behind in the room, and none of them has moved.
    state_now = world.exit_state(held)
    depart = await phrasing.say(
        guild_id, found.thing_id, "move_depart", state=state_now,
        fallback="move.depart",
        player=user.display_name, name=found.name, room=origin_name,
    )
    arrive = await phrasing.say(
        guild_id, found.thing_id, "move_arrive", state=state_now,
        fallback="move.arrive",
        player=user.mention,
        name=found.name, room=origin_name,
    )

    # The arrival line is what admits the player. A mention from a bot holding
    # Manage Threads adds them to a private thread and posts nothing, where
    # `add_user` also posts "<bot> added <player> to the thread" - an
    # out-of-game line that cannot be deleted, on top of the arrival the game
    # has already written. Verified on the test server, 26 October: the
    # mention adds silently, add_user does not.
    #
    # It goes before the write for the same reason the add did: if this fails
    # the player has not been moved or removed from anywhere, so they are
    # where they started and can retry.
    #
    # Sent with the default allowed_mentions deliberately, at both ends.
    # Going in, routing it through `_post_quietly` or suppressing the ping
    # any other way strips the mention that does the admitting and leaves
    # the player outside the room the line says they are in. Coming out,
    # the ping is the whole point: it is what turns the player around to
    # the channel they have just been put back in.
    arrival_message = None
    if not leaving_the_house:
        _admit(destination_place.id, user.id)
    try:
        if leaving_the_house:
            # Nothing to admit anybody to - the ping here is for attention
            # rather than access. It still goes before the write, so a
            # failure leaves the player inside the house rather than in a
            # room with no line saying so.
            arrival_message = await destination_place.send(arrive) if arrive else None
        elif user.mention in arrive:
            arrival_message = await destination_place.send(arrive)
        else:
            # Every `move_arrive` in the content carries `{player}`, and two
            # tests hold that for the overrides and the default. This is the
            # branch for a row that loses it later: the player is let in the
            # old way, with the system line, rather than being stranded
            # outside a room the game thinks they are standing in.
            log.warning(
                "move_arrive for %s carries no player mention; adding %s to %s directly",
                found.thing_id, user.id, destination,
            )
            await house_utils.add_player_to_thread(destination_place, user.id)
            if arrive:
                arrival_message = await destination_place.send(arrive)
    except discord.HTTPException:
        log.exception("Failed to admit %s to %s", user.id, destination)
        await interaction.followup.send(MOVE_ERROR_MESSAGE, ephemeral=True)
        return

    try:
        # **The way in is the enrolment.** This is what `/enter` did before
        # it was retired: create the player's row, and on the first one in a
        # server, pin day one. `start_game` is idempotent and reports whether
        # it was this call that enrolled them, which is also the answer to
        # whether the tutorial is owed and whether day one is now.
        enrolled = coming_inside and await database.start_game(
            user.id, guild_id, destination, await resolve.rooms_open_at_launch()
        )
        if enrolled:
            # Day one is the day somebody first walked in, not the day the
            # house was built - an admin can initialize days early, and the
            # restock calendar should start when there is somebody inside to
            # see it. Idempotent, so the first entry on the server wins.
            opened = await restocking.set_initialized_on(guild_id)
            log.info(
                "Guild %s: day one is %s (first entry by %s)", guild_id, opened, user.id
            )
        else:
            await database.update_current_room(user.id, guild_id, destination)
        await database.record_use(user.id, guild_id, found.thing_id)
        # The rail never recommends what the player has already done, so
        # each of drop 10's two doors retires the hint that points at it. A
        # player who found either on their own is never told about it.
        if found.thing_id == world.HOUSE:
            await hints.did(guild_id, user.id, hints.DID_GO_HOUSE)
        elif found.thing_id == world.FRONT_DOOR:
            await hints.did(guild_id, user.id, hints.DID_GO_ROAD)
        await telemetry.succeeded(
            guild_id,
            user.id,
            telemetry.MOVE,
            thing_id=found.thing_id,
            detail=f"from={origin} to={destination}",
        )
        # The discovery is recorded after the move has committed, so a player
        # who could not be moved is not told they found something.
        await world.after_move(guild_id, user.id, found.thing_id)
        # The channel is nobody's unlocked room. It is where players start,
        # and a row saying somebody has unlocked the road would be a row no
        # question ever asks.
        if not leaving_the_house and destination not in state.rooms_unlocked:
            await database.unlock_room(user.id, guild_id, destination)
        # `held` is deliberately *not* updated with what was just discovered.
        # 2c.5 resolves a use's text after its effect, so the drawer can be
        # described by the state it produced - but a discovery is the opposite
        # case. The long text is the reveal and is written to be read once;
        # the state it sets is what makes every later use read the short one.
    except SQLAlchemyError:
        # The arrival line goes as well as the membership: it announced a move
        # that did not happen, and it is the thing that let them in.
        if arrival_message is not None:
            try:
                await arrival_message.delete()
            except discord.HTTPException:
                log.warning(
                    "Rollback could not delete the arrival line in %s", destination,
                    exc_info=True,
                )
        if not leaving_the_house:
            try:
                await house_utils.remove_player_from_thread(destination_place, user.id)
            except discord.HTTPException:
                log.exception("Rollback failed: %s left in %s", user.id, destination)
        await interaction.followup.send(MOVE_ERROR_MESSAGE, ephemeral=True)
        return

    # The move has happened. What is left is presentational, so a failure is
    # logged rather than surfaced - the player is already through the door.
    # The arrival line is not here: posting it is what let them in, so it was
    # sent before the write.
    if origin_place is not None:
        try:
            await origin_place.send(
                depart, allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException:
            log.warning("Could not post departure in %s", origin_name, exc_info=True)
        # **Nobody is removed from the channel**, and nobody needs to be: it
        # is the one place where being able to read it is not a claim about
        # where you are standing.
        if not coming_inside:
            await _evict(interaction.guild, origin_place, origin, user.id, "move")

    # The exit's own words, which no exit has ever printed: every one of the
    # twenty has a `use` line written and players only ever saw "You head to".
    # It is what carries the discovery when somebody climbs the oak, and the
    # state decides whether they get the long version or the short one.
    walked = await phrasing.say(
        guild_id, found.thing_id, "use", state=state_now, name=found.name
    )
    arriving = f"You head to {destination_place.mention}."
    reply = f"{walked}\n\n{arriving}" if walked else arriving

    # **The way back out, on the message that says they are in.** The
    # retired tutorial's third bullet was this lesson, and the rail could
    # not give it before drop 10 because there was no exit anywhere to
    # teach movement on. `quests=False`: this is one hint riding a move,
    # not the whole rail arriving on movement for the first time.
    if coming_inside:
        reply = hints.beneath(
            reply,
            await hints.after(guild_id, user.id, hints.GO_ROAD, quests=False),
        )

    await interaction.followup.send(reply, ephemeral=True)


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


async def _exit_to_room(guild_id: int, room_id: str, typed: str, hidden=frozenset()):
    """The way out of this room that leads to the room a player named.

    `/go dining room` rather than `/go archway`. A player thinks in rooms,
    and the name of the doorway is something they have to read the prose to
    learn - so the destination's name is a way of asking for the exit.

    Matched on the whole name and on any word of it, which is `_is_this_room`
    looseness and safe for the same reason: it is asked only after nothing in
    the room answered to the word, and the candidates are the two or three
    ways out of one room.

    **The Secret Library is never matched by name**, from either of its two
    doors. `/go secret library` has to fail exactly the way `/go dungeon`
    fails, or the room's name is the thing that gives it away - and the oak
    and the cabinet are still findable by their own.

    `hidden` is the same argument for a different reason: a doorway this
    player has not earned must not be reachable by naming the room
    through it either, or `/go dining room` hands over a room the prose
    has not mentioned to them.
    """
    wanted = reach.normalise(typed)
    if not wanted:
        return None

    for exit_ in await resolve.exits_from(guild_id, room_id):
        if exit_.destination == world.SECRET_LIBRARY or exit_.thing_id in hidden:
            continue
        name = await resolve.room_name(exit_.destination)
        if not name:
            continue
        words = {reach.normalise(word) for word in name.split()}
        if wanted in {reach.normalise(name), reach.normalise(exit_.destination), *words}:
            return exit_
    return None


@bot.tree.command(name="go", description="Go somewhere.")
@app_commands.guild_only()
@app_commands.describe(where="A way out of here, or the room it leads to.")
async def go(interaction: discord.Interaction, where: str) -> None:
    """Movement, named either way: the door, or the room behind it.

    `/use <exit>` moved players before this existed and still does. This is
    the verb they reach for, and it answers the half `/use` answers badly:
    the name of the doorway is something a player has to read the prose to
    learn, while the room it leads to is on the map in their head. `/go
    dining room` asks for the room and lets the archway be an
    implementation detail of the house.

    Three answers, in this order.

    **A way out, by its own name or alias:** take it, through exactly the
    path `/use` takes, gates and lines and all.

    **A thing that is not a way out:** its own refusal. That is what keeps a
    disguised exit disguised - `/go cabinet` reads the cabinet's line
    whether or not there is a passage behind it, so the two cases are
    indistinguishable from outside.

    **A word that is neither:** *you don't see a {name} here*, which is also
    what `/go secret library` says, because the alternative is a refusal
    that admits the room exists.
    """
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command only works inside a server.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    user, guild_id = interaction.user, interaction.guild_id

    try:
        state, refusal = await _place_to_act_in(interaction, "go")
        if refusal:
            await interaction.followup.send(refusal, ephemeral=True)
            return

        hidden = await _exits_not_earned(guild_id, user.id)
        found = await reach.find(
            guild_id, user.id, state.current_room, where, reach.Scope.REACH
        )

        if isinstance(found, reach.Ambiguous):
            await interaction.followup.send(
                await phrasing.default_say(
                    "ambiguous.match", options=", ".join(found.options)
                ),
                ephemeral=True,
            )
            await _turned_away(
                interaction, telemetry.MOVE, telemetry.AMBIGUOUS, detail=where
            )
            return

        if isinstance(found, reach.NotFound):
            # Nothing here answered to the word, so try the rooms the ways
            # out lead to - and then ask for that exit by its own name,
            # rather than building a `Found` by hand that the one real
            # resolver would not have produced.
            exit_ = await _exit_to_room(guild_id, state.current_room, where, hidden)
            if exit_ is not None:
                found = await reach.find(
                    guild_id, user.id, state.current_room, exit_.name, reach.Scope.REACH
                )

        if not isinstance(found, reach.Found):
            await interaction.followup.send(
                await phrasing.default_say("use_fail.absent", name=where.strip()),
                ephemeral=True,
            )
            # Same split the other verbs log: a word the game knows is a
            # player in the wrong room, and a word it has never heard is a
            # player telling you what they expected to find.
            await _turned_away(
                interaction,
                telemetry.MOVE,
                telemetry.ABSENT
                if getattr(found, "exists_elsewhere", False)
                else telemetry.UNKNOWN,
                detail=where.strip(),
            )
            return

        if found.thing_id in hidden:
            await _no_such_doorway(interaction, found, where)
            return

        row = await phrasing.thing_row(found.thing_id)
        if row is None or row.type != "exit":
            # **Its own line first, and `go_fail.default` only behind it.**
            # That order is what keeps a disguised exit disguised: the
            # cabinet answers with the cabinet's words whether or not there
            # is a passage behind it, and so does every fixture that has
            # words of its own. The fallback is for the ones that do not.
            await interaction.followup.send(
                await phrasing.say(
                    guild_id, found.thing_id, "use_fail",
                    state=await _current_state(guild_id, user.id),
                    fallback="go_fail.default", name=found.name,
                ),
                ephemeral=True,
            )
            await _turned_away(
                interaction,
                telemetry.MOVE,
                telemetry.NOT_AN_EXIT,
                thing_id=found.thing_id,
            )
            return

        # The things-to-hand gate, read before anything is worked out, for
        # the reason `/use` reads it there: a refused move is not a move.
        wanted = states.required_things(row.requires)
        if await reach.missing_requirements(
            guild_id, user.id, state.current_room, wanted
        ):
            await interaction.followup.send(
                await phrasing.say(
                    guild_id, found.thing_id, "use_fail",
                    fallback="use_fail.default", name=found.name,
                ),
                ephemeral=True,
            )
            await _turned_away(
                interaction,
                telemetry.MOVE,
                telemetry.REQUIRES_MISSING,
                thing_id=found.thing_id,
                detail=row.requires,
            )
            return

        await _use_exit(interaction, state, found, row)
    except SQLAlchemyError:
        log.exception("Failed to go to %r in guild %s", where, guild_id)
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)


GENERIC_ROOM_DESCRIPTION = "You see a room."
CANT_LOOK_MESSAGE = "You can't look at that."
INVENTORY_ERROR_MESSAGE = "Couldn't retrieve your inventory. Try again."

# Words that mean "the room I am standing in", wherever that is. Players reach
# for these before they reach for the room's own name, and the usual answer in
# a text game is the room description - so they are folded into the
# no-argument shape rather than resolved as nouns. That is what makes
# `/look around` identical to `/look`, down to the hint it carries.
#
# Pre-empting resolution is the opposite of how the room's *name* is handled -
# `_is_this_room` runs only after resolution fails, so a thing sharing a word
# with its room still wins. These three can afford it because nothing in the
# content answers to any of them, and a test holds that.
HERE_WORDS = frozenset({"around", "room", "here"})


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

    if thing is not None and reach.normalise(thing) in HERE_WORDS:
        thing = None

    try:
        state, refusal = await _place_to_act_in(interaction, "look")
        if refusal:
            await interaction.followup.send(refusal, ephemeral=True)
            return
        room_id = state.current_room

        if thing is None or not thing.strip():
            reply = await _look_here(guild_id, user.id, room_id)
            if room_id == content.CHANNEL_ROOM:
                # **The rail rides the channel's look and not a room's.**
                # Every rung of it is about the two things the road has -
                # the bed and the toys - and the house teaches itself.
                #
                # Recorded before the rail is asked, which is what keeps
                # the invariant: by the time anything is chosen, what the
                # player just did is already a reason not to suggest it.
                await hints.did(guild_id, user.id, hints.DID_LOOK)
                reply = hints.beneath(
                    reply,
                    # **The newest drop's hint wins.** A player who never
                    # looked at the bed is eligible for both on their
                    # first `/look`, and only one line goes per message -
                    # so it points at the thing they have not seen. The
                    # bed's is not lost; it fires on their next look if
                    # still unmet.
                    await hints.after(
                        guild_id, user.id, hints.LOOK_TOY, hints.LOOK_SPECIFIC
                    ),
                )
            await interaction.followup.send(reply, ephemeral=True)
            await telemetry.succeeded(guild_id, user.id, telemetry.LOOK, detail=room_id)
            return

        await _look_at_one_thing(interaction, guild_id, user.id, room_id, thing)
    except SQLAlchemyError:
        log.exception("Failed to look at %r in guild %s", thing, guild_id)
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)


# The bed, which is drop 1's achievement and the condition on the hint
# that points at the house. Any successful fluff earns it; a refused one
# does not, which is the distinction the hint wants - a player who has
# been told to come back tomorrow has not had the moment yet.
FLUFFED = "fluffed_to_perfection"


async def _has_fluffed_the_bed(guild_id: int, user_id: int) -> bool:
    return FLUFFED in await database.player_achievements_of(guild_id, user_id)


async def _look_at_one_thing(
    interaction, guild_id: int, user_id: int, room_id: str, thing: str
) -> None:
    """`/look <thing>`, from wherever the player is standing.

    Shared by the nine rooms and the channel. The only thing that differs
    between them is which room is passed in - resolution, the two refusals
    and the art all behave the same, and a second copy of this would be a
    second place for them to drift.
    """
    # Three passes, and the order is the whole of it: an exact word for a
    # thing, then the name of the room, then a typo correction.
    #
    # An exact word outranks the room's name - in the Courtyard `/look kitchen`
    # is the back door, because that is what is in front of you. And the room's
    # name outranks a correction, because `kitchen` typed in the Kitchen is a
    # correct word for the room rather than a near miss for `kitten`, which the
    # cat answers to from two edits away and was quietly winning.
    found = await reach.find(
        guild_id, user_id, room_id, thing, reach.Scope.REACH, fuzzy=False
    )

    if isinstance(found, reach.NotFound):
        # Naming the room you are standing in is the same question as `/look`
        # with no argument, and players ask it that way.
        if await _is_this_room(room_id, thing):
            await interaction.followup.send(
                await _look_here(guild_id, user_id, room_id), ephemeral=True
            )
            await telemetry.succeeded(
                guild_id, user_id, telemetry.LOOK, detail=room_id
            )
            return

        found = await reach.find(
            guild_id, user_id, room_id, thing, reach.Scope.REACH,
            action=telemetry.LOOK,
        )

    if isinstance(found, reach.Ambiguous):
        await interaction.followup.send(
            await phrasing.default_say(
                "ambiguous.match", options=", ".join(found.options)
            ),
            ephemeral=True,
        )
        await telemetry.refused(
            guild_id, user_id, telemetry.LOOK,
            reason=telemetry.AMBIGUOUS, detail=thing.strip(),
        )
        return

    if isinstance(found, reach.NotFound):
        # The room's own name was tried above, between the two passes.
        #
        # One refusal per verb for a word the house does not know:
        # `look_fail.unknown` here, `take_fail.unknown` in /take,
        # `use_fail.unknown` in /use. They used to share one line, which
        # meant any rewrite of it had to read sensibly after all three.
        key = "take_fail.absent" if found.exists_elsewhere else "look_fail.unknown"
        await interaction.followup.send(
            await phrasing.default_say(key, name=thing.strip()), ephemeral=True
        )
        # **The free list of things players expect and the game does
        # not have.** A word typed at a room that has never heard of it
        # is a guess about what should be there, and a week of them
        # says more about the scenery than another playtest would. The
        # word is stored exactly as typed, trimmed and no more: casing
        # and plurals are part of the answer.
        await telemetry.refused(
            guild_id,
            user_id,
            telemetry.UNKNOWN_NOUN,
            reason=telemetry.ABSENT if found.exists_elsewhere else telemetry.UNKNOWN,
            detail=thing.strip(),
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
    elif found.thing_id == world.HOUSE:
        # Recorded whether or not a hint follows it, and the difference
        # matters: this flag is what puts the house into the road's prose
        # from now on, and a player who found it by typing the word has
        # earned that as much as one who was told where to look. The hint
        # below is a separate question with a stricter condition.
        await hints.did(guild_id, user_id, hints.DID_LOOK_HOUSE)
        # **Only for a player who has fluffed the bed**, and the rail is
        # asked only then: a player without it gets no line at all rather
        # than a quest notice standing in for one.
        if await _has_fluffed_the_bed(guild_id, user_id):
            text = hints.beneath(
                text, await hints.after(guild_id, user_id, hints.GO_HOUSE)
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
    await telemetry.succeeded(
        guild_id, user_id, telemetry.LOOK, thing_id=found.thing_id
    )


async def _look_here(guild_id: int, user_id: int, room_id: str) -> str:
    """Looking around, wherever "around" is. The channel is a list; a room
    is its prose and then what is loose in it."""
    if room_id == content.CHANNEL_ROOM:
        return await _look_in_the_channel(guild_id, user_id)
    return await _look_around(guild_id, user_id, room_id)


async def _current_state(guild_id: int, user_id: int) -> tuple[str, ...] | str:
    """Which state's text this player sees.

    Nothing sets a state in 2c, so this is always `default` today - the
    staircase and the drawer are 2c.5. The plumbing is here so that when states
    start being set, the text follows without another pass over /look.

    **Every state held, in priority order, rather than one of them.**
    A player holding two states that both have text for the same entity
    was unspecified in the Functional Spec, and the code took the
    alphabetically first - deterministic, and wrong as soon as it
    mattered. Drop 20 made it matter: a server holding `house_unlocked`
    and `stairs_upper` described the staircase as a ruin, because `h`
    sorts before `s`.

    The resolvers take a sequence and walk it, so handing them the whole
    set costs nothing and means a row written for any held state is
    read. `states.in_priority_order` decides which wins.
    """
    held = await database.states_of(guild_id, user_id)
    return states.in_priority_order(held) if held else resolve.DEFAULT_STATE


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

    # **Marked as a paragraph, before anything else reads the
    # sentences.** A thing named in two fragments is bolded in the first
    # and plain in the second, which only works if the whole run is
    # marked at once - so it happens here rather than as each fragment
    # is printed. A failure costs the bolding and keeps the paragraph,
    # for the same reason the notice lookup below does.
    try:
        marked = await reach.mark_paragraph(
            guild_id, user_id, room_id, [look for _, look in parts]
        )
        parts = [
            (fragment, look) for (fragment, _), look in zip(parts, marked)
        ]
    except SQLAlchemyError:
        log.exception("Could not mark the nouns in %s for %s", room_id, user_id)

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
    """The room's description, then what is lying about in it.

    **The gates are passed in here as well as in the channel**, which
    they were not until drop 10: the fog was the only staged paragraph
    in the game, and it is outdoors. The Entryway is the second, and a
    room that read its fragments without them would show every player
    the whole foyer on their first step inside.
    """
    state = await _current_state(guild_id, user_id)
    description = (
        await _describe_room(
            guild_id,
            user_id,
            room_id,
            state,
            await _unlocked_for(guild_id, user_id),
        )
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
    onboarding corridor. Three gates later it is still one query.

    **`knows_house` is four conditions rather than one**, because
    there are four honest ways to know the house is there and all of
    them should count: most players arrive through *Purrsuasive* and
    the toy, some read the word off the fog and typed it, some have
    tried the front door and found it locked, and anybody who has been
    inside obviously knows. The achievement is asked last because it is
    the only one that costs a second query, and asking it first would
    spend that query on every `/look` in the game.

    The gate names and the notice ids are the same strings, which is
    why `fed_the_cat` needs no translation and `looked_at_bed` does:
    the bed's flag predates the gate and is spelled for the hint
    ladder it was written for.
    """
    held = await database.notices_of(
        guild_id,
        user_id,
        (
            hints.DID_LOOK_BED,
            hints.DID_LOOK_HOUSE,
            hints.DID_TRY_HOUSE,
            hints.DID_GO_HOUSE,
            content.FED_THE_CAT,
        ),
    )
    gates = set()
    if hints.DID_LOOK_BED in held:
        gates.add(content.LOOKED_AT_BED)
    if content.FED_THE_CAT in held:
        gates.add(content.FED_THE_CAT)
    knows = {hints.DID_LOOK_HOUSE, hints.DID_TRY_HOUSE, hints.DID_GO_HOUSE}
    if held & knows or PURRSUASIVE in (
        await database.player_achievements_of(guild_id, user_id)
    ):
        gates.add(content.KNOWS_HOUSE)
    return frozenset(gates)


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


# The one sentence in the game that reports a shared number, written
# once in `defaults`-style prose across four rows: the lumber's look and
# use, and the staircase's look, in two states each.
REPAIR_COUNT = "{n} of {total} repairs done."


def _count_on_its_own_line(text: str, placed: int, required: int) -> str:
    """Move the repair count onto its own line.

    **A line break the writers cannot type.** A TSV cell is one line by
    construction, so the content says "...less like a ruin. 3 of 90
    repairs done." and the break is put in here. It reads as a status
    line under the prose rather than as a clause in it, which is what it
    is: the only number in the game that belongs to the whole server.

    Matched against the rendered sentence rather than guessed at with a
    pattern, so there is nothing to go wrong when a room's prose happens
    to use the word "repairs".
    """
    rendered = REPAIR_COUNT.format(n=placed, total=required)
    return text.replace(" " + rendered, "\n" + rendered)


async def _with_the_repair_count(guild_id: int, text: str) -> str:
    """Fill {n} and {total} from the staircase, if the text asked for them.

    **Asked for, not assumed.** `phrasing.fill` leaves a token it was
    given no value for exactly where it found it, so text that still
    says `{n}` after being filled is text that wants the count - which
    makes this content-driven and free for every other look in the game.
    A room full of scenery costs one substring test; only the lumber and
    the staircase cost the two reads.
    """
    placed, required = await world.planks(guild_id)
    return _count_on_its_own_line(
        phrasing.fill(text, n=placed, total=required), placed, required
    )


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

    # Before the marking, so that the count's own line is in place when
    # the nouns are bolded and nothing gets marked across the break.
    if "{n}" in description or "{total}" in description:
        description = await _with_the_repair_count(guild_id, description)

    # **`looking_at`, which is the thing this paragraph is about.** A
    # source and what it hands out are one candidate to the resolver -
    # the reason `/take candy` does not ask which candy - so the subject
    # is whichever of the two the description came from, and only that
    # half's words are left out. Looking at the pack behind the coat
    # tree still marks the can; looking at the can still marks the pack.
    try:
        description = await reach.mark_nouns(
            guild_id, user_id, room_id, description, except_for=looking_at
        )
    except SQLAlchemyError:
        log.exception("Could not mark the nouns in %s's text", looking_at)

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
        state, refusal = await _place_to_act_in(interaction, "take")
        if refusal:
            await interaction.followup.send(refusal, ephemeral=True)
            return
        room_id = state.current_room

        found = await reach.find(
            guild_id, user.id, room_id, thing, reach.Scope.ROOM, action=telemetry.TAKE
        )

        if isinstance(found, reach.Ambiguous):
            await interaction.followup.send(
                await phrasing.default_say(
                    "ambiguous.match", options=", ".join(found.options)
                ),
                ephemeral=True,
            )
            await _turned_away(
                interaction, telemetry.TAKE, telemetry.AMBIGUOUS, detail=thing
            )
            return

        if isinstance(found, reach.NotFound):
            await interaction.followup.send(
                await _take_refusal(guild_id, found, thing), ephemeral=True
            )
            await _turned_away(
                interaction,
                telemetry.TAKE,
                telemetry.ABSENT if found.exists_elsewhere else telemetry.UNKNOWN,
                detail=thing.strip(),
            )
            return

        row = await phrasing.thing_row(found.thing_id)
        refusal = await _cannot_take(guild_id, user.id, found, row)
        if refusal:
            line, reason = refusal
            await interaction.followup.send(line, ephemeral=True)
            await _turned_away(
                interaction, telemetry.TAKE, reason, thing_id=found.thing_id
            )
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
            await _turned_away(
                interaction, telemetry.TAKE, telemetry.ABSENT, thing_id=found.thing_id
            )
            return

        await telemetry.succeeded(
            guild_id, user.id, telemetry.TAKE, thing_id=taken
        )

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
    """The refusal table, in the spec's order. None means go ahead.

    Returns the line *and* the reason it was refused for, because the
    two audiences are different: the player reads a written sentence
    about this particular object, and the log wants the one word that
    groups it with every other refusal of the same kind.
    """
    if row is None:
        return (
            await phrasing.default_say("take_fail.absent", name=found.name),
            telemetry.ABSENT,
        )

    if row.type == "exit":
        return (
            await phrasing.default_say("take_fail.exit", name=found.name),
            telemetry.NOT_TAKEABLE,
        )

    # A source is never takeable itself; what matters is whether its yield is.
    if not found.is_source and not row.takeable:
        return (
            await phrasing.say(
                guild_id, found.thing_id, "take_fail",
                fallback=_no_carrying(row), name=found.name,
            ),
            telemetry.NOT_TAKEABLE,
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
    return (
        await phrasing.say(
            guild_id, taken, "take_fail",
            fallback=_no_carrying(capped), name=capped.name,
        ),
        telemetry.FULL_HANDS,
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
        state, refusal = await _place_to_act_in(interaction, "drop")
        if refusal:
            await interaction.followup.send(refusal, ephemeral=True)
            return
        room_id = state.current_room

        found = await reach.find(
            guild_id, user.id, room_id, thing, reach.Scope.CARRIED,
            action=telemetry.DROP,
        )

        if isinstance(found, reach.Ambiguous):
            await interaction.followup.send(
                await phrasing.default_say(
                    "ambiguous.match", options=", ".join(found.options)
                ),
                ephemeral=True,
            )
            await _turned_away(
                interaction, telemetry.DROP, telemetry.AMBIGUOUS, detail=thing
            )
            return

        if isinstance(found, reach.NotFound):
            await interaction.followup.send(
                await phrasing.default_say("drop_fail.not_carried", name=thing.strip()),
                ephemeral=True,
            )
            await _turned_away(
                interaction,
                telemetry.DROP,
                telemetry.NOT_HELD,
                detail=thing.strip(),
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
            await _turned_away(
                interaction,
                telemetry.DROP,
                telemetry.NOT_TAKEABLE,
                thing_id=found.thing_id,
            )
            return

        if not await database.drop_into_room(user.id, guild_id, room_id, found.thing_id):
            await interaction.followup.send(
                await phrasing.default_say("drop_fail.not_carried", name=found.name),
                ephemeral=True,
            )
            await _turned_away(
                interaction,
                telemetry.DROP,
                telemetry.NOT_HELD,
                thing_id=found.thing_id,
            )
            return

        await telemetry.succeeded(
            guild_id, user.id, telemetry.DROP, thing_id=found.thing_id
        )

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


@bot.tree.command(name="qa-midnight", description="(QA) Run the nightly job now.")
@app_commands.guild_only()
async def qa_midnight(interaction: discord.Interaction) -> None:
    """Settle every night this server owes, without waiting for one.

    Two things happen at midnight: grudges soften, and `on_midnight`
    fires. Only a negative score moves - affection no longer fades
    during an absence - so a tester who sees nothing settle has
    nobody below the threshold rather than a broken command.
    """
    if await qa.refuse(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    changes = await database.run_pending_recovery()
    await telemetry.recoveries(changes)
    mine = [c for c in changes if c.guild_id == interaction.guild_id]
    await _fire(
        achievements.Context(guild_id=interaction.guild_id, hook="on_midnight"),
        guild=interaction.guild,
        announce=False,
    )
    await qa.record(interaction, f"midnight: {len(mine)} score(s) recovered")
    lines = [f"Settled {len(mine)} recovering score(s) here."]
    lines += [f"- `{c.user_id}` {c.before} -> {c.after} on {c.day}" for c in mine[:10]]
    await interaction.followup.send(chr(10).join(lines), ephemeral=True)


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


@bot.tree.command(name="qa-state", description="(QA) Set a player's toy state.")
@app_commands.guild_only()
@app_commands.describe(
    member="Whose state to set.",
    ramp="Refusals since their last success. 4 makes the next attempt certain.",
    plays="Lifetime successful toy plays. 24 puts the next one on *Tireless*.",
    today="Successful plays so far today. 11 makes the next one pay nothing.",
)
async def qa_state(
    interaction: discord.Interaction,
    member: discord.Member,
    ramp: int | None = None,
    plays: int | None = None,
    today: int | None = None,
) -> None:
    """Put a player's toy state where you need it, without playing to get there.

    Three levers, each answering a question that otherwise costs an
    afternoon:

    `ramp` is the odds. 4 makes the next attempt a guaranteed success,
    0 replays the guaranteed first refusal, and 4 followed by a failure
    is *Impressively Bad Luck* in one call.

    `plays` is the lifetime count *Tireless* reads. Twenty-five
    successful plays is four hours of cooldowns at the very least,
    which made the achievement untestable by hand - so this writes the
    figure rather than earning it.

    `today` is where the player sits on the day's paying curve. Eleven
    puts the next success at nothing, which is the state *Purrsistent*
    is about and which eleven real plays and an hour of waiting would
    otherwise be the only way to reach.

    All three are optional and at least one is required, which is what
    makes this a generic state command rather than a fixed list of
    flags: the next thing worth setting is a fourth argument rather
    than a fourth command.
    """
    if await qa.refuse(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    asked = {"ramp": ramp, "plays": plays, "today": today}
    given = {name: value for name, value in asked.items() if value is not None}
    if not given:
        await interaction.followup.send(
            "Nothing to set. Pass at least one of `ramp`, `plays` or `today`.",
            ephemeral=True,
        )
        return

    negative = sorted(name for name, value in given.items() if value < 0)
    if negative:
        await interaction.followup.send(
            f"{', '.join(f'`{name}`' for name in negative)} counts something, so "
            "it does not go below zero.",
            ephemeral=True,
        )
        return

    await database.ensure_user_exists(member.id, interaction.guild_id)
    lines = []

    if ramp is not None:
        await database.set_play_ramp(interaction.guild_id, member.id, ramp)
        lines.append(
            f"- ramp **{ramp}**: the next attempt lands "
            f"{world.play_chance(ramp)}% of the time."
        )

    if plays is not None:
        toy = await database.set_toy_plays(interaction.guild_id, member.id, plays)
        if toy is None:
            lines.append(
                "- plays **unchanged**: the content has no toys to count against."
            )
        else:
            lines.append(
                f"- lifetime plays **{plays}**, written against `{toy}`."
            )

    if today is not None:
        await database.set_toy_plays_today(interaction.guild_id, member.id, today)
        worth = world.play_value(
            today + 1,
            await world.toy_base_points(interaction.guild_id),
            await world.toy_decay_percent(interaction.guild_id),
        )
        lines.append(
            f"- **{today}** plays today: the next success is worth {worth}."
        )

    await qa.record(
        interaction,
        f"{member.id} state -> "
        + ", ".join(f"{name}={value}" for name, value in sorted(given.items())),
    )
    await interaction.followup.send(
        chr(10).join([f"**{member.display_name}**"] + lines), ephemeral=True
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
        status = await _status_line(guild, subject.id)
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


async def _status_line(guild, user_id: int) -> str | None:
    """What the cat wants from this player right now.

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

    **The craving hint is a line of its own**, not a fourth clause on
    the end. The three conditions are all about where this player
    stands with the cat; the craving is about a game, and run on after
    them the testers read it as one more sentence about the petting.

    **The hunger half doubles as the tutorial reminder.** From drop 10
    an un-graduated player opening `/stats` is told the cat is hungry
    right beside the open quest, which is the job the follow-the-player
    nudge would have done before the cat started following everybody.
    """
    guild_id = guild.id
    recent = await database.recent_pets(user_id, guild_id)
    # The same standing the pet itself would use, or the line would
    # describe a cat the next `/pet` does not match.
    standing = await standing_of(guild, user_id)
    crowded = _is_crowded(recent, standing)
    expectant = _is_expectant(recent, standing)
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
        keys = []

    # Last, and on a line of its own. It is the only place the craving
    # game is ever mentioned, so it has to be able to appear with no
    # other condition to hang off - and it is a different kind of fact
    # from the rest, which is what the testers caught: run on after
    # *watching you expectantly*, it reads as one more sentence about
    # how the petting is going rather than as a game to go and play.
    hint = None
    if await _craving_is_open(guild_id, user_id):
        hint = await phrasing.default_say("stats.status.craving")

    said = [await phrasing.default_say(key) for key in keys]
    # The conditions themselves still compose into one sentence each.
    lines = [" ".join(part for part in said if part), hint]
    return "\n".join(line for line in lines if line) or None


# The achievement that opens the hint. Drop 2's, and the gate is about
# pacing rather than about toys: a player on their first day is already
# being handed a cat, a bed and a quest, and a fourth thing to wonder
# about is the overwhelm the testers reported.
PURRSUASIVE = "persuasive"


async def _craving_is_open(guild_id: int, user_id: int) -> bool:
    """Whether `/stats` should say the cat is craving something.

    Three conditions, and all three are about not pointing at nothing.
    The drop, because before it no craving is drawn. *Purrsuasive*,
    because the line is the game's only announcement and a player who has
    not got that far has enough to read already. And not having found it,
    because once they have, the 😻 and the award have both said so - a
    standing line repeating it would read as a second craving to go and
    find.

    Per player throughout. Somebody else solving it changes nothing here.
    """
    drop = await resolve.current_drop(guild_id)
    if drop is resolve.NO_GAME or drop < world.CRAVING_FROM_DROP:
        return False
    if PURRSUASIVE not in await database.player_achievements_of(guild_id, user_id):
        return False
    return not await craving.found_today(guild_id, user_id)


async def _is_hungry(guild_id: int, user_id: int) -> bool:
    """Whether this player could feed the cat right now.

    Eight hours since their last successful feed, or never fed - and
    only from the drop that puts food in the game. Without that gate
    every player at drops 0 to 2 has never fed her, and `/stats` would
    tell all of them she is hungry in a game with nothing to feed her
    with.

    Read off `thing_uses`, which `/use` already writes on a successful
    feed and only on a successful one: a refused use returns before the
    row is touched.

    **`FEEDS` and not `CAT_FOOD`**, which is the whole of why the two
    sets exist. The expired can is a can of cat food and is not a meal:
    she takes one breath of it and walks away, so a player who opened
    one has not fed her and must not have to wait eight hours before
    she will eat again.
    """
    drop = await resolve.current_drop(guild_id)
    if drop is resolve.NO_GAME or drop < world.FEEDING_FROM_DROP:
        return False
    fed = await database.last_used_any(user_id, guild_id, world.FEEDS)
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
    """Catch-all so an unexpected failure never leaves the user staring at
    'thinking...'.

    **Except when the apology needs the thing that is broken.** If Discord
    itself is refusing us - a Cloudflare block, an outage, a revoked token
    - then the reply below fails exactly the way the command did, and an
    unawaited failure inside an error handler surfaces as asyncio's
    *Task exception was never retrieved*: a second traceback for every
    first one, in the log that is already struggling.

    Nothing here can rescue the player's "thinking..." in that case,
    because there is no channel left to apologise down. What it can do is
    fail quietly and say so in one line.
    """
    log.exception("Unhandled error in command %s", interaction.command, exc_info=error)
    message = "Something went wrong. Please try again."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException as second:
        log.warning(
            "Could not even tell %s that their command failed: %s",
            interaction.user.id,
            second.__class__.__name__,
        )


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
