"""Drop 46, second call: a toy can also turn up loose on a room's floor.

Drop 46 shipped drawing containers only, and ran that way for eleven
hours on the two QA servers - fourteen eligible containers, `of=14` in
every `restock_placed` row. The call was then made the other way: a
room's floor is a spot too, at the same odds as a cupboard, and a toy
that lands on one is announced with the line the road has always used.

Three things are being held here, and they are separable on purpose:

1. **Floors are spots.** Every arrived room except the road and the
   library, one entry each.
2. **One draw, no weighting.** A floor and a cupboard come out of the
   same `rng.choice`, each listed once. Eight floors against fourteen
   containers today, so a toy lands in the open a little over a third
   of the time - a ratio that follows from the content rather than from
   a number anybody tuned.
3. **The floor speaks and the cupboard does not.** `channel.arrival`,
   once per room per sweep, and nothing at all for a toy that arrived
   inside something, because that one is the reward for `/look
   sideboard` rather than news.

**Where the selector is pinned and where it is not.** Which spot the
real draw picks is derived from a seed of (guild, row, day), so it is
deterministic for a day and different tomorrow - an unpinned "a toy
landed loose" would pass some days and fail others. So the *list* is
asserted against the real content and the *landing* is driven through
a selector pinned to one spot. Flakiness that only shows up in a
fortnight is worse than a test that says plainly which half it is
proving.
"""

from collections import Counter

import pytest
from sqlalchemy import select

from conftest import ALICE, GUILD_A
from fake_discord import FakeBot, FakeChannel, FakeGuild, FakeMember
from test_restocking import end_of_day

import bot
import content as content_module
import content_loader
import database
import phrasing
import resolve
import restocking

CHANNEL = content_module.CHANNEL_ROOM
LIBRARY = content_module.SECRET_LIBRARY
FLOOR = database.LOOSE_IN_ROOM
SWAT = "channel.arrival"

# Every room's thread, so a line posted into one can be read back. The
# names are `rooms.tsv`'s, because `get_thread_for_room` matches on them.
ROOM_THREADS = (
    "Entryway",
    "Dining Room",
    "Kitchen",
    "Courtyard",
    "Living Room",
    "Upstairs Hallway",
    "Bedroom",
    "Nursery",
)

_RUN_ALL = restocking.run_all


@pytest.fixture
async def house(db, monkeypatch):
    """A server on drop 46 with a thread standing open in every room."""
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    halloween.add_active(*ROOM_THREADS)
    guild = FakeGuild(GUILD_A, channels=[halloween], members=[FakeMember(ALICE)])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, 46)
    await db.ensure_user_exists(ALICE, GUILD_A)
    monkeypatch.setattr(bot, "bot", FakeBot(guild))
    return guild, halloween


async def sweep(monkeypatch, now=None):
    """The real sweep, with only the clock pinned.

    The toy row's window shuts at 23:00, so a suite run after that
    would sweep a day with nothing due in it and every assertion here
    would pass for the wrong reason.
    """
    when = end_of_day() if now is None else now
    monkeypatch.setattr(restocking, "run_all", lambda ids: _RUN_ALL(ids, now=when))
    await bot.restock_sweep.coro()


def one_spot(monkeypatch, room, container=FLOOR):
    """Pin the draw to a single spot, so a test can name where it lands."""

    async def only(guild_id):
        return [(room, container)]

    monkeypatch.setattr(restocking, "_scatter_spots", only)


def thread(halloween, name):
    return next(t for t in halloween.threads if t.name == name)


async def toys_out():
    """Every toy in the house, as (room, container, thing, count)."""
    session_factory = database._require_session()
    async with session_factory() as session:
        return (
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


def row_five():
    return next(r for r in content_module.load().restocks if r.restock_id == 5)


# --------------------------------------------------------------------------
# Floors are spots
# --------------------------------------------------------------------------


async def test_every_room_a_player_can_stand_in_has_a_floor_to_scatter_to(house):
    """The change itself, read off the real content rather than a list.

    `rooms.tsv` has no `scatter_target` column - four columns and none
    of them is this one - so there is nothing to opt a room in with and
    nothing to read. Every arrived room is in by being arrived, which
    is why this asserts equality rather than containment: a room added
    to the files in a later drop joins without anybody remembering to
    come back here.
    """
    spots = await restocking._scatter_spots(GUILD_A)

    floors = {room for room, container in spots if container == FLOOR}
    expected = await resolve.arrived_rooms(GUILD_A)

    assert floors == expected - {CHANNEL, LIBRARY}
    assert len(floors) == 8


async def test_both_kinds_of_spot_are_in_the_one_list(house):
    """A floor and a cupboard are the same sort of answer to the same
    question, so they come back from one selector and go into one
    draw. Two lists would be two chances to weight them by accident."""
    spots = await restocking._scatter_spots(GUILD_A)

    assert any(container == FLOOR for _, container in spots)
    assert any(container != FLOOR for _, container in spots)
    assert ("LI", FLOOR) in spots
    assert ("LI", "fireplace") in spots


async def test_a_toy_lands_loose_on_a_floor(house, monkeypatch):
    """End to end, with the draw pinned to the Living Room floor.

    What this holds is that a floor survives the whole pipeline -
    `_destination` to `_place` to a `room_contents` row with an empty
    `container_id` - which is the part the selector cannot prove.

    **Passes without the change**, because pinning the selector is
    exactly what routes around it. The two tests above are the ones
    that go red; this is here so that a later change to `_place` or to
    the upsert key cannot quietly make a floor unlandable while the
    list still offers one.
    """
    one_spot(monkeypatch, "LI")

    await sweep(monkeypatch)

    placed = await toys_out()
    assert placed
    assert all((room, container) == ("LI", FLOOR) for room, container, _, _ in placed)


async def test_a_toy_still_lands_inside_something(house, monkeypatch):
    """The other half, unchanged, and worth one assertion because the
    change could have been made by deleting the container branch.

    **Passes without the change** - that is the point of it. Drop 46
    was container-only and has to stay able to be.
    """
    one_spot(monkeypatch, "LI", "fireplace")

    await sweep(monkeypatch)

    placed = await toys_out()
    assert placed
    assert all(
        (room, container) == ("LI", "fireplace") for room, container, _, _ in placed
    )


# --------------------------------------------------------------------------
# One draw, no weighting
# --------------------------------------------------------------------------


async def test_a_floor_is_exactly_as_likely_as_a_cupboard(house):
    """**No weighting, stated as the thing that would implement it.**

    There is no weight column and the decision was to add none, so the
    only way a spot could be favoured is by appearing in the list more
    than once. This reads the list `_destination` actually offers to
    `rng.choice` and counts it: every spot once, so a whole room's
    floor sits against one cupboard at even odds. That is the same
    trade `_slots` already makes for the bottles.

    **Passes without the change**, because a list of fourteen
    containers has no duplicates either. It is the guard *for* the
    change: floors are the first spots anybody would be tempted to
    weight, and the cheapest way to do it would be to list each one
    twice.
    """
    spots = await restocking._scatter_spots(GUILD_A)
    offered = {}

    class Recording:
        def choice(self, sequence):
            offered["seen"] = list(sequence)
            return sequence[0]

    restocking._destination(row_five(), [], {}, Recording(), spots)

    assert offered["seen"] == spots
    assert set(Counter(offered["seen"]).values()) == {1}


async def test_the_draw_is_a_third_floors_by_how_the_house_is_furnished(house):
    """The ratio nobody tuned, written down so a change to it is visible.

    Eight floors and fourteen containers at drop 46, so a little over a
    third of arrivals are in plain sight. This is not a target - it
    falls out of how many containers the files happen to describe - but
    an unremarked drift to four fifths would change the drop, and the
    number belongs somewhere a diff can show it moving.
    """
    spots = await restocking._scatter_spots(GUILD_A)
    floors = [spot for spot in spots if spot[1] == FLOOR]

    assert (len(floors), len(spots)) == (8, 22)


# --------------------------------------------------------------------------
# Where a scattered toy still never goes
# --------------------------------------------------------------------------


async def test_the_road_has_no_floor_in_the_draw(house):
    """Drop 46's first promise, and now the one the floors could have
    broken. Row 4 is still in the files stocking the channel for a
    server below 46; the road getting toys from both rows would be two
    schedules for one place.

    **Passes without the change**, because a selector that returned no
    floors at all returned no channel floor either. It is here for the
    next person to widen the list.
    """
    spots = await restocking._scatter_spots(GUILD_A)

    assert (CHANNEL, FLOOR) not in spots
    assert all(room != CHANNEL for room, _ in spots)


async def test_the_library_floor_is_no_better_than_its_shelves(house):
    """The library is found per player, so a toy on its floor is out of
    play and holding one of the six until the drain comes for it - the
    same reason its shelves were never drawn.

    **Passes without the change**, for the same reason as the road: the
    exclusion already existed for containers and the floors inherit it.
    """
    await resolve.set_current_drop(GUILD_A, 50)

    spots = await restocking._scatter_spots(GUILD_A)

    assert LIBRARY in await resolve.arrived_rooms(GUILD_A)
    assert all(room != LIBRARY for room, _ in spots)


async def test_a_room_that_has_not_opened_has_no_floor_either(house):
    """`random` does not ask this and does not need to - the sweep
    clears what lands in a shut room on the next tick. A toy is
    different: it counts against the cap for as long as it sits there.

    **Passes without the change** - the arrived-room filter is the one
    piece of `_scatter_spots` the floors did not have to be taught.
    """
    await resolve.set_current_drop(GUILD_A, 25)

    spots = await restocking._scatter_spots(GUILD_A)
    rooms = {room for room, _ in spots}

    assert rooms <= await resolve.arrived_rooms(GUILD_A)
    assert "BE" not in rooms
    assert ("BE", FLOOR) not in spots


# --------------------------------------------------------------------------
# The line
# --------------------------------------------------------------------------


async def test_a_toy_in_the_open_is_announced_with_the_cat_swatting_it(
    house, monkeypatch
):
    """The decision, in the room it happens in.

    A thing appearing on the floor in front of everybody standing there
    is the case `_announce_arrival` was written for on the road, and
    the house is no different. The copy is the road's, unchanged and
    not reworded for a room: it never names what came, so it is as true
    of a wine cork in the Living Room as of a toy on the channel floor.
    """
    _, halloween = house
    one_spot(monkeypatch, "LI")

    await sweep(monkeypatch)

    assert await phrasing.default_say(SWAT) in thread(halloween, "Living Room").posted


async def test_a_toy_in_a_cupboard_is_not_announced(house, monkeypatch):
    """The half that stays quiet, and the reason the notice reads the
    placement rather than the row.

    A hair tie that turned up inside the sideboard has not slid
    anywhere, so the line would be false; and it is the reward for
    `/look sideboard`, so the line would also spend it.

    **Passes without the change**, because row 5 carried no notice at
    all before this and announced nothing either way. What it guards is
    the next row that gets one.
    """
    _, halloween = house
    one_spot(monkeypatch, "LI", "fireplace")

    await sweep(monkeypatch)

    assert await toys_out()
    assert thread(halloween, "Living Room").posted == []


async def test_the_room_hears_it_once_however_many_landed(house, monkeypatch):
    """Six toys onto one floor in one sweep, and one sentence about it.

    The line never names what came, so it reads the same for one toy or
    six - whereas six identical sentences in a row read as a bug rather
    than as six toys. That was already `_announce_arrival`'s rule for
    the channel; drop 46 is what made it reachable in a room, because
    six occurrences now draw from twenty-two spots and a catch-up sweep
    places everything it owes at once.
    """
    _, halloween = house
    one_spot(monkeypatch, "LI")

    await sweep(monkeypatch)

    landed = sum(count for _, _, _, count in await toys_out())
    assert landed == 6
    assert thread(halloween, "Living Room").posted == [await phrasing.default_say(SWAT)]


async def test_the_line_is_the_road_s_own_key(house):
    """One key, so the sentence cannot drift in one place and not the
    other. `drop.1.announce` is already duplicated away from this for
    exactly that reason - a writer who wants the house to read
    differently from the road should have to say so in the files."""
    assert row_five().arrival_notice == SWAT
    assert await phrasing.default_say(SWAT)


async def test_an_empty_room_hears_nothing_and_keeps_the_toy(house, monkeypatch):
    """No thread means nobody is standing there, and this line is about
    something coming into view in front of people.

    Losing it is the right outcome rather than a gap to fill: the toy
    is on the floor either way and the next `/look` finds it. Asserted
    together, because the dangerous version of this is the sweep
    raising on the missing thread and taking the placement with it.

    **Read off the threads and not off the channel**, which also says
    something worth knowing: the channel may well have a swat line in
    it after this sweep, because rows 2 and 3 scatter bottles and
    diapers with placement `random` and one of those can land on the
    road's floor. That is `_announce_arrival`'s own doing and predates
    all of this.

    **Passes without the change**, because row 5 said nothing in any
    room before it. What it guards is the sweep raising on the missing
    thread: the notice is cosmetic and the placement is not, and an
    exception here would take the toy with it.
    """
    _, halloween = house
    halloween.threads = [t for t in halloween.threads if t.name != "Nursery"]
    one_spot(monkeypatch, "NU")

    await sweep(monkeypatch)

    placed = await toys_out()
    line = await phrasing.default_say(SWAT)
    assert placed
    assert {(room, container) for room, container, _, _ in placed} == {("NU", FLOOR)}
    assert [t.name for t in halloween.threads if line in t.posted] == []
