"""Drop 30: the kitchen trash can, which is three mechanics on one fixture.

`/use trash can` opens a private menu and moves things from the bag into
the can. Anybody can `/take` them back out, like any container. `/take
trash can` takes the bag to the curb: everything the house can make more
of is gone for good, and anything one-of-a-kind finds its way back into
the house somewhere else.

**Why "can the house make another one" is the test.** Not whether the
thing is precious. Cat food, candy, spice jars, bottles, diapers, toys,
herbs and pieces of wasp nest all arrive again, so a bag of them going
out costs the server nothing and the joke lands. The cat collar, the
music box, the silver spoon, the candle stub and the brass key arrive
once ever - and the key is the sharp end of it: before the front door
opens, throwing the only one away would lock a server out of its own
house until the cat bed happened to drop another.

**Why the room is told so little.** Something was thrown away; somebody
went through the trash and came out with something; somebody took the
trash out. None of the three says what, which is what makes going and
looking in the bin worth doing.

**What is not tested here.** The 25-option cap has a test, and paging
does not exist: a bag with more kinds than that shows the first 25 and
says so. Sixteen spice jars are one kind, not sixteen.
"""

import pytest
from datetime import date
from types import SimpleNamespace

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
import resolve
import states
import triggers
import world


THIS_DROP = 30
KITCHEN = "KI"

MENU = "You step on the pedal and the lid swings up"
NOTHING = "You have nothing to throw away"
HOW_MANY = "How many go in?"
THREW_ONE = "and the lid swings shut"
THREW_PUBLIC = "steps on the pedal and drops something in the trash"
FISHED_OUT = "out of the trash. It seems fine"
FISHED_PUBLIC = "goes through the trash and comes out with something"
WENT_TO_THE_CURB = "carry it out to the curb"
CLINK = "clinks against the steps"
BAG_WAS_EMPTY = "coffee grounds and a banana peel"
CURB_PUBLIC = "takes the trash out to the curb"
TOO_MUCH = "more in your bag than you can rummage through"
NOT_A_NUMBER = "isn't a number you can throw away"


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
async def kitchen(db):
    """Drop 30, the door open, Alice and Bob fed and in the Kitchen.

    The drop goes in before the load and the load is told the guild, for
    the reason `test_the_ladder` spells out: the loader places stock
    into the servers it has heard of, and it hears about them from
    `users`.
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
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    for who in (ALICE, BOB):
        await db.start_game(who, GUILD_A, KITCHEN, await resolve.rooms_open_at_launch())
        await db.notice(GUILD_A, who, content_module.FED_THE_CAT)
    return db, guild, halloween, rooms


def place(kitchen, room=KITCHEN):
    _, _, halloween, rooms = kitchen
    return next(t for t in halloween.threads if t.name == rooms[room])


async def run(kitchen, command, arg=None, *, room=KITCHEN, who=ALICE):
    db, guild, _, _ = kitchen
    await db.update_current_room(who, GUILD_A, room)
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=place(kitchen, room))
    args = () if arg is None else (arg,)
    await command.callback(interaction, *args)
    return interaction


def replies(interaction) -> str:
    """Everything sent privately, in order."""
    return "\n".join(text for text, _ in interaction.sent if text)


def shown(interaction) -> str:
    """What a component replaced the message with."""
    return "\n".join(str(edit.get("content") or "") for edit in interaction.edited)


def posted(kitchen, room=KITCHEN) -> str:
    return "\n".join(place(kitchen, room).posted)


async def carry(db, thing_id, count=1, who=ALICE):
    async with db._require_session()() as session:
        session.add(
            database.PlayerInventory(
                guild_id=GUILD_A, user_id=who, thing_id=thing_id, count=count
            )
        )
        await session.commit()


async def in_the_can(room=KITCHEN) -> dict:
    """What is in the bin, by thing id."""
    rows = await database.loose_here(GUILD_A, room, world.TRASH_CAN)
    return dict(rows)


async def open_the_lid(kitchen, who=ALICE):
    return await run(kitchen, bot.use, "trash can", who=who)


def view_of(interaction):
    return interaction.sent[-1][1]["view"]


def item_of(interaction, index=0):
    return view_of(interaction).children[index]


async def pick(kitchen, control, chosen=None, *, who=ALICE, text=None):
    """Click a control the way Discord would, with a message behind it.

    `chosen` is what a select was set to; `text` is what was typed into
    a modal. Both are written into the component's own storage, which is
    the only way in - `Select.values` and `TextInput.value` are
    read-only properties over `_values` and `_value`.
    """
    _, guild, _, _ = kitchen
    interaction = FakeInteraction(
        who,
        GUILD_A,
        guild=guild,
        channel=place(kitchen),
        message=SimpleNamespace(id=7),
    )
    if chosen is not None:
        control._values = list(chosen)
    if text is not None:
        control.amount._value = text
        await control.on_submit(interaction)
        return interaction
    await control.callback(interaction)
    return interaction


async def throw_away(kitchen, thing_id, who=ALICE):
    """The shortest path: open the lid and pick one thing."""
    menu = await open_the_lid(kitchen, who=who)
    return await pick(kitchen, item_of(menu), [thing_id], who=who)


# --------------------------------------------------------------------------
# The lid goes up
# --------------------------------------------------------------------------


async def test_an_empty_bag_gets_the_writers_own_line(kitchen):
    """Not an empty menu. A select with no options is a Discord error,
    and the deck has a sentence for exactly this."""
    reply = replies(await open_the_lid(kitchen))

    assert NOTHING in reply


async def test_the_menu_lists_what_is_in_the_bag(kitchen):
    db, *_ = kitchen
    await carry(db, "cat_food_salmon", 2)
    await carry(db, "candle_stub")

    menu = await open_the_lid(kitchen)

    assert MENU in replies(menu)
    assert {o.value for o in item_of(menu).options} == {
        "cat_food_salmon",
        "candle_stub",
    }


async def test_a_count_rides_the_label(kitchen):
    """In the label rather than in the prompt: the prompt is the
    writers' sentence about stepping on the pedal, and a list of what is
    in somebody's bag does not belong in it."""
    db, *_ = kitchen
    await carry(db, "cat_food_salmon", 2)

    menu = await open_the_lid(kitchen)

    assert item_of(menu).options[0].label.endswith("x2")


async def test_nothing_undroppable_is_offered(kitchen):
    """**An option that refuses is worse than one that is not there.**
    Three things in the game cannot leave a player's hands - the
    skeleton key, the carving tools and the ghost's bedsheet - and the
    menu reads `droppable` rather than `takeable` to say so."""
    db, *_ = kitchen
    await carry(db, "skeleton_key")
    await carry(db, "candle_stub")

    menu = await open_the_lid(kitchen)

    assert {o.value for o in item_of(menu).options} == {"candle_stub"}


async def test_a_bag_with_more_kinds_than_the_select_holds_says_so(kitchen):
    """Twenty-five is Discord's limit, and the menu does not page."""
    db, *_ = kitchen
    parsed = content_module.load_files()
    droppable = [
        t.thing_id
        for t in parsed.things
        if t.droppable
        and t.type in content_module.CARRIABLE_TYPES
        # Not the ladder, which never reaches the menu: carrying it
        # blocks `/use` outright, and the test below is that.
        and t.thing_id != world.LADDER
    ]
    assert len(droppable) > bot.TRASH_MENU_LIMIT
    for thing_id in droppable:
        await carry(db, thing_id)

    menu = await open_the_lid(kitchen)

    assert len(item_of(menu).options) == bot.TRASH_MENU_LIMIT
    assert TOO_MUCH in replies(menu)


async def test_the_ladder_never_reaches_the_menu(kitchen):
    """**And needs no rule of its own to keep it out.** `/use trash can`
    is a `/use`, and carrying the ladder refuses every one of those bar
    three - so the one thing in the game nobody should be able to throw
    away is already unthrowable."""
    db, *_ = kitchen
    await carry(db, world.LADDER)

    reply = replies(await open_the_lid(kitchen))

    assert "carrying this ladder" in reply
    assert MENU not in reply


async def test_and_says_nothing_about_it_when_it_fits(kitchen):
    db, *_ = kitchen
    await carry(db, "candle_stub")

    assert TOO_MUCH not in replies(await open_the_lid(kitchen))


# --------------------------------------------------------------------------
# Throwing one thing away
# --------------------------------------------------------------------------


async def test_one_of_something_goes_straight_in(kitchen):
    """**No "how many" for one of something.** The question would have
    one answer, and asking it is a click the player makes to tell the
    game what it already knows."""
    db, *_ = kitchen
    await carry(db, "candle_stub")

    thrown = await throw_away(kitchen, "candle_stub")

    assert THREW_ONE in shown(thrown)
    assert await in_the_can() == {"candle stub": 1}


async def test_and_leaves_the_bag(kitchen):
    db, *_ = kitchen
    await carry(db, "candle_stub")

    await throw_away(kitchen, "candle_stub")

    assert await database.carried_of(ALICE, GUILD_A, "candle_stub") == 0


async def test_the_room_is_told_that_something_went_in(kitchen):
    """And not what, which is the mechanic as much as the copy: the only
    way to find out is to go and look in the bin."""
    db, *_ = kitchen
    await carry(db, "candle_stub")

    await throw_away(kitchen, "candle_stub")

    assert THREW_PUBLIC in posted(kitchen)
    assert "candle" not in posted(kitchen)


async def test_the_lid_stays_open(kitchen):
    """The deck offers *Throw away something else* after every throw, so
    emptying a full bag is one message rather than six commands."""
    db, *_ = kitchen
    await carry(db, "candle_stub")
    await carry(db, "cat_collar")

    thrown = await throw_away(kitchen, "candle_stub")

    again = thrown.edited[-1]["view"]
    assert [item.label for item in again.children] == ["Throw away something else"]


async def test_and_reopens_on_what_is_left(kitchen):
    db, *_ = kitchen
    await carry(db, "candle_stub")
    await carry(db, "cat_collar")
    thrown = await throw_away(kitchen, "candle_stub")

    reopened = await pick(kitchen, thrown.edited[-1]["view"].children[0])

    options = reopened.edited[-1]["view"].children[0].options
    assert {o.value for o in options} == {"cat_collar"}


async def test_and_says_so_when_the_bag_is_empty_now(kitchen):
    db, *_ = kitchen
    await carry(db, "candle_stub")
    thrown = await throw_away(kitchen, "candle_stub")

    reopened = await pick(kitchen, thrown.edited[-1]["view"].children[0])

    assert NOTHING in shown(reopened)


# --------------------------------------------------------------------------
# Throwing several away
# --------------------------------------------------------------------------


async def test_several_of_something_asks_how_many(kitchen):
    db, *_ = kitchen
    await carry(db, "cat_food_salmon", 6)

    asked = await throw_away(kitchen, "cat_food_salmon")

    assert HOW_MANY in shown(asked)
    assert [item.label for item in asked.edited[-1]["view"].children] == [
        "All 6",
        "Some",
    ]


async def test_all_of_them_means_all_of_them(kitchen):
    db, *_ = kitchen
    await carry(db, "cat_food_salmon", 6)
    asked = await throw_away(kitchen, "cat_food_salmon")

    thrown = await pick(kitchen, asked.edited[-1]["view"].children[0])

    assert await in_the_can() == {"salmon cat food": 6}
    assert "6" in shown(thrown)


async def test_some_opens_a_box_to_type_in(kitchen):
    db, *_ = kitchen
    await carry(db, "cat_food_salmon", 6)
    asked = await throw_away(kitchen, "cat_food_salmon")

    clicked = await pick(kitchen, asked.edited[-1]["view"].children[1])

    assert len(clicked.modals) == 1
    assert "salmon cat food" in clicked.modals[0].title


async def test_and_throws_the_number_that_was_typed(kitchen):
    db, *_ = kitchen
    await carry(db, "cat_food_salmon", 6)
    asked = await throw_away(kitchen, "cat_food_salmon")
    clicked = await pick(kitchen, asked.edited[-1]["view"].children[1])

    await pick(kitchen, clicked.modals[0], text="3")

    assert await in_the_can() == {"salmon cat food": 3}
    assert await database.carried_of(ALICE, GUILD_A, "cat_food_salmon") == 3


async def test_a_number_that_is_not_one_is_refused(kitchen):
    """And nothing moves. The line names the range, so the player is
    told what would have worked rather than that they were wrong."""
    db, *_ = kitchen
    await carry(db, "cat_food_salmon", 6)
    asked = await throw_away(kitchen, "cat_food_salmon")
    clicked = await pick(kitchen, asked.edited[-1]["view"].children[1])

    refused = await pick(kitchen, clicked.modals[0], text="nine")

    assert NOT_A_NUMBER in replies(refused)
    assert await in_the_can() == {}


@pytest.mark.parametrize(
    "typed,carried,wanted",
    [
        ("3", 6, 3),
        (" 3 ", 6, 3),
        ("6", 6, 6),
        ("1", 1, 1),
        ("0", 6, None),
        ("-1", 6, None),
        ("7", 6, None),
        ("", 6, None),
        ("three", 6, None),
        ("3.5", 6, None),
    ],
)
def test_what_counts_as_a_number(typed, carried, wanted):
    """The half of the modal worth testing on its own: the rest is
    Discord handing a string to a callback."""
    assert bot._how_many(typed, carried) == wanted


# --------------------------------------------------------------------------
# Fishing something back out
# --------------------------------------------------------------------------


async def test_anybody_can_take_it_back_out(kitchen):
    """Like any container, which is what the shipping box already does -
    so this needed no new code and is asserted for that reason."""
    db, *_ = kitchen
    await carry(db, "candle_stub")
    await throw_away(kitchen, "candle_stub")

    await run(kitchen, bot.take, "candle stub", who=BOB)

    assert await database.carried_of(BOB, GUILD_A, "candle_stub") == 1
    assert await in_the_can() == {}


async def test_it_has_its_own_pair_of_lines(kitchen):
    """**The only take in the game that says anything privately.** Every
    other one is a single third-person sentence to the room, because the
    room and the player want the same words. Here they do not: the
    player gets the state of the thing, and the room gets that somebody
    went through the bin."""
    db, *_ = kitchen
    await carry(db, "candle_stub")
    await throw_away(kitchen, "candle_stub")

    took = await run(kitchen, bot.take, "candle stub", who=BOB)

    assert FISHED_OUT in replies(took)
    assert FISHED_PUBLIC in posted(kitchen)


async def test_the_public_line_does_not_say_what(kitchen):
    db, *_ = kitchen
    await carry(db, "candle_stub")
    await throw_away(kitchen, "candle_stub")
    place(kitchen).posted.clear()

    await run(kitchen, bot.take, "candle stub", who=BOB)

    assert "candle" not in posted(kitchen)


# --------------------------------------------------------------------------
# Trash Panda
# --------------------------------------------------------------------------

TRASH_PANDA = "trash_panda"


async def earned_by(who=ALICE) -> set:
    return set(await database.player_achievements_of(GUILD_A, who))


async def test_the_first_thing_out_of_the_bin_earns_it(kitchen):
    db, *_ = kitchen
    await carry(db, "candle_stub")
    await throw_away(kitchen, "candle_stub")

    await run(kitchen, bot.take, "candle stub", who=BOB)

    assert TRASH_PANDA in await earned_by(BOB)


async def test_somebody_elses_rubbish_counts(kitchen):
    """The file's own wording: *went through the trash and came out with
    something*. Nothing in it asks whose."""
    db, *_ = kitchen
    await carry(db, "candle_stub", who=ALICE)
    await throw_away(kitchen, "candle_stub", who=ALICE)

    await run(kitchen, bot.take, "candle stub", who=BOB)

    assert TRASH_PANDA in await earned_by(BOB)


async def test_picking_the_same_thing_off_the_floor_does_not(kitchen):
    """**Read off the container and not the thing.** Everything that can
    go in the bin can also be picked up off a floor somewhere, so the
    thing id says nothing about whether anybody went through the trash."""
    await database.place_in_room(GUILD_A, KITCHEN, "candle_stub", 1)

    await run(kitchen, bot.take, "candle stub", who=BOB)

    assert TRASH_PANDA not in await earned_by(BOB)


async def test_nor_does_taking_something_out_of_the_shipping_box(kitchen):
    """The other container in the game, and the one this could have been
    confused with: a spice jar out of the box is a delivery being
    unpacked."""
    await run(kitchen, bot.take, "spice jar", room="EN", who=BOB)

    assert TRASH_PANDA not in await earned_by(BOB)


# --------------------------------------------------------------------------
# What being last costs the bin
#
# Pass two ranks a copy in the bin below a source in the same room, so a
# kitchen with a freezer in it never hands anybody a burrito out of the
# rubbish. That was asked for with the cost already weighed, and the cost
# belongs in a test rather than in a comment: a burrito and a can opener
# thrown away stay thrown away, and everything the kitchen cannot make
# another of still comes back out. `test_the_nearest_hand` has the order
# itself.
# --------------------------------------------------------------------------


async def test_a_burrito_in_the_bin_loses_to_the_freezer(kitchen):
    """And the bin keeps it. Nobody picks the rubbish over the groceries,
    and the freezer is inexhaustible."""
    db, *_ = kitchen
    await carry(db, "frozen_burrito")
    await throw_away(kitchen, "frozen_burrito")

    await run(kitchen, bot.take, "burrito")

    assert await database.carried_of(ALICE, GUILD_A, "frozen_burrito") == 1
    assert (await in_the_can()).get("frozen burrito") == 1


async def test_and_that_take_is_not_going_through_the_trash(kitchen):
    """The half a player sees: the ordinary take line, not the bin's, and
    no secret for having opened the lid they did not open."""
    db, *_ = kitchen
    await carry(db, "frozen_burrito")
    await throw_away(kitchen, "frozen_burrito")
    place(kitchen).posted.clear()

    await run(kitchen, bot.take, "burrito", who=BOB)

    assert FISHED_PUBLIC not in posted(kitchen)
    assert TRASH_PANDA not in await earned_by(BOB)


async def test_a_diaper_in_the_bin_still_comes_back_out(kitchen):
    """Nothing in the Kitchen hands out dirty diapers, so the bin is the
    only rung with one on it. This is the case *Trash Panda* needs, and
    the order leaves it exactly where it was."""
    db, *_ = kitchen
    await carry(db, "dirty_diaper")
    await throw_away(kitchen, "dirty_diaper")
    place(kitchen).posted.clear()

    await run(kitchen, bot.take, "diaper", who=BOB)

    assert await database.carried_of(BOB, GUILD_A, "dirty_diaper") == 1
    assert "dirty diaper" not in await in_the_can()
    assert FISHED_PUBLIC in posted(kitchen)
    assert TRASH_PANDA in await earned_by(BOB)


# --------------------------------------------------------------------------
# Taking the bag out
# --------------------------------------------------------------------------


async def test_the_bag_goes_out_and_the_can_is_empty(kitchen):
    db, *_ = kitchen
    await carry(db, "cat_food_salmon", 2)
    asked = await throw_away(kitchen, "cat_food_salmon")
    await pick(kitchen, asked.edited[-1]["view"].children[0])

    took = await run(kitchen, bot.take, "trash can")

    assert WENT_TO_THE_CURB in replies(took)
    assert await in_the_can() == {}


async def test_the_player_stays_in_the_kitchen(kitchen):
    db, *_ = kitchen

    await run(kitchen, bot.take, "trash can")

    assert (await db.get_game_state(ALICE, GUILD_A)).current_room == KITCHEN


async def test_an_empty_bag_goes_out_anyway(kitchen):
    """Somebody has to."""
    took = await run(kitchen, bot.take, "trash can")

    assert BAG_WAS_EMPTY in replies(took)


async def test_the_room_watches_it_go(kitchen):
    await run(kitchen, bot.take, "trash can")

    assert CURB_PUBLIC in posted(kitchen)


async def test_the_bag_answers_to_its_own_name(kitchen):
    """The writers added *trash bag* and *garbage bag* as aliases so
    `/take trash bag` reads as taking the bag out rather than as trying
    to pocket a bin."""
    took = await run(kitchen, bot.take, "trash bag")

    assert BAG_WAS_EMPTY in replies(took)


# --------------------------------------------------------------------------
# What survives the curb
# --------------------------------------------------------------------------


async def everywhere_but_the_can() -> dict:
    """Every container in the house and what is in it, bar the bin."""
    found = {}
    for room_id, container in await world.places_to_put_things_back(GUILD_A):
        for name, count in await database.loose_here(GUILD_A, room_id, container):
            found[name] = (room_id, container, count)
    return found


async def test_what_the_house_can_make_more_of_is_gone(kitchen):
    db, *_ = kitchen
    await carry(db, "cat_food_salmon", 2)
    asked = await throw_away(kitchen, "cat_food_salmon")
    await pick(kitchen, asked.edited[-1]["view"].children[0])

    await run(kitchen, bot.take, "trash can")

    assert "salmon cat food" not in await everywhere_but_the_can()


async def test_a_toy_counts_as_something_the_house_makes(kitchen):
    """**The one thing whose renewability is written as a class.** The
    restock row names `type:toy` rather than a thing id, so nothing in
    the content says a crinkle ball in particular comes back - the
    prefix has to be expanded before the question can be answered, and
    a toy is the only kind of thing that turns on it.

    Unexpanded, a toy reads as one-of-a-kind and the bin would put it
    back in the house instead of deleting it. Which it would do
    silently: a toy appearing in a cupboard is exactly what the
    scheduler does anyway.
    """
    db, *_ = kitchen
    await carry(db, "crinkle_ball")
    await throw_away(kitchen, "crinkle_ball")

    await run(kitchen, bot.take, "trash can")

    assert "crinkle ball" not in await everywhere_but_the_can()


async def test_a_one_of_a_kind_thing_goes_back_into_the_house(kitchen):
    db, *_ = kitchen
    await carry(db, "cat_collar")
    await throw_away(kitchen, "cat_collar")

    await run(kitchen, bot.take, "trash can")

    assert "cat collar" in await everywhere_but_the_can()


async def test_and_into_a_container_rather_than_onto_a_floor(kitchen):
    """**The clink is the whole of the hint.** A music box lying in the
    middle of the Entryway would be found by the next person to type
    `/look`; tucked inside something, it has to be searched for."""
    db, *_ = kitchen
    await carry(db, "music_box")
    await throw_away(kitchen, "music_box")

    await run(kitchen, bot.take, "trash can")

    _, container, _ = (await everywhere_but_the_can())["music box"]
    assert container and container != database.LOOSE_IN_ROOM


async def test_never_back_into_the_trash_can(kitchen):
    db, *_ = kitchen
    await carry(db, "cat_collar")
    await throw_away(kitchen, "cat_collar")

    await run(kitchen, bot.take, "trash can")

    assert await in_the_can() == {}


async def test_never_into_the_secret_library(kitchen):
    """A player who has not found it could never get the thing back,
    which would make taking the trash out a way of destroying the one
    thing the bin is not allowed to destroy."""
    for room_id, _ in await world.places_to_put_things_back(GUILD_A):
        assert room_id != "SE"


async def test_nor_into_a_room_whose_drop_has_not_arrived(kitchen):
    """A thing put upstairs at drop 30 is a thing in a room nobody can
    reach."""
    arrived = await resolve.arrived_drop_ids(GUILD_A)
    parsed = content_module.load_files()
    by_id = parsed.things_by_id

    for _, container in await world.places_to_put_things_back(GUILD_A):
        assert by_id[container].since_drop in arrived


async def test_the_brass_key_survives_the_curb(kitchen):
    """**The sharp end of the rule.** Before the front door opens the
    cat bed's spare is the only other key, so throwing the only one away
    would lock a server out of its own house until the bed happened to
    drop another."""
    db, *_ = kitchen
    await carry(db, world.HOUSE_KEY)
    await throw_away(kitchen, world.HOUSE_KEY)

    await run(kitchen, bot.take, "trash can")

    assert "brass key" in str(await everywhere_but_the_can())


async def test_the_clink_only_sounds_when_something_was_kept(kitchen):
    db, *_ = kitchen
    await carry(db, "cat_collar")
    await throw_away(kitchen, "cat_collar")

    took = await run(kitchen, bot.take, "trash can")

    assert CLINK in replies(took)


async def test_and_not_when_the_bag_was_all_rubbish(kitchen):
    db, *_ = kitchen
    await carry(db, "cat_food_salmon")
    await throw_away(kitchen, "cat_food_salmon")

    took = await run(kitchen, bot.take, "trash can")

    assert CLINK not in replies(took)


async def test_the_clink_does_not_say_where(kitchen):
    """The only record of where it went is the log, which is deliberate
    and which the log had better therefore carry."""
    db, *_ = kitchen
    await carry(db, "cat_collar")
    await throw_away(kitchen, "cat_collar")

    took = await run(kitchen, bot.take, "trash can")

    for room_name in ("Entryway", "Dining", "Living", "Courtyard", "Kitchen"):
        assert room_name not in replies(took)


async def test_and_the_log_does(kitchen):
    db, *_ = kitchen
    await carry(db, "cat_collar")
    await throw_away(kitchen, "cat_collar")

    await run(kitchen, bot.take, "trash can")

    async with db._require_session()() as session:
        rows = await session.execute(
            db.select(db.InteractionLog.detail).where(
                db.InteractionLog.guild_id == GUILD_A,
                db.InteractionLog.action == database.TRASH_EMPTIED,
            )
        )
    detail = "\n".join(row[0] or "" for row in rows)
    assert "cat_collar->" in detail


# --------------------------------------------------------------------------
# Bin Looking for You
# --------------------------------------------------------------------------

BIN_LOOKING = "bin_looking_for_you"


async def test_a_diaper_carried_into_the_kitchen_earns_it(kitchen):
    db, *_ = kitchen
    await carry(db, "dirty_diaper")

    await run(kitchen, bot.look)

    assert BIN_LOOKING in await earned_by()


async def test_without_a_diaper_the_chance_is_spent(kitchen):
    """**One chance, ever**, which is what makes it a secret. Walking in
    prints nothing, so that first `/look` is the moment they see the
    trash can - and a player who was not holding one then never gets
    another go."""
    db, *_ = kitchen
    await run(kitchen, bot.look)

    await carry(db, "dirty_diaper")
    await run(kitchen, bot.look)

    assert BIN_LOOKING not in await earned_by()


async def test_looking_at_the_trash_can_is_not_looking_at_the_room(kitchen):
    """A player who typed `/look trash can` has already read the Kitchen,
    so it must neither earn this nor spend the chance."""
    db, *_ = kitchen
    await carry(db, "dirty_diaper")

    await run(kitchen, bot.look, "trash can")

    assert BIN_LOOKING not in await earned_by()

    await run(kitchen, bot.look)
    assert BIN_LOOKING in await earned_by()


async def test_a_first_look_in_another_room_does_nothing(kitchen):
    db, *_ = kitchen
    await carry(db, "dirty_diaper")

    await run(kitchen, bot.look, room="DI")

    assert BIN_LOOKING not in await earned_by()


async def test_the_flag_is_per_player(kitchen):
    """Alice looking spends Alice's chance and nobody else's."""
    db, *_ = kitchen
    await run(kitchen, bot.look, who=ALICE)
    await carry(db, "dirty_diaper", who=BOB)

    await run(kitchen, bot.look, who=BOB)

    assert BIN_LOOKING in await earned_by(BOB)
    assert BIN_LOOKING not in await earned_by(ALICE)


# --------------------------------------------------------------------------
# Curbside Pickup moved hooks
# --------------------------------------------------------------------------


def test_curbside_pickup_watches_the_take_and_not_the_use():
    """`/use trash can` opens the menu now. The trigger moved with the
    mechanic, and `test_triggers` owns the day it fires on."""
    trigger = achievements.trigger_for("curbside_pickup")

    assert trigger.hooks == frozenset({"on_take"})


async def test_taking_the_trash_out_fires_the_take_hook(kitchen):
    """Which is the half this file can assert: the can's own id reaching
    `on_take` is what the date predicate is waiting for."""
    seen = []

    async def spy(context):
        seen.append((context.hook, context.thing_id))
        return False

    achievements.clear()
    achievements.register("curbside_pickup", "on_take", spy)

    await run(kitchen, bot.take, "trash can")

    assert ("on_take", world.TRASH_CAN) in seen
