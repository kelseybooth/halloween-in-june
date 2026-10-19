"""Which commands exist in a server, and the registration that enforces it.

**The riskiest work in Phase 3a is subtraction**, and subtraction is what
a one-sided test will not catch. Every test here that asserts a command is
absent at one drop also asserts it is present at another: "`/look` is not
registered" is true of a working gate and of a bot that registered nothing
at all, and only the pair tells them apart.

A command a player cannot use is not in their menu. Not greyed out, not
refusing - absent, so it cannot be typed, guessed, or half-learned from
the autocomplete.
"""

import pytest

from conftest import ALICE, GUILD_A, GUILD_B, HOUSE_DROP
from fake_discord import FakeChannel, FakeGuild, FakeMember

import bot
import gating

PLAYER_VERBS = {"pet", "stats", "look", "use", "take", "drop", "inventory", "enter"}


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------


def test_a_server_with_no_game_offers_one_way_to_start():
    """Not the same as drop 0. Nobody has run `/start-game`, so there is
    nowhere for the cat to be and nothing for a player to do."""
    menu = gating.commands_for(None)

    assert "start-game" in menu
    assert not (menu & PLAYER_VERBS)


def test_drop_zero_is_two_verbs():
    menu = gating.commands_for(0)

    assert menu & PLAYER_VERBS == {"pet", "stats"}


def test_drop_one_adds_look_and_use_and_nothing_else():
    menu = gating.commands_for(1)

    assert menu & PLAYER_VERBS == {"pet", "stats", "look", "use"}


@pytest.mark.parametrize("verb", ["look", "use"])
def test_the_drop_one_verbs_are_absent_at_drop_zero_and_present_at_one(verb):
    """Both directions, because absence alone is also what a broken gate
    that registers nothing looks like."""
    assert verb not in gating.commands_for(0)
    assert verb in gating.commands_for(1)


@pytest.mark.parametrize("verb", ["take", "drop", "inventory", "enter"])
def test_the_out_of_scope_verbs_are_absent_from_both_poc_drops(verb):
    """The scope table's own list, and the gating has to prove it. Present
    at drop 3, so this is a gate rather than a bot with no commands."""
    assert verb not in gating.commands_for(0)
    assert verb not in gating.commands_for(1)
    assert verb in gating.commands_for(HOUSE_DROP)


@pytest.mark.parametrize("name", ["initialize-haunted-house"])
def test_the_house_admin_commands_wait_for_the_house(name):
    assert name not in gating.commands_for(1)
    assert name in gating.commands_for(HOUSE_DROP)


def test_an_admin_can_always_reach_the_three_that_matter():
    """Including in a server with no game, which is the one place a player
    sees nothing at all."""
    for drop in (None, 0, 1, HOUSE_DROP):
        assert {"start-game", "advance-game", "admin_config"} <= gating.commands_for(drop)


def test_a_drop_with_no_entry_uses_the_one_below_it():
    """Drop 2 has its own entry now that the toys are built. Nothing
    sits between 2 and 3, so a server QA has jumped to a drop with no
    table of its own still sees the highest set at or below it."""
    # Drop 2 has its own entry now, so the fallback has to be shown on a
    # drop that genuinely has none. Four and five are the house filling
    # in, and they add no verbs.
    assert 4 not in gating.PLAYER_COMMANDS
    assert gating.commands_for(4) == gating.commands_for(3)
    assert gating.commands_for(2) != gating.commands_for(1)


def test_every_name_in_the_table_is_a_command_that_exists():
    """The table is strings, and a typo in one would quietly cost a server
    a verb. Checked against what the bot actually defines."""
    defined = {c.name for c in bot.bot.tree.get_commands()}
    named = set()
    for table in (gating.PLAYER_COMMANDS, gating.ADMIN_COMMANDS):
        for names in table.values():
            named |= set(names)

    assert named <= defined, named - defined


def test_what_a_drop_turns_on():
    assert gating.arrivals(0, 1) == {"look", "use"}
    assert gating.arrivals(None, 0) == {"pet", "stats"}
    assert gating.arrivals(1, 1) == set()


def test_rewinding_turns_nothing_on():
    """`arrivals` answers what appeared, so going back answers with
    nothing rather than with a negative."""
    assert gating.arrivals(1, 0) == set()


# --------------------------------------------------------------------------
# The registration itself
# --------------------------------------------------------------------------


class FakeTree:
    """Enough of a command tree to see what was registered where."""

    def __init__(self, defined):
        self._defined = defined
        self.per_guild: dict[int, set[str]] = {}
        self.syncs: list[int] = []

    def clear_commands(self, *, guild):
        self.per_guild[guild.id] = set()

    def add_command(self, command, *, guild):
        self.per_guild.setdefault(guild.id, set()).add(command.name)

    async def sync(self, *, guild=None):
        self.syncs.append(guild.id if guild else None)
        return sorted(self.per_guild.get(guild.id if guild else None, ()))


@pytest.fixture
def tree(monkeypatch):
    defined = {c.name: c for c in bot.bot.tree.get_commands()}
    fake = FakeTree(defined)
    monkeypatch.setattr(bot, "_DEFINED", defined)
    return fake


def a_guild(guild_id=GUILD_A):
    return FakeGuild(
        guild_id, channels=[FakeChannel(name="halloween")], members=[FakeMember(ALICE)]
    )


async def test_registering_puts_exactly_the_drops_set_in_place(db, tree):
    guild = a_guild()

    await bot.register_commands_for(guild, 1, tree)

    assert tree.per_guild[GUILD_A] == gating.commands_for(1)


async def test_it_is_one_request_per_guild(db, tree):
    """A bulk overwrite rather than a create or delete per command, which
    is what keeps `/qa-drop` churn clear of the per-command limits."""
    guild = a_guild()

    await bot.register_commands_for(guild, 1, tree)

    assert tree.syncs == [GUILD_A]


async def test_advancing_replaces_the_set_rather_than_adding_to_it(db, tree):
    guild = a_guild()
    await bot.register_commands_for(guild, 0, tree)

    await bot.register_commands_for(guild, 1, tree)

    assert tree.per_guild[GUILD_A] == gating.commands_for(1)


async def test_rewinding_takes_the_verbs_away_again(db, tree):
    """The direction that matters for an admin who advanced by mistake."""
    guild = a_guild()
    await bot.register_commands_for(guild, 1, tree)
    assert "look" in tree.per_guild[GUILD_A]

    await bot.register_commands_for(guild, 0, tree)

    assert "look" not in tree.per_guild[GUILD_A]
    assert "pet" in tree.per_guild[GUILD_A]


async def test_two_servers_get_their_own_sets(db, tree):
    """The reason registration is per guild at all."""
    await bot.register_commands_for(a_guild(GUILD_A), 0, tree)
    await bot.register_commands_for(a_guild(GUILD_B), 1, tree)

    assert "look" not in tree.per_guild[GUILD_A]
    assert "look" in tree.per_guild[GUILD_B]


async def test_the_drop_is_read_from_the_server_when_not_given(db, tree):
    import content as content_module
    import content_loader
    import resolve

    await content_loader.load_content(content_module.load_files())
    await resolve.set_current_drop(GUILD_A, 0)

    await bot.register_commands_for(a_guild(), tree=tree)

    assert tree.per_guild[GUILD_A] == gating.commands_for(0)


async def test_a_name_no_command_answers_to_is_logged_not_raised(db, tree, caplog):
    """A typo in the table should cost one verb, not every verb."""
    tree._defined.pop("look", None)
    bot._DEFINED.pop("look", None)

    await bot.register_commands_for(a_guild(), 1, tree)

    assert "pet" in tree.per_guild[GUILD_A]
    assert "look" not in tree.per_guild[GUILD_A]
