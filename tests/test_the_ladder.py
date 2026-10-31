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
import triggers
import world


THIS_DROP = 30

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
    """
    parsed = content_module.load_files()
    rooms = {room.room_id for room in parsed.rooms}

    written = {
        row.state[len(content_module.ROOM_STATE_PREFIX) :]
        for row in parsed.thing_text
        if row.state.startswith(content_module.ROOM_STATE_PREFIX)
    }

    assert written == set(CLIMBS)
    assert written <= rooms


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

    await bot.ladder_sweep.coro()

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

    await bot.ladder_sweep.coro()

    assert EXHAUSTED in posted(house, "KI")


async def test_somebody_still_playing_keeps_it(house):
    db, *_ = house
    await carry_it(house)
    await quiet_for(db, 0)

    await bot.ladder_sweep.coro()

    assert await database.carried_of(ALICE, GUILD_A, world.LADDER) == 1


async def test_a_player_with_no_stamp_at_all_keeps_it(house):
    """**Null is no evidence, not idleness.** Every row that existed
    before the stamp shipped has none, and nothing should be taken off
    a player the game has never watched run a command. The cost is that
    such a carrier keeps the ladder until they next do anything."""
    await carry_it(house)

    await bot.ladder_sweep.coro()

    assert await database.carried_of(ALICE, GUILD_A, world.LADDER) == 1


async def test_a_ladder_nobody_is_carrying_is_left_alone(house):
    """It is standing in the Courtyard where the loader put it, and the
    sweep is about shoulders rather than about floors."""
    await bot.ladder_sweep.coro()

    assert "ladder" in await floor_of("CO")
    assert EXHAUSTED not in posted(house, "CO")
