"""Reading the world: the house layout, exits, `/look` and `/inventory`.

Everything here goes through the content tables. The per-guild rooms and things
tables this used to test are no longer written or read, so the tests that
covered them went with the functions.

What is deliberately *not* here is the phase 2c resolution ladder: scoping by
verb, ambiguity prompts, `Also here:`, containers, sources and transforms. 2b's
job was to keep `/look` and `/inventory` behaving as they did while moving the
data under them, and that is what these assert.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import content as content_module
import content_loader
import database
import resolve
from content import Content, Drop, Room, TextRow, Thing
from test_loader import a_thing


def a_house(*things, rooms=(("EN", "Entryway"), ("KI", "Kitchen")), thing_text=None):
    parsed = Content()
    parsed.rooms = [
        Room(room_id=rid, name=name, sort_order=i, open_at_launch=True)
        for i, (rid, name) in enumerate(rooms)
    ]
    parsed.room_text = [
        TextRow(entity_id=rid, state="default", since_drop=1, text={"look": f"The {name}."})
        for rid, name in rooms
    ]
    parsed.things = list(things)
    parsed.thing_text = list(thing_text) if thing_text is not None else [
        TextRow(
            entity_id=t.thing_id,
            state="default",
            since_drop=1,
            text={"look": f"It is a {t.name}."},
        )
        for t in things
    ]
    # The real house strings, not stand-ins: the work order asks that every
    # default be reachable by a path a test can trigger, and asserting against
    # invented text would prove the plumbing while missing the writer's words.
    parsed.defaults = dict(content_module.load_files().defaults)
    parsed.drops = [
        Drop(drop_id=1, trigger="date", date="launch", event=None, name="Launch", notes=None)
    ]
    return parsed


@pytest.fixture
async def house(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(BOB, GUILD_A)
    return db


async def carry(db, user_id, guild_id, thing_id, count=1):
    async with db._require_session()() as session:
        session.add(
            database.PlayerInventory(
                guild_id=guild_id, user_id=user_id, thing_id=thing_id, count=count
            )
        )
        await session.commit()


# --------------------------------------------------------------------------
# The house comes from the files
# --------------------------------------------------------------------------


async def test_rooms_come_from_the_content_tables(house):
    await content_loader.load_content(a_house())
    assert await resolve.all_rooms() == [("EN", "Entryway"), ("KI", "Kitchen")]


async def test_rooms_are_ordered_by_sort_order(house):
    parsed = a_house(rooms=(("KI", "Kitchen"), ("EN", "Entryway")))
    await content_loader.load_content(parsed)
    assert [r[0] for r in await resolve.all_rooms()] == ["KI", "EN"]


async def test_the_shipped_house_has_nine_rooms_and_twenty_exits(house):
    await content_loader.load_content(content_module.load_files())

    rooms = await resolve.all_rooms()
    assert len(rooms) == 9

    total = 0
    for room_id, _ in rooms:
        total += len(await resolve.exits_from(GUILD_A, room_id))
    assert total == 20


async def test_the_shipped_house_is_still_fully_connected(house):
    """The graph check that used to live in house_utils, now over the real data."""
    await content_loader.load_content(content_module.load_files())
    rooms = [rid for rid, _ in await resolve.all_rooms()]

    seen, queue = {"EN"}, ["EN"]
    while queue:
        for exit_ in await resolve.exits_from(GUILD_A, queue.pop()):
            if exit_.destination not in seen:
                seen.add(exit_.destination)
                queue.append(exit_.destination)

    assert seen == set(rooms)


# --------------------------------------------------------------------------
# open_at_launch
# --------------------------------------------------------------------------


async def test_the_secret_library_is_locked_at_launch(house):
    await content_loader.load_content(content_module.load_files())
    assert "SE" not in await resolve.rooms_open_at_launch()


async def test_every_other_room_is_open(house):
    await content_loader.load_content(content_module.load_files())
    assert len(await resolve.rooms_open_at_launch()) == 8


async def test_a_new_player_does_not_start_with_the_library_unlocked(house):
    await content_loader.load_content(content_module.load_files())
    await house.start_game(
        ALICE, GUILD_A, await resolve.starting_room(), await resolve.rooms_open_at_launch()
    )

    state = await house.get_game_state(ALICE, GUILD_A)
    assert "SE" not in state.rooms_unlocked
    assert state.current_room == "EN"


async def test_the_starting_room_is_the_entryway(house):
    await content_loader.load_content(content_module.load_files())
    assert await resolve.starting_room() == "EN"


# --------------------------------------------------------------------------
# Exits
# --------------------------------------------------------------------------


async def test_an_exit_resolves_by_name(house):
    await content_loader.load_content(content_module.load_files())
    exits = await resolve.exits_from(GUILD_A, "EN")
    first = exits[0]

    assert await resolve.resolve_exit(GUILD_A, "EN", first.name) == first


async def test_an_exit_resolves_by_alias(house):
    await content_loader.load_content(content_module.load_files())
    target = next(e for e in await resolve.exits_from(GUILD_A, "EN") if e.aliases)

    assert await resolve.resolve_exit(GUILD_A, "EN", target.aliases[0]) == target


@pytest.mark.parametrize("wrap", [str.upper, str.lower, lambda s: f"  {s}  "])
async def test_exit_matching_ignores_case_and_padding(house, wrap):
    await content_loader.load_content(content_module.load_files())
    target = (await resolve.exits_from(GUILD_A, "EN"))[0]

    assert await resolve.resolve_exit(GUILD_A, "EN", wrap(target.name)) == target


@pytest.mark.parametrize("typed", ["", "   ", "nowhere at all"])
async def test_unresolvable_input_returns_nothing(house, typed):
    await content_loader.load_content(content_module.load_files())
    assert await resolve.resolve_exit(GUILD_A, "EN", typed) is None


async def test_an_exit_from_another_room_does_not_resolve_here(house):
    await content_loader.load_content(content_module.load_files())
    elsewhere = (await resolve.exits_from(GUILD_A, "BE"))[0]

    assert await resolve.resolve_exit(GUILD_A, "EN", elsewhere.name) is None


async def test_every_exit_in_the_house_resolves_from_its_own_room(house):
    await content_loader.load_content(content_module.load_files())

    for room_id, _ in await resolve.all_rooms():
        for exit_ in await resolve.exits_from(GUILD_A, room_id):
            assert await resolve.resolve_exit(GUILD_A, room_id, exit_.name) == exit_


# --------------------------------------------------------------------------
# /look at the room
# --------------------------------------------------------------------------


async def test_looking_at_a_room_gives_its_description(house):
    await content_loader.load_content(a_house())
    assert await resolve.room_look(GUILD_A, "EN") == "The Entryway."


async def test_an_unknown_room_has_no_description(house):
    await content_loader.load_content(a_house())
    assert await resolve.room_look(GUILD_A, "NOWHERE") is None


# --------------------------------------------------------------------------
# /look at a thing
# --------------------------------------------------------------------------


async def test_looking_at_a_thing_in_the_room(house):
    await content_loader.load_content(a_house(a_thing("spoon", name="silver spoon")))

    found = await database.look_at_thing_here(ALICE, GUILD_A, "EN", "silver spoon")
    assert found.description == "It is a silver spoon."
    assert found.count == 1


@pytest.mark.parametrize("typed", ["SILVER SPOON", "  silver spoon  ", "Silver Spoon"])
async def test_looking_is_case_and_whitespace_insensitive(house, typed):
    await content_loader.load_content(a_house(a_thing("spoon", name="silver spoon")))
    assert await database.look_at_thing_here(ALICE, GUILD_A, "EN", typed) is not None


async def test_looking_matches_an_alias(house):
    await content_loader.load_content(
        a_house(a_thing("spoon", name="silver spoon", aliases=("spoon", "cutlery")))
    )
    assert await database.look_at_thing_here(ALICE, GUILD_A, "EN", "cutlery") is not None


async def test_looking_at_something_absent_finds_nothing(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    assert await database.look_at_thing_here(ALICE, GUILD_A, "EN", "hammer") is None


@pytest.mark.parametrize("blank", ["", "   "])
async def test_looking_at_nothing_finds_nothing(house, blank):
    await content_loader.load_content(a_house(a_thing("spoon")))
    assert await database.look_at_thing_here(ALICE, GUILD_A, "EN", blank) is None


async def test_a_thing_in_another_room_is_not_visible(house):
    await content_loader.load_content(a_house(a_thing("spoon", room_id="KI")))
    assert await database.look_at_thing_here(ALICE, GUILD_A, "EN", "spoon") is None


async def test_several_copies_report_a_count(house):
    await content_loader.load_content(a_house(a_thing("bottle", quantity=5)))

    found = await database.look_at_thing_here(ALICE, GUILD_A, "EN", "bottle")
    assert found.count == 5


async def test_a_carried_thing_is_found_from_any_room(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    await carry(house, ALICE, GUILD_A, "spoon")

    assert await database.look_at_thing_here(ALICE, GUILD_A, "KI", "spoon") is not None


async def test_room_and_bag_counts_add_up(house):
    await content_loader.load_content(a_house(a_thing("bottle", quantity=2)))
    await carry(house, ALICE, GUILD_A, "bottle", count=3)

    found = await database.look_at_thing_here(ALICE, GUILD_A, "EN", "bottle")
    assert found.count == 5


async def test_another_players_bag_is_not_counted(house):
    await content_loader.load_content(a_house(a_thing("bottle", quantity=1)))
    await carry(house, BOB, GUILD_A, "bottle", count=4)

    found = await database.look_at_thing_here(ALICE, GUILD_A, "EN", "bottle")
    assert found.count == 1


async def test_a_fixture_is_visible_without_being_stock(house):
    """One fireplace, not a count of fireplaces - fixtures never enter
    room_contents, so they are found through thing_types.room_id instead."""
    await content_loader.load_content(
        a_house(a_thing("fireplace", type="fixture", takeable=False))
    )

    found = await database.look_at_thing_here(ALICE, GUILD_A, "EN", "fireplace")
    assert found.count == 1


async def test_a_source_is_visible_the_same_way(house):
    await content_loader.load_content(
        a_house(
            a_thing("stash", type="source", yields="can"),
            a_thing("can", room_id=None, quantity=0),
        )
    )

    assert await database.look_at_thing_here(ALICE, GUILD_A, "EN", "stash") is not None


async def test_an_exit_can_be_looked_at(house):
    await content_loader.load_content(
        a_house(a_thing("door", type="exit", destination_room_id="KI", takeable=False))
    )
    assert await database.look_at_thing_here(ALICE, GUILD_A, "EN", "door") is not None


async def test_an_emptied_object_is_gone_from_the_room(house):
    """Count zero is not "there are none" - it is not there at all."""
    await content_loader.load_content(a_house(a_thing("chips")))
    async with house._require_session()() as session:
        await session.execute(
            database.RoomContents.__table__.update().values(count=0)
        )
        await session.commit()

    assert await database.look_at_thing_here(ALICE, GUILD_A, "EN", "chips") is None


async def test_a_thing_with_no_look_text_still_reports_it_exists(house):
    await content_loader.load_content(
        a_house(
            a_thing("spoon"),
            thing_text=[
                TextRow(entity_id="spoon", state="default", since_drop=1, text={"use": "Stir."})
            ],
        )
    )

    found = await database.look_at_thing_here(ALICE, GUILD_A, "EN", "spoon")
    assert found is not None
    assert found.description is None


# --------------------------------------------------------------------------
# /inventory
# --------------------------------------------------------------------------


async def test_a_new_player_carries_nothing(house):
    await content_loader.load_content(a_house(a_thing("spoon")))

    assert await database.get_carried(ALICE, GUILD_A) == []
    assert await database.carried_count(ALICE, GUILD_A) == 0


async def test_the_inventory_lists_names_and_counts(house):
    await content_loader.load_content(
        a_house(a_thing("spoon", name="silver spoon"), a_thing("can", name="tin of beans"))
    )
    await carry(house, ALICE, GUILD_A, "spoon", count=1)
    await carry(house, ALICE, GUILD_A, "can", count=3)

    assert await database.get_carried(ALICE, GUILD_A) == [
        ("silver spoon", 1),
        ("tin of beans", 3),
    ]
    assert await database.carried_count(ALICE, GUILD_A) == 4


async def test_the_inventory_is_alphabetical(house):
    await content_loader.load_content(
        a_house(
            a_thing("c", name="torch"), a_thing("a", name="apple"), a_thing("b", name="candle")
        )
    )
    for thing_id in ("a", "b", "c"):
        await carry(house, ALICE, GUILD_A, thing_id)

    assert [name for name, _ in await database.get_carried(ALICE, GUILD_A)] == [
        "apple",
        "candle",
        "torch",
    ]


async def test_a_zero_count_is_not_listed(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    await carry(house, ALICE, GUILD_A, "spoon", count=0)

    assert await database.get_carried(ALICE, GUILD_A) == []


async def test_one_players_bag_is_not_anothers(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    await carry(house, ALICE, GUILD_A, "spoon")

    assert await database.get_carried(BOB, GUILD_A) == []


async def test_inventories_are_per_server(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(ALICE, GUILD_B)
    await content_loader.load_content(a_house(a_thing("spoon")))
    await carry(db, ALICE, GUILD_A, "spoon")

    assert len(await database.get_carried(ALICE, GUILD_A)) == 1
    assert await database.get_carried(ALICE, GUILD_B) == []


async def test_every_exit_is_named_in_its_room_prose(db):
    """The only way a player learns a door exists.

    `/look` prints the room's description and the `Also here:` line, and
    `Also here:` holds loose takeable objects - never exits. So an exit that
    the prose does not mention is an exit nobody can find, in exactly the way
    an unmentioned source is a source nobody can find.

    This became load-bearing in 2e, which settled that discovery stays in the
    prose rather than adding an exit list. Before that the rule was implicit
    and nothing checked it.
    """
    parsed = content_module.load_files()
    prose = {
        (row.entity_id, row.state): (row.text.get("look") or "").lower()
        for row in parsed.room_text
    }

    unmentioned = []
    for thing in parsed.things:
        if thing.type != "exit" or not thing.room_id:
            continue
        here = prose.get((thing.room_id, "default"), "")
        if not any(name.lower() in here for name in (thing.name, *thing.aliases) if name):
            unmentioned.append(f"{thing.thing_id} ({thing.name}) in {thing.room_id}")

    assert unmentioned == [], unmentioned
