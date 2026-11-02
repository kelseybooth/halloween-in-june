"""The one-time recovery of the two trails from the interaction log.

Driven through synthetic log rows rather than through the commands, which
is the opposite of `test_interaction_log`'s choice and for the opposite
reason: that file is about whether the call sites write, and this one is
about reading rows that were written months ago by code that may since
have changed. A test that produced its fixtures by playing the game could
only ever prove the script can read today's writer.

**What the script is sure of and what it is not** is the shape of almost
every test here. A climb's room is in its log row; a drop's is not, and is
recovered by replaying the moves. Both halves are asserted, and so is the
gap the second one leaves.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import backfill_room_deeds as backfill
import database
import telemetry
import world


NOON = datetime(2026, 11, 1, 12, 0, 0)


async def logged(
    db,
    action,
    *,
    thing_id=None,
    detail=None,
    at=NOON,
    who=ALICE,
    guild_id=GUILD_A,
    outcome=telemetry.SUCCESS,
):
    """One row straight into the log, the way the past left it there."""
    async with db._require_session()() as session:
        session.add(
            database.InteractionLog(
                guild_id=guild_id,
                user_id=who,
                actor=database.PLAYER,
                action=action,
                thing_id=thing_id,
                outcome=outcome,
                detail=detail,
                created_at=at,
            )
        )
        await session.commit()


async def climbed(db, room_id, *, cat="no", at=NOON, who=ALICE, guild_id=GUILD_A):
    await logged(
        db,
        telemetry.USE,
        thing_id=world.LADDER,
        detail=f"room={room_id} carried=no cat={cat} nest=no",
        at=at,
        who=who,
        guild_id=guild_id,
    )


async def moved(db, to, *, at=NOON, who=ALICE, guild_id=GUILD_A):
    await logged(
        db,
        telemetry.MOVE,
        thing_id="ED",
        detail=f"from=EN to={to}",
        at=at,
        who=who,
        guild_id=guild_id,
    )


async def dropped(db, thing_id, *, at=NOON, who=ALICE, guild_id=GUILD_A, **kw):
    await logged(
        db, telemetry.DROP, thing_id=thing_id, at=at, who=who, guild_id=guild_id, **kw
    )


async def deeds_of(action, thing_id, *, who=ALICE, guild_id=GUILD_A) -> set[str]:
    return await database.rooms_where(who, guild_id, action, thing_id)


# --------------------------------------------------------------------------
# Climbs, which the log recorded
# --------------------------------------------------------------------------


async def test_a_climb_is_recovered_from_its_own_row(db):
    """The room is in `detail` because the ladder wanted four facts in its
    log row, which is the whole reason this half is a read and not a
    guess."""
    await climbed(db, "CO")

    await backfill.apply(await backfill.plan())

    assert await deeds_of(telemetry.USE, world.LADDER) == {"CO"}


async def test_a_climb_the_cat_took_is_not_recovered(db):
    """`cat=yes` is in the same string, so the one rule the design states
    about climbs survives the recovery - a backfill that counted her
    climbs would hand out progress the live path refuses."""
    await climbed(db, "CO", cat="yes")

    found = await backfill.plan()
    await backfill.apply(found)

    assert await deeds_of(telemetry.USE, world.LADDER) == set()
    assert found.cat_climbs == 1


async def test_a_climb_with_no_room_in_it_is_skipped(db):
    """There may be none of these, and the cost of being wrong about that
    is a crash in the middle of a one-time write."""
    await logged(db, telemetry.USE, thing_id=world.LADDER, detail=None)

    await backfill.apply(await backfill.plan())

    assert await deeds_of(telemetry.USE, world.LADDER) == set()


async def test_the_earliest_climb_in_a_room_is_the_one_remembered(db):
    """One deed per room however many climbs, and `first_at` is the
    first - which is what the column means on the live path too."""
    await climbed(db, "CO", at=NOON)
    await climbed(db, "CO", at=NOON + timedelta(days=3))

    await backfill.apply(await backfill.plan())

    async with database._require_session()() as session:
        rows = (
            await session.execute(
                select(database.RoomDeed.first_at).where(
                    database.RoomDeed.thing_id == world.LADDER
                )
            )
        ).all()

    assert [row[0] for row in rows] == [NOON]


# --------------------------------------------------------------------------
# Drops, which it did not
# --------------------------------------------------------------------------


async def test_a_drop_is_placed_by_the_move_before_it(db):
    """A drop row carries the container or nothing, never the room. The
    move rows carry `to=`, so where somebody was standing is where they
    last went."""
    await moved(db, "KI", at=NOON)
    await dropped(db, "frozen_burrito", at=NOON + timedelta(minutes=1))

    await backfill.apply(await backfill.plan())

    assert await deeds_of(telemetry.DROP, "frozen_burrito") == {"KI"}


async def test_a_later_move_does_not_place_an_earlier_drop(db):
    """**The whole reason moves and drops are replayed on one timeline.**
    Reading each player's latest move would place every drop they ever
    made in the last room they walked into."""
    await moved(db, "KI", at=NOON)
    await dropped(db, "frozen_burrito", at=NOON + timedelta(minutes=1))
    await moved(db, "CO", at=NOON + timedelta(minutes=2))

    await backfill.apply(await backfill.plan())

    assert await deeds_of(telemetry.DROP, "frozen_burrito") == {"KI"}


async def test_a_drop_before_the_first_move_is_placed_by_its_from(db):
    """**Half the live drops are this case**, most of them in the channel,
    where a game starts and plenty of players stay. A move says
    `from=CH to=EN`, so where somebody stood before their first move is
    recorded as surely as where they went - and a drop with nothing before
    it would otherwise have been thrown away."""
    await dropped(db, "frozen_burrito", at=NOON)
    await moved(db, "KI", at=NOON + timedelta(minutes=1))

    found = await backfill.plan()
    await backfill.apply(found)

    assert await deeds_of(telemetry.DROP, "frozen_burrito") == {"EN"}
    assert found.drops_without_a_room == 0


async def test_but_a_player_never_seen_moving_cannot_be_placed(db):
    """Reported rather than guessed. The room could be inferred from where
    a game begins, and a guess in a table of facts is worse than a gap -
    this one would hand somebody a room of the trail they never walked."""
    await dropped(db, "frozen_burrito", at=NOON)

    found = await backfill.plan()
    await backfill.apply(found)

    assert await deeds_of(telemetry.DROP, "frozen_burrito") == set()
    assert found.drops_without_a_room == 1


async def test_one_player_s_moves_do_not_place_another_s_drops(db):
    """Two testers in the same server, which is the ordinary case and the
    one a map keyed on the player alone would get wrong."""
    await moved(db, "KI", at=NOON, who=ALICE)
    await moved(db, "CO", at=NOON + timedelta(minutes=1), who=BOB)
    await dropped(db, "frozen_burrito", at=NOON + timedelta(minutes=2), who=ALICE)

    await backfill.apply(await backfill.plan())

    assert await deeds_of(telemetry.DROP, "frozen_burrito", who=ALICE) == {"KI"}
    assert await deeds_of(telemetry.DROP, "frozen_burrito", who=BOB) == set()


async def test_nor_do_another_server_s(db):
    """The same player in two servers is one person with two games."""
    await moved(db, "KI", at=NOON, guild_id=GUILD_A)
    await dropped(
        db, "frozen_burrito", at=NOON + timedelta(minutes=1), guild_id=GUILD_B
    )

    found = await backfill.plan()
    await backfill.apply(found)

    assert await deeds_of(telemetry.DROP, "frozen_burrito", guild_id=GUILD_B) == set()
    assert found.drops_without_a_room == 1


async def test_a_refused_drop_is_not_a_drop(db):
    """Thirty-six of the live drop rows are refusals, and a refusal put
    nothing down. The filter is `outcome`, which the writer has set since
    before either trail existed."""
    await moved(db, "KI", at=NOON)
    await dropped(
        db,
        "frozen_burrito",
        at=NOON + timedelta(minutes=1),
        outcome=telemetry.REFUSED,
    )

    await backfill.apply(await backfill.plan())

    assert await deeds_of(telemetry.DROP, "frozen_burrito") == set()


async def test_a_refused_move_moves_nobody(db):
    """The other half of that filter, and the one that would be wrong
    quietly: a refused move would put the player in a room they were
    turned away from, and every drop after it in the wrong place."""
    await moved(db, "KI", at=NOON)
    async with db._require_session()() as session:
        session.add(
            database.InteractionLog(
                guild_id=GUILD_A,
                user_id=ALICE,
                actor=database.PLAYER,
                action=telemetry.MOVE,
                thing_id="KC",
                outcome=telemetry.REFUSED,
                detail="from=KI to=CO",
                created_at=NOON + timedelta(minutes=1),
            )
        )
        await session.commit()
    await dropped(db, "frozen_burrito", at=NOON + timedelta(minutes=2))

    await backfill.apply(await backfill.plan())

    assert await deeds_of(telemetry.DROP, "frozen_burrito") == {"KI"}


# --------------------------------------------------------------------------
# Running it
# --------------------------------------------------------------------------


async def test_planning_writes_nothing(db):
    """`--apply` is the whole safety of a one-time script against a live
    database, and it is only worth anything if the default really is a
    read."""
    await climbed(db, "CO")

    found = await backfill.plan()

    assert found.deeds
    assert await deeds_of(telemetry.USE, world.LADDER) == set()


async def test_running_it_twice_writes_nothing_the_second_time(db):
    """What makes it safe to run again after a failure halfway."""
    await climbed(db, "CO")
    await moved(db, "KI", at=NOON)
    await dropped(db, "frozen_burrito", at=NOON + timedelta(minutes=1))

    first = await backfill.apply(await backfill.plan())
    second = await backfill.apply(await backfill.plan())

    assert first == 2
    assert second == 0


async def test_the_report_says_what_it_could_not_place(db):
    """The two uncertain numbers are in the report rather than in a log
    line, because the person running this decides from them whether the
    inferred half is worth having at all."""
    await climbed(db, "CO", cat="yes")
    await dropped(db, "frozen_burrito", at=NOON)

    found = await backfill.plan()
    text = backfill.report(found)

    assert "1 climbs the cat took" in text
    assert "1 drops with no move before them" in text
    assert "Nothing written" in text


async def test_every_drop_is_recovered_and_not_only_the_burrito(db):
    """The table is written for every drop on the live path, so a backfill
    that filled it for one thing would leave a table that is complete for
    the burrito and silently partial for everything else - which is the
    trap the next trail achievement would fall into."""
    await moved(db, "KI", at=NOON)
    await dropped(db, "spice_jar", at=NOON + timedelta(minutes=1))

    await backfill.apply(await backfill.plan())

    assert await deeds_of(telemetry.DROP, "spice_jar") == {"KI"}
