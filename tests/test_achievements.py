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
    assert len(parsed.achievements) == 35
    assert len(parsed.achievement_ids) == 35


def test_the_shipped_file_validates():
    assert content_module.validate(content_module.load_files()) == []


def test_every_kind_is_represented():
    """Three kinds, and `group` is the one that changes where an award lands."""
    kinds = {a.kind for a in content_module.load_files().achievements}
    assert kinds == content_module.ACHIEVEMENT_KINDS


def test_the_three_group_achievements_are_the_room_ones():
    """A group achievement has no earner, so which ones they are is a design
    fact worth pinning rather than a detail of the file."""
    parsed = content_module.load_files()
    assert {a.achievement_id for a in parsed.achievements if a.kind == "group"} == {
        "strength_in_numbers",
        "making_a_mess",
        "the_feline_collection",
    }


def test_no_name_or_unlock_is_blank():
    for row in content_module.load_files().achievements:
        assert row.name.strip(), row.achievement_id
        assert row.unlock.strip(), row.achievement_id


# --------------------------------------------------------------------------
# Validation: the four ways a writer can break it
# --------------------------------------------------------------------------


def a_file(*achievements) -> Content:
    parsed = Content()
    parsed.achievements = list(achievements)
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

    assert await row_count(db, "achievements") == 35


async def test_a_reload_replaces_the_rows(db):
    """Content, so the file wins and nothing merges."""
    parsed = a_world(a_thing("candle"))
    parsed.achievements = [an_achievement("gourd_job", name="Gourd Job")]
    await content_loader.load_content(parsed)

    parsed.achievements = [an_achievement("gourd_job", name="Squash Buckler")]
    await content_loader.load_content(parsed)

    rows = await resolve.achievements(GUILD_A, today=TODAY)
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
    parsed = a_calendar(a_drop(1, value="launch"), a_drop(2, value=str(TOMORROW)))
    parsed.achievements = [
        an_achievement("gourd_job"),
        an_achievement("say_cheese", since_drop=2),
    ]
    await content_loader.load_content(parsed)

    rows = await resolve.achievements(GUILD_A, today=TODAY)
    assert set(rows) == {"gourd_job"}


async def test_a_later_drop_supersedes_an_earlier_one(guild):
    parsed = a_calendar(a_drop(1, value="launch"), a_drop(2, value=str(YESTERDAY)))
    parsed.achievements = [
        an_achievement("gourd_job", name="Before"),
        an_achievement("gourd_job", since_drop=2, name="After"),
    ]
    await content_loader.load_content(parsed)

    rows = await resolve.achievements(GUILD_A, today=TODAY)
    assert rows["gourd_job"].name == "After"


async def test_a_rewrite_that_has_not_arrived_is_ignored(guild):
    parsed = a_calendar(a_drop(1, value="launch"), a_drop(2, value=str(TOMORROW)))
    parsed.achievements = [
        an_achievement("gourd_job", name="Before"),
        an_achievement("gourd_job", since_drop=2, name="After"),
    ]
    await content_loader.load_content(parsed)

    rows = await resolve.achievements(GUILD_A, today=TODAY)
    assert rows["gourd_job"].name == "Before"


async def test_highest_arrived_wins_not_highest(guild):
    """An event drop can arrive while a lower-numbered dated one has not, so
    the maximum is taken after arrival is filtered, never before."""
    parsed = a_calendar(
        a_drop(1, value="launch"),
        a_drop(2, value=str(TOMORROW)),
        a_drop(3, trigger="manual"),
    )
    parsed.achievements = [
        an_achievement("gourd_job", name="One"),
        an_achievement("gourd_job", since_drop=2, name="Two"),
        an_achievement("gourd_job", since_drop=3, name="Three"),
    ]
    await content_loader.load_content(parsed)
    await resolve.record_arrival(GUILD_A, 3)

    rows = await resolve.achievements(GUILD_A, today=TODAY)
    assert rows["gourd_job"].name == "Three"


async def test_resolution_carries_the_unlock_and_the_kind(guild):
    parsed = a_calendar(a_drop(1, value="launch"))
    parsed.achievements = [
        an_achievement("making_a_mess", kind="group", unlock="Amassed 200 things.")
    ]
    await content_loader.load_content(parsed)

    row = (await resolve.achievements(GUILD_A, today=TODAY))["making_a_mess"]
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
    await database.award_player_achievement(GUILD_A, ALICE, "say_cheese")

    assert set(await database.player_achievements_of(GUILD_A, ALICE)) == {
        "gourd_job",
        "say_cheese",
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
