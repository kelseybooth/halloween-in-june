"""Drop 40: coming down the ivy badly, which is a tenth of the time.

A climb down from the bedroom window rolls `ivy_fall_percent`, default
**10** - the design proposed 5 and Kelsey raised it before it shipped,
on the grounds that the mechanic had never existed so nobody had ever
fallen. Climbing up never rolls: going down starts with your whole
weight on a handful of ivy, and coming up ends with you hauling
yourself over a sill.

Nobody is hurt. The player still arrives, up to three things come out
of their bag into the herb garden, a full watering can arrives empty,
and their hands shake until they eat something or half an hour passes.

**The roll is driven by the config and not by a monkeypatched
`random`.** 100 always falls and 0 never does, which tests the key a
server would actually turn as well as the behaviour behind it.

**Why the roll is pure and the cost is not.** Both lines a fall changes
are written before the player is moved - the arrival line is what
admits them to the Courtyard thread - so the roll has to be answerable
without writing, and the spill has to wait until they are standing
where it lands. A post that failed would otherwise leave somebody's
belongings in a room they never reached.
"""

import pytest
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select, update

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import resolve
import states
import triggers
import world


THIS_DROP = 40

LANDED = "You land in the lavender"
CLIMBED_DOWN = "swing a leg over the sill"
CAN_WENT_OVER = "lands upside down in the lavender"
PUBLIC = "a lot faster than they meant to"
SHAKY = "hands are still a little shaky"


@pytest.fixture
async def house(db, monkeypatch):
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    await db.set_setting(GUILD_A, resolve.DROP_KEY, THIS_DROP)
    # **Without this the two awards are silently never considered.**
    # `achievements._BY_HOOK` starts empty and `bot` fills it on startup,
    # which a test does not run - so an unregistered hook is not an error,
    # it is a predicate nobody ever asks. The fixture has to do what
    # startup does, the way `test_the_ladder` does.
    triggers.register_all()
    await content_loader.load_content(content_module.load_files(), guild_ids=[GUILD_A])
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    await states.set_server_state(GUILD_A, world.STAIRS_UPPER)
    await states.set_server_state(GUILD_A, world.STAIRS_REPAIRED)
    for who in (ALICE, BOB):
        await db.start_game(who, GUILD_A, "EN", await resolve.rooms_open_at_launch())
    # The window open for both, which is what makes the ivy usable at all.
    for who in (ALICE, BOB):
        await states.set_player_state(GUILD_A, who, world.WINDOW_OPEN)
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


async def always_falls(db):
    await db.set_setting(GUILD_A, world.IVY_FALL_PERCENT, 100)


async def never_falls(db):
    await db.set_setting(GUILD_A, world.IVY_FALL_PERCENT, 0)


async def carry(db, thing_id, count=1, who=ALICE):
    async with db._require_session()() as session:
        existing = await session.scalar(
            select(database.PlayerInventory.count).where(
                database.PlayerInventory.guild_id == GUILD_A,
                database.PlayerInventory.user_id == who,
                database.PlayerInventory.thing_id == thing_id,
            )
        )
        if existing is None:
            session.add(
                database.PlayerInventory(
                    guild_id=GUILD_A, user_id=who, thing_id=thing_id, count=count
                )
            )
        else:
            await session.execute(
                update(database.PlayerInventory)
                .where(
                    database.PlayerInventory.guild_id == GUILD_A,
                    database.PlayerInventory.user_id == who,
                    database.PlayerInventory.thing_id == thing_id,
                )
                .values(count=count)
            )
        await session.commit()


async def floor_of(room) -> dict:
    return dict(await database.loose_here(GUILD_A, room))


async def earned(achievement_id, who=ALICE) -> bool:
    return achievement_id in await database.player_achievements_of(GUILD_A, who)


async def where_is(who=ALICE) -> str:
    return (await database.get_game_state(who, GUILD_A)).current_room


async def next_command(house, who=ALICE, room="CO"):
    """Whatever the player does next, which is when a lazy award lands.

    `on_command` is fired by `on_app_command_completion`, a discord.py
    listener - so calling a command's callback the way every other test
    here does never reaches it. The listener has to be called too, the
    way `test_the_ladder` and `test_the_watering_can` call it.
    """
    db, guild, _, _ = house
    await db.update_current_room(who, GUILD_A, room)
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=place(house, room))
    await bot.look.callback(interaction, "oak tree")
    await bot.on_app_command_completion(interaction, bot.look)

async def back_date(db, minutes, who=ALICE):
    """The QA clock moves whole days, so half an hour has to be written."""
    async with db._require_session()() as session:
        await session.execute(
            update(database.PlayerState)
            .where(
                database.PlayerState.guild_id == GUILD_A,
                database.PlayerState.user_id == who,
                database.PlayerState.state == world.SHAKEN,
            )
            .values(
                set_at=await database.server_now(GUILD_A) - timedelta(minutes=minutes)
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# The roll


async def test_the_default_is_ten_not_the_five_the_doc_proposed(house):
    assert await database.get_setting(GUILD_A, world.IVY_FALL_PERCENT) == 10
    assert world.IVY_FALL_PERCENT_DEFAULT == 10


async def test_a_fall_still_arrives_in_the_courtyard(house):
    await always_falls(house[0])

    reply = await run(house, bot.use, "ivy", room="BE")

    assert LANDED in reply
    assert CLIMBED_DOWN not in reply
    assert await where_is() == "CO"


async def test_and_without_the_roll_it_is_an_ordinary_climb(house):
    await never_falls(house[0])

    reply = await run(house, bot.use, "ivy", room="BE")

    assert CLIMBED_DOWN in reply
    assert LANDED not in reply
    assert not await states.has(GUILD_A, ALICE, world.SHAKEN)


async def test_climbing_up_never_falls_however_the_dice_are_set(house):
    """The design's call, and the roll does not even happen."""
    await always_falls(house[0])
    await run(house, bot.use, "ivy", room="BE")
    await database.clear_player_state(GUILD_A, ALICE, world.SHAKEN)

    reply = await run(house, bot.use, "ivy", room="CO")

    assert LANDED not in reply
    assert await where_is() == "BE"
    assert not await states.has(GUILD_A, ALICE, world.SHAKEN)


# ---------------------------------------------------------------------------
# What it costs


async def test_up_to_three_things_come_out_of_the_bag(house):
    await always_falls(house[0])
    for thing in ("crinkle_ball", "feather_wand", "candle_stub", "silver_spoon"):
        await carry(house[0], thing)
    # The Courtyard's floor is not empty to begin with - the ladder
    # stands there and the watering can sits by the garden - so a spill
    # is a delta rather than a total.
    before = sum((await floor_of("CO")).values())

    await run(house, bot.use, "ivy", room="BE")

    after = sum((await floor_of("CO")).values())
    assert after - before == world.SPILL_AT_MOST


async def test_and_a_bag_with_nothing_spillable_in_it_still_falls(house):
    """The copy says "a few things" and names none, which is why it can."""
    await always_falls(house[0])

    reply = await run(house, bot.use, "ivy", room="BE")

    assert LANDED in reply
    assert await states.has(GUILD_A, ALICE, world.SHAKEN)


async def test_the_gourmet_can_never_spills(house):
    """One per player ever, so a dice roll is the wrong way to lose it."""
    await always_falls(house[0])
    await carry(house[0], "cat_food_gourmet")

    await run(house, bot.use, "ivy", room="BE")

    assert "cat_food_gourmet" not in await floor_of("CO")
    assert await database.carried_of(ALICE, GUILD_A, "cat_food_gourmet") == 1


async def test_a_full_watering_can_lands_empty_and_stays_in_the_bag(house):
    await always_falls(house[0])
    await carry(house[0], world.WATERING_CAN)
    await database.set_thing_state(GUILD_A, world.WATERING_CAN, world.CAN_FULL)

    reply = await run(house, bot.use, "ivy", room="BE")

    assert CAN_WENT_OVER in reply
    assert await world.can_level(GUILD_A) == world.CAN_EMPTY
    assert await database.carried_of(ALICE, GUILD_A, world.WATERING_CAN) == 1
    assert world.WATERING_CAN not in await floor_of("CO")


async def test_but_a_can_that_was_not_full_says_nothing_about_it(house):
    await always_falls(house[0])
    await carry(house[0], world.WATERING_CAN)
    await database.set_thing_state(GUILD_A, world.WATERING_CAN, world.CAN_EMPTY)

    reply = await run(house, bot.use, "ivy", room="BE")

    assert LANDED in reply
    assert CAN_WENT_OVER not in reply


# ---------------------------------------------------------------------------
# What the room sees


async def test_the_courtyard_sees_the_fall_and_the_bedroom_the_usual_departure(house):
    await always_falls(house[0])

    await run(house, bot.use, "ivy", room="BE")

    assert PUBLIC in posted(house, "CO")
    assert "climbs out of the bedroom window" in posted(house, "BE")


async def test_and_the_public_line_still_carries_the_mention(house):
    """Load-bearing, not cosmetic: the arrival line is what admits them.

    A fall line with a plain name would leave the player outside the
    thread it says they are lying in.
    """
    await always_falls(house[0])

    await run(house, bot.use, "ivy", room="BE")

    assert f"<@{ALICE}>" in posted(house, "CO")


# ---------------------------------------------------------------------------
# Shaky hands


async def test_a_fall_leaves_them_unable_to_take_anything(house):
    await always_falls(house[0])
    await run(house, bot.use, "ivy", room="BE")

    reply = await run(house, bot.take, "herbs", room="CO")

    assert SHAKY in reply


async def test_until_they_eat_something(house):
    await always_falls(house[0])
    await run(house, bot.use, "ivy", room="BE")
    await carry(house[0], "dark_chocolate")

    reply = await run(house, bot.use, "dark chocolate", room="CO")

    assert "the world settles back into place" in reply
    assert not await states.has(GUILD_A, ALICE, world.SHAKEN)


async def test_and_each_snack_has_its_own_words(house):
    await always_falls(house[0])
    await run(house, bot.use, "ivy", room="BE")
    await carry(house[0], "frozen_burrito")

    reply = await run(house, bot.use, "burrito", room="CO")

    assert "Aunt Sue would be proud" in reply
    # The burrito's own line is not replaced by the one about hands.
    assert "popsicle" in reply


async def test_or_until_half_an_hour_has_gone_by(house):
    await always_falls(house[0])
    await run(house, bot.use, "ivy", room="BE")

    await back_date(house[0], 31)

    await run(house, bot.take, "herbs", room="CO")

    assert await database.carried_of(ALICE, GUILD_A, "herbs") == 1
    assert not await states.has(GUILD_A, ALICE, world.SHAKEN)


# ---------------------------------------------------------------------------
# Not with a ladder


@pytest.mark.parametrize("room", ["BE", "CO"])
async def test_the_ivy_refuses_anybody_carrying_the_ladder(house, room):
    await carry(house[0], world.LADDER)

    reply = await run(house, bot.use, "ivy", room=room)

    assert "a third hand, and possibly a fourth" in reply
    assert await where_is() == room


async def test_and_go_refuses_it_the_same_way(house):
    """One check inside `_use_exit`, so the two verbs cannot drift."""
    await carry(house[0], world.LADDER)

    reply = await run(house, bot.go, "ivy", room="BE")

    assert "a third hand, and possibly a fourth" in reply
    assert await where_is() == "BE"


# ---------------------------------------------------------------------------
# The two awards


async def test_stuck_the_landing_on_a_first_fall(house):
    await always_falls(house[0])

    await run(house, bot.use, "ivy", room="BE")

    assert await earned("stuck_the_landing")


async def test_walk_it_off_arrives_on_the_next_command_not_on_the_clock(house):
    """What choosing lazy expiry over a sweep costs, asserted.

    Nothing is awake at the thirty-minute mark, so the award waits for
    the player to do something - which is also why it is on the widest
    hook there is.
    """
    await always_falls(house[0])
    await run(house, bot.use, "ivy", room="BE")
    await back_date(house[0], 31)

    assert not await earned("walk_it_off")

    await next_command(house)

    assert await earned("walk_it_off")


async def test_but_not_for_somebody_who_ate_their_way_out(house):
    """The whole reason the expired row is left in the table."""
    await always_falls(house[0])
    await run(house, bot.use, "ivy", room="BE")
    await carry(house[0], "candy")
    await run(house, bot.use, "candy", room="CO")

    # Through the listener, or this would pass without ever asking:
    # `on_command` fires from `on_app_command_completion`, so a bare
    # callback cannot award *Walk It Off* whatever the state says.
    await next_command(house)

    assert await earned("stuck_the_landing")
    assert not await earned("walk_it_off")
