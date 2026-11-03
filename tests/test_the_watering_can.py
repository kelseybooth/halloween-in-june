"""Drop 30's watering can: four levels, three rooms, and both hands.

The can is the first thing in the game with a state of its own. Every
other state belongs to a player or to the whole server, and both of those
are things that have *become true* - permanent, never cleared, because the
staircase does not un-repair. A can's level goes backwards all day, so it
lives in `thing_states` instead, one row per server per thing, and
`phrasing.say` reads it in front of the player's states.

**What that buys, and why most of this file is about text.** The can's
`look`, `take` and `drop` are four rows in `thing_text` keyed on the
level, read by the ordinary resolution with no handler knowing anything
about water. Only `use` is special, and it is special because it is the
one line in the game that depends on two axes at once - the room decides
whether you are watering, filling or just holding a can, and the level
decides what that looks like. So it comes out of the defaults, chosen in
`world`, and arrives through `Effect.say`.

**The hands are the other half.** A full can fills them the way the
ladder does, and the block lifts two ways rather than the ladder's one:
put it down, or water with it until it is no longer full.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember
from test_world import carry

import achievements
import bot
import content as content_module
import content_loader
import database
import resolve
import states
import telemetry
import triggers
import world


THIS_DROP = 30

RAINWATER = "an inch of rainwater in the bottom"
DRY = "dry inside"
HALF = "about half full"
BRIM = "filled to the brim"

POUR_RAINWATER = "that's all of it"
POUR_FULL = "long, even shower"
POUR_HALF = "until the can runs dry"
ONE_DROP = "One drop comes out"
FILLED = "all the way to the brim"
ALREADY_FULL = "watering the kitchen floor"
NOTHING_TO_WATER = "Nothing in here does"
ITS_EMPTY = "It's empty."
BOTH_HANDS = "need a free hand"


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.register_all()
    triggers.forget_arrivals()
    yield
    achievements.clear()


@pytest.fixture(autouse=True)
def forget_admissions():
    bot._ADMITTING.clear()
    yield
    bot._ADMITTING.clear()


@pytest.fixture
async def courtyard(db, monkeypatch):
    """Drop 30, the can standing in the Courtyard where the loader puts it.

    **The drop is set before the load and the load is told the guild**, for
    the reason `test_the_ladder`'s fixture is: this one needs stock on the
    floor, the loader places into the guilds `users` has seen, and it
    judges arrival from the pointer. Loading first places nothing.

    Drop 30 and not 31, so the ladder does not exist here. That is
    deliberate: the ladder's half of the hands rule is its own file's, and
    a Courtyard holding both would let a test pass on the wrong one.
    """
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    await db.set_setting(GUILD_A, resolve.DROP_KEY, THIS_DROP)
    await content_loader.load_content(
        content_module.load_files(), guild_ids=[GUILD_A]
    )
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    for who in (ALICE, BOB):
        await db.start_game(who, GUILD_A, "EN", await resolve.rooms_open_at_launch())
        await db.notice(GUILD_A, who, content_module.FED_THE_CAT)
    monkeypatch.setattr(
        bot,
        "bot",
        SimpleNamespace(
            guilds=[guild],
            get_guild=lambda gid: guild if gid == GUILD_A else None,
        ),
    )
    return db, guild, halloween, rooms


def thread(courtyard, room):
    _, _, halloween, rooms = courtyard
    if room == content_module.CHANNEL_ROOM:
        return halloween
    return next(t for t in halloween.threads if t.name == rooms[room])


async def run(courtyard, command, arg=None, *, room, who=ALICE):
    db, guild, _, _ = courtyard
    await db.update_current_room(who, GUILD_A, room)
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=thread(courtyard, room))
    args = () if arg is None else (arg,)
    await command.callback(interaction, *args)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


async def used(courtyard, room, who=ALICE) -> str:
    return replies(await run(courtyard, bot.use, "watering can", room=room, who=who))


async def fetched(courtyard, who=ALICE) -> None:
    """Out of the Courtyard, which is where it stands.

    `to_hand_in_room` makes the can usable where it is, like the
    ladder - but only where it *is*. Using it anywhere else means
    carrying it there, which is most of this file.
    """
    await run(courtyard, bot.take, "watering can", room="CO", who=who)


async def looked(courtyard, room, who=ALICE) -> str:
    return replies(await run(courtyard, bot.look, "watering can", room=room, who=who))


async def level() -> str:
    return await world.can_level(GUILD_A)


# --------------------------------------------------------------------------
# What the can is, before anybody touches it
# --------------------------------------------------------------------------


async def test_it_starts_with_an_inch_of_rainwater(courtyard):
    """**The starting level is a row that already existed and a row that is
    never written.** An untouched can has nothing in `thing_states`, and
    `default` is the name of the `thing_text` row the resolution reads when
    no state matches - so "untouched" and "back to rainwater" are the same
    thing to read and the first watering is free."""
    assert await level() == world.CAN_RAINWATER
    assert RAINWATER in await looked(courtyard, "CO")


async def test_and_it_is_standing_in_the_courtyard(courtyard):
    """It was a fixture parked at 99 while its levels were designed. One
    copy, takeable, where the loader puts it."""
    db, *_ = courtyard

    await run(courtyard, bot.take, "watering can", room="CO")

    assert await db.carried_of(ALICE, GUILD_A, world.WATERING_CAN) == 1


# --------------------------------------------------------------------------
# The Courtyard: watering
# --------------------------------------------------------------------------


async def test_the_rainwater_is_good_for_one_watering(courtyard):
    reply = await used(courtyard, "CO")

    assert POUR_RAINWATER in reply
    assert await level() == world.CAN_EMPTY
    assert DRY in await looked(courtyard, "CO")


async def test_and_an_empty_can_gets_one_drop(courtyard):
    """Which is the hint, and the reason the empty branch has a line at all
    rather than a refusal: the player is told what is wrong with the can
    and not that the can is wrong."""
    await used(courtyard, "CO")

    reply = await used(courtyard, "CO")

    assert ONE_DROP in reply
    assert await level() == world.CAN_EMPTY


async def test_a_full_can_is_good_for_two(courtyard):
    """**The only level that does not go straight to empty.** A full can
    waters twice, which is what makes the trip to the Kitchen worth making
    and what gives the half-full level something to be."""
    await fetched(courtyard)
    await used(courtyard, "KI")

    first = await used(courtyard, "CO")
    half = await level()
    second = await used(courtyard, "CO")

    assert POUR_FULL in first
    assert half == world.CAN_PARTLY_FULL
    assert POUR_HALF in second
    assert await level() == world.CAN_EMPTY


# --------------------------------------------------------------------------
# The Kitchen: filling
# --------------------------------------------------------------------------


async def test_the_kitchen_fills_it_from_any_level(courtyard):
    await used(courtyard, "CO")
    await fetched(courtyard)

    reply = await used(courtyard, "KI")

    assert FILLED in reply
    assert await level() == world.CAN_FULL
    assert BRIM in await looked(courtyard, "KI")


async def test_but_a_full_can_cannot_be_filled_again(courtyard):
    await fetched(courtyard)
    await used(courtyard, "KI")

    reply = await used(courtyard, "KI")

    assert ALREADY_FULL in reply
    assert await level() == world.CAN_FULL


# --------------------------------------------------------------------------
# Everywhere else: nothing
# --------------------------------------------------------------------------


@pytest.mark.parametrize("room", ["EN", "DI", "LI"])
async def test_nowhere_else_has_anything_to_water(courtyard, room):
    """And the level does not move, which is the half worth pinning: a can
    that quietly emptied itself in the hall would be a bug nobody could
    see until they got to the herbs."""
    await fetched(courtyard)

    reply = await used(courtyard, room)

    assert NOTHING_TO_WATER in reply
    assert await level() == world.CAN_RAINWATER


async def test_an_empty_can_says_so_instead(courtyard):
    """Shorter than the line about looking around, because a player
    holding an empty can already knows what is wrong with it."""
    await used(courtyard, "CO")
    await fetched(courtyard)

    reply = await used(courtyard, "LI")

    assert ITS_EMPTY in reply
    assert NOTHING_TO_WATER not in reply


# --------------------------------------------------------------------------
# Carried or standing there
# --------------------------------------------------------------------------


async def test_it_works_without_being_picked_up(courtyard):
    """The can is in the Also here list and that is enough - unlike the
    ladder, which is set down by the act of climbing it. Nothing here
    takes it first."""
    reply = await used(courtyard, "CO")

    assert POUR_RAINWATER in reply


async def test_and_the_level_belongs_to_the_can_and_not_the_carrier(courtyard):
    """**Which is what makes one can enough for a server.** Alice fills
    it, Bob waters with it: two people cannot disagree about how much
    water is in one can, and a level stored per player would have let them
    fill it twice over."""
    await fetched(courtyard, who=ALICE)
    await used(courtyard, "KI", who=ALICE)
    await run(courtyard, bot.drop, "watering can", room="CO", who=ALICE)

    reply = await used(courtyard, "CO", who=BOB)

    assert POUR_FULL in reply
    assert await level() == world.CAN_PARTLY_FULL


async def test_dropping_a_full_can_keeps_it_full(courtyard):
    """It is the can's water, so putting the can down does not spill it.
    The slosh in the `drop` line is flavour."""
    db, *_ = courtyard
    await fetched(courtyard)
    await used(courtyard, "KI")

    await run(courtyard, bot.drop, "watering can", room="KI")

    assert await db.carried_of(ALICE, GUILD_A, world.WATERING_CAN) == 0
    assert await level() == world.CAN_FULL


@pytest.mark.parametrize(
    "state,phrase",
    [
        (world.CAN_RAINWATER, "Rainwater shifts around"),
        (world.CAN_EMPTY, "weighs almost nothing"),
        (world.CAN_PARTLY_FULL, "water inside sloshes"),
        (world.CAN_FULL, "heaves up the full watering can"),
    ],
)
async def test_each_level_has_its_own_take_line(courtyard, state, phrase):
    """Four rows in `thing_text`, read by the ordinary state resolution
    with nothing in `/take` knowing about water. This is the whole return
    on putting the level in front of the states in `phrasing.say`."""
    await database.set_thing_state(GUILD_A, world.WATERING_CAN, state)

    posted = thread(courtyard, "CO").posted
    await run(courtyard, bot.take, "watering can", room="CO")

    assert any(phrase in line for line in posted)


async def test_the_full_can_is_set_down_clumsily(courtyard):
    """The one `drop` line that is not the hollow clank, which is the only
    reason `drop` is keyed on the level at all."""
    await database.set_thing_state(GUILD_A, world.WATERING_CAN, world.CAN_FULL)
    await run(courtyard, bot.take, "watering can", room="CO")

    await run(courtyard, bot.drop, "watering can", room="CO")

    assert any(
        "onto their feet" in line for line in thread(courtyard, "CO").posted
    )


# --------------------------------------------------------------------------
# What counts as gardening
#
# *Green Thumb* asks whether somebody watered the herbs, and all three
# things `/use watering can` can do are successful uses of the watering
# can - so `thing_uses`, which is what the achievement read until the
# can got levels, cannot tell them apart. The pour writes a `room_deeds`
# row of its own, and these two are the end-to-end half of that: the
# predicate itself is `test_triggers`, which writes the deed directly.
#
# **Written because a mutation survived.** Taking the deed write out of
# `world._use_the_watering_can` left the whole suite green, because
# every test that cared wrote the deed itself.
# --------------------------------------------------------------------------


async def watered(who=ALICE) -> set[str]:
    return await database.rooms_where(
        who, GUILD_A, telemetry.USE, world.WATERING_CAN
    )


async def test_only_a_pour_counts_as_gardening(courtyard):
    await fetched(courtyard)
    await used(courtyard, "KI")
    after_a_fill = await watered()

    await used(courtyard, "CO")

    assert after_a_fill == set()
    assert await watered() == {"CO"}


async def test_and_tipping_an_empty_can_does_not(courtyard):
    """The other thing that looks like watering and is not. One drop
    comes out, which is a hint and not a harvest."""
    await database.set_thing_state(GUILD_A, world.WATERING_CAN, world.CAN_EMPTY)

    reply = await used(courtyard, "CO")

    assert ONE_DROP in reply
    assert await watered() == set()


# --------------------------------------------------------------------------
# Both hands
# --------------------------------------------------------------------------


async def carrying_a_full_can(courtyard) -> None:
    """Fetched from the Courtyard, filled at the Kitchen faucet."""
    await fetched(courtyard)
    await used(courtyard, "KI")


async def test_a_full_can_fills_both_hands(courtyard):
    """The ladder's rule, on a thing that only sometimes fills them."""
    await carrying_a_full_can(courtyard)

    reply = replies(await run(courtyard, bot.pet, room="CO"))

    assert BOTH_HANDS in reply


async def test_and_nothing_else_can_be_picked_up(courtyard):
    await carrying_a_full_can(courtyard)

    reply = replies(await run(courtyard, bot.take, "rattle", room="CO"))

    assert BOTH_HANDS in reply


async def test_nor_used(courtyard):
    """A can of cat food is a `/use`, so the watering can goes down before
    the cat gets fed. The design's call, same as the ladder's."""
    db, *_ = courtyard
    await carry(db, ALICE, GUILD_A, "cat_food_salmon")
    await carrying_a_full_can(courtyard)

    reply = replies(await run(courtyard, bot.use, "salmon", room="CO"))

    assert BOTH_HANDS in reply


async def test_but_the_can_itself_still_works(courtyard):
    """The exception that makes the block escapable: watering is what the
    hands are full *for*, and a player who could not use the thing they
    were holding would be stuck with it until they thought to drop it."""
    await carrying_a_full_can(courtyard)

    reply = await used(courtyard, "CO")

    assert POUR_FULL in reply


async def test_and_so_do_the_doors(courtyard):
    """`/go` has never asked about your arms, so a `/use` on an exit must
    not either - a player who could leave a room one way but not the other
    would be reading a bug. Decided before anything is read, so a doorway
    never costs a lookup."""
    await carrying_a_full_can(courtyard)

    reply = replies(await run(courtyard, bot.use, "back door", room="KI"))

    assert BOTH_HANDS not in reply


async def test_watering_it_down_frees_your_hands(courtyard):
    """**The transition, which is the ladder's rule with an extra way
    out.** A ladder is only let go of; a full can can also be poured down
    to half, and the block has to lift on that without the can leaving the
    player's bag."""
    await carrying_a_full_can(courtyard)
    await used(courtyard, "CO")

    reply = replies(await run(courtyard, bot.pet, room="CO"))

    assert await level() == world.CAN_PARTLY_FULL
    assert BOTH_HANDS not in reply


async def test_and_so_does_putting_it_down(courtyard):
    """The other way out, which is the only one the ladder has."""
    await carrying_a_full_can(courtyard)
    await run(courtyard, bot.drop, "watering can", room="CO")

    reply = replies(await run(courtyard, bot.pet, room="CO"))

    assert BOTH_HANDS not in reply


async def test_a_half_full_can_never_filled_them(courtyard):
    """The level is read on every call rather than cached, and this is the
    assertion that fails if somebody reads "is carrying the can" instead of
    "is carrying it full"."""
    db, *_ = courtyard
    await run(courtyard, bot.take, "watering can", room="CO")

    reply = replies(await run(courtyard, bot.pet, room="CO"))

    assert await db.carried_of(ALICE, GUILD_A, world.WATERING_CAN) == 1
    assert BOTH_HANDS not in reply


# --------------------------------------------------------------------------
# Forgotten, and put down where they stood
#
# **The can came off the ladder's clock on 2 November and onto its
# own.** The ladder's rule asks whether the *player* has gone quiet -
# twenty-four hours with no command - and that was always a poor fit
# here. Climbing sets the ladder down, so a carrier who has not used
# one is about to; watering does not set the can down, so somebody can
# play hard all afternoon with it in their hand while the herbs stay
# dry and nobody else can reach it.
#
# So six hours since the can was last *used*, out of `idle_drop_hours`
# in `things.tsv`, and it fires whether or not its carrier is busy.
# `test_a_busy_player_loses_it_anyway` is the one that would have
# failed under the old rule and is the whole reason for the new one.
# --------------------------------------------------------------------------


async def quiet_for(db, days, who=ALICE):
    """Backdate this player's last command by whole days."""
    now = await database.server_now(GUILD_A)
    async with db._require_session()() as session:
        await session.execute(
            update(database.User)
            .where(database.User.id == who, database.User.guild_id == GUILD_A)
            .values(last_command_at=now - timedelta(days=days))
        )
        await session.commit()


async def unused_for(db, hours, who=ALICE, thing=None):
    """Backdate both halves of the can's own clock.

    Two stamps, because the sweep takes the later of them: `taken_at`
    on the inventory row for when it reached these hands, and
    `last_used_at` in `thing_uses` for the last time it was tipped over
    anything. Backdating one and not the other tests nothing - the
    other one is still `now` and still holds the can.

    The `thing_uses` update is a no-op for a can that has only been
    picked up, which is correct and is why it is not asserted on:
    `take_from_room` writes no use row, so a fetched-and-never-used can
    runs on `taken_at` alone.
    """
    thing = thing or world.WATERING_CAN
    then = await database.server_now(GUILD_A) - timedelta(hours=hours)
    async with db._require_session()() as session:
        await session.execute(
            update(database.PlayerInventory)
            .where(
                database.PlayerInventory.user_id == who,
                database.PlayerInventory.guild_id == GUILD_A,
                database.PlayerInventory.thing_id == thing,
            )
            .values(taken_at=then)
        )
        await session.execute(
            update(database.ThingUse)
            .where(
                database.ThingUse.user_id == who,
                database.ThingUse.guild_id == GUILD_A,
                database.ThingUse.thing_id == thing,
            )
            .values(last_used_at=then)
        )
        await session.commit()


async def floor_of(room) -> dict:
    return dict(await database.loose_here(GUILD_A, room))


async def test_six_hours_unused_sets_the_can_down(courtyard):
    db, *_ = courtyard
    await fetched(courtyard)
    await db.update_current_room(ALICE, GUILD_A, "LI")
    await unused_for(db, 7)

    await bot.idle_sweep.coro()

    assert await db.carried_of(ALICE, GUILD_A, world.WATERING_CAN) == 0
    assert "watering can" in await floor_of("LI")


async def test_but_five_hours_is_not_enough(courtyard):
    """The number is six and the sweep reads it from the file. A rule
    that fired on any gap at all would pass the test above and take the
    can off somebody who put it down for lunch."""
    db, *_ = courtyard
    await fetched(courtyard)
    await unused_for(db, 5)

    await bot.idle_sweep.coro()

    assert await db.carried_of(ALICE, GUILD_A, world.WATERING_CAN) == 1


async def test_a_busy_player_loses_it_anyway(courtyard):
    """**The test the whole rule exists for.**

    This player ran a command a second ago, so the ladder's clock says
    they are here and playing and the old sweep left them alone. The
    herbs do not care: the can has been in their hand unused for seven
    hours either way, and it is the only one in the house.
    """
    db, *_ = courtyard
    await fetched(courtyard)
    await unused_for(db, 7)
    await quiet_for(db, 0)

    await bot.idle_sweep.coro()

    assert await db.carried_of(ALICE, GUILD_A, world.WATERING_CAN) == 0


async def test_and_using_it_restarts_the_clock(courtyard):
    """Seven hours of carrying, then one watering, and it is theirs
    again. `last_used_at` is the later stamp, so a player who is using
    the can keeps it however long they have had it."""
    db, *_ = courtyard
    await fetched(courtyard)
    await unused_for(db, 7)

    await used(courtyard, "CO")
    await bot.idle_sweep.coro()

    assert await db.carried_of(ALICE, GUILD_A, world.WATERING_CAN) == 1


async def test_putting_it_down_and_picking_it_up_restarts_the_clock(courtyard):
    """**The `on_conflict` half of the inventory upsert.**

    A player who has carried the can for seven hours, sets it down and
    immediately picks it up again has a fresh can in their hands as far
    as the sweep is concerned. The row already exists at that point, so
    the stamp has to be written on the conflict branch as well as on
    the insert - and a version that only wrote it on insert would pass
    every other test in this section, because every one of them takes a
    can the player has never held before.
    """
    db, *_ = courtyard
    await fetched(courtyard)
    await unused_for(db, 7)

    await run(courtyard, bot.drop, "watering can", room="CO")
    await fetched(courtyard)
    await bot.idle_sweep.coro()

    assert await db.carried_of(ALICE, GUILD_A, world.WATERING_CAN) == 1


async def test_a_can_the_game_never_timed_stays_put(courtyard):
    """A null `taken_at` is not idleness.

    Every inventory row that predates the column has one, and the sweep
    is explicit that it would rather leave a thing with a player it has
    never timed than take it off them on no evidence. Worth a test
    because the alternative - `NULL < cutoff` being false in SQL - is
    true by accident rather than by the code saying so, and a later
    `coalesce` would quietly reverse it.
    """
    db, *_ = courtyard
    await fetched(courtyard)
    async with db._require_session()() as session:
        await session.execute(
            update(database.PlayerInventory)
            .where(
                database.PlayerInventory.user_id == ALICE,
                database.PlayerInventory.thing_id == world.WATERING_CAN,
            )
            .values(taken_at=None)
        )
        await session.commit()

    await bot.idle_sweep.coro()

    assert await db.carried_of(ALICE, GUILD_A, world.WATERING_CAN) == 1


async def test_and_it_still_has_whatever_was_in_it(courtyard):
    """Nothing spills. The level belongs to the can and the sweep moves
    the can, so there is nothing for it to do about the water - which is
    worth an assertion because a sweep that reset the level would look
    exactly like a sweep that worked."""
    db, *_ = courtyard
    await carrying_a_full_can(courtyard)
    await unused_for(db, 7)

    await bot.idle_sweep.coro()

    assert await level() == world.CAN_FULL


async def test_and_the_room_is_told_it_was_absent_minded(courtyard):
    """**Not "gets tired", which is the other clock's sentence.**

    `exhausted.public` is for a carrier who has gone quiet, and reads
    true of somebody who went to bed holding a ladder. This player has
    been busy all afternoon and simply stopped using the can, so the
    room gets `idle_drop.public` and the word is "absent-mindedly".
    Telling them they got tired would be the sweep describing a day
    nobody had.
    """
    db, *_ = courtyard
    await fetched(courtyard)
    await db.update_current_room(ALICE, GUILD_A, "LI")
    await unused_for(db, 7)

    await bot.idle_sweep.coro()

    said = "\u0020".join(thread(courtyard, "LI").posted)
    assert "absent-mindedly sets the watering can down" in said
    assert "gets tired" not in said


async def test_and_the_carrier_is_told_where_on_their_next_command(courtyard):
    """**The half the room cannot deliver.** The public line goes where
    the can landed, which is no use to the person who left it there -
    they were not looking. So the sweep leaves word, and the next
    command they run says which room."""
    db, *_ = courtyard
    await fetched(courtyard)
    await db.update_current_room(ALICE, GUILD_A, "LI")
    await unused_for(db, 7)
    await bot.idle_sweep.coro()

    interaction = await run(courtyard, bot.look, room="LI")
    await bot.on_app_command_completion(interaction, bot.look)

    assert "watering can" in replies(interaction)
    assert "Living Room" in replies(interaction)


async def test_but_only_once(courtyard):
    """The row is deleted as it is read, so the second command is quiet.
    A notice that repeated would follow somebody around for the rest of
    the evening."""
    db, *_ = courtyard
    await fetched(courtyard)
    await unused_for(db, 7)
    await bot.idle_sweep.coro()
    first = await run(courtyard, bot.look, room="CO")
    await bot.on_app_command_completion(first, bot.look)

    second = await run(courtyard, bot.look, room="CO")
    await bot.on_app_command_completion(second, bot.look)

    assert "You realize" in replies(first)
    assert "You realize" not in replies(second)


# --------------------------------------------------------------------------
# What the log says about the water
#
# The work order asks for the level on every row the can appears in, and
# the reason is that every question about it is a question about change:
# whether the Kitchen trip gets made, how often somebody tips an empty
# can over the herbs and needs telling why. A level before and a level
# after answers those; either alone answers neither.
# --------------------------------------------------------------------------


async def last_row(action, *, actor=database.PLAYER):
    """The newest log row for one action, as (thing, reason, detail)."""
    async with database._require_session()() as session:
        got = await session.execute(
            select(
                database.InteractionLog.thing_id,
                database.InteractionLog.reason,
                database.InteractionLog.detail,
            )
            .where(
                database.InteractionLog.action == action,
                database.InteractionLog.actor == actor,
            )
            .order_by(database.InteractionLog.id.desc())
        )
        return got.first()


async def test_a_fill_logs_the_level_it_came_from(courtyard):
    await fetched(courtyard)

    await used(courtyard, "KI")

    _, _, detail = await last_row(telemetry.USE)
    assert detail == "room=KI level=default->full"


async def test_a_watering_logs_both_sides_of_it(courtyard):
    await carrying_a_full_can(courtyard)

    await used(courtyard, "CO")

    _, _, detail = await last_row(telemetry.USE)
    assert detail == "room=CO level=full->partly_full"


async def test_and_an_empty_tip_logs_itself_going_nowhere(courtyard):
    """Which is the row that matters most of the four that move nothing:
    a player tipping an empty can over the herbs has misread something,
    and how often it happens is how well the hint reads."""
    await database.set_thing_state(GUILD_A, world.WATERING_CAN, world.CAN_EMPTY)

    await used(courtyard, "CO")

    _, _, detail = await last_row(telemetry.USE)
    assert detail == "room=CO level=empty->empty"


async def test_a_take_logs_the_level(courtyard):
    await database.set_thing_state(GUILD_A, world.WATERING_CAN, world.CAN_PARTLY_FULL)

    await fetched(courtyard)

    _, _, detail = await last_row(telemetry.TAKE)
    assert detail == "level=partly_full"


async def test_and_so_does_a_drop(courtyard):
    """"Was it full when they put it down" is most of what the hands
    rule gets tuned on."""
    await carrying_a_full_can(courtyard)

    await run(courtyard, bot.drop, "watering can", room="KI")

    _, _, detail = await last_row(telemetry.DROP)
    assert detail == "level=full"


@pytest.mark.parametrize(
    "action,verb,arg",
    [
        ("pet", "pet", None),
        ("take", "take", "rattle"),
        ("use", "use", "salmon"),
    ],
)
async def test_a_refusal_says_which_thing_filled_the_hands(
    courtyard, action, verb, arg
):
    """Two things can fill them now, and the refusal reads the same
    either way - so without this the row cannot say whether the can or
    the ladder is the one players keep bouncing off.

    **All three verbs, and the third is why `_cannot_take` returns a
    detail at all.** `/pet` and `/use` had the holder in scope already;
    the take path reached its refusal through a table that returned a
    line and a reason and nothing else, so it had to start carrying a
    third thing. A mutation emptying that detail passed the whole suite
    while only `/pet` was covered here.
    """
    db, *_ = courtyard
    await carry(db, ALICE, GUILD_A, "cat_food_salmon")
    await carrying_a_full_can(courtyard)

    await run(courtyard, getattr(bot, verb), arg, room="CO")

    _, reason, detail = await last_row(getattr(telemetry, action.upper()))
    assert reason == telemetry.ARMS_FULL
    assert detail == "holding=watering_can"


async def test_and_the_sweep_says_where_and_how_much(courtyard):
    """A system row rather than a player's. The level is the half that
    cannot be recovered afterwards: the can on the Nursery floor will
    have been filled and emptied twenty times before anybody asks."""
    db, *_ = courtyard
    await carrying_a_full_can(courtyard)
    await db.update_current_room(ALICE, GUILD_A, "LI")
    await unused_for(db, 7)

    await bot.idle_sweep.coro()

    thing_id, _, detail = await last_row(
        telemetry.ABANDONED, actor=database.SYSTEM
    )
    assert thing_id == world.WATERING_CAN
    assert detail == "room=LI level=full rule=unused"
