"""Drop 1's channel scenery: the fog, the fence, and what is under them.

Playtesters reported drop 1 as empty. They were right, and the reason
was structural rather than a thin paragraph: the channel was forbidden
prose, so `/look` printed `Also here: cat bed` and there was nothing
else in the world to type. Ten scenery nouns and a six-fragment
description give the drop something to be about, and the fragments
arrive in two stages so that looking at the bed changes the view.

What is tested here is the staging, because that is where the bugs
live. The prose itself is the writers' and is asserted only where the
engine's behaviour depends on it.
"""

import dataclasses
import re

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import hints
import reach
import resolve
import world


@pytest.fixture
async def channel(db):
    """A server on drop 1, where the scenery lives."""
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
    return db, guild, halloween


async def look(channel, thing=None, who=ALICE):
    _, guild, halloween = channel
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await bot.look.callback(interaction, thing)
    return interaction


async def use(channel, thing, who=ALICE):
    _, guild, halloween = channel
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await bot.use.callback(interaction, thing)
    return interaction


# --------------------------------------------------------------------------
# The two stages
# --------------------------------------------------------------------------


async def test_a_new_player_sees_three_fragments(channel):
    """The road, the fence, the smell of the air. Not the branches."""
    reply = (await look(channel)).reply

    assert "**road**" in reply
    assert "**fence**" in reply
    assert "cold and wet earth" in reply
    assert "**Branches**" not in reply
    assert "**Tire tracks**" not in reply


async def test_looking_at_the_bed_opens_the_other_three(channel):
    await look(channel, "cat bed")

    reply = (await look(channel)).reply

    assert "**Branches**" in reply
    assert "**Tire tracks**" in reply
    assert "too square to be trees" in reply


async def test_an_unlocked_fragment_takes_its_numbered_place(channel):
    """Ordered by `fragment`, never by arrival.

    The branches are sentence two. Appending them on unlock would put
    them after the tire tracks and read as a different paragraph to the
    player who earned them than to the writer who wrote it.
    """
    await look(channel, "cat bed")

    reply = (await look(channel)).reply

    assert reply.index("**Branches**") < reply.index("**fence**")
    assert reply.index("**fence**") < reply.index("**Tire tracks**")
    assert reply.index("**Tire tracks**") < reply.index("cold and wet earth")


async def test_the_stage_is_per_player(channel):
    """Alice looking at the bed does not thin Bob's fog.

    The gate reads the hint ladder's per-player row, which is the whole
    reason this could be done without the general per-player
    `present_when` the V3.2 list is holding.
    """
    await look(channel, "cat bed", who=ALICE)

    assert "**Branches**" in (await look(channel, who=ALICE)).reply
    assert "**Branches**" not in (await look(channel, who=BOB)).reply


async def test_the_channel_is_still_bare_at_drop_zero(channel):
    """The scenery is drop 1's, and drop 0 is the cat alone."""
    await resolve.set_current_drop(GUILD_A, 0)

    reply = (await look(channel)).reply

    assert "**road**" not in reply
    assert "Nothing here but the cat" in reply


# --------------------------------------------------------------------------
# The notice
# --------------------------------------------------------------------------


async def test_the_first_look_at_the_bed_says_the_fog_thinned(channel):
    """Otherwise nothing tells the player to look again, and the three
    sentences they unlocked are never read."""
    reply = (await look(channel, "cat bed")).reply

    assert "the fog has thinned" in reply


async def test_it_is_not_labelled_as_a_hint(channel):
    """Italic, unlabelled, and not from the rail. It reports something
    that happened rather than recommending an action, and the rail's
    budget is spent on `/use`."""
    reply = (await look(channel, "cat bed")).reply

    assert "*When you look up from the bed, the fog has thinned slightly.*" in reply
    assert "Hint: When you look up" not in reply

    # Above the hint: it reports what happened, the hint recommends what
    # to do, and the rail owns the last line everywhere else.
    assert reply.index("fog has thinned") < reply.index("Hint:")


async def test_it_fires_once(channel):
    await look(channel, "cat bed")

    assert "the fog has thinned" not in (await look(channel, "cat bed")).reply


async def test_it_does_not_fire_for_other_scenery(channel):
    assert "the fog has thinned" not in (await look(channel, "fence")).reply


# --------------------------------------------------------------------------
# Looking at the nouns
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed",
    ["road", "fog", "fence", "ditch", "ruts", "leaves", "field", "wasp nest"],
)
async def test_every_bolded_noun_answers(channel, typed):
    """Bolding is a promise. The loader checks the content side of it;
    this checks that `/look` in the channel actually resolves them."""
    await look(channel, "cat bed")

    reply = (await look(channel, typed)).reply

    assert "no such thing" not in reply
    assert len(reply) > 40


async def test_a_second_layer_is_reached_through_the_first(channel):
    """The ditch is named by the road, not by the paragraph. Two or three
    nouns opening onto two or three more is the shape the drop needed."""
    road = (await look(channel, "road")).reply

    assert "**ditch**" in road
    assert "leaves" in (await look(channel, "ditch")).reply


async def test_an_alias_works(channel):
    assert "no such thing" not in (await look(channel, "mist")).reply


# --------------------------------------------------------------------------
# Using what cannot be used
# --------------------------------------------------------------------------


async def test_a_fixture_refuses_in_its_own_words(channel):
    """`use.default` is "you turn the {name} over in your hands", which is
    nonsense on a ditch - and `/use` is one of only two verbs drop 1 has,
    so every scenery noun is one command away from it."""
    reply = (await use(channel, "ditch")).reply

    assert "nothing to do with the ditch but look at it" in reply
    assert "over in your hands" not in reply


async def test_the_refusal_is_private(channel):
    assert (await use(channel, "fence")).was_private


async def test_a_refused_use_is_not_recorded(channel):
    """It never happened, so it must not count as a use - `thing_uses` is
    what cooldowns and achievements read."""
    from sqlalchemy import func, select

    await use(channel, "fence")

    async with database._require_session()() as session:
        rows = await session.scalar(
            select(func.count())
            .select_from(database.ThingUse)
            .where(database.ThingUse.thing_id == "fence")
        )

    assert rows == 0


async def test_a_house_fixture_is_left_alone(channel):
    """**The refusal is scoped to scenery, not to `takeable = no`.**

    The argument for it reads as though it should cover the stove too,
    and the work order words it that way. But a house fixture with a
    blank `use` cell falls through to `use.default` *and counts as a
    use*, which `test_verbs.py` pins on purpose because use counts feed
    achievements - so widening this would change shipped drop-3
    behaviour from a patch whose scope says the only thing that changes
    is what `/look` prints in the channel.

    Asserted on the cat bed, which is `takeable = no` and not scenery.
    """
    row = content_module.load_files().things_by_id[world.CAT_BED]

    assert row.takeable is False
    assert row.type != content_module.SCENERY


async def test_the_bed_still_works(channel):
    """The fixture refusal must not swallow a fixture that has use text."""
    reply = (await use(channel, "cat bed")).reply

    assert "nothing to do with" not in reply


async def test_the_wasp_nest_refuses_on_circumstance(channel):
    """Written now and unreachable until `/take` ships at drop 2 -
    somebody will try it on the first day it exists.

    **The refusal has to be a no for today, not a no forever.** A paper
    nest does not survive a winter, and the plan on the shelf is to put
    this one on the ground in a later drop and let the players who went
    after it in week one finally have it. A line like *there is no
    version of this where you end up holding it* would make the game a
    liar that day. So the refusal names the twenty feet, which stops
    being true the moment the nest is on the ground, and never the nest
    itself as something not to be had.

    *"That seems unwise"* opening it was a late call, made for the joke
    and against the advice written into the work order. Both are on the
    record; what this test guards is only the part that would break the
    game later.
    """
    rows = content_module.load_files().thing_text
    nest = [r for r in rows if r.entity_id == "wasp_nest"]
    refusal = next(r.text["take_fail"] for r in nest if r.state == "default")

    assert "twenty feet" in refusal
    for forever in ("never", "no version", "not yours", "cannot"):
        assert forever not in refusal.lower(), forever


# --------------------------------------------------------------------------
# The gate is the ladder's row, and nothing else
# --------------------------------------------------------------------------


async def test_the_gate_reads_the_ladder(channel):
    """Named rather than inferred, because the day the rail renames
    `DID_LOOK_BED` is the day the fog stops lifting, and the failure is
    silent - a paragraph that is simply shorter than it should be."""
    assert await bot._unlocked_for(GUILD_A, ALICE) == frozenset()

    await database.notice(GUILD_A, ALICE, hints.DID_LOOK_BED)

    assert await bot._unlocked_for(GUILD_A, ALICE) == frozenset(
        {content_module.LOOKED_AT_BED}
    )

# --------------------------------------------------------------------------
# Every noun, every alias, every refusal
# --------------------------------------------------------------------------

SCENERY = (
    "road", "fog", "branches", "fence", "ruts",
    "ditch", "leaves", "wasp_nest", "field", "tire_tracks",
    "stand", "shelves", "firewood_bin", "coin_slot",
)

# Playtesters tried both verbs on everything in the scene, so eight of
# the fourteen were given refusals of their own. The other six are
# terrain, and share one line about scale.
WRITES_ITS_OWN_REFUSAL = (
    "branches", "leaves", "fence", "wasp_nest",
    "stand", "shelves", "firewood_bin", "coin_slot",
)
TERRAIN = ("road", "fog", "ruts", "ditch", "field", "tire_tracks")


def _aliases():
    things = content_module.load_files().things_by_id
    return [(t, name) for t in SCENERY for name in things[t].names]


@pytest.mark.parametrize("thing_id,typed", _aliases())
async def test_every_alias_resolves(channel, thing_id, typed):
    """`/look posts`, `/look mud`, `/look culvert` and the other
    thirty-odd. Aliases are where a scene like this is won or lost: the
    player types the word they thought of, not the word in the row."""
    found = await reach.find(GUILD_A, ALICE, content_module.CHANNEL_ROOM, typed,
                             reach.Scope.REACH)

    assert isinstance(found, reach.Found), f"{typed!r} -> {found}"
    assert found.thing_id == thing_id


@pytest.mark.parametrize("thing_id", TERRAIN)
async def test_terrain_refuses_use_with_the_default(channel, thing_id):
    """Definition of done 3. None of the fourteen has `use` text and
    none should: a scenery row that pays out a relationship point is
    farmed by whoever finds the cheapest one, and the bed's once-a-day
    economy stops meaning anything."""
    name = content_module.load_files().things_by_id[thing_id].name

    reply = (await use(channel, name)).reply

    assert f"nothing to do with the {name} but look at it" in reply


@pytest.mark.parametrize("thing_id", WRITES_ITS_OWN_REFUSAL)
async def test_a_written_refusal_beats_the_default(channel, thing_id):
    """The eight that answer for themselves.

    A refusal and no success is already a shape the engine reads out of
    content, so these need no code - but they are the first scenery to
    use it, and the failure mode is silent: lose the row and the fence
    goes back to saying there is nothing to do with it but look at it,
    which is the generic line the playtest was about.
    """
    parsed = content_module.load_files()
    name = parsed.things_by_id[thing_id].name
    written = [
        r.text["use_fail"] for r in parsed.thing_text
        if r.entity_id == thing_id and r.state == "default"
    ]

    reply = (await use(channel, name)).reply

    assert reply == written[0]
    assert "nothing to do with" not in reply


async def test_no_scenery_row_has_use_text():
    """Asserted against the files rather than the rendered reply, so a
    `use` string added later fails here rather than quietly turning one
    of the ten into a second bed."""
    parsed = content_module.load_files()

    for row in parsed.thing_text:
        if row.entity_id in SCENERY:
            assert "use" not in row.text, row.entity_id


# --------------------------------------------------------------------------
# What the prose must not mention
# --------------------------------------------------------------------------


# The words a channel string must not contain before the house arrives.
# Four kinds of thing rather than a loose wordlist, because the channel prose
# is ordinary English and a wide list catches "the ground opens" and "one lets
# go" - which would train whoever next edits it to delete the check instead of
# the leak.
LEAK_WORDS = ("room", "rooms", "mailbox", "drive", "driveway", "door", "doors")


def leaking_words(prose: str) -> list[str]:
    """Which of the forbidden words this prose names.

    A function rather than a loop inside the test, so that the test and the
    guard beneath it run the **same** matcher. That is the whole point: this
    search spent months with two literal backspace characters where `\b` was
    meant, so it matched nothing, the assertion was `assert not ...`, and it
    passed on an empty result for as long as it existed.

    A guard with its own copy of the pattern would not have caught that - it
    would have gone on matching its own prose while this one matched nothing.
    Only a guard that comes through here can.
    """
    lowered = prose.lower()
    return [word for word in LEAK_WORDS if re.search(rf"\b{word}\b", lowered)]


async def test_nothing_from_a_later_drop_is_named():
    """The leak test. The mailbox is drop 2 and carries David's name with
    it; the house, its door and the drive are drop 3. A channel string
    that mentions one spends the reveal weeks early, for free.
    """
    parsed = content_module.load_files()

    # **Only the prose written before the reveal.** The channel holds the
    # house itself now, and the house's own description says "The front door
    # is shut" - which is the reveal happening rather than a leak of it. The
    # drop is read off the house rather than written down here, so moving it
    # moves this with it.
    houses = [t for t in parsed.things if t.thing_id == "house"]
    assert houses, "this check is anchored on the house and could not find it"
    reveal = houses[0].since_drop

    here = {
        t.thing_id
        for t in parsed.things
        if t.room_id == content_module.CHANNEL_ROOM and t.since_drop < reveal
    }
    blobs = [
        r.text.get("look", "")
        for r in parsed.room_text
        if r.entity_id == content_module.CHANNEL_ROOM and r.since_drop < reveal
    ]
    blobs += [
        v
        for r in parsed.thing_text
        if r.entity_id in here and r.since_drop < reveal
        for v in r.text.values()
    ]
    prose = " ".join(blobs)

    # The haystack has to be real. A filter that excluded every row would
    # pass this test for the wrong reason - the same vacuity as the broken
    # pattern, one step along - so something known to be in drop 1's channel
    # has to be in it.
    assert "fence" in prose.lower()

    assert leaking_words(prose) == []


def test_and_the_check_itself_still_catches_one():
    """**The guard that was missing.** The search above ran for months with
    two literal backspace characters where `\b` was meant: it matched
    nothing, the assertion was `assert not ...`, and the leak it exists to
    catch would have walked straight through. A terminal prints those bytes
    invisibly, which is how it survived being read.

    Planted prose rather than the house's own, so that rewording the house
    cannot turn this into a false alarm - and routed through
    `leaking_words`, so that breaking the pattern breaks this too.
    """
    assert leaking_words("You can see the front door from the end of the drive.") == [
        "drive",
        "door",
    ]
    assert leaking_words("The fence sags where the wire has gone slack.") == []


# --------------------------------------------------------------------------
# The three loader checks, each against a deliberately broken copy
# --------------------------------------------------------------------------


def _broken(mangle):
    parsed = content_module.load_files()
    mangle(parsed)
    return content_module.validate(parsed)


def test_the_shipped_files_pass_all_three():
    assert not content_module.validate(content_module.load_files())


def test_bolding_written_into_the_prose_fails():
    """**These two tests used to be one rule each, and are now one.**

    They guarded a checker that read the bolding in the files and made
    sure each marked word named something real, here, now: a
    `**lamppost**` with no row behind it was a word the game pointed at
    and the parser denied, and a drop-1 fragment bolding a drop-2 thing
    was the same failure arriving on a timer.

    Neither is a mistake anybody can make any more, because the asterisk
    is gone from the writers' hands. The engine marks what is in reach,
    so a word with no row behind it is never marked and a thing that has
    not arrived is left plain - which `test_bolding.py` holds directly
    rather than through a mangled copy of the channel.

    What is left to guard is the habit: a pair of asterisks typed into
    the prose is a second claim about a word the engine is already
    deciding, and the loader refuses it whatever the word is.
    """

    def mangle(parsed):
        for row in parsed.room_text:
            if row.entity_id == content_module.CHANNEL_ROOM and row.fragment == 10:
                row.text["look"] += " A **lamppost** stands here."

    assert any("has bolding written into it" in p for p in _broken(mangle))


def test_bolding_written_into_a_things_text_fails_too():
    """The other file. Both are prose a player reads in a room, and the
    engine marks both."""

    def mangle(parsed):
        for row in parsed.thing_text:
            if row.entity_id == "road":
                row.text["look"] += " A **lamppost** stands here."

    assert any("has bolding written into it" in p for p in _broken(mangle))


def test_dropping_a_scenery_noun_from_the_prose_fails():
    """The inverse, and the one that will fire during authoring: take
    *ruts* out of `road.look` and the row becomes unreachable by any
    path, with nothing logged.

    **This used to be about unbolding**, back when the asterisks were
    written by hand and trimming a pair was the whole mistake. Writers
    cannot make that mistake any more - there is nothing to trim, and
    the engine bolds what it finds - so the mistake that is left is the
    one underneath it: prose that never says the word at all.
    """

    def mangle(parsed):
        for row in parsed.thing_text:
            if row.entity_id == "road":
                row.text["look"] = row.text["look"].replace("Ruts", "Grooves")

    assert any("names scenery ruts" in p for p in _broken(mangle))


def test_a_second_person_take_line_fails():
    """`/take` and `/drop` are the only texts in the game with an
    audience other than the person who typed the command, and for a
    release they did not know it. All thirty-two were rewritten; this
    is what stops the thirty-third arriving in the old voice."""

    def mangle(parsed):
        for row in parsed.thing_text:
            if row.text.get("take"):
                row.text["take"] = "You pocket it, guiltily."
                return

    assert any("posted to the room" in p for p in _broken(mangle))


def test_a_misspelled_gate_fails():
    """The enum has one member, which is exactly why this is checked. A
    typo in that one word raises nothing: the fragment loads, the gate
    never matches, and the sentence is invisible to every player
    forever."""

    def mangle(parsed):
        parsed.room_text[:] = [
            dataclasses.replace(row, visible_when="looked_at_the_bed")
            if row.visible_when
            else row
            for row in parsed.room_text
        ]

    assert any("not a visibility gate" in p for p in _broken(mangle))


def test_a_scenery_alias_shared_with_anything_else_fails():
    """`tree` and `wire` both failed this on the first run, which is why
    neither is an alias today - `tree` is already the Courtyard's and
    `wire` becomes the copper wire's the day a player can carry one
    outdoors."""

    def mangle(parsed):
        things = parsed.things_by_id
        fence = things["fence"]
        parsed.things[parsed.things.index(fence)] = dataclasses.replace(
            fence, aliases=fence.aliases + ("wire",)
        )

    assert any("scenery fence answers to 'wire'" in p for p in _broken(mangle))


# --------------------------------------------------------------------------
# Back to stage one
# --------------------------------------------------------------------------


async def test_resetting_a_player_returns_them_to_stage_one(channel):
    """Definition of done 6. `forget_player` is table-driven, so the
    notices went with everything else - but the staging is a new reason
    to care, and a reset that left stage 2 latched would make the
    sequence testable exactly once per tester per server."""
    await look(channel, "cat bed")
    assert "**Branches**" in (await look(channel)).reply

    await database.forget_player(GUILD_A, ALICE)

    reply = (await look(channel)).reply
    assert "**Branches**" not in reply
    assert "the fog has thinned" in (await look(channel, "cat bed")).reply

# --------------------------------------------------------------------------
# The roadside stand
# --------------------------------------------------------------------------


async def take(channel, thing, who=ALICE):
    _, guild, halloween = channel
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await bot.take.callback(interaction, thing)
    return interaction


async def test_the_stand_is_the_first_thing_the_player_reads(channel):
    """Playtesters found a cat bed at a bare roadside odd, and they were
    right - the bed had nothing to be in. The stand is what the opening
    sentence is now for, and the order matters: where you are, then
    everything outward of it.

    **The viewpoint is the load-bearing part.** The paragraph opens
    *onto* the road rather than describing the stand from the road,
    which is what keeps the player under the roof - and a player
    standing on a road for no reason beside a cat bed is where this
    whole thread started.
    """
    reply = (await look(channel)).reply

    assert reply.startswith("A derelict, tin-roofed **farm stand**")
    assert reply.index("**farm stand**") < reply.index("**fence**")


async def test_the_stand_reveals_its_own_interior(channel):
    """One level down, not a staged fragment.

    The shelves, the bin and the slot were two fragments of the channel
    paragraph until the 21 October trim, which cut the description back
    to what a player takes in at a glance. They live in the stand's own
    `look` now - the same nesting as the ruts inside `road.look` and the
    wasp nest inside `branches.look` - so all four are still reachable
    and the opening paragraph is one sentence.

    **Four children is the most any parent carries in this scene**, and
    the cat bed is one of them: take a noun out of this string and the
    row behind it stops being reachable by anything, which for the bed
    would mean drop 1's whole mechanic sitting in a room that never
    names it.
    """
    reply = (await look(channel)).reply
    assert "**bin**" not in reply

    inside = (await look(channel, "farm stand")).reply

    # The name of each, which is what the engine marks: "sign" is
    # another of the shelves' words and "bin" another of the firewood
    # bin's, and a thing is marked once however many of its words the
    # sentence happens to use.
    for noun in ("**shelves**", "**plank bin**", "**coin slot**",
                 "**cat bed**"):
        assert noun in inside, noun


@pytest.mark.parametrize("typed,thing_id", [
    ("sign", "shelves"),
    ("sweet corn", "shelves"),
    ("blueberries", "shelves"),
    ("bin", "firewood_bin"),
    ("slot", "coin_slot"),
    ("cash box", "coin_slot"),
    ("honor box", "coin_slot"),
    ("cooler", "cat_bed"),
])
async def test_a_trap_answers_instead_of_shrugging(channel, typed, thing_id):
    """**Every one of these is a word the prose spends without stocking.**

    The sign lists sweet corn and blueberries that are not objects and
    never will be; the slot names a cash box that was unbolted and
    carried off; the bed sits on a cooler's footprint. A player who
    types any of them deserves the sentence that explains the absence,
    not "whatever that is, this house doesn't have one."

    `cooler` is the one that points at something that is not scenery, so
    it also pins that alias lookup does not filter by type.
    """
    found = await reach.find(GUILD_A, ALICE, content_module.CHANNEL_ROOM, typed,
                             reach.Scope.REACH)

    assert isinstance(found, reach.Found), f"{typed!r} -> {found}"
    assert found.thing_id == thing_id


@pytest.mark.parametrize("thing_id", TERRAIN)
async def test_terrain_refuses_take_on_scale(channel, thing_id):
    """`take_fail.fixture` reads "the {name} isn't yours to carry off",
    which assumes an owner and is nonsense on fog. Terrain is a type so
    that the content file says which joke a row is in - the same way
    `take_fail.exit` is already chosen - rather than the engine keeping
    a list of six ids."""
    await resolve.set_current_drop(GUILD_A, 2)
    name = content_module.load_files().things_by_id[thing_id].name

    reply = (await take(channel, name)).reply

    assert reply == "You would have to take the whole place with it."


@pytest.mark.parametrize("thing_id", WRITES_ITS_OWN_REFUSAL)
async def test_a_built_thing_refuses_in_its_own_words(channel, thing_id):
    """The other eight. Nothing built falls to the terrain line, and
    nothing terrain falls to the one about an owner."""
    await resolve.set_current_drop(GUILD_A, 2)
    parsed = content_module.load_files()
    name = parsed.things_by_id[thing_id].name
    written = next(
        r.text["take_fail"] for r in parsed.thing_text
        if r.entity_id == thing_id and r.state == "default"
    )

    reply = (await take(channel, name)).reply

    assert reply == written
    assert "take the whole place" not in reply
    assert "isn't yours to carry off" not in reply


def test_a_scenery_word_may_name_a_fixture_in_another_room():
    """**The stand's shelves are the reason this check narrowed.**

    It first read "a scenery word must mean nothing else anywhere in the
    table", which is wider than either of its own arguments: the bag
    travels, and one outdoors may one day sit beside another. A fixture
    bolted to the Library satisfies neither - `/look` is scoped to the
    room the player is standing in - and enforcing it there would have
    cost the stand its shelves to prevent a confusion nobody could have.
    """
    parsed = content_module.load_files()
    claims = {
        t.thing_id for t in parsed.things if "shelves" in [n.lower() for n in t.names]
    }

    assert len(claims) > 1, claims
    assert not content_module.validate(parsed)


def test_a_fixture_no_sentence_names_fails():
    """The third kind of unlisted thing, and the last one to get a check.

    `Also here:` carries finite takeables and nothing else, which the
    house has always done and the channel now does too - so a fixture is
    revealed by prose or it is revealed by nothing. Sources have been
    checked since 2b and scenery since this file; fixtures worked only
    because the writers happened to name all ninety-odd of them.
    """

    def mangle(parsed):
        for row in parsed.room_text:
            if row.entity_id == "KI":
                row.text["look"] = re.sub(
                    r"[Tt]rash can", "receptacle", row.text["look"]
                )

    assert any("fixture trash_can is named nowhere" in p for p in _broken(mangle))


def test_a_fixture_may_not_reveal_itself():
    """Half the fixtures in the house say their own name in their own
    `look`, so counting that would pass every row in the table and prove
    nothing. The cat bed is the live case: drop 1's reply is prose
    alone, and without somebody else naming it the drop's whole
    mechanic sits in a room that never mentions it.

    **Three things name it now**, which is why the mangle has to be so
    thorough: the opening fragment, since the 22 October rewrite put
    *containing a cat bed but no produce* in it; `stand.look`, with *a
    cat bed sits in place of the cooler*; and the slot's sentence,
    because *egg cooler* is one of the bed's own aliases. The first of
    those is the good one - the bed used to be findable only by
    looking at the stand first, or by taking the hint."""

    def mangle(parsed):
        for row in parsed.thing_text:
            if row.entity_id == "stand":
                row.text["look"] = "Bare planks, and a tin roof that holds."
        for row in parsed.room_text:
            if row.entity_id == content_module.CHANNEL_ROOM and row.fragment == 10:
                row.text["look"] = "A derelict farm **stand** by a **road**."

    assert any("fixture cat_bed is named nowhere" in p for p in _broken(mangle))


def test_a_scenery_word_that_names_something_in_the_same_room_fails():
    """What the narrowing kept. Two rows answering to one word in one
    view resolve to whichever sorts first and log nothing."""

    def mangle(parsed):
        things = parsed.things_by_id
        fog = things["fog"]
        parsed.things[parsed.things.index(fog)] = dataclasses.replace(
            fog, aliases=fog.aliases + ("cat bed",)
        )

    assert any("scenery fog answers to 'cat bed'" in p for p in _broken(mangle))
