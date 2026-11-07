"""The music box leaves the Nursery, and a clock follows it out.

It was takeable and droppable from the day it shipped, with a
`cross_weight` of 1 and nothing in the engine pinning it to the room -
so "can it go anywhere" was already yes, and the shelf was the only
thing saying otherwise. The shelf's `look` named it in prose, which is
the half of the house rule that covers what stays put; a loose takeable
is the engine's to list under `Also here:`, and naming it in both
places told the player it was furniture.

**The clock is the actual change.** `idle_drop_hours` was empty, and the
music box is the one thing in the house whose absence costs somebody
else an achievement they cannot otherwise earn: *Accompanist* fires on
a rattle shaken within a minute of **another player's** music box. One
box, no clock, and a single player could carry the only accompaniment
in the game upstairs and forget about it.

Six hours, the same as the rattle it plays with.
"""

import pytest
from datetime import timedelta
from sqlalchemy import update
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


# The Nursery was split out of drop 40 on 7 November, and the box is in
# it, so this file moved with the room rather than staying with the
# Hallway and the Bedroom.
THIS_DROP = 45

# Quoted off the content files. Each phrase appears in one row and no other.
A_LULLABY = "a thin, slow lullaby drifts through the room"
THROUGH_THE_MONITOR = "the same tune is already playing"
LID_MID_BAR = "closes the lid mid-bar"


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


async def holding(house, who=ALICE):
    """Take the box the way a player does, so the stamps are real."""
    db, *_ = house
    await run(house, bot.take, "music box", room="NU", who=who)
    assert await db.carried_of(who, GUILD_A, world.MUSIC_BOX) == 1
    return db


async def unused_for(db, hours, who=ALICE):
    """Backdate both stamps the sweep takes the later of.

    `taken_at` for when it reached these hands, `last_used_at` for the
    last use. Moving one and leaving the other at `now` tests nothing.
    """
    then = await database.server_now(GUILD_A) - timedelta(hours=hours)
    async with db._require_session()() as session:
        await session.execute(
            update(database.PlayerInventory)
            .where(
                database.PlayerInventory.user_id == who,
                database.PlayerInventory.guild_id == GUILD_A,
                database.PlayerInventory.thing_id == world.MUSIC_BOX,
            )
            .values(taken_at=then)
        )
        await session.execute(
            update(database.ThingUse)
            .where(
                database.ThingUse.user_id == who,
                database.ThingUse.guild_id == GUILD_A,
                database.ThingUse.thing_id == world.MUSIC_BOX,
            )
            .values(last_used_at=then)
        )
        await session.commit()


# ---------------------------------------------------------------------------
# It goes anywhere


async def test_the_box_can_be_carried_out_of_the_nursery(house):
    db = await holding(house)

    await run(house, bot.drop, "music box", room="LI")

    assert await db.carried_of(ALICE, GUILD_A, world.MUSIC_BOX) == 0
    assert "music box" in dict(await database.loose_here(GUILD_A, "LI"))


async def test_and_plays_its_own_line_once_it_is_out(house):
    """The room-specific line is the Nursery's, not the box's.

    `in:NU` adds the monitor echoing it back, which is a fact about the
    monitor. Downstairs there is no monitor, so the default plays.
    """
    await holding(house)
    await run(house, bot.use, "music box", room="LI")

    said = posted(house, "LI")

    assert A_LULLABY in said
    assert THROUGH_THE_MONITOR not in said


async def test_but_in_the_nursery_the_monitor_still_answers(house):
    """The `in:NU` row is untouched by any of this."""
    await holding(house)
    await run(house, bot.use, "music box", room="NU")

    assert THROUGH_THE_MONITOR in posted(house, "NU")


# ---------------------------------------------------------------------------
# The shelf stops claiming it


def test_the_shelf_no_longer_names_the_music_box():
    """Prose names what stays put; the engine lists what does not.

    Read off the file rather than played, because the subject is one
    cell. The pacifier and the photograph stay in the sentence: neither
    is takeable, so neither is ever listed.
    """
    parsed = content_module.load_files()
    shelf = next(
        r for r in parsed.thing_text
        if r.entity_id == "nursery_shelf" and r.state == "default"
    )

    assert "music box" not in shelf.text["look"].lower()
    assert "pacifier" in shelf.text["look"]
    assert "photograph" in shelf.text["look"]


async def test_and_the_engine_lists_it_instead(house):
    """Which is where a player now learns it is there at all."""
    said = await run(house, bot.look, None, room="NU")

    assert "music box" in said.lower()


async def test_once_somebody_has_it_the_room_stops_offering_it(house):
    """One box: carried means gone from the floor, not listed twice."""
    await holding(house)

    said = await run(house, bot.look, None, room="NU")

    assert "music box" not in said.lower()


# ---------------------------------------------------------------------------
# The six-hour clock


async def test_six_hours_unused_sets_the_music_box_down(house):
    """So nobody can carry off the only accompaniment in the game.

    Driven by the `idle_drop_hours` cell alone - the sweep selects every
    thing with the column set - so this needed no code.
    """
    db = await holding(house)
    await db.update_current_room(ALICE, GUILD_A, "LI")
    await unused_for(db, 7)

    await bot.idle_sweep.coro()

    assert await db.carried_of(ALICE, GUILD_A, world.MUSIC_BOX) == 0
    assert "music box" in dict(await database.loose_here(GUILD_A, "LI"))


async def test_but_five_hours_is_not_enough(house):
    db = await holding(house)
    await unused_for(db, 5)

    await bot.idle_sweep.coro()

    assert await db.carried_of(ALICE, GUILD_A, world.MUSIC_BOX) == 1


async def test_a_box_still_being_played_is_never_swept(house):
    """The later of the two stamps is what counts.

    A player who took it this morning and wound it a minute ago has not
    forgotten it, so backdating only `taken_at` must not sweep them.
    """
    db = await holding(house)
    then = await database.server_now(GUILD_A) - timedelta(hours=9)
    async with db._require_session()() as session:
        await session.execute(
            update(database.PlayerInventory)
            .where(
                database.PlayerInventory.user_id == ALICE,
                database.PlayerInventory.guild_id == GUILD_A,
                database.PlayerInventory.thing_id == world.MUSIC_BOX,
            )
            .values(taken_at=then)
        )
        await session.commit()
    await run(house, bot.use, "music box", room="NU")

    await bot.idle_sweep.coro()

    assert await db.carried_of(ALICE, GUILD_A, world.MUSIC_BOX) == 1


# ---------------------------------------------------------------------------
# The take itself, which a playtester saw fail


async def test_taking_the_music_box_posts_its_own_line(house):
    """Reported from a playtest as an error, and the take had committed.

    Production shows one `take` row for the box, `success`, with the
    player holding it afterwards - so whatever failed, failed after the
    write. Kept as the cheapest guard on the sentence a player should
    see, which is the one thing the report ruled out.
    """
    db = await holding(house)

    assert LID_MID_BAR in posted(house, "NU")
    assert await db.carried_of(ALICE, GUILD_A, world.MUSIC_BOX) == 1
