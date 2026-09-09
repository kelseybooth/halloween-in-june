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

        # Settle any nights the bot was offline for before serving commands.
        caught_up = await database.run_pending_decay()
        if caught_up:
            log.info("Startup decay settled %d relationship(s)", len(caught_up))
        nightly_decay.start()

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
        log.info("Ready - try /pet in your server")

    async def close(self) -> None:
        """Graceful shutdown: stop the scheduler, release the pool, then disconnect."""
        nightly_decay.cancel()
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
                "Decay %s: user %s %s -> %s",
                change.day,
                change.user_id,
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


@bot.tree.command(name="pet", description="Pet the cat.")
async def pet(interaction: discord.Interaction) -> None:
    # Defer first: the DB round trip can exceed Discord's 3s interaction deadline.
    await interaction.response.defer()
    try:
        result = await database.increment_pet_count(interaction.user.id)
        reaction = choose_response(result.recent)
        delta = RELATIONSHIP_STEP if reaction.friendly else -RELATIONSHIP_STEP
        relationship = await database.adjust_relationship(interaction.user.id, delta)
    except SQLAlchemyError:
        await interaction.followup.send(DB_ERROR_MESSAGE, ephemeral=True)
        return

    message = f"{reaction.text}\n\nTotal pets: {result.total}"
    if SHOW_DEBUG_INFO:
        message += _debug_lines(reaction, result.recent, relationship)
    await interaction.followup.send(message)


@bot.tree.command(name="stats", description="See how many times you've petted the cat.")
async def stats(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    try:
        count = await database.get_pet_count(interaction.user.id)
        relationship = await database.get_relationship(interaction.user.id)
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


if __name__ == "__main__":
    main()
