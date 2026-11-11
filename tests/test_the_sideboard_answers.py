"""The sideboard's own sentences, made typeable.

**Fifty-one refusals in the Dining Room came out of two paragraphs.**
The sideboard's `look` names a stack of unopened mail, a saucer of loose
change and the cupboard doors; its `use` names two utility bills, a
parenting magazine and a card. Only the candy bowl, the vase and the
tuna were things. Players typed the rest and the house said it had
never heard of them - `loose change` fifteen times, `unopened mail`
ten, `saucer` nine, `change` eight, `card` seven, across three verbs
and thirteen different people.

**None of this is bolding.** A one-word alias is never markable, and a
thing's own words are left out of its own description by `except_for` -
so `/look sideboard` reads exactly as it did, and nothing new is
promised. These words are a net under prose that already mentions them,
which is what the house's parser is for: the player types what they
just read.

**Two of them go to the cupboard rather than to the sideboard**, because
that is what the sentence says is behind them. `cupboard` already led
there; `cupboard doors` is the phrase the prose actually uses.

**The bills, the magazine and the card are parked**, deliberately and
not forgotten - see `Parking lot.md`. They exist only in the `use`
text, so an alias would give `/use card` the right line and leave
`/look card` handing back the furniture the mail is lying on. What
they want is their own text or a mention in the sideboard's `look`,
which is a writing decision rather than a parsing one.
"""

import pytest

from conftest import ALICE, GUILD_A

import bot
import content as content_module
import content_loader
import reach
from reach import Found, NotFound, Scope
from test_verbs import (  # noqa: F401
    a_room_thread,
    command,
    enter_properly,
    real_house,
)


@pytest.fixture
async def dining_room(db):
    await db.ensure_user_exists(ALICE, GUILD_A)
    await content_loader.load_content(content_module.load_files())
    return db


async def resolves(typed, room="DI"):
    return await reach.find(GUILD_A, ALICE, room, typed, Scope.REACH)


# Every noun either paragraph puts in front of a player, and the thing it
# reaches. The two the cupboard owns are the point of the split.
NOUNS = [
    ("unopened mail", "sideboard"),
    ("mail", "sideboard"),
    ("letters", "sideboard"),
    ("saucer", "sideboard"),
    ("loose change", "sideboard"),
    ("change", "sideboard"),
    ("cupboard doors", "cat_food_tuna"),
    ("cupboard door", "cat_food_tuna"),
    # Already worked, and here so that a rewrite of the row cannot quietly
    # take one of them away while adding the others.
    ("candy bowl", "candy"),
    ("vase", "flowers"),
    ("tuna cat food", "cat_food_tuna"),
    ("cupboard", "cat_food_tuna"),
    ("sideboard", "sideboard"),
]


@pytest.mark.parametrize("typed, thing_id", NOUNS)
async def test_every_noun_on_the_sideboard_reaches_something(
    dining_room, typed, thing_id
):
    found = await resolves(typed)

    assert isinstance(found, Found), typed
    assert found.thing_id == thing_id
    # Exact, not forgiven. A fuzzy match here would mean the alias had not
    # been added and something else happened to sit one edit away.
    assert found.fuzzy is None


PARKED = ["card", "bills", "utility bills", "magazine", "parenting magazine"]


@pytest.mark.parametrize("typed", PARKED)
async def test_what_is_inside_the_mail_is_parked_and_not_aliased(
    dining_room, typed
):
    """**Left refusing on purpose**, which is why there is a test for it:
    the next person to read the sideboard's `use` line and count the
    refusals would otherwise add these five in good faith.

    They are named only in the `use` text, so an alias would answer
    `/use card` correctly and hand `/look card` the furniture the mail is
    lying on - a dead end wearing the clothes of an answer. The decision
    they are waiting on is whether the card gets its own text or a
    mention in the sideboard's `look`, and both are writing.

    `Parking lot.md` holds the row, and this is the assertion that says
    the row is still true.
    """
    assert isinstance(await resolves(typed), NotFound)


async def test_going_through_the_mail_is_still_what_the_sideboard_does(
    real_house,
):
    """And the line those five come from is reachable the way it always
    was, so nothing was lost by leaving them out: a player who read about
    the card gets back to it through the mail, or through the sideboard."""
    db, _ = real_house
    await enter_properly(db, room="DI")

    for typed in ("sideboard", "mail", "unopened mail"):
        reply = (await command(bot.use, typed, a_room_thread("Dining Room"))).reply
        assert "You go through the mail." in reply
        assert "a card addressed to" in reply


async def test_looking_at_the_sideboard_reads_exactly_as_it_did(real_house):
    """**Nothing new is bolded**, which is why these are safe to add in
    bulk. The sideboard's own words are left out of its own description by
    `except_for`, and the cupboard is already marked once by the tuna - so
    the emphasis is still on the two things in the sentence that are not
    the sideboard, and no new word is promised to anybody."""
    db, _ = real_house
    await enter_properly(db, room="DI")

    reply = (await command(bot.look, "sideboard", a_room_thread("Dining Room"))).reply

    assert "**candy bowl**" in reply
    assert "**tuna cat food**" in reply
    assert reply.count("**") == 4, reply
    for plain in ("unopened mail", "loose change", "saucer", "cupboard doors"):
        assert f"**{plain}**" not in reply


async def test_the_dining_room_marks_what_it_always_did(dining_room):
    """The other half of the same promise, from the files rather than from
    a player. Adding a phrase two things answer to would silently drop it
    from the marked set, so this is the check that it did not happen."""
    marked = content_module.marked_in_room(content_module.load())

    assert sorted(marked["DI"]) == [
        "DE", "DK", "candy_bowl", "cat_food_stash_sideboard", "chairs",
        "david_journal_page", "dining_table", "high_chair", "plates",
        "sideboard", "silver_spoon", "tall_windows", "to_do_list",
        "wine_glass",
    ]


# `saucer` is left out: three cat bowls already answered to it, so it was
# a word the house knew before this and the case proves nothing here.
@pytest.mark.parametrize("typed", ["change", "loose change", "unopened mail"])
async def test_elsewhere_the_house_now_admits_it_knows_the_word(
    dining_room, typed
):
    """A side effect worth having. These are words the house knows now, so
    a player who types one in the Nursery gets *you don't see a loose
    change here* instead of *there's not much to look at* - the refusal
    that says it is somewhere, rather than the one that says it is
    nothing."""
    found = await resolves(typed, room="NU")

    assert isinstance(found, NotFound)
    assert found.exists_elsewhere is True
