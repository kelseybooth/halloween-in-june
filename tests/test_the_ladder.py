"""Drop 30: the ladder, which is one object the whole server shares.

It stands in the Courtyard, anybody can carry it anywhere, climbing it
shows each room from above, and having it at hand is the only way to
reach the top fifth of the grand staircase. Six behaviours, and nearly
all of them follow from "there is exactly one of it".

**Why your arms are full.** A ladder on your shoulder is a ladder in
both hands, so `/pet`, `/take` and `/use` refuse while you carry it -
with three exceptions, each of them something a person does while
holding a ladder: climb it, lay a plank in the top steps, or walk
through a door. Feeding is a `/use` of a can, so the ladder goes down
first. That is the design's call and not an oversight.

**Why every climb sets it down.** Climbing a ladder you are carrying
means putting it down and going up it. It is also what keeps the one
ladder moving: a player who uses it at all has already let go.

**Why the cat matters.** One climb in ten she gets to the top first and
keeps it for five minutes. It is the only timed lock in the game, and
the only refusal a player can do nothing about but wait.

**Why there is a sweep.** Because of all of the above, the only way to
hoard the ladder is to pick it up and stop playing without climbing it -
and that stalls the last eighteen planks for everybody. After a day of
silence it is set down where its carrier stands.
"""

import pytest
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select, update

from conftest import ALICE, BOB, GUILD_A
from content import TextRow
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember
from test_loader import a_thing, a_world

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


THIS_DROP = 31

# Where a climb is written for, and a phrase out of each line that no
# other room's says. Read off the files in the test below rather than
# trusted: these are what a player sees, and a typo in a state name
# would quietly serve the default climb in every room.
CLIMBS = {
    "CO": "level with the kitchen stoop",
    "EN": "carvings along the outside of it",
    # Not the scarlet leaves: `leaves` is a thing on the road, so the
    # engine bolds the word and the phrase no longer matches itself.
    "CH": "gray and papery and long empty",
    "KI": "top of the fridge",
    "DI": "like a still life",
    "LI": "all tops of things",
}
ANYWHERE_ELSE = "one abandoned cobweb"
CAT_CLIMB = "she's on the very top"
CAT_PUBLIC = "the cat gets to the top first"
SWAT_TAKE = "a black paw shoots down"
SWAT_USE = "swats you smartly on the head"
ARMS_FULL = "can't figure out how while you're carrying this ladder"
EXHAUSTED = "drops the heavy wooden ladder out of exhaustion"

# What `/look larder` says in the Kitchen, and what `/look ladder` there
# was saying until 6 November. Off `thing_text.tsv`'s pantry row.
PANTRY = "A narrow pantry with a door that won't quite shut"


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
async def house(db, monkeypatch):
    """Drop 30, the door open, Alice and Bob fed and standing in the hall.

    **The drop is set before the load, and the load is told the guild.**
    Unlike every other fixture in the suite, this one needs stock on the
    floor: the ladder is one takeable copy in the Courtyard, which means
    a `room_contents` row written by the loader. The loader places into
    "every guild the database has seen" and reads that off `users`, so
    loading before anybody exists places nothing - and it judges which
    drops have arrived from the pointer, so the pointer has to be at 30
    before rather than after. `conftest` leaves it at 50; writing it
    the way `conftest` does skips `set_current_drop`'s validation,
    which cannot pass until the drops table is loaded.

    `bot.bot` is replaced the way `test_toy_arrival` replaces it, because
    the sweep at the end of this file is a real loop body and needs a
    guild list and a `get_guild` to post through.
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


def place(house, room):
    """The channel for a room, which for the road is the channel itself."""
    _, _, halloween, rooms = house
    if room == content_module.CHANNEL_ROOM:
        return halloween
    return next(t for t in halloween.threads if t.name == rooms[room])


async def run(house, command, arg=None, *, room, who=ALICE):
    db, guild, _, _ = house
    await db.update_current_room(who, GUILD_A, room)
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=place(house, room))
    args = () if arg is None else (arg,)
    await command.callback(interaction, *args)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


def posted(house, room) -> str:
    return "\n".join(place(house, room).posted)


async def carry_it(house, room="CO", who=ALICE):
    """Pick the ladder up the way a player does, out of the Courtyard."""
    return await run(house, bot.take, "ladder", room=room, who=who)


async def climb(house, room, who=ALICE):
    return replies(await run(house, bot.use, "ladder", room=room, who=who))


async def use_it(house, thing, room, who=ALICE):
    """`/use` on something that is not the ladder, for the exceptions."""
    return replies(await run(house, bot.use, thing, room=room, who=who))


async def floor_of(room) -> dict:
    return dict(await database.loose_here(GUILD_A, room))


# --------------------------------------------------------------------------
# A line per room
# --------------------------------------------------------------------------


class _NeverTheCat:
    """The ninety percent. `randint` is what the roll calls."""

    def randint(self, low, high):
        return high


class _AlwaysTheCat:
    def randint(self, low, high):
        return low


@pytest.fixture(autouse=True)
def no_cat(monkeypatch):
    """The cat loses the roll unless a test says otherwise.

    One in ten is a coin the suite would otherwise flip a hundred times
    a run, which is a handful of unexplainable failures a month in
    tests about something else entirely.
    """
    monkeypatch.setattr(world, "random", _NeverTheCat())


@pytest.mark.parametrize("room,phrase", sorted(CLIMBS.items()))
async def test_each_room_has_its_own_climb(house, room, phrase):
    """Six rows, one state each, read off the room the player is in.

    **Nothing holds an `in:CO`.** It is not a state in the sense the
    rest of the game means - nothing sets it and nothing clears it -
    so this is the whole of what proves the prefix is wired: six rooms,
    six different lines, out of one thing's `use` column.
    """
    await carry_it(house)

    assert phrase in await climb(house, room)


async def test_anywhere_else_gets_the_generic_climb(house):
    """Which is what the upstairs rooms read at drop 40 and the library
    at drop 50, until somebody writes them one."""
    await carry_it(house)

    assert ANYWHERE_ELSE in await climb(house, "UH")


async def test_the_room_decides_and_not_where_it_started(house):
    """Carried from the Courtyard to the Kitchen, it is a kitchen climb.
    The obvious reading, and worth pinning: the ladder's row could as
    easily have been keyed on where the thing was placed at load."""
    await carry_it(house)

    reply = await climb(house, "KI")

    assert CLIMBS["KI"] in reply
    assert CLIMBS["CO"] not in reply


def test_a_climb_written_for_no_room_is_caught_at_load():
    """The check behind the six above, as the loader runs it.

    A misspelled room is not an error at runtime - the resolver walks
    past a state nothing matches and falls to `default` - so a typo
    would serve the generic climb everywhere, forever, in silence. The
    shipped files passing says nothing about whether anything is
    watching, which is what this asks.
    """
    world_ = a_world(a_thing("odd_ladder"))
    world_.thing_text.append(
        TextRow(
            entity_id="odd_ladder",
            state=f"{content_module.ROOM_STATE_PREFIX}XX",
            since_drop=1,
            text={"use": "You climb the odd ladder."},
        )
    )

    problems = content_module.validate(world_)

    assert any("in:XX" in problem for problem in problems)


def test_a_climb_written_for_a_real_room_is_fine():
    world_ = a_world(a_thing("odd_ladder"))
    world_.thing_text.append(
        TextRow(
            entity_id="odd_ladder",
            state=f"{content_module.ROOM_STATE_PREFIX}KI",
            since_drop=1,
            text={"use": "You climb the odd ladder."},
        )
    )

    problems = content_module.validate(world_)

    assert not any("in:KI" in problem for problem in problems)


async def test_every_climb_row_names_a_room_that_exists(house):
    """The check behind the six above, asked of the files directly.

    A misspelled room is not an error at runtime - the resolver walks
    past a state nothing matches and falls to `default` - so a typo
    would serve the generic climb everywhere, forever, in silence.

    **Asked of the ladder's own rows, which it was not until now.** It
    collected every `in:` row in the file and compared the lot to
    `CLIMBS`, which was only ever true by coincidence: the nachos and
    the frozen burrito have had `in:KI` rows all along, and KI is a
    climb room too, so they vanished into the set. The music box's
    `in:NU` row is the first one in a room the ladder does not reach,
    and it is what made the coincidence visible.

    The second assertion is the one that was always general, so it
    stays that way: every `in:` row in the file, whosever it is, has to
    name a room that exists.
    """
    parsed = content_module.load_files()
    rooms = {room.room_id for room in parsed.rooms}

    def rooms_named_by(rows):
        return {
            row.state[len(content_module.ROOM_STATE_PREFIX) :]
            for row in rows
            if row.state.startswith(content_module.ROOM_STATE_PREFIX)
        }

    climbs = rooms_named_by(
        row for row in parsed.thing_text if row.entity_id == "ladder"
    )
    every = rooms_named_by(parsed.thing_text)

    assert climbs == set(CLIMBS)
    assert every <= rooms, sorted(every - rooms)


# --------------------------------------------------------------------------
# Full arms
# --------------------------------------------------------------------------


async def test_petting_is_refused_while_carrying_it(house):
    await carry_it(house)

    assert ARMS_FULL in replies(await run(house, bot.pet, room="CO"))


async def test_and_the_pet_does_not_count(house):
    """A refused pet is not a pet. She has not been touched, so the
    meter must not move and the count must not rise."""
    db, *_ = house
    await carry_it(house)
    before = await database.get_relationship(ALICE, GUILD_A)

    await run(house, bot.pet, room="CO")

    assert await database.get_relationship(ALICE, GUILD_A) == before


async def test_taking_anything_is_refused_while_carrying_it(house):
    """Herbs out of the garden, which is a thing a player can actually
    pick up. It is also a source, so this covers the half of `/take`
    that hands over a yield rather than moving an object."""
    await carry_it(house)

    reply = replies(await run(house, bot.take, "herbs", room="CO"))

    assert ARMS_FULL in reply


async def test_but_a_thing_nobody_can_take_says_so_instead(house):
    """**The order inside the refusal table, and the reason for it.**
    Told that their arms were full, a player reaching for the pumpkins
    would reasonably put the ladder down and reach again. The pumpkins'
    own line is the true one and the useful one.
    """
    await carry_it(house)

    reply = replies(await run(house, bot.take, "pumpkins", room="CO"))

    assert ARMS_FULL not in reply


async def test_feeding_is_refused_too(house):
    """**The design's call, written down because it surprises people.**
    A can of cat food is used, not thrown, so the ladder goes down
    before the cat gets fed."""
    await run(house, bot.take, "salmon", room="EN")
    await carry_it(house)

    assert ARMS_FULL in await use_it(house, "salmon", "CO")


async def test_climbing_it_is_allowed(house):
    """The first exception, and the one the whole thing is for."""
    await carry_it(house)

    assert ARMS_FULL not in await climb(house, "CO")


async def test_laying_a_plank_is_allowed(house):
    """The second. Fetching the ladder to the Entryway and then being
    told you cannot use the lumber would make it unfetchable."""
    await carry_it(house)

    assert ARMS_FULL not in await use_it(house, "lumber", "EN")


async def test_walking_through_a_door_is_allowed(house):
    """The third. `/go` never asks about your arms, so a player who
    could leave a room one way and not the other would read as a bug."""
    db, *_ = house
    await carry_it(house)

    reply = await use_it(house, "front door", "EN")

    assert ARMS_FULL not in reply
    assert (await db.get_game_state(ALICE, GUILD_A)).current_room == "CH"


async def test_dropping_it_is_allowed(house):
    """Not an exception at all - `/drop` was never checked - and pinned
    because it is the one way out of a full-arms refusal."""
    await carry_it(house)

    await run(house, bot.drop, "ladder", room="CO")

    assert await database.carried_of(ALICE, GUILD_A, world.LADDER) == 0


async def test_nobody_else_is_affected(house):
    """One player's arms. Bob can pet the cat while Alice hauls the
    ladder around, which the check being per-inventory gives for free
    and which a server-wide lock would have broken."""
    await carry_it(house)

    assert ARMS_FULL not in replies(await run(house, bot.pet, room="CO", who=BOB))


# --------------------------------------------------------------------------
# Every climb sets it down
# --------------------------------------------------------------------------


async def test_a_carried_ladder_ends_up_standing_in_the_room(house):
    await carry_it(house)

    await climb(house, "KI")

    assert await database.carried_of(ALICE, GUILD_A, world.LADDER) == 0
    assert "ladder" in await floor_of("KI")


async def test_a_standing_ladder_can_be_climbed_where_it_stands(house):
    """**`to_hand_in_room`, which is the column that makes this work.**
    The ladder is takeable, and a takeable thing normally has to be in
    your hands to be used - so without the opt-in, `/use ladder` would
    refuse the ladder the player is standing next to and tell them to
    pick it up first.
    """
    assert await database.carried_of(ALICE, GUILD_A, world.LADDER) == 0

    assert CLIMBS["CO"] in await climb(house, "CO")


async def test_and_it_is_still_standing_afterwards(house):
    await climb(house, "CO")

    assert "ladder" in await floor_of("CO")
    assert await database.carried_of(ALICE, GUILD_A, world.LADDER) == 0


# --------------------------------------------------------------------------
# The wasp nest
# --------------------------------------------------------------------------

PIECE = "piece of wasp nest"


async def test_a_climb_on_the_road_knocks_a_piece_down(house):
    await carry_it(house)

    await climb(house, "CH")

    assert (await floor_of("CH")).get(PIECE) == 1


async def test_the_nest_never_runs_out(house):
    """A source in everything but name: three climbs, three pieces. It
    is the one thing the ladder makes, and the design has it
    inexhaustible so that anybody who thinks to carry the ladder
    outside can have the discovery."""
    await carry_it(house)
    for _ in range(3):
        await climb(house, "CH")

    assert (await floor_of("CH"))[PIECE] == 3


async def test_a_climb_anywhere_else_knocks_nothing_down(house):
    """The nest hangs over the road and nowhere else. Every other climb
    is for the view."""
    await carry_it(house)

    await climb(house, "KI")

    assert PIECE not in await floor_of("KI")


async def test_the_piece_is_not_a_yield_of_the_ladder(house):
    """**The trap the content sets on purpose.** `wasp_nest_piece` is
    written in the ladder's `yields` cell so the loader counts the
    piece as obtainable - without it the piece is content with quantity
    zero and no way in. The engine must not read that as a yield: a
    `/take ladder` hands over a ladder.
    """
    await carry_it(house)

    assert await database.carried_of(ALICE, GUILD_A, world.LADDER) == 1
    assert await database.carried_of(ALICE, GUILD_A, world.NEST_PIECE) == 0


async def test_the_piece_can_be_picked_up(house):
    """And by anybody, which is what putting it on the floor is for."""
    await carry_it(house)
    await climb(house, "CH")

    await run(house, bot.take, "piece of wasp nest", room="CH", who=BOB)

    assert await database.carried_of(BOB, GUILD_A, world.NEST_PIECE) == 1


# --------------------------------------------------------------------------
# Hive Five
# --------------------------------------------------------------------------

HIVE_FIVE = "hive_five"


async def earned_by(who=ALICE) -> set:
    return set(await database.player_achievements_of(GUILD_A, who))


async def test_the_first_climb_that_drops_a_piece_earns_it(house):
    await carry_it(house)

    await climb(house, "CH")

    assert HIVE_FIVE in await earned_by()


async def test_a_climb_that_drops_nothing_does_not(house):
    await carry_it(house)

    await climb(house, "DI")

    assert HIVE_FIVE not in await earned_by()


async def test_a_climb_the_cat_takes_does_not(house, monkeypatch):
    """She gets to the top first, so nobody reaches the nest. Both are
    `on_use` of the ladder on the road, which is why the predicate
    reads what the climb reported rather than the thing and the room."""
    await carry_it(house)
    monkeypatch.setattr(world, "random", _AlwaysTheCat())

    await climb(house, "CH")

    assert HIVE_FIVE not in await earned_by()
    assert PIECE not in await floor_of("CH")


async def test_picking_up_somebody_elses_piece_does_not(house):
    """Scavenging, not climbing. The file asks for this in words."""
    await carry_it(house)
    await climb(house, "CH")

    await run(house, bot.take, "piece of wasp nest", room="CH", who=BOB)

    assert HIVE_FIVE not in await earned_by(BOB)


# --------------------------------------------------------------------------
# The cat takes it
# --------------------------------------------------------------------------


@pytest.fixture
async def she_has_it(house, monkeypatch):
    """One climb, lost to the cat, from the Courtyard."""
    monkeypatch.setattr(world, "random", _AlwaysTheCat())
    reply = await climb(house, "CO")
    monkeypatch.setattr(world, "random", _NeverTheCat())
    return reply


async def test_she_gets_the_line_and_the_room_gets_told(house, she_has_it):
    """**Public and private both**, which is the cat bed's arrangement
    rather than the staircase's. The private line is the climb, and six
    of the seven are a view only the climber had; this one is a thing
    the room watched happen."""
    assert CAT_CLIMB in she_has_it
    assert CAT_PUBLIC in posted(house, "CO")


async def test_her_line_replaces_the_rooms(house, she_has_it):
    """She is on top of the ladder, so the climb did not happen. A line
    that said both would have the player level with the kitchen stoop
    and also back on the grass."""
    assert CLIMBS["CO"] not in she_has_it


async def test_nobody_may_take_it_for_five_minutes(house, she_has_it):
    assert SWAT_TAKE in replies(await run(house, bot.take, "ladder", room="CO"))


async def test_nor_climb_it(house, she_has_it):
    assert SWAT_USE in await climb(house, "CO")


async def test_the_lock_is_the_ladder_s_and_not_the_player_s(house, she_has_it):
    """Per thing, which is what a cat sitting on a ladder means: she is
    in everybody's way at once."""
    assert SWAT_USE in await climb(house, "CO", who=BOB)


async def test_and_it_lifts_on_its_own(house, she_has_it):
    db, *_ = house

    await db.set_setting(GUILD_A, database.CLOCK_KEY, 1)

    assert CLIMBS["CO"] in await climb(house, "CO")


async def test_the_swat_pays_nothing_either_way(house, she_has_it):
    """Play, with the claws tucked in. The design is explicit that it
    earns no relationship points in either direction, which is unusual
    enough among the cat's interactions to pin."""
    before = await database.get_relationship(ALICE, GUILD_A)

    await climb(house, "CO")

    assert await database.get_relationship(ALICE, GUILD_A) == before


async def test_a_climb_she_takes_still_sets_the_ladder_down(house, monkeypatch):
    """She took it off their shoulder, so it is hers and not theirs."""
    await carry_it(house)
    monkeypatch.setattr(world, "random", _AlwaysTheCat())

    await climb(house, "KI")

    assert await database.carried_of(ALICE, GUILD_A, world.LADDER) == 0
    assert "ladder" in await floor_of("KI")


# --------------------------------------------------------------------------
# A carrier who goes quiet
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


async def test_a_command_is_stamped(house):
    """Where "still playing" is written down. Any command at all, which
    is the same width as *Familiar* and for the same reason."""
    db, guild, _, _ = house
    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=place(house, "EN"))

    await bot.on_app_command_completion(interaction, SimpleNamespace(name="look"))

    async with db._require_session()() as session:
        stamped = await session.scalar(
            select(database.User.last_command_at).where(
                database.User.id == ALICE, database.User.guild_id == GUILD_A
            )
        )
    assert stamped is not None


async def test_a_day_of_silence_sets_the_ladder_down(house):
    db, *_ = house
    await carry_it(house)
    await db.update_current_room(ALICE, GUILD_A, "KI")
    await quiet_for(db, 2)

    await bot.idle_sweep.coro()

    assert await database.carried_of(ALICE, GUILD_A, world.LADDER) == 0
    assert "ladder" in await floor_of("KI")


async def test_and_says_so_where_it_landed(house):
    """In the room its carrier was standing in, not the one they picked
    it up in. The line names them, so the next person knows who to go
    and find rather than only that a ladder has appeared."""
    db, *_ = house
    await carry_it(house)
    await db.update_current_room(ALICE, GUILD_A, "KI")
    await quiet_for(db, 2)

    await bot.idle_sweep.coro()

    assert EXHAUSTED in posted(house, "KI")


async def test_somebody_still_playing_keeps_it(house):
    db, *_ = house
    await carry_it(house)
    await quiet_for(db, 0)

    await bot.idle_sweep.coro()

    assert await database.carried_of(ALICE, GUILD_A, world.LADDER) == 1


async def test_a_player_with_no_stamp_at_all_keeps_it(house):
    """**Null is no evidence, not idleness.** Every row that existed
    before the stamp shipped has none, and nothing should be taken off
    a player the game has never watched run a command. The cost is that
    such a carrier keeps the ladder until they next do anything."""
    await carry_it(house)

    await bot.idle_sweep.coro()

    assert await database.carried_of(ALICE, GUILD_A, world.LADDER) == 1


async def test_the_ladder_is_not_on_the_things_own_clock(house):
    """**The other side of the split, and the one that pins it.**

    The can and the rattle went onto `idle_drop_hours` on 2 November -
    six hours unused, whether or not their carrier is busy - and the
    ladder deliberately did not. Climbing sets it down, so somebody
    holding one who has not climbed is on their way to the stairs, and
    taking it off them mid-errand would be the sweep interrupting the
    job it exists to protect.

    Seven hours carried, never used, player active a second ago. Under
    the thing's clock that is gone; under the ladder's it is theirs.
    Adding `ladder` to the column, or dropping the `SET_DOWN_WHEN_IDLE`
    guard that skips things with their own clock, fails here.
    """
    db, *_ = house
    await carry_it(house)
    await quiet_for(db, 0)
    then = await database.server_now(GUILD_A) - timedelta(hours=7)
    async with db._require_session()() as session:
        await session.execute(
            update(database.PlayerInventory)
            .where(
                database.PlayerInventory.user_id == ALICE,
                database.PlayerInventory.thing_id == world.LADDER,
            )
            .values(taken_at=then)
        )
        await session.commit()

    await bot.idle_sweep.coro()

    assert await database.carried_of(ALICE, GUILD_A, world.LADDER) == 1


async def test_a_ladder_nobody_is_carrying_is_left_alone(house):
    """It is standing in the Courtyard where the loader put it, and the
    sweep is about shoulders rather than about floors."""
    await bot.idle_sweep.coro()

    assert "ladder" in await floor_of("CO")
    assert EXHAUSTED not in posted(house, "CO")


# ------------------------------------------------------------------------
# What a climb leaves behind
#
# *Rung by Rung* wants the ten places, and the only record of where a
# climb happened used to be a string in the log. These two are the write
# that replaced it; the achievement itself is `test_triggers`.
# ------------------------------------------------------------------------


async def test_a_climb_is_remembered_by_its_room(house):
    """One deed per room, however many times it is climbed."""
    db, *_ = house
    await carry_it(house)

    await climb(house, "CO")
    await climb(house, "CO")

    assert await db.rooms_where(
        ALICE, GUILD_A, telemetry.USE, world.LADDER
    ) == {"CO"}


async def test_but_a_climb_she_takes_is_not(house, monkeypatch):
    """**The design says cat climbs do not count, and this is where
    that is decided.** She goes up and the player does not, so there is
    nothing to have seen from the top - and the handler cannot tell the
    difference, because a climb she takes is still a successful `/use`
    with a line of its own. The branch returns before the write rather
    than writing a row the predicate would have to filter."""
    db, *_ = house
    monkeypatch.setattr(world, "random", _AlwaysTheCat())
    await carry_it(house)

    await climb(house, "CO")

    assert await db.rooms_where(
        ALICE, GUILD_A, telemetry.USE, world.LADDER
    ) == set()



# ------------------------------------------------------------------------
# Walking away from it, and asking where it went
#
# The two behaviours at the top of this file meet here and the meeting
# is what a playtester hit on 6 November: every climb sets the ladder
# down, and anybody can carry it anywhere - so the room you climbed in
# is where it stays, and the room you walk into has no ladder in it.
#
# Asking about it there used to describe the pantry, which answers to
# `larder`, one edit from `ladder`. She asked twice. The guard itself is
# `reach.find`'s; these four are what she typed, in the rooms she typed
# it in.
# ------------------------------------------------------------------------


async def test_the_kitchen_says_the_ladder_is_not_here(house):
    """Her run: take it, climb it, walk next door, ask where it went.
    The refusal is what sent her back to the Courtyard, and it is true -
    she had left it there, because climbing it is what puts it down."""
    await carry_it(house)
    await climb(house, "CO")

    reply = replies(await run(house, bot.look, "ladder", room="KI"))

    assert "ladder" in await floor_of("CO")
    assert "don't see a ladder here" in reply


async def test_rather_than_describing_the_pantry(house):
    """The sentence she was given instead, quoted off the file so that a
    change which makes it reachable from `ladder` again fails here."""
    await carry_it(house)
    await climb(house, "CO")

    reply = replies(await run(house, bot.look, "ladder", room="KI"))

    assert PANTRY in replies(await run(house, bot.look, "larder", room="KI"))
    assert PANTRY not in reply


async def test_and_the_pantry_still_answers_to_larder(house):
    """The alias is a good word for a pantry and keeps it. The bug was
    never the alias - it was a correction nobody asked for."""
    reply = replies(await run(house, bot.look, "larder", room="KI"))

    assert "don't see" not in reply


async def test_and_carrying_it_in_describes_the_ladder(house):
    """The climb before hers worked, which is why she was sure the game
    was wrong rather than that she had put it down."""
    await carry_it(house)

    reply = replies(await run(house, bot.look, "ladder", room="KI"))

    assert "heavy, it's awkward" in reply



# ------------------------------------------------------------------------
# The other five, 6 November
#
# One work order, five achievements, three hooks. They are all here
# rather than in `test_triggers` because all five turn on what a handler
# writes - the tallies and the set-down offer - and a predicate tested on
# a hand-built context would pass while no command ever wrote the number
# it reads. `test_triggers` has the conditions; this has the mechanics.
#
# The work order's acceptance tests are the spine of this section: with
# an audience and one fewer, three cat climbs and somebody else's swats,
# five minutes and eleven, four moves and a drop after three.
# ------------------------------------------------------------------------

KING = "king_of_the_mountain"
SECOND = "second_place"
PASS_IT_ON = "pass_it_on"
HEAVY = "heavy_lifting"
HEIGHTS = "head_for_heights"


async def an_audience_of(house, how_many, room, *, awake=True):
    """Players standing in a room, stamped as having just done something.

    Awake means stamped: `active_others_in_room` reads
    `last_command_at`, because where somebody is standing says nothing
    about whether anybody is at the keyboard.
    """
    db, *_ = house
    watchers = []
    for n in range(how_many):
        who = 300000000000000000 + n
        await db.ensure_user_exists(who, GUILD_A)
        await db.start_game(who, GUILD_A, room, [room])
        await db.update_current_room(who, GUILD_A, room)
        if awake:
            await db.stamp_command(who, GUILD_A)
        watchers.append(who)
    return watchers


async def walk(house, door, room, who=ALICE):
    """One real move, through a real door, with whatever is in the bag."""
    return await use_it(house, door, room, who=who)


async def tally(column, who=ALICE):
    async with database._require_session()() as session:
        return await session.scalar(
            select(getattr(database.User, column)).where(
                database.User.id == who, database.User.guild_id == GUILD_A
            )
        )


async def age_the_offer(minutes):
    """Back-date the standing set-down so the window can be tested.

    **Not the clock offset**, which the lock tests use: `CLOCK_KEY` is
    `clock_offset_days`, so the smallest step it can take is a day and
    it cannot tell five minutes from eleven. Moving the row is the
    honest way to age it, and it is the row the window is read against.
    """
    async with database._require_session()() as session:
        await session.execute(
            update(database.SetDownOffer)
            .where(
                database.SetDownOffer.guild_id == GUILD_A,
                database.SetDownOffer.thing_id == world.LADDER,
            )
            .values(
                at=await database.server_now(GUILD_A) - timedelta(minutes=minutes)
            )
        )
        await session.commit()


async def climb_log(house):
    """Every logged climb of the ladder, oldest first."""
    db, *_ = house
    async with db._require_session()() as session:
        return list(
            (
                await session.scalars(
                    select(database.InteractionLog)
                    .where(
                        database.InteractionLog.guild_id == GUILD_A,
                        database.InteractionLog.thing_id == world.LADDER,
                        database.InteractionLog.action == telemetry.USE,
                    )
                    .order_by(database.InteractionLog.id)
                )
            ).all()
        )


# --- King of the Mountain -------------------------------------------------


async def test_a_climb_with_an_audience_earns_it(house):
    """The work order's first acceptance test: enough other testers
    active in the room, and a climb earns it."""
    db, *_ = house
    await db.set_config(GUILD_A, "captive_audience_size", "2")
    await an_audience_of(house, 2, "CO")

    await climb(house, "CO")

    assert KING in await earned_by()


async def test_and_one_fewer_does_not(house):
    """The edge, not a spare case. Two watchers against a bar of three
    is the shape the rattle's tests use for the same reason."""
    db, *_ = house
    await db.set_config(GUILD_A, "captive_audience_size", "3")
    await an_audience_of(house, 2, "CO")

    await climb(house, "CO")

    assert KING not in await earned_by()


async def test_a_cat_climb_with_a_full_audience_does_not(house, monkeypatch):
    """**Nobody surveyed a kingdom from halfway up.** The work order
    asks for this case by name, and it is the same distinction *Hive
    Five* turns on: both are `on_use` of the ladder in a room with a
    crowd in it, and only one of them reached the top."""
    db, *_ = house
    await db.set_config(GUILD_A, "captive_audience_size", "2")
    await an_audience_of(house, 2, "CO")
    monkeypatch.setattr(world, "random", _AlwaysTheCat())

    await climb(house, "CO")

    assert KING not in await earned_by()


async def test_the_climber_is_not_their_own_audience(house):
    """With the bar at one, which is the only setting where counting
    yourself would pass unnoticed - the rattle's test, for the ladder."""
    db, *_ = house
    await db.set_config(GUILD_A, "captive_audience_size", "1")

    await climb(house, "CO")

    assert KING not in await earned_by()


async def test_an_audience_that_has_gone_quiet_does_not_count(house):
    """Standing somewhere is not being at the keyboard. The rows are
    there and never stamped, which is no evidence rather than absence -
    the rule the sweep reads the other way round."""
    db, *_ = house
    await db.set_config(GUILD_A, "captive_audience_size", "2")
    await an_audience_of(house, 2, "CO", awake=False)

    await climb(house, "CO")

    assert KING not in await earned_by()


async def test_an_audience_in_another_room_does_not_count(house):
    db, *_ = house
    await db.set_config(GUILD_A, "captive_audience_size", "2")
    await an_audience_of(house, 2, "LI")

    await climb(house, "CO")

    assert KING not in await earned_by()


async def test_the_audience_is_logged_on_every_climb(house):
    """**Including the climbs that earn nothing**, which is the whole
    reason the headcount is taken in the handler rather than in the
    predicate: the number is collected to settle what
    `captive_audience_size` should be for a climb, and a column holding
    only numbers already over the bar could not answer that."""
    db, *_ = house
    await db.set_config(GUILD_A, "captive_audience_size", "9")
    await an_audience_of(house, 2, "CO")

    await climb(house, "CO")

    climbs = await climb_log(house)

    assert climbs, "the climb wrote no log row"
    assert "audience=2" in climbs[-1].detail


# --- Second Place ---------------------------------------------------------


async def cat_climbs(house, how_many, who=ALICE):
    """Roll the cat this many times, walking out of her lock between.

    **The offset is set, not stepped**, which is the trap here: she
    keeps the ladder for five minutes from each climb, and writing the
    same `clock_offset_days` twice leaves the second lock in the
    future. The day has to go up every time or the third climb is
    refused and the tally quietly stops at two.
    """
    db, *_ = house
    for day in range(1, how_many + 1):
        await climb(house, "CO", who=who)
        await db.set_setting(GUILD_A, database.CLOCK_KEY, day)


async def test_three_cat_climbs_earn_it(house, monkeypatch):
    """Tester A's climb rolls the cat three times: earned."""
    monkeypatch.setattr(world, "random", _AlwaysTheCat())

    await cat_climbs(house, 3)

    assert SECOND in await earned_by()
    assert await tally("ladder_cat_climbs") == 3


async def test_two_are_not_enough(house, monkeypatch):
    monkeypatch.setattr(world, "random", _AlwaysTheCat())

    await cat_climbs(house, 2)

    assert SECOND not in await earned_by()
    assert await tally("ladder_cat_climbs") == 2


async def test_a_swat_is_not_a_tick(house, monkeypatch):
    """**The work order's second acceptance test.** Bob's swats, taken
    while Alice's cat is guarding the ladder, must not move Bob's tally:
    he only earns ticks from his own climbs that roll her. A swat is a
    refusal and never reaches `after_use`, which is what makes this
    true rather than checked - so the test is that the counter is
    untouched, not that the award is absent."""
    monkeypatch.setattr(world, "random", _AlwaysTheCat())
    await climb(house, "CO")

    assert SWAT_USE in await climb(house, "CO", who=BOB)
    assert SWAT_TAKE in replies(
        await run(house, bot.take, "ladder", room="CO", who=BOB)
    )
    assert await tally("ladder_cat_climbs", who=BOB) in (None, 0)
    assert SECOND not in await earned_by(BOB)


async def test_an_ordinary_climb_is_not_a_cat_climb(house):
    """The ninety percent, which `no_cat` is making certain of."""
    await climb(house, "CO")

    assert await tally("ladder_cat_climbs") in (None, 0)


# --- Head for Heights -----------------------------------------------------


async def test_the_twenty_fifth_climb_earns_it(house):
    for n in range(triggers.HEAD_FOR_HEIGHTS_CLIMBS):
        await climb(house, "CO")
        if n < triggers.HEAD_FOR_HEIGHTS_CLIMBS - 1:
            assert HEIGHTS not in await earned_by(), f"earned on climb {n + 1}"

    assert HEIGHTS in await earned_by()
    assert await tally("ladder_climbs") == triggers.HEAD_FOR_HEIGHTS_CLIMBS


async def test_cat_climbs_are_not_counted(house, monkeypatch):
    """**The one place this departs from the work order is not here.**
    That the count excludes her is exactly what the order asks for;
    what it does not get is the climbs made before this shipped, because
    neither `room_deeds` nor `thing_uses` could supply them. Two columns
    rather than a total and a subtraction is what makes this testable at
    all."""
    db, *_ = house
    monkeypatch.setattr(world, "random", _AlwaysTheCat())

    await climb(house, "CO")

    assert await tally("ladder_climbs") in (None, 0)
    assert await tally("ladder_cat_climbs") == 1


async def test_any_room_counts(house):
    """Climbs, not places - which is what separates this from *Rung by
    Rung*. Three climbs of one ladder in one room is three."""
    for _ in range(3):
        await climb(house, "CO")

    assert await tally("ladder_climbs") == 3


# --- Pass It On -----------------------------------------------------------


async def take_log(house):
    """Every logged take of the ladder, oldest first."""
    db, *_ = house
    async with db._require_session()() as session:
        return list(
            (
                await session.scalars(
                    select(database.InteractionLog)
                    .where(
                        database.InteractionLog.guild_id == GUILD_A,
                        database.InteractionLog.thing_id == world.LADDER,
                        database.InteractionLog.action == telemetry.TAKE,
                    )
                    .order_by(database.InteractionLog.id)
                )
            ).all()
        )


async def test_every_take_of_the_ladder_says_what_the_offer_was(house):
    """**All three outcomes are written down**, which is what the work
    order's logging line asks for: how often one player picks up what
    another put down is only answerable beside how often they nearly
    did. A first take with nothing standing, a hand-off, and a player
    taking their own ladder back."""
    await carry_it(house)
    await run(house, bot.drop, "ladder", room="CO")
    await run(house, bot.take, "ladder", room="CO", who=BOB)
    await run(house, bot.drop, "ladder", room="CO", who=BOB)
    await run(house, bot.take, "ladder", room="CO", who=BOB)

    details = [row.detail for row in await take_log(house)]

    assert details[0] == "handoff=none"
    assert details[1].startswith("handoff=")
    assert f"from={ALICE}" in details[1]
    assert details[2] == "handoff=self"


async def test_a_take_of_anything_else_is_unchanged(house):
    """The ladder is the only thing with offers on it, and the detail
    for everything else has to read as it always did - `_moved_detail`
    returns None for most things, and a stray "handoff=none" on a pair
    of booties would be a column that meant two things."""
    await run(house, bot.take, "ladder", room="CO")
    taking = await run(house, bot.take, "booties", room="EN")

    assert replies(taking) or posted(house, "EN")
    async with database._require_session()() as session:
        detail = await session.scalar(
            select(database.InteractionLog.detail).where(
                database.InteractionLog.guild_id == GUILD_A,
                database.InteractionLog.thing_id == "booties",
                database.InteractionLog.action == telemetry.TAKE,
            )
        )
    assert detail is None or "handoff" not in detail


async def test_a_drop_and_somebody_else_taking_it_earns_it(house):
    """**The award goes to the player who is not in the room.** Alice
    drops it and Bob picks it up, so Alice earns it and Bob does not -
    which is the whole of why `on_hand_off` is a hook of its own."""
    await carry_it(house)
    await run(house, bot.drop, "ladder", room="CO")

    await run(house, bot.take, "ladder", room="CO", who=BOB)

    assert PASS_IT_ON in await earned_by(ALICE)
    assert PASS_IT_ON not in await earned_by(BOB)


async def test_the_taker_is_not_told_they_earned_it(house):
    """**The reason the hook fires with no interaction.** An ordinary
    player award sends its private half to `interaction.followup`, and
    the interaction in flight here is Bob's - so a context fired the
    ordinary way would congratulate Bob on Alice's achievement in his
    own ephemeral reply."""
    await carry_it(house)
    await run(house, bot.drop, "ladder", room="CO")

    taking = await run(house, bot.take, "ladder", room="CO", who=BOB)

    assert "Pass It On" not in replies(taking)


async def test_eleven_minutes_is_too_late(house):
    """The work order's third acceptance test, the far half: after
    eleven minutes, nobody earns it."""
    await carry_it(house)
    await run(house, bot.drop, "ladder", room="CO")

    await age_the_offer(11)
    await run(house, bot.take, "ladder", room="CO", who=BOB)

    assert PASS_IT_ON not in await earned_by(ALICE)
    assert PASS_IT_ON not in await earned_by(BOB)


async def test_five_minutes_is_in_time(house):
    """And the near half, in the order's own numbers: five minutes
    later, A earns it and B does not."""
    await carry_it(house)
    await run(house, bot.drop, "ladder", room="CO")

    await age_the_offer(5)
    await run(house, bot.take, "ladder", room="CO", who=BOB)

    assert PASS_IT_ON in await earned_by(ALICE)
    assert PASS_IT_ON not in await earned_by(BOB)


async def test_an_expired_offer_is_cleared_rather_than_left(house):
    """A take after the window spends the row as surely as one inside
    it. Otherwise a stale offer would sit there until somebody happened
    to set the ladder down again, and the next taker would earn it for
    a gesture made an hour ago."""
    await carry_it(house)
    await run(house, bot.drop, "ladder", room="CO")
    await age_the_offer(11)

    await run(house, bot.take, "ladder", room="CO", who=BOB)

    assert await database.claim_set_down_offer(
        GUILD_A, world.LADDER, timedelta(minutes=world.HANDOFF_MINUTES)
    ) is None


async def test_taking_it_back_yourself_earns_nothing(house):
    await carry_it(house)
    await run(house, bot.drop, "ladder", room="CO")

    await run(house, bot.take, "ladder", room="CO")

    assert PASS_IT_ON not in await earned_by(ALICE)


async def test_and_spends_the_chance(house):
    """**Explicit in the work order**, and the half a reading could
    miss: taking it back does not merely fail to earn, it clears the
    offer. Asserted on the row rather than on the award, because the
    award is absent either way and only the row says which reason."""
    await carry_it(house)
    await run(house, bot.drop, "ladder", room="CO")

    await run(house, bot.take, "ladder", room="CO")

    assert await database.claim_set_down_offer(
        GUILD_A, world.LADDER, timedelta(minutes=world.HANDOFF_MINUTES)
    ) is None


async def test_but_dropping_it_again_makes_a_fresh_one(house):
    """The other side of that: the chance is spent, not the mechanic.
    Alice takes it back, puts it down again, and Bob picking it up is
    an ordinary hand-off."""
    await carry_it(house)
    await run(house, bot.drop, "ladder", room="CO")
    await run(house, bot.take, "ladder", room="CO")

    await run(house, bot.drop, "ladder", room="CO")
    await run(house, bot.take, "ladder", room="CO", who=BOB)

    assert PASS_IT_ON in await earned_by(ALICE)


async def test_a_climb_hands_it_on_too(house):
    """The second of the three deliberate set-downs. Climbing a ladder
    you were carrying puts it down, and the next player along taking it
    is the same gesture as a `/drop`."""
    await carry_it(house)

    await climb(house, "KI")
    await run(house, bot.take, "ladder", room="KI", who=BOB)

    assert PASS_IT_ON in await earned_by(ALICE)


async def test_but_climbing_one_already_standing_there_does_not(house):
    """Nothing was set down. The ladder was in the Courtyard before the
    climb and is in the Courtyard after it, so the next player could
    have taken it either way and there is no gesture to reward."""
    await climb(house, "CO")

    await run(house, bot.take, "ladder", room="CO", who=BOB)

    assert PASS_IT_ON not in await earned_by(ALICE)


async def test_a_cat_climb_hands_it_to_nobody(house, monkeypatch):
    """She took it off them, so the player chose nothing. The work
    order rules this out by name, and the row is what says so - after
    the five minutes are walked out of, a take would look the same
    either way."""
    db, *_ = house
    await carry_it(house)
    monkeypatch.setattr(world, "random", _AlwaysTheCat())

    await climb(house, "CO")

    assert await database.claim_set_down_offer(
        GUILD_A, world.LADDER, timedelta(minutes=world.HANDOFF_MINUTES)
    ) is None
    await db.set_setting(GUILD_A, database.CLOCK_KEY, 6)
    await run(house, bot.take, "ladder", room="CO", who=BOB)
    assert PASS_IT_ON not in await earned_by(ALICE)


async def test_and_clears_one_that_was_standing(house, monkeypatch):
    """**The half that is easy to miss**, and the reason the cat branch
    clears rather than simply not writing. Alice leaves the ladder
    standing, nobody comes for it, and then somebody rolls the cat on
    it - the offer Alice's drop made must not survive a climb she won,
    or the next player along would earn Alice a hand-off she had
    nothing to do with."""
    await carry_it(house)
    await run(house, bot.drop, "ladder", room="CO")
    await run(house, bot.take, "ladder", room="CO")
    await run(house, bot.drop, "ladder", room="CO")
    monkeypatch.setattr(world, "random", _AlwaysTheCat())

    await climb(house, "CO")

    assert await database.claim_set_down_offer(
        GUILD_A, world.LADDER, timedelta(minutes=world.HANDOFF_MINUTES)
    ) is None


async def test_an_idle_drop_hands_it_to_nobody(house):
    """**The work order's fourth acceptance test**, and the one that
    says what the achievement is for: a player who went quiet for a day
    did not decide to share."""
    db, *_ = house
    await carry_it(house)
    async with db._require_session()() as session:
        await session.execute(
            update(database.User)
            .where(database.User.id == ALICE, database.User.guild_id == GUILD_A)
            .values(
                last_command_at=await db.server_now(GUILD_A)
                - timedelta(hours=world.IDLE_HOURS + 1)
            )
        )
        await session.commit()

    await bot.idle_sweep.coro()
    await run(house, bot.take, "ladder", room="CO", who=BOB)

    assert PASS_IT_ON not in await earned_by(ALICE)


# --- Heavy Lifting --------------------------------------------------------


async def test_four_moves_carrying_it_earn_it(house):
    """**The work order's fifth acceptance test.** Four moves without
    setting it down, earned on the fourth - and back and forth between
    two rooms, which the order says counts because it is still four
    rooms' worth of carrying."""
    await carry_it(house)
    await walk(house, "back door", "CO")

    await walk(house, "swinging door", "KI")
    await walk(house, "swinging door", "DI")
    assert HEAVY not in await earned_by()

    await walk(house, "swinging door", "KI")

    assert HEAVY in await earned_by()
    assert await tally("ladder_carry_moves") == 4


async def test_the_road_is_one_of_the_rooms(house):
    """Named in the work order, and it is the one place a player can
    walk to that is not a thread."""
    await carry_it(house)
    await walk(house, "back door", "CO")
    await walk(house, "swinging door", "KI")
    await walk(house, "arched doorway", "DI")

    await walk(house, "front door", "EN")

    assert HEAVY in await earned_by()


async def test_a_drop_after_three_loses_them(house):
    """The other half of the order's fifth test: drop it after three
    and carry it three more, and nothing is earned. Four in one trip is
    the condition, and this is the zeroing that makes "trip" mean
    something."""
    await carry_it(house)
    await walk(house, "back door", "CO")
    await walk(house, "swinging door", "KI")
    await walk(house, "swinging door", "DI")

    await run(house, bot.drop, "ladder", room="DI")
    await run(house, bot.take, "ladder", room="DI")
    assert await tally("ladder_carry_moves") == 0

    await walk(house, "swinging door", "DI")
    await walk(house, "swinging door", "KI")
    await walk(house, "swinging door", "DI")

    assert HEAVY not in await earned_by()


async def test_a_climb_loses_them_too(house):
    """Every route out of the bag zeroes it, and the climb is the one a
    player reaches by accident: it sets the ladder down whether they
    meant it to or not."""
    await carry_it(house)
    await walk(house, "back door", "CO")

    await climb(house, "KI")

    assert await tally("ladder_carry_moves") == 0


async def test_moving_without_it_counts_nothing(house):
    """Which is almost every move in the game. The hook carries no
    count at all unless the ladder was in the bag."""
    await walk(house, "arched doorway", "EN")
    await walk(house, "swinging door", "DI")

    assert await tally("ladder_carry_moves") in (None, 0)


async def test_one_players_haul_is_not_anothers(house):
    """Per player, like every other tally on that row. Alice carrying
    it three rooms must not put Bob a move away from the award."""
    await carry_it(house)
    await walk(house, "back door", "CO")
    await walk(house, "swinging door", "KI")
    await walk(house, "swinging door", "DI")

    assert await tally("ladder_carry_moves", who=BOB) in (None, 0)
