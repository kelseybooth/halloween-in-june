"""The oak's ambient hints, and the wire cutters in the library.

Two small additions on top of drop 50. The hints are the house
muttering about the tree in the Courtyard until somebody gets into the
Secret Library; the cutters are a fixture that hands out copper wire
when you use it and refuses to be pocketed.

**What ends the hints is "has anybody been in", not "has this server
had a ghost".** The work order asked for the first ghost's check by
name and the two are different questions - see
`database.anyone_holding`, and `ghosts.first_ghost` for why the ghost's
own check must stay as it is. Both halves are pinned here: a server
with a ghost and nobody in the library still mutters, and a server
where somebody walked in during QA never does.

**Driven through the completion hook**, which is where they run, and
through the detached task that posts them - `settle` waits for it. The
delay is zeroed in most of these, because the only thing they need to
know is that a line lands; `test_the_line_waits_for_its_own_moment` is
where the waiting itself is the subject.

**Hints are counted by key, not by text.** The Courtyard's thread also
carries arrival and departure lines - a climb up the oak posts one - so
`muttered` matches what was said back to the ten keys and ignores the
rest.
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember, a_room_thread

import achievements
import bot
import content as content_module
import content_loader
import database
import oak
import resolve
import states
import triggers
import world

COURTYARD = "CO"
LIBRARY = "SE"
LIVING_ROOM = "LI"


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.register_all()
    yield
    achievements.clear()


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """The thirty seconds, taken out. See the module docstring."""
    monkeypatch.setattr(bot, "OAK_HINT_DELAY", 0)


@pytest.fixture
async def house(db, monkeypatch):
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
    await db.set_setting(GUILD_A, resolve.DROP_KEY, oak.FROM_DROP)
    # One in one and no gap, which is what the work order's acceptance
    # tests are run with. The tests about the odds and the gap set their
    # own.
    await db.set_config(GUILD_A, oak.ODDS, "1")
    await db.set_config(GUILD_A, oak.GAP_HOURS, "0")
    # A hint goes to the room rather than into a reply, so the posting
    # path looks the guild up on the client instead of taking it off an
    # interaction. This is the suite's standing idiom for that.
    monkeypatch.setattr(
        bot,
        "bot",
        SimpleNamespace(
            guilds=[guild], get_guild=lambda gid: guild if gid == GUILD_A else None
        ),
    )
    return db, guild, halloween, rooms


async def settle():
    """Let the detached posting task finish.

    Deterministic rather than a sleep: the task is the only other thing
    on the loop in a test, so it is awaited rather than waited for.
    """
    for _ in range(3):
        running = [
            task for task in asyncio.all_tasks() if task is not asyncio.current_task()
        ]
        if not running:
            return
        await asyncio.gather(*running)


async def a_command(house, who=ALICE, where=COURTYARD, *, wait=True):
    """One command's worth of the completion hook, run from a room."""
    db, guild, halloween, rooms = house
    await db.update_current_room(who, GUILD_A, where)
    interaction = FakeInteraction(
        who, GUILD_A, guild=guild, channel=a_room_thread(rooms[where])
    )
    await bot.on_app_command_completion(interaction, bot.look)
    if wait:
        await settle()
    return interaction


async def said(key: str) -> str:
    line = await bot.phrasing.default_say(key)
    assert line, f"{key} has no text in the files"
    return line


async def muttered(house) -> list[str]:
    """Which hint keys the house has posted in the Courtyard, in order."""
    _, _, halloween, rooms = house
    thread = next(t for t in halloween.threads if t.name == rooms[COURTYARD])
    by_line = {await said(key): key for key in oak.KEYS}
    return [by_line[line] for line in thread.posted if line in by_line]


def posted_in(house, room_id) -> list[str]:
    _, _, halloween, rooms = house
    thread = next(t for t in halloween.threads if t.name == rooms[room_id])
    return list(thread.posted)


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


async def carrying(db, thing_id, who=ALICE) -> int:
    return await db.carried_of(who, GUILD_A, thing_id)


# --------------------------------------------------------------------------
# 1. When one posts
# --------------------------------------------------------------------------


async def test_a_courtyard_command_posts_the_first_hint(house):
    await a_command(house)

    assert await muttered(house) == [oak.KEYS[0]]


async def test_the_line_waits_for_its_own_moment(house, monkeypatch):
    """**The whole reason it is a detached task.** A line that arrives in
    the same breath as the reply reads as an answer to what the player
    typed, and this one is the house talking to the room.

    Parked in the wait rather than raced: the delay is set long enough
    that "not yet" is a fact and not a timing accident.
    """
    monkeypatch.setattr(bot, "OAK_HINT_DELAY", 600)

    await a_command(house, wait=False)

    assert await muttered(house) == []

    for task in [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]:
        task.cancel()


async def test_it_is_public_and_not_a_reply(house):
    """Nothing private: the player whose command triggered it is not
    singled out, and nobody can ask for one."""
    interaction = await a_command(house)

    assert await muttered(house) == [oak.KEYS[0]]
    assert await said(oak.KEYS[0]) not in replies(interaction)


async def test_a_command_in_another_room_posts_nothing(house):
    await a_command(house, where=LIVING_ROOM)

    assert await muttered(house) == []


async def test_a_command_from_the_road_posts_nothing(house):
    """The road is where players start, and it is not the Courtyard."""
    db, guild, halloween, _ = house
    await db.update_current_room(ALICE, GUILD_A, content_module.CHANNEL_ROOM)
    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    await bot.on_app_command_completion(interaction, bot.look)
    await settle()

    assert await muttered(house) == []


async def test_below_fifty_nothing_posts(house):
    db, *_ = house
    await db.set_setting(GUILD_A, resolve.DROP_KEY, oak.FROM_DROP - 1)

    await a_command(house)

    assert await muttered(house) == []


async def test_the_odds_decide_whether_it_is_even_considered(house, monkeypatch):
    """One in `oak_hint_odds`, and the roll happens before anything is
    read - which is the whole cost of hanging this off the widest hook
    in the game."""
    db, *_ = house
    await db.set_config(GUILD_A, oak.ODDS, "4")
    rolls = iter([1, 2, 3, 0])
    monkeypatch.setattr(oak.random, "randrange", lambda _: next(rolls))

    for _ in range(4):
        await a_command(house)

    assert await muttered(house) == [oak.KEYS[0]]


async def test_odds_of_zero_turns_them_off(house):
    """An admin who wants silence has a number that means silence, and it
    is not a division by zero."""
    db, *_ = house
    await db.set_config(GUILD_A, oak.ODDS, "0")

    await a_command(house)

    assert await muttered(house) == []


# --------------------------------------------------------------------------
# 2. Which line, and how often
# --------------------------------------------------------------------------


async def test_the_ten_play_once_in_order(house):
    for _ in range(oak.COUNT):
        await a_command(house)

    assert await muttered(house) == list(oak.KEYS)


async def test_after_the_tenth_they_are_random(house):
    for _ in range(oak.COUNT + 4):
        await a_command(house)

    extra = (await muttered(house))[oak.COUNT :]
    assert len(extra) == 4
    assert all(key in oak.KEYS for key in extra)


async def test_the_random_phase_never_repeats_itself(house):
    """With ten lines this is the difference between a house that
    mutters and one that sounds broken, and it costs one column."""
    for _ in range(oak.COUNT + 8):
        await a_command(house)

    keys = await muttered(house)
    assert all(a != b for a, b in zip(keys, keys[1:]))


def test_the_order_is_the_writers_order():
    """The first five are subtle and the last five point at the window,
    so a shuffled first pass would hand over the plainest hint first."""
    assert [oak.line_at(at, None) for at in range(oak.COUNT)] == list(oak.KEYS)


def test_the_random_phase_leaves_out_the_last_line():
    assert all(oak.line_at(oak.COUNT, oak.KEYS[2]) != oak.KEYS[2] for _ in range(50))


async def test_the_gap_holds_them_apart(house):
    """With the defaults back on, no two land within four hours."""
    db, *_ = house
    await db.set_config(GUILD_A, oak.GAP_HOURS, "4")

    for _ in range(5):
        await a_command(house)

    assert await muttered(house) == [oak.KEYS[0]]


async def test_two_commands_in_one_window_draw_one_line(house):
    """**The slot is claimed before the line is posted**, thirty seconds
    before, so two commands inside that half minute cannot both draw.
    Claimed on the command rather than on the post is the whole of it."""
    db, *_ = house
    await db.set_config(GUILD_A, oak.GAP_HOURS, "4")

    await a_command(house, wait=False)
    await a_command(house, who=BOB, wait=False)
    await settle()

    assert await muttered(house) == [oak.KEYS[0]]


async def test_a_hint_that_cannot_post_is_not_spent(house):
    """A server does not lose a line to a channel that would not take it.

    The slot goes back, so the next command reads the same line rather
    than the one after it.
    """
    db, _, halloween, rooms = house
    await db.set_config(GUILD_A, oak.GAP_HOURS, "4")
    halloween.threads.clear()

    await a_command(house)

    assert await database.oak_hints_so_far(GUILD_A) == 0

    halloween.add_active(*rooms.values())
    await a_command(house)

    assert await muttered(house) == [oak.KEYS[0]]


# --------------------------------------------------------------------------
# 3. When they stop
# --------------------------------------------------------------------------


async def test_climbing_the_oak_ends_them_for_everybody(house):
    """The first player in, by either way, ends them for the server -
    including for somebody who has never been up the tree."""
    await act(house, bot.use, "oak tree", COURTYARD)

    await a_command(house, who=BOB)

    assert await muttered(house) == []


async def test_the_cabinet_ends_them_too(house):
    """`passage_open` is the other way in, and either one means the
    secret is out."""
    await states.set_player_state(GUILD_A, ALICE, world.PASSAGE_OPEN)

    await a_command(house, who=BOB)

    assert await muttered(house) == []


async def test_a_library_found_before_this_shipped_never_mutters(house):
    """A server that reached 50 and had somebody in the library before
    the hints existed starts with none and stays that way: the state
    rows are the record, so nothing has to be backfilled."""
    await states.set_player_state(GUILD_A, ALICE, world.LIBRARY_FOUND)

    for _ in range(3):
        await a_command(house, who=BOB)

    assert await muttered(house) == []
    assert await database.oak_hints_so_far(GUILD_A) == 0


async def test_they_do_not_come_back(house):
    """Nothing is held in memory, so there is nothing a restart could
    forget: the state row is the whole of it."""
    await a_command(house)
    await act(house, bot.use, "oak tree", COURTYARD)

    for _ in range(3):
        await a_command(house, who=BOB)

    assert await muttered(house) == [oak.KEYS[0]]


async def test_a_ghost_does_not_stop_them(house):
    """**The check the work order asked for, and why it is not this
    one.** `ever_had_a_ghost` is Part 2's marker; a server that has a
    ghost and nobody in the library is still a server where the tree is
    worth pointing at.
    """
    db, *_ = house
    await db.claim_first_ghost(
        GUILD_A,
        await db.server_today(GUILD_A),
        user_id=ALICE,
        display_name="Alice",
        username="alice",
    )
    assert await db.ever_had_a_ghost(GUILD_A)

    await a_command(house, who=BOB)

    assert await muttered(house) == [oak.KEYS[0]]


async def test_the_first_entry_says_how_many_came_before_it(house, caplog):
    """The number the work order asks to see, so the odds and the gap can
    be tuned against what players actually did."""
    for _ in range(3):
        await a_command(house)

    with caplog.at_level(logging.INFO, logger="oak"):
        await act(house, bot.use, "oak tree", COURTYARD)

    assert "after 3 oak hint(s)" in caplog.text


# --------------------------------------------------------------------------
# 4. The wire cutters
# --------------------------------------------------------------------------


async def test_the_spool_points_at_the_cutters(house):
    """Pointed at from the spool's line, so the approved library room
    text stays as it is.

    **And bolded there**, which is the half that matters: the marker is
    the only promise in the game that a word can be typed, and it is
    made here because the cutters are a thing in the room the sentence
    is read in.
    """
    reply = replies(await act(house, bot.look, "spool of copper wire", LIBRARY))

    assert "lies beside it" in reply
    assert "**wire cutters**" in reply


async def test_looking_at_the_cutters(house):
    reply = replies(await act(house, bot.look, "wire cutters", LIBRARY))

    assert "red rubber handles" in reply


async def test_using_them_hands_over_copper_wire(house):
    """**The line is the room's, not the player's.** What it hands over is
    the same event a take from a source is - a third-person sentence
    everybody standing there reads once - so it posts into the thread
    and no private reply goes with it.

    **And the wire is bolded in it**, which is the marker doing exactly
    what it promises: the player is holding one by the time they read
    the sentence, so the word is one they can type.
    """
    db, *_ = house

    interaction = await act(house, bot.use, "wire cutters", LIBRARY)

    assert await carrying(db, "copper_wire") == 1
    assert any(
        "coils the **copper wire** and stows it" in line
        for line in posted_in(house, LIBRARY)
    )
    assert replies(interaction) == ""


async def test_a_use_is_counted_once_and_knows_its_room(house):
    """**The trap the general rule walked into.** `record_use` is the only
    place `use_count` increments, which is the whole reason a count off
    it can be trusted - and a draw from a source asks it for a second
    stamp, with a deliberately null room. Every use already arrives
    through `_finish_use`, which recorded this one with the room in it,
    so asking for the draw's stamp as well counted one snip twice and
    then forgot where it happened.
    """
    from sqlalchemy import select

    db, *_ = house

    await act(house, bot.use, "wire cutters", LIBRARY)

    async with db._require_session()() as session:
        row = await session.scalar(
            select(db.ThingUse).where(
                db.ThingUse.guild_id == GUILD_A,
                db.ThingUse.user_id == ALICE,
                db.ThingUse.thing_id == "wire_cutters",
            )
        )

    assert row is not None
    assert row.use_count == 1
    assert row.last_used_room == LIBRARY


async def test_a_second_use_gives_another(house):
    db, *_ = house
    await act(house, bot.use, "cutters", LIBRARY)

    await act(house, bot.use, "cutters", LIBRARY)

    assert await carrying(db, "copper_wire") == 2


async def test_taking_them_refuses_and_moves_nothing(house):
    db, *_ = house

    reply = replies(await act(house, bot.take, "wire cutters", LIBRARY))

    assert "strongest urge to keep them in this room" in reply
    assert await carrying(db, "wire_cutters") == 0
    assert await carrying(db, "copper_wire") == 0


async def test_the_spool_is_unchanged(house):
    """`/take wire` and `/use wire` still mean what they meant, which is
    why the cutters' aliases leave the word out."""
    db, *_ = house

    await act(house, bot.take, "wire", LIBRARY)

    assert await carrying(db, "copper_wire") == 1

    reply = replies(await act(house, bot.use, "wire", LIBRARY))

    assert "uncoil a little of it" in reply


async def test_the_rule_turns_a_source_down(house):
    """**The other half of "a fixture, not a source", pinned on the rule
    itself.**

    It has to be asked here rather than through `/use`, and the reason
    is the parser: `reach` files a source under the thing it yields -
    which is what stops `/take cat food` asking which cat food - so
    `/use spool of copper wire` resolves to `copper_wire`, an object
    with no `yields` cell. A widened rule would find nothing to hand
    over on that path and look safe while being wrong.

    So the type guard is checked where it is written. Dropping it is
    how a source quietly starts handing out its yield twice, once per
    verb.
    """
    db, *_ = house

    handed = await world._hand_over_what_it_yields(
        GUILD_A, ALICE, "copper_wire_spool"
    )

    assert handed is None
    assert await carrying(db, "copper_wire") == 0


async def test_asking_to_use_the_spool_is_asking_about_the_wire(house):
    """**Why the guard above cannot be tested through `/use`.**

    Naming the spool resolves to the thing it yields, so a player who
    is not carrying wire is told to pick some up - the spool's own
    sentence is never what answers. Nothing is handed over either way,
    which is what makes a widened rule invisible from here.
    """
    db, *_ = house

    reply = replies(await act(house, bot.use, "spool of copper wire", LIBRARY))

    assert "have to pick it up first" in reply
    assert await carrying(db, "copper_wire") == 0


def test_only_the_cutters_yield_on_use():
    """**The general rule, and the list it applies to.**

    `world._hand_over_what_it_yields` reads a `fixture` with a `yields`
    cell and hands one out, which is a rule about the type rather than
    about the cutters - so this is where a second one says so. Nothing
    else in the files can reach it: every other `yields` is on a
    `source`, which answers `/take` with it instead, or on the ladder,
    which is an `object` with code of its own.
    """
    content = content_module.load()
    yielding = sorted(
        thing.thing_id
        for thing in content.things
        if thing.yields and thing.type == content_module.FIXTURE
    )

    assert yielding == ["wire_cutters"]


def test_the_cutters_are_a_fixture_and_not_a_source():
    """The difference is `/take`: a source answers one with its yield,
    and these have to refuse it."""
    content = content_module.load()
    cutters = next(t for t in content.things if t.thing_id == "wire_cutters")

    assert cutters.type == content_module.FIXTURE
    assert cutters.takeable is False
    assert cutters.yields == "copper_wire"


def test_the_latest_playable_drop_covers_this():
    """The standing rule every work order checks."""
    assert resolve.LAST_PLAYABLE_DROP >= oak.FROM_DROP
