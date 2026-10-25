"""The interaction log: what the game writes down about itself.

Driven through the real commands rather than through `log_interaction`,
because every way this can be wrong is at a call site. A writer that
works and a gate that forgets to call it produce exactly the table the
proposal was trying to avoid - one where a refusal and a zero-scoring
success look identical, because the refusal is simply absent.

The one thing asserted negatively, more than once, is that **a telemetry
failure never reaches the player**. Every call here happens inside a
command handler, most of them inside its `except SQLAlchemyError`, so a
raise from a logging call would be reported as "something went wrong"
for an action that had already happened.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select, text

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import hints
import resolve
import telemetry


@pytest.fixture
async def server(db):
    """Drop 1: a channel, a cat, a bed and the verbs that reach them."""
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A,
        name="Test Server",
        channels=[halloween],
        members=[FakeMember(ALICE), FakeMember(BOB)],
    )
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, 1)
    await db.ensure_user_exists(ALICE, GUILD_A)
    return db, guild, halloween


async def rows(db, *, action=None, user_id=None):
    """Every logged row, oldest first."""
    async with db._require_session()() as session:
        query = select(database.InteractionLog).order_by(database.InteractionLog.id)
        if action is not None:
            query = query.where(database.InteractionLog.action == action)
        if user_id is not None:
            query = query.where(database.InteractionLog.user_id == user_id)
        return list((await session.scalars(query)).all())


async def run(server, command, *args, who=ALICE):
    _, guild, halloween = server
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await command.callback(interaction, *args)
    return interaction


# --------------------------------------------------------------------------
# Petting, which is the whole game at drop 0
# --------------------------------------------------------------------------


async def test_a_pet_writes_one_row(server):
    db, *_ = server
    await run(server, bot.pet)

    (row,) = await rows(db, action=database.PET)
    assert row.actor == database.PLAYER
    assert row.outcome == database.SUCCESS
    assert row.user_id == ALICE
    assert row.guild_id == GUILD_A
    assert row.drop == 1


async def test_the_row_says_what_the_pet_was_worth_and_where_it_left_them(server):
    """Self-describing, which is the point of `score_after`: the score
    is otherwise only knowable by summing every delta correctly from
    the beginning of time."""
    db, *_ = server
    await run(server, bot.pet)

    (row,) = await rows(db, action=database.PET)
    assert row.relationship_delta in (bot.RELATIONSHIP_STEP, -bot.RELATIONSHIP_STEP)
    assert row.score_after == database.RELATIONSHIP_START + row.relationship_delta


async def test_a_standoffish_pet_is_a_success_with_a_negative_delta(server, monkeypatch):
    """**Not a refusal.** The command did exactly what it does; the cat
    was simply unimpressed. Filing that as `refused` would put it in
    with the cooldowns and the missing keys, and the count of players
    bouncing off the game would quietly include everybody petting a
    cat."""
    db, *_ = server
    monkeypatch.setattr(bot, "friendly_chance", lambda *a, **k: 0)
    await run(server, bot.pet)

    (row,) = await rows(db, action=database.PET)
    assert row.outcome == database.SUCCESS
    assert row.relationship_delta == -bot.RELATIONSHIP_STEP


async def test_every_pet_gets_its_own_row(server):
    db, *_ = server
    for _ in range(3):
        await run(server, bot.pet)

    assert len(await rows(db, action=database.PET)) == 3


# --------------------------------------------------------------------------
# The mood roll reads this table now
# --------------------------------------------------------------------------


async def test_the_recent_window_counts_logged_pets(server):
    """`pet_events` is gone and this is the query that replaced it.
    Asserted through the count the cat actually weights, because a
    table nobody reads is the failure worth catching."""
    db, *_ = server
    assert await db.recent_pets(ALICE, GUILD_A) == 0

    await run(server, bot.pet)
    await run(server, bot.pet)

    assert await db.recent_pets(ALICE, GUILD_A) == 2


async def test_rows_of_other_actions_do_not_weight_the_cats_mood(server):
    """The filter on `action` is the whole difference between this
    table and the one it replaced. Without it every `/look` would make
    the cat crowded."""
    db, *_ = server
    await telemetry.succeeded(GUILD_A, ALICE, telemetry.LOOK)
    await telemetry.succeeded(GUILD_A, ALICE, telemetry.USE, thing_id="cat_bed")

    assert await db.recent_pets(ALICE, GUILD_A) == 0


async def test_a_pet_outside_the_window_has_left_it(server):
    db, *_ = server
    stale = await db.server_now(GUILD_A) - db.RECENT_PET_WINDOW - timedelta(minutes=1)
    await telemetry.record(
        GUILD_A,
        action=telemetry.PET,
        user_id=ALICE,
        outcome=telemetry.SUCCESS,
        now=stale,
    )

    assert await db.recent_pets(ALICE, GUILD_A) == 0


async def test_clearing_cooldowns_clears_the_window_it_counts_from(server):
    db, *_ = server
    await run(server, bot.pet)
    await db.clear_cooldowns(GUILD_A, ALICE)

    assert await db.recent_pets(ALICE, GUILD_A) == 0


# --------------------------------------------------------------------------
# Refusals, which are the half the first proposal could not see
# --------------------------------------------------------------------------


async def test_an_unknown_noun_records_the_word_that_was_typed(server):
    """**A free, ranked list of the things players expect and the game
    does not have.** A week of these says more about the channel than
    another playtest would."""
    db, *_ = server
    await run(server, bot.look, "chandelier")

    (row,) = await rows(db, action=database.UNKNOWN_NOUN)
    assert row.detail == "chandelier"
    assert row.outcome == database.REFUSED
    assert row.reason == database.UNKNOWN


async def test_the_word_is_stored_as_it_was_typed(server):
    """Casing and plurals are part of the answer: knowing whether
    people reach for the singular or the plural is the kind of thing
    this table is for, and normalising it away costs nothing visible
    until somebody wants it back."""
    db, *_ = server
    await run(server, bot.look, "  Fireplaces  ")

    (row,) = await rows(db, action=database.UNKNOWN_NOUN)
    assert row.detail == "Fireplaces"


async def test_a_refusal_scores_nothing_and_says_so(server):
    """Zero rather than null, and told apart from a success that
    happened to score zero by the outcome beside it."""
    db, *_ = server
    await run(server, bot.look, "chandelier")

    (row,) = await rows(db, action=database.UNKNOWN_NOUN)
    assert row.relationship_delta == 0


async def test_looking_at_something_real_is_a_success_naming_the_thing(server):
    db, *_ = server
    await run(server, bot.look, "bed")

    looks = await rows(db, action=database.LOOK)
    assert looks[-1].outcome == database.SUCCESS
    assert looks[-1].thing_id == "cat_bed"


async def test_looking_around_names_the_room_rather_than_a_thing(server):
    db, *_ = server
    await run(server, bot.look)

    (row,) = await rows(db, action=database.LOOK)
    assert row.thing_id is None
    assert row.detail == content_module.CHANNEL_ROOM


# --------------------------------------------------------------------------
# The hint rail
# --------------------------------------------------------------------------


async def test_a_hint_records_which_rung_fired(server):
    """The rail is a bet about discoverability that it cannot settle on
    its own: a player who reads the bed's description and does nothing
    might have missed the prose or missed the verb, and those want
    opposite fixes. A hint row before an action says the rail carried
    them; an action with no hint before it says the prose did its job."""
    db, *_ = server
    await run(server, bot.look)

    hinted = await rows(db, action=database.HINT)
    assert hinted, "the first look should offer a rung"
    assert hinted[0].detail in {hint.hint_id for hint in hints.ALL}


async def test_a_rung_is_logged_once_because_it_only_fires_once(server):
    db, *_ = server
    await run(server, bot.look)
    first = [row.detail for row in await rows(db, action=database.HINT)]
    await run(server, bot.look)
    again = [row.detail for row in await rows(db, action=database.HINT)]

    assert len(first) == 1
    assert again.count(first[0]) == 1


# --------------------------------------------------------------------------
# The world acting on its own
# --------------------------------------------------------------------------


async def test_the_nightly_recovery_is_a_system_row(server):
    """**The main downward force in the game across a staged release**
    is the clock, not anything a player does. A log of player actions
    alone would show meters moving for no recorded reason."""
    db, *_ = server
    await db.adjust_relationship(ALICE, GUILD_A, -60)
    await telemetry.recoveries(await db.run_pending_recovery())

    (row,) = await rows(db, action=database.RECOVERY)
    assert row.actor == database.SYSTEM
    assert row.user_id == ALICE
    assert row.relationship_delta == db.RECOVERY_STEP
    assert row.score_after == -60 + db.RECOVERY_STEP


async def test_a_system_row_still_names_the_player_it_moved(server):
    """A null `user_id` is for a row about nobody. A recovery is about
    one player's score, and a table of them with no player in it could
    not answer the question it exists for."""
    db, *_ = server
    await db.adjust_relationship(ALICE, GUILD_A, -60)
    await telemetry.recoveries(await db.run_pending_recovery())

    moved = await rows(db, action=database.RECOVERY)
    assert moved and all(row.user_id is not None for row in moved)


# --------------------------------------------------------------------------
# A log that cannot be written is not an error the player sees
# --------------------------------------------------------------------------


async def test_a_failed_write_does_not_cost_the_player_their_pet(server, monkeypatch):
    db, *_ = server

    async def explode(*args, **kwargs):
        raise database.SQLAlchemyError("the log is on fire")

    monkeypatch.setattr(database, "log_interaction", explode)
    interaction = await run(server, bot.pet)

    assert bot.DB_ERROR_MESSAGE not in str(interaction.sent[-1])
    assert await db.get_pet_count(ALICE, GUILD_A) == 1


async def test_a_failed_write_returns_none_rather_than_raising(db, monkeypatch):
    def explode(*args, **kwargs):
        raise database.SQLAlchemyError("still on fire")

    monkeypatch.setattr(database.InteractionLog, "__init__", explode)

    assert await telemetry.succeeded(GUILD_A, ALICE, telemetry.LOOK) is None


async def test_closing_a_row_that_was_never_opened_is_quiet(db):
    """A failed open returns None, and the second half has to cope with
    that rather than stack a second failure on the first."""
    await database.close_interaction(None, relationship_delta=5, score_after=5)


# --------------------------------------------------------------------------
# Upgrading a database that still has the old table
# --------------------------------------------------------------------------


OLD_TABLE = (
    "CREATE TABLE pet_events (id INTEGER PRIMARY KEY, user_id BIGINT, "
    "guild_id BIGINT, created_at TIMESTAMP, relationship_at_pet INTEGER)"
)
OLD_ROW = (
    "INSERT INTO pet_events (user_id, guild_id, created_at, relationship_at_pet) "
    f"VALUES ({ALICE}, {GUILD_A}, '2026-10-01 12:00:00', 35)"
)


async def test_old_pet_events_are_carried_over_and_the_table_dropped(db):
    """**Copied rather than abandoned**, for the ten minutes it would
    otherwise lose: a server upgraded mid-evening would read every
    player as having pet nobody recently, so the cat would turn
    friendly for everybody at once and the crowding nudge would fire
    again on the next pet."""
    async with db._engine.begin() as conn:
        await conn.execute(text(OLD_TABLE))
        await conn.execute(text(OLD_ROW))
        await database._migrate_pet_events(conn)

    (row,) = await rows(db, action=database.PET)
    assert row.user_id == ALICE
    assert row.guild_id == GUILD_A
    assert row.outcome == database.SUCCESS

    async with db._engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(text("SELECT 1 FROM pet_events"))


async def test_what_a_carried_row_cannot_claim_to_know(db):
    """The old row recorded the score *before* the pet and never the
    outcome, so a copy cannot say what the pet was worth. Null rather
    than a plausible zero, and the one figure it does have goes where
    it cannot be mistaken for either."""
    async with db._engine.begin() as conn:
        await conn.execute(text(OLD_TABLE))
        await conn.execute(text(OLD_ROW))
        await database._migrate_pet_events(conn)

    (row,) = await rows(db, action=database.PET)
    assert row.relationship_delta is None
    assert row.score_after is None
    assert row.detail == "score_before=35"


async def test_a_database_without_the_old_table_is_untouched(db):
    """Every fresh install, and every boot after the first."""
    async with db._engine.begin() as conn:
        await database._migrate_pet_events(conn)
        await database._migrate_pet_events(conn)

    assert await rows(db) == []


# --------------------------------------------------------------------------
# Drop 2, where a refusal is the mechanic rather than a locked door
# --------------------------------------------------------------------------


WAND = "feather_wand"


@pytest.fixture
async def with_a_toy(db):
    """Drop 2, with a wand already in the player's hands."""
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A,
        name="Test Server",
        channels=[halloween],
        members=[FakeMember(ALICE), FakeMember(BOB)],
    )
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, 2)
    await content_loader.place_arrived(GUILD_A)
    await db.ensure_user_exists(ALICE, GUILD_A)
    await database.place_in_room(GUILD_A, content_module.CHANNEL_ROOM, WAND, 1)
    bot.forget_public_pets()
    return db, guild, halloween


async def test_the_cat_declining_is_logged_with_the_rung(with_a_toy):
    """**Not a gate, but it reads as one to the player.** The first
    offer is a guaranteed refusal by design, and without the rung a
    month of these is indistinguishable from a toy nobody can use."""
    db, *_ = with_a_toy
    await run(with_a_toy, bot.take, "wand")
    await run(with_a_toy, bot.use, "wand")

    refusals = [r for r in await rows(db, action=database.USE)
                if r.outcome == database.REFUSED]
    assert refusals[-1].reason == database.RAMP
    assert refusals[-1].thing_id == WAND
    assert refusals[-1].detail == "rung_after=1"


async def test_taking_the_toy_is_logged_as_a_success(with_a_toy):
    db, *_ = with_a_toy
    await run(with_a_toy, bot.take, "wand")

    (row,) = await rows(db, action=database.TAKE)
    assert row.outcome == database.SUCCESS
    assert row.thing_id == WAND
    assert row.drop == 2


async def test_using_a_toy_on_the_floor_is_refused_for_not_carrying_it(with_a_toy):
    """A gate this time, and the reason is what separates it from the
    one above: the same command, the same toy, two different fixes."""
    db, *_ = with_a_toy
    await run(with_a_toy, bot.use, "wand")

    refusals = [r for r in await rows(db, action=database.USE)
                if r.outcome == database.REFUSED]
    assert refusals[-1].reason == database.NOT_CARRIED
