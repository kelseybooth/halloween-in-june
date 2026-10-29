"""A log line has a ceiling, and the catch-all survives a silent Discord.

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
"""

import logging
from types import SimpleNamespace

import discord
import pytest

from fake_discord import FakeInteraction, FakeResponse

import bot


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
