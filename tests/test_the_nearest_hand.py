"""Which copy of a thing a verb acts on, when a room holds several.

A room holds the same thing in more than one place at a time, and always
has: `container_id` is part of room_contents' key, so a dirty bottle on
the kitchen floor, a second in the pantry and a third in the bin are
three rows in one room. The spec calls which-copy "pass two" and gave it
three places - your hands, the room, a source - which was a complete
answer right up to the point where the room stopped being one place.

**And it was not choosing between them. It was discarding two of them.**
`_gather` collected the room's stock into a dict keyed by thing id, so
three rows became one, and the survivor was whichever the database
happened to hand back last: an order nothing chose and nothing could
predict from the files.

The order, settled 31 October:

    your hands, the floor, a cupboard, a source, the bin.

The three in the middle are what "nearest hand" means inside a room.
Something lying out is nearer than something inside the pantry, and both
are nearer than opening the freezer for a new one.

**The bin is last, and below the source on purpose.** A player who types
`/take burrito` in a kitchen with a freezer in it means the freezer;
nobody picks the rubbish over the groceries. The price was weighed when
the rule was asked for: while a source is standing in the room its copy
in the bin can never be reached, so a burrito or a can opener thrown away
is thrown away. Everything whose only copy is in there - a diaper, a
spice jar, a toy, a bottle - still comes back out, which is all *Trash
Panda* ever needed. `test_the_trash_can` has that end to end.
"""

import pytest

from conftest import ALICE, GUILD_A

import content_loader
import database
import reach
from reach import Scope, Where
from test_loader import a_thing
from test_world import a_house, carry


@pytest.fixture
async def house(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    return db


def a_fixture(thing_id, name, **overrides):
    """Furniture: in the room because the files say so, and not stock."""
    return a_thing(thing_id, name=name, type="fixture", takeable=False, **overrides)


def a_bottle():
    return a_thing(
        "bottle", name="dirty bottle", aliases=("bottle",), room_id=None, quantity=0
    )


@pytest.fixture
async def four_bottles(house):
    """A bottle in four places: the floor, the pantry, the bin, and a
    crate that hands them out.

    Nothing in the house has all four at once, and that is the reason to
    build it. The order has to be total, and a rule tested only where the
    content happens to exercise it is a rule with gaps nobody can see.
    """
    await content_loader.load_content(
        a_house(
            a_bottle(),
            a_fixture("pantry", "pantry"),
            a_fixture("trash_can", "trash can"),
            a_thing(
                "crate", name="crate of bottles", aliases=("bottle", "crate"),
                type="source", yields="bottle", takeable=False,
            ),
        )
    )
    return house


@pytest.fixture
async def bin_only(house):
    """The same bottle and a bin, and nothing else that has one."""
    await content_loader.load_content(a_house(a_bottle(), a_fixture("trash_can", "trash can")))
    return house


async def put(container=database.LOOSE_IN_ROOM, count=1):
    await database.place_in_room(GUILD_A, "EN", "bottle", count, container)


async def taking(scope=Scope.ROOM, typed="bottle"):
    return await reach.find(GUILD_A, ALICE, "EN", typed, scope)


# --------------------------------------------------------------------------
# The five rungs, one pair at a time
# --------------------------------------------------------------------------


async def test_the_floor_comes_before_the_pantry(four_bottles):
    await put()
    await put("pantry")

    result = await taking()

    assert result.where is Where.ROOM
    assert result.container_id is None


async def test_the_pantry_comes_before_the_crate(four_bottles):
    await put("pantry")

    result = await taking()

    assert result.where is Where.ROOM
    assert result.container_id == "pantry"


async def test_the_crate_comes_before_the_bin(four_bottles):
    """The rung the writers asked for by name."""
    await put("trash_can")

    assert (await taking()).where is Where.SOURCE


async def test_and_the_bin_is_reached_when_nothing_else_has_one(bin_only):
    """Which is what keeps going through the trash worth doing."""
    await put("trash_can")

    result = await taking()

    assert result.where is Where.ROOM
    assert result.container_id == "trash_can"


async def test_the_copy_in_your_hands_beats_all_of_them(four_bottles):
    await put()
    await carry(four_bottles, ALICE, GUILD_A, "bottle")

    assert (await taking(Scope.REACH)).where is Where.CARRIED


# --------------------------------------------------------------------------
# And all of them at once
# --------------------------------------------------------------------------


async def test_the_whole_ladder_in_one_room(four_bottles):
    """Taken one at a time until the crate answers, which is the
    assertion the pairs above cannot make between them: this is one
    order rather than three separate preferences."""
    await put()
    await put("pantry")
    await put("trash_can")

    reached = []
    for _ in range(4):
        result = await taking()
        if result.is_source:
            reached.append("crate")
            break
        reached.append(result.container_id)
        await database.take_from_room(
            ALICE, GUILD_A, "EN", result.container_id or database.LOOSE_IN_ROOM,
            "bottle",
        )

    assert reached == [None, "pantry", "crate"]


async def test_three_rows_in_one_room_are_all_of_them_seen(four_bottles):
    """The bug underneath the order, asserted where it was rather than
    where it showed. Two of these three rows did not survive being
    collected, so no ranking anywhere could have reached them."""
    await put()
    await put("pantry")
    await put("trash_can")

    candidates = await reach._gather(GUILD_A, ALICE, "EN", Scope.ROOM)

    assert candidates["bottle"].room_copies == {None: 1, "pantry": 1, "trash_can": 1}


async def test_the_count_belongs_to_the_copy_and_not_to_the_room(four_bottles):
    """One on the floor and four in the pantry is a one, because the one
    on the floor is the copy being acted on."""
    await put(count=1)
    await put("pantry", count=4)

    assert (await taking()).count == 1


# --------------------------------------------------------------------------
# What the order does not change
# --------------------------------------------------------------------------


async def test_a_word_only_the_crate_answers_to_still_means_the_crate(four_bottles):
    """`crate` is the crate and not a bottle out of it, which is what
    separates a harvest from a pickup and what *Green Thumb* turns on.
    Above every rung including the hand: a player who says `crate` while
    holding a bottle is not talking about the bottle."""
    await put()
    await carry(four_bottles, ALICE, GUILD_A, "bottle")

    assert (await taking(Scope.REACH, "crate")).where is Where.SOURCE


async def test_a_shared_word_leaves_the_order_alone(four_bottles):
    """`bottle` is both of their words, so it is the ladder's question
    and not the source's."""
    await put()

    assert (await taking(Scope.REACH)).where is Where.ROOM


async def test_drop_is_still_scoped_to_the_bag(four_bottles):
    """The room now offers four rungs and `/drop` may reach none of them.
    Scope is applied twice, in `_gather` and again in `_rungs`, because a
    list built in one place and ranked in another is two chances to widen
    it by accident."""
    await put()

    assert isinstance(await taking(Scope.CARRIED), reach.NotFound)
