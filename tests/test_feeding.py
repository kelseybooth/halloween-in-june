"""Drop 10: the cat is fed, and the Entryway opens up.

Three things that are really one thing. **Feeding** is the mechanic the
drop ends in - a can, a bowl, a hungry cat, and four ways to be told no.
**The fragments** are what the first feed buys: until it, the Entryway is
one sentence and its inner doorways do not exist. And **the road** is
where it starts, which now shows the house only to a player with some
reason to know it is there.

They are in one file because they share a flag. `fed_the_cat` is written
by the feed, read by the room text and read again by every move out of
the hall, and a test for any one of the three that stubbed the other two
would be testing the stub.

**What the gate is safe because of**, and the thing to re-check if
anything here is ever relaxed: feeding can always be completed inside the
Entryway. The cat is in every room, the bowl is a fixture on this floor,
and the stash behind the coat tree never runs out. A player behind the
gate is always three commands from being past it, which is why the only
per-player gate on an exit in the game is allowed to exist.
"""

import pytest
from sqlalchemy import select

from conftest import ALICE, BOB, GUILD_A, HOUSE_DROP, LAST_DROP
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
import hints
import reach
import resolve
import states
import triggers
import world


ROOM_SERVICE = "room_service"
PURRSUASIVE = "persuasive"


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.register_all()
    triggers.forget_arrivals()
    yield
    achievements.clear()


@pytest.fixture(autouse=True)
def forget_admissions():
    """`test_wrong_place`'s fixture, for the same reason: the fake's thread
    ids hash the room name, so an admission left behind outlives its test."""
    bot._ADMITTING.clear()
    yield
    bot._ADMITTING.clear()


@pytest.fixture
async def house(db):
    """The whole house built, and Alice standing in the Entryway, unfed."""
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
    await db.start_game(ALICE, GUILD_A, "EN", await resolve.rooms_open_at_launch())
    return db, guild, halloween, rooms


def thread(house, room_name):
    _, _, halloween, _ = house
    return next(t for t in halloween.threads if t.name == room_name)


async def run(house, command, arg=None, *, room="EN", who=ALICE):
    """One command, typed in a room's own thread, or in the channel."""
    _, guild, halloween, rooms = house
    channel = halloween if room == "CH" else thread(house, rooms[room])
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=channel)
    args = () if arg is None else (arg,)
    await command.callback(interaction, *args)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


async def take_a_can(house, room="EN", who=ALICE):
    """A can in the bag, which is what `/use` needs. Drawn the way a player
    draws one, so the stash and its `contained_in` are exercised too."""
    return await run(house, bot.take, "salmon", room=room, who=who)


async def feed(house, room="EN", who=ALICE):
    return await run(house, bot.use, "salmon", room=room, who=who)


async def on_the_road(house, who=ALICE):
    """Standing outside, which is the only other place a can can be used.

    Her body has to be there, not just the command: the place check has
    been the rule since the threads became rooms.
    """
    db, *_ = house
    await db.update_current_room(who, GUILD_A, "CH")


async def a_day_later(db):
    """The clock offset, which is whole days - the hunger window is eight
    hours, so one day is the smallest move that clears it."""
    await db.set_setting(GUILD_A, database.CLOCK_KEY, 1)


async def stamped(db, who=ALICE):
    """This player's `last_cat_interaction_date`, which the drift reads."""
    session_factory = db._require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(db.User.last_cat_interaction_date).where(
                db.User.id == who, db.User.guild_id == GUILD_A
            )
        )


async def logged(db, action, who=ALICE):
    session_factory = db._require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(db.InteractionLog)
            .where(
                db.InteractionLog.guild_id == GUILD_A,
                db.InteractionLog.user_id == who,
                db.InteractionLog.action == action,
            )
            .order_by(db.InteractionLog.id)
        )
        return list(rows.scalars())


# --------------------------------------------------------------------------
# Finding the food
# --------------------------------------------------------------------------


async def test_the_coat_tree_is_where_the_salmon_is(house):
    """**Drop 10's one lesson**: a description conceals a findable thing.
    The stash is named nowhere else, so a player who does not read this
    has nothing to feed her with."""
    reply = replies(await run(house, bot.look, "coat tree"))

    assert "salmon cat food" in reply


async def test_the_old_name_still_answers(house):
    """`coat_rack` was renamed to *coat tree* and kept its id. A playtester
    who learned the old word a drop ago types the old word."""
    reply = replies(await run(house, bot.look, "coat rack"))

    assert "bentwood coat tree" in reply


async def test_taking_the_salmon_gives_a_can(house):
    db, *_ = house

    await take_a_can(house)

    assert await db.carried_of(ALICE, GUILD_A, "cat_food_salmon") == 1


async def test_the_stash_never_runs_out(house):
    """A source, so the quest cannot be failed by somebody else's hoarding
    - which matters more here than anywhere, because the gate on the rest
    of the house is downstream of it."""
    db, *_ = house

    for _ in range(3):
        await take_a_can(house)

    assert await db.carried_of(ALICE, GUILD_A, "cat_food_salmon") == 3


async def test_the_bowl_is_in_the_first_fragment(house):
    """Not hidden, and deliberately not: the salmon is the thing to find,
    and the bowl is what tells a player there is something to look for."""
    reply = replies(await run(house, bot.look))

    assert "bowl" in reply


async def test_an_empty_bowl_asks_for_a_can(house):
    """Its refusal doubles as the quest's hint rail - it names the noun
    without naming where the noun is."""
    reply = replies(await run(house, bot.use, "bowl"))

    assert "that takes a can" in reply


# --------------------------------------------------------------------------
# The feed itself
# --------------------------------------------------------------------------


async def test_feeding_her_works_in_the_entryway(house):
    db, *_ = house
    await take_a_can(house)

    reply = replies(await feed(house))

    assert "hook a finger through the ring" in reply
    assert await db.carried_of(ALICE, GUILD_A, "cat_food_salmon") == 0


async def test_a_feed_is_worth_ten(house):
    db, *_ = house
    await take_a_can(house)

    await feed(house)

    assert await db.get_relationship(ALICE, GUILD_A) == world.FEED_POINTS


async def test_the_room_sees_it(house):
    """One line in `defaults.tsv` rather than one per flavor: the room sees
    that she was fed, not what out of."""
    await take_a_can(house)

    await feed(house)

    posted = "\n".join(thread(house, "Entryway").posted)
    assert "fed the cat. Finally." in posted


async def test_the_first_feed_earns_room_service(house):
    db, *_ = house
    await take_a_can(house)

    await feed(house)

    assert ROOM_SERVICE in await db.player_achievements_of(GUILD_A, ALICE)


async def test_the_first_feed_writes_the_flag(house):
    db, *_ = house
    await take_a_can(house)

    await feed(house)

    assert await db.has_been_told(GUILD_A, ALICE, content_module.FED_THE_CAT)


async def test_the_first_feed_says_the_room_opened(house):
    """`en_settles`, which is the Entryway's `channel.fog_thins`: the one
    line that reports the gate flipping."""
    await take_a_can(house)

    reply = replies(await feed(house))

    assert "when you look up you notice more of the room" in reply


async def test_and_says_it_exactly_once(house):
    """Written on the transition, so the second feed is an ordinary feed."""
    db, *_ = house
    await take_a_can(house)
    await feed(house)
    await a_day_later(db)
    await take_a_can(house)

    reply = replies(await feed(house))

    assert "notice more of the room" not in reply


async def test_a_drop_10_server_is_not_told_the_room_opened(house):
    """**The line describes a room that has not shipped yet.**

    Every gated fragment of the Entryway is written for drop 20. A
    drop-10 server flips `fed_the_cat` and the foyer goes on reading
    as one sentence - so telling the player they look up and notice
    more of the room sends them to a `/look` that shows them exactly
    what they had already read, and makes the game look broken at the
    one moment it is trying to feel generous.

    The feed itself is untouched: the flag is written, the quest is
    earned, the room still sees it. Only the sentence about the
    sentences waits.
    """
    db, *_ = house
    await resolve.set_current_drop(GUILD_A, HOUSE_DROP)
    await take_a_can(house)

    reply = replies(await feed(house))

    assert await db.has_been_told(GUILD_A, ALICE, content_module.FED_THE_CAT)
    assert "notice more of the room" not in reply


async def test_what_decides_is_the_room_and_not_a_drop_number(house):
    """**The same server, the same feed, one drop apart.**

    This is the whole reason the condition is a question put to the
    room rather than `drop > 10` written in `bot.py`. The fragments
    are content and content moves: a writer who brings the mirror
    forward to drop 10, or pushes the doorways back to 30, changes
    when this line is true, and nothing in the code has to be found
    and edited to match.
    """
    await resolve.set_current_drop(GUILD_A, HOUSE_DROP)
    quiet = await resolve.gate_reveals_more(
        GUILD_A, "EN", content_module.FED_THE_CAT
    )

    await resolve.set_current_drop(GUILD_A, 20)
    opened = await resolve.gate_reveals_more(
        GUILD_A, "EN", content_module.FED_THE_CAT
    )

    assert not quiet
    assert opened


async def test_the_gate_counts_even_when_the_player_already_holds_it(house):
    """**Asked after the flag is written, which is when it is asked.**

    The feed writes `fed_the_cat` before the reply is composed, so the
    gates the caller is holding already contain it. Reading the room
    twice with that set unchanged would compare it against itself and
    report that nothing opened, which is the bug this discounting
    exists to avoid - and it would have passed every test above,
    because "say nothing" is also what a drop-10 server wants.
    """
    held = frozenset({content_module.FED_THE_CAT})

    assert await resolve.gate_reveals_more(
        GUILD_A, "EN", content_module.FED_THE_CAT, unlocked=held
    )


async def test_the_expired_can_is_not_a_feed(house):
    """It is in `CAT_FOOD` and not in `FEEDS`, and every question about a
    meal reads the second one. She will not eat it, so it must not earn the
    quest, open the room or satisfy her hunger."""
    assert "cat_food_expired" in world.CAT_FOOD
    assert "cat_food_expired" not in world.FEEDS


# --------------------------------------------------------------------------
# The four ways to be told no
# --------------------------------------------------------------------------


async def test_feeding_a_sated_cat_is_refused(house):
    await take_a_can(house)
    await feed(house)
    await take_a_can(house)

    reply = replies(await feed(house))

    assert "isn't hungry yet" in reply


async def test_a_refused_feed_keeps_the_can(house):
    """Losing a can to a cat who was not hungry reads as a bug, and is the
    kind of thing players remember."""
    db, *_ = house
    await take_a_can(house)
    await feed(house)
    await take_a_can(house)

    await feed(house)

    assert await db.carried_of(ALICE, GUILD_A, "cat_food_salmon") == 1


async def test_a_refused_feed_does_not_reset_her_hunger(house):
    """Otherwise a player could hold her off forever by offering food she
    had already turned down."""
    db, *_ = house
    await take_a_can(house)
    await feed(house)
    first = await db.last_used_any(ALICE, GUILD_A, world.FEEDS)

    await take_a_can(house)
    await feed(house)

    assert await db.last_used_any(ALICE, GUILD_A, world.FEEDS) == first


async def test_a_refused_feed_still_counts_as_turning_up(house):
    """*Attempts, not just successes* is settled for the nightly drift.
    Offering food to a cat who will not eat is showing up.

    She is sated here by a `thing_uses` row written directly rather than
    by a feed, because a feed would have stamped the date itself and the
    test would pass without the refusal doing anything.
    """
    db, *_ = house
    await db.record_use(ALICE, GUILD_A, "cat_food_salmon")
    await take_a_can(house)
    assert await stamped(db) is None

    await feed(house)

    assert await stamped(db) == await db.server_today(GUILD_A)


async def test_she_is_hungry_again_the_next_day(house):
    db, *_ = house
    await take_a_can(house)
    await feed(house)
    await a_day_later(db)
    await take_a_can(house)

    reply = replies(await feed(house))

    assert "hook a finger through the ring" in reply


async def test_a_hungry_cat_and_no_bowl_gets_the_cans_own_refusal(house):
    """Everywhere but the Entryway, which is everywhere the bowl is not."""
    await take_a_can(house)
    await on_the_road(house)

    reply = replies(await run(house, bot.use, "salmon", room="CH"))

    assert "pour it on the floor" in reply


async def test_a_sated_cat_and_no_bowl_is_wrong_twice_over(house):
    """**Hunger is read first**, so this is the not-hungry answer rather
    than the no-bowl one - with a line that says both."""
    await take_a_can(house)
    await feed(house)
    await take_a_can(house)
    await on_the_road(house)

    reply = replies(await run(house, bot.use, "salmon", room="CH"))

    assert "neither the right time nor the right place" in reply


async def test_the_bowl_is_met_from_the_room_not_the_bag(house):
    """`requires` used to mean "in your bag". A floor fixture nobody can
    pocket would have made feeding impossible under that reading."""
    db, *_ = house
    await take_a_can(house)

    assert await db.carried_of(ALICE, GUILD_A, "cat_bowl") == 0
    assert "hook a finger" in replies(await feed(house))


async def test_a_takeable_requirement_still_has_to_be_carried(house):
    """The can opener, which is the rule that did not move: the opener is on
    its hook in this room and still has to be in your hand.

    The can is picked up in the dining room and carried in, because the tuna
    moved to the sideboard on 30 October. That makes the point harder rather
    than softer - the player is standing with the opener in reach and the
    refusal still comes - where before it only showed that being in the
    pantry was not enough.
    """
    db, *_ = house
    await db.update_current_room(ALICE, GUILD_A, "DI")
    await run(house, bot.take, "tuna", room="DI")
    await db.update_current_room(ALICE, GUILD_A, "KI")

    reply = replies(await run(house, bot.use, "tuna", room="KI"))

    assert "looking for a pull-tab" in reply


# --------------------------------------------------------------------------
# What the log says
# --------------------------------------------------------------------------


async def test_a_feed_is_logged_as_a_feed(house):
    db, *_ = house
    await take_a_can(house)

    await feed(house)

    rows = await logged(db, database.FEED)
    assert [(r.outcome, r.thing_id, r.relationship_delta) for r in rows] == [
        (database.SUCCESS, "cat_food_salmon", world.FEED_POINTS)
    ]


async def test_and_not_also_as_a_use(house):
    """Two rows for one event is how a count ends up doubled."""
    db, *_ = house
    await take_a_can(house)

    await feed(house)

    assert [r.thing_id for r in await logged(db, database.USE)] == []


@pytest.mark.parametrize(
    "room, sated, reason",
    [
        ("EN", True, database.NOT_HUNGRY),
        ("CH", True, database.WRONG_TIME_AND_PLACE),
        ("CH", False, database.NO_BOWL),
    ],
)
async def test_every_refusal_says_why(house, room, sated, reason):
    """Four reasons rather than two, because which one players hit says
    which room they are stuck outside of."""
    db, *_ = house
    if sated:
        await take_a_can(house)
        await feed(house)
    await take_a_can(house)
    if room == "CH":
        await on_the_road(house)

    await run(house, bot.use, "salmon", room=room)

    rows = await logged(db, database.FEED)
    assert rows[-1].outcome == database.REFUSED
    assert rows[-1].reason == reason


async def test_the_opener_and_the_bowl_are_told_apart(house):
    """`can_opener|cat_bowl` names the opener first, so a player in the
    Kitchen with neither hears about the opener.

    The gourmet tin since 30 October, which carries that same requirement
    and stayed in the Kitchen when the tuna moved to the dining room.
    """
    db, *_ = house
    await db.update_current_room(ALICE, GUILD_A, "KI")
    await run(house, bot.take, "gourmet", room="KI")

    await run(house, bot.use, "gourmet", room="KI")

    rows = await logged(db, database.FEED)
    assert rows[-1].reason == database.NO_OPENER


# --------------------------------------------------------------------------
# Twenty-five of them
# --------------------------------------------------------------------------


async def test_bowl_half_empty_counts_every_flavor(house):
    """Off `thing_uses`, like *Tireless*: the interaction log started empty
    on a server that had already been played."""
    db, *_ = house
    for _ in range(triggers.BOWL_HALF_EMPTY_FEEDS - 1):
        await db.record_use(ALICE, GUILD_A, "cat_food_chicken")
    # Those rows stamped her last meal as well as counting it, so she is
    # not hungry until the clock moves.
    await a_day_later(db)
    await take_a_can(house)

    await feed(house)

    assert "bowl_half_empty" in await db.player_achievements_of(GUILD_A, ALICE)


async def test_and_not_before(house):
    db, *_ = house
    for _ in range(5):
        await db.record_use(ALICE, GUILD_A, "cat_food_chicken")
    await a_day_later(db)
    await take_a_can(house)

    await feed(house)

    assert "bowl_half_empty" not in await db.player_achievements_of(GUILD_A, ALICE)


# --------------------------------------------------------------------------
# The room, before and after
# --------------------------------------------------------------------------


async def test_an_unfed_player_sees_one_sentence(house):
    """At the last drop, with everything in the house built. The ceiling is
    fragment 1; the mirror is fragment 2 and gated."""
    reply = replies(await run(house, bot.look))

    assert "water-stained" in reply
    assert "cloudy" not in reply
    assert "Amazon box" not in reply


async def test_feeding_her_opens_the_rest(house):
    await take_a_can(house)
    await feed(house)

    reply = replies(await run(house, bot.look))

    assert "cloudy" in reply
    assert "shipping box" in reply
    assert "arched doorway" in reply


async def test_but_not_the_fragment_that_waits(house):
    """**Fragment 4 names two things that are not built.** Alexa needs a
    notes feature and the bulletin board needs somewhere to pin them, so
    both sit at drop 99 - and a sentence that names only delayed things
    has to wait with them, or the room describes furniture a player
    cannot look at."""
    await take_a_can(house)
    await feed(house)

    reply = replies(await run(house, bot.look))

    assert "bulletin board" not in reply
    assert "smart speaker" not in reply


async def test_the_room_opens_for_that_player_alone(house):
    """Per player by construction, because it is keyed to an act the player
    performs. Bob is standing in the same room and has fed nobody."""
    db, *_ = house
    await db.start_game(BOB, GUILD_A, "EN", await resolve.rooms_open_at_launch())
    await take_a_can(house)
    await feed(house)

    reply = replies(await run(house, bot.look, who=BOB))

    assert "cloudy" not in reply


async def test_a_thing_in_a_hidden_fragment_can_still_be_looked_at(house):
    """**The agreed scope cut.** Only the room text is per-player; a player
    who guesses the mirror before the room opens still sees it."""
    reply = replies(await run(house, bot.look, "mirror"))

    assert "silvering" in reply


async def test_the_doorways_describe_rather_than_name(house):
    """Fragment 6 and the two looks were rewritten so the rooms behind them
    are discovered rather than announced."""
    await take_a_can(house)
    await feed(house)

    arch = replies(await run(house, bot.look, "arched doorway"))

    assert "corner of a long table" in arch
    assert "dining room" not in arch.lower()


# --------------------------------------------------------------------------
# The doorways, which are gated and the front door is not
# --------------------------------------------------------------------------


async def test_an_unfed_player_cannot_go_through_the_arch(house):
    db, *_ = house

    reply = replies(await run(house, bot.go, "arched doorway"))

    # "a arched" is the house's own article, in `use_fail.absent`, and
    # it is what a player typing any vowel-initial word has always got.
    assert "You don't see a arched doorway here." in reply
    assert (await db.get_game_state(ALICE, GUILD_A)).current_room == "EN"


async def test_nor_by_naming_the_room_behind_it(house):
    """The other half, and the one that would have leaked: `/go dining
    room` resolves through the room's name, so skipping the doorway in
    `/look` alone would have left this route open."""
    db, *_ = house

    reply = replies(await run(house, bot.go, "dining room"))

    assert "You don't see a dining room here." in reply
    assert (await db.get_game_state(ALICE, GUILD_A)).current_room == "EN"


async def test_the_refusal_is_the_one_for_a_word_nobody_wrote(house):
    """**Not the doorway's own line and not `go_fail.default`.** Either
    would confirm the arch is there and say only that it will not open,
    which is a locked door rather than a room that has not opened yet."""
    unearned = replies(await run(house, bot.go, "arched doorway"))
    invented = replies(await run(house, bot.go, "trapdoor"))

    assert unearned.replace("arched doorway", "trapdoor") == invented


async def test_using_the_doorway_is_refused_the_same_way(house):
    """`/use` is the older way to walk through a door and still works, so
    the gate cannot live in `/go` alone."""
    db, *_ = house

    reply = replies(await run(house, bot.use, "arched doorway"))

    assert "You don't see a arched doorway here." in reply
    assert (await db.get_game_state(ALICE, GUILD_A)).current_room == "EN"


async def test_the_staircase_is_gated_too(house):
    db, *_ = house

    reply = replies(await run(house, bot.go, "staircase"))

    assert "You don't see a staircase here." in reply


async def test_but_the_front_door_always_opens(house):
    """**The reason the gate is allowed to exist at all is in the Entryway,
    but this is the reason it is not a trap.** Leaving cannot overwhelm
    anybody, and the bed and the toys are out on the road."""
    db, *_ = house

    await run(house, bot.go, "road")

    assert (await db.get_game_state(ALICE, GUILD_A)).current_room == "CH"


async def test_and_a_fed_player_walks_straight_through(house):
    db, *_ = house
    await take_a_can(house)
    await feed(house)

    await run(house, bot.go, "dining room")

    assert (await db.get_game_state(ALICE, GUILD_A)).current_room == "DI"


async def test_no_other_room_is_gated(house):
    """One gate, in one room. The Living Room's doorway back to the hall is
    not conditional on anything."""
    db, *_ = house
    await db.update_current_room(ALICE, GUILD_A, "LI")

    await run(house, bot.go, "entryway", room="LI")

    assert (await db.get_game_state(ALICE, GUILD_A)).current_room == "EN"


# --------------------------------------------------------------------------
# The road, and who can see the house from it
# --------------------------------------------------------------------------


@pytest.fixture
async def road(db):
    """Drop 10, and a player standing on the road with no history."""
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(GUILD_A, channels=[halloween], members=[FakeMember(ALICE)])
    await content_loader.load_content(content_module.load_files())
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, HOUSE_DROP)
    # **Unlocked, because this file is about the door working rather
    # than about the lock on it.** Drop 10 ships the front door shut for
    # the whole server until somebody turns the brass key in it; that is
    # `test_the_locked_door.py`, and a fixture here that kept it shut
    # would make every test below fail on a condition none of them
    # mentions.
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    await db.ensure_user_exists(ALICE, GUILD_A)
    return db, guild, halloween, rooms


async def look_at_the_road(road, who=ALICE):
    _, guild, halloween, _ = road
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await bot.look.callback(interaction, None)
    return replies(interaction)


async def test_the_road_hides_the_house_from_a_stranger(road):
    """Decided 27 October: the fog thins around the house only for players
    who have some reason to know it is there."""
    assert "unlit **house**" not in await look_at_the_road(road)


async def test_purrsuasive_is_how_most_players_get_there(road):
    """The toy achievement, which also means they already know `/look` and
    `/take` - which is why drop 10 ships with no hints of its own."""
    db, *_ = road
    await db.award_player_achievement(GUILD_A, ALICE, PURRSUASIVE)

    assert "unlit **house**" in await look_at_the_road(road)


async def test_so_is_having_looked_at_it(road):
    """Guessing is fine. A player who typed the word has earned the sentence
    as much as one who was told where to look."""
    db, *_ = road
    await hints.did(GUILD_A, ALICE, hints.DID_LOOK_HOUSE)

    assert "unlit **house**" in await look_at_the_road(road)


async def test_looking_at_the_house_is_what_records_it(road):
    """Recorded on the look itself rather than on the hint that sometimes
    rides it: the hint wants *Fluffed to Perfection* and this does not."""
    db, guild, halloween, _ = road
    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    await bot.look.callback(interaction, "house")

    assert await db.has_been_told(GUILD_A, ALICE, hints.DID_LOOK_HOUSE)
    assert "unlit **house**" in await look_at_the_road(road)


async def test_and_so_is_having_been_inside(road):
    db, *_ = road
    await hints.did(GUILD_A, ALICE, hints.DID_GO_HOUSE)

    assert "unlit **house**" in await look_at_the_road(road)


async def test_the_house_is_walkable_whether_or_not_it_is_in_the_prose(road):
    """The gate is on the sentence, not on the door. A player who types
    `/go house` on a hunch gets in."""
    db, guild, halloween, _ = road
    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    await bot.go.callback(interaction, "house")

    assert (await db.get_game_state(ALICE, GUILD_A)).current_room == "EN"
# --------------------------------------------------------------------------
# Three bowls, one requirement
#
# Every cat food's `requires` names `cat_bowl`, which is the Entryway's
# bowl and nothing else. Drop 30 puts one in the Courtyard and drop 40
# one in the Upstairs Hallway, and a player standing beside either of
# them with a can was told to go and find a bowl.
# --------------------------------------------------------------------------


async def test_the_courtyard_bowl_feeds_her_too(house):
    """The payoff, as a player gets it: a can, a bowl, and no trip back
    to the hall."""
    db, *_ = house
    await take_a_can(house)
    await db.update_current_room(ALICE, GUILD_A, "CO")

    reply = replies(await feed(house, room="CO"))

    assert "hook a finger through the ring" in reply


async def test_the_upstairs_bowl_does_as_well(house):
    """Drop 40's, asserted now because the rule is one rule and the row
    is already in the files. A bowl that works downstairs and not up is
    the bug this would be."""
    db, *_ = house
    await take_a_can(house)
    await db.update_current_room(ALICE, GUILD_A, "UH")

    reply = replies(await feed(house, room="UH"))

    assert "hook a finger through the ring" in reply


async def test_the_rule_is_the_name_and_not_the_id(house):
    """Asked of `reach` directly, because that is where it lives and
    because the three rooms above would pass for other reasons.

    The name, deliberately, and not the aliases: aliases overlap across
    unrelated things - the sideboard and the changing table both answer
    to "table" - and a requirement met by a near-synonym is a gate
    opening on a thing nobody meant.
    """
    assert await reach.missing_requirements(GUILD_A, ALICE, "CO", ["cat_bowl"]) == []
    assert await reach.missing_requirements(GUILD_A, ALICE, "UH", ["cat_bowl"]) == []
    assert await reach.missing_requirements(GUILD_A, ALICE, "EN", ["cat_bowl"]) == []


async def test_a_room_with_no_bowl_in_it_still_says_so(house):
    """The half of the widening that could have gone wrong quietly. A
    requirement satisfied from anywhere is not a requirement, and the
    Kitchen is the room a player is most likely to assume has a bowl."""
    assert await reach.missing_requirements(GUILD_A, ALICE, "KI", ["cat_bowl"]) == [
        "cat_bowl"
    ]


async def test_nothing_else_was_widened_with_it(house):
    """The can opener is in the Kitchen and is still the can opener. Three
    things share a name in this house and they are three of the same
    object; a widening that reached further than that would show here."""
    assert await reach.missing_requirements(GUILD_A, ALICE, "CO", ["can_opener"]) == [
        "can_opener"
    ]
