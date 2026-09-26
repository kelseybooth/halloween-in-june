"""Rooms, things and inventory - the queries `/look` and `/inventory` run on.

This is the suite phase 2a step 4 leans on: removing cohorts rewrites every
query here, so the behaviour that must survive that change is pinned down first.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A

import house_utils


# --------------------------------------------------------------------------
# Rooms
# --------------------------------------------------------------------------


async def test_seeding_creates_one_row_per_room(db):
    assert await db.seed_rooms(GUILD_A, house_utils.ROOMS) == 9


async def test_seeding_twice_creates_nothing_the_second_time(db):
    await db.seed_rooms(GUILD_A, house_utils.ROOMS)
    assert await db.seed_rooms(GUILD_A, house_utils.ROOMS) == 0


async def test_reseeding_does_not_wipe_a_writers_description(db):
    """Rebuilding the house must never cost a writer their work."""
    await db.seed_rooms(GUILD_A, ["Kitchen"])
    await db.set_room_description(GUILD_A, "Kitchen", "Something is burning.")
    await db.seed_rooms(GUILD_A, ["Kitchen"])

    assert await db.get_room_description(GUILD_A, "Kitchen") == "Something is burning."


async def test_a_seeded_room_starts_with_no_description(db):
    await db.seed_rooms(GUILD_A, ["Kitchen"])
    assert await db.get_room_description(GUILD_A, "Kitchen") is None


async def test_setting_a_description_twice_replaces_it(db):
    await db.set_room_description(GUILD_A, "Kitchen", "first")
    await db.set_room_description(GUILD_A, "Kitchen", "second")
    assert await db.get_room_description(GUILD_A, "Kitchen") == "second"


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
async def test_a_whitespace_description_reads_as_unset(db, blank):
    """So the caller shows its generic fallback rather than an empty message."""
    await db.set_room_description(GUILD_A, "Kitchen", blank)
    assert await db.get_room_description(GUILD_A, "Kitchen") is None


async def test_a_description_is_returned_stripped(db):
    await db.set_room_description(GUILD_A, "Kitchen", "  padded  ")
    assert await db.get_room_description(GUILD_A, "Kitchen") == "padded"


async def test_an_unknown_room_has_no_description(db):
    assert await db.get_room_description(GUILD_A, "Nowhere") is None


# --------------------------------------------------------------------------
# Placing things
# --------------------------------------------------------------------------


async def test_adding_a_thing_creates_its_room_if_needed(db):
    """Things can be placed before the house has been initialized."""
    await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can")
    assert [n for _, n in await db.get_things_in_room(GUILD_A, "Kitchen", "A")] == ["cat food"]


async def test_thing_names_are_stored_stripped(db):
    await db.add_thing(GUILD_A, "Kitchen", "  cat food  ", "a can")
    assert [n for _, n in await db.get_things_in_room(GUILD_A, "Kitchen", "A")] == ["cat food"]


async def test_the_same_name_can_be_placed_many_times(db):
    """Five cans in the Kitchen are five rows sharing a name."""
    for _ in range(5):
        await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can")
    assert len(await db.get_things_in_room(GUILD_A, "Kitchen", "A")) == 5


@pytest.mark.parametrize("bad", ["C", "a", "", "AB"])
async def test_an_unknown_cohort_is_refused(db, bad):
    with pytest.raises(ValueError):
        await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can", cohort=bad)


async def test_an_empty_room_lists_nothing(db):
    await db.seed_rooms(GUILD_A, ["Kitchen"])
    assert await db.get_things_in_room(GUILD_A, "Kitchen", "A") == []


# --------------------------------------------------------------------------
# Cohort placement
#
# Step 4 removes cohorts. These assert only that placement is honoured while it
# exists; the visibility rules below are the ones that must outlive the change.
# --------------------------------------------------------------------------


async def test_a_thing_with_no_cohort_is_visible_to_both(db):
    await db.add_thing(GUILD_A, "Entryway", "mirror", "cloudy", cohort=None)
    assert len(await db.get_things_in_room(GUILD_A, "Entryway", "A")) == 1
    assert len(await db.get_things_in_room(GUILD_A, "Entryway", "B")) == 1


async def test_a_cohort_thing_is_visible_only_to_that_cohort(db):
    await db.add_thing(GUILD_A, "Entryway", "cat food", "a can", cohort="A")
    assert len(await db.get_things_in_room(GUILD_A, "Entryway", "A")) == 1
    assert await db.get_things_in_room(GUILD_A, "Entryway", "B") == []


# --------------------------------------------------------------------------
# Visibility once something is carried
#
# An instance leaves its room only when it is exclusive (`removed_on_take`) and
# somebody holds it. Anything else stays put for the next player.
# --------------------------------------------------------------------------


async def test_an_exclusive_thing_disappears_from_the_room_when_taken(db):
    note = await db.add_thing(GUILD_A, "Kitchen", "note", "a secret", removed_on_take=True)
    await db.add_to_inventory(ALICE, GUILD_A, note)
    assert await db.get_things_in_room(GUILD_A, "Kitchen", "A") == []


async def test_an_exclusive_thing_is_gone_for_everyone_not_just_the_taker(db):
    note = await db.add_thing(GUILD_A, "Kitchen", "note", "a secret", removed_on_take=True)
    await db.add_to_inventory(ALICE, GUILD_A, note)

    assert await db.look_at_thing(BOB, GUILD_A, "Kitchen", "A", "note") is None


async def test_a_copyable_thing_stays_in_the_room_when_taken(db):
    """Somebody taking a copy leaves the original for the next player."""
    poster = await db.add_thing(
        GUILD_A, "Kitchen", "poster", "a notice", removed_on_take=False
    )
    await db.add_to_inventory(ALICE, GUILD_A, poster)
    assert len(await db.get_things_in_room(GUILD_A, "Kitchen", "A")) == 1


async def test_dropping_an_exclusive_thing_returns_it_to_the_room(db):
    note = await db.add_thing(GUILD_A, "Kitchen", "note", "a secret", removed_on_take=True)
    await db.add_to_inventory(ALICE, GUILD_A, note)
    await db.remove_from_inventory(ALICE, GUILD_A, note)

    assert len(await db.get_things_in_room(GUILD_A, "Kitchen", "A")) == 1


async def test_one_instance_taken_does_not_hide_its_siblings(db):
    ids = [
        await db.add_thing(GUILD_A, "Kitchen", "can", "a can", removed_on_take=True)
        for _ in range(3)
    ]
    await db.add_to_inventory(ALICE, GUILD_A, ids[0])
    assert len(await db.get_things_in_room(GUILD_A, "Kitchen", "A")) == 2


# --------------------------------------------------------------------------
# /look
# --------------------------------------------------------------------------


async def test_look_finds_a_thing_in_the_room(db):
    await db.add_thing(GUILD_A, "Kitchen", "cat food", "A dented can.")
    result = await db.look_at_thing(ALICE, GUILD_A, "Kitchen", "A", "cat food")
    assert result.description == "A dented can."
    assert result.count == 1


@pytest.mark.parametrize("typed", ["CAT FOOD", "Cat Food", "  cat food  ", "cAt FoOd"])
async def test_look_is_case_and_whitespace_insensitive(db, typed):
    await db.add_thing(GUILD_A, "Kitchen", "cat food", "A dented can.")
    assert await db.look_at_thing(ALICE, GUILD_A, "Kitchen", "A", typed) is not None


async def test_look_at_something_absent_finds_nothing(db):
    await db.add_thing(GUILD_A, "Kitchen", "cat food", "A dented can.")
    assert await db.look_at_thing(ALICE, GUILD_A, "Kitchen", "A", "hammer") is None


@pytest.mark.parametrize("blank", ["", "   "])
async def test_look_at_nothing_finds_nothing(db, blank):
    await db.add_thing(GUILD_A, "Kitchen", "cat food", "A dented can.")
    assert await db.look_at_thing(ALICE, GUILD_A, "Kitchen", "A", blank) is None


async def test_look_counts_every_matching_instance_in_the_room(db):
    for _ in range(3):
        await db.add_thing(GUILD_A, "Kitchen", "cat food", "A dented can.")
    assert (await db.look_at_thing(ALICE, GUILD_A, "Kitchen", "A", "cat food")).count == 3


async def test_look_does_not_count_a_carried_exclusive_thing_twice(db):
    """The trap: hidden from the room, counted in the bag, so exactly one."""
    note = await db.add_thing(GUILD_A, "Kitchen", "note", "a secret", removed_on_take=True)
    await db.add_to_inventory(ALICE, GUILD_A, note)

    result = await db.look_at_thing(ALICE, GUILD_A, "Kitchen", "A", "note")
    assert result.count == 1


async def test_look_counts_a_copyable_thing_in_both_places(db):
    """One on the shelf and one in the bag really is two."""
    poster = await db.add_thing(
        GUILD_A, "Kitchen", "poster", "a notice", removed_on_take=False
    )
    await db.add_to_inventory(ALICE, GUILD_A, poster)

    result = await db.look_at_thing(ALICE, GUILD_A, "Kitchen", "A", "poster")
    assert result.count == 2


async def test_look_finds_a_carried_thing_from_another_room(db):
    """What you carry travels with you."""
    note = await db.add_thing(GUILD_A, "Kitchen", "note", "a secret", removed_on_take=True)
    await db.add_to_inventory(ALICE, GUILD_A, note)

    assert await db.look_at_thing(ALICE, GUILD_A, "Bedroom", "A", "note") is not None


async def test_look_falls_through_to_the_first_description_that_exists(db):
    """A described instance answers for an undescribed sibling."""
    await db.add_thing(GUILD_A, "Kitchen", "can", None)
    await db.add_thing(GUILD_A, "Kitchen", "can", "A dented can.")

    result = await db.look_at_thing(ALICE, GUILD_A, "Kitchen", "A", "can")
    assert result.description == "A dented can."
    assert result.count == 2


async def test_look_reports_a_match_with_no_description_at_all(db):
    await db.add_thing(GUILD_A, "Kitchen", "can", None)
    result = await db.look_at_thing(ALICE, GUILD_A, "Kitchen", "A", "can")
    assert result is not None
    assert result.description is None
    assert result.count == 1


async def test_look_respects_cohort_placement(db):
    await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can", cohort="A")
    assert await db.look_at_thing(ALICE, GUILD_A, "Kitchen", "A", "cat food") is not None
    assert await db.look_at_thing(ALICE, GUILD_A, "Kitchen", "B", "cat food") is None


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------


async def test_a_new_player_carries_nothing(db):
    assert await db.get_inventory(ALICE, GUILD_A) == []
    assert await db.inventory_count(ALICE, GUILD_A) == 0


async def test_taking_a_thing_puts_it_in_the_bag(db):
    can = await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can")
    assert await db.add_to_inventory(ALICE, GUILD_A, can) is True
    assert await db.get_inventory(ALICE, GUILD_A) == [("cat food", 1)]


async def test_taking_the_same_instance_twice_is_refused(db):
    can = await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can")
    await db.add_to_inventory(ALICE, GUILD_A, can)

    assert await db.add_to_inventory(ALICE, GUILD_A, can) is False
    assert await db.inventory_count(ALICE, GUILD_A) == 1


async def test_taking_a_thing_that_does_not_exist_is_refused(db):
    """The foreign key is what refuses it, so this only holds while it is enforced."""
    assert await db.add_to_inventory(ALICE, GUILD_A, 424242) is False


async def test_the_two_inventory_readers_always_agree(db):
    """`/inventory` shows names; anything counting the bag must see the same set.

    They can only diverge over a row pointing at a thing that does not exist,
    which the foreign key now makes unreachable on both backends.
    """
    await db.add_to_inventory(ALICE, GUILD_A, 424242)

    listed = sum(count for _, count in await db.get_inventory(ALICE, GUILD_A))
    assert listed == await db.inventory_count(ALICE, GUILD_A)


async def test_the_inventory_groups_by_name_and_sorts_alphabetically(db):
    for name in ("torch", "cat food", "cat food", "apple"):
        thing_id = await db.add_thing(GUILD_A, "Kitchen", name, None)
        await db.add_to_inventory(ALICE, GUILD_A, thing_id)

    assert await db.get_inventory(ALICE, GUILD_A) == [
        ("apple", 1),
        ("cat food", 2),
        ("torch", 1),
    ]
    assert await db.inventory_count(ALICE, GUILD_A) == 4


async def test_dropping_a_thing_removes_it(db):
    can = await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can")
    await db.add_to_inventory(ALICE, GUILD_A, can)

    assert await db.remove_from_inventory(ALICE, GUILD_A, can) is True
    assert await db.get_inventory(ALICE, GUILD_A) == []


async def test_dropping_something_you_do_not_have_is_refused(db):
    can = await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can")
    assert await db.remove_from_inventory(ALICE, GUILD_A, can) is False


async def test_one_players_bag_is_not_anothers(db):
    can = await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can")
    await db.add_to_inventory(ALICE, GUILD_A, can)

    assert await db.get_inventory(BOB, GUILD_A) == []


async def test_taking_a_thing_works_for_a_player_who_never_petted(db):
    """The users row is a foreign key; entering the house must not require /pet."""
    can = await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can")
    assert await db.add_to_inventory(ALICE, GUILD_A, can) is True


async def test_foreign_keys_are_enforced_on_this_backend(db):
    """The guard behind the two tests above.

    SQLite defaults foreign key enforcement off, so without the pragma the
    local and CI backend accepts rows PostgreSQL refuses. Assert the setting
    itself, not just its effect, so a regression names its own cause.
    """
    from sqlalchemy import text

    async with db._engine.connect() as conn:
        if db._engine.dialect.name == "sqlite":
            assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar() == 1


async def test_wiping_player_records_succeeds_with_foreign_keys_enforced(db):
    """`reset_db.py --yes` deletes users, who are referenced by two other tables.

    Deleting them in the wrong order fails the constraint on PostgreSQL, and
    used to pass locally only because SQLite was not checking.
    """
    import reset_db

    await db.start_game(ALICE, GUILD_A, "Entryway", [], cohort="A")
    can = await db.add_thing(GUILD_A, "Kitchen", "cat food", "a can")
    await db.add_to_inventory(ALICE, GUILD_A, can)
    await db.increment_pet_count(ALICE, GUILD_A)

    await reset_db._wipe()

    assert await db.get_pet_count(ALICE, GUILD_A) == 0
    assert await db.get_game_state(ALICE, GUILD_A) is None
    assert await db.inventory_count(ALICE, GUILD_A) == 0
    # The room's contents are a writer's work and must survive a player wipe.
    assert len(await db.get_things_in_room(GUILD_A, "Kitchen", "A")) == 1
