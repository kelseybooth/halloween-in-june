"""The ninth content file: parsing it, loading it, and awarding from it.

Nothing here fires an achievement - the dispatcher and the thirty-five
predicates are the next step. This is the layer underneath: a writer can edit
the names without a deploy, a reload cannot cost anybody what they earned, and
an award announces exactly once however many times the condition is true.

The last of those is the one worth protecting. *Cat's Best Friend* stays true
forever once true, so an award that is not idempotent re-announces on every
`/pet` for the rest of October.
"""

from dataclasses import replace
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from conftest import ALICE, BOB, GUILD_A, GUILD_B

import content as content_module
import content_loader
import database
import resolve
from content import Achievement, Content, Drop, Room, TextRow

from test_drops import a_calendar, a_drop
from test_loader import a_thing, a_world


TODAY = date(2026, 10, 15)
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)


def an_achievement(achievement_id, **overrides):
    defaults = dict(
        achievement_id=achievement_id,
        kind="public",
        name=achievement_id.replace("_", " ").title(),
        unlock=f"You did {achievement_id}.",
        since_drop=1,
        sort_order=0,
        notes=None,
    )
    return Achievement(**{**defaults, **overrides})


@pytest.fixture
async def guild(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(BOB, GUILD_A)
    await db.ensure_user_exists(ALICE, GUILD_B)
    return db


async def row_count(db, table):
    async with db._require_session()() as session:
        return await session.scalar(
            select(func.count()).select_from(database.Base.metadata.tables[table])
        )


# --------------------------------------------------------------------------
# The file as the writers delivered it
# --------------------------------------------------------------------------


def test_the_shipped_file_parses():
    parsed = content_module.load_files()
    # Thirty-five from Release 1, nine added by V3, the two October
    # holidays the writers added on 21 October, *Room Service*, which is
    # what drop 10's quest ends in, and *Bug Catcher*, which is awarded
    # by hand and cannot be played for. Then drop 20's two: *Are You
    # David?* at a thousand points, and *Board Meeting*, which is parked
    # at 99 until drop 30 builds a group award that names its
    # contributors.
    # Two new ones with the ground floor: *Bin Looking for You*, for
    # walking into the Kitchen holding a dirty diaper, and *Hive Five*,
    # for the first climb that knocks a piece off the wasp nest.
    # Then *Clean Plate Club*, from playtesting on 30 October: the plates'
    # use text has the player taste the dried food, so the achievement is
    # the use and nothing more.
    # Fifty-five on 2 November: *Rung by Rung* and *Burrito Trail*,
    # the two drop 50 trails.
    # Then *Captive Audience*, the same day: a rattle played with other
    # people awake in the room. It is one of the two the rattle work
    # order asked for.
    # Fifty-seven with the other one. *Accompanist* was waiting for drop
    # 40 and drop 40 arrived the same day, when the ceiling moved so beta
    # could reach the upstairs - the music box is in the Nursery, so the
    # release that made the room reachable is the one that made the
    # achievement earnable.
    # Fifty-eight on 5 November: *Growth Spurt*, for trying on all three
    # pieces of baby clothing the house has. A drop 40 row, and the only
    # new thing in it is the row - the booties, the sunhat and the
    # clothes were all usable already.
    # Sixty-three on 6 November, the ladder's other five in one work
    # order: *King of the Mountain* for a climb with an audience,
    # *Second Place* for losing three races to the cat, *Pass It On* for
    # a ladder somebody else picked up, *Heavy Lifting* for four rooms
    # without setting it down, and *Head for Heights* for twenty-five
    # climbs. The first batch since drop 20 that needed columns built
    # for it: three tallies on `users` and a row for the last set-down,
    # because neither `room_deeds` nor `thing_uses` can count a climb.
    # Sixty-four on 6 November, the cat collar: the first thing in the
    # game a player gives back rather than keeps. It is also the first
    # row whose thing is destroyed on purpose - `content.SPENT_FOR_GOOD`
    # exempts the collar from the rule that nothing may be consumed
    # unless something puts it back.
    # And sixty-six the same day, the ivy fall's two: *Stuck the Landing*
    # for a first fall off the ivy, and *Walk It Off* for a shaky state
    # that ran its half hour out without being eaten away. Neither needed
    # a column - the first reads the state the fall sets, which nothing
    # else sets, and the second reads the `player_states` row that expiry
    # leaves behind and food deletes. *Walk It Off* is the first award in
    # the file that cannot ask `states.has`, because by the time it is
    # true the state is out of force.
    # And seventy-one on 11 November, drop 50's *Boo Who?*, for the ghost
    # who haunted all day and was named by nobody. The other two ghost
    # rows moved from 99 to 50 the same day and are not in this number,
    # because they were already in the file: the drop a row waits for is
    # not what this counts.
    assert len(parsed.achievements) == 71
    # The ids are a set, so this pair is also the file's duplicate check.
    assert len(parsed.achievement_ids) == 71


def test_the_shipped_file_validates():
    assert content_module.validate(content_module.load_files()) == []


def test_every_kind_is_represented():
    """Three kinds, and `group` is the one that changes where an award lands."""
    kinds = {a.kind for a in content_module.load_files().achievements}
    assert kinds == content_module.ACHIEVEMENT_KINDS


def test_the_group_achievements_are_the_room_ones_and_the_staircase():
    """A group achievement has no earner, so which ones they are is a design
    fact worth pinning rather than a detail of the file.

    *Board Meeting* was the fourth and the odd one out: the three room
    achievements go to the server and name nobody, which is what `group`
    meant until drop 30, while that one goes to the players who laid a
    plank. Drop 30 built the award shape for it - a `group` row with
    recipients.

    **Drop 46's *Playgroup* is the second of those**, and the first to
    arrive wanting the shape rather than waiting for it. It is the same
    distinction: everybody who played a toy in the room that hour earns
    it, and somebody standing there who never played does not.
    """
    parsed = content_module.load_files()
    assert {a.achievement_id for a in parsed.achievements if a.kind == "group"} == {
        "strength_in_numbers",
        "making_a_mess",
        "the_feline_collection",
        "board_meeting",
        "playgroup",
    }


def test_public_means_offered_and_nothing_else_is_public():
    """Two kinds of goal, not three.

    `kind` is read nowhere in the code but the `group` branch, so
    `public` and `secret` differed only for a reader of the file:
    neither appears in `/stats` before it is earned, and both announce
    by name when it is. That let `public` mean two unrelated things -
    the four cat goals the game actually puts in front of a player,
    and fourteen it never mentions - and for the fourteen, secret is
    what the game was already doing.

    So the column now says what the game does. A row is `public`
    exactly when it is `offered`, which is the only thing that shows a
    goal before it is earned; every other goal is found or not found,
    which is `secret`.

    Pinned both ways, because the two failures are not the same
    mistake. A `public` row that is not offered is this file's old
    state - a goal the writers meant to signpost and the game never
    mentions. An `offered` row that is not public would be a secret
    printed in `/stats` as an open quest, which gives away the one
    thing `secret` is for. Neither raises at runtime.
    """
    parsed = content_module.load_files()
    public = {a.achievement_id for a in parsed.achievements if a.kind == 'public'}
    offered = {a.achievement_id for a in parsed.achievements if a.offered}
    # Both empty would pass the equality and prove nothing.
    assert offered, 'no achievement is offered, so this proves nothing'
    assert public == offered


def test_no_name_or_unlock_is_blank():
    for row in content_module.load_files().achievements:
        assert row.name.strip(), row.achievement_id
        assert row.unlock.strip(), row.achievement_id


# --------------------------------------------------------------------------
# Validation: the four ways a writer can break it
# --------------------------------------------------------------------------


def a_file(*achievements) -> Content:
    """A content set with nothing in it but these achievements.

    It carries a calendar as well, because a row has to point at a drop
    that exists - an achievement waiting on a drop nobody wrote is
    unreachable rather than late, and the loader refuses it. Three drops
    covers every `since_drop` these tests use.
    """
    parsed = Content()
    parsed.achievements = list(achievements)
    parsed.drops = [
        content_module.Drop(
            drop_id=n, trigger="manual", date=None, event=None,
            name=f"Drop {n}", notes=None,
        )
        for n in (1, 2, 3)
    ]
    return parsed


def test_the_same_id_twice_at_one_drop_is_caught():
    """Which name won would depend on row order, which is no way to decide."""
    problems = content_module.validate(
        a_file(an_achievement("gourd_job"), an_achievement("gourd_job"))
    )
    assert any("appears twice at drop 1" in p for p in problems)


def test_the_same_id_at_two_drops_is_fine():
    """Not a duplicate - a rewrite. It is how a name changes without a deploy."""
    problems = content_module.validate(
        a_file(
            an_achievement("gourd_job", name="Gourd Job"),
            an_achievement("gourd_job", since_drop=2, name="A Better Name"),
        )
    )
    assert problems == []


@pytest.mark.parametrize("kind", ["Public", "player", "", "bonus"])
def test_a_kind_outside_the_three_is_caught(kind):
    """`bonus` is the tempting one: the Story Bible calls two achievements
    bonus achievements, but that is a fact about the fiction and not a kind."""
    problems = content_module.validate(a_file(an_achievement("x", kind=kind)))
    assert any("is not one of" in p for p in problems)


@pytest.mark.parametrize("column", ["name", "unlock"])
def test_a_blank_name_or_unlock_is_caught(column):
    """Every other text column falls back to defaults.tsv. These two have
    nowhere to fall back to, so a blank is an error rather than a default."""
    problems = content_module.validate(a_file(an_achievement("x", **{column: ""})))
    assert any(f"has no {'name' if column == 'name' else 'unlock text'}" in p for p in problems)


def test_a_file_with_no_achievements_at_all_is_not_an_error():
    """The other eight files loaded for weeks without this one."""
    assert content_module.validate(a_file()) == []


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


async def test_the_rows_reach_the_database(db):
    parsed = a_world(a_thing("candle"))
    parsed.achievements = [an_achievement("gourd_job"), an_achievement("out_on_a_limb")]
    await content_loader.load_content(parsed)

    assert await row_count(db, "achievements") == 2


async def test_the_whole_shipped_file_loads(db):
    await content_loader.load_content(content_module.load_files())

    assert await row_count(db, "achievements") == 71


async def test_a_reload_replaces_the_rows(db):
    """Content, so the file wins and nothing merges."""
    parsed = a_world(a_thing("candle"))
    parsed.achievements = [an_achievement("gourd_job", name="Gourd Job")]
    await content_loader.load_content(parsed)

    parsed.achievements = [an_achievement("gourd_job", name="Squash Buckler")]
    await content_loader.load_content(parsed)

    rows = await resolve.achievements(GUILD_A)
    assert await row_count(db, "achievements") == 1
    assert rows["gourd_job"].name == "Squash Buckler"


async def test_a_reload_does_not_cost_anybody_what_they_earned(guild):
    """The rule that matters most here. Achievements are world state; the file
    is content. Reloading the file mid-October must not clear the game."""
    parsed = a_world(a_thing("candle"))
    parsed.achievements = [an_achievement("gourd_job")]
    await content_loader.load_content(parsed)
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")
    await database.award_server_achievement(GUILD_A, "gourd_job")

    await content_loader.load_content(parsed)

    assert await database.player_achievements_of(GUILD_A, ALICE)
    assert await database.server_achievements_of(GUILD_A)


async def test_a_fresh_load_does_clear_them(guild):
    """`--fresh` is the testing and migration path and resets everything."""
    parsed = a_world(a_thing("candle"))
    parsed.achievements = [an_achievement("gourd_job")]
    await content_loader.load_content(parsed)
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")
    await database.award_server_achievement(GUILD_A, "gourd_job")

    await content_loader.load_content(parsed, fresh=True)

    assert await database.player_achievements_of(GUILD_A, ALICE) == {}
    assert await database.server_achievements_of(GUILD_A) == {}


# --------------------------------------------------------------------------
# Drop resolution
#
# The same rule as every other content row, which is the point: achievements
# are not a special case. `since_drop` is not the date gate - six achievements
# fire only on a given day, and those dates live in the trigger functions.
# --------------------------------------------------------------------------


async def test_an_unarrived_drop_does_not_exist_yet(guild):
    parsed = a_calendar(a_drop(1), a_drop(2))
    parsed.achievements = [
        an_achievement("gourd_job"),
        an_achievement("self_reflection", since_drop=2),
    ]
    await content_loader.load_content(parsed)
    await resolve.set_current_drop(GUILD_A, 1)

    rows = await resolve.achievements(GUILD_A)
    assert set(rows) == {"gourd_job"}


async def test_a_later_drop_supersedes_an_earlier_one(guild):
    parsed = a_calendar(a_drop(1), a_drop(2))
    parsed.achievements = [
        an_achievement("gourd_job", name="Before"),
        an_achievement("gourd_job", since_drop=2, name="After"),
    ]
    await content_loader.load_content(parsed)
    await resolve.set_current_drop(GUILD_A, 2)

    rows = await resolve.achievements(GUILD_A)
    assert rows["gourd_job"].name == "After"


async def test_a_rewrite_that_has_not_arrived_is_ignored(guild):
    parsed = a_calendar(a_drop(1), a_drop(2))
    parsed.achievements = [
        an_achievement("gourd_job", name="Before"),
        an_achievement("gourd_job", since_drop=2, name="After"),
    ]
    await content_loader.load_content(parsed)
    await resolve.set_current_drop(GUILD_A, 1)

    rows = await resolve.achievements(GUILD_A)
    assert rows["gourd_job"].name == "Before"


async def test_the_highest_at_or_below_the_pointer_wins(guild):
    """This used to be `test_highest_arrived_wins_not_highest`, and it
    tested something that can no longer happen: under the calendar an
    event drop could arrive while a lower-numbered dated one had not, so
    the set of arrived drops had holes in it and the maximum had to be
    taken after filtering. The pointer cannot have holes. What is left
    worth asserting is that a rewrite two drops back still loses to one
    drop back."""
    parsed = a_calendar(a_drop(1), a_drop(2), a_drop(3))
    parsed.achievements = [
        an_achievement("gourd_job", name="One"),
        an_achievement("gourd_job", since_drop=2, name="Two"),
        an_achievement("gourd_job", since_drop=3, name="Three"),
    ]
    await content_loader.load_content(parsed)
    await resolve.set_current_drop(GUILD_A, 2)

    rows = await resolve.achievements(GUILD_A)
    assert rows["gourd_job"].name == "Two"


async def test_resolution_carries_the_unlock_and_the_kind(guild):
    parsed = a_calendar(a_drop(1, value="launch"))
    parsed.achievements = [
        an_achievement("making_a_mess", kind="group", unlock="Amassed 200 things.")
    ]
    await content_loader.load_content(parsed)

    row = (await resolve.achievements(GUILD_A))["making_a_mess"]
    assert (row.kind, row.unlock) == ("group", "Amassed 200 things.")


# --------------------------------------------------------------------------
# Awarding
# --------------------------------------------------------------------------


async def test_the_first_award_says_it_was_first(guild):
    assert await database.award_player_achievement(GUILD_A, ALICE, "gourd_job") is True


async def test_the_second_award_says_it_was_not(guild):
    """What the announcement hangs on. Without it, a standing condition
    re-announces every time it is checked."""
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")

    assert await database.award_player_achievement(GUILD_A, ALICE, "gourd_job") is False


async def test_re_awarding_does_not_move_the_earned_at(guild):
    """`/stats` shows when it was earned, and earning it is a moment that
    happened once."""
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")
    first = (await database.player_achievements_of(GUILD_A, ALICE))["gourd_job"]

    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")
    assert (await database.player_achievements_of(GUILD_A, ALICE))["gourd_job"] == first


async def test_a_server_award_is_idempotent_the_same_way(guild):
    assert await database.award_server_achievement(GUILD_A, "making_a_mess") is True
    assert await database.award_server_achievement(GUILD_A, "making_a_mess") is False


async def test_two_players_can_each_earn_the_same_one(guild):
    assert await database.award_player_achievement(GUILD_A, ALICE, "gourd_job") is True
    assert await database.award_player_achievement(GUILD_A, BOB, "gourd_job") is True


async def test_one_player_can_earn_several(guild):
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")
    await database.award_player_achievement(GUILD_A, ALICE, "self_reflection")

    assert set(await database.player_achievements_of(GUILD_A, ALICE)) == {
        "gourd_job",
        "self_reflection",
    }


async def test_a_player_award_is_scoped_to_one_server(guild):
    await database.award_player_achievement(GUILD_A, ALICE, "gourd_job")

    assert await database.player_achievements_of(GUILD_B, ALICE) == {}
    assert await database.award_player_achievement(GUILD_B, ALICE, "gourd_job") is True


async def test_a_server_award_is_scoped_to_one_server(guild):
    await database.award_server_achievement(GUILD_A, "making_a_mess")

    assert await database.server_achievements_of(GUILD_B) == {}


async def test_a_group_award_names_nobody(guild):
    """There is no user column, which is the design rather than an omission:
    crediting whoever dropped the two hundredth thing rewards arriving last at
    something everyone built."""
    await database.award_server_achievement(GUILD_A, "making_a_mess")

    assert await database.player_achievements_of(GUILD_A, ALICE) == {}
    assert set(await database.server_achievements_of(GUILD_A)) == {"making_a_mess"}


async def test_nothing_earned_reads_as_nothing_rather_than_an_error(guild):
    """A player runs `/stats` on day one, and it has to be an invitation."""
    assert await database.player_achievements_of(GUILD_A, ALICE) == {}
    assert await database.server_achievements_of(GUILD_A) == {}
