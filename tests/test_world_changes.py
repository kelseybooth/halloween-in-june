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
        user_id, guild_id, guild=SimpleNamespace(id=guild_id, name="Test", text_channels=[])
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


async def test_every_swing_is_a_plank(house):
    """**Drop 20 changed the unit.** It counted distinct players while
    the wait between turns was 48 rolling hours and ten of them finished
    the job. Ninety planks at one per player per day means the count has
    to be the planks, and the daily cooldown is what stops one person
    laying them all - so three uses are three planks here, where the
    engine is asked directly and no clock is involved.
    """
    for _ in range(3):
        await database.record_use(ALICE, GUILD_A, "lumber")

    placed, _ = await world.planks(GUILD_A)
    assert placed == 3


async def test_two_players_one_plank_each_is_two(house):
    await database.record_use(ALICE, GUILD_A, "lumber")
    await database.record_use(BOB, GUILD_A, "lumber")

    placed, _ = await world.planks(GUILD_A)
    assert placed == 2


async def test_the_target_comes_from_server_config(house):
    await database.set_setting(GUILD_A, world.PLANKS_SETTING, 3)
    _, required = await world.planks(GUILD_A)
    assert required == 3


async def test_the_top_steps_are_four_fifths_of_it_rounded_down(house):
    """A fraction rather than a number, so a QA server with five planks
    reaches the same moment at four instead of never reaching it."""
    assert world.reachable_from_the_floor(90) == 72
    assert world.reachable_from_the_floor(5) == 4
    assert world.reachable_from_the_floor(1) == 0


async def test_the_last_plank_opens_the_staircase_for_everyone(house):
    """Server-wide: the reward for collective labour lands for the whole room,
    not for whoever happened to place the final plank.

    **The ladder has to be in the hall for this, since 30 October.** A
    two-plank target puts `stairs_upper` at one, so the second plank is
    a top-step plank and the top steps need something to stand on. It
    is not a quirk of a small target either: it is the same arithmetic
    on a ninety-plank server, where plank 73 onwards needs the ladder.
    Standing in the Entryway rather than carried, which is the half of
    `to_hand_in_room` that matters here - neither player picks it up.
    """
    await database.set_setting(GUILD_A, world.PLANKS_SETTING, 2)
    await database.place_in_room(GUILD_A, "EN", world.LADDER, 1)

    await use(ALICE)
    assert not await states.has(GUILD_A, BOB, "stairs_repaired")

    await use(BOB)
    assert await states.has(GUILD_A, ALICE, "stairs_repaired")
    assert await states.has(GUILD_A, BOB, "stairs_repaired")


async def test_the_announcement_does_not_repeat(house):
    """Asked of the effect, because the line it rides is posted to the
    room now and this file's fake guild has no channels.
    `test_the_staircase` asserts the announcement arriving, against a
    thread; what belongs here is that it rides the crossing and not
    every plank laid afterwards.
    """
    await database.set_setting(GUILD_A, world.PLANKS_SETTING, 1)
    await use(ALICE)

    again = await world.after_use(GUILD_A, BOB, "lumber", "EN")

    assert again.announce is None


async def test_the_upper_state_is_set_on_the_way(house):
    """Both thresholds, from one count. Five planks puts the top steps
    at four, so the fourth sets `stairs_upper` and the fifth finishes
    the job."""
    await database.set_setting(GUILD_A, world.PLANKS_SETTING, 5)
    for _ in range(3):
        await database.record_use(ALICE, GUILD_A, "lumber")

    await world.check_staircase(GUILD_A)
    assert not await states.has(GUILD_A, ALICE, "stairs_upper")

    await database.record_use(ALICE, GUILD_A, "lumber")
    await world.check_staircase(GUILD_A)

    assert await states.has(GUILD_A, ALICE, "stairs_upper")
    assert not await states.has(GUILD_A, ALICE, "stairs_repaired")


async def test_the_tokens_carry_the_count_and_the_target(house):
    """The numbers the line is written around. Whether a player reads
    them is `test_the_staircase`'s question now that the line is posted
    rather than replied."""
    await database.set_setting(GUILD_A, world.PLANKS_SETTING, 4)
    await use(ALICE)

    effect = await world.after_use(GUILD_A, ALICE, "lumber", "EN")

    assert effect.tokens == {"n": 1, "total": 4}


async def test_placing_a_plank_is_marked_public(house):
    """The only public /use in the game. The others in the room need to see
    the work happen rather than hear about it later.

    **And since 30 October it is public instead of both**, not public as
    well: the player is standing in the room, so the private copy was
    the same sentence twice in two messages. This flag is what the
    handler reads to make that choice, and the choice itself is
    asserted in `test_the_staircase`, against a thread this file's fake
    guild does not have.
    """
    await database.set_setting(GUILD_A, world.PLANKS_SETTING, 5)

    effect = await world.after_use(GUILD_A, ALICE, "lumber", "EN")

    assert effect.public is True


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


# The Entryway's staircase sentence is fragment 7, and every fragment
# past the first is gated on having fed the cat. Asked without that,
# both states of the room come back as the one sentence a new player
# reads - the same string twice, and no evidence of anything.
FED = frozenset({content_module.FED_THE_CAT})


async def test_the_room_description_swaps(house):
    """The Entryway reads differently once the staircase holds.

    **The Upstairs Hallway used to be asserted here too, and cannot
    be.** It had two descriptions because the back stairs let a player
    stand up there before the repair and see a ruin from above. The
    back stairs were deleted on 30 October, so the only way up is the
    repaired staircase, so nobody can be in that hallway and *not*
    hold `stairs_repaired` - and the row describing the ruin was text
    no player could ever have read. The writers cut it, which leaves
    one description and nothing to swap.
    """
    before_en = await resolve.room_look(GUILD_A, "EN", unlocked=FED)

    await states.set_server_state(GUILD_A, "stairs_repaired")

    assert (
        await resolve.room_look(GUILD_A, "EN", "stairs_repaired", FED) != before_en
    )


async def test_the_hallway_reads_the_same_either_way(house):
    """The other half of that cut, asserted rather than assumed.

    One row for the hallway means a player who somehow arrives without
    `stairs_repaired` still reads the hallway as itself, through the
    `default` fallback, instead of "You see a room."
    """
    await states.set_server_state(GUILD_A, "stairs_repaired")

    assert await resolve.room_look(GUILD_A, "UH", "stairs_repaired") == (
        await resolve.room_look(GUILD_A, "UH")
    )
    assert "patched steps" in await resolve.room_look(GUILD_A, "UH")


async def test_a_room_with_no_row_for_your_state_reads_its_default(house):
    """**The fallback, which fragmenting room text nearly cost.**

    A player holds a state the room was never written for - someone who
    unlocked the cabinet standing in the Dining Room, say - and the
    room must still read as itself. The first fragment implementation
    compared each row against the one state and kept no fallback, so
    every such room came back `None` and rendered as "You see a room."
    The Living Room went blank the moment anybody opened the cabinet.
    """
    plain = await resolve.room_look(GUILD_A, "DI")

    assert plain
    assert await resolve.room_look(GUILD_A, "DI", "stairs_repaired") == plain
    assert await resolve.room_look(GUILD_A, "DI", "cabinet_unlocked") == plain


async def test_a_room_written_for_your_state_still_wins(house):
    """The other half: the fallback must not swallow the specific row."""
    await states.set_server_state(GUILD_A, "stairs_repaired")

    assert await resolve.room_look(GUILD_A, "EN", "stairs_repaired", FED) != (
        await resolve.room_look(GUILD_A, "EN", unlocked=FED)
    )


async def test_the_staircase_is_per_server(db):
    for guild in (GUILD_A, GUILD_B):
        await enter(db, ALICE, guild)
    await content_loader.load_content(content_module.load_files())
    await database.set_setting(GUILD_A, world.PLANKS_SETTING, 1)

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


async def test_everything_capped_is_capped_at_one(house):
    """Four things nobody may hold two of. The can opener joined them with
    the drop that has not arrived - one per player, like the key, because
    the point is that everybody can open a can rather than that one person
    can hoard the means."""
    capped = {
        t.thing_id: t.max_per_player
        for t in content_module.load_files().things
        if t.max_per_player
    }
    assert capped == {
        "cat_food_gourmet": 1,
        "skeleton_key": 1,
        "carving_tools": 1,
        "can_opener": 1,
        # The ladder, which is one per player because there is one
        # ladder: a cap on a thing with `quantity = 1` says what the
        # count already says, and says it to the second player who
        # tries rather than letting the first hold a spare.
        "ladder": 1,
        # Both toys, so one player cannot hold the channel's whole supply.
        "feather_wand": 1,
        "crinkle_ball": 1,
        # The brass key, so a spare always goes to somebody new - which
        # is the whole of what a spare is for.
        "house_key": 1,
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
# `requires`: a gate on `/use`, not a state
#
# It is checked after resolution and before any branch, because it answers
# whether this player can do the thing at all rather than what the thing does.
# An unmet requirement refuses the whole use and replies with `use_fail`, and
# a refused use is not a use - the same rule the cooldown already follows.
#
# Nothing here is stored. Put an ingredient down and the gate closes again,
# which is what makes it different from the four states above.
# --------------------------------------------------------------------------


INGREDIENTS = ("herbs", "dark_chocolate", "spice_jar")


async def use_stove(user_id=ALICE):
    await database.update_current_room(user_id, GUILD_A, "KI")
    return (await use(user_id, thing="stove")).reply


async def test_the_stove_requires_all_three(house):
    stove = content_module.load_files().things_by_id["stove"]
    assert set(states.required_things(stove.requires)) == set(INGREDIENTS)


async def carry_the_ingredients(user_id=ALICE, how_many=3):
    for thing in INGREDIENTS[:how_many]:
        await database.take_from_source(user_id, GUILD_A, thing)


async def test_without_the_ingredients_it_refuses(house):
    assert "don't have all of it yet" in await use_stove()


@pytest.mark.parametrize("held", [1, 2])
async def test_some_of_the_ingredients_is_not_enough(house, held):
    await carry_the_ingredients(how_many=held)

    assert "don't have all of it yet" in await use_stove()


async def test_all_three_opens_the_gate(house):
    await carry_the_ingredients()

    reply = await use_stove()
    assert "far more delicious" in reply
    assert "don't have all of it yet" not in reply


async def test_a_refused_use_is_not_a_use(house):
    """The rule the cooldown already follows, and the reason `Something's
    Cooking` can be `a successful on_use of the stove` and nothing more: if a
    refusal recorded a use, the achievement would fire for empty hands."""
    await use_stove()
    assert await database.last_used(ALICE, GUILD_A, "stove") is None

    await carry_the_ingredients()
    await use_stove()
    assert await database.last_used(ALICE, GUILD_A, "stove") is not None


async def test_the_refusal_consumes_nothing(house):
    """Not a transform and not a cost - the player still holds what they had
    and can try again once they have the rest."""
    await carry_the_ingredients(how_many=2)
    await use_stove()

    for thing in INGREDIENTS[:2]:
        assert await database.carried_of(ALICE, GUILD_A, thing) == 1


async def test_a_thing_with_no_use_fail_falls_back_to_the_default(house):
    """`use_fail.default` catches it, so a writer who adds a `requires` and
    forgets the refusal line gets a dull message rather than an empty one."""
    from dataclasses import replace

    parsed = content_module.load_files()
    parsed.thing_text = [
        replace(row, text={k: v for k, v in row.text.items() if k != "use_fail"})
        if row.entity_id == "stove"
        else row
        for row in parsed.thing_text
    ]
    await content_loader.load_content(parsed)

    assert "Nothing happens" in await use_stove()


async def test_putting_one_down_closes_it_again(house):
    """Checked at the moment of use, never recorded - which is what makes it
    different from every other gate in this file."""
    await carry_the_ingredients()
    assert "far more delicious" in await use_stove()

    await database.drop_into_room(ALICE, GUILD_A, "KI", "herbs")
    assert "don't have all of it yet" in await use_stove()


async def test_it_is_per_player(house):
    await carry_the_ingredients()

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
    """An empty requirement must not read as met, or the gate would close on
    the hundred-odd things that carry no `requires` at all."""
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
