"""Which nouns the engine bolds, and which it leaves alone.

Bolding is the only signal that a noun can be typed. It used to be
written into the content files by hand, which put writers in charge of a
fact only the engine knows - a word is typeable when something in reach
answers to it, which depends on the room, the drop and what this player
has unlocked. The files hold plain prose now and `content.mark` bolds it
on the way out, against the same index `reach.find` resolves against.

**These tests are deliberately about the rule and not about the house.**
The last three guards written around this behaviour were all vacuous -
one walked a constant and asserted it had arrived at itself, two asserted
invariants that were already true with the bug in place. Prose makes that
easy: assert that the Entryway reads a certain way and the test passes
for a dozen reasons, only one of which you meant. So most of what is
here is `mark` called with three words and a dictionary, where there is
nowhere for a wrong answer to hide. The last section walks the shipped
house, because a rule nobody applies is also worth catching.
"""

import pytest

from conftest import ALICE, GUILD_A, LAST_DROP
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import reach
import resolve
from content import mark, markable


# --------------------------------------------------------------------------
# Which of a thing's words may be bolded at all
# --------------------------------------------------------------------------


def test_a_things_own_name_is_markable():
    assert "cat bowl" in markable("cat bowl", ("cat bowl", "bowl", "dish"))


def test_an_alias_of_two_words_is_markable():
    """How a thing is still reached when the prose never says its name.
    The firewood bin is "a plank bin by the wall" and nothing in the
    channel calls it a firewood bin."""
    assert "plank bin" in markable("firewood bin", ("bin", "plank bin"))


def test_a_single_word_alias_is_not_markable():
    """**Where the noise lives.** The front door answers to "out", the
    road to "mud", the farm stand to "wood". They are conveniences for
    somebody already typing, not nouns a sentence is about, and marking
    them bolds half the words in a paragraph."""
    assert markable("front door", ("front door", "door", "out")) == {"front door"}


def test_a_single_word_name_is_markable_even_though_it_is_one_word():
    """The rule is about aliases, not about length. `shelves` is the
    shelves' name and the word the prose uses."""
    assert "shelves" in markable("shelves", ("shelves", "sign", "produce"))


def test_punctuation_in_a_name_does_not_stop_it_matching():
    """The files say "door-hardware manual" and the parser says
    `door hardware manual`; both have to mean the one thing."""
    assert markable("door-hardware manual", ()) == {"door hardware manual"}


# --------------------------------------------------------------------------
# Where the marks go
# --------------------------------------------------------------------------

SOFA = {"sofa": "sofa", "deep sofa": "sofa"}


def test_a_known_noun_is_bolded():
    assert mark("A blanket over the sofa.", SOFA) == "A blanket over the **sofa**."


def test_an_unknown_noun_is_left_alone():
    assert mark("A blanket over the chair.", SOFA) == "A blanket over the chair."


def test_the_longest_phrase_wins():
    assert mark("A deep sofa.", SOFA) == "A **deep sofa**."


def test_a_thing_is_marked_once():
    """The second mention of the sofa is the same sofa, and bolding it
    again is only louder."""
    assert mark("The sofa, and under the sofa.", SOFA) == (
        "The **sofa**, and under the sofa."
    )


def test_two_different_things_are_both_marked():
    known = {"sofa": "sofa", "rug": "rug"}
    assert mark("A sofa on a rug.", known) == "A **sofa** on a **rug**."


def test_a_name_wins_over_an_alias_of_the_same_thing():
    """**The farm stand's sign.** Its prose reads "Empty shelves line the
    back … still offers sweet corn, blueberries and brown eggs", and the
    shelves answer to all four. Taking the longest phrase first marked
    "sweet corn" - advertising produce that has not been there in years,
    and leaving "blueberries" plain between two that were - and spent the
    shelves' one mark doing it."""
    known = {"shelves": "shelves", "sweet corn": "shelves"}

    marked = mark(
        "Empty shelves line the back, and a sign still offers sweet corn.",
        known,
        names={"shelves"},
    )

    assert "**shelves**" in marked
    assert "sweet corn" in marked and "**sweet corn**" not in marked


def test_the_name_wins_even_when_the_alias_comes_first():
    """Position does not decide it; being the name does."""
    known = {"shelves": "shelves", "sweet corn": "shelves"}

    marked = mark("Sweet corn, once. Empty shelves now.", known, names={"shelves"})

    assert marked == "Sweet corn, once. Empty **shelves** now."


def test_a_window_does_not_cross_a_full_stop():
    """Two sentences that happen to end and begin with the right words
    are not a phrase."""
    assert mark("Down to the deep. Sofa cushions.", SOFA) == (
        "Down to the deep. **Sofa** cushions."
    )


def test_a_hyphen_sits_inside_a_phrase():
    known = {"door hardware manual": "door_manual"}
    assert mark("An open door-hardware manual.", known) == (
        "An open **door-hardware manual**."
    )


# --------------------------------------------------------------------------
# Marking twice, and marking a paragraph
# --------------------------------------------------------------------------


def test_marking_its_own_output_changes_nothing():
    once = mark("A blanket over the sofa.", SOFA)
    assert mark(once, SOFA) == once


def test_a_thing_already_bolded_is_not_bolded_again():
    """Which is what makes the line above true, and what kept the
    transition honest: while the asterisks were still in the files,
    "dirt **road**" could not be re-marked as one phrase, so the road
    went unregistered and the next sentence bolded it a second time."""
    assert mark("The **sofa**, and under the sofa.", SOFA) == (
        "The **sofa**, and under the sofa."
    )


def test_once_per_thing_runs_across_a_paragraph():
    """A room's description is five rows and one paragraph. The sentence
    that names the road second is reading the same road the first one
    marked."""
    already: set[str] = set()
    first = mark("A rutted sofa.", SOFA, already=already)
    second = mark("Behind the sofa, a fence.", SOFA, already=already)

    assert first == "A rutted **sofa**."
    assert second == "Behind the sofa, a fence."


def test_separate_calls_mark_separately_without_a_shared_set():
    """Each thing's own `look` is its own message, read at its own
    moment, so "once" stops at the end of it."""
    assert mark("The sofa.", SOFA) == mark("The sofa.", SOFA) == "The **sofa**."


# --------------------------------------------------------------------------
# What the engine will not mark
# --------------------------------------------------------------------------


@pytest.fixture
async def channel(db):
    """A server standing on the road, with everything built."""
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, name="Test Server", channels=[halloween], members=[FakeMember(ALICE)]
    )
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, LAST_DROP)
    return db, guild, halloween


async def look(channel, thing=None):
    _, guild, halloween = channel
    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=halloween)
    await bot.look.callback(interaction, thing)
    return interaction


async def test_a_word_two_things_answer_to_is_not_marked(channel):
    """**Advertising a word that asks a question is worse than leaving
    it plain.** Both cat toys answer to "cat toy", so a player who types
    it is asked which - and a bolded word is a promise that typing it
    works."""
    for toy in ("crinkle_ball", "feather_wand"):
        await database.place_in_room(GUILD_A, "CH", toy, 1)

    known, _ = await reach.nouns_within_reach(GUILD_A, ALICE, "CH")

    assert "crinkle ball" in known and "feather wand" in known
    assert "cat toy" not in known


async def test_the_cat_is_never_marked(channel):
    """She is in reach in every room and the subject of most sentences
    in the game, so marking her spends the emphasis that should be
    pointing at the wasp nest."""
    known, _ = await reach.nouns_within_reach(GUILD_A, ALICE, "CH")

    assert "cat" not in known
    assert "black cat" not in known


async def test_a_thing_whose_drop_has_not_arrived_is_not_marked(channel):
    """**The same failure the old checker caught, arriving on a timer.**

    A drop-1 sentence naming a drop-2 thing used to be a content error,
    because the asterisks were written once and read on every drop
    afterwards. The engine marks per server, so the word is plain until
    the drop lands and bold after it - the answer the files could never
    give.
    """
    await resolve.set_current_drop(GUILD_A, 1)
    await database.place_in_room(GUILD_A, "CH", "feather_wand", 1)

    early, _ = await reach.nouns_within_reach(GUILD_A, ALICE, "CH")

    await resolve.set_current_drop(GUILD_A, LAST_DROP)
    later, _ = await reach.nouns_within_reach(GUILD_A, ALICE, "CH")

    assert "feather wand" not in early
    assert "feather wand" in later


async def test_a_thing_does_not_mark_itself(channel):
    """A sentence about the branches that bolds the word "branches"
    points the player at what they are already looking at, and spends
    the emphasis the wasp nest in the next clause needed."""
    known, _ = await reach.nouns_within_reach(
        GUILD_A, ALICE, "CH", except_for="branches"
    )

    assert "branches" not in known
    assert "wasp nest" in known


# --------------------------------------------------------------------------
# And the house itself
# --------------------------------------------------------------------------


async def test_the_channel_bolds_the_farm_stand(channel):
    """The one end-to-end case: plain prose in the file, marked by the
    time it reaches a player."""
    reply = (await look(channel)).reply

    assert "**farm stand**" in reply
    assert "**cat bed**" in reply


async def test_the_files_carry_no_bolding_of_their_own(channel):
    """The engine's job, and nobody else's. A hand-written pair of
    asterisks is a second claim about the same word, and the loader
    refuses one - this is the same rule from the other side, so that
    deleting the check does not quietly bring the habit back."""
    parsed = content_module.load_files()

    for row in parsed.room_text:
        assert "**" not in (row.text.get("look") or ""), row.entity_id
    for row in parsed.thing_text:
        for column in ("look", "use"):
            assert "**" not in (row.text.get(column) or ""), row.entity_id


async def test_a_bolded_word_is_always_one_a_player_can_type(channel):
    """**The promise the whole change exists to make.** Every noun the
    channel's description bolds resolves to something, from where the
    player is standing, by the parser's own ladder - so there is no
    bolded word that answers with "there is no such thing here".
    """
    reply = (await look(channel)).reply
    import re

    marked = re.findall(r"\*\*(.+?)\*\*", reply)
    assert marked, "the description bolded nothing at all"
    for phrase in marked:
        found = await reach.find(
            GUILD_A, ALICE, "CH", phrase, reach.Scope.REACH, fuzzy=False
        )
        assert isinstance(found, reach.Found), phrase
