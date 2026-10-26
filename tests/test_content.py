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
    assert len(c.rooms) == 10  # nine rooms and the channel
    assert len(c.things) == 162  # ...drop 1's ten scenery, and the stand's four
    assert len(c.defaults) == 115  # ...and the craving status line
    assert len(c.drops) == 9      # 0 to 3 built; 10 to 50 named ahead of their content
    assert len(c.restocks) == 4  # the toy channel row joined them


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
    """The channel is `open_at_launch = no` as well, for a different
    reason: the Secret Library is found, and the channel is never walked
    into at all."""
    locked = [r.room_id for r in shipped.rooms if not r.open_at_launch]
    assert locked == ["SE", content.CHANNEL_ROOM]


def test_what_carries_a_cooldown(shipped):
    """**Two kinds, and the bed changed kind.**

    The staircase waits two rolling days between planks: forty-eight
    hours from whenever the last one went in. The bed waits for Pacific
    midnight, which resets for everybody at the same instant.

    It used to be rolling hours here too, because that is what the
    column meant and the design accepted it rather than coding around
    it. A rolling day drifts - fluff at nine tonight and the next turn
    is nine tomorrow - so anybody taking their turn at the first
    opportunity loses a few minutes a day forever, and somebody who
    fluffs just before midnight loses nearly all of the next day.
    """
    hourly = {
        t.thing_id: t.use_cooldown_hours
        for t in shipped.things
        if t.use_cooldown_hours
    }
    daily = {t.thing_id for t in shipped.things if t.use_cooldown_daily}

    assert hourly == {"lumber": 48}
    assert daily == {"cat_bed"}
    assert not (set(hourly) & daily)  # the loader refuses both on one row


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


def test_a_toy_is_obtainable_through_the_class_its_restock_names(shipped):
    """Both toys sit in no room: drop 2's channel opens empty and the
    schedule fills it. The row that fills it names `type:toy` rather
    than either toy, so counting a restock as a route means expanding
    the class - unexpanded, the only way to get a toy reads as no way
    at all and the shipped files fail to load.
    """
    for toy in ("feather_wand", "crinkle_ball"):
        assert thing(shipped, toy).quantity in (None, 0)
    assert "type:toy" in {r.thing_id for r in shipped.restocks}

    assert not problems_matching(shipped, "no player could ever obtain it")


def test_pointing_that_row_at_another_class_strands_the_toys(shipped):
    """The other side of it. The expansion is a real lookup against the
    things, not a blanket pass for any row with a colon in it."""
    broken = copy.deepcopy(shipped)
    broken.restocks = [
        replace(r, thing_id="type:nothing_of_this_kind")
        if r.thing_id == "type:toy"
        else r
        for r in broken.restocks
    ]

    assert problems_matching(broken, "feather_wand")


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
    """Every emoji in the writers' catalogue, not just the edible ones.

    The file used to hold 132 food rows. It now holds all 1,927, because
    the ladder has an answer for an unrelated guess too - a 🐱 - and
    that answer needs the row to exist to be sure the guess is unrelated
    rather than unlisted."""
    assert len(shipped.emoji_groups) == 1927


def test_dishes_are_not_drawable(shipped):
    """A plate as the cat's craving of the day is a strange day.

    **This used to need a special case in code.** Dishware sits inside
    Unicode's Food & Drink group, so the old grouping made plates look
    edible and a named constant kept them out. The writers' categories
    file them under Adjacent, and the rule is data now."""
    dishes = [e for e in shipped.emoji_groups if e.type == "Dishes"]

    assert len(dishes) == 7
    assert all(e.category == "Adjacent" for e in dishes)
    assert not any(e.drawable for e in dishes)


def test_the_drawable_pool_is_the_food_and_the_prey(shipped):
    """138 Food and Prey rows, less four, for two different reasons.

    Two are new in Unicode 18.0, which Discord's picker may not have yet,
    and a craving nobody can type is unwinnable. Two are faces of an
    animal already in the pool - the 🐭 and the 🐰 - and putting a pair in
    twice would make the mouse twice as likely as the rat while giving
    the cat two ways to want the same thing.
    """
    assert len(shipped.craving_pool) == 134
    assert {e.category for e in shipped.craving_pool} == {"Food", "Prey"}
    assert not any(e.same_as for e in shipped.craving_pool)


def test_an_alias_is_still_in_the_file(shipped):
    """Out of the pool, not out of the game. The 🐭 has to resolve to a
    category and a type like anything else, because it is a legal guess -
    and the one that wins."""
    face = next(e for e in shipped.emoji_groups if e.emoji == chr(0x1F42D))
    body = next(e for e in shipped.emoji_groups if e.emoji == chr(0x1F401))

    assert face.same_as == body.emoji
    assert (face.category, face.type) == (body.category, body.type)
    assert face.drawable is False and body.drawable is True


def test_the_shipped_aliases_are_valid(shipped):
    assert content._check_emoji_aliases(shipped) == []


def test_an_alias_pointing_at_nothing_is_caught(shipped):
    groups = [
        replace(e, same_as="\u0000") if e.emoji == chr(0x1F42D) else e
        for e in shipped.emoji_groups
    ]

    problems = content._check_emoji_aliases(replace(shipped, emoji_groups=groups))

    assert any("not in the file" in p for p in problems)


def test_a_chain_of_aliases_is_caught(shipped):
    """Whether 🐭 answers for 🐁 or for whatever 🐁 answers for would
    depend on which row was read first."""
    groups = [
        replace(e, same_as=chr(0x1F400)) if e.emoji == chr(0x1F401) else e
        for e in shipped.emoji_groups
    ]

    problems = content._check_emoji_aliases(replace(shipped, emoji_groups=groups))

    assert any("chains are not resolved" in p for p in problems)


def test_an_alias_filed_somewhere_else_is_caught(shipped):
    """A 👀 means "right type". An alias in another type would win while
    the rung below it said the type was wrong."""
    groups = [
        replace(e, type="Bird") if e.emoji == chr(0x1F42D) else e
        for e in shipped.emoji_groups
    ]

    problems = content._check_emoji_aliases(replace(shipped, emoji_groups=groups))

    assert any("ladder would disagree with itself" in p for p in problems)


def test_a_drawable_alias_is_caught(shipped):
    groups = [
        replace(e, drawable=True) if e.emoji == chr(0x1F42D) else e
        for e in shipped.emoji_groups
    ]

    problems = content._check_emoji_aliases(replace(shipped, emoji_groups=groups))

    assert any("two ways" in p for p in problems)


def test_an_alias_for_something_undrawable_is_caught(shipped):
    """Both halves unwinnable: the cat can never want the 🐁, and the 🐭
    only ever answers for it."""
    groups = [
        replace(e, drawable=False) if e.emoji == chr(0x1F401) else e
        for e in shipped.emoji_groups
    ]

    problems = content._check_emoji_aliases(replace(shipped, emoji_groups=groups))

    assert any("can never want" in p for p in problems)


def test_salt_is_not_a_possible_craving(shipped):
    """A writer's call, made in the file rather than in code - which is the
    whole reason `drawable` is a column."""
    salt = next(e for e in shipped.emoji_groups if e.emoji == "🧂")

    assert (salt.category, salt.type) == ("Adjacent", "Ingredient")
    assert salt.drawable is False


def test_a_plate_still_resolves_to_a_category_and_type(shipped):
    """It can never be the answer, but it is a legal guess and must not crash -
    which is why `drawable` is a separate column from the grouping."""
    plate = next(e for e in shipped.emoji_groups if e.type == "Dishes")

    assert plate.category and plate.type
    assert plate.drawable is False


def test_the_bots_own_reactions_are_excluded(shipped):
    """The faces the bot answers with are in the file so the writers can
    swap them, and out of the game so that reacting with one cannot be
    read as a guess - which would let a player walk the ladder backwards
    from the bot's own replies.

    Seven, not six: five rungs, the ❌ that closes a message, and the
    ✖ that pads out the slot the ❌ could not take.
    """
    excluded = [e for e in shipped.emoji_groups if e.excluded]

    assert len(excluded) == len(shipped.craving_reactions) == 7
    assert all(e.category == content.BOT_CATEGORY for e in excluded)
    assert not any(e.drawable for e in excluded)


def test_the_categories_are_the_ones_the_ladder_judges_by(shipped):
    """**Seven, and the game pays only two of them.** Today's craving is
    always Food or Prey; Adjacent and Toy can earn the second rung and no
    more; Misc and Cat are the friendly nothing; Bot is the bot's own
    replies, kept out of the game.

    Unicode's own grouping is gone, and with it the accident it caused -
    dishware sat inside Food & Drink, so plates looked edible."""
    assert {e.category for e in shipped.emoji_groups} == {
        "Food",
        "Prey",
        "Adjacent",
        "Toy",
        "Cat",
        "Misc",
        "Bot",
    }


def test_drinks_are_adjacent_rather_than_food(shipped):
    """A writers' call that changes play: a drink can earn the
    wrong-category rung at best, where the old file filed it as food."""
    coffee = next(
        e for e in shipped.emoji_groups
        if e.emoji == content.normalise_emoji(chr(0x2615))
    )

    assert coffee.category == "Adjacent"
    assert coffee.drawable is False


def test_emoji_are_normalised_on_load(shipped):
    """Not at compare time: normalising there lets the file and a reaction
    disagree invisibly for one emoji nobody thinks to test."""
    assert not any("\ufe0f" in e.emoji for e in shipped.emoji_groups)


def test_the_pool_is_large_enough_for_the_game(shipped):
    """The spec sizes the daily guess at roughly 1-in-130, narrowed by type
    to something a room closes out in a few tries."""
    assert 100 <= len(shipped.craving_pool) <= 160  # noqa: PLR2004
    by_type = {}
    for e in shipped.craving_pool:
        by_type.setdefault(e.type, []).append(e)
    assert all(5 <= len(v) <= 40 for v in by_type.values())


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
        EmojiGroup(emoji=content.normalise_emoji("\u2615\ufe0f"), code="", name="hot beverage", category="Adjacent", type="Drinks",
            drawable=False, excluded=False),
        EmojiGroup(emoji=content.normalise_emoji("\u2615"), code="", name="hot beverage", category="Adjacent", type="Drinks",
            drawable=False, excluded=False),
    ]
    assert any("appears twice" in p for p in content._check_emoji_groups(c))


def test_an_emoji_with_no_category_or_type_is_caught(shipped):
    """The ladder judges a guess by both, so a blank one cannot be scored."""
    from dataclasses import replace

    for blank in ({"category": ""}, {"type": ""}):
        broken = copy.deepcopy(shipped)
        broken.emoji_groups[0] = replace(broken.emoji_groups[0], **blank)

        assert problems_matching(broken, "has no category or no type"), blank


def test_an_excluded_emoji_that_is_also_drawable_is_caught(shipped):
    """It would make the craving an emoji the bot refuses to judge, so
    nobody could ever win the day."""
    from dataclasses import replace

    broken = copy.deepcopy(shipped)
    broken.emoji_groups[0] = replace(
        broken.emoji_groups[0], excluded=True, drawable=True
    )

    assert problems_matching(broken, "both excluded and drawable")


def test_a_file_with_nothing_drawable_is_caught(shipped):
    from dataclasses import replace

    broken = copy.deepcopy(shipped)
    broken.emoji_groups = [replace(e, drawable=False) for e in broken.emoji_groups]

    assert problems_matching(broken, "could never be drawn")


# --------------------------------------------------------------------------
# Two doors, one word
# --------------------------------------------------------------------------


def test_two_exits_in_a_room_may_share_a_word():
    """A room can honestly contain two doorways, and its own prose calls them
    both doorways. Refusing the load would force the shared word off both,
    which leaves a player typing a word the room just used at them and being
    told the house has no such thing. Asking is the better answer."""
    parsed = content.load_files()
    entryway = {t.thing_id: t for t in parsed.things if t.room_id == "EN"}

    assert "doorway" in entryway["EL"].aliases
    assert "doorway" in entryway["ED"].aliases
    assert content.validate(parsed) == []


def test_an_exit_sharing_a_word_with_an_object_is_still_an_error():
    """The case that is almost always a slip rather than a choice."""
    from dataclasses import replace

    parsed = content.load_files()
    parsed.things = [
        replace(t, aliases=t.aliases + ("doorway",))
        if t.thing_id == "coat_rack"
        else t
        for t in parsed.things
    ]

    problems = content.validate(parsed)
    assert any("could mean any of" in p and "coat_rack" in p for p in problems)


def test_two_objects_in_a_room_sharing_a_word_is_still_an_error():
    from dataclasses import replace

    parsed = content.load_files()
    parsed.things = [
        replace(t, aliases=t.aliases + ("thing",))
        if t.thing_id in ("coat_rack", "ornate_mirror")
        else t
        for t in parsed.things
    ]

    assert any("'thing'" in p for p in content.validate(parsed))


# --------------------------------------------------------------------------
# The craving ladder
#
# Six rows, and every one of these is a way the file can be wrong while
# still loading perfectly well - which is the only kind of content error
# worth a validator.
# --------------------------------------------------------------------------


def a_ladder(**changes):
    """The shipped reactions, with one row swapped out."""
    rows = list(content.load_files().craving_reactions)
    for index, row in enumerate(rows):
        if row.outcome in changes:
            rows[index] = replace(row, **changes[row.outcome])
    return rows


def with_ladder(rows):
    parsed = content.load_files()
    return replace(parsed, craving_reactions=rows)


def test_the_shipped_ladder_is_valid():
    assert content._check_craving_reactions(content.load_files()) == []


def test_a_missing_outcome_is_caught():
    """One row short is one answer the bot has nothing to say for."""
    short = [r for r in content.load_files().craving_reactions if r.outcome != "win"]

    problems = content._check_craving_reactions(with_ladder(short))

    assert any("no row for win" in p for p in problems)


def test_an_outcome_the_game_cannot_branch_on_is_caught():
    rows = a_ladder(win={"outcome": "nearly"})

    problems = content._check_craving_reactions(with_ladder(rows))

    assert any("nearly" in p and "no branch" in p for p in problems)


def test_two_outcomes_sharing_a_face_are_caught():
    """Indistinguishable answers. The player would be told two different
    things in the same way, which is worse than being told nothing."""
    greeting = content.load_files().reaction_for_outcome["greeting"]
    rows = a_ladder(win={"emoji": greeting.emoji})

    problems = content._check_craving_reactions(with_ladder(rows))

    assert any("indistinguishable" in p for p in problems)


def test_a_ladder_out_of_order_is_caught():
    """**The one that would be hardest to find in play.** A better guess
    simply would not replace a worse one, and the message would sit on
    its 😼 while people guessed their way past it."""
    rows = a_ladder(win={"progression": 1}, greeting={"progression": 5})

    problems = content._check_craving_reactions(with_ladder(rows))

    assert any("not " in p and "increasing" in p for p in problems)


def test_a_rung_with_no_rank_is_caught():
    rows = a_ladder(right_type={"progression": None})

    problems = content._check_craving_reactions(with_ladder(rows))

    assert any("needs a progression" in p for p in problems)


def test_ranking_the_end_of_a_message_is_caught():
    """❌ is not a rung. Given one, it could outrank a win and a message
    that ran out of room could never show that somebody found it."""
    rows = a_ladder(out_of_guesses={"progression": 6})

    problems = content._check_craving_reactions(with_ladder(rows))

    assert any("end" in p and "rung" in p for p in problems)


def test_a_face_a_player_could_guess_with_is_caught():
    """The six have to be excluded from the emoji file, or a player could
    react with the bot's own 😻 and read the answer out of the reply."""
    parsed = content.load_files()
    groups = [
        replace(row, excluded=False) if row.category == "Bot" else row
        for row in parsed.emoji_groups
    ]

    problems = content._check_craving_reactions(replace(parsed, emoji_groups=groups))

    assert any("not excluded" in p for p in problems)


# --------------------------------------------------------------------------
# The written opening week
# --------------------------------------------------------------------------


def test_the_shipped_script_is_valid():
    assert content._check_scripted_cravings(content.load_files()) == []


def test_a_scripted_craving_that_is_not_in_the_file_is_caught():
    """By name, so a writer renaming a row in the catalogue breaks this
    rather than dropping the server quietly into a random draw on day one."""
    parsed = content.load_files()
    groups = [row for row in parsed.emoji_groups if row.name != "broccoli"]

    problems = content._check_scripted_cravings(replace(parsed, emoji_groups=groups))

    assert any("broccoli" in p and "not a CLDR short name" in p for p in problems)


def test_a_scripted_craving_that_is_not_drawable_is_caught():
    parsed = content.load_files()
    groups = [
        replace(row, drawable=False) if row.name == "fish" else row
        for row in parsed.emoji_groups
    ]

    problems = content._check_scripted_cravings(replace(parsed, emoji_groups=groups))

    assert any("fish" in p and "not drawable" in p for p in problems)


def test_an_ambiguous_scripted_craving_is_caught():
    """Two rows called "egg" and the game would take whichever the
    database happened to return first."""
    parsed = content.load_files()
    egg = next(row for row in parsed.emoji_groups if row.name == "egg")
    groups = list(parsed.emoji_groups) + [replace(egg, emoji="x")]

    problems = content._check_scripted_cravings(replace(parsed, emoji_groups=groups))

    assert any("egg" in p and "2 rows" in p for p in problems)
