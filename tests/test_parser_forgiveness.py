"""Three parser fixes from the beta log, 23 to 27 October.

About 150 of 2,876 commands failed because the game did not know the word the
player typed, and most of those players were typing something they had just
read. The three fixes are independent: new aliases for words the prose puts in
front of people, a forgiving second pass for typos, and `around`/`room`/`here`
meaning the room you are standing in.

Two things here are deliberately *not* what the work order asked for, and both
are pinned by a test so the next person reads the reason rather than the gap:

- `wire` on the fence and `tin` on the farm stand are refused by the content
  checker, because both words belong to a takeable object that can be carried
  into the channel. `_check_scenery_aliases_are_unique` was written for exactly
  the `wire` case and names it.
- `roaf` and `rood` are not corrected to `road`, because the farm stand's
  `roof` sits the same single edit away. The rule the work order gave says not
  to guess between two things equally close, and this is that rule working.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import reach
import resolve

CHANNEL = content_module.CHANNEL_ROOM
WAND = "feather_wand"
BALL = "crinkle_ball"


@pytest.fixture
async def channel(db):
    """Drop 2: the scenery, the cat, the bed and both toys loose in the room."""
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
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    for toy in (WAND, BALL):
        await database.place_in_room(GUILD_A, CHANNEL, toy, 1)
    bot.forget_public_pets()
    return db, guild, halloween


async def run(channel, command, thing=None, who=ALICE):
    _, guild, halloween = channel
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await command.callback(interaction, thing)
    return interaction


async def resolves(word, scope=reach.Scope.REACH, who=ALICE):
    return await reach.find(GUILD_A, who, CHANNEL, word, scope)


async def logged(db):
    rows = await database.recent_interactions(GUILD_A, ALICE, limit=50)
    return [r.detail for r in rows if r.detail and r.detail.startswith("fuzzy=")]


# --------------------------------------------------------------------------
# 1. The new aliases
# --------------------------------------------------------------------------

NEW_WORDS = [
    ("strands", "fence"),
    ("chaff", "shelves"),
    ("dried stem", "shelves"),
    ("stem", "shelves"),
    ("egg", "shelves"),
    ("boards", "shelves"),
    ("splinters", "firewood_bin"),
    ("splinter", "firewood_bin"),
    ("trees", "branches"),
    ("tree", "branches"),
    ("water", "ditch"),
    ("trickle", "ditch"),
    ("middle distance", "fog"),
    ("paw", "eunoia"),
    ("paws", "eunoia"),
    ("eyes", "eunoia"),
    ("tail", "eunoia"),
    ("catbed", "cat_bed"),
    ("featherwand", WAND),
    ("ribbon", WAND),
    ("stick", WAND),
    ("coinslot", "coin_slot"),
]


@pytest.mark.parametrize("word,thing_id", NEW_WORDS)
async def test_every_new_word_resolves_to_its_thing(channel, word, thing_id):
    found = await resolves(word)

    assert isinstance(found, reach.Found), word
    assert found.thing_id == thing_id


@pytest.mark.parametrize("word,thing_id", NEW_WORDS)
async def test_a_new_word_is_an_exact_match_not_a_near_one(channel, word, thing_id):
    """An alias is the word itself. If one of these only resolved through the
    typo pass it would be one edit away from working, and the next alias added
    nearby would silently take it."""
    found = await resolves(word)

    assert found.fuzzy is None, word


async def test_the_middle_distance_is_the_fog(channel):
    """Four players typed it, every one of them after a toy refusal told them
    the cat was looking at the middle distance."""
    reply = (await run(channel, bot.look, "middle distance")).reply

    assert "lies low and even" in reply


async def test_catbed_fluffs_the_bed(channel):
    """End to end, because the alias is only worth having if the verb runs."""
    await run(channel, bot.use, "catbed")

    assert await database.get_relationship(ALICE, GUILD_A) > 0


async def test_wire_and_tin_were_not_added(channel):
    """Both belong to a takeable object - the copper wire and a tin of cat
    food - so a player carrying one outdoors would make the word mean two
    things in one view. The content checker refuses it, and the fence keeps
    `wire fence` and `fencing` either way."""
    assert isinstance(await resolves("wire"), reach.NotFound)
    assert isinstance(await resolves("tin"), reach.NotFound)
    assert isinstance(await resolves("wire fence"), reach.Found)


# --------------------------------------------------------------------------
# 2. Forgiving a typo
# --------------------------------------------------------------------------

TYPOS = [
    ("crincle ball", BALL),
    ("crinkle vall", BALL),
    ("feather wamd", WAND),
    ("feathef", WAND),
    ("cat ber", "cat_bed"),
    ("car bed", "cat_bed"),
]


@pytest.mark.parametrize("typed,thing_id", TYPOS)
async def test_a_typo_reaches_the_thing_it_meant(channel, typed, thing_id):
    found = await resolves(typed)

    assert isinstance(found, reach.Found), typed
    assert found.thing_id == thing_id


@pytest.mark.parametrize("typed,thing_id", TYPOS)
async def test_the_correction_is_reported_on_the_result(channel, typed, thing_id):
    found = await resolves(typed)

    assert found.fuzzy is not None
    assert found.fuzzy.startswith(f"{typed}→")


async def test_an_exact_word_never_loses_to_a_typo(channel):
    """`road` is a word in the room and `roof` is one edit from it. The exact
    pass runs first and returns, so the forgiving pass never sees it."""
    found = await resolves("road")

    assert found.thing_id == "road"
    assert found.fuzzy is None


async def test_the_cats_kitten_sits_two_edits_from_the_kitchen(channel):
    """**Why `/look` runs its passes in rank order.** `kitten` is a word the
    cat answers to in every room, and it is two edits from `kitchen` - so with
    the typo pass running before the room's name, `/look kitchen` in the
    Kitchen described the cat instead of the room.

    The end-to-end guard is `test_naming_your_own_room_describes_it` in
    test_verbs.py. This is the collision underneath it: the word reaches the
    cat only through the forgiving pass, which is exactly why the room's own
    name has to be tried between the two.
    """
    assert reach._distance("kitchen", "kitten", 2) == 2
    assert (await resolves("kitchen")).thing_id == "eunoia"

    exact_only = await reach.find(
        GUILD_A, ALICE, CHANNEL, "kitchen", reach.Scope.REACH, fuzzy=False
    )
    assert isinstance(exact_only, reach.NotFound)


async def test_two_things_equally_close_are_refused(channel):
    """`roaf` is one edit from the road and one edit from the farm stand's
    roof. The work order's rule is not to guess, so this is a refusal the
    player can read and retype rather than a coin flip."""
    assert isinstance(await resolves("roaf"), reach.NotFound)
    assert isinstance(await resolves("rood"), reach.NotFound)


async def test_crickle_is_the_price_of_trickle(channel):
    """**The work order's two halves collide here, and this is the seam.**
    `trickle` was added to the ditch in part 1 because a player typed it, and
    it sits one edit from `crinkle` - so `crickle`, a typo in part 2's own
    list, now has two things equally close and is refused.

    Kept this way round deliberately. `trickle` is a word players type and it
    resolves for every one of them; `crickle` is a typo whose fallback is a
    refusal they can read and retype. Dropping the alias to rescue the typo
    would trade a certainty for a guess.
    """
    assert isinstance(await resolves("crickle"), reach.NotFound)
    assert (await resolves("trickle")).thing_id == "ditch"
    assert (await resolves("crinkle")).thing_id == BALL


async def test_a_short_word_is_not_corrected_across_two_edits(channel):
    """`wire` is two edits from the road's `dirt`, and was reaching it before
    the tolerance was scaled by length. A wrong answer to a word three players
    typed is worse than the refusal it replaced."""
    assert reach._distance("wire", "dirt", 2) == 2
    assert isinstance(await resolves("wire"), reach.NotFound)


async def test_a_long_word_still_gets_both_edits(channel):
    """The other side of the same rule: the band is only tight where two
    edits would be most of the word."""
    assert reach._tolerance("wire") == 1
    assert reach._tolerance("crinkle") == 2


async def test_a_short_word_is_left_alone(channel):
    """At three letters, two edits is most of the word: `toi` is as close to
    the toy as it is to several other things."""
    assert isinstance(await resolves("toi"), reach.NotFound)


async def test_three_letters_is_not_fuzzy_matched_even_when_it_is_close(channel):
    """`fo` and `fog` differ by one, and `fop` would too. The length rule is
    on the typed word, so neither reaches the fog."""
    assert isinstance(await resolves("fop"), reach.NotFound)


async def test_a_word_too_far_from_anything_is_still_refused(channel):
    """Two edits is the limit. `featehry` is three from `feather`, which is
    the shape of typo this rule deliberately does not reach."""
    assert isinstance(await resolves("featehry"), reach.NotFound)


async def test_nonsense_is_still_nonsense(channel):
    assert isinstance(await resolves("xylophone"), reach.NotFound)


async def test_take_works_through_a_typo_and_logs_it(channel):
    """The work order's acceptance test, end to end."""
    db, *_ = channel

    await run(channel, bot.take, "crincle ball")

    assert await database.carried_of(ALICE, GUILD_A, BALL) == 1
    assert "fuzzy=crincle ball→crinkle ball" in await logged(db)


async def test_an_exact_match_logs_nothing(channel):
    db, *_ = channel

    await run(channel, bot.take, "crinkle ball")

    assert await logged(db) == []


async def test_a_refused_verb_still_logs_the_correction(channel):
    """Logged from the resolver rather than the verbs, so a correction that
    led somewhere useless is as findable as one that worked - which is the
    half worth auditing."""
    db, *_ = channel

    await run(channel, bot.take, "cat ber")

    assert "fuzzy=cat ber→cat bed" in await logged(db)


# --------------------------------------------------------------------------
# 3. Looking around
# --------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["around", "room", "here", "Around", " here "])
async def test_looking_around_reads_as_a_bare_look(channel, word):
    """Two players, one each, both on their first look - so the hint each one
    is owed is the same and the replies have to match exactly."""
    spelled_out = (await run(channel, bot.look, word, who=ALICE)).reply
    bare = (await run(channel, bot.look, None, who=BOB)).reply

    assert spelled_out == bare


async def test_under_and_behind_keep_their_refusal(channel):
    """Named in the work order as the two to leave alone: they are questions
    about a place in the room, not the room, and answering them with the room
    description would be a different promise."""
    for word in ("under", "behind"):
        assert isinstance(await resolves(word), reach.NotFound)


async def test_no_thing_answers_to_one_of_the_here_words():
    """What makes it safe to read these before resolution rather than after,
    which is how the room's own name is handled. An alias added later would
    be shadowed silently, so this is the guard."""
    things = content_module.load_files().things

    for thing in things:
        for name in (thing.name,) + tuple(thing.aliases):
            assert reach.normalise(name) not in bot.HERE_WORDS, thing.thing_id
