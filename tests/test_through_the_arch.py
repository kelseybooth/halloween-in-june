"""Drop 25: the Dining Room and the Kitchen, and the two doors that stay shut.

The ground floor was one drop and is now two. The Dining Room, the
Kitchen, everything in them, the arch from the Entryway and the swinging
door between them arrive at 25; the Courtyard, the Living Room, the wide
doorway and the back door stay at 30. So drop 25 is two rooms with one
way in, one way between, and no way out of the Kitchen except back
through the Dining Room.

**What this file is for.** Every decision above is a cell in a
spreadsheet, and the engine was built to read it - `arrived` is
`{d <= pointer}`, visibility is one filter on one query, and nothing
about splitting a release needed code. That is exactly why it is worth
asserting: there is no function anywhere named after drop 25, so nothing
else would notice if a single `since_drop` were typed wrong. The three
checks in `content.validate` catch a row left behind; these catch a room
that reads wrong or a door that opens when it should not.

**Why the stove and the pasta pot are here.** Both arrive at 25 with
nothing they can cook - the stove's herbs are the Courtyard's and its
chocolate is the Living Room's. They read correctly anyway, and the
reason is worth keeping where somebody will find it: no refusal in this
game names the thing you are missing. A `requires` failure sends the
thing's own `use_fail` with `{name}` filled and nothing else, and the
writers wrote both of these about the player's hands rather than about
the house's inventory.
"""

import pytest

from conftest import ALICE, GUILD_A
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


THIS_DROP = 25
THE_GROUND_FLOOR = 30

ABSENT = "You don't see"
AMBIGUOUS = "Which one do you mean"
BACK_DOOR = "glazed back door there are steps, then tangled green"
SWINGING_DOOR = "A swinging door shows a sliver of a long table"
THE_ARCH = "An arched doorway opens on one side of the hall"
THE_WIDE_DOORWAY = "A wide doorway opens on the other"


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
async def arch(db):
    """Drop 25, the door open, Alice fed and standing in the Entryway.

    The drop goes in before the load and the load is told the guild, for
    the reason `test_the_ladder` spells out: the loader places stock into
    the servers it has heard of, and it hears about them from `users`.

    Fed, because both doorways are behind that gate - `fed_the_cat` is on
    fragment 6 and on the exits themselves, and drop 25 does not change
    it. `test_feeding` owns the gate.
    """
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(GUILD_A, channels=[halloween], members=[FakeMember(ALICE)])
    await db.ensure_user_exists(ALICE, GUILD_A)
    await database.set_setting(GUILD_A, resolve.DROP_KEY, THIS_DROP)
    await content_loader.load_content(content_module.load_files(), guild_ids=[GUILD_A])
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    await db.start_game(ALICE, GUILD_A, "EN", await resolve.rooms_open_at_launch())
    await db.notice(GUILD_A, ALICE, content_module.FED_THE_CAT)
    return db, guild, halloween, rooms


def thread(arch, room_name):
    _, _, halloween, _ = arch
    return next(t for t in halloween.threads if t.name == room_name)


async def run(arch, command, arg=None, *, room, who=ALICE):
    db, guild, _, rooms = arch
    await db.update_current_room(who, GUILD_A, room)
    interaction = FakeInteraction(
        who, GUILD_A, guild=guild, channel=thread(arch, rooms[room])
    )
    args = () if arg is None else (arg,)
    await command.callback(interaction, *args)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


async def where(db, who=ALICE) -> str:
    return (await db.get_game_state(who, GUILD_A)).current_room


async def reads(room, who=ALICE) -> str:
    """The room's paragraph, with the markup taken back off.

    Two layers of it. The marker bolds every noun a player can act on,
    and `_describe_room` italicises every fragment they have not read
    before - so a first look at a room is almost entirely punctuation.
    What is asked here is which sentences the paragraph is made of,
    which is a different question from how they are dressed.

    `unlocked` is the gates, and it has to be passed: six of the
    Entryway's eight fragments are behind `fed_the_cat`, and a caller
    that leaves it out reads the hall as an unfed player would - one
    sentence, and none of the ones this file is about.
    """
    unlocked = await bot._unlocked_for(GUILD_A, who)
    text = await bot._describe_room(
        GUILD_A, who, room, resolve.DEFAULT_STATE, unlocked
    )
    return (text or "").replace("*", "").replace("_", "")


async def the_ground_floor_opens():
    await resolve.set_current_drop(GUILD_A, THE_GROUND_FLOOR)


# --------------------------------------------------------------------------
# The Kitchen, with the back door taken out of its paragraph
# --------------------------------------------------------------------------


async def test_the_kitchen_does_not_mention_the_back_door_yet(arch):
    """The clause was already the last thing in the paragraph, so it
    split off into a fragment of its own with nothing renumbered and no
    reading order changed - which is why the Kitchen's half of this
    change cost the writers nothing."""
    kitchen = await reads("KI")

    assert SWINGING_DOOR in kitchen
    assert BACK_DOOR not in kitchen


async def test_and_mentions_it_when_the_courtyard_opens(arch):
    await the_ground_floor_opens()

    kitchen = await reads("KI")

    assert SWINGING_DOOR in kitchen
    assert BACK_DOOR in kitchen


async def test_the_sentence_arrives_last_and_not_in_the_middle(arch):
    """Fragments are assembled by number and never by arrival order, so
    the new one reads where the writers put it: after the swinging door,
    at the end, exactly where the clause was."""
    await the_ground_floor_opens()

    kitchen = await reads("KI")

    assert kitchen.index(SWINGING_DOOR) < kitchen.index(BACK_DOOR)
    assert kitchen.rstrip().endswith("then tangled green.")


# --------------------------------------------------------------------------
# And no way through it
# --------------------------------------------------------------------------


async def test_the_back_door_is_not_a_place_you_can_go(arch):
    db, *_ = arch

    reply = replies(await run(arch, bot.go, "back door", room="KI"))

    assert ABSENT in reply
    assert await where(db) == "KI"


async def test_nor_is_the_courtyard_by_name(arch):
    """`courtyard` is one of the back door's own aliases, which is how a
    player says where they want to end up rather than what they want to
    open. Both are the same row and both are gone until 30."""
    db, *_ = arch

    reply = replies(await run(arch, bot.go, "courtyard", room="KI"))

    assert ABSENT in reply
    assert await where(db) == "KI"


async def test_and_both_work_the_moment_the_courtyard_opens(arch):
    db, *_ = arch
    await the_ground_floor_opens()

    await run(arch, bot.go, "back door", room="KI")

    assert await where(db) == "CO"


async def test_the_swinging_door_is_the_only_way_out_of_the_kitchen(arch):
    """Which is the shape of drop 25: in through the arch, between
    through the swinging door, and back the same way."""
    db, *_ = arch

    await run(arch, bot.go, "swinging door", room="KI")

    assert await where(db) == "DI"


# --------------------------------------------------------------------------
# The Entryway, with one doorway instead of two
# --------------------------------------------------------------------------


async def test_the_entryway_offers_the_arch_and_not_the_wide_doorway(arch):
    hall = await reads("EN")

    assert THE_ARCH in hall
    assert THE_WIDE_DOORWAY not in hall


async def test_and_offers_both_at_the_ground_floor(arch):
    await the_ground_floor_opens()

    hall = await reads("EN")

    assert THE_ARCH in hall
    assert THE_WIDE_DOORWAY in hall


async def test_the_staircase_still_reads_after_the_doorways(arch):
    """The cost of splitting the approved sentence in two: the
    staircase's three state rows moved from fragment 7 to 8, which
    orphans every `seen.EN.7` and italicises that sentence once for a
    player who had already read it. What must not change is the order it
    reads in."""
    await the_ground_floor_opens()

    hall = await reads("EN")

    assert hall.index(THE_ARCH) < hall.index(THE_WIDE_DOORWAY)
    assert hall.index(THE_WIDE_DOORWAY) < hall.index("grand staircase")


async def test_the_arch_opens_the_dining_room(arch):
    db, *_ = arch

    await run(arch, bot.go, "dining room", room="EN")

    assert await where(db) == "DI"


async def test_the_living_room_does_not_open(arch):
    """**And is refused rather than corrected into the arch.** This is
    the one thing drop 25 found that was not in the spreadsheets:
    `living room` is two edits from `dining room`, so the forgiving pass
    walked a player who had spelled it correctly through the other
    doorway and said nothing about it. The fix is in `reach.find` and
    `test_reach` owns the rule; this is the case that found it."""
    db, *_ = arch

    reply = replies(await run(arch, bot.go, "living room", room="EN"))

    assert ABSENT in reply
    assert await where(db) == "EN"


async def test_doorway_means_the_arch_while_it_is_the_only_one(arch):
    """A free one. `doorway` is an alias of both exits, so in the
    finished hall the word raises the ambiguity prompt; with one doorway
    open it can only mean the arch."""
    db, *_ = arch

    reply = replies(await run(arch, bot.go, "doorway", room="EN"))

    assert AMBIGUOUS not in reply
    assert await where(db) == "DI"


async def test_and_goes_back_to_being_ambiguous_at_thirty(arch):
    """Which is not a regression. It is how the hall reads today, and
    what drop 25 does is postpone it."""
    db, *_ = arch
    await the_ground_floor_opens()

    reply = replies(await run(arch, bot.go, "doorway", room="EN"))

    assert AMBIGUOUS in reply
    assert await where(db) == "EN"


# --------------------------------------------------------------------------
# Two rooms, and not four
# --------------------------------------------------------------------------


async def test_two_rooms_arrive_and_the_other_two_wait(arch):
    """**A room arrives with its description**, so this is read off
    `room_text` and not off `rooms.tsv` - which carries no drop number
    and would answer yes to all four at drop 0."""
    here = await resolve.arrived_rooms(GUILD_A)

    assert {"DI", "KI"} <= here
    assert not {"CO", "LI"} & here


async def test_and_all_four_at_the_ground_floor(arch):
    await the_ground_floor_opens()

    here = await resolve.arrived_rooms(GUILD_A)

    assert {"DI", "KI", "CO", "LI"} <= here


# --------------------------------------------------------------------------
# What the cat can eat
# --------------------------------------------------------------------------


async def test_the_tuna_comes_out_of_the_sideboard(arch):
    """A source and its yield are one thing, so the can has to move with
    the cupboard: `reach` applies the visibility filter to the source's
    id and then files the candidate under what it hands out."""
    db, *_ = arch

    await run(arch, bot.take, "tuna", room="DI")

    assert await database.carried_of(ALICE, GUILD_A, "cat_food_tuna") == 1


async def test_and_the_gourmet_out_of_the_cake_box(arch):
    db, *_ = arch

    await run(arch, bot.take, "gourmet", room="KI")

    assert await database.carried_of(ALICE, GUILD_A, "cat_food_gourmet") == 1


async def test_the_chicken_is_still_the_living_rooms_and_the_bedrooms(arch):
    """The flavour that looks as though it should have come too. Its two
    stashes are under the sofa and in the bedroom, so it stays where they
    are - drop 25 brings two flavours, not three."""
    visible = await resolve.visible_thing_ids(GUILD_A)

    assert "cat_food_tuna" in visible
    assert "cat_food_gourmet" in visible
    assert "cat_food_chicken" not in visible


# --------------------------------------------------------------------------
# Three fixtures with nothing to do, and no new copy for any of them
# --------------------------------------------------------------------------


async def test_the_stove_refuses_in_the_writers_own_words(arch):
    """It needs herbs, dark chocolate and a spice jar; the first two are
    the Courtyard's and the Living Room's. **No new text row.** A
    `requires` failure sends the thing's own `use_fail` with `{name}`
    filled and nothing else, so a refusal cannot name what is missing
    even when it wants to - and this one was written about the player's
    hands instead."""
    reply = replies(await run(arch, bot.use, "stove", room="KI"))

    assert "you don't have all of it yet" in reply


async def test_the_pasta_pot_has_been_doing_this_since_drop_thirty(arch):
    """Parked on pasta that sits at 99, so it arrived empty-handed one
    release ago and reads the same way at 25. The precedent, not a new
    problem."""
    reply = replies(await run(arch, bot.use, "pasta pot", room="KI"))

    assert "nothing to put in it" in reply
