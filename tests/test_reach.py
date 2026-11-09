"""Resolution: which thing the player meant, and which copy to act on.

The spec calls this the most reused logic in the bot, so it gets the most
tests. Three things here are worth more attention than the rest, because each
is a rule that exists to prevent a specific bug rather than to express an
obvious behaviour:

- **Scope is set before pass one.** `/take` never sees the bag, `/drop` never
  sees the room. The worked example from the spec is reproduced below.
- **A source and its yield are one thing**, or a player standing by a stash
  holding a can is asked "chicken or chicken?" forever.
- **Step four never says where.** Confirming a thing exists is fine; naming its
  room gives away the Secret Library before anyone has found it.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A

import content as content_module
import content_loader
import database
import reach
import resolve
import states
from reach import Ambiguous, Found, NotFound, Scope, Where
from test_loader import a_thing
from test_world import a_house, carry


@pytest.fixture
async def house(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.ensure_user_exists(BOB, GUILD_A)
    return db


async def find(room="EN", typed="", scope=Scope.REACH, user=ALICE):
    return await reach.find(GUILD_A, user, room, typed, scope)


# --------------------------------------------------------------------------
# A word the house knows is not a typo for one it also knows
#
# The forgiving pass runs over the candidates, and the candidates are
# what the player can reach - so on its own it reaches past a word the
# house knows perfectly well to a different thing that happens to be
# standing here.
#
# Drop 25 found the narrow half with two doorways: `living room` is two
# edits from `dining room`, so an Entryway with the arch open and the
# wide doorway still to come took a player who had spelled the Living
# Room correctly and walked them through the other one. That was fixed
# by asking whether the word belonged to something in *this room* that
# had not arrived yet.
#
# 6 November found the rest of it, and the room was the wrong place to
# have looked: the ladder is not in the Kitchen at all, not even
# invisibly. So the question is now game-wide - does the house know this
# word - and the two doorway cases below pass unchanged, because a
# doorway that has not arrived is still a word the house knows.
# --------------------------------------------------------------------------


def a_doorway(thing_id, name, *aliases, **overrides):
    return a_thing(
        thing_id, name=name, aliases=aliases, type="scenery", takeable=False,
        quantity=None, **overrides,
    )


@pytest.fixture
async def one_doorway(house):
    """An arch that has arrived and a wide doorway that has not."""
    parsed = a_house(
        a_doorway("ED", "arched doorway", "doorway", "dining room"),
        a_doorway("EL", "wide doorway", "doorway", "living room", since_drop=2),
    )
    parsed.drops.append(
        content_module.Drop(
            drop_id=2, trigger="manual", date=None, event=None,
            name="The Other Doorway", notes=None,
        )
    )
    await content_loader.load_content(parsed)
    await resolve.set_current_drop(GUILD_A, 1)
    return house


async def test_the_doorway_that_has_not_arrived_is_refused_and_not_corrected(one_doorway):
    """The bug, in the two words that found it."""
    result = await find(typed="living room")

    assert isinstance(result, NotFound)
    assert result.exists_elsewhere


async def test_and_the_one_that_has_arrived_answers_to_its_own_words(one_doorway):
    """The guard is on the forgiving pass alone, so nothing a player
    spells correctly about a thing they can see is affected."""
    assert (await find(typed="arched doorway")).thing_id == "ED"
    assert (await find(typed="dining room")).thing_id == "ED"


async def test_a_typo_is_still_forgiven(one_doorway):
    """`arched doorwy` is one edit from a word in the room and spells
    nothing, so it is corrected exactly as before. The guard asks whether
    the word *is* something here, not whether it is close to it."""
    result = await find(typed="arched doorwy")

    assert result.thing_id == "ED"
    assert result.fuzzy == "arched doorwy→arched doorway"


async def test_and_the_wide_doorway_resolves_once_its_drop_arrives(one_doorway):
    await resolve.set_current_drop(GUILD_A, 2)

    assert (await find(typed="living room")).thing_id == "EL"


@pytest.fixture
async def a_gated_doorway(house):
    """The same shape, with a per-player gate instead of a drop.

    Which is the half that was already possible before drop 25: both of
    the Entryway's doorways sit behind `fed_the_cat`, and an unfed player
    typing one of their names has been getting the other one. The gate
    here is `drawer_unjammed` because it is a state a test can set -
    `fed_the_cat` is a notice, and `_describe_room` is what turns it
    into one of these.
    """
    await content_loader.load_content(
        a_house(
            a_doorway("ED", "arched doorway", "doorway", "dining room"),
            a_doorway(
                "EL", "wide doorway", "doorway", "living room",
                present_when="drawer_unjammed",
            ),
        )
    )
    return house


async def test_a_doorway_behind_a_gate_is_refused_the_same_way(a_gated_doorway):
    result = await find(typed="living room")

    assert isinstance(result, NotFound)


async def test_and_opens_to_the_player_who_has_passed_it(a_gated_doorway):
    await states.set_player_state(GUILD_A, ALICE, "drawer_unjammed")

    assert (await find(typed="living room")).thing_id == "EL"


@pytest.fixture
async def a_ladder_and_a_larder(house):
    """Two rooms, and the one word each that the other sits an edit from.

    The report's own shape, with the content files' two words: a thing
    that is somewhere else entirely, not merely unarrived or gated.
    """
    await content_loader.load_content(
        a_house(
            a_thing("ladder", name="ladder", aliases=("rungs",), room_id="CO"),
            a_doorway("pantry", "pantry", "cupboard", "larder", room_id="KI"),
        )
    )
    await database.place_in_room(GUILD_A, "CO", "ladder", 1)
    return house


async def test_a_thing_in_another_room_is_not_a_typo_for_one_here(a_ladder_and_a_larder):
    """The bug, in the two words that found it. A playtester climbed the
    ladder in the Courtyard - which sets it down - walked into the Kitchen
    and typed `/look ladder`. She was told about the pantry, which answers
    to `larder`, and when she did not believe it she was told again."""
    assert reach._distance("ladder", "larder", 1) == 1

    result = await find(room="KI", typed="ladder")

    assert isinstance(result, NotFound)


async def test_and_the_refusal_still_says_it_exists_somewhere(a_ladder_and_a_larder):
    """Which is the half that sends her back to the Courtyard: the verbs
    read this to choose `take_fail.absent` - *you don't see a ladder here* -
    over `look_fail.unknown`, and the first is both true and a direction."""
    result = await find(room="KI", typed="ladder")

    assert result.exists_elsewhere


async def test_the_ladder_answers_in_the_room_it_is_actually_in(a_ladder_and_a_larder):
    """The guard is on the forgiving pass alone. Nothing about reaching a
    thing that is there changes."""
    assert (await find(room="CO", typed="ladder")).thing_id == "ladder"
    assert (await find(room="KI", typed="larder")).thing_id == "pantry"


async def test_and_a_word_that_spells_nothing_is_still_forgiven(a_ladder_and_a_larder):
    """The rule is about words the house knows, not about distance. `lardet`
    is a word of nothing, so it reaches the pantry's `larder` from one edit
    away exactly as before - which is the behaviour this keeps."""
    result = await find(room="KI", typed="lardet")

    assert result.thing_id == "pantry"
    assert result.fuzzy == "lardet→larder"


async def test_against_the_shipped_content_in_the_room_it_happened_in(house):
    """The report end to end, on drop 31's own files: one ladder, lying in
    the Courtyard where its last climb set it down, and a player standing
    in the Kitchen."""
    await content_loader.load_content(content_module.load_files())
    await resolve.set_current_drop(GUILD_A, 31)
    await database.place_in_room(GUILD_A, "CO", "ladder", 1)

    refused = await find(room="KI", typed="ladder")

    assert isinstance(refused, NotFound)
    assert refused.exists_elsewhere
    assert (await find(room="KI", typed="larder")).thing_id == "pantry"
    assert (await find(room="CO", typed="ladder")).thing_id == "ladder"


async def test_and_carrying_it_into_the_kitchen_describes_the_ladder(house):
    """The other half of her run, and why she was sure the game was wrong:
    the climb before it worked. A ladder in her hands resolves in the
    Kitchen on the exact pass, as it always did."""
    await content_loader.load_content(content_module.load_files())
    await resolve.set_current_drop(GUILD_A, 31)
    await carry(house, ALICE, GUILD_A, "ladder")

    found = await find(room="KI", typed="ladder")

    assert found.thing_id == "ladder"
    assert found.where is Where.CARRIED
    assert found.fuzzy is None


# --------------------------------------------------------------------------
# Normalising what was typed
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("Cat Food", "cat food"),
        ("  cat   food  ", "cat food"),
        ("blue-door", "blue door"),
        ("Alexa,", "alexa"),
        ("the cat's food", "the cat s food"),
        ("", ""),
    ],
)
def test_input_is_normalised(typed, expected):
    assert reach.normalise(typed) == expected


async def test_matching_ignores_case_and_punctuation(house):
    await content_loader.load_content(a_house(a_thing("spoon", name="silver spoon")))

    for typed in ("silver spoon", "SILVER SPOON", "  Silver  Spoon  ", "silver-spoon"):
        assert isinstance(await find(typed=typed), Found), typed


async def test_an_alias_matches(house):
    await content_loader.load_content(
        a_house(a_thing("spoon", name="silver spoon", aliases=("spoon", "cutlery")))
    )
    assert (await find(typed="cutlery")).thing_id == "spoon"


@pytest.mark.parametrize("typed", ["", "   ", ",,,"])
async def test_empty_input_finds_nothing(house, typed):
    await content_loader.load_content(a_house(a_thing("spoon")))
    assert isinstance(await find(typed=typed), NotFound)


# --------------------------------------------------------------------------
# Scope: the spec's worked example
# --------------------------------------------------------------------------


@pytest.fixture
async def cat_food(house):
    """Carrying chicken, standing in a room with the salmon cupboard."""
    await content_loader.load_content(
        a_house(
            a_thing("chicken", name="chicken cat food", aliases=("cat food",), room_id=None, quantity=0),
            a_thing("salmon", name="salmon cat food", aliases=("cat food",), room_id=None, quantity=0),
            a_thing(
                "cupboard",
                name="cupboard of salmon cat food",
                aliases=("cat food",),
                type="source",
                yields="salmon",
                takeable=False,
            ),
        )
    )
    await carry(house, ALICE, GUILD_A, "chicken")
    return house


async def test_take_is_scoped_to_the_room(cat_food):
    """The bug: with the bag in scope this asks "chicken or salmon?", and if the
    player says chicken there is no chicken in the room to take."""
    result = await find(typed="cat food", scope=Scope.ROOM)

    assert isinstance(result, Found)
    assert result.thing_id == "salmon"


async def test_drop_is_scoped_to_the_bag(cat_food):
    """The same fault mirrored: dropping must not offer the salmon."""
    result = await find(typed="cat food", scope=Scope.CARRIED)

    assert isinstance(result, Found)
    assert result.thing_id == "chicken"


async def test_use_and_look_see_everything_in_reach(cat_food):
    """Two genuinely different things are both reachable, so the prompt is fair."""
    result = await find(typed="cat food", scope=Scope.REACH)

    assert isinstance(result, Ambiguous)
    assert result.options == ["chicken cat food", "salmon cat food"]


async def test_the_prompt_names_the_object_not_the_furniture(cat_food):
    """A source is offered as what it hands over - "salmon cat food", not
    "cupboard of salmon cat food", which the player cannot take."""
    result = await find(typed="cat food", scope=Scope.REACH)
    assert "cupboard of salmon cat food" not in result.options


# --------------------------------------------------------------------------
# A source and its yield are one thing
# --------------------------------------------------------------------------


@pytest.fixture
async def stash(house):
    await content_loader.load_content(
        a_house(
            a_thing("can", name="chicken cat food", aliases=("cat food",), room_id=None, quantity=0),
            a_thing(
                "sofa_stash",
                name="stash of chicken cat food",
                aliases=("cat food",),
                type="source",
                yields="can",
                takeable=False,
            ),
        )
    )
    return house


async def test_standing_by_the_stash_holding_a_can_is_not_ambiguous(stash):
    """Without this rule the player is asked "chicken or chicken?" every time."""
    await carry(stash, ALICE, GUILD_A, "can")
    result = await find(typed="cat food", scope=Scope.REACH)

    assert isinstance(result, Found)
    assert result.thing_id == "can"


async def test_the_carried_copy_wins_for_use_and_look(stash):
    await carry(stash, ALICE, GUILD_A, "can")
    assert (await find(typed="cat food", scope=Scope.REACH)).where is Where.CARRIED


async def test_take_reaches_the_source_because_the_bag_is_not_in_scope(stash):
    await carry(stash, ALICE, GUILD_A, "can")
    result = await find(typed="cat food", scope=Scope.ROOM)

    assert result.where is Where.SOURCE
    assert result.yields == "can"


async def test_the_sources_own_name_still_matches_it(stash):
    result = await find(typed="stash of chicken cat food", scope=Scope.ROOM)
    assert isinstance(result, Found)
    assert result.where is Where.SOURCE


async def test_a_source_is_never_consumed_so_it_always_resolves(stash):
    for _ in range(3):
        assert isinstance(await find(typed="cat food", scope=Scope.ROOM), Found)


# --------------------------------------------------------------------------
# ...but only the words they share
# --------------------------------------------------------------------------
#
# The merge above files a stash under the can it hands out, which is what
# stops "chicken or chicken?". It also merged their vocabularies, so a word
# belonging to the stash alone - `pack`, `crate`, `cupboard` - reached the
# can instead: pass two was written for the words they share and never asked
# which kind it had been given.


@pytest.fixture
async def pack(house):
    """A stash with words of its own, and a loose can of what it yields."""
    await content_loader.load_content(
        a_house(
            a_thing(
                "can",
                name="salmon cat food",
                aliases=("cat food", "salmon"),
                room_id="EN",
                quantity=1,
            ),
            a_thing(
                "hall_stash",
                name="pack of salmon cat food",
                aliases=("cat food", "salmon", "pack", "flat"),
                type="source",
                yields="can",
                takeable=False,
            ),
        )
    )
    return house


async def test_a_word_only_the_source_answers_to_means_the_source(pack):
    """There is a loose can on the floor, and `pack` is still the pack."""
    result = await find(typed="pack", scope=Scope.REACH)

    assert result.where is Where.SOURCE
    assert result.source_id == "hall_stash"


async def test_even_with_a_can_of_it_in_the_bag(pack):
    await carry(pack, ALICE, GUILD_A, "can")

    assert (await find(typed="pack", scope=Scope.REACH)).where is Where.SOURCE


async def test_taking_by_the_sources_own_word_records_the_source(pack):
    """Not cosmetic. `source_id` is what tells a harvest from a pickup, and
    a player typing the stash's own word was being credited with neither."""
    result = await find(typed="pack", scope=Scope.ROOM)

    assert result.source_id == "hall_stash"
    assert result.yields == "can"


async def test_a_shared_word_still_means_the_copy_in_your_hands(pack):
    """The rule above is unchanged for every word the two have in common.
    Somebody holding a can who says `cat food` means that can."""
    await carry(pack, ALICE, GUILD_A, "can")

    assert (await find(typed="cat food", scope=Scope.REACH)).where is Where.CARRIED


async def test_a_shared_word_still_prefers_the_floor_to_the_stash(pack):
    assert (await find(typed="salmon", scope=Scope.REACH)).where is Where.ROOM


async def test_a_typo_on_the_sources_word_still_means_the_source(pack):
    """Pass two asks about the word that was meant rather than the one that
    was typed, or forgiving a typo would quietly undo this."""
    result = await find(typed="packs", scope=Scope.REACH)

    assert result.where is Where.SOURCE
    assert result.fuzzy == "packs→pack"


async def test_the_pack_of_salmon_in_the_entryway(house):
    """The report, against the shipped content: a can of salmon loose in the
    Entryway, and `/look pack` described the can."""
    await content_loader.load_content(content_module.load_files())
    await database.place_in_room(GUILD_A, "EN", "cat_food_salmon", 1)

    result = await find(room="EN", typed="pack", scope=Scope.REACH)

    assert result.where is Where.SOURCE
    assert result.source_id == "cat_food_stash_hall"


async def test_and_the_shared_words_there_are_untouched(house):
    """`salmon` and `cat food` belong to both, so they still find the can
    that is actually on the floor."""
    await content_loader.load_content(content_module.load_files())
    await database.place_in_room(GUILD_A, "EN", "cat_food_salmon", 1)

    for typed in ("salmon", "cat food"):
        assert (await find(room="EN", typed=typed, scope=Scope.REACH)).where is Where.ROOM, typed



# --------------------------------------------------------------------------
# Pass two: which copy
# --------------------------------------------------------------------------


async def test_the_bag_is_checked_before_the_room(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    await carry(house, ALICE, GUILD_A, "spoon")

    assert (await find(typed="spoon")).where is Where.CARRIED


async def test_the_room_is_used_when_nothing_is_carried(house):
    await content_loader.load_content(a_house(a_thing("spoon")))
    assert (await find(typed="spoon")).where is Where.ROOM


async def test_loose_objects_come_before_sources(house):
    await content_loader.load_content(
        a_house(
            a_thing("can", name="beans", room_id="EN", quantity=1),
            a_thing("crate", name="crate of beans", aliases=("beans",), type="source", yields="can", takeable=False),
        )
    )
    assert (await find(typed="beans", scope=Scope.ROOM)).where is Where.ROOM


async def test_several_copies_of_one_thing_never_prompt(house):
    """Pass one settled it; a count is not an ambiguity."""
    await content_loader.load_content(a_house(a_thing("bottle", quantity=5)))

    result = await find(typed="bottle")
    assert isinstance(result, Found)
    assert result.count == 5


async def test_a_copy_inside_a_container_is_in_reach(house):
    """A bare name always works - never an `in <container>` parser."""
    await content_loader.load_content(
        a_house(
            a_thing("box", name="amazon box", type="fixture", takeable=False),
            a_thing("jar", name="spice jar", contained_in="box"),
        )
    )

    result = await find(typed="spice jar", scope=Scope.ROOM)
    assert isinstance(result, Found)
    assert result.container_id == "box"


# --------------------------------------------------------------------------
# Nothing in reach
# --------------------------------------------------------------------------


async def test_a_word_the_game_does_not_know(house):
    await content_loader.load_content(a_house(a_thing("spoon")))

    result = await find(typed="helicopter")
    assert isinstance(result, NotFound)
    assert result.exists_elsewhere is False


async def test_a_thing_that_exists_but_is_elsewhere(house):
    await content_loader.load_content(
        a_house(a_thing("spoon"), a_thing("kettle", room_id="KI"))
    )

    result = await find(typed="kettle")
    assert isinstance(result, NotFound)
    assert result.exists_elsewhere is True


async def test_nothing_reveals_where_it_is(house):
    """Naming the room would give away the Secret Library before anyone has
    found it, so the result carries a boolean and never a location."""
    await content_loader.load_content(
        a_house(a_thing("spoon"), a_thing("kettle", room_id="KI"))
    )

    result = await find(typed="kettle")
    assert not hasattr(result, "room_id")
    assert "KI" not in repr(result)


async def test_take_knows_the_difference_between_absent_and_already_carried(house):
    """take_fail.absent would be a lie when the player is holding one."""
    await content_loader.load_content(a_house(a_thing("spoon", room_id=None, quantity=0)))
    await carry(house, ALICE, GUILD_A, "spoon")

    result = await find(typed="spoon", scope=Scope.ROOM)
    assert isinstance(result, NotFound)
    assert result.carried is True


async def test_that_distinction_is_only_drawn_for_take(house):
    await content_loader.load_content(a_house(a_thing("spoon", room_id=None, quantity=0)))
    await carry(house, ALICE, GUILD_A, "spoon")

    result = await find(typed="spoon", scope=Scope.CARRIED)
    assert isinstance(result, Found)


async def test_an_emptied_object_is_out_of_reach(house):
    await content_loader.load_content(a_house(a_thing("chips")))
    async with house._require_session()() as session:
        await session.execute(database.RoomContents.__table__.update().values(count=0))
        await session.commit()

    assert isinstance(await find(typed="chips"), NotFound)


async def test_another_players_bag_is_out_of_reach(house):
    await content_loader.load_content(a_house(a_thing("spoon", room_id=None, quantity=0)))
    await carry(house, BOB, GUILD_A, "spoon")

    assert isinstance(await find(typed="spoon", user=ALICE), NotFound)


# --------------------------------------------------------------------------
# Fixtures and exits
# --------------------------------------------------------------------------


async def test_a_fixture_is_in_reach_without_being_stock(house):
    await content_loader.load_content(
        a_house(a_thing("fireplace", type="fixture", takeable=False))
    )

    result = await find(typed="fireplace")
    assert isinstance(result, Found)
    assert result.count == 1


async def test_an_exit_is_in_reach(house):
    await content_loader.load_content(
        a_house(a_thing("door", name="blue door", type="exit", destination_room_id="KI", takeable=False))
    )
    assert isinstance(await find(typed="blue door"), Found)


async def test_a_fixture_in_another_room_is_not(house):
    await content_loader.load_content(
        a_house(a_thing("fireplace", type="fixture", room_id="KI", takeable=False))
    )
    assert isinstance(await find(typed="fireplace"), NotFound)


# --------------------------------------------------------------------------
# Drops gate reach too
# --------------------------------------------------------------------------


async def test_a_thing_from_an_unarrived_drop_is_out_of_reach(house):
    import resolve
    from content import Drop

    parsed = a_house(a_thing("lantern", since_drop=2))
    parsed.drops.append(
        Drop(drop_id=2, trigger="manual", date=None, event=None, name="Later", notes=None)
    )
    await content_loader.load_content(parsed)
    await resolve.set_current_drop(GUILD_A, 1)

    result = await reach.find(GUILD_A, ALICE, "EN", "lantern", Scope.REACH)
    assert isinstance(result, NotFound)


async def test_and_is_in_reach_once_the_drop_opens(house):
    """The other half. Without it this suite would pass just as happily
    against a loader that placed nothing at all."""
    import resolve
    from content import Drop

    parsed = a_house(a_thing("lantern", since_drop=2))
    parsed.drops.append(
        Drop(drop_id=2, trigger="manual", date=None, event=None, name="Later", notes=None)
    )
    await content_loader.load_content(parsed)
    await resolve.set_current_drop(GUILD_A, 2)

    result = await reach.find(GUILD_A, ALICE, "EN", "lantern", Scope.REACH)
    assert isinstance(result, Found)


# --------------------------------------------------------------------------
# Against the real content
# --------------------------------------------------------------------------


async def test_the_shipped_house_resolves_a_fixture(house):
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "EN", "mirror", Scope.REACH)
    assert isinstance(result, Found)
    assert result.thing_id == "ornate_mirror"


async def test_the_shipped_house_resolves_an_exit_by_alias(house):
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "EN", "stairs", Scope.REACH)
    assert isinstance(result, Found)


async def test_taking_cat_food_in_the_dining_room_reaches_the_sideboard_stash(house):
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "DI", "tuna", Scope.ROOM)
    assert isinstance(result, Found)
    assert result.where is Where.SOURCE
    assert result.yields == "cat_food_tuna"


async def test_the_gourmet_tin_is_reachable_inside_the_cake_box(house):
    """Contained things resolve by bare name; discovery is preserved by what the
    listing shows, not by what the player has to type."""
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "KI", "gourmet", Scope.ROOM)
    assert isinstance(result, Found)
    assert result.container_id == "cake_box"


# --------------------------------------------------------------------------
# Which source, not just that it was one
#
# A source and its yield are filed as one thing, which is the only reason
# `/take herbs` does not raise a spurious ambiguity prompt. The cost is that
# `thing_id` alone cannot say where the herbs came from, and one achievement
# turns on exactly that difference.
# --------------------------------------------------------------------------


async def test_a_source_reports_which_source_it_was(house):
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "CO", "herbs", Scope.ROOM)
    assert result.thing_id == "herbs"
    assert result.source_id == "herb_garden"


async def test_a_loose_copy_reports_no_source(house):
    """Gardening versus scavenging. Both hand over an identical `herbs`, and
    without this the two are indistinguishable to anything downstream."""
    await content_loader.load_content(content_module.load_files())
    await database.take_from_source(ALICE, GUILD_A, "herbs")
    await database.drop_into_room(ALICE, GUILD_A, "EN", "herbs")

    result = await reach.find(GUILD_A, ALICE, "EN", "herbs", Scope.ROOM)
    assert result.thing_id == "herbs"
    assert result.source_id is None


async def test_the_source_id_is_the_stash_not_the_can(house):
    """The cat food stashes are the case with the most rows: six of them hand
    out five flavors, and chicken comes from two stashes.

    Tuna moved from the kitchen pantry to the dining room sideboard on 30
    October, so this asks in DI. The point of the test is the indirection -
    typing a flavor finds the stash, not the can - and that is unchanged by
    which room the stash stands in.
    """
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "DI", "tuna", Scope.ROOM)
    assert result.yields == "cat_food_tuna"
    assert result.source_id == "cat_food_stash_sideboard"


# --------------------------------------------------------------------------
# `ALL`: a room nobody stands in
#
# `content.EVERYWHERE` marks a thing present in every room. The validator has
# always exempted it from the "is this a real room?" check, and nothing else
# implemented it - so the things declared to be everywhere were reachable
# nowhere, and their look text and take_fail were both dead.
#
# **These used to be Alexa's tests.** She was the example because she was
# the only thing in the house that was everywhere; drop 20 parked her at
# `NEVER` until the notes feature she needs exists, so she is now the
# example of the opposite and the cat carries the mechanism. The cat is
# the better subject anyway: she has been everywhere since drop 0, so
# these no longer depend on a row that may move again.
# --------------------------------------------------------------------------


EVERY_ROOM = ["EN", "DI", "KI", "CO", "LI", "SE", "UH", "BE", "NU"]


@pytest.mark.parametrize("room", EVERY_ROOM)
async def test_the_cat_is_reachable_in_every_room(house, room):
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, room, "cat", Scope.ROOM)
    assert isinstance(result, Found)
    assert result.thing_id == "eunoia"


@pytest.mark.parametrize("typed", ["cat", "black cat", "kitty", "eunoia"])
async def test_every_name_for_her_resolves(house, typed):
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "KI", typed, Scope.ROOM)
    assert getattr(result, "thing_id", None) == "eunoia"


async def test_she_is_reachable_by_a_verb_that_reaches_the_bag_too(house):
    """REACH is /use's scope, and she has a use_fail for it."""
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "BE", "cat", Scope.REACH)
    assert getattr(result, "thing_id", None) == "eunoia"


async def test_she_is_not_in_the_bag(house):
    """Everywhere in the house is not the same as carried - CARRIED scope is
    the inventory, and a fixture never enters it."""
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "KI", "cat", Scope.CARRIED)
    assert isinstance(result, NotFound)


@pytest.mark.parametrize("room", EVERY_ROOM)
async def test_a_parked_thing_is_everywhere_and_reachable_nowhere(house, room):
    """**What parking has to mean, room by room.**

    Alexa's `room_id` is `ALL`, which is why delaying her is a decision
    about every room at once rather than about the Entryway. Her drop is
    99 and `drops.tsv` stops at 50, so she never arrives - and a player
    who types her name anywhere gets the same answer as for a word the
    game has never heard.
    """
    await content_loader.load_content(content_module.load_files())

    for typed in ("alexa", "smart speaker", "echo"):
        result = await reach.find(GUILD_A, ALICE, room, typed, Scope.REACH)
        assert isinstance(result, NotFound), (room, typed)


async def test_an_ordinary_room_id_still_means_one_room(house):
    """The clause admits `ALL` as well as the current room, not instead of
    it, and must not make everything global."""
    await content_loader.load_content(content_module.load_files())

    here = await reach.find(GUILD_A, ALICE, "KI", "stove", Scope.ROOM)
    elsewhere = await reach.find(GUILD_A, ALICE, "BE", "stove", Scope.ROOM)
    assert isinstance(here, Found)
    assert isinstance(elsewhere, NotFound)


async def test_everything_declared_everywhere_is_a_fixture(house):
    """Two things are in every room: the smart speaker and the cat. Both are
    safe to be everywhere for the same reason - `Also here:` lists loose
    takeable objects, and a fixture is neither, so being omnipresent does not
    drop either name into nine rooms' prose.

    This started as "alexa is the only one", and caught the cat being added
    in 2f. If a *takeable* thing ever gets `ALL`, the listing rules need
    reading again before it ships - and so does the typo rule below, which
    asks the same question of the thing rather than of the copy in reach.
    """
    parsed = content_module.load_files()
    everywhere = [
        t for t in parsed.things if t.room_id == content_module.EVERYWHERE
    ]

    assert {t.thing_id for t in everywhere} == {"alexa", "eunoia"}
    for thing in everywhere:
        assert thing.type == "fixture", thing.thing_id
        assert thing.takeable is False, thing.thing_id


async def test_a_thing_that_is_everywhere_is_still_a_fixture(house):
    """Which is what keeps her out of `Also here:` - the listing holds loose
    takeable objects, and she is neither."""
    parsed = content_module.load_files()
    assert parsed.things_by_id["alexa"].type == "fixture"
    assert parsed.things_by_id["alexa"].takeable is False


# --------------------------------------------------------------------------
# A thing that is everywhere is never what a typo meant
#
# **Reported as "I tried to look at the sideboard and got the cat".** The
# sideboard had worked. Nine seconds earlier, from the beta log:
#
#     05:39:13  look  thing=sideboard  typed='sideboard'  success
#     05:39:22  look  thing=eunoia     typed='mail'       success
#
# She read *its top crowded with the things that live on sideboards: the
# candy bowl, a vase, a stack of unopened mail*, typed the noun, and was
# told about a cat. There was no `mail` to find, so the typo pass ran, and
# the cat answers to `tail` from one edit away in every room in the house.
#
# Two fixes, and they are not alternatives:
#
# - `mail` and `letters` are the sideboard's now, because the exact pass
#   runs first and a word the prose puts in front of somebody should reach
#   the thing it describes. That is the reported case and only that case.
# - **A thing in every room no longer wins a near miss**, which is the
#   class. The cat owns `tail`, `paws`, `eyes`; four-letter words get one
#   edit forgiven; and being everywhere made her a candidate for all of
#   their neighbours in all nine rooms. She had taken 38 of the 343
#   corrections ever logged in the beta server.
#
# `kitchen`->`kitten` was this bug caught small, and ranking the room's own
# name above a correction fixed that one room. `reach._nearest` carries the
# rest of the reasoning and the numbers.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("typed", ["mail", "letters"])
async def test_a_word_the_sideboard_puts_in_front_of_you_reaches_it(house, typed):
    """The reported case, and it is an exact match rather than a forgiven
    one - which is the whole reason the alias settles it, since pass one
    returns before the cat is ever looked at."""
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "DI", typed, Scope.REACH)

    assert isinstance(result, Found)
    assert result.thing_id == "sideboard"
    assert result.fuzzy is None


async def test_mail_is_still_one_edit_from_the_cat(house):
    """So the alias is not what fixed the class, and removing the rule would
    not be caught by the sideboard tests alone. `mail` is settled in the
    Dining Room by being a word; `rail` is settled everywhere by the rule."""
    assert reach._distance("mail", "tail", 1) == 1
    await content_loader.load_content(content_module.load_files())

    hers = await reach.find(GUILD_A, ALICE, "DI", "tail", Scope.REACH)
    assert hers.thing_id == "eunoia"


@pytest.mark.parametrize("typed", ["laws", "jaws", "saws", "cart", "eyed"])
async def test_a_near_miss_on_a_thing_that_is_everywhere_is_refused(house, typed):
    """One edit from `paws`, `cat` or `eyes`, and nothing in the Kitchen is
    any closer - so before the rule each of these described the cat. The
    refusal is the honest answer: no such thing is here."""
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "KI", typed, Scope.REACH)

    assert isinstance(result, NotFound)


async def test_she_takes_no_near_miss_in_any_room(house):
    """The point of the rule rather than a sample of it. Swept in one test
    rather than parametrized over nine, because the content load is the
    expensive part and the assertion is cheap."""
    await content_loader.load_content(content_module.load_files())

    for room in EVERY_ROOM:
        result = await reach.find(GUILD_A, ALICE, room, "laws", Scope.REACH)
        assert isinstance(result, NotFound), room


@pytest.mark.parametrize("typed", ["tail", "paws", "paw", "eyes"])
async def test_every_word_she_owns_still_reaches_her(house, typed):
    """**Nothing she answers to was given up.** These four are the ones the
    rule puts at risk and that `test_every_name_for_her_resolves` does not
    cover: the short body-part words, which are hers exactly and were never
    the problem. `paw` is three letters and so was never fuzzy-matchable at
    all, which is the shape the other three now have too."""
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "LI", typed, Scope.REACH)

    assert isinstance(result, Found)
    assert result.thing_id == "eunoia"


async def test_a_misspelling_of_her_name_is_what_this_costs(house):
    """**The one real correction in the log that the rule gives up.**
    `einoia`->`eunoia` fired once, on 8 November, against 37 thefts.

    Written down rather than worked around, and it is the trade
    `test_crickle_is_the_price_of_trickle` already makes by name: a refusal
    a player can read and retype costs less than a confident answer about
    something they never typed. Spelled right she is still reachable from
    every room in the house, and so are `cat`, `kitty` and `kitten`."""
    await content_loader.load_content(content_module.load_files())

    result = await reach.find(GUILD_A, ALICE, "DI", "einoia", Scope.REACH)
    assert isinstance(result, NotFound)

    assert (
        await reach.find(GUILD_A, ALICE, "DI", "eunoia", Scope.REACH)
    ).thing_id == "eunoia"


async def test_the_flag_is_read_off_the_thing_and_not_off_the_room(house):
    """What `_nearest` is actually asking, checked directly.

    The rule is about the thing's own `room_id`, not about how this copy
    came to be in reach, because being declared everywhere is what makes a
    word a candidate in nine rooms at once. Asserted on both sides: a
    fixture standing in one room is not flagged, so the rule cannot be
    quietly excluding everything."""
    await content_loader.load_content(content_module.load_files())

    here = await reach._gather(GUILD_A, ALICE, "DI", Scope.REACH)

    assert here["eunoia"].everywhere is True
    assert here["sideboard"].everywhere is False
    assert here["dining_table"].everywhere is False
