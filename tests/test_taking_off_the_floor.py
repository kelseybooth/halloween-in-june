"""A take out of a source and a take off the floor are different sentences.

Until now the only axes a `take` could be written on were the thing, a
state, and the room, and none of them can tell those two apart. So a
twist of graphite powder somebody had left on the ground was picked up
with *"{player} folds a spoonful of the powder into a twist of paper and
pockets it"* - a sentence about the tin, which was nowhere near it.

**Two halves, and they fix two things written opposite ways round.**

The burrito's general line is the floor one and its `in:KI` row is the
freezer's: *"works one loose from the stack."* Inside the Kitchen the
room won, so a burrito somebody dropped by the fridge also came away
with a crack. That is the bug the take handler used to describe in a
comment and leave. A copy off the floor came out of nothing, so the room
no longer decides its line and the writers' general one is read.

The powder is the other way up: its own `take` row *is* the source's, so
dropping the room would not have helped. `from:floor` goes in front of
the order, and content can say what being picked up off the ground is
like.

So the burrito needed no new cell and the powder needed exactly one.
"""

import pytest
from types import SimpleNamespace

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import resolve
import states
import world


THIS_DROP = 40

# Quoted off `thing_text.tsv`. Each phrase appears in one row and no other.
FROM_THE_TIN = "folds a spoonful of the powder"
OFF_THE_FLOOR = "carefully picks up a twist of paper"
FROM_THE_STACK = "works one loose from the stack"
ABANDONED = "somebody abandoned here"


@pytest.fixture
async def house(db, monkeypatch):
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    await db.set_setting(GUILD_A, resolve.DROP_KEY, THIS_DROP)
    await content_loader.load_content(content_module.load_files(), guild_ids=[GUILD_A])
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    await states.set_server_state(GUILD_A, world.STAIRS_UPPER)
    await states.set_server_state(GUILD_A, world.STAIRS_REPAIRED)
    for who in (ALICE, BOB):
        await db.start_game(who, GUILD_A, "EN", await resolve.rooms_open_at_launch())
    monkeypatch.setattr(
        bot,
        "bot",
        SimpleNamespace(
            guilds=[guild], get_guild=lambda gid: guild if gid == GUILD_A else None
        ),
    )
    return db, guild, halloween, rooms


def place(house, room):
    _, _, halloween, rooms = house
    return next(t for t in halloween.threads if t.name == rooms[room])


async def run(house, command, arg, *, room, who=ALICE) -> str:
    db, guild, _, _ = house
    await db.update_current_room(who, GUILD_A, room)
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=place(house, room))
    await command.callback(interaction, arg)
    return "\n".join(text for text, _ in interaction.sent if text)


def posted(house, room) -> str:
    return "\n".join(place(house, room).posted)


async def take_then_drop(house, thing, *, room, who=ALICE):
    """Put a copy on the floor the way a player does, by dropping one."""
    await run(house, bot.take, thing, room=room, who=who)
    await run(house, bot.drop, thing, room=room, who=who)


# ---------------------------------------------------------------------------
# The powder, which needed a cell


async def test_out_of_the_tin_still_folds_a_spoonful(house):
    await run(house, bot.take, "graphite powder", room="BE")

    said = posted(house, "BE")

    assert FROM_THE_TIN in said
    assert OFF_THE_FLOOR not in said


async def test_but_off_the_floor_it_is_already_in_a_twist_of_paper(house):
    await take_then_drop(house, "graphite powder", room="BE")

    await run(house, bot.take, "graphite powder", room="BE")
    said = posted(house, "BE")

    assert OFF_THE_FLOOR in said
    assert said.count(FROM_THE_TIN) == 1  # the first take, not the second


async def test_and_the_floor_line_travels_with_the_copy(house):
    """It is about where the copy was, not which room the player is in.

    The tin is in the bedroom and nowhere else, so a twist of powder
    carried downstairs and dropped can only be picked up off the floor -
    and reads that way without any room having to be named.
    """
    await run(house, bot.take, "graphite powder", room="BE")
    await run(house, bot.drop, "graphite powder", room="LI")

    await run(house, bot.take, "graphite powder", room="LI")

    assert OFF_THE_FLOOR in posted(house, "LI")


# ---------------------------------------------------------------------------
# The burrito, which needed none


async def test_out_of_the_freezer_comes_away_with_a_crack(house):
    await run(house, bot.take, "burrito", room="KI")

    assert FROM_THE_STACK in posted(house, "KI")


async def test_but_one_dropped_by_the_fridge_was_abandoned_there(house):
    """The bug the handler used to describe in a comment and leave.

    Same room, same thing, same verb - and the only difference is that
    this copy was lying on the floor rather than in the freezer.
    """
    await take_then_drop(house, "burrito", room="KI")

    await run(house, bot.take, "burrito", room="KI")
    said = posted(house, "KI")

    assert ABANDONED in said
    assert said.count(FROM_THE_STACK) == 1  # the take that filled the floor


async def test_and_a_burrito_anywhere_else_reads_as_it_always_did(house):
    """Unchanged behaviour, which is most of the suite's interest here."""
    await run(house, bot.take, "burrito", room="KI")
    await run(house, bot.drop, "burrito", room="EN")

    await run(house, bot.take, "burrito", room="EN")

    assert ABANDONED in posted(house, "EN")


# ---------------------------------------------------------------------------
# What the change must not have touched


async def test_a_thing_with_no_floor_line_is_unchanged(house):
    """Which is everything else: two cells in the files are keyed this way.

    The cat collar is the cleanest case in the game - one `take` row, no
    room row, no origin row, and it starts lying loose in the bedroom,
    so picking it up *is* a floor take. Dropping the room from the order
    has nothing to fall past, and it reads exactly as it always did.

    **The line it reads changed on 6 November and this test did not.**
    The collar became something a player gives back rather than keeps,
    so "something worth keeping safe" - advice to keep it - was replaced
    by a hint that somebody is missing it. The subject here is that a
    thing with no floor line takes the same way it always has, which is
    about the row that is read and not about the words in it.
    """
    await run(house, bot.take, "collar", room="BE")

    assert "Somebody is probably missing this" in posted(house, "BE")


def test_only_the_burrito_keyed_a_take_on_its_room():
    """So dropping the room on a floor take costs nothing anywhere else.

    Every other `in:XX` row in the files fills `use` - the ladder's six
    climbs, the chips, the music box. If a second one ever fills `take`
    this test is where it says so, because the half of this change that
    needs no content is exactly the half that assumes this.
    """
    keyed = sorted(
        row.thing_id if hasattr(row, "thing_id") else row.entity_id
        for row in content_module.load_files().thing_text
        if row.state.startswith(content_module.ROOM_STATE_PREFIX)
        and row.text.get("take")
    )

    assert keyed == ["frozen_burrito"]


def test_a_misspelled_origin_is_caught():
    """The silent failure this prefix could have, and the only way to get it.

    There is one spelling that works, so a typo is the whole risk: the
    row is never read, the thing's ordinary take line is, and nothing
    anywhere says so.
    """
    files = content_module.load_files()
    row = next(
        r for r in files.thing_text
        if r.entity_id == "graphite_powder" and r.state == content_module.FROM_THE_FLOOR
    )
    object.__setattr__(row, "state", "from:flooor")

    problems = content_module.validate(files)

    assert any("names no origin" in p for p in problems), problems
