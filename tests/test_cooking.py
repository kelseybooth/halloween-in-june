"""The stove, and what a recipe costs.

**Two bugs, one root.** A playtester reported that the chocolate, herbs and
spice were not used up when cooked with. They were not: consumption in
`_finish_use` is keyed to the thing being *used*, and the stove is a fixture
that `content.validate` refuses to mark `consumed_on_use` at all - so nothing
in the engine had ever spent a `requires` part, and cooking was free and
endlessly repeatable.

The second bug was in the same place and worse. The herbs and the chocolate
*did* carry `consumed_on_use`, which somebody had plainly set to mean *the
stove eats this* - so `/use herbs` destroyed them for a flavour line telling
the player to go and find the rest of the recipe. The spice jar did not carry
it, so the three ingredients behaved three different ways.

`consumes` is the column that separates the two readings: `consumed_on_use`
is *spent when you use it*, `consumes` is *spent when something else is used
with it*. `requires` stays the gate and is not the bill - the pumpkins
require the carving tools and must never eat them, which is the case that
rules out widening either existing column.
"""

from dataclasses import replace

import pytest
from sqlalchemy import text

from conftest import ALICE, GUILD_A
import content as content_module
import database
from test_verbs import real_house, use, enter_properly, heard  # noqa: F401
from test_world import carry

RECIPE = ("herbs", "dark_chocolate", "spice_jar")


async def held(db, *thing_ids):
    return {t: await db.carried_of(ALICE, GUILD_A, t) for t in thing_ids}


async def a_cook_with_everything(db):
    await enter_properly(db, room="KI")
    for thing_id in RECIPE:
        await carry(db, ALICE, GUILD_A, thing_id)


# --------------------------------------------------------------------------
# What the recipe costs
# --------------------------------------------------------------------------


async def test_cooking_spends_the_whole_recipe(real_house):
    """**The reported bug.** All three go, not none of them.

    Asserted as the whole bag rather than one ingredient, because the
    three were flagged three different ways before this and a test that
    only read the herbs would have passed with the spice jar still in
    hand.
    """
    db, guild = real_house
    await a_cook_with_everything(db)

    await use(thing="stove", guild=guild)

    assert await held(db, *RECIPE) == {
        "herbs": 0,
        "dark_chocolate": 0,
        "spice_jar": 0,
    }


async def test_one_recipe_cooks_once(real_house):
    """The other half of the report: it was endlessly repeatable.

    The second attempt is refused in the stove's own words, because by
    then it is an ordinary unmet `requires` - which is the right refusal
    and not a new one.
    """
    db, guild = real_house
    await a_cook_with_everything(db)

    await use(thing="stove", guild=guild)
    second = await use(thing="stove", guild=guild)

    assert "don't have all of it yet" in heard(second)


async def test_a_partial_recipe_spends_nothing(real_house):
    """Two of the three, and the bag comes out untouched.

    The gate refuses this before the spend, so what is really pinned is
    that the spend is downstream of the gate rather than racing it.
    """
    db, guild = real_house
    await enter_properly(db, room="KI")
    await carry(db, ALICE, GUILD_A, "herbs")
    await carry(db, ALICE, GUILD_A, "dark_chocolate")

    await use(thing="stove", guild=guild)

    assert await held(db, *RECIPE) == {
        "herbs": 1,
        "dark_chocolate": 1,
        "spice_jar": 0,
    }


async def test_a_lost_race_spends_none_of_it(real_house):
    """`consume_all_carried` is all or nothing, driven directly.

    The command cannot produce this state - the gate has already proved
    all three were in the bag - so it is asked of the function, which is
    where the guarantee lives. Without the rollback a player who put the
    spice down mid-command would lose the herbs and the chocolate for
    nothing.
    """
    db, guild = real_house
    await enter_properly(db, room="KI")
    await carry(db, ALICE, GUILD_A, "herbs")
    await carry(db, ALICE, GUILD_A, "dark_chocolate")

    spent = await database.consume_all_carried(ALICE, GUILD_A, list(RECIPE))

    assert spent is False
    assert await held(db, *RECIPE) == {
        "herbs": 1,
        "dark_chocolate": 1,
        "spice_jar": 0,
    }


# --------------------------------------------------------------------------
# An ingredient you only poked at
# --------------------------------------------------------------------------


async def test_crushing_the_herbs_does_not_destroy_them(real_house):
    """**The bug nobody reported.** The line says to go and find the rest
    of the recipe; it used to take the herbs while saying it.

    The reply is asserted alongside the count because the fix must not
    be *the line stopped appearing* - the flavour text is still there,
    it just no longer costs an ingredient.
    """
    db, guild = real_house
    await enter_properly(db, room="CO")
    await carry(db, ALICE, GUILD_A, "herbs")

    interaction = await use(thing="herbs", guild=guild)

    assert "crush the leaves" in heard(interaction)
    assert await db.carried_of(ALICE, GUILD_A, "herbs") == 1


async def test_breaking_off_a_square_does_not_destroy_the_bar(real_house):
    db, guild = real_house
    await enter_properly(db, room="LI")
    await carry(db, ALICE, GUILD_A, "dark_chocolate")

    interaction = await use(thing="chocolate", guild=guild)

    assert "break off a square" in heard(interaction)
    assert await db.carried_of(ALICE, GUILD_A, "dark_chocolate") == 1


async def test_the_spice_jar_reads_the_same_as_the_other_two(real_house):
    """It always behaved correctly, and it is here so the three are pinned
    together. The whole bug was that they disagreed."""
    db, guild = real_house
    await enter_properly(db, room="EN")
    await carry(db, ALICE, GUILD_A, "spice_jar")

    interaction = await use(thing="spice jar", guild=guild)

    assert "not useful on its own" in heard(interaction)
    assert await db.carried_of(ALICE, GUILD_A, "spice_jar") == 1


# --------------------------------------------------------------------------
# What `consumes` must not touch
# --------------------------------------------------------------------------


async def test_the_carving_tools_are_required_and_not_eaten(real_house):
    """The case that rules out consuming every `requires` part.

    The pumpkins want the tools in your hands and must leave them there.
    A rule that spent requirements generally would take a player's
    carving tools the first time they carved anything.
    """
    db, guild = real_house
    await enter_properly(db, room="CO")
    await carry(db, ALICE, GUILD_A, "carving_tools")

    await use(thing="pumpkins", guild=guild)

    assert await db.carried_of(ALICE, GUILD_A, "carving_tools") == 1


async def test_the_graphite_is_still_spent_by_its_own_use(real_house):
    """`consumed_on_use` keeps working on its own terms.

    The powder is the row that would have been caught by the cheaper
    fix: the bedroom window `requires` it, so consuming requirements
    generally would have taken a packet every time somebody opened the
    sash - including re-opening it, which asks for powder a player has
    no reason to still be carrying.
    """
    db, guild = real_house
    await enter_properly(db, room="BE")
    await carry(db, ALICE, GUILD_A, "graphite_powder")

    await use(thing="graphite", guild=guild)

    assert await db.carried_of(ALICE, GUILD_A, "graphite_powder") == 0


async def test_opening_the_window_leaves_the_powder_alone(real_house):
    """The same row from the other end: the window is the consumer here and
    it has no `consumes`, so it spends nothing of its own accord."""
    db, guild = real_house
    await enter_properly(db, room="BE")
    await carry(db, ALICE, GUILD_A, "graphite_powder")

    await use(thing="window", guild=guild)

    assert await db.carried_of(ALICE, GUILD_A, "graphite_powder") == 1


# --------------------------------------------------------------------------
# What the files may say
# --------------------------------------------------------------------------


def a_stove_that(**changes):
    """The shipped content with the stove's columns overridden."""
    parsed = content_module.load_files()
    parsed.things = [
        replace(t, **changes) if t.thing_id == "stove" else t for t in parsed.things
    ]
    return content_module.validate(parsed)


def test_the_shipped_recipe_is_sound():
    """The guard on the five rules below: they only mean something if the
    real content passes them."""
    assert content_module.validate(content_module.load_files()) == []


def test_an_ingredient_has_to_be_required_too():
    problems = a_stove_that(consumes="herbs|dark_chocolate|spice_jar|candy")

    assert any("consumes candy without requiring it" in p for p in problems)


def test_an_ingredient_has_to_exist():
    problems = a_stove_that(requires="rosemary", consumes="rosemary")

    assert any("consumes rosemary, which is not a thing" in p for p in problems)


def test_an_ingredient_cannot_be_a_fixture():
    """`consume_carried` takes a thing off a bag, and a pot is never in one."""
    problems = a_stove_that(requires="pasta_pot", consumes="pasta_pot")

    assert any("never in anybody's bag" in p for p in problems)


def test_an_ingredient_nothing_replaces_is_refused():
    """The reading glasses are `quantity = 1` with no source. Cooking with
    them would delete them from that server for the rest of October."""
    problems = a_stove_that(requires="reading_glasses", consumes="reading_glasses")

    assert any("destroy it for good" in p for p in problems)


def test_an_ingredient_cannot_be_an_either_or_group():
    """`requires` allows `a/b` and this does not: spending one would have to
    say which, in a sentence nobody has written."""
    problems = a_stove_that(
        requires="herbs/dark_chocolate", consumes="herbs/dark_chocolate"
    )

    assert any("either/or group" in p for p in problems)


def test_an_ingredient_cannot_be_furniture_in_the_room():
    """The ladder satisfies a `requires` by standing in the room, so a cell
    that ate it could be gated by a copy no bag holds."""
    problems = a_stove_that(requires="ladder", consumes="ladder")

    assert any("room that nobody is carrying" in p for p in problems)


# --------------------------------------------------------------------------
# The column reaching a database that already exists
# --------------------------------------------------------------------------


async def columns_of(db, table):
    async with db._engine.begin() as conn:
        rows = await conn.execute(text(f"SELECT * FROM {table} LIMIT 0"))
        return set(rows.keys())


async def test_thing_types_gains_consumes_in_place(db):
    """**The migration, against a table that already exists.**

    `create_all` creates missing tables and never missing columns, so
    the live beta's `thing_types` will not gain this one by being
    redeployed - it gains it from `_LATER_COLUMNS`. Checked by dropping
    the column and putting it back, which is the shape of the live
    database rather than of a fresh one.

    A missing column here is not a quiet failure like the log's was:
    every boot rewrites every content table, so the insert would throw
    and the bot would not start. That is the better failure and still
    worth pinning, because there is no Postgres here to rehearse the
    deploy against.
    """
    async with db._engine.begin() as conn:
        await conn.execute(text("ALTER TABLE thing_types DROP COLUMN consumes"))
    assert "consumes" not in await columns_of(db, "thing_types")

    async with db._engine.begin() as conn:
        await db._add_missing_columns(conn)

    assert "consumes" in await columns_of(db, "thing_types")


async def test_the_recipe_survives_the_trip_through_the_database(real_house):
    """The cell reaches the row the engine actually reads.

    `_finish_use` reads `consumes` off the database row, not off the
    files, so a column that loaded into nothing would leave the bug
    exactly as reported with every content check still passing.
    """
    db, guild = real_house

    import phrasing

    row = await phrasing.thing_row("stove")

    assert row.consumes == "herbs|dark_chocolate|spice_jar"
