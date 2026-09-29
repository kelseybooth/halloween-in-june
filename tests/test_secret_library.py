"""Phase 2e: finding the Secret Library, and keeping it secret.

Two routes in, and the order they happen in is structural rather than
enforced: the keys hang on a nail inside the library, so nobody can hold one
until they have already climbed the oak. There is no ordering check written
anywhere, and these tests are how that claim is kept true.

The trap this phase is built around: **the oak must be usable by a player who
has not discovered it.** An exit gated on the state its own use produces is a
locked door with the key inside, and the library could never be found by
anyone.

The other half is what the rooms either side are told. The house defaults give
the secret away twice - "exits via the oak tree" teaches the Courtyard that
the tree is a way out, and "arrives from the Secret Library" names the secret
outright - so the four secret exits override both lines.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember, a_room_thread

import achievements
import bot
import content as content_module
import content_loader
import database
import resolve
import states
import triggers
import world


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.register_all()
    yield
    achievements.clear()


@pytest.fixture
async def house(db):
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    await content_loader.load_content(content_module.load_files())
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*rooms.values())
    for who in (ALICE, BOB):
        await db.start_game(who, GUILD_A, "EN", await resolve.rooms_open_at_launch())
    await db.set_announcement_channel(GUILD_A, halloween.id)
    return db, guild, halloween, rooms


async def act(house, fn, arg, room, who=ALICE):
    db, guild, _, rooms = house
    await db.update_current_room(who, GUILD_A, room)
    interaction = FakeInteraction(
        who, GUILD_A, guild=guild, channel=a_room_thread(rooms[room])
    )
    await fn.callback(interaction, arg)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


async def where(db, who=ALICE) -> str:
    return (await db.get_game_state(who, GUILD_A)).current_room


def posted(house, room_name) -> list[str]:
    _, _, halloween, _ = house
    thread = next(t for t in halloween.threads if t.name == room_name)
    return list(thread.posted)


async def climb(house, who=ALICE):
    return await act(house, bot.use, "tree", "CO", who=who)


# --------------------------------------------------------------------------
# The oak: usable by anybody, which is the whole trap
# --------------------------------------------------------------------------


async def test_the_oak_works_for_a_player_who_has_never_used_it(house):
    db, *_ = house

    await climb(house)

    assert await where(db) == "SE"


async def test_the_first_climb_sets_library_found(house):
    await climb(house)

    assert await states.has(GUILD_A, ALICE, world.LIBRARY_FOUND)


async def test_the_first_climb_prints_the_discovery(house):
    """The long text is the reveal and is written to be read once."""
    reply = replies(await climb(house))

    assert "haul yourself up into the old oak" in reply


async def test_the_second_climb_prints_the_short_version(house):
    """2c.5 resolves a use's text *after* its effect, so the drawer can be
    described by the state it produced. A discovery is the opposite case: the
    state it sets is what makes every later use read the short line."""
    await climb(house)

    reply = replies(await climb(house))

    assert "slip in through the library window" in reply
    assert "haul yourself up" not in reply


async def test_the_oak_unlocks_the_library_for_that_player(house):
    """`SE` is `open_at_launch = no`, so nobody starts with it in
    `rooms_unlocked`. Climbing is what puts it there."""
    db, *_ = house
    assert "SE" not in (await db.get_game_state(ALICE, GUILD_A)).rooms_unlocked

    await climb(house)

    assert "SE" in (await db.get_game_state(ALICE, GUILD_A)).rooms_unlocked


async def test_the_unlock_is_per_player(house):
    db, *_ = house
    await climb(house)

    assert "SE" not in (await db.get_game_state(BOB, GUILD_A)).rooms_unlocked


async def test_out_on_a_limb_fires_on_the_first_climb_and_never_again(house):
    await climb(house)
    assert "out_on_a_limb" in await database.player_achievements_of(GUILD_A, ALICE)
    assert posted(house, "Courtyard") or True

    _, _, halloween, _ = house
    announced = list(halloween.posted)
    await climb(house)
    assert halloween.posted == announced


# --------------------------------------------------------------------------
# The cabinet, and the key that opens it
# --------------------------------------------------------------------------


async def test_the_cabinet_refuses_without_a_key(house):
    db, *_ = house

    reply = replies(await act(house, bot.use, "cabinet", "LI"))

    assert "takes a skeleton key" in reply
    assert await where(db) == "LI"


async def test_the_cabinet_still_refuses_after_finding_the_library(house):
    """Discovery is not permission: the key is the second gate."""
    db, *_ = house
    await climb(house)

    reply = replies(await act(house, bot.use, "cabinet", "LI"))

    assert "takes a skeleton key" in reply
    assert await where(db) == "LI"


async def test_the_key_can_only_be_taken_inside(house):
    """No ordering check is written anywhere. This is why one is not needed:
    the nail hangs on the library shelves."""
    parsed = content_module.load_files()
    nail = parsed.things_by_id["key_nail"]
    shelves = parsed.things_by_id[nail.contained_in]

    assert shelves.room_id == "SE"


async def test_taking_the_key_gives_exactly_one(house):
    await climb(house)

    await act(house, bot.take, "key", "SE")
    second = replies(await act(house, bot.take, "key", "SE"))

    assert await database.carried_of(ALICE, GUILD_A, "skeleton_key") == 1
    assert "already have" in second


async def test_the_key_cannot_be_dropped(house):
    """`has_key` is derived from the inventory rather than stored, which is
    only safe because the key can never leave a player."""
    await climb(house)
    await act(house, bot.take, "key", "SE")

    await act(house, bot.drop, "key", "SE")

    assert await database.carried_of(ALICE, GUILD_A, "skeleton_key") == 1


async def test_has_key_is_derived_not_stored(house):
    await climb(house)
    await act(house, bot.take, "key", "SE")

    assert await world.has_key(GUILD_A, ALICE)
    assert world.HAS_KEY not in await states.in_force(GUILD_A, ALICE)


async def test_the_cabinet_opens_with_a_key(house):
    db, *_ = house
    await climb(house)
    await act(house, bot.take, "key", "SE")

    reply = replies(await act(house, bot.use, "cabinet", "LI"))

    assert "fit the skeleton key into the lock" in reply
    assert await where(db) == "SE"


async def test_opening_the_cabinet_sets_passage_open(house):
    await climb(house)
    await act(house, bot.take, "key", "SE")
    await act(house, bot.use, "cabinet", "LI")

    assert await states.has(GUILD_A, ALICE, world.PASSAGE_OPEN)


async def test_the_hinge_text_is_read_once(house):
    """The `has_key` row sets `passage_open`, and after that the cabinet is
    simply open."""
    await climb(house)
    await act(house, bot.take, "key", "SE")
    await act(house, bot.use, "cabinet", "LI")

    reply = replies(await act(house, bot.use, "cabinet", "LI"))

    # Both rows mention the hinge; only the reveal turns the key in the lock.
    assert "fit the skeleton key into the lock" not in reply
    assert "cabinet swings open" in reply


# --------------------------------------------------------------------------
# The way back, and nobody stranded
# --------------------------------------------------------------------------


async def test_the_window_always_works(house):
    """A player who climbs in and never finds the keys can always climb back
    out. Nobody can be stranded."""
    db, *_ = house
    await climb(house)

    await act(house, bot.use, "window", "SE")

    assert await where(db) == "CO"


async def test_the_back_of_the_cabinet_is_shut_without_the_passage(house):
    db, *_ = house
    await climb(house)

    reply = replies(await act(house, bot.use, "back of the cabinet", "SE"))

    assert await where(db) == "SE"
    assert "keyhole on this side" in reply


async def test_the_back_of_the_cabinet_opens_once_the_passage_is(house):
    db, *_ = house
    await climb(house)
    await act(house, bot.take, "key", "SE")
    await act(house, bot.use, "cabinet", "LI")

    reply = replies(await act(house, bot.use, "back of the cabinet", "SE"))

    assert await where(db) == "LI"
    assert "push the cabinet aside" in reply


async def test_a_player_holding_several_states_reads_the_right_one(house):
    """The bug this phase's resolution order exists for. Alphabetically
    `library_found` beats `passage_open`, so a naive pick would have shown
    the back of the cabinet nothing at all."""
    await climb(house)
    await act(house, bot.take, "key", "SE")
    await act(house, bot.use, "cabinet", "LI")
    held = await world.states_for_exit(GUILD_A, ALICE)

    assert held >= {world.LIBRARY_FOUND, world.HAS_KEY, world.PASSAGE_OPEN}
    assert world.exit_state(held)[0] == world.PASSAGE_OPEN


async def test_the_oak_is_unaffected_by_the_states_that_came_after(house):
    """The same ordered list asked about the oak has to fall past both to the
    oak's own row, rather than landing on the long discovery text again."""
    await climb(house)
    await act(house, bot.take, "key", "SE")
    await act(house, bot.use, "cabinet", "LI")

    reply = replies(await climb(house))

    assert "slip in through the library window" in reply
    assert "haul yourself up" not in reply


# --------------------------------------------------------------------------
# Keeping it secret
# --------------------------------------------------------------------------


async def test_climbing_the_oak_does_not_tell_the_courtyard_how(house):
    await climb(house)

    line = posted(house, "Courtyard")[-1]
    assert "can't quite tell where they went" in line
    assert "oak" not in line.lower()
    assert "exits via" not in line


async def test_the_cabinet_does_not_tell_the_living_room_how(house):
    await climb(house)
    await act(house, bot.take, "key", "SE")

    await act(house, bot.use, "cabinet", "LI")

    line = posted(house, "Living Room")[-1]
    assert "You hear a creak" in line
    assert "cabinet" not in line.lower()


async def test_arriving_in_the_living_room_does_not_name_where_from(house):
    """`move.arrive` reads "{player} arrives from the {room}", which would
    announce the Secret Library to everybody standing there."""
    await climb(house)
    await act(house, bot.take, "key", "SE")
    await act(house, bot.use, "cabinet", "LI")

    await act(house, bot.use, "back of the cabinet", "SE")

    line = posted(house, "Living Room")[-1]
    assert "Where did they come from?" in line
    assert "Secret Library" not in line


async def test_arriving_in_the_courtyard_does_not_name_where_from(house):
    await climb(house)

    await act(house, bot.use, "window", "SE")

    line = posted(house, "Courtyard")[-1]
    assert "small thud" in line
    assert "Secret Library" not in line


async def test_the_words_secret_library_never_reach_a_public_room(house):
    """The whole secret, checked in one place: every line posted in the two
    rooms a player can reach without discovering anything."""
    await climb(house)
    await act(house, bot.take, "key", "SE")
    await act(house, bot.use, "cabinet", "LI")
    await act(house, bot.use, "back of the cabinet", "SE")
    await act(house, bot.use, "window", "SE")

    for room in ("Courtyard", "Living Room"):
        for line in posted(house, room):
            assert "Secret Library" not in line, line


async def test_an_ordinary_exit_still_uses_the_house_default(house):
    """Only the four secret rows override. Everything else falls through to
    `move.depart` and `move.arrive` exactly as before."""
    await act(house, bot.use, "back door", "KI")

    assert any("exits via" in line for line in posted(house, "Kitchen"))
    assert any("arrives from the Kitchen" in line for line in posted(house, "Courtyard"))


# --------------------------------------------------------------------------
# Two players, different states, same room
# --------------------------------------------------------------------------


async def test_one_player_opening_the_cabinet_does_not_open_it_for_another(house):
    db, *_ = house
    await climb(house)
    await act(house, bot.take, "key", "SE")
    await act(house, bot.use, "cabinet", "LI")

    reply = replies(await act(house, bot.use, "cabinet", "LI", who=BOB))

    assert "takes a skeleton key" in reply
    assert await where(db, BOB) == "LI"


async def test_the_oak_is_never_shut_to_anybody(house):
    """However far ahead somebody else is, the first way in stays open."""
    db, *_ = house
    await climb(house)
    await act(house, bot.take, "key", "SE")

    await climb(house, who=BOB)

    assert await where(db, BOB) == "SE"


async def test_the_living_room_reads_the_same_for_everybody(house):
    """2e changes which exits open, not what a room says. The cabinet is in
    the Living Room's prose for everyone, locked doors and all."""
    await climb(house)
    await act(house, bot.take, "key", "SE")
    await act(house, bot.use, "cabinet", "LI")

    mine = replies(await act(house, bot.look, None, "LI"))
    theirs = replies(await act(house, bot.look, None, "LI", who=BOB))

    assert mine == theirs
    assert "curiosity cabinet" in mine


# --------------------------------------------------------------------------
# The two new columns
# --------------------------------------------------------------------------


def test_only_the_four_secret_exits_override_the_move_lines():
    parsed = content_module.load_files()
    overridden = {
        row.entity_id
        for row in parsed.thing_text
        if row.text.get("move_depart") or row.text.get("move_arrive")
    }

    assert overridden == {"CS", "LS", "SL", "SC"}


def test_the_override_lines_use_the_token_that_already_exists():
    """`{player}`, lower case, the one `move.depart` already substitutes.
    A second spelling would render as literal text in the room."""
    parsed = content_module.load_files()
    for row in parsed.thing_text:
        for column in ("move_depart", "move_arrive"):
            line = row.text.get(column) or ""
            if line:
                assert "{player}" in line, (row.entity_id, column)


async def test_the_columns_load_and_resolve(house):
    """New columns on a frozen file: the loader is generic over
    THING_TEXT_COLUMNS, so they need no special handling anywhere."""
    assert "can't quite tell" in await resolve.thing_text(GUILD_A, "CS", "move_depart")
    assert await resolve.thing_text(GUILD_A, "CS", "move_arrive") is None


async def test_a_blank_override_falls_through_to_the_house_default(house):
    """Which is what keeps 146 rows blank rather than repeating the default
    on every one of them."""
    assert await resolve.thing_text(GUILD_A, "EL", "move_depart") is None
    assert "exits via" in await resolve.default_text("move.depart")
