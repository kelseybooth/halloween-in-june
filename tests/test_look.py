"""`/look` in its three shapes, and the listing rules.

The listing is the fiddly part and most of what is here. One rule runs through
all of it: **no listing anywhere names a source.** A source is inexhaustible,
so it would sit in every listing for ever; the prose that reveals it is what a
player reads instead, and the loader refuses content where that prose is
missing. Everything else about `/look` follows from where a thing is.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeInteraction

import bot
import content as content_module
import content_loader
import database
import phrasing
from content import TextRow
from test_loader import a_thing
from test_world import a_house, carry


async def look(user_id=ALICE, guild_id=GUILD_A, thing=None):
    interaction = FakeInteraction(user_id, guild_id)
    await bot.look.callback(interaction, thing)
    return interaction


@pytest.fixture
async def house(db):
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
        await db.start_game(who, GUILD_A, "EN", ["EN", "KI"])
    return db


# --------------------------------------------------------------------------
# Looking around
# --------------------------------------------------------------------------


async def test_looking_around_gives_the_room_description(house):
    await content_loader.load_content(a_house())

    interaction = await look()
    assert "The Entryway." in interaction.reply
    assert interaction.was_private


async def test_a_room_with_nothing_loose_has_no_listing(house):
    """Four of the nine rooms are in that state at launch. No line at all,
    rather than a line saying the room is empty."""
    await content_loader.load_content(a_house())

    assert "Also here" not in (await look()).reply


async def test_loose_things_are_listed(house):
    await content_loader.load_content(a_house(a_thing("spoon", name="silver spoon")))

    assert "Also here: silver spoon" in (await look()).reply


async def test_a_count_above_one_is_shown(house):
    await content_loader.load_content(a_house(a_thing("herbs", name="herbs", quantity=10)))

    assert "herbs x10" in (await look()).reply


async def test_a_count_of_one_is_not_decorated(house):
    await content_loader.load_content(a_house(a_thing("spoon", name="spoon")))
    reply = (await look()).reply

    assert "spoon" in reply
    assert "x1" not in reply


async def test_several_things_are_separated(house):
    await content_loader.load_content(
        a_house(a_thing("a", name="apple"), a_thing("b", name="candle"))
    )
    assert "apple, candle" in (await look()).reply


async def test_a_source_is_never_listed(house):
    """The rule that runs through every listing in the game."""
    await content_loader.load_content(
        a_house(
            a_thing("can", name="tin", room_id=None, quantity=0),
            a_thing("crate", name="crate of tins", type="source", yields="can",
                    takeable=False),
        )
    )
    assert "Also here" not in (await look()).reply


async def test_a_fixture_is_not_listed(house):
    """Fixtures are the room, not things in it."""
    await content_loader.load_content(
        a_house(a_thing("fireplace", name="fireplace", type="fixture", takeable=False))
    )
    assert "Also here" not in (await look()).reply


async def test_an_exit_is_not_listed(house):
    await content_loader.load_content(
        a_house(a_thing("door", name="blue door", type="exit",
                        destination_room_id="KI", takeable=False))
    )
    assert "Also here" not in (await look()).reply


async def test_a_contained_thing_is_not_listed_in_the_room(house):
    """It shows when the container is looked at. That is how the gourmet can
    stays findable under the bed without the bed's prose giving it away."""
    await content_loader.load_content(
        a_house(
            a_thing("bed", name="bed", type="fixture", takeable=False),
            a_thing("tin", name="gourmet tin", contained_in="bed"),
        )
    )
    assert "gourmet tin" not in (await look()).reply


async def test_something_taken_leaves_the_listing(house):
    await content_loader.load_content(a_house(a_thing("chips", name="chips")))
    assert "chips" in (await look()).reply

    await database.take_from_room(ALICE, GUILD_A, "EN", "", "chips")
    assert "Also here" not in (await look()).reply


async def test_something_dropped_joins_the_listing_for_everyone(house):
    await content_loader.load_content(a_house(a_thing("spoon", name="spoon")))
    await database.take_from_room(ALICE, GUILD_A, "EN", "", "spoon")
    await database.drop_into_room(ALICE, GUILD_A, "EN", "spoon")

    assert "spoon" in (await look(BOB)).reply


async def test_looking_outside_the_house_is_refused(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await content_loader.load_content(a_house())

    assert "must be in a room" in (await look()).reply


# --------------------------------------------------------------------------
# Looking at a thing
# --------------------------------------------------------------------------


async def test_looking_at_a_thing_gives_its_description(house):
    await content_loader.load_content(a_house(a_thing("spoon", name="spoon")))

    assert (await look(thing="spoon")).reply == "It is a spoon."


async def test_a_carried_thing_uses_look_carried(house):
    """Six things describe where they were sitting, which stops being true the
    moment somebody picks them up."""
    await content_loader.load_content(
        a_house(
            a_thing("glasses", name="reading glasses"),
            thing_text=[
                TextRow(entity_id="glasses", state="default", since_drop=1,
                        text={"look": "Folded on the desk.",
                              "look_carried": "Smudged, in your hand."})
            ],
        )
    )
    assert (await look(thing="reading glasses")).reply == "Folded on the desk."

    await database.take_from_room(ALICE, GUILD_A, "EN", "", "glasses")
    assert (await look(thing="reading glasses")).reply == "Smudged, in your hand."


async def test_a_carried_thing_without_look_carried_falls_back(house):
    await content_loader.load_content(a_house(a_thing("spoon", name="spoon")))
    await database.take_from_room(ALICE, GUILD_A, "EN", "", "spoon")

    assert (await look(thing="spoon")).reply == "It is a spoon."


async def test_looking_at_something_absent(house):
    await content_loader.load_content(
        a_house(a_thing("spoon"), a_thing("kettle", name="kettle", room_id="KI"))
    )
    assert "don" in (await look(thing="kettle")).reply


async def test_looking_at_a_word_the_game_does_not_know(house):
    """`/look` has its own line for this, and does not share `unknown.noun`
    with `/take` and `/use`: looking at nonsense earns a shrug, where trying
    to take it should still say the house has no such thing."""
    await content_loader.load_content(a_house(a_thing("spoon")))
    defaults = content_module.load_files().defaults

    reply = (await look(thing="helicopter")).reply
    assert reply == defaults["look_fail.unknown"]
    assert reply != defaults["unknown.noun"]


async def test_an_ambiguous_look_asks(house):
    await content_loader.load_content(
        a_house(
            a_thing("chicken", name="chicken cat food", aliases=("cat food",)),
            a_thing("salmon", name="salmon cat food", aliases=("cat food",)),
        )
    )
    assert "Which one" in (await look(thing="cat food")).reply


# --------------------------------------------------------------------------
# Looking at a container
# --------------------------------------------------------------------------


def with_a_box():
    return a_house(
        a_thing("box", name="amazon box", type="fixture", takeable=False),
        a_thing("jar", name="spice jar", contained_in="box"),
        thing_text=[
            TextRow(entity_id="box", state="default", since_drop=1,
                    text={"look": "A half-opened parcel."}),
            TextRow(entity_id="jar", state="default", since_drop=1,
                    text={"look": "A jar of something orange."}),
        ],
    )


async def test_looking_in_a_container_lists_what_is_inside(house):
    await content_loader.load_content(with_a_box())

    reply = (await look(thing="amazon box")).reply
    assert "A half-opened parcel." in reply
    assert "Here you find: spice jar" in reply


async def test_an_empty_container_prints_no_listing(house):
    """The same as an empty room. There is no "it's empty" string and there
    should not be one."""
    await content_loader.load_content(with_a_box())
    await database.take_from_room(ALICE, GUILD_A, "EN", "box", "jar")

    reply = (await look(thing="amazon box")).reply
    assert "A half-opened parcel." in reply
    assert "Here you find" not in reply


async def test_a_bare_name_finds_a_contained_thing(house):
    """Never an `in <container>` parser - it is a syntax players have to guess."""
    await content_loader.load_content(with_a_box())

    assert (await look(thing="spice jar")).reply == "A jar of something orange."


async def test_a_source_inside_a_container_is_not_listed(house):
    await content_loader.load_content(
        a_house(
            a_thing("pantry", name="pantry", type="fixture", takeable=False),
            a_thing("can", name="tin", room_id=None, quantity=0),
            a_thing("stack", name="stack of tins", type="source", yields="can",
                    takeable=False, contained_in="pantry"),
        )
    )
    assert "Here you find" not in (await look(thing="pantry")).reply


# --------------------------------------------------------------------------
# Truncation
#
# Ships with the scheduler that causes it: ten scattered objects a day and
# nothing removing them until somebody takes one.
# --------------------------------------------------------------------------


async def test_a_long_listing_is_cut_rather_than_lost(house):
    parsed = a_house(
        *[a_thing(f"t{i}", name=f"curiously long object number {i}") for i in range(200)]
    )
    await content_loader.load_content(parsed)

    reply = (await look()).reply
    assert len(reply) <= phrasing.MESSAGE_LIMIT
    assert "more" in reply


async def test_the_cut_says_how_much_was_left_out(house):
    parsed = a_house(
        *[a_thing(f"t{i}", name=f"curiously long object number {i}") for i in range(200)]
    )
    await content_loader.load_content(parsed)

    reply = (await look()).reply
    import re

    stated = int(re.search(r"and (\d+) more", reply).group(1))
    listed = reply.count("curiously long object")
    assert stated + listed == 200


async def test_a_listing_that_fits_is_not_cut(house):
    await content_loader.load_content(
        a_house(a_thing("a", name="apple"), a_thing("b", name="candle"))
    )
    assert "more" not in (await look()).reply


async def test_the_room_description_is_never_cut(house):
    """The listing gives way to the prose, not the other way round."""
    long_description = "A very long room. " * 100
    parsed = a_house(*[a_thing(f"t{i}", name=f"object {i}") for i in range(200)])
    parsed.room_text = [
        TextRow(entity_id="EN", state="default", since_drop=1,
                text={"look": long_description}),
        TextRow(entity_id="KI", state="default", since_drop=1, text={"look": "Kitchen."}),
    ]
    await content_loader.load_content(parsed)

    reply = (await look()).reply
    assert long_description.strip() in reply
    assert len(reply) <= phrasing.MESSAGE_LIMIT


# --------------------------------------------------------------------------
# Against the real content
# --------------------------------------------------------------------------


async def test_the_entryway_reads_properly(house):
    await content_loader.load_content(content_module.load_files())

    reply = (await look()).reply
    assert "foyer" in reply.lower()
    assert len(reply) <= phrasing.MESSAGE_LIMIT


async def test_the_cake_box_does_not_list_the_gourmet_cans(house):
    """The cans are a source, and no listing anywhere names a source.

    So looking at the box describes a cake box, and it is *using* it that
    reveals what is inside - which is the joke, and which is also why the
    loader insists the box's own text names them.
    """
    await content_loader.load_content(content_module.load_files())
    await database.update_current_room(ALICE, GUILD_A, "KI")

    room = (await look()).reply
    assert "gourmet" not in room.lower()

    box = (await look(thing="cake box")).reply
    assert "Here you find" not in box
    assert "caramel apple cake" in box.lower()


async def test_using_the_cake_box_reveals_the_cans(house):
    await content_loader.load_content(content_module.load_files())
    await database.update_current_room(ALICE, GUILD_A, "KI")

    import phrasing

    said = await phrasing.say(GUILD_A, "cake_box", "use", fallback="use.default")
    assert "gourmet" in said.lower()


async def test_no_room_in_the_house_lists_a_source(house):
    await content_loader.load_content(content_module.load_files())
    import resolve

    sources = {
        t.thing_id: t.name
        for t in content_module.load_files().things
        if t.is_source
    }
    for room_id, _ in await resolve.all_rooms():
        await database.update_current_room(ALICE, GUILD_A, room_id)
        reply = (await look()).reply
        _, _, listed = reply.partition("Also here:")
        for name in sources.values():
            assert name not in listed, f"{name} listed in {room_id}"


# --------------------------------------------------------------------------
# /inventory, rendered the same way
# --------------------------------------------------------------------------


async def inventory(user_id=ALICE, guild_id=GUILD_A):
    interaction = FakeInteraction(user_id, guild_id)
    await bot.inventory.callback(interaction)
    return interaction


async def test_an_empty_bag_says_so(house):
    await content_loader.load_content(a_house(a_thing("spoon")))

    interaction = await inventory()
    assert interaction.reply == "Your bag is empty."
    assert interaction.was_private


async def test_the_bag_lists_what_is_carried(house):
    await content_loader.load_content(
        a_house(a_thing("spoon", name="spoon"), a_thing("herbs", name="herbs", quantity=10))
    )
    await database.take_from_room(ALICE, GUILD_A, "EN", "", "spoon")
    for _ in range(10):
        await database.take_from_room(ALICE, GUILD_A, "EN", "", "herbs")

    reply = (await inventory()).reply
    assert reply.startswith("You're carrying: ")
    assert "herbs x10" in reply
    assert "spoon" in reply


async def test_a_bag_reads_the_way_a_room_does(house):
    """Ten herbs in a bag and ten on the floor should not look different."""
    await content_loader.load_content(a_house(a_thing("herbs", name="herbs", quantity=10)))
    room = (await look()).reply
    for _ in range(10):
        await database.take_from_room(ALICE, GUILD_A, "EN", "", "herbs")

    assert "herbs x10" in room
    assert "herbs x10" in (await inventory()).reply
