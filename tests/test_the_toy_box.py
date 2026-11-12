"""Drop 46: the toys leave the road and turn up all over the house.

Three things change at once and only the first is visible from a room:
a toy arrives *inside* something rather than on a floor, six are out at
a time rather than two, and the six are counted across the whole house
rather than per room. The third is what makes the other two mean
anything - a per-room count of six would have allowed six in every
container, which is ninety-six toys and not a drop.

**Row 4 is not edited and not deleted.** Drop 46 writes a second
`type:toy` row and the later one wins on a server that has reached it,
so a server on drop 45 keeps exactly the channel it has. `superseded`
in `restocking.run_for_guild` is that rule, and it is general rather
than a check for these two rows by id.

What is deliberately *not* gated is the cap itself. `toys_present` is
one config default, so raising it to six raised it for the channel too,
on every server at once. That was the call rather than an oversight -
`test_toy_arrival.test_the_cap_is_still_the_cap` now expects six at
drop 2 and says why.
"""

import pytest
from sqlalchemy import select

from conftest import ALICE, GUILD_A
from fake_discord import FakeBot, FakeChannel, FakeGuild, FakeMember
from test_restocking import end_of_day
from test_world import carry

import bot
import content as content_module
import content_loader
import database
import resolve
import restocking

CHANNEL = content_module.CHANNEL_ROOM
TRASH = content_module.TRASH_CAN

_RUN_ALL = restocking.run_all


@pytest.fixture
async def toy_box(db, monkeypatch):
    """A server at drop 46, with the house as the files leave it."""
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(GUILD_A, channels=[halloween], members=[FakeMember(ALICE)])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, 46)
    await db.ensure_user_exists(ALICE, GUILD_A)
    monkeypatch.setattr(bot, "bot", FakeBot(guild))
    return guild, halloween


async def sweep(monkeypatch, now=None):
    when = end_of_day() if now is None else now
    monkeypatch.setattr(restocking, "run_all", lambda ids: _RUN_ALL(ids, now=when))
    await bot.restock_sweep.coro()


async def toys_out(room=None):
    """Every toy row in the house, as (room, container, thing, count)."""
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    database.RoomContents.room_id,
                    database.RoomContents.container_id,
                    database.RoomContents.thing_id,
                    database.RoomContents.count,
                )
                .join(
                    database.ThingType,
                    database.ThingType.thing_id == database.RoomContents.thing_id,
                )
                .where(
                    database.RoomContents.guild_id == GUILD_A,
                    database.RoomContents.count > 0,
                    database.ThingType.type == "toy",
                )
            )
        ).all()
    return [row for row in rows if room is None or row[0] == room]


async def how_many_out():
    return sum(count for _, _, _, count in await toys_out())


# --------------------------------------------------------------------------
# Where they land
# --------------------------------------------------------------------------


async def test_a_toy_turns_up_somewhere_in_the_house(toy_box, monkeypatch):
    """Anywhere a player can reach, which is the drop in one assertion.

    **This test used to say the opposite** - that nothing lands loose
    on a floor, because a toy on a floor was one somebody dropped. That
    held for the eleven hours drop 46 ran container-only on the two QA
    servers, and then the call was made the other way: floors are
    spots too, at the same odds as a cupboard. `test_toys_in_the_open`
    is the file that holds the new half; what is left here is the part
    that did not change, which is that every toy lands in a room of the
    house rather than on the road.
    """
    await sweep(monkeypatch)

    placed = await toys_out()
    assert placed
    for room_id, _, _, _ in placed:
        assert room_id not in (CHANNEL, content_module.SECRET_LIBRARY), room_id


async def test_the_road_stops_getting_them(toy_box, monkeypatch):
    """Row 4's whole job, and it has stopped. Not because the row was
    edited - it is still in the file and still runs on drop 45 - but
    because `superseded` takes the later of two rows drawing from the
    same selector."""
    await sweep(monkeypatch)

    assert await toys_out(room=CHANNEL) == []


async def test_and_still_gets_them_at_drop_forty_five(toy_box, monkeypatch):
    """The other side of the same rule, and the reason it is a rule
    rather than a deletion. A server that has not reached drop 46 has
    only one arrived `type:toy` row, so it keeps the channel it had."""
    await resolve.set_current_drop(GUILD_A, 45)

    await sweep(monkeypatch)

    assert await toys_out(room=CHANNEL)
    assert [row for row in await toys_out() if row[0] != CHANNEL] == []


async def test_the_eligible_containers_are_the_ones_a_player_can_open(toy_box):
    """Every exclusion in one list, read off the real content.

    The shipping box is out because it is not a scatter target - David's
    spice order arriving with a hair tie in it reads as a bug. The
    library shelves are out because the Secret Library is found per
    player, so a toy in there is out of play and holding a slot.
    """
    slots = await restocking._scatter_spots(GUILD_A)
    containers = {container for _, container in slots}

    assert "shipping_box" not in containers
    assert "library_shelves" not in containers
    assert {"sideboard", "pantry", "sofa", "rolltop_desk"} <= containers
    assert all(room != content_module.SECRET_LIBRARY for room, _ in slots)


async def test_a_room_that_has_not_opened_holds_none_of_them(toy_box):
    """`random` does not ask this and does not need to, because the
    sweep clears what lands in a closed room on the next tick. A toy is
    different: it would count against the cap for as long as it sat
    there, and six would stop the draw while the player saw nothing."""
    await resolve.set_current_drop(GUILD_A, 25)

    rooms = {room for room, _ in await restocking._scatter_spots(GUILD_A)}

    assert rooms <= await resolve.arrived_rooms(GUILD_A)
    assert "BE" not in rooms


# --------------------------------------------------------------------------
# How many are out
# --------------------------------------------------------------------------


async def test_six_are_out_and_then_no_more(toy_box, monkeypatch):
    """Six go out, and a second sweep adds nothing: the occurrences are
    spent rather than banked.

    **This one does not hold the scope**, and that is worth writing down
    because the assertion looks as though it does. Six occurrences
    scattered across nine rooms sit under a cap of six whether it is
    read per room or across the house, so a per-room count passes here
    too. `test_a_toy_a_player_dropped_counts_toward_the_six` is the one
    that fails: six already in the Kitchen leave no room anywhere.
    """
    await sweep(monkeypatch)
    first = await how_many_out()

    await sweep(monkeypatch)

    assert first == 6
    assert await how_many_out() == 6


async def test_a_toy_a_player_dropped_counts_toward_the_six(toy_box, monkeypatch):
    """**Whether the restock placed it or somebody put it down.** The
    old count asked "how many did the scheduler put in this room"; the
    rule was always "how many toys are out", and across a house those
    are different numbers."""
    for _ in range(6):
        await database.place_in_room(GUILD_A, "KI", "acorn", 1)

    await sweep(monkeypatch)

    assert await how_many_out() == 6
    assert await toys_out(room="KI")


async def test_a_toy_in_a_bag_does_not(toy_box, monkeypatch, db):
    """Collecting toys is how the drop is played - *Playgroup* wants ten
    in one room - so a cap that counted them would stop the draw for
    whoever played hardest."""
    for toy in ("acorn", "wine_cork", "hair_tie", "bottle_cap", "spider_ring"):
        await carry(db, ALICE, GUILD_A, toy)

    await sweep(monkeypatch)

    assert await how_many_out() == 6


async def test_a_toy_in_the_bin_does_not(toy_box, monkeypatch):
    """A toy in the trash can is on its way out of the world. The trash
    mechanic owns it and the drain leaves it alone, so counting it would
    hold a slot nothing can free."""
    await database.place_in_room(GUILD_A, "KI", "acorn", 1, container_id=TRASH)

    await sweep(monkeypatch)

    assert await how_many_out() == 7
    assert (
        await database.count_of_type_in_house(GUILD_A, "toy", except_container=TRASH)
        == 6
    )


async def test_the_shipping_box_never_spends_a_slot(toy_box, monkeypatch):
    """It is a toy to the cat and furniture to everybody else: bolted to
    the Entryway, never placed and never drained. Counting it would
    spend one of the six for the rest of the game."""
    assert not content_module.load().things_by_id["shipping_box"].takeable

    await sweep(monkeypatch)

    assert (
        await database.count_of_type_in_house(GUILD_A, "toy", except_container=TRASH)
        == 6
    )


# --------------------------------------------------------------------------
# Housekeeping
# --------------------------------------------------------------------------


def test_the_drop_can_be_reached_at_all():
    """Change 12, and every drop's work order carries it because a drop
    progression hit this once: `/advance-game` and `/qa-drop` both stop
    at `LAST_PLAYABLE_DROP`, so a drop above it ships unreachable."""
    assert resolve.LAST_PLAYABLE_DROP >= 46
