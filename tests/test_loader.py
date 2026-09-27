"""Putting content into a database, and the reload rules that protect a live game.

The load path is easy. The reload path is the part that runs against a server
with players mid-game, and every rule it follows exists because the obvious
behaviour would destroy something: re-placing stock would undo every `/take`,
dropping a thing quietly would leave inventories pointing at nothing, and
wiping world state without being asked would end everyone's game.
"""

from dataclasses import replace

import pytest
from sqlalchemy import func, select

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import content as content_module
import content_loader
import database
from content import Content, Drop, Restock, Room, TextRow, Thing


# --------------------------------------------------------------------------
# Building small worlds to load
# --------------------------------------------------------------------------


def a_thing(thing_id, **overrides):
    defaults = dict(
        thing_id=thing_id,
        name=thing_id.replace("_", " "),
        aliases=(),
        type="object",
        room_id="EN",
        quantity=1,
        takeable=True,
        droppable=True,
        cross_weight=0,
        max_per_player=None,
        requires=None,
        present_when=None,
        transforms_to=None,
        transform_room=None,
        yields=None,
        destination_room_id=None,
        contained_in=None,
        use_cooldown_hours=None,
        since_drop=1,
        sort_order=0,
    )
    return Thing(**{**defaults, **overrides})


def a_world(*things, rooms=("EN", "KI")) -> Content:
    """A minimal, internally consistent Content for the loader to chew on."""
    parsed = Content()
    parsed.rooms = [
        Room(room_id=r, name=r, sort_order=i, open_at_launch=True)
        for i, r in enumerate(rooms)
    ]
    parsed.room_text = [
        TextRow(entity_id=r, state="default", since_drop=1, text={"look": f"The {r}."})
        for r in rooms
    ]
    parsed.things = list(things)
    parsed.thing_text = [
        TextRow(entity_id=t.thing_id, state="default", since_drop=1, text={"look": "A thing."})
        for t in things
    ]
    parsed.defaults = {"take.default": "You take the {name}."}
    parsed.drops = [
        Drop(
            drop_id=1,
            trigger="date",
            date="launch",
            event=None,
            name="Launch",
            notes=None,
        )
    ]
    return parsed


async def contents(db, guild_id):
    async with db._require_session()() as session:
        rows = await session.execute(
            select(
                database.RoomContents.room_id,
                database.RoomContents.container_id,
                database.RoomContents.thing_id,
                database.RoomContents.count,
            )
            .where(database.RoomContents.guild_id == guild_id)
            .order_by(database.RoomContents.thing_id)
        )
        return [tuple(r) for r in rows]


async def row_count(db, table):
    async with db._require_session()() as session:
        return await session.scalar(
            select(func.count()).select_from(database.Base.metadata.tables[table])
        )


@pytest.fixture
async def two_servers(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(BOB, GUILD_B)
    return db


# --------------------------------------------------------------------------
# The first load
# --------------------------------------------------------------------------


async def test_content_tables_are_populated(two_servers):
    report = await content_loader.load_content(a_world(a_thing("spoon")))

    assert report.content_rows["thing_types"] == 1
    assert report.content_rows["room_types"] == 2
    assert await row_count(two_servers, "thing_types") == 1


async def test_finite_things_are_placed_in_every_server(two_servers):
    await content_loader.load_content(a_world(a_thing("spoon"), a_thing("mug", room_id="KI")))

    assert await contents(two_servers, GUILD_A) == [
        ("KI", "", "mug", 1),
        ("EN", "", "spoon", 1),
    ]
    assert await contents(two_servers, GUILD_B) == await contents(two_servers, GUILD_A)


async def test_a_contained_thing_is_placed_inside_its_container(two_servers):
    world = a_world(
        a_thing("box", type="fixture", takeable=False, quantity=1),
        a_thing("jar", contained_in="box"),
    )
    await content_loader.load_content(world)

    assert ("EN", "box", "jar", 1) in await contents(two_servers, GUILD_A)


async def test_quantity_above_one_is_a_count_not_rows(two_servers):
    await content_loader.load_content(a_world(a_thing("bottle", quantity=5)))
    assert await contents(two_servers, GUILD_A) == [("EN", "", "bottle", 5)]


@pytest.mark.parametrize(
    "kind, extra",
    [
        ("source", {"yields": "spoon"}),
        ("fixture", {}),
        ("exit", {"destination_room_id": "KI"}),
    ],
)
async def test_only_objects_are_placed(two_servers, kind, extra):
    """A source is inexhaustible, a fixture is scenery, an exit is a door. None
    of them move, so none of them are stock."""
    world = a_world(a_thing("spoon"), a_thing("other", type=kind, **extra))
    await content_loader.load_content(world)

    placed = {row[2] for row in await contents(two_servers, GUILD_A)}
    assert placed == {"spoon"}


async def test_a_roomless_thing_starts_nowhere(two_servers):
    """It arrives when a source yields it, a transform makes it, or a restock
    scatters it - never at load."""
    world = a_world(
        a_thing("stash", type="source", yields="can"),
        a_thing("can", room_id=None, quantity=0),
    )
    await content_loader.load_content(world)

    assert await contents(two_servers, GUILD_A) == []


async def test_a_server_with_no_players_yet_gets_nothing(db):
    report = await content_loader.load_content(a_world(a_thing("spoon")))
    assert report.guilds == []
    assert report.placed == 0


async def test_only_the_named_guilds_are_placed_for(two_servers):
    await content_loader.load_content(a_world(a_thing("spoon")), guild_ids=[GUILD_A])

    assert len(await contents(two_servers, GUILD_A)) == 1
    assert await contents(two_servers, GUILD_B) == []


# --------------------------------------------------------------------------
# Reloading
# --------------------------------------------------------------------------


async def test_a_second_load_places_nothing_new(two_servers):
    world = a_world(a_thing("spoon"))
    await content_loader.load_content(world)
    report = await content_loader.load_content(world)

    assert report.placed == 0
    assert report.already_present == 2  # one per server
    assert len(await contents(two_servers, GUILD_A)) == 1


async def test_a_taken_thing_does_not_come_back(two_servers):
    """The rule the whole reload path exists for."""
    world = a_world(a_thing("chips"))
    await content_loader.load_content(world)

    # A player takes the only packet: the room row empties, their bag fills.
    async with two_servers._require_session()() as session:
        await session.execute(
            database.RoomContents.__table__.update()
            .where(database.RoomContents.guild_id == GUILD_A)
            .values(count=0)
        )
        session.add(
            database.PlayerInventory(
                guild_id=GUILD_A, user_id=ALICE, thing_id="chips", count=1
            )
        )
        await session.commit()

    await content_loader.load_content(world)

    assert await contents(two_servers, GUILD_A) == [("EN", "", "chips", 0)]


async def test_a_thing_added_later_reaches_a_running_server(two_servers):
    """Placement is judged per thing, not per server, so new content arrives."""
    await content_loader.load_content(a_world(a_thing("spoon")))
    report = await content_loader.load_content(a_world(a_thing("spoon"), a_thing("mug")))

    assert report.placed == 2  # the mug, in both servers
    assert {row[2] for row in await contents(two_servers, GUILD_A)} == {"spoon", "mug"}


async def test_a_thing_a_player_moved_is_left_where_they_left_it(two_servers):
    await content_loader.load_content(a_world(a_thing("spoon")))
    async with two_servers._require_session()() as session:
        await session.execute(
            database.RoomContents.__table__.update()
            .where(database.RoomContents.guild_id == GUILD_A)
            .values(room_id="KI")
        )
        await session.commit()

    await content_loader.load_content(a_world(a_thing("spoon")))

    assert await contents(two_servers, GUILD_A) == [("KI", "", "spoon", 1)]


async def test_content_tables_are_replaced_not_appended(two_servers):
    """The mug is roomless, so removing it orphans nothing and the guard stays
    out of the way - what is under test here is the replace, not the refusal."""
    unplaced = a_thing("mug", room_id=None, quantity=0)
    await content_loader.load_content(a_world(a_thing("spoon"), unplaced))
    await content_loader.load_content(a_world(a_thing("spoon")))

    assert await row_count(two_servers, "thing_types") == 1


async def test_edited_text_is_replaced_wholesale(two_servers):
    world = a_world(a_thing("spoon"))
    await content_loader.load_content(world)

    rewritten = a_world(a_thing("spoon"))
    rewritten.thing_text = [
        TextRow(entity_id="spoon", state="default", since_drop=1, text={"look": "Rewritten."})
    ]
    await content_loader.load_content(rewritten)

    async with two_servers._require_session()() as session:
        look = await session.scalar(
            select(database.ThingText.look).where(database.ThingText.thing_id == "spoon")
        )
    assert look == "Rewritten."


# --------------------------------------------------------------------------
# Orphans
# --------------------------------------------------------------------------


async def test_dropping_a_thing_a_player_holds_aborts_the_load(two_servers):
    await content_loader.load_content(a_world(a_thing("spoon"), a_thing("relic")))
    async with two_servers._require_session()() as session:
        session.add(
            database.PlayerInventory(
                guild_id=GUILD_A, user_id=ALICE, thing_id="relic", count=1
            )
        )
        await session.commit()

    with pytest.raises(content_loader.OrphanedThings) as caught:
        await content_loader.load_content(a_world(a_thing("spoon")))

    assert "relic" in str(caught.value)
    assert str(ALICE) in str(caught.value)


async def test_an_aborted_load_changes_nothing(two_servers):
    """All or nothing: a refused load must not have half-replaced the content."""
    await content_loader.load_content(a_world(a_thing("spoon"), a_thing("relic")))
    async with two_servers._require_session()() as session:
        session.add(
            database.PlayerInventory(
                guild_id=GUILD_A, user_id=ALICE, thing_id="relic", count=1
            )
        )
        await session.commit()

    with pytest.raises(content_loader.OrphanedThings):
        await content_loader.load_content(a_world(a_thing("spoon")))

    assert await row_count(two_servers, "thing_types") == 2


async def test_dropping_a_thing_still_sitting_in_a_room_aborts_too(two_servers):
    await content_loader.load_content(a_world(a_thing("spoon"), a_thing("relic")))

    with pytest.raises(content_loader.OrphanedThings) as caught:
        await content_loader.load_content(a_world(a_thing("spoon")))

    assert "relic" in str(caught.value)


async def test_the_abort_names_every_holder(two_servers):
    await content_loader.load_content(a_world(a_thing("relic", room_id=None, quantity=0)))
    async with two_servers._require_session()() as session:
        session.add_all(
            [
                database.PlayerInventory(
                    guild_id=GUILD_A, user_id=ALICE, thing_id="relic", count=1
                ),
                database.PlayerInventory(
                    guild_id=GUILD_B, user_id=BOB, thing_id="relic", count=2
                ),
            ]
        )
        await session.commit()

    with pytest.raises(content_loader.OrphanedThings) as caught:
        await content_loader.load_content(a_world(a_thing("spoon")))

    message = str(caught.value)
    assert str(ALICE) in message and str(BOB) in message


async def test_allow_orphans_loads_anyway_and_says_so(two_servers):
    await content_loader.load_content(a_world(a_thing("spoon"), a_thing("relic")))

    report = await content_loader.load_content(a_world(a_thing("spoon")), allow_orphans=True)

    assert report.orphans_ignored == ["relic"]
    assert await row_count(two_servers, "thing_types") == 1


async def test_a_thing_nobody_has_can_be_dropped_freely(two_servers):
    """An orphan is only an orphan if world state still points at it."""
    await content_loader.load_content(a_world(a_thing("spoon"), a_thing("ghost", quantity=0, room_id=None)))
    report = await content_loader.load_content(a_world(a_thing("spoon")))

    assert report.orphans_ignored == []


# --------------------------------------------------------------------------
# --fresh
# --------------------------------------------------------------------------


async def test_fresh_wipes_world_state_and_places_again(two_servers):
    world = a_world(a_thing("chips"))
    await content_loader.load_content(world)
    async with two_servers._require_session()() as session:
        await session.execute(
            database.RoomContents.__table__.update().values(count=0, room_id="KI")
        )
        session.add(
            database.PlayerInventory(
                guild_id=GUILD_A, user_id=ALICE, thing_id="chips", count=1
            )
        )
        await session.commit()

    report = await content_loader.load_content(world, fresh=True)

    assert report.fresh is True
    assert await contents(two_servers, GUILD_A) == [("EN", "", "chips", 1)]
    assert await row_count(two_servers, "player_inventory") == 0


async def test_fresh_ignores_orphans_rather_than_aborting(two_servers):
    """Nothing survives the wipe, so nothing can be orphaned by it."""
    await content_loader.load_content(a_world(a_thing("spoon"), a_thing("relic")))
    async with two_servers._require_session()() as session:
        session.add(
            database.PlayerInventory(
                guild_id=GUILD_A, user_id=ALICE, thing_id="relic", count=1
            )
        )
        await session.commit()

    report = await content_loader.load_content(a_world(a_thing("spoon")), fresh=True)
    assert report.orphans_ignored == []


async def test_fresh_clears_states_and_config_too(two_servers):
    async with two_servers._require_session()() as session:
        session.add_all(
            [
                database.PlayerState(guild_id=GUILD_A, user_id=ALICE, state="has_key"),
                database.ServerState(guild_id=GUILD_A, state="stairs_repaired"),
                database.ServerConfig(guild_id=GUILD_A, key="planks_required", value="10"),
            ]
        )
        await session.commit()

    await content_loader.load_content(a_world(a_thing("spoon")), fresh=True)

    for table in ("player_states", "server_states", "server_config"):
        assert await row_count(two_servers, table) == 0


async def test_fresh_leaves_players_in_the_house(two_servers):
    """Wiping the world is not the same as evicting everyone from it."""
    await two_servers.start_game(ALICE, GUILD_A, "Entryway", [])
    await content_loader.load_content(a_world(a_thing("spoon")), fresh=True)

    assert await two_servers.get_game_state(ALICE, GUILD_A) is not None


# --------------------------------------------------------------------------
# Refusing bad content
# --------------------------------------------------------------------------


async def test_a_bad_file_is_refused_before_anything_is_written(two_servers, tmp_path, monkeypatch):
    """load_content validates when it reads the files itself, and a failure has
    to leave the database exactly as it was."""
    await content_loader.load_content(a_world(a_thing("spoon")))

    monkeypatch.setattr(
        content_module,
        "load_files",
        lambda directory=None: a_world(a_thing("spoon"), a_thing("mug", room_id="NOWHERE")),
    )

    with pytest.raises(content_module.ContentError) as caught:
        await content_loader.load_content()

    assert "unknown room" in str(caught.value)
    assert await row_count(two_servers, "thing_types") == 1


# --------------------------------------------------------------------------
# The content we actually ship
# --------------------------------------------------------------------------


async def test_the_shipped_content_loads(two_servers):
    """Parsed rather than validated, because two sources are still unnamed in
    prose - see test_content.py. Everything else about the load is real."""
    parsed = content_module.load_files()
    report = await content_loader.load_content(parsed)

    assert report.content_rows["room_types"] == 9
    assert report.content_rows["thing_types"] == 140
    assert report.content_rows["drops"] == 1
    assert report.content_rows["restocks"] == 3


async def test_the_shipped_content_places_six_things_per_server(two_servers):
    """The work order's count: six physical copies across six things."""
    parsed = content_module.load_files()
    await content_loader.load_content(parsed)

    placed = await contents(two_servers, GUILD_A)
    assert len(placed) == 6
    assert sum(row[3] for row in placed) == 6


async def test_the_shipped_content_respects_containment(two_servers):
    parsed = content_module.load_files()
    await content_loader.load_content(parsed)

    by_thing = {row[2]: row for row in await contents(two_servers, GUILD_A)}
    assert by_thing["cat_food_gourmet"][1] == "bed"
    assert by_thing["reading_glasses"][1] == "rolltop_desk"


# --------------------------------------------------------------------------
# Loading at startup
#
# Railway has no shell, so the bot loads content itself on boot. The rule that
# matters is what it does when the files are bad: it keeps serving whatever the
# last good load left in the database, rather than refusing to start. A writer's
# typo should cost the new text, not the whole game.
# --------------------------------------------------------------------------


async def test_startup_loads_the_content(two_servers, monkeypatch):
    import bot

    monkeypatch.setattr(content_module, "load", lambda directory=None: a_world(a_thing("spoon")))
    await bot.load_content_at_startup()

    assert await row_count(two_servers, "thing_types") == 1


async def test_bad_files_leave_the_previous_content_in_place(two_servers, monkeypatch, caplog):
    import bot

    await content_loader.load_content(a_world(a_thing("spoon")))

    def explode(directory=None):
        raise content_module.ContentError(["everything is wrong"])

    monkeypatch.setattr(content_module, "load", explode)
    with caplog.at_level("ERROR"):
        await bot.load_content_at_startup()

    assert await row_count(two_servers, "thing_types") == 1
    assert "load_content.py --check" in caplog.text


async def test_bad_files_do_not_raise(two_servers, monkeypatch):
    """Whatever else happens, setup_hook must finish and the bot must connect."""
    import bot

    def explode(directory=None):
        raise content_module.ContentError(["everything is wrong"])

    monkeypatch.setattr(content_module, "load", explode)
    await bot.load_content_at_startup()  # must not raise


async def test_startup_tolerates_orphans_but_says_so(two_servers, monkeypatch, caplog):
    """Refusing here would let a removed thing take the bot down on restart."""
    import bot

    await content_loader.load_content(a_world(a_thing("spoon"), a_thing("relic")))
    async with two_servers._require_session()() as session:
        session.add(
            database.PlayerInventory(
                guild_id=GUILD_A, user_id=ALICE, thing_id="relic", count=1
            )
        )
        await session.commit()

    monkeypatch.setattr(content_module, "load", lambda directory=None: a_world(a_thing("spoon")))
    with caplog.at_level("WARNING"):
        await bot.load_content_at_startup()

    assert "relic" in caplog.text
    assert await row_count(two_servers, "thing_types") == 1


async def test_startup_never_wipes_world_state(two_servers, monkeypatch):
    """--fresh is a deliberate act at a keyboard, never something a restart does."""
    import bot

    await content_loader.load_content(a_world(a_thing("chips")))
    async with two_servers._require_session()() as session:
        session.add(
            database.PlayerInventory(
                guild_id=GUILD_A, user_id=ALICE, thing_id="chips", count=1
            )
        )
        await session.commit()

    monkeypatch.setattr(content_module, "load", lambda directory=None: a_world(a_thing("chips")))
    await bot.load_content_at_startup()

    assert await row_count(two_servers, "player_inventory") == 1
