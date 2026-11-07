"""Drop 40: the bottle warmer, which asks whether you brought a bottle.

Plugged in, up to temperature, and up to temperature for some time -
which is the joke, and the joke only lands on somebody carrying a
bottle. So its `/use` is two lines rather than one, and which one a
player gets is a fact about their bag.

**Why it is a `requires` and not a branch.** The engine already chooses
between `use` and `use_fail` on whether a requirement is to hand. A
second mechanism for the same question would be a second place to look
when a gate misbehaves, and the warmer wants exactly what the cans
want - something in your hands before the verb means anything.

**Why `requires` needed a new spelling to say it.** `|` is and. The
warmer wants either bottle, and the two bottles are called different
things on purpose: a used one and a sanitized one. A requirement is
already met by any thing of the same *name*, which is how three cat
bowls answer one `cat_bowl` - but renaming the bottles to match would
have been a lie about the objects told to get a lie past the gate. So
a part may now be a `/` group, and `used_baby_bottle/sanitized_baby_bottle`
is one requirement with two ways to meet it.

**Why `{to_hand}`.** A group is the one shape where which thing
satisfied the gate is not knowable from the cell, so a line that
mentions it has to be told. Nothing else in the files has a group, so
nothing else pays for the lookup.
"""

import pytest
from types import SimpleNamespace

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import phrasing
import reach
import resolve
import states
import world


THIS_DROP = 40
WARMER = "bottle_warmer"
USED = "used_baby_bottle"
CLEAN = "sanitized_baby_bottle"

# Quoted off `thing_text.tsv` rather than paraphrased: these are the two
# answers, and a test that matched on "bottle" would pass on either.
NO_BOTTLE = "There's no bottle in it"
MISTAKE = "then realize your mistake"


@pytest.fixture
async def house(db, monkeypatch):
    """The shipped content at drop 40, with the Bedroom open."""
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    await db.set_setting(GUILD_A, resolve.DROP_KEY, THIS_DROP)
    await content_loader.load_content(content_module.load_files(), guild_ids=[GUILD_A])
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    for who in (ALICE, BOB):
        await db.start_game(who, GUILD_A, "EN", await resolve.rooms_open_at_launch())
    monkeypatch.setattr(
        bot,
        "bot",
        SimpleNamespace(
            guilds=[guild], get_guild=lambda gid: guild if gid == GUILD_A else None
        ),
    )
    return db, guild, halloween, rooms


def place(house, room):
    _, _, halloween, rooms = house
    return next(t for t in halloween.threads if t.name == rooms[room])


async def use_warmer(house, who=ALICE, room="BE") -> str:
    db, guild, _, _ = house
    await db.update_current_room(who, GUILD_A, room)
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=place(house, room))
    await bot.use.callback(interaction, "bottle warmer")
    return "\n".join(text for text, _ in interaction.sent if text)


async def give(db, who, thing_id):
    """One bottle in somebody's bag, written the way `test_world` writes it."""
    async with db._require_session()() as session:
        session.add(
            database.PlayerInventory(
                guild_id=GUILD_A, user_id=who, thing_id=thing_id, count=1
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# The gate


async def test_with_no_bottle_the_warmer_says_there_is_no_bottle_in_it(house):
    reply = await use_warmer(house)

    assert NO_BOTTLE in reply
    assert MISTAKE not in reply


async def test_and_records_nothing_because_a_refused_use_is_not_a_use(house):
    """The one behaviour this change does alter, deliberately.

    The no-bottle line used to be a success: it printed, and it stamped
    a `thing_uses` row. As a refusal it prints the same words and stamps
    nothing.

    **"No achievement names the warmer" is true and is not the reason
    this is safe**, because a reader does not have to name a thing to
    count it. Three mechanisms make it safe, each read off the query
    rather than off the absence of a mention:

    - `toy_plays` sums `use_count` joined on `ThingType.type == "toy"`.
      The warmer is a fixture, so it was never in that sum.
    - the explicit-list readers filter `thing_id.in_(wanted)`, so they
      count only ids an achievement hands them, and none hands them
      this one.
    - the idle sweep drives off `PlayerInventory` and outer-joins
      `ThingUse`. The warmer is `takeable = no`, so it can never have an
      inventory row and can never reach that query at all.

    The distinction is the whole point of writing it down: make the
    warmer takeable one day, or retype it, and "no achievement names
    it" stays true while the conclusion stops following.
    """
    await use_warmer(house)

    assert await database.use_count_of(ALICE, GUILD_A, WARMER) == 0


@pytest.mark.parametrize("bottle", [USED, CLEAN])
async def test_either_bottle_opens_the_gate(house, bottle):
    await give(house[0], ALICE, bottle)

    reply = await use_warmer(house)

    assert MISTAKE in reply
    assert NO_BOTTLE not in reply


@pytest.mark.parametrize("bottle,expected", [(USED, "used"), (CLEAN, "sanitized")])
async def test_and_the_line_names_the_bottle_they_actually_had(house, bottle, expected):
    """Bolded, which is the marking pass getting this right for free.

    A substituted name is a thing's own name, and this player is holding
    it - so it is a word they can type at, and it is marked like every
    other one. Asserted rather than stripped: a token that rendered
    unmarked would mean the pass runs before the fill, and a player
    would be reading a noun the game had not told them was one.
    """
    await give(house[0], ALICE, bottle)

    reply = await use_warmer(house)

    assert f"pull out a **{expected} baby bottle**" in reply
    assert "{to_hand}" not in reply


async def test_holding_both_names_the_one_the_cell_lists_first(house):
    """The same tie-break the refusal uses, for the same reason.

    `used_baby_bottle/sanitized_baby_bottle` puts the used one first, so
    which line a player with both gets is the writer's decision rather
    than whichever row the database handed back.
    """
    await give(house[0], ALICE, USED)
    await give(house[0], ALICE, CLEAN)

    assert "pull out a **used baby bottle**" in await use_warmer(house)


async def test_a_bottle_in_somebody_elses_bag_is_not_in_yours(house):
    await give(house[0], BOB, USED)

    assert NO_BOTTLE in await use_warmer(house, who=ALICE)


# ---------------------------------------------------------------------------
# The group, under the gate


async def test_a_group_is_one_requirement_and_not_two(house):
    """Missing only when every alternative is, and reported as written."""
    part = f"{USED}/{CLEAN}"

    assert await reach.missing_requirements(GUILD_A, ALICE, "BE", [part]) == [part]

    await give(house[0], ALICE, CLEAN)

    assert await reach.missing_requirements(GUILD_A, ALICE, "BE", [part]) == []


async def test_and_a_plain_requirement_is_answered_exactly_as_before(house):
    """The ids in the files today have no group in them.

    `can_opener|cat_bowl` is two parts and two requirements, and the
    answer still comes back in the cell's order - which is what the
    refusal text depends on.
    """
    assert await reach.missing_requirements(
        GUILD_A, ALICE, "KI", ["can_opener", "cat_bowl"]
    ) == ["can_opener", "cat_bowl"]

    await give(house[0], ALICE, "can_opener")

    assert await reach.missing_requirements(
        GUILD_A, ALICE, "KI", ["can_opener", "cat_bowl"]
    ) == ["cat_bowl"]


async def test_satisfied_by_names_nothing_when_nothing_is_to_hand(house):
    assert await reach.satisfied_by(GUILD_A, ALICE, "BE", f"{USED}/{CLEAN}") is None


# ---------------------------------------------------------------------------
# The syntax


def test_a_pipe_is_and_and_a_slash_is_or():
    assert states.required_things("a|b") == ["a", "b"]
    assert states.alternatives("a") == ["a"]
    assert states.alternatives("a/b") == ["a", "b"]
    assert content_module.requires_ids("a|b/c") == ["a", "b", "c"]
    assert states.required_things(None) == []


def test_the_warmer_is_the_only_thing_in_the_files_with_a_group():
    """So the cost of asking is paid by one thing, and the claim is checked.

    If a second gate ever wants a group this test is where it says so -
    which is better than the comment in `bot` quietly going stale about
    how much the lookup costs.
    """
    grouped = sorted(
        thing.thing_id
        for thing in content_module.load_files().things
        if any(
            len(content_module.requires_alternatives(part)) > 1
            for part in content_module.requires_parts(thing.requires)
        )
    )

    assert grouped == [WARMER]


def test_and_the_other_requires_column_is_not_parsed_by_this_at_all():
    """`achievements.tsv` has a `requires` too, and it is a different column.

    Two columns share the word and nothing else. A thing's `requires` is
    a list of things to have to hand, parsed here; an achievement's is a
    single achievement id that `resolve` compares whole against the set
    somebody has earned. Nothing splits it, so a slash in that column
    would be a literal id - caught, but by `_check_achievements` for
    naming an achievement that does not exist rather than by anything
    here.

    Pinned because the hazard is invisible from either column on its
    own: a reader who finds this parser and greps for `requires` lands
    in both files, and the second one is not its business.
    """
    files = content_module.load_files()
    earned_ids = {row.achievement_id for row in files.achievements}

    for row in files.achievements:
        if not row.requires:
            continue
        assert content_module.REQUIRES_OR not in row.requires, row.achievement_id
        assert row.requires in earned_ids, row.achievement_id


def test_every_id_in_a_group_has_to_be_a_real_thing():
    """A dead alternative is a dead branch of a gate, which is quieter
    than a dead gate and no more correct."""
    files = content_module.load_files()
    warmer = next(t for t in files.things if t.thing_id == WARMER)
    object.__setattr__(warmer, "requires", f"{USED}/not_a_thing")

    problems = content_module.validate(files)

    assert any("not_a_thing" in problem for problem in problems), problems


def test_the_token_is_spellable():
    """`{bottle type}` is not a token and never could be.

    `fill` matches `\\{(\\w+)\\}`, and an unknown token is left in place
    rather than dropped - so a cell written with a space in the braces
    prints the braces to a player. Pinned because the submitted copy
    asked for one.
    """
    assert phrasing.fill("a {to_hand}.", to_hand="used baby bottle") == (
        "a used baby bottle."
    )
    assert phrasing.fill("a {bottle type}.", **{"bottle type": "x"}) == (
        "a {bottle type}."
    )
