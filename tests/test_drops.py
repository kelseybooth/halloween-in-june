"""Drop arrival, and the text a player sees because of it.

Every row in the shipped content is drop 1, so the mechanism is entirely
untested by the data - which is exactly why the work order asks for faked drops
rather than trust. Everything here builds a calendar by hand: a drop dated in
the past, one dated in the future, one waiting on an event, one waiting on an
admin.

The distinction the tests keep returning to is that a dated drop is *computed*
and an event drop is *recorded*. Getting that backwards either way is a real bug:
recording a date would let two servers disagree about the same calendar day, and
computing an event would let content vanish from a house it had already changed.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import content as content_module
import content_loader
import database
import resolve
from content import Content, Drop, Room, TextRow, Thing
from test_loader import a_thing, contents


TODAY = date(2026, 10, 15)
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)


def a_drop(drop_id, trigger="date", value=None, event=None):
    return Drop(
        drop_id=drop_id,
        trigger=trigger,
        date=value,
        event=event,
        name=f"Drop {drop_id}",
        notes=None,
    )


def a_calendar(*drops, things=(), room_text=(), thing_text=()):
    """Content with a handmade drop calendar."""
    parsed = Content()
    parsed.rooms = [Room(room_id="EN", name="Entryway", sort_order=1, open_at_launch=True)]
    parsed.room_text = list(room_text) or [
        TextRow(entity_id="EN", state="default", since_drop=1, text={"look": "The hall."})
    ]
    parsed.things = list(things)
    parsed.thing_text = list(thing_text) or [
        TextRow(entity_id=t.thing_id, state="default", since_drop=1, text={"look": "A thing."})
        for t in things
    ]
    parsed.defaults = dict(content_module.load_files().defaults)
    parsed.drops = list(drops)
    return parsed


@pytest.fixture
async def guild(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(BOB, GUILD_B)
    return db


# --------------------------------------------------------------------------
# Arrival
# --------------------------------------------------------------------------


async def test_launch_has_always_arrived(guild):
    await content_loader.load_content(a_calendar(a_drop(1, value="launch")))
    assert await resolve.arrived_drop_ids(GUILD_A, today=TODAY) == {1}


async def test_a_past_date_has_arrived(guild):
    await content_loader.load_content(a_calendar(a_drop(1, value=str(YESTERDAY))))
    assert await resolve.arrived_drop_ids(GUILD_A, today=TODAY) == {1}


async def test_todays_date_has_arrived(guild):
    """At or before today, so a drop lands on its own date rather than the next."""
    await content_loader.load_content(a_calendar(a_drop(1, value=str(TODAY))))
    assert await resolve.arrived_drop_ids(GUILD_A, today=TODAY) == {1}


async def test_a_future_date_has_not_arrived(guild):
    await content_loader.load_content(a_calendar(a_drop(1, value=str(TOMORROW))))
    assert await resolve.arrived_drop_ids(GUILD_A, today=TODAY) == set()


async def test_a_dated_drop_arrives_on_every_server_at_once(guild):
    """Computed, not recorded, so there is nothing to get out of step."""
    await content_loader.load_content(a_calendar(a_drop(1, value=str(YESTERDAY))))

    assert await resolve.arrived_drop_ids(GUILD_A, today=TODAY) == {1}
    assert await resolve.arrived_drop_ids(GUILD_B, today=TODAY) == {1}


async def test_a_dated_drop_needs_no_row(guild):
    await content_loader.load_content(a_calendar(a_drop(1, value=str(YESTERDAY))))
    await resolve.arrived_drop_ids(GUILD_A, today=TODAY)

    async with guild._require_session()() as session:
        rows = (await session.execute(select(database.ServerDrop))).all()
    assert rows == []


async def test_an_unreadable_date_is_treated_as_not_yet_arrived(guild):
    """Early content is worse than late content, and the loader rejects the file
    anyway - this is the belt to that braces."""
    await content_loader.load_content(a_calendar(a_drop(1, value="soon-ish")))
    assert await resolve.arrived_drop_ids(GUILD_A, today=TODAY) == set()


async def test_an_event_drop_waits_until_it_is_recorded(guild):
    await content_loader.load_content(a_calendar(a_drop(1, trigger="event", event="whatever")))
    assert await resolve.arrived_drop_ids(GUILD_A, today=TODAY) == set()

    await resolve.record_arrival(GUILD_A, 1)
    assert await resolve.arrived_drop_ids(GUILD_A, today=TODAY) == {1}


async def test_a_manual_drop_waits_for_an_admin(guild):
    await content_loader.load_content(a_calendar(a_drop(1, trigger="manual")))
    assert await resolve.arrived_drop_ids(GUILD_A, today=TODAY) == set()

    await resolve.record_arrival(GUILD_A, 1)
    assert await resolve.arrived_drop_ids(GUILD_A, today=TODAY) == {1}


async def test_an_event_arrival_is_per_server(guild):
    await content_loader.load_content(a_calendar(a_drop(1, trigger="event", event="whatever")))
    await resolve.record_arrival(GUILD_A, 1)

    assert await resolve.arrived_drop_ids(GUILD_B, today=TODAY) == set()


async def test_recording_the_same_arrival_twice_is_harmless(guild):
    await content_loader.load_content(a_calendar(a_drop(1, trigger="manual")))

    assert await resolve.record_arrival(GUILD_A, 1) is True
    assert await resolve.record_arrival(GUILD_A, 1) is False


async def test_firing_a_drop_that_does_not_exist_is_refused(guild):
    await content_loader.load_content(a_calendar(a_drop(1, value="launch")))
    with pytest.raises(resolve.UnknownDrop):
        await resolve.record_arrival(GUILD_A, 99)


async def test_an_arrival_is_permanent(guild):
    """The whole reason arrivals are stored: a condition can stop being true, and
    content must not vanish from a house it has already changed."""
    await content_loader.load_content(a_calendar(a_drop(1, trigger="event", event="whatever")))
    await resolve.record_arrival(GUILD_A, 1)

    # Whatever caused it is now false again; the drop stays arrived regardless.
    assert await resolve.arrived_drop_ids(GUILD_A, today=TODAY) == {1}
    assert await resolve.arrived_drop_ids(GUILD_A, today=TODAY + timedelta(days=365)) == {1}


async def test_drops_can_arrive_out_of_order(guild):
    """An event drop can land while a lower-numbered dated one has not, which is
    why 'highest arrived' is not the same as 'highest'."""
    await content_loader.load_content(
        a_calendar(
            a_drop(1, value="launch"),
            a_drop(2, value=str(TOMORROW)),
            a_drop(3, trigger="manual"),
        )
    )
    await resolve.record_arrival(GUILD_A, 3)

    assert await resolve.arrived_drop_ids(GUILD_A, today=TODAY) == {1, 3}


# --------------------------------------------------------------------------
# Text resolution
# --------------------------------------------------------------------------


async def test_a_later_drop_supersedes_an_earlier_one(guild):
    parsed = a_calendar(
        a_drop(1, value="launch"),
        a_drop(2, value=str(YESTERDAY)),
        room_text=[
            TextRow(entity_id="EN", state="default", since_drop=1, text={"look": "Before."}),
            TextRow(entity_id="EN", state="default", since_drop=2, text={"look": "After."}),
        ],
    )
    await content_loader.load_content(parsed)

    assert await resolve.room_look(GUILD_A, "EN", today=TODAY) == "After."


async def test_an_unarrived_row_is_invisible(guild):
    """In the files, loaded, and simply not yet reachable."""
    parsed = a_calendar(
        a_drop(1, value="launch"),
        a_drop(2, value=str(TOMORROW)),
        room_text=[
            TextRow(entity_id="EN", state="default", since_drop=1, text={"look": "Before."}),
            TextRow(entity_id="EN", state="default", since_drop=2, text={"look": "After."}),
        ],
    )
    await content_loader.load_content(parsed)

    assert await resolve.room_look(GUILD_A, "EN", today=TODAY) == "Before."
    # ...and the same database answers differently once the day comes.
    assert await resolve.room_look(GUILD_A, "EN", today=TOMORROW) == "After."


async def test_the_highest_arrived_wins_not_the_highest(guild):
    parsed = a_calendar(
        a_drop(1, value="launch"),
        a_drop(2, value=str(TOMORROW)),
        a_drop(3, trigger="manual"),
        room_text=[
            TextRow(entity_id="EN", state="default", since_drop=1, text={"look": "One."}),
            TextRow(entity_id="EN", state="default", since_drop=2, text={"look": "Two."}),
            TextRow(entity_id="EN", state="default", since_drop=3, text={"look": "Three."}),
        ],
    )
    await content_loader.load_content(parsed)
    await resolve.record_arrival(GUILD_A, 3)

    assert await resolve.room_look(GUILD_A, "EN", today=TODAY) == "Three."


async def test_two_servers_can_see_different_text(guild):
    """One has fired the manual drop; the other has not."""
    parsed = a_calendar(
        a_drop(1, value="launch"),
        a_drop(2, trigger="manual"),
        room_text=[
            TextRow(entity_id="EN", state="default", since_drop=1, text={"look": "Before."}),
            TextRow(entity_id="EN", state="default", since_drop=2, text={"look": "After."}),
        ],
    )
    await content_loader.load_content(parsed)
    await resolve.record_arrival(GUILD_A, 2)

    assert await resolve.room_look(GUILD_A, "EN", today=TODAY) == "After."
    assert await resolve.room_look(GUILD_B, "EN", today=TODAY) == "Before."


async def test_state_is_matched_before_drop(guild):
    parsed = a_calendar(
        a_drop(1, value="launch"),
        room_text=[
            TextRow(entity_id="EN", state="default", since_drop=1, text={"look": "Ruined."}),
            TextRow(
                entity_id="EN", state="stairs_repaired", since_drop=1, text={"look": "Mended."}
            ),
        ],
    )
    await content_loader.load_content(parsed)

    assert await resolve.room_look(GUILD_A, "EN", "stairs_repaired", today=TODAY) == "Mended."
    assert await resolve.room_look(GUILD_A, "EN", today=TODAY) == "Ruined."


async def test_an_unwritten_state_falls_back_to_default(guild):
    await content_loader.load_content(a_calendar(a_drop(1, value="launch")))
    assert await resolve.room_look(GUILD_A, "EN", "drawer_unjammed", today=TODAY) == "The hall."


async def test_a_state_resolves_within_its_own_drops(guild):
    """A state row from an unarrived drop does not win either."""
    parsed = a_calendar(
        a_drop(1, value="launch"),
        a_drop(2, value=str(TOMORROW)),
        room_text=[
            TextRow(entity_id="EN", state="default", since_drop=1, text={"look": "Plain."}),
            TextRow(entity_id="EN", state="lit", since_drop=1, text={"look": "Lit."}),
            TextRow(entity_id="EN", state="lit", since_drop=2, text={"look": "Lit, later."}),
        ],
    )
    await content_loader.load_content(parsed)

    assert await resolve.room_look(GUILD_A, "EN", "lit", today=TODAY) == "Lit."


async def test_thing_text_resolves_per_column(guild):
    parsed = a_calendar(
        a_drop(1, value="launch"),
        things=[a_thing("spoon")],
        thing_text=[
            TextRow(
                entity_id="spoon",
                state="default",
                since_drop=1,
                text={"look": "A spoon.", "use": "You stir nothing."},
            )
        ],
    )
    await content_loader.load_content(parsed)

    assert await resolve.thing_text(GUILD_A, "spoon", "look", today=TODAY) == "A spoon."
    assert await resolve.thing_text(GUILD_A, "spoon", "use", today=TODAY) == "You stir nothing."


async def test_a_blank_cell_resolves_to_nothing_so_a_default_can_apply(guild):
    parsed = a_calendar(
        a_drop(1, value="launch"),
        things=[a_thing("spoon")],
        thing_text=[
            TextRow(entity_id="spoon", state="default", since_drop=1, text={"look": "A spoon."})
        ],
    )
    await content_loader.load_content(parsed)

    assert await resolve.thing_text(GUILD_A, "spoon", "take", today=TODAY) is None
    fallback = await resolve.default_text("take.default")
    assert fallback and "{name}" in fallback


async def test_asking_for_a_column_that_does_not_exist_is_refused(guild):
    await content_loader.load_content(a_calendar(a_drop(1, value="launch")))
    with pytest.raises(ValueError):
        await resolve.thing_text(GUILD_A, "spoon", "smell", today=TODAY)


async def test_an_unknown_entity_resolves_to_nothing(guild):
    await content_loader.load_content(a_calendar(a_drop(1, value="launch")))
    assert await resolve.room_look(GUILD_A, "NOWHERE", today=TODAY) is None


# --------------------------------------------------------------------------
# Placement waits for the drop too
# --------------------------------------------------------------------------


async def test_a_thing_from_a_future_drop_is_not_placed(guild):
    parsed = a_calendar(
        a_drop(1, value="launch"),
        a_drop(2, value=str(TOMORROW)),
        things=[a_thing("spoon"), a_thing("lantern", since_drop=2)],
    )
    report = await content_loader.load_content(parsed)

    assert report.waiting_on_drops == 2  # one per server
    assert {row[2] for row in await contents(guild, GUILD_A)} == {"spoon"}


async def test_it_lands_by_itself_once_the_drop_comes_due(guild, monkeypatch):
    """No migration and no deploy: the next boot after the date places it."""
    parsed = a_calendar(
        a_drop(1, value="launch"),
        a_drop(2, value=str(TOMORROW)),
        things=[a_thing("spoon"), a_thing("lantern", since_drop=2)],
    )
    await content_loader.load_content(parsed)

    monkeypatch.setattr(database, "pacific_today", lambda: TOMORROW)
    report = await content_loader.load_content(parsed)

    assert report.placed == 2
    assert {row[2] for row in await contents(guild, GUILD_A)} == {"spoon", "lantern"}


async def test_a_manual_drop_places_only_where_it_was_fired(guild):
    parsed = a_calendar(
        a_drop(1, value="launch"),
        a_drop(2, trigger="manual"),
        things=[a_thing("spoon"), a_thing("lantern", since_drop=2)],
    )
    await content_loader.load_content(parsed)
    await resolve.record_arrival(GUILD_A, 2)
    await content_loader.load_content(parsed)

    assert {row[2] for row in await contents(guild, GUILD_A)} == {"spoon", "lantern"}
    assert {row[2] for row in await contents(guild, GUILD_B)} == {"spoon"}


async def test_visible_thing_ids_gates_on_arrival(guild):
    parsed = a_calendar(
        a_drop(1, value="launch"),
        a_drop(2, value=str(TOMORROW)),
        things=[a_thing("spoon"), a_thing("lantern", since_drop=2)],
    )
    await content_loader.load_content(parsed)

    assert await resolve.visible_thing_ids(GUILD_A, today=TODAY) == {"spoon"}
    assert await resolve.visible_thing_ids(GUILD_A, today=TOMORROW) == {"spoon", "lantern"}


# --------------------------------------------------------------------------
# The content we ship
# --------------------------------------------------------------------------


async def test_the_shipped_calendar_has_arrived(guild):
    """One row, `launch`, so every server sees everything from the first boot."""
    parsed = content_module.load_files()
    await content_loader.load_content(parsed)

    assert await resolve.arrived_drop_ids(GUILD_A) == {1}
    assert len(await resolve.visible_thing_ids(GUILD_A)) == len(parsed.things)


async def test_the_shipped_content_resolves_a_room(guild):
    parsed = content_module.load_files()
    await content_loader.load_content(parsed)

    look = await resolve.room_look(GUILD_A, "EN")
    assert look and "foyer" in look.lower()


async def test_the_shipped_content_resolves_a_state_row(guild):
    """The Entryway has a stairs_repaired description as well as a default."""
    parsed = content_module.load_files()
    await content_loader.load_content(parsed)

    default = await resolve.room_look(GUILD_A, "EN")
    repaired = await resolve.room_look(GUILD_A, "EN", "stairs_repaired")
    assert repaired and repaired != default
