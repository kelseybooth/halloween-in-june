"""Drop 40: the collar stops being something to keep.

**The one thing in the house a player gives back.** Everything else is
taken, used, eaten or carried; the collar is spent on the cat and
leaves the game, and the house looks different afterwards for
everybody.

Two decisions on 6 November shaped what is here as much as the work
order did.

**The relationship minimum is gone.** The order opened with a gate at
fifty - she refuses below it, the player keeps the collar - and it was
dropped. That removed the only hard problem in the order: a refusal has
to land before `record_use` *and* before the `consumed_on_use` spend,
and `after_use` runs after both, so the gate could not have lived where
the order put it ("a code check, like the drawer" - the drawer has no
code check; its gate is `requires`). With no gate, this is an ordinary
consuming use.

**The floor-use case is gone too.** The order wanted the collar usable
from the room's Also here list. `_finish_use` deliberately refuses a
`consumed_on_use` thing that is not carried - the burrito rule - and
that was kept rather than widened, because widening it changes every
consumable in the game.

The order's `use_fail` line, *she walks off with her tail high*, is
therefore **not in the files**. With `use` filled, no `requires` and no
cooldown, nothing can read a `use_fail` - so writing it in would be a
sentence no player could ever see, which is the `window_open` mistake
in miniature. `test_the_refusal_line_was_not_written` says so where
somebody putting the gate back will find it.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
import resolve
import states
import telemetry
import triggers
import world


THIS_DROP = 40

COLLAR = "cat_collar"
NAME_TAG = "name_tag"

BUCKLED = "lowers her head and lets you buckle it on"
PLEASED = "looks extremely pleased with herself"
PUBLIC = "buckles the cat's collar back on"
POCKETS = "Somebody is probably missing this"
TAG_ON_CAT = "A slim black collar sits at her throat"
PLAIN_CAT = "winding between your feet"


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.register_all()
    triggers.forget_arrivals()
    yield
    achievements.clear()


@pytest.fixture(autouse=True)
def forget_admissions():
    bot._ADMITTING.clear()
    yield
    bot._ADMITTING.clear()


@pytest.fixture
async def bedroom(db, monkeypatch):
    """Drop 40, the collar where the loader puts it, and two players.

    Bob exists so the server-wide half can be read by somebody who did
    not buckle it. The drop is set before the load for the reason the
    can's and the ladder's fixtures set it: the loader places stock into
    the guilds `users` has seen and judges arrival from the pointer, so
    loading first places nothing.
    """
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    await db.set_setting(GUILD_A, resolve.DROP_KEY, THIS_DROP)
    await content_loader.load_content(
        content_module.load_files(), guild_ids=[GUILD_A]
    )
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    # Both players have to be *in* the house, not merely known to it.
    # Without a `player_game_state` row `/use` finds no body, falls back
    # to the channel stand-in, and refuses every command here as typed
    # from the wrong window - which looks exactly like a broken feature.
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    for who in (ALICE, BOB):
        await db.start_game(who, GUILD_A, "EN", await resolve.rooms_open_at_launch())
        await db.notice(GUILD_A, who, content_module.FED_THE_CAT)
    # The idle sweep walks `bot.bot.guilds`, so it needs one to walk.
    monkeypatch.setattr(
        bot,
        "bot",
        SimpleNamespace(
            guilds=[guild],
            get_guild=lambda gid: guild if gid == GUILD_A else None,
        ),
    )
    return db, guild, halloween, rooms


def thread(bedroom, room):
    """The thread for a room id, or the channel itself for the road.

    Takes the id rather than the name, and the road is the reason: `CH`
    has no thread - it *is* the channel - so a lookup by name misses,
    and a helper that fell back to the channel on a miss would hand
    every room the wrong window and blame the place check.
    """
    _, _, halloween, rooms = bedroom
    if room == content_module.CHANNEL_ROOM:
        return halloween
    return next(t for t in halloween.threads if t.name == rooms[room])


async def run(bedroom, command, arg=None, *, room, who=ALICE):
    db, guild, _, rooms = bedroom
    await db.update_current_room(who, GUILD_A, room)
    interaction = FakeInteraction(
        who, GUILD_A, guild=guild, channel=thread(bedroom, room)
    )
    args = () if arg is None else (arg,)
    await command.callback(interaction, *args)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


def out_loud(bedroom) -> str:
    """Everything said out loud, in every room and the channel."""
    _, _, halloween, _ = bedroom
    lines = list(halloween.posted)
    for th in halloween.threads:
        lines.extend(th.posted)
    return "\n".join(line for line in lines if line)


async def earned_by(who=ALICE) -> set:
    return set(await database.player_achievements_of(GUILD_A, who))


async def use_rows(thing_id=COLLAR) -> list:
    """The `detail` of every successful logged use of a thing."""
    session_factory = database._require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(database.InteractionLog.detail).where(
                database.InteractionLog.guild_id == GUILD_A,
                database.InteractionLog.thing_id == thing_id,
                database.InteractionLog.action == telemetry.USE,
                database.InteractionLog.outcome == telemetry.SUCCESS,
            )
        )
        return [r[0] for r in rows if r[0]]


async def holding(bedroom, who=ALICE):
    """Take the collar the way a player does, not by writing the row.

    **`carry()` would be wrong here and it took a test to notice.** A
    direct inventory insert leaves the Bedroom's own copy on the floor,
    so the collar is in a bag *and* still in the room - and
    `test_and_there_is_no_collar_left_to_find` passed the bag check
    while Bob happily took a second one. There is exactly one collar,
    which is the whole premise.

    A real take also writes the log row `when_first_taken` reads, so
    `in_play` in the log is a duration rather than a shrug.
    """
    db, *_ = bedroom
    await run(bedroom, bot.take, "cat collar", room="BE", who=who)
    assert await db.carried_of(who, GUILD_A, COLLAR) == 1
    return db


async def unused_for(db, hours, who=ALICE):
    """Backdate both stamps the sweep takes the later of.

    `taken_at` for when it reached these hands and `last_used_at` for
    the last time it was used. Moving one and not the other tests
    nothing, because the other is still `now`.
    """
    then = await database.server_now(GUILD_A) - timedelta(hours=hours)
    async with db._require_session()() as session:
        await session.execute(
            update(database.PlayerInventory)
            .where(
                database.PlayerInventory.user_id == who,
                database.PlayerInventory.guild_id == GUILD_A,
                database.PlayerInventory.thing_id == COLLAR,
            )
            .values(taken_at=then)
        )
        await session.execute(
            update(database.ThingUse)
            .where(
                database.ThingUse.user_id == who,
                database.ThingUse.guild_id == GUILD_A,
                database.ThingUse.thing_id == COLLAR,
            )
            .values(last_used_at=then)
        )
        await session.commit()


# --------------------------------------------------------------------------
# Taking it
# --------------------------------------------------------------------------


async def test_taking_it_hints_that_somebody_is_missing_it(bedroom):
    """The take line changed with the collar's purpose.

    It read "something worth keeping safe", which is advice to keep a
    thing the drop now exists for giving away.

    Read from the room and not the reply: the line is third person, so
    it is posted where the other players can see it.
    """
    await run(bedroom, bot.take, "cat collar", room="BE")

    assert POCKETS in out_loud(bedroom)


# --------------------------------------------------------------------------
# Putting it on
# --------------------------------------------------------------------------


async def test_the_cat_lets_you_buckle_it_on(bedroom):
    await holding(bedroom)

    reply = replies(await run(bedroom, bot.use, "cat collar", room="BE"))

    assert BUCKLED in reply
    assert PLEASED in reply


async def test_and_the_room_is_told_in_its_own_sentence(bedroom):
    """**Two lines rather than one, which is the exception here.**

    Everywhere else a public line replaces the private one, because
    both were the same sentence and the player stood in the room
    reading it twice. These are written as two: the buckler gets the
    scene, the room gets the notice and the name on the tag.
    """
    await holding(bedroom)

    interaction = await run(bedroom, bot.use, "cat collar", room="BE")

    assert PUBLIC in out_loud(bedroom)
    assert BUCKLED in replies(interaction)
    assert PUBLIC not in replies(interaction)


async def test_the_collar_is_spent(bedroom):
    db = await holding(bedroom)

    await run(bedroom, bot.use, "cat collar", room="BE")

    assert await db.carried_of(ALICE, GUILD_A, COLLAR) == 0


async def test_and_it_earns_name_tag(bedroom):
    await holding(bedroom)

    await run(bedroom, bot.use, "cat collar", room="BE")

    assert NAME_TAG in await earned_by()


async def test_the_state_is_set_for_the_whole_server(bedroom):
    await holding(bedroom)

    await run(bedroom, bot.use, "cat collar", room="BE")

    assert world.COLLAR_ON in await states.in_force(GUILD_A, BOB)


# --------------------------------------------------------------------------
# What everybody sees afterwards
# --------------------------------------------------------------------------


async def test_before_it_the_cat_has_no_collar(bedroom):
    reply = replies(await run(bedroom, bot.look, "cat", room="BE"))

    assert PLAIN_CAT in reply
    assert TAG_ON_CAT not in reply


async def test_afterwards_somebody_else_sees_the_collar(bedroom):
    """**The whole point of a server state.** Bob did not buckle it and
    was not in the room; the cat he looks at is wearing it."""
    await holding(bedroom)
    await run(bedroom, bot.use, "cat collar", room="BE")

    reply = replies(await run(bedroom, bot.look, "cat", room="LI", who=BOB))

    assert TAG_ON_CAT in reply


async def test_and_on_the_road_too(bedroom):
    """The cat is `room_id = ALL`, and the road is a room like any other.

    Worth pinning because the channel reads as somewhere the game is
    not: players walk out of the Entryway onto it, and `reach` resolves
    `ALL` things there exactly as it does indoors.
    """
    await holding(bedroom)
    await run(bedroom, bot.use, "cat collar", room="BE")

    reply = replies(await run(bedroom, bot.look, "cat", room="CH", who=BOB))

    assert TAG_ON_CAT in reply


async def test_the_collar_can_be_buckled_on_the_road(bedroom):
    """Not only looked at from there - used there.

    `after_use` takes no room for this one, deliberately: a rule naming
    the Bedroom would refuse a player who carried the collar out of the
    house, with the cat standing next to them.
    """
    await holding(bedroom)

    reply = replies(await run(bedroom, bot.use, "cat collar", room="CH"))

    assert BUCKLED in reply
    assert world.COLLAR_ON in await states.in_force(GUILD_A, ALICE)


async def test_and_there_is_no_collar_left_to_find(bedroom):
    await holding(bedroom)
    await run(bedroom, bot.use, "cat collar", room="BE")

    reply = replies(await run(bedroom, bot.take, "cat collar", room="BE", who=BOB))

    assert POCKETS not in reply
    assert await database.carried_of(BOB, GUILD_A, COLLAR) == 0


# --------------------------------------------------------------------------
# The rules that did not change for it
# --------------------------------------------------------------------------


async def test_the_collar_has_to_be_in_your_hands(bedroom):
    """**The floor-use case, refused on purpose.**

    The work order asked for the collar to be usable from the room's
    Also here list. `_finish_use` refuses a `consumed_on_use` thing
    that is not carried, so a burrito on the floor is not eaten by
    somebody who never picked it up. Nothing is spent and no state is
    set.
    """
    reply = replies(await run(bedroom, bot.use, "cat collar", room="BE"))

    assert BUCKLED not in reply
    assert world.COLLAR_ON not in await states.in_force(GUILD_A, ALICE)
    assert NAME_TAG not in await earned_by()


async def test_and_that_refusal_is_not_a_use(bedroom):
    """The row, not the reply: a refused use must not stamp one.

    Which is also what would have made a relationship gate hard. The
    check has to come before `record_use`, and `after_use` - where a
    code gate would naturally go - runs after it.
    """
    await run(bedroom, bot.use, "cat collar", room="BE")

    assert await database.which_of_these_used(ALICE, GUILD_A, [COLLAR]) == set()


def test_the_refusal_line_was_not_written():
    """**No `use_fail` on the collar**, because nothing can read one."""
    content = content_module.load_files()
    rows = [
        r for r in content.thing_text
        if r.entity_id == COLLAR and r.state == "default"
    ]
    assert len(rows) == 1
    assert not rows[0].text.get("use_fail")
    assert rows[0].text.get("use")


# --------------------------------------------------------------------------
# The six-hour clock
# --------------------------------------------------------------------------


async def test_six_hours_unused_sets_the_collar_down(bedroom):
    """So nobody can sit on the only collar in the game.

    The sweep is driven by the `idle_drop_hours` cell alone - the query
    selects every thing with the column set - so this needed no code.
    """
    db = await holding(bedroom)
    await db.update_current_room(ALICE, GUILD_A, "LI")
    await unused_for(db, 7)

    await bot.idle_sweep.coro()

    assert await db.carried_of(ALICE, GUILD_A, COLLAR) == 0
    assert "cat collar" in dict(await database.loose_here(GUILD_A, "LI"))


async def test_but_five_hours_is_not_enough(bedroom):
    db = await holding(bedroom)
    await unused_for(db, 5)

    await bot.idle_sweep.coro()

    assert await db.carried_of(ALICE, GUILD_A, COLLAR) == 1


async def test_and_a_buckled_collar_cannot_be_swept(bedroom):
    """Nothing left to sweep, and the sweep must not mind.

    There is one collar and it is spent, so the inventory row is gone
    before any clock could trip. Written down because a sweep that
    raised on a consumed thing would break the nightly job rather than
    only this feature.
    """
    db = await holding(bedroom)
    await unused_for(db, 7)
    await run(bedroom, bot.use, "cat collar", room="BE")

    await bot.idle_sweep.coro()

    assert await db.carried_of(ALICE, GUILD_A, COLLAR) == 0
    assert world.COLLAR_ON in await states.in_force(GUILD_A, ALICE)


# --------------------------------------------------------------------------
# The log
# --------------------------------------------------------------------------


async def test_the_buckling_logs_what_cannot_be_asked_afterwards(bedroom):
    """`score` and `in_play` are both gone by the time anybody could ask.

    The inventory row is deleted by the spend, so how long the collar
    sat in a bag is answerable only from the log's take rows - which is
    why `when_first_taken` reads those rather than `taken_at`. The
    score is recorded although nothing reads it any more: the question
    the deck will ask is whether the dropped gate should have existed.
    """
    await holding(bedroom)
    await database.set_relationship(GUILD_A, ALICE, 73)

    await run(bedroom, bot.use, "cat collar", room="BE")

    rows = await use_rows()
    assert len(rows) == 1
    assert "score=73" in rows[0]
    assert "first=yes" in rows[0]
    # A number, not a shrug. `in_play=?` is what a missing take row
    # reads as, and asserting only the key would have accepted it.
    in_play = rows[0].split("in_play=")[1].split()[0]
    assert in_play.isdigit(), rows[0]
