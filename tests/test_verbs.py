"""`/take` and `/drop`, driven through the handlers.

The handlers are thin by design - resolution decides which thing, the refusal
tables decide whether the verb may act, phrasing decides the words - so what is
worth testing here is the wiring between those three, and every refusal being
reachable. The work order asks for exactly that last part: "every one of the
seven new default strings is reachable by a path a test can trigger".
"""

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeInteraction

import bot
import content as content_module
import content_loader
import database
import resolve
from content import TextRow
from test_loader import a_thing
from test_world import a_house, carry


async def enter(db, user_id=ALICE, guild_id=GUILD_A, room="EN"):
    await db.ensure_user_exists(user_id, guild_id)
    await db.start_game(user_id, guild_id, room, ["EN", "KI"])


async def take(user_id=ALICE, guild_id=GUILD_A, thing="spoon"):
    interaction = FakeInteraction(user_id, guild_id)
    await bot.take.callback(interaction, thing)
    return interaction


async def drop(user_id=ALICE, guild_id=GUILD_A, thing="spoon"):
    interaction = FakeInteraction(user_id, guild_id)
    await bot.drop.callback(interaction, thing)
    return interaction


async def bag(user_id=ALICE, guild_id=GUILD_A):
    return dict(await database.get_carried(user_id, guild_id))


@pytest.fixture
async def house(db):
    await enter(db)
    await enter(db, BOB)
    return db


# --------------------------------------------------------------------------
# Taking
# --------------------------------------------------------------------------


async def test_taking_puts_it_in_the_bag(house):
    await content_loader.load_content(a_house(a_thing("spoon", name="spoon")))

    interaction = await take()

    assert await bag() == {"spoon": 1}
    assert "spoon" in interaction.reply


async def test_taking_is_public(house):
    """The room is shared, so the others need to see the last of something go."""
    await content_loader.load_content(a_house(a_thing("spoon")))
    assert (await take()).was_private is False


async def test_the_reply_uses_the_things_own_take_text(house):
    await content_loader.load_content(
        a_house(
            a_thing("spoon", name="spoon"),
            thing_text=[
                TextRow(
                    entity_id="spoon",
                    state="default",
                    since_drop=1,
                    text={"look": "A spoon.", "take": "You pocket it, guiltily."},
                )
            ],
        )
    )
    assert "guiltily" in (await take()).reply


async def test_a_blank_take_cell_falls_through_to_the_house_default(house):
    """Most things have no take text, and that is the intended shape."""
    await content_loader.load_content(a_house(a_thing("spoon", name="spoon")))

    assert (await take()).reply == "You pick up the spoon and tuck it into your bag."


async def test_taking_from_a_source_hands_over_what_it_yields(house):
    await content_loader.load_content(
        a_house(
            a_thing("can", name="tin of beans", room_id=None, quantity=0),
            a_thing("crate", name="crate of beans", aliases=("beans",), type="source",
                    yields="can", takeable=False),
        )
    )

    await take(thing="beans")
    assert await bag() == {"tin of beans": 1}


async def test_a_source_is_not_consumed_by_taking_from_it(house):
    await content_loader.load_content(
        a_house(
            a_thing("can", name="tin of beans", room_id=None, quantity=0),
            a_thing("crate", name="crate of beans", aliases=("beans",), type="source",
                    yields="can", takeable=False),
        )
    )

    for _ in range(3):
        await take(thing="beans")
    assert await bag() == {"tin of beans": 3}


async def test_the_source_reply_uses_the_yielded_objects_text(house):
    """Sources have no take text of their own; the can's is what fires."""
    await content_loader.load_content(
        a_house(
            a_thing("can", name="tin of beans", room_id=None, quantity=0),
            a_thing("crate", name="crate of beans", aliases=("beans",), type="source",
                    yields="can", takeable=False),
            thing_text=[
                TextRow(entity_id="can", state="default", since_drop=1,
                        text={"look": "A tin.", "take": "You take a tin from the crate."}),
                TextRow(entity_id="crate", state="default", since_drop=1,
                        text={"look": "A crate."}),
            ],
        )
    )

    assert "You take a tin from the crate." == (await take(thing="beans")).reply


async def test_taking_the_only_copy_empties_the_room_for_everyone(house):
    await content_loader.load_content(a_house(a_thing("chips", name="chips")))
    await take(thing="chips")

    assert isinstance(
        await __import__("reach").find(GUILD_A, BOB, "EN", "chips", __import__("reach").Scope.ROOM),
        __import__("reach").NotFound,
    )


# --------------------------------------------------------------------------
# Refusing to take
# --------------------------------------------------------------------------


async def test_a_fixture_cannot_be_taken(house):
    await content_loader.load_content(
        a_house(a_thing("fireplace", name="fireplace", type="fixture", takeable=False))
    )

    interaction = await take(thing="fireplace")
    assert "isn't yours to carry off" in interaction.reply
    assert interaction.was_private


async def test_a_fixture_with_its_own_refusal_uses_it(house):
    await content_loader.load_content(
        a_house(
            a_thing("alexa", name="alexa", type="fixture", takeable=False),
            thing_text=[
                TextRow(entity_id="alexa", state="default", since_drop=1,
                        text={"look": "A speaker.", "take_fail": "It seems happy there."})
            ],
        )
    )
    assert "It seems happy there." == (await take(thing="alexa")).reply


async def test_an_exit_cannot_be_put_in_a_bag(house):
    await content_loader.load_content(
        a_house(a_thing("door", name="blue door", type="exit",
                        destination_room_id="KI", takeable=False))
    )
    assert "doorway in your bag" in (await take(thing="blue door")).reply


async def test_max_per_player_refuses_a_second_copy(house):
    await content_loader.load_content(
        a_house(a_thing("key", name="skeleton key", quantity=2, max_per_player=1))
    )

    await take(thing="skeleton key")
    interaction = await take(thing="skeleton key")

    assert await bag() == {"skeleton key": 1}
    assert interaction.was_private


async def test_the_cap_applies_to_what_a_source_yields(house):
    await content_loader.load_content(
        a_house(
            a_thing("key", name="skeleton key", room_id=None, quantity=0, max_per_player=1),
            a_thing("nail", name="ring of keys", aliases=("keys",), type="source",
                    yields="key", takeable=False),
        )
    )

    await take(thing="keys")
    await take(thing="keys")
    assert await bag() == {"skeleton key": 1}


async def test_an_uncapped_thing_can_be_hoarded(house):
    """The bottles are deliberately uncapped; the restock scatter is what
    spreads them, not a limit."""
    await content_loader.load_content(a_house(a_thing("bottle", name="bottle", quantity=6)))

    for _ in range(6):
        await take(thing="bottle")
    assert await bag() == {"bottle": 6}


async def test_taking_something_absent_says_so(house):
    await content_loader.load_content(
        a_house(a_thing("spoon"), a_thing("kettle", name="kettle", room_id="KI"))
    )
    assert "don't see" in (await take(thing="kettle")).reply


async def test_taking_a_word_the_game_does_not_know(house):
    """Its own line. The three verbs used to share one, which meant any
    rewrite had to read sensibly after all of "take", "use" and "look"."""
    await content_loader.load_content(a_house(a_thing("spoon")))
    defaults = content_module.load_files().defaults

    interaction = await take(thing="helicopter")

    assert interaction.reply == defaults["take_fail.unknown"]
    assert interaction.reply != defaults["look_fail.unknown"]


async def test_taking_what_you_already_carry_is_not_called_absent(house):
    """take_fail.absent would be a lie to somebody holding the thing."""
    await content_loader.load_content(a_house(a_thing("spoon", name="spoon", room_id=None, quantity=0)))
    await carry(house, ALICE, GUILD_A, "spoon")

    assert "already carrying" in (await take(thing="spoon")).reply


async def test_an_ambiguous_name_asks_rather_than_guessing(house):
    await content_loader.load_content(
        a_house(
            a_thing("chicken", name="chicken cat food", aliases=("cat food",)),
            a_thing("salmon", name="salmon cat food", aliases=("cat food",)),
        )
    )

    interaction = await take(thing="cat food")
    assert "Which one" in interaction.reply
    assert await bag() == {}


async def test_taking_outside_the_house_is_refused(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await content_loader.load_content(a_house(a_thing("spoon")))

    assert "must be in a room" in (await take()).reply


# --------------------------------------------------------------------------
# Dropping
# --------------------------------------------------------------------------


async def test_dropping_puts_it_back_in_the_room(house):
    await content_loader.load_content(a_house(a_thing("spoon", name="spoon")))
    await take()

    interaction = await drop()
    assert await bag() == {}
    assert "spoon" in interaction.reply


async def test_dropping_is_public(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    await take()
    assert (await drop()).was_private is False


async def test_a_blank_drop_cell_falls_through_to_the_default(house):
    await content_loader.load_content(a_house(a_thing("spoon", name="spoon")))
    await take()

    assert (await drop()).reply == "You set the spoon down."


async def test_dropping_what_you_do_not_have(house):
    await content_loader.load_content(a_house(a_thing("spoon", name="spoon")))
    interaction = await drop()

    assert "aren't carrying" in interaction.reply
    assert interaction.was_private


async def test_an_undroppable_thing_refuses_with_its_own_line(house):
    await content_loader.load_content(
        a_house(
            a_thing("key", name="skeleton key", droppable=False),
            thing_text=[
                TextRow(entity_id="key", state="default", since_drop=1,
                        text={"look": "A key.", "drop_fail": "You'd rather not."})
            ],
        )
    )
    await take(thing="skeleton key")

    interaction = await drop(thing="skeleton key")
    assert interaction.reply == "You'd rather not."
    assert await bag() == {"skeleton key": 1}


async def test_an_undroppable_thing_without_its_own_line_uses_the_default(house):
    await content_loader.load_content(
        a_house(a_thing("key", name="skeleton key", droppable=False))
    )
    await take(thing="skeleton key")

    assert "rather not" in (await drop(thing="skeleton key")).reply


async def test_dropping_is_scoped_to_the_bag(house):
    """Carrying chicken beside the salmon, /drop cat food drops chicken and
    does not ask."""
    await content_loader.load_content(
        a_house(
            a_thing("chicken", name="chicken cat food", aliases=("cat food",),
                    room_id=None, quantity=0),
            a_thing("salmon", name="salmon cat food", aliases=("cat food",)),
        )
    )
    await carry(house, ALICE, GUILD_A, "chicken")

    await drop(thing="cat food")
    assert await bag() == {}


async def test_a_dropped_thing_lands_loose(house):
    """Not back inside the container it came out of."""
    await content_loader.load_content(
        a_house(
            a_thing("box", name="box", type="fixture", takeable=False),
            a_thing("jar", name="spice jar", contained_in="box"),
        )
    )
    await take(thing="spice jar")
    await drop(thing="spice jar")

    from test_loader import contents

    placed = {(row[1], row[3]) for row in await contents(house, GUILD_A)}
    assert placed == {("box", 0), ("", 1)}


async def test_a_thing_can_be_carried_to_another_room_and_left_there(house):
    """Cans of chicken can end up in the Nursery. That is how the house
    accumulates evidence of other players."""
    await content_loader.load_content(a_house(a_thing("spoon", name="spoon")))
    await take()
    await database.update_current_room(ALICE, GUILD_A, "KI")
    await drop()

    from test_loader import contents

    assert ("KI", "", "spoon", 1) in await contents(house, GUILD_A)


# --------------------------------------------------------------------------
# Against the real content
# --------------------------------------------------------------------------


async def test_taking_the_nachos_from_the_kitchen(house):
    await content_loader.load_content(content_module.load_files())
    await database.update_current_room(ALICE, GUILD_A, "KI")

    interaction = await take(thing="nachos")
    assert "nacho" in (await bag()).popitem()[0].lower()
    assert interaction.reply


async def test_the_gourmet_tin_is_capped_at_one(house):
    await content_loader.load_content(content_module.load_files())
    await database.update_current_room(ALICE, GUILD_A, "KI")

    await take(thing="gourmet")
    await take(thing="gourmet")
    assert list((await bag()).values()) == [1]


# --------------------------------------------------------------------------
# /use, four branches
#
# What is deliberately absent: placing a plank counts toward nothing and
# graphite unjams nothing. Both are Phase 2c.5, as is the public reply a plank
# earns. Every /use reply here is private.
# --------------------------------------------------------------------------


async def use(user_id=ALICE, guild_id=GUILD_A, thing="spoon", guild=None):
    # /use guards on interaction.guild before anything else, so a fake needs
    # one even for the branches that never look at a channel.
    from types import SimpleNamespace

    interaction = FakeInteraction(
        user_id, guild_id, guild=guild or SimpleNamespace(name="Test", text_channels=[])
    )
    await bot.use.callback(interaction, thing)
    return interaction


async def uses_of(user_id, guild_id, thing_id):
    from sqlalchemy import select

    async with database._require_session()() as session:
        return await session.scalar(
            select(database.ThingUse.use_count).where(
                database.ThingUse.guild_id == guild_id,
                database.ThingUse.user_id == user_id,
                database.ThingUse.thing_id == thing_id,
            )
        )


async def test_using_an_ordinary_thing_prints_its_use_text(house):
    await content_loader.load_content(
        a_house(
            a_thing("radio", name="radio", type="fixture", takeable=False),
            thing_text=[
                TextRow(
                    entity_id="radio",
                    state="default",
                    since_drop=1,
                    text={"look": "A radio.", "use": "It hisses at you."},
                )
            ],
        )
    )

    interaction = await use(thing="radio")
    assert interaction.reply == "It hisses at you."
    assert interaction.was_private


async def test_a_blank_use_cell_falls_through_to_the_default(house):
    await content_loader.load_content(
        a_house(a_thing("rock", name="rock", type="fixture", takeable=False))
    )
    assert "Nothing obvious happens" in (await use(thing="rock")).reply


async def test_every_successful_use_is_counted_once(house):
    await content_loader.load_content(
        a_house(a_thing("radio", name="radio", type="fixture", takeable=False))
    )

    for expected in range(1, 4):
        await use(thing="radio")
        assert await uses_of(ALICE, GUILD_A, "radio") == expected


async def test_using_something_out_of_reach(house):
    await content_loader.load_content(
        a_house(a_thing("spoon"), a_thing("kettle", name="kettle", room_id="KI"))
    )
    assert "don" in (await use(thing="kettle")).reply


async def test_using_a_word_the_game_does_not_know(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    defaults = content_module.load_files().defaults

    reply = (await use(thing="helicopter")).reply

    assert reply == defaults["use_fail.unknown"]
    assert reply != defaults["take_fail.unknown"]


async def test_an_ambiguous_use_asks(house):
    await content_loader.load_content(
        a_house(
            a_thing("chicken", name="chicken cat food", aliases=("cat food",)),
            a_thing("salmon", name="salmon cat food", aliases=("cat food",)),
        )
    )
    assert "Which one" in (await use(thing="cat food")).reply


# --- the transform branch ---------------------------------------------------


def bottles():
    return a_house(
        a_thing("used", name="used bottle", transforms_to="clean", transform_room="KI"),
        a_thing("clean", name="clean bottle", room_id=None, quantity=0),
        thing_text=[
            TextRow(
                entity_id="used",
                state="default",
                since_drop=1,
                text={
                    "look": "A grubby bottle.",
                    "use": "You scrub it clean.",
                    "use_fail": "It needs a sink, and there is none here.",
                },
            ),
            TextRow(
                entity_id="clean",
                state="default",
                since_drop=1,
                text={"look": "A clean bottle."},
            ),
        ],
    )


async def test_a_transform_in_the_right_room_swaps_the_thing(house):
    await content_loader.load_content(bottles())
    await take(thing="used bottle")
    await database.update_current_room(ALICE, GUILD_A, "KI")

    interaction = await use(thing="used bottle")
    assert interaction.reply == "You scrub it clean."
    assert await bag() == {"clean bottle": 1}


async def test_a_transform_in_the_wrong_room_refuses_and_changes_nothing(house):
    await content_loader.load_content(bottles())
    await take(thing="used bottle")

    interaction = await use(thing="used bottle")
    assert "needs a sink" in interaction.reply
    assert await bag() == {"used bottle": 1}


async def test_a_transform_is_one_way(house):
    await content_loader.load_content(bottles())
    await take(thing="used bottle")
    await database.update_current_room(ALICE, GUILD_A, "KI")
    await use(thing="used bottle")

    assert await bag() == {"clean bottle": 1}
    await use(thing="clean bottle")
    assert await bag() == {"clean bottle": 1}


async def test_a_failed_transform_is_not_counted_as_a_use(house):
    await content_loader.load_content(bottles())
    await take(thing="used bottle")

    await use(thing="used bottle")  # wrong room
    assert await uses_of(ALICE, GUILD_A, "used") is None


# --- the cooldown branch ------------------------------------------------------


def lumber():
    return a_house(
        a_thing(
            "lumber", name="lumber", type="fixture", takeable=False, use_cooldown_hours=48
        ),
        thing_text=[
            TextRow(
                entity_id="lumber",
                state="default",
                since_drop=1,
                text={
                    "look": "A stack of planks.",
                    "use": "You hammer a plank into place.",
                    "use_fail": "Your shoulders want {time} first.",
                },
            )
        ],
    )


async def test_a_first_use_is_allowed(house):
    await content_loader.load_content(lumber())
    assert (await use(thing="lumber")).reply == "You hammer a plank into place."


async def test_a_second_use_inside_the_window_is_refused(house):
    await content_loader.load_content(lumber())
    await use(thing="lumber")

    interaction = await use(thing="lumber")
    assert "shoulders want" in interaction.reply
    assert "2 days" in interaction.reply


async def test_a_refused_use_does_not_slide_the_window_forward(house):
    """A refused use is not a use, so trying repeatedly must not keep resetting
    the clock and lock the player out for ever."""
    await content_loader.load_content(lumber())
    await use(thing="lumber")
    first = await database.last_used(ALICE, GUILD_A, "lumber")

    for _ in range(3):
        await use(thing="lumber")

    assert await database.last_used(ALICE, GUILD_A, "lumber") == first
    assert await uses_of(ALICE, GUILD_A, "lumber") == 1


async def test_the_cooldown_expires(house):
    from datetime import timedelta

    from sqlalchemy import update

    await content_loader.load_content(lumber())
    await use(thing="lumber")

    async with database._require_session()() as session:
        await session.execute(
            update(database.ThingUse).values(
                last_used_at=database._utcnow() - timedelta(hours=49)
            )
        )
        await session.commit()

    assert (await use(thing="lumber")).reply == "You hammer a plank into place."
    assert await uses_of(ALICE, GUILD_A, "lumber") == 2


async def test_the_cooldown_is_per_player(house):
    await content_loader.load_content(lumber())
    await use(thing="lumber")

    assert (await use(BOB, thing="lumber")).reply == "You hammer a plank into place."


async def test_planks_below_the_target_leave_the_staircase_alone(house):
    """Two planks against a default target of ten is progress, not completion."""
    from sqlalchemy import select

    await content_loader.load_content(lumber())
    await use(thing="lumber")
    await use(BOB, thing="lumber")

    assert await database.distinct_users_of(GUILD_A, "lumber") == 2
    async with database._require_session()() as session:
        rows = (await session.execute(select(database.ServerState))).all()
    assert rows == []


# --------------------------------------------------------------------------
# The exit branch, through the real house
#
# The fourth `/use` branch, and the one nothing here used to drive: every
# other test in this file stops before a player actually moves. The bug that
# gap hid was reported as "the wide doorway out of the Living Room does
# nothing" and was really "no exit works for anyone who entered before 2b".
# --------------------------------------------------------------------------


from fake_discord import FakeChannel, FakeGuild, FakeMember  # noqa: E402


@pytest.fixture
async def real_house(db):
    """The shipped nine rooms, with a thread for each."""
    await content_loader.load_content(content_module.load_files())
    channel = FakeChannel(name="halloween")
    channel.add_active(*[name for _, name in await resolve.all_rooms()])
    return db, FakeGuild(GUILD_A, channels=[channel], members=[FakeMember(ALICE)])


async def enter_properly(db, room="EN"):
    """Entering the way `/enter` does, with ids in both columns."""
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.start_game(ALICE, GUILD_A, room, await resolve.rooms_open_at_launch())


async def where_is_alice(db):
    return (await db.get_game_state(ALICE, GUILD_A)).current_room


async def test_the_wide_doorway_leads_out_of_the_living_room(real_house):
    """The reported bug, as a player hit it."""
    db, guild = real_house
    await enter_properly(db, room="LI")

    reply = (await use(thing="wide doorway", guild=guild)).reply

    assert await where_is_alice(db) == "EN"
    assert "You head to" in reply


async def test_the_wide_doorway_leads_back_in_again(real_house):
    """Two exits share the name, one in each room. Resolution is scoped to
    the room the player is standing in, so each takes them the other way."""
    db, guild = real_house
    await enter_properly(db, room="EN")

    await use(thing="wide doorway", guild=guild)
    assert await where_is_alice(db) == "LI"

    await use(thing="wide doorway", guild=guild)
    assert await where_is_alice(db) == "EN"


@pytest.mark.parametrize("typed", ["wide doorway", "doorway", "entryway", "hall"])
async def test_every_alias_of_the_doorway_works(real_house, typed):
    db, guild = real_house
    await enter_properly(db, room="LI")

    await use(thing=typed, guild=guild)

    assert await where_is_alice(db) == "EN"


async def test_a_pre_2b_player_can_still_use_the_doorway(real_house):
    """The actual cause. Their `rooms_unlocked` held room *names*, `/use`
    compared it against a room *id*, and every exit refused with the house's
    generic use_fail - while `/look` at the same exit worked, because looking
    does not consult the list."""
    db, guild = real_house
    await db.ensure_user_exists(ALICE, GUILD_A)
    rooms = await resolve.all_rooms()
    await db.start_game(ALICE, GUILD_A, "Living Room", [name for _, name in rooms])
    await db.migrate_room_names_to_ids()

    await use(thing="wide doorway", guild=guild)

    assert await where_is_alice(db) == "EN"


async def test_a_pre_2b_player_is_not_let_into_the_secret_library(real_house):
    """Their old list named every room. The Secret Library is shut until 2e,
    and the repair must not be the thing that opens it."""
    db, guild = real_house
    await db.ensure_user_exists(ALICE, GUILD_A)
    rooms = await resolve.all_rooms()
    await db.start_game(ALICE, GUILD_A, "Living Room", [name for _, name in rooms])
    await db.migrate_room_names_to_ids()

    await use(thing="curiosity cabinet", guild=guild)

    assert await where_is_alice(db) == "LI"


async def test_a_locked_room_refuses_rather_than_moving_anybody(real_house):
    """The same check, doing its real job. The Secret Library is the only
    room not open at launch, and the cabinet is the route that respects that
    - the oak is the deliberate exception, because climbing it is what
    unlocks the room in the first place."""
    db, guild = real_house
    await enter_properly(db, room="LI")

    reply = (await use(thing="cabinet", guild=guild)).reply

    assert await where_is_alice(db) == "LI"
    assert "You head to" not in reply


async def test_moving_posts_a_departure_and_an_arrival(real_house):
    db, guild = real_house
    await enter_properly(db, room="LI")
    threads = {t.name: t for t in guild.text_channels[0].threads}

    await use(thing="wide doorway", guild=guild)

    assert any("exits via" in (line or "") for line in threads["Living Room"].posted)
    assert threads["Entryway"].posted


# --------------------------------------------------------------------------
# The thread is the room
#
# Reported from testing: `/look` in an unrelated channel answered with the
# player's room. The four world verbs used to run from anywhere in the
# server, which made the house a status readout rather than a place.
# --------------------------------------------------------------------------


from fake_discord import a_room_thread, somewhere_else  # noqa: E402


async def command(fn, arg, channel, user_id=ALICE, guild_id=GUILD_A, guild=None):
    from types import SimpleNamespace

    interaction = FakeInteraction(
        user_id,
        guild_id,
        guild=guild or SimpleNamespace(name="Test", text_channels=[]),
        channel=channel,
    )
    args = () if arg is None else (arg,)
    await fn.callback(interaction, *args)
    return interaction


WORLD_VERBS = [
    pytest.param(lambda: bot.look, None, id="look"),
    pytest.param(lambda: bot.take, "spoon", id="take"),
    pytest.param(lambda: bot.drop, "spoon", id="drop"),
    pytest.param(lambda: bot.use, "spoon", id="use"),
]


@pytest.mark.parametrize("verb, arg", WORLD_VERBS)
async def test_a_world_verb_is_refused_outside_the_house(house, verb, arg):
    await content_loader.load_content(a_house(a_thing("spoon")))

    reply = (await command(verb(), arg, somewhere_else())).reply

    assert "only works inside the house" in reply


@pytest.mark.parametrize("verb, arg", WORLD_VERBS)
async def test_a_world_verb_works_in_a_room_thread(house, verb, arg):
    await content_loader.load_content(a_house(a_thing("spoon")))

    # Threads are named after the room, not its id.
    reply = (await command(verb(), arg, a_room_thread("Entryway"))).reply

    assert "only works inside the house" not in reply


async def test_the_refusal_says_where_the_player_actually_is(house):
    """So a player who typed in the wrong place knows where to go."""
    await content_loader.load_content(a_house(a_thing("spoon")))

    reply = (await command(bot.look, None, somewhere_else())).reply

    assert "Entryway" in reply


async def test_a_thread_outside_the_halloween_channel_is_not_the_house(house):
    """Somebody else's thread in another channel is not a room, however it is
    named - the rooms are the threads under #halloween."""
    from fake_discord import FakeChannel, FakeThread

    await content_loader.load_content(a_house(a_thing("spoon")))
    impostor = FakeThread("Entryway", channel=FakeChannel(name="off-topic"))

    reply = (await command(bot.look, None, impostor)).reply

    assert "only works inside the house" in reply


async def test_a_thread_named_after_no_room_is_not_the_house(house):
    """A thread under #halloween that is not one of the rooms - somebody's
    own thread in the same channel."""
    from fake_discord import FakeChannel, FakeThread

    await content_loader.load_content(a_house(a_thing("spoon")))
    chatter = FakeThread("spoilers", channel=FakeChannel(name="halloween"))

    reply = (await command(bot.look, None, chatter)).reply

    assert "only works inside the house" in reply


async def test_the_player_verbs_are_not_gated(house):
    """`/pet`, `/inventory` and `/stats` are about the player rather than the
    room, so they answer anywhere - the house is not a place you have to
    stand to check your own bag."""
    await content_loader.load_content(a_house(a_thing("spoon")))
    await carry(house, ALICE, GUILD_A, "spoon")

    reply = (await command(bot.inventory, None, somewhere_else())).reply

    assert "only works inside the house" not in reply
    assert "spoon" in reply


async def test_a_word_two_doors_answer_to_asks_which(real_house):
    """The Entryway has an arched doorway to the Dining Room and a wide one
    to the Living Room, and its prose calls them both doorways. Before this
    the word was taken off one of them, so `/use doorway` answered "you don't
    see a doorway here" in a room that had just mentioned two."""
    db, guild = real_house
    await enter_properly(db, room="EN")

    reply = (await use(thing="doorway", guild=guild)).reply

    assert "Which one do you mean" in reply
    assert "arched doorway" in reply and "wide doorway" in reply
    assert await where_is_alice(db) == "EN"


async def test_naming_which_door_still_walks_through_it(real_house):
    db, guild = real_house
    await enter_properly(db, room="EN")

    await use(thing="wide doorway", guild=guild)

    assert await where_is_alice(db) == "LI"


async def test_a_room_with_one_doorway_does_not_ask(real_house):
    """Only the Entryway has two. The Living Room's `doorway` is unambiguous
    and still walks straight through."""
    db, guild = real_house
    await enter_properly(db, room="LI")

    await use(thing="doorway", guild=guild)

    assert await where_is_alice(db) == "EN"
