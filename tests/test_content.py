"""Parsing and validating the content files.

Two jobs here. The first is that the content we actually ship loads and passes -
a check that runs on every push, so a writer's edit cannot reach main broken.

The second is that each validator fires. A validation suite that only ever sees
good input proves nothing: every check below is handed content broken in exactly
the way it exists to catch, because a check that cannot fail is worse than no
check - it reads like coverage.
"""

import copy
import re
from dataclasses import replace

import pytest

import content


@pytest.fixture
def shipped():
    """The real content files, parsed but not validated."""
    return content.load_files()


def thing(c, thing_id):
    return next(t for t in c.things if t.thing_id == thing_id)


def replace_thing(c, thing_id, **changes):
    """A copy of the content with one thing altered."""
    out = copy.deepcopy(c)
    out.things = [replace(t, **changes) if t.thing_id == thing_id else t for t in out.things]
    return out


def problems_matching(c, fragment):
    return [p for p in content.validate(c) if fragment in p]


# --------------------------------------------------------------------------
# The content we ship
# --------------------------------------------------------------------------


def test_the_shipped_content_parses():
    c = content.load_files()
    assert len(c.rooms) == 9
    assert len(c.things) == 141
    assert len(c.defaults) == 23
    assert len(c.drops) == 1
    assert len(c.restocks) == 3


def test_the_shipped_content_validates():
    """If this fails, someone edited a TSV into a state the loader would refuse.

    Clean since 27 September. Three sources were unreachable before that - the
    tortilla chips, the ring of iron keys and the coil of copper wire - and each
    was fixed by naming it in the prose that reveals it rather than by relaxing
    the check.
    """
    assert content.validate(content.load_files()) == []


def test_every_source_is_findable():
    """The check with no counterpart elsewhere: a source appears in no listing,
    so prose that fails to name it makes it unobtainable rather than untidy."""
    problems = [
        p for p in content.validate(content.load_files()) if "named nowhere" in p
    ]
    assert problems == []


def test_there_are_twenty_exits_and_they_match_the_rooms(shipped):
    exits = [t for t in shipped.things if t.is_exit]
    assert len(exits) == 20
    assert all(e.destination_room_id in shipped.rooms_by_id for e in exits)


def test_the_secret_library_is_the_only_room_locked_at_launch(shipped):
    locked = [r.room_id for r in shipped.rooms if not r.open_at_launch]
    assert locked == ["SE"]


def test_lumber_is_the_only_thing_with_a_cooldown(shipped):
    cooled = {t.thing_id: t.use_cooldown_hours for t in shipped.things if t.use_cooldown_hours}
    assert cooled == {"lumber": 48}


def test_quantity_many_parses_as_no_count(shipped):
    assert thing(shipped, "lumber").quantity is None


def test_aliases_split_on_pipes(shipped):
    assert "mirror" in thing(shipped, "ornate_mirror").names


def test_blank_cells_become_none_not_empty_strings(shipped):
    for t in shipped.things:
        for field in ("requires", "present_when", "transforms_to", "yields", "contained_in"):
            assert getattr(t, field) != ""


# --------------------------------------------------------------------------
# Each validator, handed the break it exists to catch
# --------------------------------------------------------------------------


def test_a_thing_in_a_room_that_does_not_exist_is_caught(shipped):
    broken = replace_thing(shipped, "nacho_chips", room_id="ZZ")
    assert problems_matching(broken, "unknown room")


def test_a_dangling_yields_target_is_caught(shipped):
    broken = replace_thing(shipped, "cat_food_stash_pantry", yields="nonexistent_thing")
    assert problems_matching(broken, "is not a thing")


def test_a_dangling_transform_target_is_caught(shipped):
    broken = replace_thing(shipped, "used_baby_bottle", transforms_to="nope")
    assert problems_matching(broken, "is not a thing")


def test_an_unknown_thing_type_is_caught(shipped):
    broken = replace_thing(shipped, "nacho_chips", type="widget")
    assert problems_matching(broken, "has type")


def test_a_duplicate_thing_id_is_caught(shipped):
    broken = copy.deepcopy(shipped)
    broken.things.append(broken.things[0])
    assert problems_matching(broken, "duplicate thing id")


def test_two_levels_of_containment_are_caught(shipped):
    """spice_jar is in amazon_box; putting amazon_box inside something makes it two."""
    broken = replace_thing(shipped, "amazon_box", contained_in="ornate_mirror")
    assert problems_matching(broken, "containment is one level only")


def test_a_container_in_a_different_room_is_caught(shipped):
    broken = replace_thing(shipped, "spice_jar", room_id="KI")
    assert problems_matching(broken, "but its container")


def test_two_things_sharing_a_word_in_one_room_are_caught(shipped):
    broken = replace_thing(shipped, "nacho_chips", aliases=("mirror",), room_id="EN")
    assert problems_matching(broken, "could mean any of")


def test_the_same_word_in_two_different_rooms_is_fine(shipped):
    """A player is only ever in one room, so this is not ambiguous."""
    broken = replace_thing(shipped, "music_box", aliases=("mirror",))
    assert not problems_matching(broken, "could mean any of")


def test_a_thing_with_no_text_row_is_caught(shipped):
    broken = copy.deepcopy(shipped)
    broken.thing_text = [r for r in broken.thing_text if r.entity_id != "nacho_chips"]
    assert problems_matching(broken, "nacho_chips has no text row")


def test_a_text_row_for_a_thing_that_does_not_exist_is_caught(shipped):
    broken = copy.deepcopy(shipped)
    broken.thing_text.append(
        content.TextRow(entity_id="ghost", state="default", since_drop=1, text={"look": "x"})
    )
    assert problems_matching(broken, "unknown thing")


def test_a_thing_with_only_a_non_default_state_is_caught(shipped):
    """rolltop_desk has default and drawer_unjammed; losing the default is fatal."""
    broken = copy.deepcopy(shipped)
    broken.thing_text = [
        r
        for r in broken.thing_text
        if not (r.entity_id == "rolltop_desk" and r.state == "default")
    ]
    assert problems_matching(broken, "no default state")


def test_an_exit_with_no_destination_is_caught(shipped):
    broken = replace_thing(shipped, "EL", destination_room_id=None)
    assert problems_matching(broken, "has no destination_room_id")


def test_a_one_way_exit_is_caught(shipped):
    """The HE regression, in content form: remove the way back and the check fires."""
    broken = copy.deepcopy(shipped)
    broken.things = [t for t in broken.things if t.thing_id != "HE"]
    broken.thing_text = [r for r in broken.thing_text if r.entity_id != "HE"]
    assert problems_matching(broken, "with no exit back")


def test_an_exit_marked_takeable_is_caught(shipped):
    broken = replace_thing(shipped, "EL", takeable=True)
    assert problems_matching(broken, "is marked takeable")


def test_a_room_nothing_leads_to_is_caught(shipped):
    """Cutting both ways into the Nursery strands it, even though no reference dangles."""
    broken = copy.deepcopy(shipped)
    broken.things = [t for t in broken.things if t.thing_id not in {"HN", "NH"}]
    broken.thing_text = [r for r in broken.thing_text if r.entity_id not in {"HN", "NH"}]
    assert problems_matching(broken, "cannot be reached")


def test_a_gate_on_a_state_nothing_sets_is_caught(shipped):
    broken = replace_thing(shipped, "nacho_chips", present_when="moon_is_full")
    assert problems_matching(broken, "which nothing sets")


def test_a_negated_gate_is_read_without_its_bang(shipped):
    """`!stairs_repaired` gates on a real state and must not be reported."""
    assert not problems_matching(shipped, "which nothing sets")
    broken = replace_thing(shipped, "nacho_chips", present_when="!stairs_repaired")
    assert not problems_matching(broken, "which nothing sets")


# --------------------------------------------------------------------------
# Unobtainable things
#
# The check with no counterpart in the old validator: every reference a roomless
# object makes can be sound while nothing in the game ever produces it.
# --------------------------------------------------------------------------


def test_a_roomless_object_nothing_produces_is_caught(shipped):
    broken = copy.deepcopy(shipped)
    broken.things.append(
        replace(thing(shipped, "nacho_chips"), thing_id="ghost_item", room_id=None, quantity=0)
    )
    broken.thing_text.append(
        content.TextRow(
            entity_id="ghost_item", state="default", since_drop=1, text={"look": "x"}
        )
    )
    assert problems_matching(broken, "no player could ever obtain it")


def test_the_sanitized_bottle_is_obtainable_through_its_transform(shipped):
    """Roomless and no source feeds it - the bottle transform is what produces it."""
    bottle = thing(shipped, "sanitized_baby_bottle")
    assert bottle.room_id in (None, "")
    assert not any(t.yields == bottle.thing_id for t in shipped.things)
    assert any(t.transforms_to == bottle.thing_id for t in shipped.things)
    assert not problems_matching(shipped, "no player could ever obtain it")


def test_cutting_the_transform_makes_the_sanitized_bottle_unobtainable(shipped):
    broken = replace_thing(shipped, "used_baby_bottle", transforms_to=None)
    assert problems_matching(broken, "sanitized_baby_bottle")


# --------------------------------------------------------------------------
# Malformed files
# --------------------------------------------------------------------------


def test_a_missing_file_is_reported_by_name(tmp_path):
    with pytest.raises(content.ContentError) as caught:
        content.load_files(tmp_path)
    assert "rooms.tsv is missing" in str(caught.value)


def test_a_missing_column_is_reported(tmp_path):
    (tmp_path / "rooms.tsv").write_text("room_id\tsort_order\nEN\t1\n", encoding="utf-8")
    with pytest.raises(content.ContentError) as caught:
        content.load_files(tmp_path)
    assert "no name column" in str(caught.value)


def test_a_stray_tab_is_reported_with_its_line_number(tmp_path):
    for name, text in {
        "rooms.tsv": "room_id\tname\tsort_order\topen_at_launch\nEN\tEntryway\t1\tyes\textra\n",
    }.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    with pytest.raises(content.ContentError) as caught:
        content.load_files(tmp_path)
    assert "line 2 has more fields" in str(caught.value)


def test_validate_reports_every_problem_at_once(shipped):
    """A writer should get the whole report, not the first line of it."""
    broken = replace_thing(shipped, "nacho_chips", room_id="ZZ", type="widget")
    problems = content.validate(broken)

    assert len(problems) >= 2
    assert any("unknown room" in p for p in problems)
    assert any("has type" in p for p in problems)


def test_the_error_message_names_the_count_and_lists_them():
    error = content.ContentError(["first thing wrong", "second thing wrong"])
    message = str(error)

    assert "2 problem(s)" in message
    assert "first thing wrong" in message
    assert "second thing wrong" in message


# --------------------------------------------------------------------------
# The craving lookup
#
# Generated from Unicode's emoji-test.txt rather than written by hand, because
# a mis-grouped emoji shows up as the bot saying "right subgroup" to a wrong
# guess - which nobody would trace back to a data file.
# --------------------------------------------------------------------------


def test_the_emoji_file_loads(shipped):
    assert len(shipped.emoji_groups) == 132


def test_dishware_is_not_drawable(shipped):
    """A plate as the cat's craving of the day is a strange day."""
    dishware = [e for e in shipped.emoji_groups if e.subgroup == content.DISHWARE_SUBGROUP]

    assert len(dishware) == 7
    assert not any(e.drawable for e in dishware)


def test_the_drawable_pool_is_everything_edible(shipped):
    """125 non-dishware rows, less the salt shaker, which is food-prepared in
    Unicode but is not a craving anyone wants."""
    assert len(shipped.craving_pool) == 124


def test_salt_is_not_a_possible_craving(shipped):
    """A writer's call, made in the file rather than in code - which is the
    whole reason `drawable` is a column."""
    salt = next(e for e in shipped.emoji_groups if e.emoji == "🧂")

    assert salt.subgroup == "food-prepared"
    assert salt.drawable is False


def test_a_plate_still_resolves_to_a_subgroup(shipped):
    """It can never be the answer, but it is a legal guess and must not crash -
    which is why `drawable` is a separate column from the grouping."""
    plate = next(e for e in shipped.emoji_groups if e.subgroup == content.DISHWARE_SUBGROUP)

    assert plate.subgroup
    assert plate.drawable is False


def test_every_subgroup_the_spec_names_is_present_except_marine(shipped):
    """food-marine is in the Functional Spec's list but not in Unicode 18.0:
    crab, lobster, shrimp, squid and oyster are Animals & Nature/animal-marine.
    The pool is the Food & Drink group, so there is no seafood in it."""
    found = {e.subgroup for e in shipped.emoji_groups}

    assert found == {
        "food-fruit",
        "food-vegetable",
        "food-prepared",
        "food-asian",
        "food-sweet",
        "drink",
        "dishware",
    }


def test_emoji_are_normalised_on_load(shipped):
    """Not at compare time: normalising there lets the file and a reaction
    disagree invisibly for one emoji nobody thinks to test."""
    assert not any("\ufe0f" in e.emoji for e in shipped.emoji_groups)


def test_the_pool_is_large_enough_for_the_game(shipped):
    """The spec sizes the daily guess at roughly 1-in-130, narrowed by subgroup
    to something a room closes out in a few tries."""
    assert 100 <= len(shipped.craving_pool) <= 160  # noqa: PLR2004
    by_group = {}
    for e in shipped.craving_pool:
        by_group.setdefault(e.subgroup, []).append(e)
    assert all(5 <= len(v) <= 40 for v in by_group.values())


def test_a_duplicate_emoji_is_caught(shipped):
    broken = copy.deepcopy(shipped)
    broken.emoji_groups.append(broken.emoji_groups[0])

    assert problems_matching(broken, "appears twice")


def test_a_duplicate_that_differs_only_by_variation_selector_is_caught():
    """They normalise to the same string, so one would shadow the other and
    which won would depend on row order."""
    from content import EmojiGroup

    c = content.Content()
    c.emoji_groups = [
        EmojiGroup(emoji=content.normalise_emoji("\u2615\ufe0f"), subgroup="drink", drawable=True),
        EmojiGroup(emoji=content.normalise_emoji("\u2615"), subgroup="drink", drawable=True),
    ]
    assert any("appears twice" in p for p in content._check_emoji_groups(c))


def test_an_emoji_with_no_subgroup_is_caught(shipped):
    from dataclasses import replace

    broken = copy.deepcopy(shipped)
    broken.emoji_groups[0] = replace(broken.emoji_groups[0], subgroup="")

    assert problems_matching(broken, "has no subgroup")


def test_a_file_with_nothing_drawable_is_caught(shipped):
    from dataclasses import replace

    broken = copy.deepcopy(shipped)
    broken.emoji_groups = [replace(e, drawable=False) for e in broken.emoji_groups]

    assert problems_matching(broken, "could never be drawn")
