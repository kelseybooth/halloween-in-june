"""The other bed: the one in the Secret Library, and what it does not do.

Drop 50 put a second cat bed in the house and gave it text and nothing
else - a `look`, a `use` and a `take_fail`, with no line in `world.py`
at all. Fluffing it moved no score, earned nothing and refused no
second attempt: the cushion's own sentence came back as often as
anybody typed it. It fluffs properly now, for the same fifteen points
on the same daily clock as the one in the farm stand.

**Most of this file is about what did not come with it**, which is the
half worth pinning. Three parts of the road bed are keyed to the road
rather than to the bed: the yield places into the channel and spends
itself once per player ever, the brass key cannot fall while the house
is unlocked - and it always is, for anybody standing in the library -
and the hint rungs are drop 1 teaching a player what `/use` is. The
fluff travelled. Those did not, and nothing in the row says so.

The one consequence that is neither a port nor an omission has a test
of its own: `thing_uses` is keyed on (player, thing), so the two beds
keep two clocks and a player who can reach the library is worth thirty
points a day rather than fifteen.
"""

import pytest
from sqlalchemy import func, select, update

from conftest import ALICE, BOB, GUILD_A, LAST_DROP
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

LIBRARY = "SE"
ROAD = content_module.CHANNEL_ROOM

FLUFFED = "You fluff the cushion"
REFUSED = "You've done that recently"


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.register_all()
    yield
    achievements.clear()


@pytest.fixture
async def house(db):
    """A server at the last drop, with both beds in it."""
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
        await db.start_game(who, GUILD_A, LIBRARY, await resolve.rooms_open_at_launch())
    await db.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, LAST_DROP)
    # **Not decoration.** Every exit into the Courtyard comes from
    # inside the house (`KC` from the Kitchen, `BC` from the Bedroom),
    # and the only way inside is the `house` exit, which
    # `world.movement_refused_by` turns down until this state is set. A
    # player standing in the Secret Library is therefore always on a
    # server with the front door open - which is what makes the brass
    # key half of the road bed's yield unreachable from in here, rather
    # than merely unwanted.
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    return db, guild, halloween, rooms


async def fluff(house, who=ALICE, room=LIBRARY, thing="cat bed", verb=None):
    """`/use cat bed` in whichever room holds one.

    The road's bed is refused outside the announcement channel, so that
    one is typed in `#halloween` itself and the library's in its own
    thread - and the thread is the object `add_active` made rather than
    a fresh fake, so `posted` below is looking at what the bot posted
    to.
    """
    db, guild, halloween, rooms = house
    await db.update_current_room(who, GUILD_A, room)
    where = (
        halloween
        if room == ROAD
        else next(t for t in halloween.threads if t.name == rooms[room])
    )
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=where)
    await (verb or bot.use).callback(interaction, thing)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


def posted(house, room_id) -> str:
    _, _, halloween, rooms = house
    if room_id == ROAD:
        return "\n".join(line for line in halloween.posted if line)
    thread = next(t for t in halloween.threads if t.name == rooms[room_id])
    return "\n".join(line for line in thread.posted if line)


async def score(who=ALICE) -> int:
    return await database.get_relationship(who, GUILD_A)


async def loose_things() -> int:
    """Everything on a floor or in a container, anywhere on the server.

    A count rather than a list, because the question every yield test
    asks is whether the bed put something somewhere - and the road is
    where it would have gone, which is not a room this file visits.
    """
    async with database._require_session()() as session:
        return await session.scalar(
            select(func.coalesce(func.sum(database.RoomContents.count), 0)).where(
                database.RoomContents.guild_id == GUILD_A
            )
        )


async def drift_stamp(who=ALICE):
    async with database._require_session()() as session:
        return await session.scalar(
            select(database.User.last_cat_interaction_date).where(
                database.User.id == who, database.User.guild_id == GUILD_A
            )
        )


# --------------------------------------------------------------------------
# The fluff, which is the whole of what travelled
# --------------------------------------------------------------------------


async def test_the_cushion_can_be_fluffed(house):
    assert FLUFFED in replies(await fluff(house))


async def test_it_is_worth_the_same_fifteen(house):
    assert await score() == 0

    await fluff(house)

    assert await score() == world.BED_FLUFF


async def test_an_alias_works(house):
    """`empty cat bed` and `bed` as well as the name, and `cat bed`
    reaching this one rather than the road's is the whole of what makes
    the row addressable from in here."""
    assert FLUFFED in replies(await fluff(house, thing="empty cat bed"))


async def test_a_second_fluff_the_same_day_is_refused(house):
    """**The thing that was missing.** Without the column the cushion's
    own sentence came back every time it was typed, which was harmless
    only because nothing moved behind it. It is not harmless now.

    The row carries no `use_fail` of its own, so the refusal is the
    house default - which is the arrangement the road bed has had since
    drop 1, with its own line, and the one the work order asked to be
    copied rather than rewritten.
    """
    await fluff(house)

    interaction = await fluff(house)

    assert REFUSED in replies(interaction)
    assert await score() == world.BED_FLUFF


async def test_the_room_watches_the_fluff(house):
    """Public and private both, the road bed's arrangement: the room is
    told the event and the person who did it gets the cushion's text.

    `bed_fluff.public` is reused rather than written a second time,
    which was the call made on 12 November. It is why the library's
    thread reads "the cat bed" for a thing named *empty cat bed*.
    """
    interaction = await fluff(house)

    assert "fluffs the cat bed. The cat approves." in posted(house, LIBRARY)
    assert FLUFFED in replies(interaction)


async def test_a_refused_fluff_announces_nothing(house):
    await fluff(house)
    before = len(posted(house, LIBRARY))

    await fluff(house)

    assert len(posted(house, LIBRARY)) == before


# --------------------------------------------------------------------------
# Two beds, two clocks
# --------------------------------------------------------------------------


async def test_the_two_beds_keep_two_cooldowns(house):
    """**Thirty points a day, not fifteen**, for anybody who can reach
    the library.

    `thing_uses` is keyed on (player, thing), so this falls out of the
    schema rather than being decided anywhere - which is exactly why it
    is written down here. It is the one consequence of giving the
    second bed the first one's mechanic that neither row shows.
    """
    await fluff(house, room=LIBRARY)
    assert await score() == world.BED_FLUFF

    await fluff(house, room=ROAD)

    assert await score() == world.BED_FLUFF * 2


async def test_each_bed_refuses_on_its_own_clock(house):
    """Fluffing one does not refuse the other, and each refuses in its
    own words.

    The road's cushion has a `use_fail` of its own, written for it at
    drop 1: *the bed already looks fluffy and cozy*. The library's has
    none, so it gets `use_fail.cooldown` from the house - which is the
    one thing here that is a fallback rather than a copy, and is worth
    knowing before anybody reads the two side by side.
    """
    await fluff(house, room=ROAD)

    assert FLUFFED in replies(await fluff(house, room=LIBRARY))
    assert "already looks fluffy" in replies(await fluff(house, room=ROAD))
    assert REFUSED in replies(await fluff(house, room=LIBRARY))


async def test_each_room_s_bed_is_the_one_that_answers(house):
    """Two rows share the alias `cat bed`, in two rooms, and `thing_uses`
    is where the answer shows: the stamped row is the bed that was
    actually in the room.

    Asserted on the table rather than on the reply, because a first-ever
    fluff on the road suppresses its private line in favour of the
    public yield - which says nothing about which row resolved.
    """
    await fluff(house, room=LIBRARY)

    assert await database.last_used(ALICE, GUILD_A, world.EMPTY_CAT_BED)
    assert await database.last_used(ALICE, GUILD_A, world.CAT_BED) is None

    await fluff(house, room=ROAD)

    assert await database.last_used(ALICE, GUILD_A, world.CAT_BED)


# --------------------------------------------------------------------------
# What stayed on the road
# --------------------------------------------------------------------------


async def test_nothing_falls_out_of_this_one(house):
    """`world.dislodge_from_bed` places into `CHANNEL_ROOM` and spends
    `bed_stash_given` once per player ever. Called from the library it
    would drop a toy twenty rooms away and take the player's one turn
    at it to do so."""
    before = await loose_things()

    await fluff(house)

    assert await loose_things() == before
    assert not await database.has_been_told(GUILD_A, ALICE, world.BED_STASH)


async def test_the_yield_is_never_consulted(house, monkeypatch):
    """**Neither half of it**, and this is the stronger claim: not that
    the yield declines to give anything, but that the handler does not
    ask.

    The key half would decline anyway. `_a_key_falls_out` returns early
    while the house is unlocked, and the library is only reachable
    through an unlocked house, so that branch is dead from in here by
    construction - see the fixture. The toy half would not decline; it
    would place a crinkle ball on the road and spend the player's one
    turn at it.
    """

    def explode(*args, **kwargs):
        raise AssertionError("the library bed reached into the road's cushion")

    monkeypatch.setattr(world, "dislodge_from_bed", explode)

    assert FLUFFED in replies(await fluff(house))
    assert await score() == world.BED_FLUFF


async def test_it_does_not_spend_the_road_bed_s_one_yield(house):
    """The flag is untouched, so the toy is still waiting in the farm
    stand cushion for a player who has fluffed this one every day."""
    await fluff(house, room=LIBRARY)

    await fluff(house, room=ROAD)

    assert await database.has_been_told(GUILD_A, ALICE, world.BED_STASH)


async def test_it_does_not_earn_fluffed_to_perfection(house):
    """A drop 1 award for a drop 1 cushion. The library bed pays the
    points and leaves the achievement where it was written - the choice
    made on 12 November, when re-keying it to either bed was the other
    option on the table."""
    await fluff(house)

    earned = await database.player_achievements_of(GUILD_A, ALICE)
    assert "fluffed_to_perfection" not in earned


async def test_the_road_bed_still_earns_it(house):
    await fluff(house, room=ROAD)

    earned = await database.player_achievements_of(GUILD_A, ALICE)
    assert "fluffed_to_perfection" in earned


async def test_it_does_not_close_the_road_s_hint_rung(house):
    """`did.use_cat_bed` retires *Things can be used, too. Try /use cat
    bed* - drop 1 teaching `/use` to somebody who has not met it. A
    player standing in the Secret Library is not that player, and
    closing the rung from here would retire a nudge nobody read."""
    await fluff(house)

    assert not await database.has_been_told(GUILD_A, ALICE, hints.DID_USE_BED)


async def test_it_is_still_not_takeable(house):
    """The fluff is all that changed. `take_fail` is the answer this
    row has given since it shipped."""
    interaction = await fluff(house, thing="cat bed", verb=bot.take)

    assert "where a cat would expect to find it" in replies(interaction)


# --------------------------------------------------------------------------
# Reaching for the cat
# --------------------------------------------------------------------------


async def test_it_counts_as_turning_up(house):
    """The nightly drift asks whether anybody came, and fluffing the
    bed she has not slept in is coming."""
    assert await drift_stamp() is None

    await fluff(house)

    assert await drift_stamp() == database.pacific_today()


async def test_a_refused_fluff_still_counts_as_turning_up(house):
    """Stamped on the attempt, like the road bed: a player turned away
    inside their own window still turned up."""
    await fluff(house)
    async with database._require_session()() as session:
        await session.execute(
            update(database.User)
            .where(database.User.id == ALICE, database.User.guild_id == GUILD_A)
            .values(last_cat_interaction_date=None)
        )
        await session.commit()

    await fluff(house)  # refused, inside the window

    assert await drift_stamp() == database.pacific_today()


async def test_it_is_reaching_for_the_cat(house):
    """`triggers._is_the_cat`, which is the question *Lucky Black Cat*
    asks on 27 October."""
    assert await triggers._is_the_cat(world.EMPTY_CAT_BED)
    assert await triggers._is_the_cat(world.CAT_BED)
