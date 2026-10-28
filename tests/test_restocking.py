"""The restock scheduler.

The work order asks for the container path, the random path, a faked one-day
cycle and catch-up to be tested separately, so they are.

The rule doing most of the work is that occurrence times are *derived* from a
seed of (guild, restock, day) rather than rolled and stored. Asking twice gives
the same answer, which is what makes catch-up, restarts and double-sweeps all
the same question: what should have happened between the last one applied and
now? Several tests below exist to hold that property rather than to check a
behaviour a player would notice.
"""

from collections import Counter
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from conftest import ALICE, GUILD_A, GUILD_B

import content as content_module
import content_loader
import database
import resolve
import restocking
from content import Content, Drop, Restock, Room, TextRow
from test_loader import a_thing, contents


def a_restock(restock_id=1, **overrides):
    defaults = dict(
        restock_id=restock_id,
        thing_id="bottle",
        placement="random",
        destination=None,
        max_present=None,
        amount=1,
        times_per_day=1,
        first_day=1,
        every_n_days=1,
        window_start="00:00",
        window_end="23:59",
        config_key=None,
        since_drop=1,
        notes=None,
    )
    return Restock(**{**defaults, **overrides})


def a_world(*restocks, things=()):
    parsed = Content()
    parsed.rooms = [
        Room(room_id=r, name=r, sort_order=i, open_at_launch=True)
        for i, r in enumerate(("EN", "KI"))
    ]
    parsed.room_text = [
        TextRow(entity_id=r, state="default", since_drop=1, text={"look": f"The {r}."})
        for r in ("EN", "KI")
    ]
    parsed.things = list(things) or [
        a_thing("bottle", name="bottle", room_id=None, quantity=0)
    ]
    parsed.thing_text = [
        TextRow(entity_id=t.thing_id, state="default", since_drop=1, text={"look": "A thing."})
        for t in parsed.things
    ]
    parsed.defaults = dict(content_module.load_files().defaults)
    parsed.drops = [
        Drop(drop_id=1, trigger="date", date="launch", event=None, name="Launch", notes=None)
    ]
    parsed.restocks = list(restocks)
    return parsed


@pytest.fixture
async def server(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    return db


async def started(days_ago=0, guild_id=GUILD_A):
    on = database.pacific_today() - timedelta(days=days_ago)
    await restocking.set_initialized_on(guild_id, on)
    return on


def end_of_day(offset=0):
    """The last moment of a Pacific day, as naive UTC.

    `now` and the day now derive from each other, so a test that means "after
    everything today" has to say so precisely rather than adding 24 hours -
    which would roll into tomorrow and generate tomorrow's arrivals too.
    """
    day = database.pacific_today() + timedelta(days=offset)
    local = datetime.combine(day, datetime.max.time(), tzinfo=database.PACIFIC)
    return local.astimezone(database.timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------
# Day numbers
# --------------------------------------------------------------------------


def test_the_first_day_is_day_one():
    start = date(2026, 10, 1)
    assert restocking.day_number(start, start) == 1


def test_days_count_forward():
    start = date(2026, 10, 1)
    assert restocking.day_number(start, date(2026, 10, 5)) == 5


@pytest.mark.parametrize(
    "first, every, day, expected",
    [
        (1, 1, 1, True),
        (1, 1, 7, True),
        (2, 3, 1, False),   # before it starts
        (2, 3, 2, True),    # first day
        (2, 3, 3, False),
        (2, 3, 5, True),    # every third
        (2, 3, 8, True),
    ],
)
def test_which_days_a_schedule_fires_on(first, every, day, expected):
    assert restocking.is_active_day(first, every, day) is expected


# --------------------------------------------------------------------------
# Derived times
# --------------------------------------------------------------------------


def test_asking_twice_gives_the_same_times():
    """The property the whole design rests on. If this drifts, a restart
    redraws and the scheduler either skips or doubles."""
    a = restocking.occurrence_times(1, 1, 1, date(2026, 10, 1), 8, "00:00", "23:59")
    b = restocking.occurrence_times(1, 1, 1, date(2026, 10, 1), 8, "00:00", "23:59")
    assert a == b


def test_different_servers_draw_different_times():
    a = restocking.occurrence_times(1, 1, 1, date(2026, 10, 1), 8, "00:00", "23:59")
    b = restocking.occurrence_times(2, 1, 1, date(2026, 10, 1), 8, "00:00", "23:59")
    assert a != b


def test_different_days_draw_different_times():
    a = restocking.occurrence_times(1, 1, 1, date(2026, 10, 1), 8, "00:00", "23:59")
    b = restocking.occurrence_times(1, 1, 2, date(2026, 10, 2), 8, "00:00", "23:59")
    assert a != b


def test_times_per_day_is_a_count_of_occurrences():
    """Eight bottles a day is eight arrivals of one, not one delivery of eight."""
    times = restocking.occurrence_times(1, 1, 1, date(2026, 10, 1), 8, "00:00", "23:59")
    assert len(times) == 8
    assert len(set(times)) == 8


def test_times_come_back_in_order():
    times = restocking.occurrence_times(1, 1, 1, date(2026, 10, 1), 8, "00:00", "23:59")
    assert times == sorted(times)


def test_times_fall_inside_the_window():
    times = restocking.occurrence_times(1, 1, 1, date(2026, 10, 1), 20, "09:00", "17:00")
    opens = datetime.combine(date(2026, 10, 1), datetime.min.time(), tzinfo=database.PACIFIC)

    for moment in times:
        local = moment.replace(tzinfo=database.timezone.utc).astimezone(database.PACIFIC)
        assert 9 <= local.hour < 17 or (local.hour == 17 and local.minute == 0)


def test_a_seed_is_stable_across_processes():
    """Python salts hash() per process, so using it would redraw every restart.
    This asserts the digest, not the hash."""
    times = restocking.occurrence_times(42, 7, 3, date(2026, 10, 1), 3, "00:00", "23:59")
    again = restocking.occurrence_times(42, 7, 3, date(2026, 10, 1), 3, "00:00", "23:59")
    assert times == again


# --------------------------------------------------------------------------
# The container path
# --------------------------------------------------------------------------


async def test_a_container_row_always_lands_in_its_container(server):
    await content_loader.load_content(
        a_world(
            a_restock(placement="container", destination="box", thing_id="jar", amount=4),
            things=[
                a_thing("box", name="box", type="fixture", takeable=False),
                a_thing("jar", name="jar", room_id=None, quantity=0),
            ],
        )
    )
    await started()

    # Pinned to the end of the day like every other placement test: the
    # occurrence time is derived, so a bare `now` makes this pass or fail
    # depending on the hour it is run at.
    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())
    assert report.placed
    assert all(row[2] == "box" for row in report.placed)


async def test_the_container_row_adds_its_full_amount(server):
    await content_loader.load_content(
        a_world(
            a_restock(placement="container", destination="box", thing_id="jar", amount=4),
            things=[
                a_thing("box", name="box", type="fixture", takeable=False),
                a_thing("jar", name="jar", room_id=None, quantity=0),
            ],
        )
    )
    await started()
    await restocking.run_for_guild(GUILD_A, now=end_of_day())

    rows = [r for r in await contents(server, GUILD_A) if r[2] == "jar"]
    assert sum(r[3] for r in rows) == 4


# --------------------------------------------------------------------------
# The random path
# --------------------------------------------------------------------------


async def test_a_random_row_scatters_across_slots(server):
    """**The clock is pinned, and it has to be.**

    Only occurrences that have already come due are placed, and a day's
    forty are scattered through it - so at one in the morning this had
    one placement to look at and no two slots to find among them. The
    three tests here ask about the *spread* of a day's arrivals, which
    means they have to ask after the day has had them.
    """
    await content_loader.load_content(a_world(a_restock(times_per_day=40)))
    await started()

    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())
    slots = {(row[1], row[2]) for row in report.placed}
    assert len(slots) > 1


async def test_a_fresh_slot_is_drawn_for_every_occurrence(server):
    """Not once for the day - eight bottles scatter rather than arriving in a
    heap in one room."""
    await content_loader.load_content(a_world(a_restock(times_per_day=30)))
    await started()

    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())
    counts = Counter((row[1], row[2]) for row in report.placed)
    assert max(counts.values()) < len(report.placed)


async def test_random_placement_can_land_inside_a_container(server):
    """Nine rooms and twelve containers, drawn from uniformly."""
    await content_loader.load_content(
        a_world(
            a_restock(times_per_day=60),
            things=[
                a_thing("bottle", name="bottle", room_id=None, quantity=0),
                a_thing("box", name="box", type="fixture", takeable=False),
                a_thing("jar", name="jar", contained_in="box"),
            ],
        )
    )
    await started()

    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())
    assert any(row[2] for row in report.placed)


# --------------------------------------------------------------------------
# One day, and the day after
# --------------------------------------------------------------------------


async def test_a_one_day_cycle_places_the_days_occurrences(server):
    await content_loader.load_content(a_world(a_restock(times_per_day=5)))
    await started()

    # End of the day, so every occurrence has come due.
    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())

    assert len(report.placed) == 5


async def test_a_second_sweep_places_nothing_new(server):
    await content_loader.load_content(a_world(a_restock(times_per_day=5)))
    await started()

    await restocking.run_for_guild(GUILD_A, now=end_of_day())
    again = await restocking.run_for_guild(GUILD_A, now=end_of_day())

    assert again.placed == []


async def test_stock_is_incremented_not_assigned(server):
    """A restock tops up what is there rather than resetting it."""
    await content_loader.load_content(
        a_world(
            a_restock(placement="container", destination="box", thing_id="jar", amount=2),
            things=[
                a_thing("box", name="box", type="fixture", takeable=False),
                a_thing("jar", name="jar", room_id=None, quantity=0),
            ],
        )
    )
    await started()
    await restocking.run_for_guild(GUILD_A)

    # A second day's delivery adds to the first.
    await restocking.run_for_guild(GUILD_A, now=end_of_day(1))

    rows = [r for r in await contents(server, GUILD_A) if r[2] == "jar"]
    assert sum(r[3] for r in rows) == 4


async def test_nothing_fires_before_its_first_day(server):
    await content_loader.load_content(a_world(a_restock(first_day=5)))
    await started()

    assert (await restocking.run_for_guild(GUILD_A)).placed == []


async def test_every_n_days_skips_the_days_between(server):
    """**The clock is pinned, and it has to be.**

    Day 4 is today, and today's single occurrence is scattered
    somewhere in its window by a seed drawn from (guild, restock, day)
    - so "has it happened yet" depends on the hour the test runs and on
    a time that is redrawn every day. Unpinned, this asserted that
    today's delivery was already in the past: it passed all evening and
    failed in the small hours. CI caught it at 01:50 Pacific against an
    occurrence due at 02:32, forty-two minutes short.

    `end_of_day` exists for exactly this and seven other tests here use
    it. This one is the only place an exact count was asked for without
    saying when.
    """
    await content_loader.load_content(
        a_world(a_restock(first_day=1, every_n_days=3, times_per_day=1))
    )
    await started(days_ago=3)  # days 1 to 4 have elapsed

    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())
    assert len(report.placed) == 2  # days 1 and 4


# --------------------------------------------------------------------------
# Catch-up
# --------------------------------------------------------------------------


async def test_a_missed_day_is_applied_when_the_bot_returns(server):
    """The work order's test: move the initialization date backwards."""
    await content_loader.load_content(a_world(a_restock(times_per_day=2)))
    await started(days_ago=3)

    report = await restocking.run_for_guild(GUILD_A)
    # Three full days plus whatever of today has elapsed.
    assert len(report.placed) >= 6


async def test_catch_up_is_capped(server):
    """A long outage costs bounded work, not a year of placements at once."""
    await content_loader.load_content(a_world(a_restock(times_per_day=1)))
    await started(days_ago=400)

    report = await restocking.run_for_guild(GUILD_A)
    assert len(report.placed) <= restocking.MAX_CATCHUP_DAYS + 1


async def test_future_occurrences_are_not_placed_early(server):
    """Today's arrivals that have not happened yet stay in the future."""
    await content_loader.load_content(a_world(a_restock(times_per_day=20)))
    await started()

    midnight = datetime.combine(
        database.pacific_today(), datetime.min.time(), tzinfo=database.PACIFIC
    ).astimezone(database.timezone.utc).replace(tzinfo=None)

    report = await restocking.run_for_guild(GUILD_A, now=midnight)
    assert len(report.placed) < 20


# --------------------------------------------------------------------------
# Admin overrides
# --------------------------------------------------------------------------


async def test_config_key_changes_how_many_arrive(server):
    await content_loader.load_content(
        a_world(a_restock(times_per_day=8, config_key="bottles_per_day"))
    )
    await started()
    await database.set_config(GUILD_A, "bottles_per_day", "2")

    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())
    assert len(report.placed) == 2


async def test_an_unset_config_key_uses_its_default(server):
    await content_loader.load_content(
        a_world(a_restock(times_per_day=99, config_key="bottles_per_day"))
    )
    await started()

    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())
    assert len(report.placed) == restocking.CONFIG_DEFAULTS["bottles_per_day"]


async def test_a_nonsense_config_value_falls_back_rather_than_crashing(server):
    """Falls back to the registry default, not the row's own number.

    Once a row names a config_key, that setting governs and the registry is
    the one place its default lives - so /admin_config cannot report one
    default while the scheduler quietly uses another. In the shipped content
    the two agree anyway.
    """
    await content_loader.load_content(
        a_world(a_restock(times_per_day=3, config_key="bottles_per_day"))
    )
    await started()
    await database.set_config(GUILD_A, "bottles_per_day", "lots")

    placed = (await restocking.run_for_guild(GUILD_A, now=end_of_day())).placed
    assert len(placed) == database.CONFIG_KEYS["bottles_per_day"][0]


async def test_setting_it_to_zero_stops_them(server):
    await content_loader.load_content(
        a_world(a_restock(times_per_day=8, config_key="bottles_per_day"))
    )
    await started()
    await database.set_config(GUILD_A, "bottles_per_day", "0")

    assert (await restocking.run_for_guild(GUILD_A)).placed == []


# --------------------------------------------------------------------------
# Day one, and keeping servers apart
# --------------------------------------------------------------------------


async def test_the_sweep_does_not_start_the_clock(server):
    """Day one is the day the first player runs `/enter`, not the day the
    sweep first ran. The sweep visits every guild the bot is in, including
    ones where the house is built and nobody has come in yet - starting the
    calendar there would put spice jars in the Amazon box before anybody
    could find them."""
    await content_loader.load_content(a_world(a_restock()))

    await restocking.run_for_guild(GUILD_A)

    assert await restocking.initialized_on(GUILD_A) is None


async def test_a_row_that_counts_days_places_nothing_before_anybody_has_entered(
    server,
):
    """A row whose schedule depends on *which* day it is has no day to
    read before `/enter` sets one, so it stays put. Spice jars start on
    day 2 and come every third day after; without a day one, "day 2" is
    not a question with an answer."""
    await content_loader.load_content(
        a_world(a_restock(first_day=2, every_n_days=3))
    )

    assert (await restocking.run_for_guild(GUILD_A, now=end_of_day())).placed == []


async def test_but_a_row_that_fires_every_day_does_not_wait_for_one(server):
    """**The bug this fixes.** Day one is set by `/enter`, which is a
    drop-3 command, so before the house opens there was no day one at
    all and the sweep returned empty for every guild. Drop 2's channel
    fills from a row that fires every day and has no calendar to
    read - it never fired once, and the drop shipped with whatever its
    content rows had placed on arrival and nothing after.

    Falling back to today costs the counting rows nothing: for them
    every day is day 1, which is before `first_day` or off the cycle,
    so they still stay put until somebody enters.
    """
    await content_loader.load_content(a_world(a_restock()))

    assert (await restocking.run_for_guild(GUILD_A, now=end_of_day())).placed


async def test_and_it_still_does_not_start_the_clock(server):
    """The fallback is read, not written. A guild the bot merely sits in
    must not have its day one stamped by a sweep, or the counting rows
    would start their calendars at boot."""
    await content_loader.load_content(a_world(a_restock()))

    await restocking.run_for_guild(GUILD_A, now=end_of_day())

    assert await restocking.initialized_on(GUILD_A) is None


async def test_the_sweep_runs_normally_once_day_one_is_set(server):
    """And the moment somebody enters, the calendar is live."""
    await content_loader.load_content(a_world(a_restock()))
    await restocking.set_initialized_on(GUILD_A)

    assert (await restocking.run_for_guild(GUILD_A, now=end_of_day())).placed


async def test_day_one_is_not_moved_once_set(server):
    await content_loader.load_content(a_world(a_restock()))
    original = await started(days_ago=10)

    await restocking.run_for_guild(GUILD_A)
    assert await restocking.initialized_on(GUILD_A) == original


async def test_servers_count_their_own_days(db):
    """Deliberately the opposite of drops, which land on the same day
    everywhere."""
    for guild in (GUILD_A, GUILD_B):
        await db.ensure_user_exists(ALICE, guild)
    await content_loader.load_content(a_world(a_restock(first_day=3)))

    await started(days_ago=5, guild_id=GUILD_A)
    await started(days_ago=0, guild_id=GUILD_B)

    assert (await restocking.run_for_guild(GUILD_A)).placed
    assert (await restocking.run_for_guild(GUILD_B)).placed == []


async def test_stock_does_not_leak_between_servers(db):
    for guild in (GUILD_A, GUILD_B):
        await db.ensure_user_exists(ALICE, guild)
    await content_loader.load_content(a_world(a_restock(times_per_day=3)))
    await started(guild_id=GUILD_A)

    await restocking.run_for_guild(GUILD_A)
    assert await contents(db, GUILD_B) == []


# --------------------------------------------------------------------------
# A room holds nothing a player could not reach
#
# The sweep that clears what the scheduler left behind while it was not
# reading drops. One rule - a player standing where they are allowed to
# stand can reach every row in a room - and three ways to break it.
# --------------------------------------------------------------------------


def a_world_in_two_drops():
    """EN and a bottle on drop 1; KI, a crate and a later thing on drop 2."""
    parsed = a_world(
        a_restock(times_per_day=0),
        things=[
            a_thing("bottle", name="bottle", room_id=None, quantity=0),
            a_thing("pebble", name="pebble", room_id=None, quantity=0, since_drop=0),
            a_thing("later", name="later", room_id=None, quantity=0, since_drop=2),
            a_thing(
                "crate", name="crate", type="fixture", takeable=False, since_drop=2
            ),
        ],
    )
    parsed.rooms.append(Room(room_id=CHANNEL, name="the channel", sort_order=9,
                             open_at_launch=False))
    parsed.thing_text.append(
        TextRow(entity_id="pebble", state="default", since_drop=0,
                text={"look": "A pebble."})
    )
    parsed.room_text = [
        TextRow(entity_id="EN", state="default", since_drop=1, text={"look": "The EN."}),
        TextRow(entity_id="KI", state="default", since_drop=2, text={"look": "The KI."}),
        TextRow(entity_id=CHANNEL, state="default", since_drop=1,
                text={"look": "The road."}),
    ]
    parsed.drops.append(
        Drop(drop_id=2, trigger="manual", date=None, event=None, name="Two", notes=None)
    )
    # Drop 0 as well, because one of these tests stands on it: the road
    # is a place before it has any prose of its own.
    parsed.drops.insert(
        0, Drop(drop_id=0, trigger="manual", date=None, event=None, name="Zero", notes=None)
    )
    return parsed


@pytest.fixture
async def two_drops(server):
    await content_loader.load_content(a_world_in_two_drops())
    await resolve.set_current_drop(GUILD_A, 1)
    await started()
    return server


async def swept(db):
    await restocking.run_for_guild(GUILD_A, now=end_of_day())
    return await contents(db, GUILD_A)


async def test_a_thing_whose_drop_has_not_arrived_is_cleared(two_drops):
    """**The bottles in the Entryway.** The room listed them under
    `Also here:` and no verb reached them, because the parser was right
    that they are not here yet."""
    await database.place_in_room(GUILD_A, "EN", "later", 1)

    assert [r for r in await swept(two_drops) if r[2] == "later"] == []


async def test_a_room_that_has_not_arrived_is_emptied(two_drops):
    """**The pile waiting to surface.** A month of litter in a room that
    has not opened is a room that opens holding a month of litter."""
    await database.place_in_room(GUILD_A, "KI", "bottle", 1)

    assert [r for r in await swept(two_drops) if r[0] == "KI"] == []


async def test_a_container_that_has_not_arrived_takes_its_contents_with_it(two_drops):
    """The spice jars went into an Amazon box two drops ahead of the
    server. The jars were fine; the box they were in was not."""
    await restocking._place(GUILD_A, "EN", "crate", "bottle", 1)

    assert [r for r in await swept(two_drops) if r[1] == "crate"] == []


async def test_what_a_player_can_reach_is_left_alone(two_drops):
    """The half that stops this being a tidy-everything-away job."""
    await database.place_in_room(GUILD_A, "EN", "bottle", 1)

    assert ("EN", database.LOOSE_IN_ROOM, "bottle", 1) in await swept(two_drops)


async def test_the_channel_is_not_emptied_for_want_of_prose(two_drops):
    """**The drop 0 edge.** A room arrives with its description, and the
    channel's first fragment is drop 1 - but standing on the road is
    valid from drop 0, before there is anything to read there. A sweep
    that asked only `arrived_rooms` would clear the road out from under
    the people standing on it."""
    await resolve.set_current_drop(GUILD_A, 0)
    await database.place_in_room(GUILD_A, CHANNEL, "pebble", 1)

    assert ("CH", database.LOOSE_IN_ROOM, "pebble", 1) in await swept(two_drops)


async def test_a_guild_with_no_game_is_not_emptied(two_drops):
    """Nothing arrived is not a licence to delete everything. A server
    the bot is only a member of has no pointer, and the rule read
    literally would empty it - which is one bad migration away from
    being a disaster."""
    never_started = 777000000000000777
    await database.place_in_room(never_started, "EN", "bottle", 1)

    await restocking.run_for_guild(never_started, now=end_of_day())

    assert await contents(two_drops, never_started)


async def test_a_players_bag_is_never_swept(two_drops):
    """What somebody is carrying is theirs. A bag emptied by a
    background job is worse than a bag with something odd in it."""
    await database.place_in_room(GUILD_A, "EN", "later", 1)
    await database.take_from_room(
        ALICE, GUILD_A, "EN", database.LOOSE_IN_ROOM, "later"
    )

    await swept(two_drops)

    assert await database.carried_of(ALICE, GUILD_A, "later") == 1


# --------------------------------------------------------------------------
# Against the real schedules
# --------------------------------------------------------------------------


async def test_the_shipped_schedules_run(server):
    await content_loader.load_content(content_module.load_files())
    await started(days_ago=4)

    report = await restocking.run_for_guild(GUILD_A)
    placed = Counter(row[3] for row in report.placed)

    assert placed["used_baby_bottle"] > 0
    assert placed["dirty_diaper"] > 0
    assert placed["spice_jar"] > 0


async def test_the_spice_jars_go_in_the_amazon_box(server):
    await content_loader.load_content(content_module.load_files())
    await started(days_ago=4)

    report = await restocking.run_for_guild(GUILD_A)
    jars = [row for row in report.placed if row[3] == "spice_jar"]

    assert jars
    assert all(row[2] == "amazon_box" and row[1] == "EN" for row in jars)


async def test_the_box_is_empty_until_day_two(server):
    """The spice order arrives in batches from day 2, which is why the box's
    text describing what is inside it is wrong on day 1."""
    await content_loader.load_content(content_module.load_files())
    await started(days_ago=0)

    report = await restocking.run_for_guild(GUILD_A)
    assert not [row for row in report.placed if row[3] == "spice_jar"]


# --------------------------------------------------------------------------
# A class selector, and a cap counted across the class
#
# Drop 2's toys. One row keeps the channel stocked with either toy, and
# the cap is "two toys here" rather than "two of each" - with thirteen
# toy rows written, the per-row reading would allow twenty-six.
# --------------------------------------------------------------------------

CHANNEL = "CH"


def a_toy_world(*restocks, **kwargs):
    """Two toys and a channel, with a room row the loader will accept."""
    parsed = a_world(
        *restocks,
        things=[
            a_thing("wand", name="wand", room_id=None, quantity=0, type="toy"),
            a_thing("ball", name="ball", room_id=None, quantity=0, type="toy"),
        ],
    )
    parsed.rooms.append(
        Room(room_id=CHANNEL, name="the channel", sort_order=9, open_at_launch=False)
    )
    return parsed


def a_toy_restock(**overrides):
    return a_restock(
        thing_id="type:toy",
        placement="room",
        destination=CHANNEL,
        max_present=2,
        times_per_day=4,
        **overrides,
    )


async def toys_in_the_channel(db):
    return await db.count_of_type(GUILD_A, CHANNEL, "toy")


async def a_toy_lying_there() -> str:
    """The id of a toy actually in the channel.

    The draw is uniform over the class, so which toy turned up is not
    knowable in advance - only that one did.
    """
    from sqlalchemy import select

    async with database._require_session()() as session:
        return await session.scalar(
            select(database.RoomContents.thing_id).where(
                database.RoomContents.guild_id == GUILD_A,
                database.RoomContents.room_id == CHANNEL,
                database.RoomContents.count > 0,
            )
        )


async def test_a_class_selector_draws_from_the_type(server):
    await content_loader.load_content(a_toy_world(a_toy_restock()), allow_orphans=True)
    await started()

    await restocking.run_for_guild(GUILD_A, now=end_of_day())

    assert await toys_in_the_channel(server) == 2


async def test_the_cap_counts_the_class_not_the_row(server):
    """Four occurrences a day against a cap of two. Per row this would
    allow two of each and put four toys in the channel."""
    await content_loader.load_content(a_toy_world(a_toy_restock()), allow_orphans=True)
    await started()

    await restocking.run_for_guild(GUILD_A, now=end_of_day())

    assert await toys_in_the_channel(server) == 2


async def test_it_fills_back_toward_the_cap(server):
    """A better rule than a rate: a quiet server keeps two sitting
    there and a busy one keeps getting fresh ones."""
    await content_loader.load_content(a_toy_world(a_toy_restock()), allow_orphans=True)
    await started()
    await restocking.run_for_guild(GUILD_A, now=end_of_day())
    await database.take_from_room(
        ALICE, GUILD_A, CHANNEL, "", await a_toy_lying_there()
    )

    await restocking.run_for_guild(GUILD_A, now=end_of_day(1))

    assert await toys_in_the_channel(server) == 2


async def test_a_full_channel_banks_nothing(server):
    """The occurrence is spent whether or not it places, so a day of
    refusals does not dump four toys the moment somebody takes one."""
    await content_loader.load_content(a_toy_world(a_toy_restock()), allow_orphans=True)
    await started()
    await restocking.run_for_guild(GUILD_A, now=end_of_day())

    await database.take_from_room(
        ALICE, GUILD_A, CHANNEL, "", await a_toy_lying_there()
    )
    await restocking.run_for_guild(GUILD_A, now=end_of_day())

    assert await toys_in_the_channel(server) <= 2


async def test_the_cap_can_be_retuned_without_a_deploy(server):
    """Read from `server_config`, not from the row, so two rows drawing
    from one class cannot disagree about the limit."""
    await content_loader.load_content(
        a_toy_world(a_toy_restock(config_key="toys_present")), allow_orphans=True
    )
    await started()
    await database.set_setting(GUILD_A, "toys_present", 1)

    await restocking.run_for_guild(GUILD_A, now=end_of_day())

    assert await toys_in_the_channel(server) == 1


async def test_a_player_may_put_down_more_than_the_cap(server):
    """The cap governs the scheduler, not the world.

    The real sequence: the channel is full, somebody takes one, the
    scheduler refills it, and then they put theirs back. Three toys,
    and nothing should tidy one away - they put it there.
    """
    await content_loader.load_content(a_toy_world(a_toy_restock()), allow_orphans=True)
    await started()
    await restocking.run_for_guild(GUILD_A, now=end_of_day())

    # **Whichever toy is there**, not a named one: the class draw is
    # uniform, so a test that names one fails on the runs where two of
    # the other turned up. This one failed exactly that way, in the
    # full suite and never alone.
    mine = await a_toy_lying_there()
    await database.take_from_room(ALICE, GUILD_A, CHANNEL, "", mine)
    await restocking.run_for_guild(GUILD_A, now=end_of_day(1))
    assert await toys_in_the_channel(server) == 2

    await database.drop_into_room(ALICE, GUILD_A, CHANNEL, mine)

    assert await toys_in_the_channel(server) == 3


# --------------------------------------------------------------------------
# A row waits for its own drop
#
# The selector below has always checked the drop of what it draws. The
# row itself was never checked at all: `since_drop` was parsed, validated
# and stored from September, and the scheduler never read it.
# --------------------------------------------------------------------------


async def test_a_row_whose_drop_has_not_arrived_does_not_fire(server):
    """**The reported bug.** Eight used baby bottles a day - drop 30
    content - were scattering through servers on drop 10."""
    parsed = a_world(a_restock(since_drop=2))
    parsed.drops.append(
        Drop(drop_id=2, trigger="manual", date=None, event=None, name="Later", notes=None)
    )
    await content_loader.load_content(parsed)
    await resolve.set_current_drop(GUILD_A, 1)
    await started()

    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())

    assert report.placed == []


async def test_it_fires_once_its_drop_arrives(server):
    """The other half, so the test above cannot pass by placing nothing
    ever."""
    parsed = a_world(a_restock(since_drop=2))
    parsed.drops.append(
        Drop(drop_id=2, trigger="manual", date=None, event=None, name="Later", notes=None)
    )
    await content_loader.load_content(parsed)
    await resolve.set_current_drop(GUILD_A, 2)
    await started()

    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())

    assert report.placed


async def test_one_row_waiting_does_not_hold_up_another(server):
    """Each row answers for its own drop. The toys kept arriving on the
    beta the whole time the bottles were arriving early, and that is the
    behaviour to keep."""
    parsed = a_world(
        a_restock(1, since_drop=1),
        a_restock(2, thing_id="later", since_drop=2),
        things=[
            a_thing("bottle", name="bottle", room_id=None, quantity=0),
            a_thing("later", name="later thing", room_id=None, quantity=0),
        ],
    )
    parsed.drops.append(
        Drop(drop_id=2, trigger="manual", date=None, event=None, name="Later", notes=None)
    )
    await content_loader.load_content(parsed)
    await resolve.set_current_drop(GUILD_A, 1)
    await started()

    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())

    assert {row[3] for row in report.placed} == {"bottle"}


async def test_a_guild_the_bot_only_sits_in_is_left_alone(db):
    """**The quiet half of the same bug.** The sweep visits every guild
    the bot is in, and a guild with no drop pointer at all was taking ten
    scattered objects a day into rooms of a house nobody had built."""
    never_started = 777000000000000777
    await content_loader.load_content(a_world(a_restock(times_per_day=8)))

    report = await restocking.run_for_guild(never_started, now=end_of_day())

    assert await resolve.current_drop(never_started) is resolve.NO_GAME
    assert report.placed == []


async def test_the_shipped_bottles_wait_for_their_drop(server):
    """Against the real files, on the drop the beta server is on: the
    bottles and the spice jars are drop 30 and 20 and stay away, and the
    diapers are drop 10 now and keep coming."""
    await content_loader.load_content(content_module.load_files())
    await resolve.set_current_drop(GUILD_A, 10)
    await started(days_ago=4)

    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())
    placed = Counter(row[3] for row in report.placed)

    assert placed["used_baby_bottle"] == 0
    assert placed["spice_jar"] == 0
    assert placed["dirty_diaper"] > 0


async def test_a_toy_whose_drop_has_not_arrived_is_not_drawn(server):
    """A selector must never hand out content from a drop this server
    has not reached."""
    parsed = a_toy_world(a_toy_restock())
    parsed.things[1] = a_thing(
        "ball", name="ball", room_id=None, quantity=0, type="toy", since_drop=2
    )
    parsed.drops.append(
        Drop(drop_id=2, trigger="manual", date=None, event=None, name="Toys", notes=None)
    )
    await content_loader.load_content(parsed, allow_orphans=True)
    await started()
    # The fixture opens the house; this server has only reached drop 1.
    await resolve.set_current_drop(GUILD_A, 1)

    await restocking.run_for_guild(GUILD_A, now=end_of_day())

    placed = await database.present_of_type(GUILD_A, CHANNEL, "toy")
    assert "ball" not in placed


async def test_placing_stamps_when_it_landed(server):
    """`placed_at` reads nothing today and cannot be backfilled later:
    it is what will tell a toy nobody has wanted for a week from one
    that arrived an hour ago."""
    await content_loader.load_content(a_toy_world(a_toy_restock()), allow_orphans=True)
    await started()

    await restocking.run_for_guild(GUILD_A, now=end_of_day())

    async with database._require_session()() as session:
        stamped = await session.scalar(
            select(database.RoomContents.placed_at).where(
                database.RoomContents.guild_id == GUILD_A,
                database.RoomContents.room_id == CHANNEL,
            )
        )
    assert stamped is not None

# --------------------------------------------------------------------------
# One key, and which number it means
#
# `config_key` names the one number its row is about. A scatter row is
# defined by its rate; a top-up row is defined by its ceiling. Both
# read the same column, which is why registering `toys_present` without
# this split would have set the cap *and* halved the top-up frequency.
# --------------------------------------------------------------------------


async def test_a_capped_rows_key_tunes_the_cap(server):
    """Two in the channel, topped up toward a limit an admin can raise."""
    await content_loader.load_content(
        a_world(
            a_restock(
                thing_id="type:toy", placement="room", destination="EN",
                max_present=2, times_per_day=8, config_key="toys_present",
            ),
            things=[a_thing("feather_wand", type="toy", room_id=None, quantity=0)],
        )
    )
    await started()
    await database.set_config(GUILD_A, "toys_present", "3")

    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())

    assert len(report.placed) == 3


async def test_a_capped_rows_key_leaves_the_rate_alone(server):
    """**The half that would have broken quietly.** With the key read
    as the rate too, a cap of two would also have meant two top-ups a
    day instead of eight - a channel that refills half as often, for a
    setting that says nothing about frequency."""
    await content_loader.load_content(
        a_world(
            a_restock(
                thing_id="type:toy", placement="room", destination="EN",
                max_present=9, times_per_day=5, config_key="toys_present",
            ),
            things=[a_thing("feather_wand", type="toy", room_id=None, quantity=0)],
        )
    )
    await started()
    await database.set_config(GUILD_A, "toys_present", "9")

    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())

    assert len(report.placed) == 5  # the row's own rate, not the cap


async def test_an_uncapped_rows_key_still_tunes_the_rate(server):
    """The other side, unchanged: the bottles have no ceiling, so their
    key is the only number they have."""
    await content_loader.load_content(
        a_world(a_restock(times_per_day=8, config_key="bottles_per_day"))
    )
    await started()
    await database.set_config(GUILD_A, "bottles_per_day", "2")

    report = await restocking.run_for_guild(GUILD_A, now=end_of_day())

    assert len(report.placed) == 2


def test_the_shipped_toy_row_points_at_a_registered_key():
    """It did not, and the sweep logged a warning every ten minutes
    while falling back to the row's own numbers."""
    toys = next(
        r for r in content_module.load_files().restocks
        if r.thing_id == "type:toy"
    )

    assert toys.config_key == "toys_present"
    assert toys.config_key in database.CONFIG_KEYS

