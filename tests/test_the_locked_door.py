"""The house starts locked, and one brass key opens it for everybody.

**The point is that drop 10 is a thing a server does together.** Beta
players already cooperate - they swap toys when somebody is short - and
this gives that something to be about. The door is shut for the whole
server, the only key falls out of the cat bed, taking it is public, and
whoever has it has to be asked.

Three mechanisms, and each has a failure it exists to avoid. **A server
state**, because collective labour earns a collective reward and a
per-player door would just be nine people doing the same thing. **A
spare key a day while the door stays locked**, because the first finder
can go quiet and a server should not be shut out of the house for good
by one person's Tuesday. And **the key stops working the moment the door
opens**, because a second holder turning it in an open lock should read
as "already done" rather than as the game doing nothing.

The key comes out of the bed *instead of* a toy, and without spending
that player's one toy - which they can still have on a later fluff.
Being first to the bed should not cost anybody their crinkle ball.
"""

import pytest
from sqlalchemy import select

from conftest import ALICE, BOB, GUILD_A, HOUSE_DROP
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
import hints
import resolve
import states
import triggers
import world

KEY = "house_key"
LOCKED = "except that it's locked"
TURNED = "they slide back with a clunk"


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.register_all()
    triggers.forget_arrivals()
    yield
    achievements.clear()


@pytest.fixture
async def road(db):
    """Drop 10. The house is built, and the front door is shut."""
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    await content_loader.load_content(content_module.load_files())
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, HOUSE_DROP)
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    return db, guild, halloween, rooms


def thread(road, room_name):
    _, _, halloween, _ = road
    return next(t for t in halloween.threads if t.name == room_name)


async def run(road, command, arg=None, *, who=ALICE, room=None):
    _, guild, halloween, rooms = road
    channel = halloween if room is None else thread(road, rooms[room])
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=channel)
    args = () if arg is None else (arg,)
    await command.callback(interaction, *args)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


async def fluff(road, who=ALICE):
    return await run(road, bot.use, "cat bed", who=who)


async def where(db, who=ALICE):
    state = await db.get_game_state(who, GUILD_A)
    return state.current_room if state else None


async def a_day_later(db, days=1):
    await db.set_setting(GUILD_A, database.CLOCK_KEY, days)


async def keys_on_the_road(db):
    session_factory = db._require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(db.RoomContents.count).where(
                db.RoomContents.guild_id == GUILD_A,
                db.RoomContents.room_id == content_module.CHANNEL_ROOM,
                db.RoomContents.thing_id == KEY,
            )
        ) or 0


async def logged(db, action):
    session_factory = db._require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(db.InteractionLog)
            .where(
                db.InteractionLog.guild_id == GUILD_A,
                db.InteractionLog.action == action,
            )
            .order_by(db.InteractionLog.id)
        )
        return list(rows.scalars())


async def unlock_it(road, who=ALICE):
    """The whole sequence, for the tests that are about what comes after."""
    await fluff(road, who=who)
    await run(road, bot.take, "key", who=who)
    return await run(road, bot.use, "key", who=who)


# --------------------------------------------------------------------------
# Shut
# --------------------------------------------------------------------------


async def test_the_front_door_is_locked_at_drop_ten(road):
    db, *_ = road

    reply = replies(await run(road, bot.go, "house"))

    assert LOCKED in reply
    assert await where(db) is None


async def test_the_old_verb_is_refused_the_same_way(road):
    """`/use front door` on the road is `/go house` by another name, and
    the gate is on the exit rather than on either verb."""
    assert LOCKED in replies(await run(road, bot.use, "front door"))


async def test_the_look_says_so_before_anybody_tries(road):
    """Three deadbolts outside, to match the Entryway's *three separate
    locks, every one of them undone* on the inside."""
    reply = replies(await run(road, bot.look, "house"))

    assert "three heavy brass deadbolts" in reply


async def test_trying_the_door_is_knowing_the_house_is_there(road):
    """The fourth way into `knows_house`, and the most certain of them:
    nobody types `/go house` at a road that has never mentioned one by
    accident."""
    db, *_ = road
    assert "unlit **house**" not in replies(await run(road, bot.look))

    await run(road, bot.go, "house")

    assert await db.has_been_told(GUILD_A, ALICE, hints.DID_TRY_HOUSE)
    assert "unlit **house**" in replies(await run(road, bot.look))


# --------------------------------------------------------------------------
# The key falls out of the bed
# --------------------------------------------------------------------------


async def test_the_first_fluff_drops_a_key(road):
    db, _, halloween, _ = road

    await fluff(road)

    assert await keys_on_the_road(db) == 1
    assert "something small but heavy falls out of it with a clink" in "\n".join(
        halloween.posted
    )


async def test_the_fluffer_still_gets_the_hint(road):
    """Unlike the toy yield, which suppresses its private half. A hint
    rides a private message, so the key's fluff has to keep one."""
    reply = replies(await fluff(road))

    assert "look" in reply.lower()
    assert "shake out the cushion" in reply


async def test_a_second_fluff_the_same_day_drops_nothing(road):
    """Bob, because Alice's bed is on a 24-hour cooldown of its own and
    would be refused before any of this ran."""
    db, *_ = road
    await fluff(road)

    await fluff(road, who=BOB)

    assert await keys_on_the_road(db) == 1


async def test_a_spare_falls_a_day_later(road):
    """Insurance against the first finder going quiet, not a supply."""
    db, *_ = road
    await fluff(road)
    await a_day_later(db)

    await fluff(road)

    assert await keys_on_the_road(db) == 2


async def test_and_no_spares_once_the_door_is_open(road):
    db, *_ = road
    await unlock_it(road)
    await a_day_later(db)

    await fluff(road)

    assert await keys_on_the_road(db) == 0


async def test_no_key_falls_before_the_house_arrives(road):
    """Drop 1, where the bed is the whole game and there is no house for a
    key to open."""
    db, *_ = road
    await resolve.set_current_drop(GUILD_A, 1)

    await fluff(road)

    assert await keys_on_the_road(db) == 0


async def test_the_key_does_not_cost_the_fluffer_their_toy(road):
    """The key is the server's business and the toy is theirs."""
    db, *_ = road
    await fluff(road)
    assert not await db.has_been_told(GUILD_A, ALICE, world.BED_STASH)

    await a_day_later(db, 2)
    await unlock_it(road, who=BOB)
    await fluff(road)

    assert await db.has_been_told(GUILD_A, ALICE, world.BED_STASH)


async def test_the_drop_is_logged_as_first_or_spare(road):
    db, *_ = road
    await fluff(road)
    await a_day_later(db)
    await fluff(road)

    rows = await logged(db, database.KEY_DROPPED)
    assert [r.detail for r in rows] == ["first", "spare"]
    assert [r.actor for r in rows] == [database.SYSTEM, database.SYSTEM]


# --------------------------------------------------------------------------
# Picking it up
# --------------------------------------------------------------------------


async def test_taking_the_key_is_public(road):
    """So the rest of the server can scroll back and see who has it."""
    _, _, halloween, _ = road
    await fluff(road)

    await run(road, bot.take, "key")

    assert "pockets the brass key" in "\n".join(halloween.posted)


async def test_nobody_holds_two(road):
    """`max_per_player = 1`, so a spare always goes to somebody new."""
    db, *_ = road
    await fluff(road)
    await run(road, bot.take, "key")
    await a_day_later(db)
    await fluff(road)

    await run(road, bot.take, "key")

    assert await db.carried_of(ALICE, GUILD_A, KEY) == 1
    assert await keys_on_the_road(db) == 1


# --------------------------------------------------------------------------
# Turning it
# --------------------------------------------------------------------------


async def test_the_key_only_works_where_the_house_is(road):
    """`requires = house`, met by the exit standing in the room rather
    than by anything in the bag - which is the same rule the cat bowl
    needs, arriving twice in one drop."""
    db, *_ = road
    await fluff(road)
    await run(road, bot.take, "key")
    # Put inside rather than walked inside, because the door she is
    # holding the key for is the one she would have to walk through.
    await db.start_game(ALICE, GUILD_A, "EN", await resolve.rooms_open_at_launch())

    reply = replies(await run(road, bot.use, "key", room="EN"))

    assert "nothing here for it to open" in reply


async def test_turning_it_unlocks_the_door(road):
    db, _, halloween, _ = road

    reply = replies(await unlock_it(road))

    assert TURNED in reply
    assert "unlocked the front door of the house" in "\n".join(halloween.posted)


async def test_and_it_opens_for_everybody(road):
    """The whole point of a server state. Bob did nothing."""
    db, *_ = road
    await unlock_it(road)

    await run(road, bot.go, "house", who=BOB)

    assert await where(db, BOB) == "EN"


async def test_the_house_reads_differently_once_it_is_open(road):
    await unlock_it(road)

    reply = replies(await run(road, bot.look, "house"))

    assert "three heavy brass deadbolts" not in reply
    assert "dark in every window" in reply


async def test_the_player_keeps_the_key(road):
    db, *_ = road

    await unlock_it(road)

    assert await db.carried_of(ALICE, GUILD_A, KEY) == 1


async def test_turning_it_again_says_the_door_is_already_open(road):
    """**Not silence and not a second unlock.** The key's `house_unlocked`
    row has a refusal and no success, which is normally how a writer
    retires a use - but text resolution falls past an empty cell to
    `default`, and this thing's `default` is the one with the success in
    it. So the stop is in code, next to the other gates."""
    await unlock_it(road)

    reply = replies(await run(road, bot.use, "key"))

    assert "The door is already unlocked." in reply
    assert TURNED not in reply


async def test_a_second_holder_gets_the_same_answer(road):
    db, *_ = road
    await fluff(road)
    await a_day_later(db)
    await fluff(road, who=BOB)
    await run(road, bot.take, "key", who=BOB)
    await unlock_it(road)

    reply = replies(await run(road, bot.use, "key", who=BOB))

    assert "The door is already unlocked." in reply


async def test_the_refusal_is_logged_as_already_done(road):
    db, *_ = road
    await unlock_it(road)

    await run(road, bot.use, "key")

    rows = await logged(db, database.USE)
    assert rows[-1].reason == database.ALREADY_DONE


async def test_unlocking_is_a_one_way_door(road):
    """Like the staircase. Nothing re-locks it, and the state is the
    server's rather than the turner's."""
    await unlock_it(road)

    assert world.HOUSE_UNLOCKED in await states.in_force(GUILD_A, BOB)


# --------------------------------------------------------------------------
# And a reset puts it back
# --------------------------------------------------------------------------


async def test_a_reset_relocks_the_door_and_takes_the_keys(road):
    """Free, because `reset_guild` clears every table carrying a
    `guild_id` and both the state and the key rows do - but worth a test,
    because a locked door is the one thing a QA server needs back."""
    db, *_ = road
    await unlock_it(road)

    _, _, halloween, _ = road
    await content_loader.reset_guild(GUILD_A, drop=HOUSE_DROP)
    # `reset_guild` clears `server_config` along with everything else, so
    # the server forgets which channel it lives in. `/reset-haunted-house`
    # writes it straight back and so does this.
    await database.set_announcement_channel(GUILD_A, halloween.id)

    assert world.HOUSE_UNLOCKED not in await states.in_force(GUILD_A, ALICE)
    assert await db.carried_of(ALICE, GUILD_A, KEY) == 0
    assert await keys_on_the_road(db) == 0
    assert LOCKED in replies(await run(road, bot.go, "house"))
