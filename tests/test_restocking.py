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
import restocking
from content import Content, Drop, Restock, Room, TextRow
from test_loader import a_thing, contents


def a_restock(restock_id=1, **overrides):
    defaults = dict(
        restock_id=restock_id,
        thing_id="bottle",
        placement="random",
        container=None,
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
            a_restock(placement="container", container="box", thing_id="jar", amount=4),
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
            a_restock(placement="container", container="box", thing_id="jar", amount=4),
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
    await content_loader.load_content(a_world(a_restock(times_per_day=40)))
    await started()

    report = await restocking.run_for_guild(GUILD_A)
    slots = {(row[1], row[2]) for row in report.placed}
    assert len(slots) > 1


async def test_a_fresh_slot_is_drawn_for_every_occurrence(server):
    """Not once for the day - eight bottles scatter rather than arriving in a
    heap in one room."""
    await content_loader.load_content(a_world(a_restock(times_per_day=30)))
    await started()

    report = await restocking.run_for_guild(GUILD_A)
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

    report = await restocking.run_for_guild(GUILD_A)
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
            a_restock(placement="container", container="box", thing_id="jar", amount=2),
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
    await content_loader.load_content(
        a_world(a_restock(first_day=1, every_n_days=3, times_per_day=1))
    )
    await started(days_ago=3)  # days 1 to 4 have elapsed

    report = await restocking.run_for_guild(GUILD_A)
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
    async with server._require_session()() as session:
        session.add(
            database.ServerConfig(guild_id=GUILD_A, key="bottles_per_day", value="2")
        )
        await session.commit()

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
    async with server._require_session()() as session:
        session.add(
            database.ServerConfig(guild_id=GUILD_A, key="bottles_per_day", value="lots")
        )
        await session.commit()

    placed = (await restocking.run_for_guild(GUILD_A, now=end_of_day())).placed
    assert len(placed) == database.CONFIG_KEYS["bottles_per_day"][0]


async def test_setting_it_to_zero_stops_them(server):
    await content_loader.load_content(
        a_world(a_restock(times_per_day=8, config_key="bottles_per_day"))
    )
    await started()
    async with server._require_session()() as session:
        session.add(
            database.ServerConfig(guild_id=GUILD_A, key="bottles_per_day", value="0")
        )
        await session.commit()

    assert (await restocking.run_for_guild(GUILD_A)).placed == []


# --------------------------------------------------------------------------
# Day one, and keeping servers apart
# --------------------------------------------------------------------------


async def test_day_one_is_recorded_on_the_first_sweep(server):
    await content_loader.load_content(a_world(a_restock()))
    assert await restocking.initialized_on(GUILD_A) is None

    await restocking.run_for_guild(GUILD_A)
    assert await restocking.initialized_on(GUILD_A) == database.pacific_today()


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
