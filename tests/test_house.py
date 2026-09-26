"""The house layout: the navigation graph, exit resolution and thread naming.

Pure functions, no database and no Discord. Phase 2b moves this layout into the
content files; until then these tests are what stop a typo in the graph reaching
a player as a dead end.
"""

import pytest

import house_utils
from house_utils import NAVIGATION_GRAPH, ROOMS


# --------------------------------------------------------------------------
# The graph itself
# --------------------------------------------------------------------------


def test_the_shipped_graph_is_sound():
    """The startup self-check must be clean against the layout we ship."""
    assert house_utils.validate_graph() == []


def test_every_room_has_an_entry():
    assert set(NAVIGATION_GRAPH) == set(ROOMS)


def test_there_are_nine_rooms():
    assert len(ROOMS) == 9
    assert len(set(ROOMS)) == 9


def test_every_exit_key_matches_its_own_id():
    for room, exits in NAVIGATION_GRAPH.items():
        for key, exit_ in exits.items():
            assert key == exit_.thing_id, f"{room}: {key!r} keyed an exit id {exit_.thing_id!r}"


def test_every_exit_leads_to_a_real_room():
    for room, exits in NAVIGATION_GRAPH.items():
        for exit_ in exits.values():
            assert exit_.destination in ROOMS


def test_every_exit_has_a_return():
    """The spec states exits are bidirectional; HE was the one that went missing."""
    for room, exits in NAVIGATION_GRAPH.items():
        for exit_ in exits.values():
            back = {e.destination for e in NAVIGATION_GRAPH[exit_.destination].values()}
            assert room in back, f"{room} -> {exit_.destination} has no way back"


def test_the_entryway_can_be_returned_to_from_upstairs():
    """The specific regression: EH led up with no HE leading down."""
    assert house_utils.find_exit("Upstairs Hallway", "HE") == "Entryway"


def test_every_room_is_reachable_from_the_start():
    seen, queue = {house_utils.STARTING_ROOM}, [house_utils.STARTING_ROOM]
    while queue:
        for exit_ in NAVIGATION_GRAPH[queue.pop()].values():
            if exit_.destination not in seen:
                seen.add(exit_.destination)
                queue.append(exit_.destination)
    assert seen == set(ROOMS)


def test_exit_ids_are_unique_across_the_whole_house():
    ids = [e.thing_id for exits in NAVIGATION_GRAPH.values() for e in exits.values()]
    assert len(ids) == len(set(ids))


def test_no_room_has_two_exits_described_the_same_way():
    for room, exits in NAVIGATION_GRAPH.items():
        descriptions = [e.thing.lower() for e in exits.values()]
        assert len(descriptions) == len(set(descriptions)), room


def test_no_exit_leads_back_into_its_own_room():
    for room, exits in NAVIGATION_GRAPH.items():
        for exit_ in exits.values():
            assert exit_.destination != room


def test_validate_graph_catches_a_dead_end(monkeypatch):
    """The validator has to actually fail on a broken layout, not just pass."""
    broken = {room: dict(exits) for room, exits in NAVIGATION_GRAPH.items()}
    del broken["Upstairs Hallway"]["HE"]
    monkeypatch.setattr(house_utils, "NAVIGATION_GRAPH", broken)

    problems = house_utils.validate_graph()
    assert any("no return exit" in p for p in problems)


def test_validate_graph_catches_an_unknown_destination(monkeypatch):
    broken = {room: dict(exits) for room, exits in NAVIGATION_GRAPH.items()}
    broken["Bedroom"]["BX"] = house_utils.Exit("BX", "BX_desc", "Attic")
    monkeypatch.setattr(house_utils, "NAVIGATION_GRAPH", broken)

    problems = house_utils.validate_graph()
    assert any("unknown room 'Attic'" in p for p in problems)


# --------------------------------------------------------------------------
# Resolving what a player typed
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed", ["EL", "el", "  el  ", "EL_desc", "el_desc", "Living Room", "living room"]
)
def test_an_exit_resolves_by_id_description_or_destination(typed):
    assert house_utils.find_exit("Entryway", typed) == "Living Room"


def test_the_resolved_exit_carries_the_canonical_description():
    """Whatever the player typed, the announcement uses the exit's own wording."""
    resolved = house_utils.resolve_exit("Entryway", "living room")
    assert resolved.thing == "EL_desc"
    assert resolved.thing_id == "EL"


@pytest.mark.parametrize("typed", ["", "   ", "nowhere", "XX", "Attic"])
def test_unresolvable_input_returns_nothing(typed):
    assert house_utils.resolve_exit("Entryway", typed) is None
    assert house_utils.find_exit("Entryway", typed) is None


def test_an_exit_from_another_room_does_not_resolve_here():
    """BH leaves the Bedroom; typing it in the Entryway must not work."""
    assert house_utils.find_exit("Bedroom", "BH") == "Upstairs Hallway"
    assert house_utils.find_exit("Entryway", "BH") is None


def test_resolving_from_a_room_that_does_not_exist_returns_nothing():
    assert house_utils.resolve_exit("Attic", "EL") is None


def test_every_exit_in_the_house_resolves_from_its_own_room():
    for room, exits in NAVIGATION_GRAPH.items():
        for exit_ in exits.values():
            for typed in (exit_.thing_id, exit_.thing, exit_.destination):
                assert house_utils.resolve_exit(room, typed) == exit_


def test_placeholder_descriptions_are_obvious():
    """Unwritten copy has to stand out in play rather than pass for finished."""
    for exits in NAVIGATION_GRAPH.values():
        for exit_ in exits.values():
            assert exit_.thing == f"{exit_.thing_id}_desc"


# --------------------------------------------------------------------------
# Thread names
# --------------------------------------------------------------------------


def test_cohort_a_sees_the_bare_room_name():
    assert house_utils.get_thread_name("Entryway", "A") == "Entryway"


def test_cohort_b_sees_the_article():
    assert house_utils.get_thread_name("Entryway", "B") == "The Entryway"


@pytest.mark.parametrize("cohort", ["C", "a", "", None, "AB"])
def test_an_unknown_cohort_is_refused(cohort):
    with pytest.raises(ValueError):
        house_utils.get_thread_name("Entryway", cohort)


def test_the_house_needs_eighteen_threads():
    """Nine rooms in two cohorts. Step 4 drops this to nine."""
    names = house_utils.all_thread_names()
    assert len(names) == 18
    assert len(set(names)) == 18


def test_every_room_appears_once_per_cohort():
    names = set(house_utils.all_thread_names())
    for room in ROOMS:
        assert room in names
        assert f"The {room}" in names


def test_the_starting_room_is_a_real_room():
    assert house_utils.STARTING_ROOM in ROOMS
