"""Resolution: which thing the player meant, and which copy to act on.

The spec calls this the most reused logic in the bot, so it gets the most
tests. Three things here are worth more attention than the rest, because each
is a rule that exists to prevent a specific bug rather than to express an
obvious behaviour:

- **Scope is set before pass one.** `/take` never sees the bag, `/drop` never
  sees the room. The worked example from the spec is reproduced below.
- **A source and its yield are one thing**, or a player standing by a stash
  holding a can is asked "chicken or chicken?" forever.
- **Step four never says where.** Confirming a thing exists is fine; naming its
  room gives away the Secret Library before anyone has found it.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A

import content as content_module
import content_loader
import database
import reach
from reach import Ambiguous, Found, NotFound, Scope, Where
from test_loader import a_thing
from test_world import a_house, carry


@pytest.fixture
async def house(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(BOB, GUILD_A)
    return db


async def find(room="EN", typed="", scope=Scope.REACH, user=ALICE):
    return await reach.find(GUILD_A, user, room, typed, scope)


# --------------------------------------------------------------------------
# Normalising what was typed
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("Cat Food", "cat food"),
        ("  cat   food  ", "cat food"),
        ("blue-door", "blue door"),
        ("Alexa,", "alexa"),
        ("the cat's food", "the cat s food"),
        ("", ""),
    ],
)
def test_input_is_normalised(typed, expected):
    assert reach.normalise(typed) == expected


async def test_matching_ignores_case_and_punctuation(house):
    await content_loader.load_content(a_house(a_thing("spoon", name="silver spoon")))

    for typed in ("silver spoon", "SILVER SPOON", "  Silver  Spoon  ", "silver-spoon"):
        assert isinstance(await find(typed=typed), Found), typed


async def test_an_alias_matches(house):
    await content_loader.load_content(
        a_house(a_thing("spoon", name="silver spoon", aliases=("spoon", "cutlery")))
    )
    assert (await find(typed="cutlery")).thing_id == "spoon"


@pytest.mark.parametrize("typed", ["", "   ", ",,,"])
async def test_empty_input_finds_nothing(house, typed):
    await content_loader.load_content(a_house(a_thing("spoon")))
    assert isinstance(await find(typed=typed), NotFound)


# --------------------------------------------------------------------------
# Scope: the spec's worked example
# --------------------------------------------------------------------------


@pytest.fixture
async def cat_food(house):
    """Carrying chicken, standing in a room with the salmon cupboard."""
    await content_loader.load_content(
        a_house(
            a_thing("chicken", name="chicken cat food", aliases=("cat food",), room_id=None, quantity=0),
            a_thing("salmon", name="salmon cat food", aliases=("cat food",), room_id=None, quantity=0),
            a_thing(
                "cupboard",
                name="cupboard of salmon cat food",
                aliases=("cat food",),
                type="source",
                yields="salmon",
                takeable=False,
            ),
        )
    )
    await carry(house, ALICE, GUILD_A, "chicken")
    return house


async def test_take_is_scoped_to_the_room(cat_food):
    """The bug: with the bag in scope this asks "chicken or salmon?", and if the
    player says chicken there is no chicken in the room to take."""
    result = await find(typed="cat food", scope=Scope.ROOM)

    assert isinstance(result, Found)
    assert result.thing_id == "salmon"


async def test_drop_is_scoped_to_the_bag(cat_food):
    """The same fault mirrored: dropping must not offer the salmon."""
    result = await find(typed="cat food", scope=Scope.CARRIED)

    assert isinstance(result, Found)
    assert result.thing_id == "chicken"


async def test_use_and_look_see_everything_in_reach(cat_food):
    """Two genuinely different things are both reachable, so the prompt is fair."""
    result = await find(typed="cat food", scope=Scope.REACH)

    assert isinstance(result, Ambiguous)
    assert result.options == ["chicken cat food", "salmon cat food"]


async def test_the_prompt_names_the_object_not_the_furniture(cat_food):
    """A source is offered as what it hands over - "salmon cat food", not
    "cupboard of salmon cat food", which the player cannot take."""
    result = await find(typed="cat food", scope=Scope.REACH)
    assert "cupboard of salmon cat food" not in result.options


# --------------------------------------------------------------------------
# A source and its yield are one thing
# --------------------------------------------------------------------------


@pytest.fixture
async def stash(house):
    await content_loader.load_content(
        a_house(
            a_thing("can", name="chicken cat food", aliases=("cat food",), room_id=None, quantity=0),
            a_thing(
                "sofa_stash",
                name="stash of chicken cat food",
                aliases=("cat food",),
                type="source",
                yields="can",
                takeable=False,
            ),
        )
    )
    return house


async def test_standing_by_the_stash_holding_a_can_is_not_ambiguous(stash):
    """Without this rule the player is asked "chicken or chicken?" every time."""
    await carry(stash, ALICE, GUILD_A, "can")
    result = await find(typed="cat food", scope=Scope.REACH)

    assert isinstance(result, Found)
    assert result.thing_id == "can"


async def test_the_carried_copy_wins_for_use_and_look(stash):
    await carry(stash, ALICE, GUILD_A, "can")
    assert (await find(typed="cat food", scope=Scope.REACH)).where is Where.CARRIED


async def test_take_reaches_the_source_because_the_bag_is_not_in_scope(stash):
    await carry(stash, ALICE, GUILD_A, "can")
    result = await find(typed="cat food", scope=Scope.ROOM)

    assert result.where is Where.SOURCE
    assert result.yields == "can"


async def test_the_sources_own_name_still_matches_it(stash):
    result = await find(typed="stash of chicken cat food", scope=Scope.ROOM)
    assert isinstance(result, Found)
    assert result.where is Where.SOURCE


async def test_a_source_is_never_consumed_so_it_always_resolves(stash):
    for _ in range(3):
        assert isinstance(await find(typed="cat food", scope=Scope.ROOM), Found)


# --------------------------------------------------------------------------
# Pass two: which copy
# --------------------------------------------------------------------------


async def test_the_bag_is_checked_before_the_room(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    await carry(house, ALICE, GUILD_A, "spoon")

    assert (await find(typed="spoon")).where is Where.CARRIED


async def test_the_room_is_used_when_nothing_is_carried(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    assert (await find(typed="spoon")).where is Where.ROOM


async def test_loose_objects_come_before_sources(house):
    await content_loader.load_content(
        a_house(
            a_thing("can", name="beans", room_id="EN", quantity=1),
            a_thing("crate", name="crate of beans", aliases=("beans",), type="source", yields="can", takeable=False),
        )
    )
    assert (await find(typed="beans", scope=Scope.ROOM)).where is Where.ROOM


async def test_several_copies_of_one_thing_never_prompt(house):
    """Pass one settled it; a count is not an ambiguity."""
    await content_loader.load_content(a_house(a_thing("bottle", quantity=5)))

    result = await find(typed="bottle")
    assert isinstance(result, Found)
    assert result.count == 5


async def test_a_copy_inside_a_container_is_in_reach(house):
    """A bare name always works - never an `in <container>` parser."""
    await content_loader.load_content(
        a_house(
            a_thing("box", name="amazon box", type="fixture", takeable=False),
            a_thing("jar", name="spice jar", contained_in="box"),
        )
    )

    result = await find(typed="spice jar", scope=Scope.ROOM)
    assert isinstance(result, Found)
    assert result.container_id == "box"


# --------------------------------------------------------------------------
# Nothing in reach
# --------------------------------------------------------------------------


async def test_a_word_the_game_does_not_know(house):
    await content_loader.load_content(a_house(a_thing("spoon")))

    result = await find(typed="helicopter")
    assert isinstance(result, NotFound)
    assert result.exists_elsewhere is False


async def test_a_thing_that_exists_but_is_elsewhere(house):
    await content_loader.load_content(
        a_house(a_thing("spoon"), a_thing("kettle", room_id="KI"))
    )

    result = await find(typed="kettle")
    assert isinstance(result, NotFound)
    assert result.exists_elsewhere is True


async def test_nothing_reveals_where_it_is(house):
    """Naming the room would give away the Secret Library before anyone has
    found it, so the result carries a boolean and never a location."""
    await content_loader.load_content(
        a_house(a_thing("spoon"), a_thing("kettle", room_id="KI"))
    )

    result = await find(typed="kettle")
    assert not hasattr(result, "room_id")
    assert "KI" not in repr(result)


async def test_take_knows_the_difference_between_absent_and_already_carried(house):
    """take_fail.absent would be a lie when the player is holding one."""
    await content_loader.load_content(a_house(a_thing("spoon", room_id=None, quantity=0)))
    await carry(house, ALICE, GUILD_A, "spoon")

    result = await find(typed="spoon", scope=Scope.ROOM)
    assert isinstance(result, NotFound)
    assert result.carried is True


async def test_that_distinction_is_only_drawn_for_take(house):
    await content_loader.load_content(a_house(a_thing("spoon", room_id=None, quantity=0)))
    await carry(house, ALICE, GUILD_A, "spoon")

    result = await find(typed="spoon", scope=Scope.CARRIED)
    assert isinstance(result, Found)


async def test_an_emptied_object_is_out_of_reach(house):
    await content_loader.load_content(a_house(a_thing("chips")))
    async with house._require_session()() as session:
        await session.execute(database.RoomContents.__table__.update().values(count=0))
        await session.commit()

    assert isinstance(await find(typed="chips"), NotFound)


async def test_another_players_bag_is_out_of_reach(house):
    await content_loader.load_content(a_house(a_thing("spoon", room_id=None, quantity=0)))
    await carry(house, BOB, GUILD_A, "spoon")

    assert isinstance(await find(typed="spoon", user=ALICE), NotFound)


# --------------------------------------------------------------------------
# Fixtures and exits
# --------------------------------------------------------------------------


async def test_a_fixture_is_in_reach_without_being_stock(house):
    await content_loader.load_content(
        a_house(a_thing("fireplace", type="fixture", takeable=False))
    )

    result = await find(typed="fireplace")
    assert isinstance(result, Found)
    assert result.count == 1


async def test_an_exit_is_in_reach(house):
    await content_loader.load_content(
        a_house(a_thing("door", name="blue door", type="exit", destination_room_id="KI", takeable=False))
    )
    assert isinstance(await find(typed="blue door"), Found)


async def test_a_fixture_in_another_room_is_not(house):
    await content_loader.load_content(
        a_house(a_thing("fireplace", type="fixture", room_id="KI", takeable=False))
    )
    assert isinstance(await find(typed="fireplace"), NotFound)


# --------------------------------------------------------------------------
# Drops gate reach too
# --------------------------------------------------------------------------


async def test_a_thing_from_an_unarrived_drop_is_out_of_reach(house):
    from datetime import date, timedelta

    from content import Drop

    parsed = a_house(a_thing("lantern", since_drop=2))
    parsed.drops.append(
        Drop(drop_id=2, trigger="manual", date=None, event=None, name="Later", notes=None)
    )
    await content_loader.load_content(parsed)

    result = await reach.find(GUILD_A, ALICE, "EN", "lantern", Scope.REACH)
    assert isinstance(result, NotFound)


# --------------------------------------------------------------------------
# Against the real content
# --------------------------------------------------------------------------


async def test_the_shipped_house_resolves_a_fixture(house):
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "EN", "mirror", Scope.REACH)
    assert isinstance(result, Found)
    assert result.thing_id == "ornate_mirror"


async def test_the_shipped_house_resolves_an_exit_by_alias(house):
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "EN", "stairs", Scope.REACH)
    assert isinstance(result, Found)


async def test_taking_cat_food_in_the_kitchen_reaches_the_pantry_stash(house):
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "KI", "tuna", Scope.ROOM)
    assert isinstance(result, Found)
    assert result.where is Where.SOURCE
    assert result.yields == "cat_food_tuna"


async def test_the_gourmet_tin_is_reachable_inside_the_bed(house):
    """Contained things resolve by bare name; discovery is preserved by what the
    listing shows, not by what the player has to type."""
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "BE", "gourmet", Scope.ROOM)
    assert isinstance(result, Found)
    assert result.container_id == "bed"
