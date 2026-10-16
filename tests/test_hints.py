"""The hint rail: one mechanism for every nudge, firing once each.

The invariant does most of the work here, and most of these tests exist
to pin it: **never recommend an action the player has already taken.**
It holds because an action is recorded before the hints for that message
are considered, and because a hint is retired two ways written down the
same way - by being shown, and by being made moot.

The case worth the whole design is at the bottom: a player whose first
`/look` is `/look cat bed` gets one hint rather than two, and it is not
the one telling them to look at the cat bed.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
import hints
import resolve
import triggers


@pytest.fixture
async def channel(db):
    achievements.clear()
    triggers.register_all()
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A,
        name="Test Server",
        channels=[halloween],
        members=[FakeMember(ALICE), FakeMember(BOB)],
    )
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, 1)
    bot.forget_public_pets()
    yield db, guild, halloween
    achievements.clear()


async def run(channel, command, *args, who=ALICE):
    _, guild, halloween = channel
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await command.callback(interaction, *args)
    return interaction


def said(interaction) -> str:
    out = []
    for text, kwargs in interaction.sent:
        out.append(text or "")
        embed = kwargs.get("embed")
        if embed is not None and embed.description:
            out.append(embed.description)
    return "\n".join(out)


async def look(channel, thing=None, who=ALICE):
    return said(await run(channel, bot.look, thing, who=who))


async def use(channel, thing="cat bed", who=ALICE):
    return said(await run(channel, bot.use, thing, who=who))


async def pet(channel, who=ALICE):
    return said(await run(channel, bot.pet, who=who))


# --------------------------------------------------------------------------
# How a hint looks
# --------------------------------------------------------------------------


async def test_a_hint_is_labelled_and_italic(channel):
    reply = await look(channel)

    assert "*Hint: Specific things can be looked at. Try /look cat bed.*" in reply


def test_the_label_is_not_in_the_writer_string():
    defaults = content_module.load_files().defaults

    assert not defaults["hint.look_specific"].startswith("Hint:")


# --------------------------------------------------------------------------
# Each one fires once
# --------------------------------------------------------------------------


async def test_the_look_hint_fires_once(channel):
    assert "Try /look cat bed" in await look(channel)

    assert "Try /look cat bed" not in await look(channel)


async def test_the_use_hint_fires_once(channel):
    assert "Try /use cat bed" in await look(channel, "cat bed")

    assert "Try /use cat bed" not in await look(channel, "cat bed")


async def test_the_first_pet_hint_fires_once(channel, monkeypatch):
    _friendly(monkeypatch)

    assert "first achievement" in await pet(channel)
    assert "first achievement" not in await pet(channel)


async def test_the_two_pet_hints_are_a_fork(channel, monkeypatch):
    """A player gets one of them, on whichever their first pet was."""
    _standoffish(monkeypatch)

    reply = await pet(channel)

    assert "Petting affects your relationship" in reply
    assert "first achievement" not in reply


# --------------------------------------------------------------------------
# The invariant
# --------------------------------------------------------------------------


async def test_looking_at_the_bed_first_gives_one_hint_not_two(channel):
    """**The case the whole design is for.** `hint.look_specific` would
    tell this player to try `/look cat bed`, which they are reading the
    answer to. It is retired by the action rather than by a condition
    written on the hint."""
    reply = await look(channel, "cat bed")

    assert "Try /look cat bed" not in reply
    assert "Try /use cat bed" in reply
    assert reply.count("*Hint:") == 1


async def test_using_the_bed_before_looking_gives_the_look_hint(channel):
    reply = await use(channel)

    assert "Things can be looked at, too" in reply


async def test_looking_before_using_gives_the_use_hint(channel):
    reply = await look(channel, "cat bed")

    assert "Things can be used, too" in reply


async def test_a_player_who_has_done_both_gets_neither(channel):
    await look(channel, "cat bed")
    await use(channel)

    assert "*Hint:" not in await look(channel, "cat bed")
    assert "*Hint:" not in await use(channel)


async def test_a_refused_use_still_counts_as_having_used(channel):
    """They have learnt what `/use` is. Being told to try it would be
    advice to do the thing they were just refused for doing."""
    await use(channel)
    await database.notice(GUILD_A, ALICE, "reset")  # no-op, keeps the day

    assert "Things can be used, too" not in await look(channel, "cat bed")


async def test_a_hint_passed_over_is_still_waiting(channel, monkeypatch):
    """Only one line per message, and the one that lost is not spent.

    A first pet offers two candidates - the pet hint and "there is
    something new here". The pet hint wins and the other is untouched,
    so it arrives on the next message instead of being lost."""
    _standoffish(monkeypatch)

    first = await pet(channel)
    second = await pet(channel)

    assert "Petting affects your relationship" in first
    assert "There is something new here" not in first
    assert "There is something new here" in second


# --------------------------------------------------------------------------
# At most one line
# --------------------------------------------------------------------------


async def test_never_two_hints_on_one_message(channel, monkeypatch):
    _friendly(monkeypatch)

    for reply in (await pet(channel), await look(channel), await use(channel)):
        assert reply.count("*Hint:") <= 1


# --------------------------------------------------------------------------
# Something new
# --------------------------------------------------------------------------


async def test_the_drop_announcement_carries_its_hint(channel):
    _, guild, halloween = channel
    await resolve.set_current_drop(GUILD_A, 0)
    admin = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)

    await bot.advance_game.callback(admin, True)

    posted = " ".join(halloween.posted)
    assert "swats her paw" in posted
    assert "There is something new here" in posted


async def test_the_public_firing_marks_nobody(channel):
    """A channel post has no player attached, and marking everyone as
    told would kill the private fallback for exactly the people it
    exists for - whoever was not looking when it went up."""
    _, guild, halloween = channel
    await resolve.set_current_drop(GUILD_A, 0)
    await bot.advance_game.callback(
        FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween), True
    )

    assert not await database.has_been_told(
        GUILD_A, BOB, hints.SOMETHING_NEW.hint_id
    )


async def test_somebody_who_missed_it_is_told_privately(channel, monkeypatch):
    """The fallback. BOB was asleep when the drop opened."""
    _standoffish(monkeypatch)
    await database.notice(GUILD_A, BOB, hints.FIRST_STANDOFFISH.hint_id)

    reply = await pet(channel, who=BOB)

    assert "There is something new here" in reply


async def test_and_not_if_they_have_already_looked(channel, monkeypatch):
    _standoffish(monkeypatch)
    await database.notice(GUILD_A, BOB, hints.FIRST_STANDOFFISH.hint_id)
    await look(channel, who=BOB)

    assert "There is something new here" not in await pet(channel, who=BOB)


# --------------------------------------------------------------------------
# The quest notice
# --------------------------------------------------------------------------


async def test_a_new_quest_is_announced_once_the_hints_are_spent(channel):
    """**Hints come first, and a quest notice waits behind them.** One
    line per message means a player working through the tutorial hears
    about a quest a message or two late. That is the right way round -
    the hints teach the verbs the quest will need - but it does mean
    the notice is not prompt, and the first pet's hint already says to
    check `/stats` for open quests."""
    await database.award_player_achievement(GUILD_A, ALICE, "making_first_contact")
    await look(channel)            # spends hint.look_specific
    await look(channel, "cat bed")  # spends hint.try_use

    assert "A new quest is available" in await look(channel, "cat bed")


async def test_it_is_computed_rather_than_tracked(channel):
    """No event to subscribe to: the notice is the difference between
    what is visible and what this player has been told, which is why a
    quest that opened overnight is news on their next command."""
    await database.award_player_achievement(GUILD_A, ALICE, "making_first_contact")

    assert await hints.quest_notice(GUILD_A, ALICE)
    assert await hints.quest_notice(GUILD_A, ALICE) is None


async def test_opening_stats_is_enough_to_have_been_told(channel):
    await database.award_player_achievement(GUILD_A, ALICE, "making_first_contact")
    await run(channel, bot.stats)

    assert await hints.quest_notice(GUILD_A, ALICE) is None


async def test_it_points_at_stats_rather_than_naming_the_quest(channel):
    """Three quests is unreachable in Phase 3a - only two public ones
    exist before drop 2 - so the graduated string ships unexercised by
    design. This pins the ungraduated half."""
    await database.award_player_achievement(GUILD_A, ALICE, "making_first_contact")

    line = await hints.quest_notice(GUILD_A, ALICE)

    assert "Check /stats" in line
    assert "A Paw in the Door" not in line


async def test_the_graduated_line_exists_and_names_the_quest(channel):
    """Unreachable through play, so driven directly - a string nothing
    can reach is a string nobody has read."""
    await database.award_player_achievement(GUILD_A, ALICE, "making_first_contact")
    await database.notice(GUILD_A, ALICE, hints.OPENED_STATS)
    for filler in ("a", "b", "c"):
        await database.notice(GUILD_A, ALICE, filler)

    line = await hints.quest_notice(GUILD_A, ALICE)

    assert "A Paw in the Door" in line
    assert "Attain a relationship of +50" in line


# --------------------------------------------------------------------------
# It never costs the message it rides on
# --------------------------------------------------------------------------


async def test_a_broken_rail_still_delivers_the_reply(channel, monkeypatch):
    async def explode(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(hints, "pick", explode)

    reply = await look(channel)

    assert "Items here:" in reply
    assert "*Hint:" not in reply


# --------------------------------------------------------------------------


def _friendly(monkeypatch):
    reaction = bot.Reaction(bot.FRIENDLY_RESPONSES[0], True, 80)
    monkeypatch.setattr(bot, "choose_response", lambda *a, **k: reaction)


def _standoffish(monkeypatch):
    reaction = bot.Reaction(bot.STANDOFFISH_RESPONSES[0], False, 0)
    monkeypatch.setattr(bot, "choose_response", lambda *a, **k: reaction)
