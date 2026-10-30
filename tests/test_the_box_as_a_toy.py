"""The shipping box: a toy to the cat, furniture to everybody else.

The box has stood in the Entryway since drop 20 as the thing the spice
order arrives in. The drop 2 toys deck wrote it up as one of the unusual
toys and settled that it is a fixture rather than a drop 2 toy - the
argument there being about *stocking*, not about the mechanic. The four
refusals it wrote only make sense if `/use box` plays, and now it does.

**`type` and `takeable` were the same question until this row.** Every
toy in the game was carriable and every fixture was not, so the engine
asked whichever was to hand: a class selector drew on kind, the loader
seeded on kind, the reach resolved on kind. The box answers `toy` to the
first question and `no` to the second, and the tests below are mostly
about the four places that distinction has to hold - the channel
restock, the cat bed, the room listing and the hint rail - because each
of them, asked the old way, moves the box somewhere it cannot go or
tells a player to pick up something nobody can lift.

**It is an easter egg**, which is a constraint and not just flavour:
the deck is explicit that nothing may hint at it. Discovery is by
accident or by word of mouth.
"""

from datetime import timedelta

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
import resolve
import restocking
import states
import triggers
import world


THIS_DROP = 20
BOX = "shipping_box"
WAND = "feather_wand"

PLAY_LINE = "the cat is in it before they have straightened up"
MOVED_ON = "The cat has moved on"
CAN_BE_PICKED_UP = "can be picked up"


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.register_all()
    triggers.forget_arrivals()
    yield
    achievements.clear()


@pytest.fixture
async def entryway(db):
    """Drop 20, the house open, Alice and Bob standing in the Entryway.

    Both have fed the cat, because the Entryway's later fragments are
    gated on it and the box is in one of them - an unfed player cannot
    see the box at all, which `test_feeding` owns and none of these
    tests are about.

    **A feather wand goes in the channel**, which looks irrelevant here
    and is not: the hint rungs that name a toy decline when the server
    has no takeable one, so without it the rail would be silent for a
    reason that has nothing to do with the box.
    """
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    await content_loader.load_content(content_module.load_files())
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, THIS_DROP)
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    await content_loader.place_arrived(GUILD_A)
    await database.place_in_room(GUILD_A, content_module.CHANNEL_ROOM, WAND, 1)
    for who in (ALICE, BOB):
        await db.start_game(who, GUILD_A, "EN", await resolve.rooms_open_at_launch())
        await db.notice(GUILD_A, who, content_module.FED_THE_CAT)
    bot.forget_public_pets()
    return db, guild, halloween, rooms


def thread(entryway, room_name):
    _, _, halloween, _ = entryway
    return next(t for t in halloween.threads if t.name == room_name)


async def run(entryway, command, arg=None, *, who=ALICE):
    _, guild, _, rooms = entryway
    interaction = FakeInteraction(
        who, GUILD_A, guild=guild, channel=thread(entryway, rooms["EN"])
    )
    args = () if arg is None else (arg,)
    await command.callback(interaction, *args)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


def posted(entryway) -> str:
    """What the Entryway thread has seen.

    A successful play is public and nothing else, and it posts wherever
    the command was run - so the box's success line lands in the room's
    thread rather than in the channel, which is the first time that has
    mattered. Every toy before this one lived in the channel.
    """
    return "\n".join(thread(entryway, entryway[3]["EN"]).posted)


async def play(entryway, who=ALICE) -> str:
    return replies(await run(entryway, bot.use, "shipping box", who=who))


def always(monkeypatch, *, succeed):
    """Pin the roll, as `test_toys` does. The first offer cannot land
    whatever the dice say, so a success has to earn a rung first."""
    monkeypatch.setattr(world, "random", _Loaded(0.0 if succeed else 0.999))


class _Loaded:
    def __init__(self, value):
        self._value = value

    def random(self):
        return self._value


class _First:
    """An rng that takes the front of any pool handed to it.

    Which is what makes the two draw tests sharp: the box sorts to the
    front of the toys by `sort_order`, so a pool that still contains it
    hands it over first.
    """

    def choice(self, pool):
        return pool[0]


async def a_success(entryway, monkeypatch, who=ALICE):
    always(monkeypatch, succeed=False)
    await play(entryway, who=who)
    always(monkeypatch, succeed=True)
    await play(entryway, who=who)


# --------------------------------------------------------------------------
# She plays with it
# --------------------------------------------------------------------------


async def test_the_cat_gets_in_the_box(entryway, monkeypatch):
    await a_success(entryway, monkeypatch)

    assert PLAY_LINE in posted(entryway)


async def test_it_is_played_where_it_stands(entryway, monkeypatch):
    """**The box is not an exception to the must-carry rule - it is
    outside it.** The carry check is keyed on `takeable`, so a first
    `/use` gets the cat declining rather than "you would have to pick it
    up first", and there is no `/take` anywhere in this test.
    """
    always(monkeypatch, succeed=False)

    said = await play(entryway)

    assert "pick it up first" not in said
    assert "cat" in said.lower()


async def test_the_success_is_announced_in_the_room(entryway, monkeypatch):
    """Not in the channel. Every toy until now lived in the channel, so
    the public line had nowhere else it could have gone."""
    _, _, halloween, _ = entryway
    await a_success(entryway, monkeypatch)

    assert PLAY_LINE not in "\n".join(halloween.posted)


async def test_the_cooldown_refusal_is_the_boxs_own(entryway, monkeypatch):
    """A toy's `use_fail` is its *finished* line, and the ramp refusals
    come from the shared pool - so this is the one string the box had to
    be given, or it would have fallen back to "You've done that
    recently"."""
    await a_success(entryway, monkeypatch)

    assert MOVED_ON in await play(entryway)


async def test_the_ramp_refusal_is_not_the_cooldown_line(entryway, monkeypatch):
    """The two read differently on purpose: declining is not being
    finished, and the first offer is a guaranteed decline."""
    always(monkeypatch, succeed=False)

    assert MOVED_ON not in await play(entryway)


async def test_a_play_with_the_box_counts_toward_tireless(entryway, monkeypatch):
    """Twenty-five plays, any toy. The achievement joins on the type, so
    this follows from the row rather than from a list of ids - which is
    the whole reason `type` is the column that moved."""
    await a_success(entryway, monkeypatch)

    assert await database.toy_plays(GUILD_A, ALICE) == 1


async def test_the_cooldown_is_the_players_and_not_the_boxs(entryway, monkeypatch):
    """Bob is not inside Alice's cooldown. The ramp has belonged to the
    player since drop 2 and a toy in a room rather than the channel does
    not change that."""
    await a_success(entryway, monkeypatch)
    always(monkeypatch, succeed=False)

    assert MOVED_ON not in await play(entryway, who=BOB)


# --------------------------------------------------------------------------
# Furniture to everybody else
# --------------------------------------------------------------------------


async def test_the_room_names_it_and_does_not_list_it(entryway):
    """`Also here:` carries finite takeables and nothing else, and the
    Entryway's own prose has described the box against the wall since
    drop 20. Both halves in one test, because what would be wrong is the
    box reading twice in a single `/look` - and the two mechanisms that
    could do that, the listing and the paragraph, only disagree when
    seen together."""
    around = replies(await run(entryway, bot.look))

    before, _, listing = around.partition("here")
    assert "shipping box" in before
    assert "shipping box" not in listing


async def test_it_has_no_stock_row(entryway):
    """A count that could never change. The loader seeds what a player
    can carry, which is now asked of `takeable` - and an existing server
    at drop 20 never had a row for the box either, because it loaded as
    a fixture. Reaching it has to come off the files."""
    assert (
        await database.how_many_in_container(
            GUILD_A, "EN", database.LOOSE_IN_ROOM, BOX
        )
        == 0
    )


async def test_it_is_reachable_anyway(entryway):
    """**The test for the half that would have failed silently.** The
    reach used to list the kinds that stand in a room without a stock
    row - fixture, exit, scenery - and a toy was never one of them. Asked
    that way, `/look box` answers that there is no such thing."""
    said = replies(await run(entryway, bot.look, "shipping box"))

    assert "packing slip" in said


async def test_looking_at_it_never_says_to_pick_it_up(entryway):
    """The rung is live - there is a feather wand in the channel - and it
    is still not shown, for two reasons at once: it would send a player
    to `take_fail`, and naming the box in the rail spends the joke."""
    said = replies(await run(entryway, bot.look, "shipping box"))

    assert CAN_BE_PICKED_UP not in said


async def test_the_rung_still_fires_for_a_toy_that_can_be_taken(entryway):
    """The other side of the gate, so the test above is about the box
    rather than about the rail being broken.

    A wand laid on the Entryway floor rather than looked at in the
    channel: same room, same player, same rail, and `takeable` the only
    thing that differs between the two.
    """
    await database.place_in_room(GUILD_A, "EN", WAND, 1)

    said = replies(await run(entryway, bot.look, "feather wand"))

    assert CAN_BE_PICKED_UP in said


async def test_it_cannot_be_taken(entryway):
    said = replies(await run(entryway, bot.take, "shipping box"))

    assert "packing paper" in said


async def test_the_spice_jars_still_arrive_in_it(entryway):
    """It is a container first. Nothing above may cost it that."""
    await restocking.set_initialized_on(GUILD_A, database.pacific_today())
    await entryway[0].set_setting(GUILD_A, database.CLOCK_KEY, 4)

    report = await restocking.run_for_guild(GUILD_A)

    assert [row for row in report.placed if row[3] == "spice_jar"]


# --------------------------------------------------------------------------
# Nothing delivers it
# --------------------------------------------------------------------------


async def test_the_bed_never_stashes_it(entryway):
    """The cat bed hands a player a toy drawn from the same pool a
    restock draws from, and the box sorts to the front of it. Pre-fix
    this returned the shipping box - placed in the channel, where it has
    no business being, and never takeable by the player it was given
    to."""
    assert await world.dislodge_from_bed(GUILD_A, BOB, rng=_First()) == WAND


async def test_the_channel_never_receives_it(entryway):
    """The toy row is `type:toy` into the channel, six a day. Over four
    days of catch-up it draws often enough that a pool containing the
    box would have delivered one."""
    await restocking.set_initialized_on(
        GUILD_A, database.pacific_today() - timedelta(days=4)
    )

    await restocking.run_for_guild(GUILD_A)

    assert await database.how_many_in_container(
        GUILD_A, content_module.CHANNEL_ROOM, database.LOOSE_IN_ROOM, BOX
    ) == 0


async def test_the_draw_is_only_what_can_be_carried(entryway):
    arrived = await resolve.arrived_drop_ids(GUILD_A)

    pool = await database.stock_of_type("toy", arrived)

    assert BOX not in pool
    assert WAND in pool


def test_a_class_selector_is_not_a_route_to_it():
    """`restocked_thing_ids` expands `type:toy`, and feeds the check that
    nothing may exist which no player could obtain. Expanded to include
    the box it would have claimed the restock schedule as the box's
    route into the world, which is the opposite of true."""
    content = content_module.load_files()

    assert BOX not in content.restocked_thing_ids
    assert WAND in content.restocked_thing_ids
