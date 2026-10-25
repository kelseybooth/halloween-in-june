"""Who may run the QA commands, and where they exist at all.

Three gates, and they are not redundant. **Registration** keeps them out
of the live server's slash menu entirely, so nobody there can see that
`/qa-relationship` exists. **The role** stops a curious member of a test
server from setting their own score to 250. **The log line** means that
when a server turns out not to be where somebody thought it was, there
is a record of who moved it.

The two test servers are written down here rather than configured,
because a config row is one `/admin_config` away from pointing at the
live server, and the whole point of the first gate is that it cannot be
turned on by accident.
"""

from __future__ import annotations

import logging

import database
import resolve

log = logging.getLogger(__name__)

# The only servers these commands are registered in.
TEST_GUILDS: frozenset[int] = frozenset({1542854260524453978, 1548007001915658250})

# The role a member must hold on top of that.
QA_ROLE = "qa"

# Where the log lines go, if a channel by this name exists. Falling back
# to the application log rather than refusing: a missing channel should
# cost the audit trail its convenience, not the tester their command.
LOG_CHANNEL = "qa-log"


def is_test_guild(guild_id: int | None) -> bool:
    return guild_id in TEST_GUILDS


def has_qa_role(member) -> bool:
    """Whether this member holds the QA role.

    Administrators are not exempt. The role is cheap to grant and the
    point of it is that moving a server's drop is a deliberate act by
    somebody who is testing, not something an admin can do by reflex.
    """
    roles = getattr(member, "roles", None) or []
    return any(getattr(role, "name", "").lower() == QA_ROLE for role in roles)


async def refuse(interaction) -> bool:
    """Send the refusal if this caller may not be here. True if refused."""
    if not is_test_guild(interaction.guild_id):
        # Should be unreachable: the command is not registered here. If
        # it is being reached, the registration gate has a hole in it
        # and that is worth saying out loud.
        log.error(
            "QA command reached non-test guild %s - check the registration",
            interaction.guild_id,
        )
        await interaction.response.send_message(
            "That command does not exist in this server.", ephemeral=True
        )
        return True
    if not has_qa_role(interaction.user):
        await interaction.response.send_message(
            f"`/{interaction.command.name}` needs the **{QA_ROLE}** role.",
            ephemeral=True,
        )
        return True
    return False


async def record(interaction, what: str) -> None:
    """One line, in the log channel if there is one and the log if not."""
    line = (
        f"`{interaction.user}` ({interaction.user.id}) "
        f"/{interaction.command.name}: {what}"
    )
    log.info("QA %s", line)

    guild = interaction.guild
    channel = next(
        (
            c
            for c in getattr(guild, "text_channels", [])
            if getattr(c, "name", "") == LOG_CHANNEL
        ),
        None,
    )
    if channel is None:
        return
    try:
        await channel.send(line)
    except Exception:
        log.exception("Could not write the QA log line in guild %s", guild.id)


async def forced_drop(guild_id: int) -> int | None:
    """The drop this server was forced to, or None if nobody forced it.

    **A forced drop must be visibly forced.** Without this somebody
    spends an afternoon debugging a server that is simply not where
    they think it is, and the only evidence is a log line from last
    week.
    """
    raw = await database.get_config_raw(guild_id, FORCED_KEY)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


async def mark_forced(guild_id: int, drop: int) -> None:
    await database.set_setting(guild_id, FORCED_KEY, drop)


async def clear_forced(guild_id: int) -> None:
    await database.clear_setting(guild_id, FORCED_KEY)


# Set by `/qa-drop`, cleared by `/advance-game` and `/start-game`, read
# by `/qa-inspect`. A separate row rather than a flag on the pointer so
# that the pointer stays one number that means one thing.
FORCED_KEY = "drop_forced_to"


async def describe(guild_id: int, user_id: int) -> list[str]:
    """Everything `/qa-inspect` reports about one player."""
    drop = await resolve.current_drop(guild_id)
    forced = await forced_drop(guild_id)
    offset = await database.clock_offset(guild_id)

    lines = [
        f"**drop** {drop if drop is not None else 'not started'}"
        + (f"  ⚠ **forced** to {forced}" if forced is not None else ""),
        f"**clock** {'real' if not offset else f'{offset:+d} days'}"
        f" — today is {await database.server_today(guild_id)}",
        f"**relationship** {await database.get_relationship(user_id, guild_id)}",
        f"**pets** {await database.get_pet_count(user_id, guild_id)}",
    ]

    stamped = await database.last_cat_interaction(guild_id, user_id)
    lines.append(f"**last touched the cat** {stamped or 'never'}")

    earned = await database.player_achievements_of(guild_id, user_id)
    lines.append(f"**achievements** {', '.join(sorted(earned)) or 'none'}")

    quests = await resolve.open_quests(guild_id, user_id)
    lines.append(
        f"**open quests** {', '.join(q.achievement_id for q in quests) or 'none'}"
    )

    told = await database.notice_order(guild_id, user_id)
    lines.append(f"**told** {', '.join(sorted(told)) or 'nothing'}")

    # The log, from inside Discord. Five rows rather than the ten the
    # query will give, because this is a confirmation that writing
    # works and not a place to read the data from - that is a database
    # query against the beta server, which no QA command can reach.
    recent = await database.recent_interactions(guild_id, user_id, limit=5)
    lines.append("**last interactions** " + (", ".join(_one_line(r) for r in recent) or "none"))
    return lines


def _one_line(row) -> str:
    """One logged row, short enough that five of them fit in a reply."""
    what = row.action if row.outcome != database.REFUSED else f"{row.action}!{row.reason}"
    about = row.thing_id or row.detail
    return f"{what}({about})" if about else what
