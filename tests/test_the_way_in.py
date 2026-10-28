"""The road, the house, and the door between them.

Was `test_enter.py`. `/enter` was a one-way command with three jobs nobody
would have guessed from its name: it created the player's row, it pinned
**day one for the whole server**, and it showed the tutorial. Drop 10
retires it and makes the way in an ordinary exit, so those three jobs now
belong to the first walk in through the front door - and most of this file
is about them, because they are the part a rename would have dropped.

The rest is the door working in both directions, which is new. Before this
the channel was somewhere players stood and never somewhere they walked to,
and the Entryway's front door was a fixture that declined to open.

**Where each line goes matters as much as what it says.** A move posts in
two places, and one of them is now a channel rather than a thread: the
mention that admits somebody to a private thread is a key, so arriving on
the road - where there is no lock - carries a plain name instead.
"""

import pytest
from sqlalchemy import select

from conftest import ALICE, BOB, GUILD_A, LAST_DROP
from fake_discord import (
    FakeChannel,
    FakeGuild,
    FakeInteraction,
    FakeMember,
    a_room_thread,
    somewhere_else,
)

import achievements
import bot
import content as content_module
import content_loader
import database
import hints
import resolve
import restocking
import states
import triggers
import world


HOUSE_DROP = 10


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.register_all()
    triggers.forget_arrivals()
    yield
    achievements.clear()


@pytest.fixture
async def built(db):
    """The house built, its threads open, and everybody still outside."""
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    await content_loader.load_content(content_module.load_files())
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, LAST_DROP)
    # **Unlocked, because this file is about the door working rather
    # than about the lock on it.** Drop 10 ships the front door shut for
    # the whole server until somebody turns the brass key in it; that is
    # `test_the_locked_door.py`, and a fixture here that kept it shut
    # would make every test below fail on a condition none of them
    # mentions.
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    return db, guild, halloween, rooms


async def go(built, where="house", who=ALICE, channel=None, room=None):
    """`/go` from the road, or from a room's own thread."""
    _, guild, halloween, rooms = built
    if channel is None:
        channel = halloween if room is None else a_room_thread(rooms[room])
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=channel)
    await bot.go.callback(interaction, where)
    return interaction


async def use(built, thing, who=ALICE, channel=None, room=None):
    _, guild, halloween, rooms = built
    if channel is None:
        channel = halloween if room is None else a_room_thread(rooms[room])
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=channel)
    await bot.use.callback(interaction, thing)
    return interaction


async def fed(built, who=ALICE):
    """The flag the first feed writes, for a test about something else.

    Drop 10 gates the Entryway's inner doorways on it, so anything that
    walks further in than the hall has to say the player got out of the
    hall the way a player does. Feeding itself is `test_feeding.py`.
    """
    db, *_ = built
    await db.notice(GUILD_A, who, content_module.FED_THE_CAT)


async def walk_to_the_courtyard(built):
    """Three doorways from the Entryway, which is where the oak is."""
    await fed(built)
    for room, door in (("EN", "dining room"), ("DI", "kitchen"), ("KI", "courtyard")):
        await go(built, door, room=room)


def thread(built, room_name):
    _, _, halloween, _ = built
    return next(t for t in halloween.threads if t.name == room_name)


async def where(db, who=ALICE):
    state = await db.get_game_state(who, GUILD_A)
    return state.current_room if state else None


async def logged(db, who=ALICE):
    """This player's `interaction_log` rows, oldest first."""
    session_factory = db._require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(db.InteractionLog)
            .where(
                db.InteractionLog.guild_id == GUILD_A,
                db.InteractionLog.user_id == who,
            )
            .order_by(db.InteractionLog.id)
        )
        return list(rows.scalars())


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


# --------------------------------------------------------------------------
# `/enter` is gone
# --------------------------------------------------------------------------


def test_there_is_no_enter_command():
    """**Not a rename.** Going in is movement, so the command that does it
    is the one that moves a player anywhere. A second command that also
    enrolled people is how one of the two quietly stops being maintained."""
    assert not hasattr(bot, "enter")
    assert "enter" not in {c.name for c in bot.bot.tree.get_commands()}


def test_and_nothing_still_says_to_run_it():
    """Its three lines, `#welcome`, and the tutorial, which `/enter` was
    the only thing that posted. A live lookup for a key that is gone reads
    as silence, which is worse than a line nobody wanted."""
    defaults = content_module.load_files().defaults
    for key in (
        "enter.public", "enter.returning", "enter.arrived", "#welcome", "tutorial",
    ):
        assert key not in defaults


# --------------------------------------------------------------------------
# In through the front door
# --------------------------------------------------------------------------


async def test_go_house_puts_a_new_player_in_the_entryway(built):
    db, *_ = built

    await go(built)

    assert await where(db) == "EN"


@pytest.mark.parametrize("word", ["house", "haunted house", "front door", "in"])
async def test_the_words_that_work_from_the_road(built, word):
    """The writers' aliases, each one run rather than read."""
    db, *_ = built

    await go(built, word)

    assert await where(db) == "EN"


async def test_use_front_door_works_from_the_road_too(built):
    """`/go` is the verb players reach for; `/use` moved people before it
    existed and still does."""
    db, *_ = built

    await use(built, "front door")

    assert await where(db) == "EN"


async def test_the_arrival_line_lets_them_into_the_thread(built):
    """The mention is the admission - see test_arrivals.py for why."""
    await go(built)

    posted = thread(built, "Entryway").posted
    assert any(f"<@{ALICE}>" in line for line in posted)
    assert any("comes in from the road" in line for line in posted)


async def test_the_road_watches_them_go(built):
    _, _, halloween, _ = built

    await go(built)

    assert any("disappears into the house" in line for line in halloween.posted)


async def test_and_that_line_pings_nobody(built):
    """A departure is not an admission, so it carries a plain name. Nobody
    is pinged by other players' comings and goings."""
    _, _, halloween, _ = built

    await go(built)

    assert f"<@{ALICE}>" not in " ".join(halloween.posted)


async def test_the_private_reply_is_the_exit_s_own_line(built):
    interaction = await go(built)

    reply = replies(interaction)
    assert "You cross the road to the house" in reply
    assert thread(built, "Entryway").mention in reply
    assert interaction.was_private


async def test_the_house_is_not_gated_on_anything(built):
    """It is the exit that enrols people, so there is nothing they could
    have unlocked yet - and a `requires` on it would be a lock with no key
    anywhere in the game."""
    row = next(
        t for t in content_module.load_files().things if t.thing_id == world.HOUSE
    )

    assert not row.requires
    assert world.HOUSE in world.UNGATED_EXITS


# --------------------------------------------------------------------------
# The three jobs `/enter` used to do
# --------------------------------------------------------------------------


async def test_nothing_posts_a_tutorial_any_more(built):
    """**Settled in the copy deck before this branch existed:** the POC
    ships with no welcome text and no tutorial, and the hint rail and the
    gating replace both. The key outlived the decision because `/enter`
    was still posting it.

    By the time anybody reaches the house the rail has taught `/look`,
    `/look <thing>`, `/take`, `/use`, `/inventory` and `/drop` in the
    channel - every bullet the tutorial had except movement, which it got
    wrong: it named the wide doorway, and that arrives at drop 30.
    """
    await go(built)

    posted = " ".join(thread(built, "Entryway").posted)
    assert "/look coat rack" not in posted
    assert "/use wide doorway" not in posted


async def test_building_the_house_does_not_start_the_clock(built):
    """An admin can initialize on 29 September and open on 1 October."""
    assert await restocking.initialized_on(GUILD_A) is None


async def test_the_first_walk_in_starts_it(built):
    """**Day one for the whole server**, and `/enter` was its only caller.
    Restock day numbers and the drop calendar both count from here, so a
    server that never gets this never restocks."""
    await go(built)

    assert await restocking.initialized_on(GUILD_A) == database.pacific_today()


async def test_the_second_one_does_not_move_it(built):
    """Whoever is first decides the calendar, and nobody after them can
    change it."""
    await go(built)
    day_one = await restocking.initialized_on(GUILD_A)

    await go(built, who=BOB)

    assert await restocking.initialized_on(GUILD_A) == day_one


async def test_a_refused_way_in_does_not_start_it(built):
    """Drop 3: the house is in `things.tsv` and has not arrived. The refusal
    has to come before anything is written, or a server gets a calendar out
    of a door nobody opened."""
    await resolve.set_current_drop(GUILD_A, 3)

    await go(built)

    assert await restocking.initialized_on(GUILD_A) is None
    assert await where(built[0]) is None


async def test_petting_in_the_channel_creates_a_row_with_no_game_state(built):
    """v1 behaviour, unchanged, and the reason the way in cannot assume a
    row: a member can hold a relationship score and have no room at all."""
    db, guild, halloween, _ = built

    await bot.pet.callback(
        FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    )

    assert await db.get_pet_count(ALICE, GUILD_A) == 1
    assert await db.get_game_state(ALICE, GUILD_A) is None


async def test_that_player_is_enrolled_by_the_door(built):
    db, guild, halloween, _ = built
    await bot.pet.callback(
        FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    )
    before = await db.get_relationship(ALICE, GUILD_A)

    await go(built)

    assert await where(db) == "EN"
    assert await db.get_relationship(ALICE, GUILD_A) == before


async def test_the_launch_rooms_are_unlocked_on_the_way_in(built):
    """`/enter` seeded them. A player enrolled without them is one whose
    every exit refuses as unreachable."""
    db, *_ = built

    await go(built)

    unlocked = (await db.get_game_state(ALICE, GUILD_A)).rooms_unlocked
    assert "EN" in unlocked
    assert "SE" not in unlocked


# --------------------------------------------------------------------------
# Out again
# --------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["road", "front door", "outside", "out"])
async def test_the_words_that_work_from_the_entryway(built, word):
    db, *_ = built
    await go(built)

    await go(built, word, room="EN")

    assert await where(db) == "CH"


async def test_use_front_door_lets_them_out_as_well(built):
    db, *_ = built
    await go(built)

    await use(built, "front door", room="EN")

    assert await where(db) == "CH"


async def test_leaving_posts_in_both_places(built):
    _, _, halloween, _ = built
    await go(built)
    before = len(halloween.posted)

    await go(built, "road", room="EN")

    assert any(
        "lets themselves out through the front door" in line
        for line in thread(built, "Entryway").posted
    )
    assert any(
        "back onto the road" in line for line in halloween.posted[before:]
    )


async def test_arriving_on_the_road_pings_nobody(built):
    """**The one place an arrival line carries a plain name.** The mention
    is what admits somebody to a private thread; nobody has to be let into
    the channel, so a public ping for stepping outside is only noise."""
    _, _, halloween, _ = built
    await go(built)
    before = len(halloween.posted)

    await go(built, "road", room="EN")

    assert f"<@{ALICE}>" not in " ".join(halloween.posted[before:])


async def test_they_are_taken_out_of_the_entryway_thread(built):
    await go(built)

    await go(built, "road", room="EN")

    assert ALICE in thread(built, "Entryway").removed_users


async def test_nobody_is_removed_from_the_channel(built):
    """It is the one place where being able to read it is not a claim about
    where you are standing - and nobody can be removed from it anyway."""
    _, _, halloween, _ = built

    await go(built)

    assert not getattr(halloween, "removed_users", [])


async def test_the_front_door_is_ungated_too(built):
    """Leaving is always allowed. The feeding gate the Entryway's other
    exits will carry is there to stop a player being handed nine rooms at
    once, and stepping outside cannot overwhelm anybody."""
    row = next(
        t for t in content_module.load_files().things if t.thing_id == world.FRONT_DOOR
    )

    assert not row.requires
    assert world.FRONT_DOOR in world.UNGATED_EXITS


async def test_the_road_is_nobody_s_unlocked_room(built):
    """A row saying somebody has unlocked the channel would be a row no
    question ever asks."""
    db, *_ = built
    await go(built)

    await go(built, "road", room="EN")

    assert "CH" not in (await db.get_game_state(ALICE, GUILD_A)).rooms_unlocked


# --------------------------------------------------------------------------
# `/go`, which is new
# --------------------------------------------------------------------------


async def test_go_by_the_name_of_the_way_out(built):
    db, *_ = built
    await go(built)
    await fed(built)

    await go(built, "wide doorway", room="EN")

    assert await where(db) == "LI"


async def test_go_by_the_name_of_the_room_it_leads_to(built):
    """**The half `/use` answers badly.** The name of the doorway is
    something a player has to read the prose to learn; the room behind it is
    on the map in their head."""
    db, *_ = built
    await go(built)
    await fed(built)

    await go(built, "living room", room="EN")

    assert await where(db) == "LI"


async def test_a_thing_that_is_not_a_way_out_says_so_in_its_own_words(built):
    """The disguised-exit rule, which is why this is the thing's own line
    and not a refusal of `/go`'s: a cabinet that happens to be a door has to
    read exactly like a cabinet that is not."""
    db, *_ = built
    await go(built)

    interaction = await go(built, "coat rack", room="EN")

    # The coat rack has no `use_fail` of its own, so `go_fail.default`.
    assert "That isn't a place you can go." in replies(interaction)
    assert await where(db) == "EN"


async def test_a_disguised_exit_answers_in_its_own_words_instead(built):
    """**The order the fallback sits behind.** The cabinet is a real way
    into the Secret Library, shut until the player has the key - and the
    refusal a player reads has to be the cabinet's own, because
    `go_fail.default` on a thing that is secretly a door would mark out
    every thing that is not."""
    db, *_ = built
    await go(built)
    await fed(built)
    await go(built, "living room", room="EN")

    interaction = await go(built, "curiosity cabinet", room="LI")

    reply = replies(interaction)
    assert "That isn't a place you can go." not in reply
    assert reply.strip()
    assert await where(db) == "LI"


async def test_a_word_the_house_has_never_heard_of(built):
    db, *_ = built
    await go(built)

    interaction = await go(built, "dungeon", room="EN")

    assert "don't see a dungeon here" in replies(interaction)
    assert await where(db) == "EN"


async def test_the_secret_library_cannot_be_named(built):
    """It has to fail **exactly** the way a dungeon fails, or the refusal is
    the thing that gives the room away."""
    db, *_ = built
    await go(built)
    await walk_to_the_courtyard(built)

    named = replies(await go(built, "secret library", room="CO"))
    invented = replies(await go(built, "dungeon", room="CO"))

    assert named.replace("secret library", "dungeon") == invented
    assert await where(db) == "CO"


async def test_but_the_oak_is_still_climbable_by_its_own_name(built):
    """The room is a secret; the tree in the courtyard is in the prose."""
    db, *_ = built
    await go(built)
    await walk_to_the_courtyard(built)

    await go(built, "oak tree", room="CO")

    assert await where(db) == "SE"


async def test_go_before_the_house_arrives(built):
    """Drop 3. The exit exists in the content and has not arrived, which is
    the same answer as a word nobody wrote."""
    db, *_ = built
    await resolve.set_current_drop(GUILD_A, 3)

    interaction = await go(built)

    assert "don't see a house here" in replies(interaction)
    assert await where(db) is None


# --------------------------------------------------------------------------
# The hint that teaches the door
# --------------------------------------------------------------------------


async def fluffed(who=ALICE):
    await database.award_player_achievement(GUILD_A, who, "fluffed_to_perfection")


async def look_at_the_house(built, who=ALICE):
    _, guild, halloween, _ = built
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await bot.look.callback(interaction, "house")
    return replies(interaction)


async def test_looking_at_the_house_points_at_the_way_in(built):
    """**The rail is how the house is taught now.** `#welcome` told every
    new player to run `/enter`, and there is no `/enter`."""
    await fluffed()

    assert "/go house" in await look_at_the_house(built)


async def test_a_player_who_has_not_fluffed_the_bed_is_not_told(built):
    """They are still on drop 1's lesson, and a second place to go is one
    thing too many."""
    assert "/go house" not in await look_at_the_house(built)


async def test_the_hint_is_given_once(built):
    await fluffed()
    assert "/go house" in await look_at_the_house(built)

    assert "/go house" not in await look_at_the_house(built)


async def test_a_player_who_found_the_door_themselves_is_never_told(built):
    """The rail's one invariant: never recommend an action the player has
    already taken."""
    await fluffed()
    await go(built)
    await go(built, "road", room="EN")

    assert "/go house" not in await look_at_the_house(built)


async def test_arriving_inside_points_at_the_way_back_out(built):
    """**The lesson the tutorial was carrying**, and the one the rail could
    not give before drop 10: there was no exit anywhere to teach movement
    on. It rides the private line that says they are inside, which is the
    message they were getting anyway."""
    interaction = await go(built)

    assert "If you want to leave again" in replies(interaction)
    assert "/go road" in replies(interaction)


async def test_it_matters_because_the_bed_is_outside(built):
    """Not a tidiness hint. The bed and the toys stay in the channel, so a
    player who cannot find the way out loses the daily fluff - which is the
    whole relationship engine at this drop."""
    assert any(
        t.room_id == content_module.CHANNEL_ROOM
        for t in content_module.load_files().things
        if t.thing_id == world.CAT_BED
    )


async def test_the_way_out_is_pointed_at_once(built):
    assert "If you want to leave again" in replies(await go(built))
    await go(built, "road", room="EN")

    assert "If you want to leave again" not in replies(await go(built))


async def test_a_player_who_has_already_left_is_not_told_how(built):
    """The rail's one invariant, on the other door this time: a player who
    walked out before the hint ever fired is not advised to walk out."""
    await go(built)
    await go(built, "front door", room="EN")

    assert "If you want to leave again" not in replies(await go(built))


async def test_the_hint_waits_for_the_drop(built):
    """Two gates, both the drop in the rail's own terms: `/go` is drop 10's
    command and the house is drop 10's thing."""
    await resolve.set_current_drop(GUILD_A, 3)
    await fluffed()

    assert not await hints.reachable(GUILD_A, hints.GO_HOUSE)


# --------------------------------------------------------------------------
# Going in and out is going somewhere
# --------------------------------------------------------------------------


async def test_in_and_out_five_times_is_a_little_bit_lost(built):
    """The road counts as a room, which is what moving this achievement to
    drop 10 means: with one room in the house and one outside it, the only
    way to arrive anywhere five times is the front door."""
    db, *_ = built

    for _ in range(5):
        await go(built)
        await go(built, "road", room="EN")

    assert "a_little_bit_lost" in await db.player_achievements_of(GUILD_A, ALICE)


async def test_a_move_writes_one_row_and_names_both_ends(built):
    """One row per move, and not also a `use`: two rows for one event is how
    a count ends up doubled."""
    db, *_ = built

    await go(built)

    rows = [r for r in await logged(db) if r.action != database.HINT]

    assert [(r.action, r.outcome, r.detail) for r in rows] == [
        (database.MOVE, database.SUCCESS, "from=CH to=EN")
    ]


# --------------------------------------------------------------------------
# On deploy
# --------------------------------------------------------------------------


async def test_a_player_in_a_room_this_server_has_not_reached_comes_outside(built):
    """A drop renumbered under a running server, or a row written by a build
    two deploys old. Out on the road is the one place that is always there."""
    db, *_ = built
    await go(built)
    await db.update_current_room(ALICE, GUILD_A, "SE")
    await resolve.set_current_drop(GUILD_A, HOUSE_DROP)

    moved = await bot._send_everybody_somewhere_real(GUILD_A)

    assert moved == 1
    assert await where(db) == "CH"


async def test_a_player_in_a_room_that_has_arrived_is_left_where_they_are(built):
    db, *_ = built
    await go(built)
    await resolve.set_current_drop(GUILD_A, HOUSE_DROP)

    assert await bot._send_everybody_somewhere_real(GUILD_A) == 0
    assert await where(db) == "EN"


async def test_somebody_already_on_the_road_is_left_alone(built):
    db, *_ = built
    await go(built)
    await go(built, "road", room="EN")

    assert await bot._send_everybody_somewhere_real(GUILD_A) == 0
    assert await where(db) == "CH"


async def test_the_entryway_is_somewhere_from_the_drop_it_arrives_on(built):
    """The rule is the room's text rather than a drop written on the room:
    `rooms.tsv` has no drop column, and a room nobody can read the prose of
    is not somewhere to stand."""
    await resolve.set_current_drop(GUILD_A, 3)
    assert "EN" not in await resolve.arrived_rooms(GUILD_A)

    await resolve.set_current_drop(GUILD_A, HOUSE_DROP)
    assert "EN" in await resolve.arrived_rooms(GUILD_A)
