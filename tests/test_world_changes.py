"""The two uses that change the world, and the gates that depend on them.

One test per line of the 2c.5 definition of done, plus the `present_when`
machinery both changes rest on.

The distinction worth keeping in view: the staircase is **server-wide**,
because collective labour earns a collective reward, and the drawer is **per
player**, because the discovery is the content. Getting either scope backwards
would not crash anything - it would quietly make the game worse, so several
tests below check the scope rather than the effect.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A, GUILD_B
from fake_discord import FakeInteraction

import bot
import content as content_module
import content_loader
import database
import reach
import resolve
import states
import world
from content import TextRow
from test_loader import a_thing
from test_world import a_house


async def enter(db, user_id, guild_id=GUILD_A, room="EN"):
    await db.ensure_user_exists(user_id, guild_id)
    await db.start_game(user_id, guild_id, room, ["EN", "KI", "UH"])


async def use(user_id=ALICE, guild_id=GUILD_A, thing="lumber"):
    from types import SimpleNamespace

    interaction = FakeInteraction(
        user_id, guild_id, guild=SimpleNamespace(name="Test", text_channels=[])
    )
    await bot.use.callback(interaction, thing)
    return interaction


@pytest.fixture
async def house(db):
    for who in (ALICE, BOB):
        await enter(db, who)
    await content_loader.load_content(content_module.load_files())
    return db


# --------------------------------------------------------------------------
# Gates
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "gate, held, expected",
    [
        (None, set(), True),
        ("", set(), True),
        ("drawer_unjammed", set(), False),
        ("drawer_unjammed", {"drawer_unjammed"}, True),
        ("!stairs_repaired", set(), True),
        ("!stairs_repaired", {"stairs_repaired"}, False),
        ("!stairs_repaired", {"has_key"}, True),
    ],
)
def test_a_gate_is_read_correctly(gate, held, expected):
    assert states.passes(gate, held) is expected


async def test_a_server_state_is_permanent_and_idempotent(house):
    assert await states.set_server_state(GUILD_A, "stairs_repaired") is True
    assert await states.set_server_state(GUILD_A, "stairs_repaired") is False


async def test_a_player_state_is_permanent_and_idempotent(house):
    assert await states.set_player_state(GUILD_A, ALICE, "drawer_unjammed") is True
    assert await states.set_player_state(GUILD_A, ALICE, "drawer_unjammed") is False


async def test_an_unknown_state_is_refused(house):
    with pytest.raises(ValueError):
        await states.set_server_state(GUILD_A, "drawer_unjammed")  # per player
    with pytest.raises(ValueError):
        await states.set_player_state(GUILD_A, ALICE, "stairs_repaired")  # server-wide


# --------------------------------------------------------------------------
# The staircase
# --------------------------------------------------------------------------


async def test_one_plank_per_player_however_many_times_they_swing(house):
    await database.record_use(ALICE, GUILD_A, "lumber")
    await database.record_use(ALICE, GUILD_A, "lumber")
    await database.record_use(ALICE, GUILD_A, "lumber")

    placed, _ = await world.planks(GUILD_A)
    assert placed == 1


async def test_the_target_comes_from_server_config(house):
    await database.set_setting(GUILD_A, "planks_required", 3)
    _, required = await world.planks(GUILD_A)
    assert required == 3


async def test_the_last_plank_opens_the_staircase_for_everyone(house):
    """Server-wide: the reward for collective labour lands for the whole room,
    not for whoever happened to place the final plank."""
    await database.set_setting(GUILD_A, "planks_required", 2)

    await use(ALICE)
    assert not await states.has(GUILD_A, BOB, "stairs_repaired")

    await use(BOB)
    assert await states.has(GUILD_A, ALICE, "stairs_repaired")
    assert await states.has(GUILD_A, BOB, "stairs_repaired")


async def test_it_only_announces_once(house):
    await database.set_setting(GUILD_A, "planks_required", 1)

    first = await use(ALICE)
    assert "staircase is finished" in first.reply.lower()

    second = await use(BOB)
    assert "staircase is finished" not in second.reply.lower()


async def test_the_reply_carries_the_count_and_the_target(house):
    await database.set_setting(GUILD_A, "planks_required", 4)
    reply = (await use(ALICE)).reply

    assert "1" in reply and "4" in reply


async def test_placing_a_plank_posts_publicly(house):
    """The only public /use in the game. The others in the room need to see
    the work happen rather than hear about it later."""
    await database.set_setting(GUILD_A, "planks_required", 5)
    interaction = await use(ALICE)

    # The private reply always goes out; the public one needs a channel, which
    # the fake guild has none of - so what is asserted here is that the effect
    # is marked public rather than that Discord accepted it.
    effect = await world.after_use(GUILD_A, ALICE, "lumber", "EN")
    assert effect.public is True
    assert interaction.was_private


async def test_an_ordinary_use_is_not_public(house):
    effect = await world.after_use(GUILD_A, ALICE, "ornate_mirror", "EN")
    assert effect is None


async def test_lumber_disappears_once_the_staircase_is_done(house):
    """present_when = !stairs_repaired. The planks stop being a thing you can
    interact with, because the job is finished."""
    found = await reach.find(GUILD_A, ALICE, "EN", "lumber", reach.Scope.REACH)
    assert isinstance(found, reach.Found)

    await states.set_server_state(GUILD_A, "stairs_repaired")

    gone = await reach.find(GUILD_A, ALICE, "EN", "lumber", reach.Scope.REACH)
    assert isinstance(gone, reach.NotFound)


async def test_the_room_descriptions_swap(house):
    """Both the Entryway and the Upstairs Hallway have a stairs_repaired row."""
    before_en = await resolve.room_look(GUILD_A, "EN")
    before_uh = await resolve.room_look(GUILD_A, "UH")

    await states.set_server_state(GUILD_A, "stairs_repaired")

    assert await resolve.room_look(GUILD_A, "EN", "stairs_repaired") != before_en
    assert await resolve.room_look(GUILD_A, "UH", "stairs_repaired") != before_uh


async def test_the_staircase_is_per_server(db):
    for guild in (GUILD_A, GUILD_B):
        await enter(db, ALICE, guild)
    await content_loader.load_content(content_module.load_files())
    await database.set_setting(GUILD_A, "planks_required", 1)

    await use(ALICE, GUILD_A)

    assert await states.has(GUILD_A, ALICE, "stairs_repaired")
    assert not await states.has(GUILD_B, ALICE, "stairs_repaired")


# --------------------------------------------------------------------------
# The drawer
# --------------------------------------------------------------------------


async def carrying_graphite(db, user_id=ALICE):
    await database.take_from_source(user_id, GUILD_A, "graphite_powder")
    await database.update_current_room(user_id, GUILD_A, "UH")


async def test_graphite_in_the_hallway_unjams_the_drawer(house):
    await carrying_graphite(house)
    await use(ALICE, thing="graphite")

    assert await states.has(GUILD_A, ALICE, "drawer_unjammed")


async def test_it_unjams_for_that_player_and_nobody_else(house):
    """Per player because the discovery *is* the content. Server-wide would
    mean only the first person ever found the drawer."""
    await carrying_graphite(house)
    await use(ALICE, thing="graphite")

    assert not await states.has(GUILD_A, BOB, "drawer_unjammed")


async def test_graphite_anywhere_else_changes_nothing(house):
    await database.take_from_source(ALICE, GUILD_A, "graphite_powder")
    await database.update_current_room(ALICE, GUILD_A, "KI")

    await use(ALICE, thing="graphite")
    assert not await states.has(GUILD_A, ALICE, "drawer_unjammed")


async def test_the_expired_stash_is_hidden_until_the_drawer_opens(house):
    """The source is gated on drawer_unjammed, so it does not exist for a
    player who has not opened it."""
    await database.update_current_room(ALICE, GUILD_A, "UH")

    before = await reach.find(GUILD_A, ALICE, "UH", "expired cat food", reach.Scope.ROOM)
    assert isinstance(before, reach.NotFound)

    await states.set_player_state(GUILD_A, ALICE, "drawer_unjammed")

    after = await reach.find(GUILD_A, ALICE, "UH", "expired cat food", reach.Scope.ROOM)
    assert isinstance(after, reach.Found)


async def test_two_players_in_one_room_see_different_things(house):
    """The clearest statement of why the drawer is per player."""
    await database.update_current_room(ALICE, GUILD_A, "UH")
    await database.update_current_room(BOB, GUILD_A, "UH")
    await states.set_player_state(GUILD_A, ALICE, "drawer_unjammed")

    mine = await reach.find(GUILD_A, ALICE, "UH", "expired cat food", reach.Scope.ROOM)
    theirs = await reach.find(GUILD_A, BOB, "UH", "expired cat food", reach.Scope.ROOM)

    assert isinstance(mine, reach.Found)
    assert isinstance(theirs, reach.NotFound)


async def test_the_desk_reads_differently_once_it_is_open(house):
    plain = await resolve.thing_text(GUILD_A, "rolltop_desk", "use")
    opened = await resolve.thing_text(
        GUILD_A, "rolltop_desk", "use", "drawer_unjammed"
    )

    assert plain != opened
    assert "expired" in opened.lower()


# --------------------------------------------------------------------------
# max_per_player, the third item
# --------------------------------------------------------------------------


async def test_the_three_capped_things_are_capped_at_one(house):
    capped = {
        t.thing_id: t.max_per_player
        for t in content_module.load_files().things
        if t.max_per_player
    }
    assert capped == {
        "cat_food_gourmet": 1,
        "skeleton_key": 1,
        "carving_tools": 1,
    }


async def test_each_capped_thing_has_its_own_refusal_written(house):
    """They read as refusals rather than errors - "You've already found
    yours" - which only works if a writer wrote one."""
    text = {
        r.entity_id: r.text
        for r in content_module.load_files().thing_text
        if r.state == "default"
    }
    for thing_id in ("cat_food_gourmet", "skeleton_key", "carving_tools"):
        assert text[thing_id].get("take_fail"), thing_id


# --------------------------------------------------------------------------
# `requires`: a reply that depends on what you are holding
#
# The fifth kind of state, and the only computed one. The four above are things
# that have happened and cannot un-happen; this one is true for exactly as long
# as the player holds everything the thing names, and stops the moment they put
# one down.
# --------------------------------------------------------------------------


INGREDIENTS = ("herbs", "dark_chocolate", "spice_jar")


async def use_stove(user_id=ALICE):
    await database.update_current_room(user_id, GUILD_A, "KI")
    return (await use(user_id, thing="stove")).reply


async def test_the_stove_requires_all_three(house):
    stove = content_module.load_files().things_by_id["stove"]
    assert set(states.required_things(stove.requires)) == set(INGREDIENTS)


async def test_without_the_ingredients_it_says_so(house):
    assert "don't have all of it yet" in await use_stove()


@pytest.mark.parametrize("held", [1, 2])
async def test_some_of_the_ingredients_is_not_enough(house, held):
    for thing in INGREDIENTS[:held]:
        await database.take_from_source(ALICE, GUILD_A, thing)

    assert "don't have all of it yet" in await use_stove()


async def test_all_three_changes_the_reply(house):
    for thing in INGREDIENTS:
        await database.take_from_source(ALICE, GUILD_A, thing)

    reply = await use_stove()
    assert "far more delicious" in reply
    assert "don't have all of it yet" not in reply


async def test_putting_one_down_takes_it_away_again(house):
    """Computed, not recorded - which is what makes it different from every
    other state in the game."""
    for thing in INGREDIENTS:
        await database.take_from_source(ALICE, GUILD_A, thing)
    assert "far more delicious" in await use_stove()

    await database.drop_into_room(ALICE, GUILD_A, "KI", "herbs")
    assert "don't have all of it yet" in await use_stove()


async def test_it_is_per_player(house):
    for thing in INGREDIENTS:
        await database.take_from_source(ALICE, GUILD_A, thing)

    assert "far more delicious" in await use_stove(ALICE)
    assert "don't have all of it yet" in await use_stove(BOB)


async def test_carries_all_needs_every_one(house):
    assert await database.carries_all(ALICE, GUILD_A, list(INGREDIENTS)) is False
    for thing in INGREDIENTS[:2]:
        await database.take_from_source(ALICE, GUILD_A, thing)
    assert await database.carries_all(ALICE, GUILD_A, list(INGREDIENTS)) is False

    await database.take_from_source(ALICE, GUILD_A, INGREDIENTS[2])
    assert await database.carries_all(ALICE, GUILD_A, list(INGREDIENTS)) is True


async def test_nothing_required_is_never_satisfied(house):
    """An empty requirement must not read as met, or every thing without one
    would resolve to a requirements_met row it does not have."""
    assert await database.carries_all(ALICE, GUILD_A, []) is False


async def test_a_requirement_naming_a_thing_that_does_not_exist_is_caught(house):
    from dataclasses import replace

    import content as content_mod

    broken = content_mod.load_files()
    broken.things = [
        replace(t, requires="herbs|nonexistent") if t.thing_id == "stove" else t
        for t in broken.things
    ]
    assert any("is not a thing" in p for p in content_mod.validate(broken))
