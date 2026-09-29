"""Wiping one server's game, and the list of what that means.

The list is the interesting part. It used to be written down in
`reset_db.py`, and it fell eleven tables behind: players vanished and their
achievements, inventories, room contents and unjammed drawers all survived,
which is a worse state than not resetting at all.

It is read off the schema now. Phase 2b split content from world state on
exactly this line — content is global and carries no `guild_id`, world state
is per guild and always does, and `test_schema.py` asserts it table by table
in both directions. So "has a `guild_id`" *is* "belongs to one server", and
the question cannot fall behind the answer again.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A, GUILD_B
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import craving
import database
import resolve
import restocking
import states
from sqlalchemy import func, select

SERVER_NAME = "Halloween in June"


@pytest.fixture
async def two_games(db):
    """Two servers, both mid-game, so a reset can be caught reaching across."""
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, name=SERVER_NAME, channels=[halloween], members=[FakeMember(ALICE)]
    )
    for where in (GUILD_A, GUILD_B):
        await db.ensure_user_exists(ALICE, where)
    await content_loader.load_content(content_module.load_files())
    halloween.add_active(*[name for _, name in await resolve.all_rooms()])
    for where in (GUILD_A, GUILD_B):
        await play(db, where)
    return db, guild, halloween


async def play(db, guild_id):
    """Leave a mark in as many of this server's tables as possible."""
    await db.start_game(ALICE, guild_id, "EN", await resolve.rooms_open_at_launch())
    await db.increment_pet_count(ALICE, guild_id)
    await db.take_from_source(ALICE, guild_id, "herbs")
    await db.record_use(ALICE, guild_id, "herbs")
    await states.set_player_state(guild_id, ALICE, "library_found")
    await states.set_server_state(guild_id, "stairs_repaired")
    await db.award_player_achievement(guild_id, ALICE, "gourd_job")
    await db.award_server_achievement(guild_id, "making_a_mess")
    await db.set_setting(guild_id, "planks_required", 3)
    await db.record_art(guild_id, "eunoia_icon", "https://cdn.test/icon.png")
    await restocking.set_initialized_on(guild_id)
    await craving.credit(guild_id, ALICE, database.pacific_today())


async def rows(guild_id) -> dict[str, int]:
    out = {}
    async with database._require_session()() as session:
        for name in content_loader.world_tables():
            table = database.Base.metadata.tables[name]
            n = await session.scalar(
                select(func.count()).select_from(table).where(table.c.guild_id == guild_id)
            )
            if n:
                out[name] = n
    return out


async def reset(two_games, confirm=SERVER_NAME, keep_art=True):
    _, guild, halloween = two_games
    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    await bot.reset_haunted_house.callback(interaction, confirm, keep_art)
    return interaction


# --------------------------------------------------------------------------
# What counts as this server's progress
# --------------------------------------------------------------------------


def test_the_table_list_is_the_schema_not_a_list():
    """The bug this whole thing exists because of. Anything with a guild_id
    is one server's, and nothing else is."""
    guilded = {
        name
        for name, table in database.Base.metadata.tables.items()
        if "guild_id" in table.c
    }

    assert set(content_loader.world_tables()) == guilded


def test_no_content_table_is_ever_cleared():
    """Content is global, reloads on every boot, and has nothing to do with
    what a server has done."""
    cleared = set(content_loader.world_tables())

    for name in ("room_types", "thing_types", "room_text", "thing_text",
                 "defaults", "drops", "restocks", "emoji_groups",
                 "achievements", "art"):
        assert name not in cleared, name


def test_children_are_deleted_before_parents():
    """`player_game_state` carries a foreign key to `users`, so users last."""
    order = content_loader.world_tables()

    assert order.index("player_game_state") < order.index("users")


# --------------------------------------------------------------------------
# The confirmation
# --------------------------------------------------------------------------


async def test_the_wrong_word_changes_nothing(two_games):
    before = await rows(GUILD_A)

    interaction = await reset(two_games, confirm="yes")

    assert await rows(GUILD_A) == before
    assert SERVER_NAME in interaction.reply


async def test_the_confirmation_is_the_server_name(two_games):
    await reset(two_games)

    assert await rows(GUILD_A) != {}  # the art survives; see below
    assert "player_achievements" not in await rows(GUILD_A)


async def test_the_reply_is_private(two_games):
    interaction = await reset(two_games, confirm="no")

    assert interaction.was_private


# --------------------------------------------------------------------------
# What a reset does
# --------------------------------------------------------------------------


async def test_every_trace_of_the_game_is_gone(two_games):
    """Except what is deliberately kept: the uploaded art, and the stock put
    back in the rooms."""
    await reset(two_games)

    left = await rows(GUILD_A)
    assert set(left) <= {"server_art", "room_contents"}


@pytest.mark.parametrize(
    "table",
    ["player_achievements", "server_achievements", "player_states",
     "server_states", "thing_uses", "player_inventory", "server_config",
     "craving_tally", "player_game_state", "pet_events", "users"],
)
async def test_each_kind_of_progress_is_cleared(two_games, table):
    assert table in await rows(GUILD_A)

    await reset(two_games)

    assert table not in await rows(GUILD_A)


async def test_the_other_server_is_untouched(two_games):
    """Every delete is filtered on the guild, so a reset in one server
    cannot reach another the bot is also in."""
    before = await rows(GUILD_B)

    await reset(two_games)

    assert await rows(GUILD_B) == before


async def test_the_calendar_starts_again(two_games):
    """`initialized_on` goes with the rest, so the next `/enter` is day one -
    which is most of why this is useful for testing."""
    assert await restocking.initialized_on(GUILD_A) is not None

    await reset(two_games)

    assert await restocking.initialized_on(GUILD_A) is None


async def test_the_house_is_not_left_empty(two_games):
    """Clearing `room_contents` without re-placing would leave a house with
    nothing in any room."""
    await reset(two_games)

    placed = (await rows(GUILD_A)).get("room_contents", 0)
    assert placed > 0


async def test_the_content_is_still_loaded(two_games):
    await reset(two_games)

    assert len(await resolve.all_rooms()) == 9
    assert len(await resolve.achievements(GUILD_A)) == 35


async def test_the_art_is_kept_by_default(two_games):
    """A reset should not cost ten re-uploads."""
    await reset(two_games)

    assert await database.art_urls(GUILD_A)


async def test_the_art_can_be_cleared_too(two_games):
    await reset(two_games, keep_art=False)

    assert await database.art_urls(GUILD_A) == {}


async def test_a_player_can_enter_again_afterwards(two_games):
    """The whole point: the next run starts clean rather than half-wiped."""
    db, guild, halloween = two_games
    await reset(two_games)

    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    await bot.enter.callback(interaction)

    state = await db.get_game_state(ALICE, GUILD_A)
    assert state.current_room == "EN"
    assert await db.get_pet_count(ALICE, GUILD_A) == 0
    assert await db.player_achievements_of(GUILD_A, ALICE) == {}
    assert await states.has(GUILD_A, ALICE, "tutorial_seen")


async def test_the_report_says_what_it_did(two_games):
    interaction = await reset(two_games)

    reply = interaction.reply
    assert "back to the morning before anybody entered" in reply
    assert "table(s)" in reply
    assert "back in the house" in reply
