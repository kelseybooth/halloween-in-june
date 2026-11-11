"""Drop 46's three: two collections and a group.

*Easily Amused* and *Whole Toy Box* count rows in `thing_uses`, which
is the distinction its own docstring draws - the rows say how many
toys and the sum says how many plays, and *Tireless* wants the sum.

*Playgroup* is the one that needed a table. Nothing else could answer
it: `thing_uses` is cumulative and keeps one room, `room_deeds` is
idempotent and once-ever, and `interaction_log` has the time and the
thing and no room at all. `toy_plays` is a row per play with where and
when, written beside the `record_use` that already happened.

**The window slides and nothing is latched.** The check runs on every
successful play and looks back sixty minutes from that play, which is
what makes late joiners earn it and what makes the hour a rolling one
rather than a session somebody has to start.
"""

from datetime import timedelta

import pytest

from conftest import ALICE, BOB, GUILD_A

import achievements
import content as content_module
import content_loader
import database
import resolve
import triggers

CAROL = 300000000000000003
DAVE = 400000000000000004


@pytest.fixture
async def house(db):
    await content_loader.load_content(content_module.load_files())
    await resolve.set_current_drop(GUILD_A, 46)
    for who in (ALICE, BOB, CAROL, DAVE):
        await db.ensure_user_exists(who, GUILD_A)
    return db


async def played(who, thing_id, room="LI", minutes_ago=0):
    """One successful play, recorded both ways the real handler does."""
    now = await database.server_now(GUILD_A)
    await database.record_use(who, GUILD_A, thing_id, room_id=room)
    await database.record_toy_play(
        GUILD_A, who, thing_id, room, now - timedelta(minutes=minutes_ago)
    )


async def context(who=ALICE, room="LI", thing_id="acorn"):
    return achievements.Context(
        guild_id=GUILD_A,
        hook="on_use",
        user_id=who,
        thing_id=thing_id,
        room_id=room,
        now=await database.server_now(GUILD_A),
    )


TOYS = [
    "feather_wand", "crinkle_ball", "catnip_mouse", "jingle_ball",
    "laser_pointer", "spring_coil", "hair_tie", "bottle_cap", "wine_cork",
    "acorn", "spider_ring", "crumpled_receipt", "shipping_box",
]


# --------------------------------------------------------------------------
# The two collections
# --------------------------------------------------------------------------


async def test_easily_amused_wants_five_different_toys(house):
    for toy in TOYS[:4]:
        await played(ALICE, toy)
    assert not await triggers.easily_amused(await context())

    await played(ALICE, TOYS[4])

    assert await triggers.easily_amused(await context())


async def test_playing_one_toy_five_times_is_not_five_toys(house):
    """Rows, not the sum of `use_count` - which is exactly the line
    `database.toy_plays` draws between these and *Tireless*."""
    for _ in range(5):
        await played(ALICE, "acorn")

    assert await database.toy_plays(GUILD_A, ALICE) == 5
    assert not await triggers.easily_amused(await context())


async def test_it_is_at_least_five_and_not_exactly_the_fifth(house):
    """The shape every counted achievement here uses: a check that can
    only fire on one exact play is lost for good if that play races or
    the bot is down for it."""
    for toy in TOYS[:7]:
        await played(ALICE, toy)

    assert await triggers.easily_amused(await context())


async def test_whole_toy_box_wants_all_thirteen(house):
    for toy in TOYS[:12]:
        await played(ALICE, toy)
    assert not await triggers.whole_toy_box(await context())

    await played(ALICE, TOYS[12])

    assert await triggers.whole_toy_box(await context())


def test_the_target_is_declared_rather_than_counted():
    """**Counting the rows would move the target.** A toy written later
    would un-finish a player who had collected the set - they would lose
    nothing, but the achievement's own words, *every object in this
    house that she considers a toy*, would start meaning something they
    cannot see. Adding a fourteenth is a decision about this number."""
    toys = [t for t in content_module.load_files().things if t.type == "toy"]

    assert triggers.TOY_SET_TOTAL == 13
    assert len(toys) == 13


async def test_the_box_is_the_thirteenth_and_counts(house):
    """It is a toy to the cat and furniture to everybody else, and it
    never leaves the Entryway - so the last step of the collection is
    going to find it, which is the point rather than an oversight."""
    for toy in TOYS[:12]:
        await played(ALICE, toy)

    assert await database.distinct_toys_played(GUILD_A, ALICE) == 12
    assert not content_module.load().things_by_id["shipping_box"].takeable


# --------------------------------------------------------------------------
# Playgroup
# --------------------------------------------------------------------------


async def test_ten_toys_in_one_room_in_one_hour(house):
    for toy in TOYS[:9]:
        await played(ALICE, toy)
    assert not await triggers.playgroup(await context())

    await played(BOB, TOYS[9])

    assert await triggers.playgroup(await context())


async def test_everybody_who_played_earns_it(house):
    for toy in TOYS[:5]:
        await played(ALICE, toy)
    for toy in TOYS[5:10]:
        await played(BOB, toy)

    assert await triggers._playgroup_players(await context()) == (
        tuple(sorted((ALICE, BOB)))
    )


async def test_somebody_in_the_room_who_did_not_play_does_not(house):
    """**Contributors, not occupants** - the shape *Board Meeting*
    established. Standing there is not the achievement."""
    for toy in TOYS[:10]:
        await played(ALICE, toy)

    assert await triggers._playgroup_players(await context()) == (ALICE,)


async def test_a_repeat_of_somebody_elses_toy_still_earns_it(house):
    """Every play counts, not the first play with each toy - so a player
    whose toy has already been played that hour is not shut out."""
    for toy in TOYS[:10]:
        await played(ALICE, toy)
    await played(CAROL, TOYS[0])

    assert CAROL in await triggers._playgroup_players(await context())


async def test_a_late_joiner_earns_it_too(house):
    """**Because the window slides.** The check runs on every play and
    looks back an hour from that play, so somebody arriving after the
    first award earns it as long as the last hour still covers ten."""
    for index, toy in enumerate(TOYS[:10]):
        await played(ALICE, toy, minutes_ago=40 - index)
    assert await triggers.playgroup(await context())

    await played(DAVE, "acorn")

    assert await triggers.playgroup(await context())
    assert DAVE in await triggers._playgroup_players(await context())


async def test_ten_plays_of_four_toys_is_not_ten_toys(house):
    """**Different toys, not plays** - and the two only come apart when
    somebody repeats. Every other test here plays each toy once, so the
    count of plays and the count of toys are equal and a predicate
    reading either passes them all."""
    for _ in range(3):
        for toy in TOYS[:4]:
            await played(ALICE, toy)

    assert len(await database.toy_plays_in_room_since(
        GUILD_A, "LI", (await database.server_now(GUILD_A)) - timedelta(hours=1)
    )) == 12
    assert not await triggers.playgroup(await context())


async def test_nine_toys_is_not_enough(house):
    for toy in TOYS[:9]:
        await played(ALICE, toy)

    assert not await triggers.playgroup(await context())


async def test_spread_over_more_than_an_hour_is_not_enough(house):
    """The tenth toy falls out of the back of the window as the first
    one is played, so the hour never covers ten at once."""
    for index, toy in enumerate(TOYS[:10]):
        await played(ALICE, toy, minutes_ago=61 + index)

    assert not await triggers.playgroup(await context())


async def test_split_across_two_rooms_is_not_enough(house):
    """One room, which is the part that makes it a gathering rather than
    a tally."""
    for toy in TOYS[:5]:
        await played(ALICE, toy, room="LI")
    for toy in TOYS[5:10]:
        await played(BOB, toy, room="KI")

    assert not await triggers.playgroup(await context(room="LI"))
    assert not await triggers.playgroup(await context(room="KI"))


async def test_the_box_counts_in_the_entryway(house):
    """It never leaves, so it is one of the ten only there - which is
    the whole of what the work order means by a group in the Entryway
    needing nine carried toys."""
    for toy in TOYS[:9]:
        await played(ALICE, toy, room="EN")
    assert not await triggers.playgroup(await context(room="EN"))

    await played(ALICE, "shipping_box", room="EN")

    assert await triggers.playgroup(await context(room="EN"))


async def test_a_play_with_no_room_earns_nobody(house):
    """`room_id` is optional on the context, so the predicate has to
    survive one without it rather than counting the whole house.

    **The guard says that out loud and is not what enforces it**: no
    `toy_plays` row has a null room, so the query matches nothing
    either way and deleting the early return fails no test. It is here
    so the intent is readable, not because it is load bearing."""
    for toy in TOYS[:10]:
        await played(ALICE, toy)

    assert not await triggers.playgroup(await context(room=None))
    assert await triggers._playgroup_players(await context(room=None)) == ()
