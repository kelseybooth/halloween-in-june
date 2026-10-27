"""Arrivals: the line that announces a move is also what admits the player.

A bot holding Manage Threads adds somebody to a private thread by mentioning
them, and posts nothing while doing it. `add_user` adds them *and* posts
"<bot> added <player> to the thread" - a line nobody can delete, which reads
as Discord rather than as the house, directly above the arrival the game has
already written. So the arrival line does both jobs now, and these tests are
what keep the mention in it.

Checked against a real server on 26 October 2026: the mention adds silently,
`add_user` does not. Nothing offline can prove that half - the fake admits
nobody - so what is held here is the half that is ours. The line carries the
mention, the hand add is gone, and a failure on the way in leaves the player
in the room they started from.
"""

import pytest
from sqlalchemy.exc import SQLAlchemyError

from conftest import ALICE, GUILD_A, LAST_DROP
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember, a_room_thread

import achievements
import bot
import content as content_module
import content_loader
import database
import resolve
import triggers


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.register_all()
    yield
    achievements.clear()


@pytest.fixture
async def house(db):
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(GUILD_A, channels=[halloween], members=[FakeMember(ALICE)])
    await db.ensure_user_exists(ALICE, GUILD_A)
    await content_loader.load_content(content_module.load_files())
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*rooms.values())
    await db.start_game(ALICE, GUILD_A, "EN", await resolve.rooms_open_at_launch())
    await db.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, LAST_DROP)
    return db, guild, halloween, rooms


async def stand_in(house, room):
    db, guild, _, rooms = house
    await db.update_current_room(ALICE, GUILD_A, room)
    return FakeInteraction(
        ALICE, GUILD_A, guild=guild, channel=a_room_thread(rooms[room])
    )


async def walk(house, exit_name="back door", origin="KI"):
    """One ordinary move: the Kitchen's back door out to the Courtyard."""
    interaction = await stand_in(house, origin)
    await bot.use.callback(interaction, exit_name)
    return interaction


def thread(house, room_name):
    _, _, halloween, _ = house
    return next(t for t in halloween.threads if t.name == room_name)


async def where(db):
    return (await db.get_game_state(ALICE, GUILD_A)).current_room


def replies(interaction):
    return "\n".join(text for text, _ in interaction.sent if text)


# --------------------------------------------------------------------------
# The mention is the mechanism
# --------------------------------------------------------------------------


async def test_the_arrival_line_carries_the_mention(house):
    await walk(house)

    assert any(f"<@{ALICE}>" in line for line in thread(house, "Courtyard").posted)


async def test_nobody_is_added_by_hand_any_more(house):
    """The whole point of the change: `add_user` is what posts the system line."""
    await walk(house)

    assert thread(house, "Courtyard").added_users == []


async def test_they_are_still_taken_out_of_the_room_they_left(house):
    await walk(house)

    assert thread(house, "Kitchen").removed_users == [ALICE]


async def test_the_room_they_left_still_hears_about_it(house):
    await walk(house)

    assert any("exits via" in line for line in thread(house, "Kitchen").posted)


async def test_the_move_is_recorded(house):
    db, *_ = house

    await walk(house)

    assert await where(db) == "CO"


# --------------------------------------------------------------------------
# The line is load-bearing now, so its failures are the move's failures
# --------------------------------------------------------------------------


async def test_a_line_that_cannot_be_posted_is_a_move_that_did_not_happen(house):
    """`add_user` used to gate the move. The arrival line has taken that job,
    so it has to take the failure with it: a player who was never admitted
    must not be recorded as standing in the room."""
    db, _, halloween, _ = house
    halloween.thread_send_fails = {"Courtyard"}

    interaction = await walk(house)

    assert await where(db) == "KI"
    assert bot.MOVE_ERROR_MESSAGE in replies(interaction)


async def test_a_failed_arrival_leaves_them_in_the_room_they_started_in(house):
    """The departure line and the removal both sit after the write, so a
    player who could not be admitted is still in the Kitchen, and the Kitchen
    was never told otherwise."""
    _, _, halloween, _ = house
    halloween.thread_send_fails = {"Courtyard"}

    await walk(house)

    kitchen = thread(house, "Kitchen")
    assert kitchen.removed_users == []
    assert not any("exits via" in line for line in kitchen.posted)


async def test_a_write_that_fails_takes_the_arrival_line_back_down(house, monkeypatch):
    """The line announced a move that did not happen, and it is also what let
    them in, so the rollback deletes it and removes them again."""
    db, *_ = house
    interaction = await stand_in(house, "KI")

    async def refuse(*args, **kwargs):
        raise SQLAlchemyError("the write failed")

    monkeypatch.setattr(database, "update_current_room", refuse)

    await bot.use.callback(interaction, "back door")

    courtyard = thread(house, "Courtyard")
    assert courtyard.posted == []
    assert courtyard.removed_users == [ALICE]
    assert await where(db) == "KI"


# --------------------------------------------------------------------------
# The fallback, for a content row that loses the token
# --------------------------------------------------------------------------


async def test_a_line_without_the_token_falls_back_to_adding_them(house, monkeypatch):
    """No mention, no admission. A row that lost `{player}` would otherwise
    strand the player outside a room the game says they are standing in, so
    they are let in the old way instead - system line and all."""
    db, *_ = house
    written = resolve.thing_text

    async def without_the_token(guild_id, thing_id, column, state=resolve.DEFAULT_STATE):
        if column == "move_arrive":
            return "Somebody arrives."
        return await written(guild_id, thing_id, column, state)

    monkeypatch.setattr(resolve, "thing_text", without_the_token)

    await walk(house)

    courtyard = thread(house, "Courtyard")
    assert courtyard.added_users == [ALICE]
    assert "Somebody arrives." in courtyard.posted
    assert await where(db) == "CO"


# --------------------------------------------------------------------------
# The content the mechanism rests on
# --------------------------------------------------------------------------


def test_the_house_default_carries_the_token():
    """`test_the_override_lines_use_the_token_that_already_exists` holds this
    for the four secret exits. The default is what every other exit falls
    through to, and it is now what admits the player."""
    defaults = content_module.load_files().defaults

    assert "{player}" in defaults["move.arrive"]
