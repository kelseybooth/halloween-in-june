"""A log line has a ceiling, the catch-all survives a silent Discord, and
a command that dies - or is refused - says so in the log.

Both rules here were written the morning after an outage, and both are
about the same failure: **the logging made the problem harder to see
instead of easier.**

Discord sat behind a Cloudflare block - error 1015, an IP-level ban -
and Cloudflare answers a blocked request with an HTML page instead of
JSON. `discord.HTTPException` carries the response body in its message,
our handlers log exceptions with their traceback, and so every refused
command printed the whole page: about a hundred and ten lines. Three
testers retrying was enough to pass Railway's ceiling of 500 log lines a
second, at which point Railway drops them - *"Messages dropped: 235"* -
and the evidence of the outage was being destroyed by the outage.

The second rule is the other half of the same night. The catch-all that
exists so nobody is left staring at "thinking..." tries to apologise
over the API that is refusing us, fails, and raises inside an error
handler - which asyncio reports as *Task exception was never retrieved*,
a second traceback for every first one.

The third rule was written after 9 November, and it is the same failure
from the other side: a playtester's `/look` died twice and
`interaction_log` held nothing for either attempt. Every row in that
table is written downstream of the line that raised, so a crash was the
one thing that could happen in the game and leave no trace - and no row
reads exactly like no command. Finding out why meant replaying the read
path against the live database by hand, one call at a time.

The fourth is the same silence one layer in, and the more embarrassing
half of it. Twenty-two handlers caught `SQLAlchemyError`, told the
player in so many words that the database was the problem, and
returned without writing anything down - so the failure the game
handled *politely* left less behind than the one it handled badly,
and six of those handlers did not even log a traceback. A `/stats`
could fail all evening in total silence.
"""

import logging
from types import SimpleNamespace

import discord
import pytest
from discord import app_commands
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from conftest import ALICE, GUILD_A
from fake_discord import FakeInteraction, FakeNamespace, FakeResponse

import ast
import inspect
from pathlib import Path

import bot
import database
import telemetry


# --------------------------------------------------------------------------
# The cap
# --------------------------------------------------------------------------


def formatted(message, exc_info=None):
    """One record through the real formatter the bot installs."""
    record = logging.LogRecord(
        "catbot", logging.ERROR, __file__, 1, message, (), exc_info
    )
    return bot.CappedFormatter("%(name)s: %(message)s").format(record)


def test_an_ordinary_line_is_untouched():
    assert formatted("The cat is fed.") == "catbot: The cat is fed."


# **A fixed number, not `bot.LOG_RECORD_LIMIT`.** Asserting against the
# constant under test is how three of these first passed with the cap
# switched off: raise the limit and the comparison obliges. The point of
# the rule is that a log line stays small enough for a log pipeline to
# carry, and that is a fact about the world rather than about our
# configuration - so the tests name a size.
ROOM_FOR_ANY_SANE_CAP = 4_000


def test_a_long_line_is_cut_to_the_cap():
    out = formatted("x" * 50_000)

    assert len(out) < ROOM_FOR_ANY_SANE_CAP


def test_the_cut_says_how_much_it_dropped():
    """A truncation that does not announce itself is a lie about the
    size of the problem - which is the whole complaint against the
    behaviour this replaces."""
    out = formatted("x" * 50_000)

    assert "dropped by the log cap" in out


def test_both_ends_survive_the_cut():
    """**Head and tail, not head alone.** A traceback keeps its useful
    parts at both ends: our own frames at the top, and the exception
    type and message at the bottom. Keeping only the first 2,000
    characters of a Cloudflare page would have thrown away the one line
    that said `1015`."""
    body = "HEAD" + "x" * 50_000 + "TAIL"
    out = formatted(body)

    assert len(out) < len(body), "nothing was cut, so this proves nothing"
    assert "HEAD" in out
    assert "TAIL" in out


def test_a_cloudflare_page_in_a_traceback_is_capped():
    """The night itself, in one assertion. The body is what Cloudflare
    actually returns: an HTML document, served where JSON was expected,
    carried into the log by the exception's own message."""
    page = "<!DOCTYPE html>\n" + "\n".join(
        f'    <div class="cf-error-{n}">The owner of this website '
        f"(discord.com) has banned you temporarily.</div>"
        for n in range(400)
    )
    try:
        raise discord.HTTPException(
            SimpleNamespace(status=403, reason="Forbidden"), page
        )
    except discord.HTTPException as banned:
        out = formatted("Unhandled error in command /look", (type(banned), banned, banned.__traceback__))

    assert len(page) > 20_000, "the fixture must be big enough to matter"
    assert len(out) < ROOM_FOR_ANY_SANE_CAP
    assert "HTTPException" in out


# --------------------------------------------------------------------------
# The catch-all, when there is nothing to catch it with
# --------------------------------------------------------------------------


def blocked():
    return discord.HTTPException(
        SimpleNamespace(status=429, reason="Too Many Requests"), "blocked"
    )


class RefusingFollowup:
    """Discord, during the ban: the deferred reply cannot be delivered."""

    async def send(self, *args, **kwargs):
        raise blocked()


class RefusingResponse(FakeResponse):
    """The other door, and a *subclass* rather than a replacement.

    `is_done()` is how the catch-all chooses its door, and it reads the
    interaction's own flag. An earlier draft swapped the whole response
    object out and broke that, which the suite caught only because the
    stand-in refused to answer rather than guessing.
    """

    async def send_message(self, *args, **kwargs):
        raise blocked()


def refusing(*, deferred: bool):
    """An interaction that cannot be replied to.

    **`deferred` lives on the interaction, not on the response** - the
    fake's `is_done()` reads it from there, and setting it in the wrong
    place is how the first draft of these tests passed while exercising
    neither branch.
    """
    interaction = FakeInteraction(1, 2)
    interaction.followup = RefusingFollowup()
    interaction.response = RefusingResponse(interaction)
    interaction.deferred = deferred
    return interaction


async def test_the_catch_all_does_not_raise_when_the_apology_fails(caplog):
    """**The second traceback for every first one.** Left unguarded,
    this raise escapes an error handler and asyncio reports it as a task
    exception nobody retrieved - doubling the log volume at the moment
    the log is already being dropped."""
    with caplog.at_level(logging.WARNING):
        await bot.on_app_command_error(
            refusing(deferred=True), RuntimeError("the original failure")
        )

    assert "Could not even tell" in caplog.text


async def test_the_same_holds_before_the_command_has_answered(caplog):
    """The other door. A command that failed before deferring takes
    `response.send_message`, and during a block that is refused too."""
    with caplog.at_level(logging.WARNING):
        await bot.on_app_command_error(
            refusing(deferred=False), RuntimeError("the original failure")
        )

    assert "Could not even tell" in caplog.text


# --------------------------------------------------------------------------
# The row a crash leaves behind
# --------------------------------------------------------------------------
#
# The two tests above pass without a database, and still do: the write
# below is guarded all the way down, so a catch-all with nowhere to log
# is a catch-all that still apologises.


def crashed_on(command="look", *, guild_id=GUILD_A, user_id=ALICE, **options):
    """An interaction for a command that is about to die."""
    return FakeInteraction(
        user_id, guild_id, command=command, namespace=FakeNamespace(**options)
    )


def raised_inside(error, command="look"):
    """The exception discord.py actually hands the handler.

    A callback's exception arrives wrapped in a `CommandInvokeError`, and
    the wrapper is the same class every time - which is what makes
    `type(error).__name__` the wrong thing to record and `.original` the
    right one.
    """
    return app_commands.CommandInvokeError(SimpleNamespace(name=command), error)


async def crash_rows(db):
    async with db._require_session()() as session:
        return (
            (
                await session.execute(
                    select(database.InteractionLog).where(
                        database.InteractionLog.action == database.CRASHED
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_a_crash_leaves_a_row_naming_the_command_and_the_exception(db):
    """The row that would have ended 9 November in one query.

    `look` and `TypeError` are the two facts the log could not hold, and
    between them they are most of a diagnosis: the verb says where to
    look and the class says what kind of wrong it was.
    """
    await bot.on_app_command_error(
        crashed_on("look"),
        raised_inside(TypeError("can't subtract offset-naive and offset-aware")),
    )

    (row,) = await crash_rows(db)
    assert row.action == database.CRASHED
    assert row.reason == "TypeError"
    assert row.detail == "command=look"
    assert row.user_id == ALICE
    assert row.guild_id == GUILD_A


async def test_the_wrapper_is_not_what_gets_recorded(db):
    """Left wrapped, every crash in the game reads `CommandInvokeError`.

    Which is true of all of them and therefore worth nothing - the
    column would distinguish nothing, which is the one thing a `reason`
    is for.
    """
    await bot.on_app_command_error(crashed_on(), raised_inside(KeyError("ivy")))

    (row,) = await crash_rows(db)
    assert row.reason == "KeyError"


async def test_an_error_that_arrived_unwrapped_is_recorded_as_itself(db):
    """A check failure is not wrapped, and is still worth a row.

    An admin command with no handler of its own answers a non-admin with
    "Something went wrong. Please try again." A row reading
    `MissingPermissions` is the game saying it apologised where it
    should have explained - invisible any other way.
    """
    await bot.on_app_command_error(
        crashed_on("initialize_haunted_house"),
        app_commands.MissingPermissions(["administrator"]),
    )

    (row,) = await crash_rows(db)
    assert row.reason == "MissingPermissions"
    assert row.detail == "command=initialize_haunted_house"


async def test_the_row_carries_what_they_typed(db):
    """Which noun it was is the question a crash row cannot answer twice.

    A failure that only happens on one argument is the ordinary case,
    and the argument is the whole of what makes the row reproducible.
    """
    await bot.on_app_command_error(
        crashed_on("use", thing="watering can"),
        raised_inside(ValueError("no such state"), command="use"),
    )

    (row,) = await crash_rows(db)
    assert row.typed == "thing=watering can"


async def test_a_command_with_no_options_says_nothing_about_them(db):
    """`/look` on its own, which is where this started.

    Null means *there was no word*, the way it does on every other row
    in the table, and not "they typed nothing".
    """
    await bot.on_app_command_error(crashed_on("look"), raised_inside(TypeError()))

    (row,) = await crash_rows(db)
    assert row.typed is None


async def test_an_exception_whose_name_will_not_fit_is_cut_to_size(db):
    """`reason` is `String(32)`, and an over-long value is a dropped row.

    `log_interaction` swallows what it cannot write, by design - so a
    name that overflowed the column would be a crash that logged nothing
    *again*, which is the whole failure this row exists to end.
    """
    name = "A" + "n" * 60 + "Error"
    await bot.on_app_command_error(
        crashed_on(), raised_inside(type(name, (Exception,), {})())
    )

    (row,) = await crash_rows(db)
    assert row.reason == name[:32]
    assert len(row.reason) == 32


async def test_the_row_lands_even_when_the_apology_could_not_be_sent(db, caplog):
    """The crash nobody could be told about is the one most worth a row.

    This is the Cloudflare night and 9 November at once: Discord
    refusing us is exactly when the player gets no apology, and exactly
    when a log that holds nothing leaves nobody anything to work from.
    """
    interaction = refusing(deferred=True)
    interaction.guild_id = GUILD_A
    interaction.command = SimpleNamespace(name="look", qualified_name="look")

    with caplog.at_level(logging.WARNING):
        await bot.on_app_command_error(interaction, raised_inside(TypeError()))

    assert "Could not even tell" in caplog.text
    (row,) = await crash_rows(db)
    assert row.reason == "TypeError"


async def test_a_crash_with_no_guild_is_said_in_a_line_and_dropped(db, caplog):
    """`guild_id` is NOT NULL and a DM belongs to no server's numbers.

    There is no honest value to invent, so the row is skipped rather
    than attributed to a server that was not involved.
    """
    interaction = crashed_on("look")
    interaction.guild_id = None

    with caplog.at_level(logging.WARNING):
        await bot.on_app_command_error(interaction, raised_inside(TypeError()))

    assert "no guild to log it against" in caplog.text
    assert await crash_rows(db) == []


async def test_the_crash_row_carries_the_servers_drop(db):
    """Like every other row, because it is the slicer every question starts with.

    A crash that only happens on one drop's content is a crash somebody
    can date.
    """
    await bot.on_app_command_error(crashed_on(), raised_inside(TypeError()))

    (row,) = await crash_rows(db)
    assert row.drop is not None


# --------------------------------------------------------------------------
# The row a database refusal leaves behind
# --------------------------------------------------------------------------
#
# `crashed` covers the failures nobody saw coming. These are the ones we
# did: a handler catches `SQLAlchemyError`, says something true and kind
# about the database, and returns. Until this they returned silently, so
# the better-behaved failure was the more invisible one.


def refused_on(command="inventory", *, guild_id=GUILD_A, user_id=ALICE, **options):
    """An interaction for a command the database is about to refuse."""
    return FakeInteraction(
        user_id, guild_id, command=command, namespace=FakeNamespace(**options)
    )


def pool_exhausted(message="pool exhausted"):
    """A real `OperationalError`, which is what this looks like in life.

    Built rather than faked so `reason` is checked against the class
    name SQLAlchemy actually raises - the row is only worth anything if
    the word in it is the word somebody would grep for.
    """
    return OperationalError("SELECT 1", {}, Exception(message))


def database_down(monkeypatch, name, error=None):
    async def refuse(*args, **kwargs):
        raise error or pool_exhausted()

    monkeypatch.setattr(database, name, refuse)


async def refusal_rows(db):
    async with db._require_session()() as session:
        return (
            (
                await session.execute(
                    select(database.InteractionLog).where(
                        database.InteractionLog.action == database.DB_ERROR
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_a_refused_command_leaves_a_row_naming_it_and_the_failure(
    db, monkeypatch
):
    """`/inventory` is one of the five that logged nothing whatsoever.

    No row, no traceback: a player saying "my bag won't open" left the
    log with nothing to agree or disagree with.
    """
    database_down(monkeypatch, "get_carried")

    await bot.inventory.callback(refused_on("inventory"))

    (row,) = await refusal_rows(db)
    assert row.action == database.DB_ERROR
    assert row.reason == "OperationalError"
    assert row.detail == "command=inventory"
    assert row.user_id == ALICE
    assert row.guild_id == GUILD_A
    assert row.drop is not None


async def test_the_player_still_gets_the_apology_in_its_own_words(db, monkeypatch):
    """The row is added to the handler, not swapped in for what it said.

    `/inventory` has copy of its own rather than the database sentence,
    and a change that tidied every site into one message would have
    quietly rewritten the game.

    **This one passes with the change reverted**, and is here for that
    reason: it is a guard on what the change must *not* do, not
    evidence that it does anything. Nine of the eleven tests in this
    section fail without it; this is not one of them.
    """
    database_down(monkeypatch, "get_carried")

    interaction = refused_on("inventory")
    await bot.inventory.callback(interaction)

    (content, kwargs) = interaction.sent[-1]
    assert content == bot.INVENTORY_ERROR_MESSAGE
    assert kwargs["ephemeral"] is True


async def test_a_refusal_is_not_filed_as_a_crash(db, monkeypatch):
    """**The whole argument for a second word.**

    A spike of these means the database or the pool; a spike of
    `crashed` means a bug just shipped. They are different alarms and
    want different people out of bed, and one word would have made the
    louder one impossible to see.
    """
    database_down(monkeypatch, "get_carried")

    await bot.inventory.callback(refused_on("inventory"))

    assert len(await refusal_rows(db)) == 1
    assert await crash_rows(db) == []


async def test_the_refusal_row_carries_what_they_typed(db, monkeypatch):
    """Which setting it was, for a command whose whole content is its options.

    Named apart from the crash row's version of this deliberately: the
    first draft gave both the same name, and the second definition
    silently replaced the first - a test deleted by a collision, which
    the count caught and nothing else would have.
    """
    database_down(monkeypatch, "get_setting")

    await bot.admin_config.callback(
        refused_on("admin_config", key="staircase_planks", value=5),
        "staircase_planks",
        5,
    )

    (row,) = await refusal_rows(db)
    assert row.detail == "command=admin_config"
    assert row.typed == "key=staircase_planks value=5"


async def test_the_refusal_row_lands_even_when_the_apology_could_not_be_sent(
    db, caplog, monkeypatch
):
    """Cloudflare and a refused connection at once, which is not far-fetched.

    An apology that could not be delivered is exactly when the row is
    the only thing left - and letting that raise would have handed the
    command to the catch-all, which would have filed it as a crash.
    """
    database_down(monkeypatch, "get_carried")

    interaction = refused_on("inventory")
    interaction.followup = RefusingFollowup()
    interaction.deferred = True

    with caplog.at_level(logging.WARNING):
        await bot.inventory.callback(interaction)

    assert "Could not send the database apology" in caplog.text
    (row,) = await refusal_rows(db)
    assert row.reason == "OperationalError"
    assert await crash_rows(db) == []


async def test_a_failed_write_does_not_turn_a_refusal_into_a_crash(
    db, caplog, monkeypatch
):
    """The row's own failure mode, and the one that would do real harm.

    A raise here escapes a handler that has already apologised, reaches
    the catch-all, and is written down as a `crashed` row for a command
    that did not crash. The one row this exists to write would become a
    row that lies.
    """
    database_down(monkeypatch, "get_carried")

    async def explode(*args, **kwargs):
        raise RuntimeError("the log is on fire")

    monkeypatch.setattr(telemetry, "record", explode)

    interaction = refused_on("inventory")
    with caplog.at_level(logging.ERROR):
        await bot.inventory.callback(interaction)

    assert interaction.sent[-1][0] == bot.INVENTORY_ERROR_MESSAGE
    assert "Could not log the database refusal" in caplog.text


async def test_a_refusal_with_no_guild_is_dropped_but_still_apologised_for(
    db, caplog, monkeypatch
):
    """`guild_id` is NOT NULL and a DM belongs to no server's numbers.

    The row is skipped rather than attributed to a server that was not
    involved - and the player is told either way, because the apology
    is not what the guild is needed for.
    """
    database_down(monkeypatch, "get_carried")

    interaction = refused_on("inventory")
    interaction.guild_id = None

    with caplog.at_level(logging.WARNING):
        await bot.inventory.callback(interaction)

    assert "no guild to log it against" in caplog.text
    assert interaction.sent[-1][0] == bot.INVENTORY_ERROR_MESSAGE
    assert await refusal_rows(db) == []


async def test_a_button_is_named_by_hand_because_it_has_no_command(db, monkeypatch):
    """A component callback carries no `interaction.command` at all.

    Left to derive it the row would read `command=?`, which is the one
    answer that helps nobody - so the two button sites pass the name
    themselves.
    """

    async def refuse(*args, **kwargs):
        raise pool_exhausted()

    monkeypatch.setattr(bot, "_stats_embed", refuse)

    interaction = FakeInteraction(ALICE, GUILD_A)
    interaction.command = None

    await bot._MyStats().callback(interaction)

    (row,) = await refusal_rows(db)
    assert row.detail == "command=stats"
    assert interaction.sent[-1][0] == bot.DB_ERROR_MESSAGE


async def test_both_kinds_of_failure_row_spell_the_command_the_same_way(
    db, monkeypatch
):
    """Counting the two together is the first thing anybody does.

    One `_which_command` for both, so a `crashed` and a `db_error`
    about `/inventory` are a `GROUP BY detail` rather than a join
    somebody has to get right.
    """
    database_down(monkeypatch, "get_carried")
    await bot.inventory.callback(refused_on("inventory"))
    await bot.on_app_command_error(
        crashed_on("inventory"), raised_inside(TypeError(), command="inventory")
    )

    (refused,) = await refusal_rows(db)
    (crashed,) = await crash_rows(db)
    assert refused.detail == crashed.detail == "command=inventory"


# --------------------------------------------------------------------------
# Two things about the shape of bot.py, because the next handler is the risk
# --------------------------------------------------------------------------


def _handlers_catching_the_database():
    """Every `except` clause in bot.py that catches `SQLAlchemyError`."""
    tree = ast.parse(Path(inspect.getsourcefile(bot)).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        caught = {n.attr for n in ast.walk(node.type) if isinstance(n, ast.Attribute)}
        caught |= {n.id for n in ast.walk(node.type) if isinstance(n, ast.Name)}
        if "SQLAlchemyError" in caught:
            yield node, caught


def test_nothing_else_answers_a_database_failure_on_its_own():
    """**The guard, and the reason it is worth a source-reading test.**

    Every one of these handlers was written separately and each one
    separately forgot. The failure mode is not that the helper breaks -
    it is the twenty-third handler, written next month by someone who
    copies the one above it. So the invariant is structural: a handler
    that catches the database does not get to answer the player itself.
    """
    offenders = []
    for handler, _ in _handlers_catching_the_database():
        sends = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("send", "send_message")
            for n in ast.walk(handler)
        )
        routed = any(
            isinstance(n, ast.Name) and n.id == "_the_database_refused"
            for n in ast.walk(handler)
        )
        if sends and not routed:
            offenders.append(handler.lineno)

    assert offenders == [], f"bot.py lines {offenders} answer without logging"


def test_a_handler_that_writes_a_row_catches_the_database_and_nothing_else():
    """A mixed `except` cannot say which alarm the row is.

    Five handlers used to catch `SQLAlchemyError` alongside
    `ContentError`, `UnknownDrop` or `HTTPException` *and* answer the
    player - bad content files, a missing thread and a broken database,
    all behind one sentence. Those are split now, because a `db_error`
    row reading `ContentError` is the wrong word for the wrong
    audience, and only one of the three is worth paging anybody about
    at two in the morning.

    Handlers that answer nobody are left mixed on purpose: there is no
    row for the word to be wrong on, and splitting them would be
    churn.

    **Passes vacuously with the change reverted** - nothing routes, so
    nothing can route wrongly. It earns its place against the next
    handler rather than against this one.
    """
    mixed = [
        (handler.lineno, sorted(caught - {"SQLAlchemyError"}))
        for handler, caught in _handlers_catching_the_database()
        if caught - {"SQLAlchemyError"}
        and any(
            isinstance(n, ast.Name) and n.id == "_the_database_refused"
            for n in ast.walk(handler)
        )
    ]

    assert mixed == [], f"bot.py would file these under the wrong word: {mixed}"
