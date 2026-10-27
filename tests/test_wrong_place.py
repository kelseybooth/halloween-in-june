"""Where your body is, and the two things that keep it true.

Drop 10 gave every player exactly one location - the road, or one room of
the house - and the five world verbs act on it. Before this, typing in the
channel *was* standing in the channel, and the house was whatever threads
you had been added to; a player in the Kitchen could `/look` in the
channel and be shown the road.

So there are two halves here, and they fail in opposite directions.

**The refusal** is what a player sees when the window disagrees with their
body. It points rather than explains, because the rule is not something
anybody needs taught - the way back to the window they can act in is.

**Thread membership** is the other side of the same fact: a room thread
should hold exactly the players standing in that room. Two layers keep it
that way, and the slower one exists because the fast one cannot run while
the bot is restarting.
"""

import pytest
from sqlalchemy import select
from types import SimpleNamespace

from conftest import ALICE, BOB, GUILD_A, LAST_DROP
from fake_discord import (
    FakeChannel,
    FakeGuild,
    FakeInteraction,
    FakeMember,
    a_room_thread,
    somewhere_else,
)

import bot
import content as content_module
import content_loader
import database
import resolve


@pytest.fixture(autouse=True)
def forget_admissions():
    """Clear the window that marks joins the bot is making itself.

    It is module state with a thirty-second deadline, and the fake's
    thread ids are a hash of the room name - so the Kitchen in one test is
    the Kitchen in the next, and an admission left behind makes the sweep
    skip somebody for the rest of the file. `triggers.forget_arrivals`
    exists for the same reason.
    """
    bot._ADMITTING.clear()
    yield
    bot._ADMITTING.clear()


@pytest.fixture
async def house(db):
    """The house built, and Alice standing in the Entryway."""
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    await content_loader.load_content(content_module.load_files())
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, LAST_DROP)
    await db.start_game(ALICE, GUILD_A, "EN", await resolve.rooms_open_at_launch())
    return db, guild, halloween, rooms


def thread(house, room_name):
    _, _, halloween, _ = house
    return next(t for t in halloween.threads if t.name == room_name)


async def run(house, command, arg=None, *, channel=None, room=None, who=ALICE):
    """One command, typed somewhere particular."""
    _, guild, halloween, rooms = house
    if channel is None:
        channel = halloween if room is None else thread(house, rooms[room])
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=channel)
    args = () if arg is None else (arg,)
    await command.callback(interaction, *args)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


async def where(db, who=ALICE):
    state = await db.get_game_state(who, GUILD_A)
    return state.current_room if state else None


async def logged(db, action=None):
    session_factory = db._require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(db.InteractionLog)
            .where(db.InteractionLog.guild_id == GUILD_A)
            .order_by(db.InteractionLog.id)
        )
        return [r for r in rows.scalars() if action is None or r.action == action]


SPIRIT = "Your spirit may be here"


# --------------------------------------------------------------------------
# The five world verbs, and the hand that pets the cat
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command, arg",
    [
        pytest.param(lambda: bot.look, None, id="look"),
        pytest.param(lambda: bot.use, "coat rack", id="use"),
        pytest.param(lambda: bot.take, "cat food", id="take"),
        pytest.param(lambda: bot.drop, "cat food", id="drop"),
        pytest.param(lambda: bot.go, "road", id="go"),
    ],
)
async def test_a_world_verb_typed_outside_your_room_is_refused(house, command, arg):
    """All five, run rather than argued about. A player in the Entryway
    typing in the channel is asking the Entryway's question from the road."""
    interaction = await run(house, command(), arg)

    assert SPIRIT in replies(interaction)
    assert interaction.was_private


async def test_the_refusal_links_to_the_room_they_are_in(house):
    interaction = await run(house, bot.look)

    assert thread(house, "Entryway").mention in replies(interaction)


async def test_petting_has_its_own_line(house):
    """**The cat is wherever the player is**, so this is not about her: the
    hand doing the petting is attached to a body that is in one room, and
    the line says so rather than reading as a bug."""
    interaction = await run(house, bot.pet)

    assert "your hand" in replies(interaction)
    assert thread(house, "Entryway").mention in replies(interaction)


async def test_and_nothing_happened_while_they_were_told(house):
    db, *_ = house
    before = await db.get_pet_count(ALICE, GUILD_A)

    await run(house, bot.pet)

    assert await db.get_pet_count(ALICE, GUILD_A) == before


async def test_somebody_on_the_road_is_pointed_at_the_channel(house):
    """The other direction, and the one a player hits by walking out and
    forgetting. The thread is still open in front of them."""
    db, _, halloween, _ = house
    await db.update_current_room(ALICE, GUILD_A, "CH")

    interaction = await run(house, bot.look, room="EN")

    assert SPIRIT in replies(interaction)
    assert halloween.mention in replies(interaction)


async def test_a_channel_that_is_not_the_game_is_nowhere(house):
    """#general is as wrong as the wrong room, and gets the same answer."""
    interaction = await run(house, bot.look, channel=somewhere_else("general"))

    assert SPIRIT in replies(interaction)


async def test_a_thread_for_another_room_is_nowhere_too(house):
    interaction = await run(house, bot.look, room="KI")

    assert SPIRIT in replies(interaction)


async def test_the_right_window_is_not_refused(house):
    interaction = await run(house, bot.look, room="EN")

    assert SPIRIT not in replies(interaction)
    assert "coat rack" in replies(interaction)


async def test_the_channel_is_the_right_window_for_somebody_outside(house):
    db, *_ = house
    await db.update_current_room(ALICE, GUILD_A, "CH")

    interaction = await run(house, bot.look)

    assert SPIRIT not in replies(interaction)


async def test_a_player_with_no_row_at_all_is_on_the_road(house):
    """Nobody is nowhere. Before drop 10 a member who had only petted the
    cat had no location at all, and the verbs had a third case for it."""
    interaction = await run(house, bot.look, who=BOB)

    assert SPIRIT not in replies(interaction)


# --------------------------------------------------------------------------
# What stays global
# --------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["stats", "inventory"])
async def test_the_commands_about_the_player_work_anywhere(house, command):
    """They are about the player rather than the room. Checking your own
    bag is not a thing you have to be standing somewhere to do."""
    interaction = await run(
        house, getattr(bot, command), None, channel=somewhere_else("general")
    )

    assert SPIRIT not in replies(interaction)


async def test_a_craving_guess_is_not_a_place(house):
    """The craving game is played by reacting to the bot's own messages,
    wherever they are. A player inside the house guessing on a line in the
    channel is the normal case, not an error."""
    db, guild, halloween, _ = house
    await resolve.set_current_drop(GUILD_A, 3)
    today = await database.server_today(GUILD_A)

    import craving

    guess = await craving.judge(GUILD_A, ALICE, chr(0x1F401), today)

    assert guess is not None and guess.won


# --------------------------------------------------------------------------
# The log
# --------------------------------------------------------------------------


async def test_a_refusal_writes_one_row_naming_both_places(house):
    db, *_ = house

    await run(house, bot.look)

    rows = await logged(db, database.WRONG_PLACE)
    assert len(rows) == 1
    assert rows[0].outcome == database.REFUSED
    assert rows[0].detail == "command=look in=halloween at=EN"


async def test_every_verb_names_itself_in_it(house):
    db, *_ = house

    await run(house, bot.take, "cat food")
    await run(house, bot.pet)

    assert [r.detail.split()[0] for r in await logged(db, database.WRONG_PLACE)] == [
        "command=take",
        "command=pet",
    ]


# --------------------------------------------------------------------------
# A thread holds exactly its own players
# --------------------------------------------------------------------------


def joined(house, room_name, user_id):
    """The event Discord sends when somebody turns up in a thread."""
    _, guild, _, _ = house
    room = thread(house, room_name)
    # A real `Thread` carries its guild; the fake is built from a channel
    # and has no way back to one, so the test supplies it.
    room.guild = guild
    room.members.append(user_id)
    return SimpleNamespace(id=user_id, thread=room)


async def test_somebody_added_to_a_room_they_are_not_in_is_removed(house):
    """The fast layer. An admin adds a player by hand, or a thread is
    reachable some other way, and they are out again before they have read
    anything."""
    await bot.on_thread_member_join(joined(house, "Kitchen", ALICE))

    assert ALICE in thread(house, "Kitchen").removed_users


async def test_somebody_in_their_own_room_is_left_alone(house):
    await bot.on_thread_member_join(joined(house, "Entryway", ALICE))

    assert thread(house, "Entryway").removed_users == []


async def test_the_bot_is_never_removed(house, monkeypatch):
    """It has to be in every thread to post in them.

    Patched through `_me` rather than through `bot.user`, which is a
    read-only property on the client - which is also why `_me` exists:
    the sweep runs at startup, before the gateway has said who we are.
    """
    monkeypatch.setattr(bot, "_me", lambda: 999)

    await bot.on_thread_member_join(joined(house, "Kitchen", 999))

    assert thread(house, "Kitchen").removed_users == []


async def test_staff_are_never_removed(house):
    """Anybody who can manage threads sees every private thread whatever
    the bot does, so removing them fails - and then fails again on the next
    sweep, for as long as they are an admin."""
    _, guild, _, _ = house
    admin = FakeMember(4242)
    admin.guild_permissions = SimpleNamespace(manage_threads=True)
    guild.add_member(admin)

    await bot.on_thread_member_join(joined(house, "Kitchen", 4242))

    assert thread(house, "Kitchen").removed_users == []


async def test_a_join_the_bot_is_making_is_not_policed(house):
    """**The race this exists for.** Admitting somebody is a mention, and
    Discord answers it with the same event an admin adding them produces -
    so a move would otherwise throw a player out of the room they just
    walked into, because the arrival line goes out before the row moves."""
    kitchen = thread(house, "Kitchen")
    bot._admit(kitchen.id, ALICE)

    await bot.on_thread_member_join(joined(house, "Kitchen", ALICE))

    assert kitchen.removed_users == []


# --------------------------------------------------------------------------
# The sweep behind it
# --------------------------------------------------------------------------


async def test_the_sweep_clears_whoever_the_handler_missed(house):
    """The slow layer, for everything that happened while the bot was down -
    which is the half nobody can be careful about."""
    _, guild, _, _ = house
    thread(house, "Kitchen").members.append(ALICE)

    removed = await bot._sweep_threads(guild)

    assert removed == 1
    assert ALICE in thread(house, "Kitchen").removed_users


async def test_it_leaves_the_room_they_are_standing_in(house):
    _, guild, _, _ = house
    thread(house, "Entryway").members.append(ALICE)

    assert await bot._sweep_threads(guild) == 0
    assert thread(house, "Entryway").removed_users == []


async def test_it_sweeps_the_secret_library_like_any_other_room(house):
    """Discovery is per player, and the thread is what keeps it that way."""
    _, guild, _, _ = house
    thread(house, "Secret Library").members.append(ALICE)

    await bot._sweep_threads(guild)

    assert ALICE in thread(house, "Secret Library").removed_users


async def test_it_never_touches_the_channel(house):
    """Nobody can be removed from it, and nobody needs to be: being able to
    read it is not a claim about where anybody is standing."""
    _, guild, halloween, _ = house

    await bot._sweep_threads(guild)

    assert not getattr(halloween, "removed_users", [])


async def test_the_sweep_says_so_in_the_log(house):
    _, guild, _, _ = house
    thread(house, "Kitchen").members.append(ALICE)
    db, *_ = house

    await bot._sweep_threads(guild)

    rows = await logged(db, database.THREAD_REMOVED)
    assert len(rows) == 1
    assert rows[0].actor == database.SYSTEM
    assert rows[0].detail == "thread=KI why=sweep"


async def test_a_move_says_why_too(house):
    """One of the three reasons somebody leaves a thread, and the only one
    that is not a mistake being corrected."""
    db, *_ = house

    await run(house, bot.go, "living room", room="EN")

    rows = await logged(db, database.THREAD_REMOVED)
    assert [r.detail for r in rows] == ["thread=EN why=move"]


# --------------------------------------------------------------------------
# Getting back in
# --------------------------------------------------------------------------


async def test_a_player_who_left_their_thread_is_put_back(house):
    """**A link to a thread you are not in opens nothing**, so the refusal
    that sends somebody back to their room is useless at exactly the moment
    it matters. A bare mention re-admits them silently."""
    entryway = thread(house, "Entryway")
    assert ALICE not in entryway.members

    await run(house, bot.look)

    assert entryway.posted[-1] == f"<@{ALICE}>"


async def test_somebody_still_in_their_thread_is_not_mentioned_again(house):
    entryway = thread(house, "Entryway")
    entryway.members.append(ALICE)

    await run(house, bot.look)

    assert f"<@{ALICE}>" not in entryway.posted


async def test_nobody_is_put_back_into_the_channel(house):
    """There is nothing to put them back into."""
    db, _, halloween, _ = house
    await db.update_current_room(ALICE, GUILD_A, "CH")

    await run(house, bot.look, room="EN")

    assert f"<@{ALICE}>" not in halloween.posted
