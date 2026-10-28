"""The thirty-five conditions, one test each, plus the families they share.

Every earnable achievement is earned here through the real content and, where
a command exists for it, through the real handler. The seven blocked ones are
asserted to be registered and unearnable, which is the whole of what can be
said about them until the systems they wait on ship.

The date window gets more attention than anything else, because it is seven
achievements running off one function and the failure mode is silent: a
window an hour out means a player in Japan quietly cannot earn theirs, and
nothing anywhere reports it.
"""

from datetime import date, datetime, time, timedelta, timezone

import pytest

from conftest import ALICE, BOB, GUILD_A, LAST_DROP, GUILD_B
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import craving
import database
import resolve
import states
import triggers
from achievements import Context

PACIFIC = database.PACIFIC


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.forget_arrivals()
    triggers.register_all()
    yield
    achievements.clear()
    triggers.forget_arrivals()


@pytest.fixture
def halloween():
    channel = FakeChannel(name="halloween")
    return FakeGuild(GUILD_A, channels=[channel], members=[FakeMember(ALICE), FakeMember(BOB)])


@pytest.fixture
async def playing(db, halloween):
    """Alice and Bob in the real house, with the real content.

    On the last drop rather than the one the house opens on. Every
    achievement here is tested against the moment it can be earned,
    and the renumbering put most of them behind rooms that open at
    drops 5 and 6 - on `HOUSE_DROP` two thirds of this file would be
    asserting that an achievement which has not arrived cannot be
    earned, which is true and not what any of it is about.
    """
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
        await db.start_game(who, GUILD_A, "EN", ["EN"])
    await content_loader.load_content(content_module.load_files())
    # After the load, because the drop has to exist in the database
    # before a server can be moved to it.
    await resolve.set_current_drop(GUILD_A, LAST_DROP)
    await db.set_announcement_channel(GUILD_A, halloween.text_channels[0].id)
    return db


def pacific(year, month, day, hour=12, minute=0) -> datetime:
    """A naive-UTC instant from a Pacific wall clock, as the hooks carry it."""
    local = datetime(year, month, day, hour, minute, tzinfo=PACIFIC)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def a_context(hook, **overrides):
    defaults = dict(guild_id=GUILD_A, hook=hook, user_id=ALICE)
    return Context(**{**defaults, **overrides})


async def earned(context) -> set[str]:
    return {e.achievement_id for e in await achievements.fire(context)}


async def has(user_id=ALICE, guild_id=GUILD_A) -> set[str]:
    return set(await database.player_achievements_of(guild_id, user_id))


# --------------------------------------------------------------------------
# All thirty-five, wired both ways
# --------------------------------------------------------------------------


def test_every_achievement_in_the_file_has_a_trigger():
    parsed = content_module.load_files()
    assert achievements.registration_problems(parsed.achievement_ids) == []


def test_every_row_in_the_file_is_registered():
    """Thirty-five from Release 1, and V3's seven. The count is pinned
    against the file rather than written down twice, so adding a row and
    forgetting the predicate fails here as well as at boot."""
    parsed = content_module.load_files()

    assert achievements.registered_ids() == set(parsed.achievement_ids)


def test_registering_twice_is_a_no_op():
    """The bot's boot path and a test fixture can both call it."""
    before = len(achievements.registered_ids())
    triggers.register_all()
    assert len(achievements.registered_ids()) == before


def test_every_thing_a_trigger_names_exists_in_the_content():
    """The check that catches a rename in the files going stale here. A
    predicate pointed at an id nothing has raises nothing - it just never
    fires again, which is invisible until somebody asks why."""
    things = content_module.load_files().things_by_id
    named = {
        triggers.STOVE,
        triggers.READING_GLASSES,
        triggers.BABY_MONITOR,
        triggers.COSTUME,
        triggers.CANDY,
        triggers.PUMPKINS,
        triggers.CARVING_TOOLS,
        triggers.WATERING_CAN,
        triggers.HERB_GARDEN,
        triggers.HERBS,
        triggers.KEURIG,
        triggers.TRASH_CAN,
        triggers.PASTA_POT,
        triggers.NACHO_CHIPS,
        triggers.FROZEN_BURRITO,
        triggers.GRAPHITE,
        triggers.TREE,
        *triggers.MIRRORS,
        *triggers.CAT_FOOD,
        *triggers.BABY_BOTTLES,
    }
    assert named <= set(things), sorted(named - set(things))


def test_the_three_mirrors_are_the_three_in_the_content():
    things = content_module.load_files().things_by_id
    mirrors = {key for key, t in things.items() if "mirror" in t.name.lower()}
    assert mirrors == triggers.MIRRORS


def test_the_five_flavours_are_the_five_in_the_content():
    things = content_module.load_files().things_by_id
    flavours = {
        key for key, t in things.items() if key.startswith("cat_food_") and t.type == "object"
    }
    assert flavours == triggers.CAT_FOOD


# --------------------------------------------------------------------------
# The 43-hour day
#
# Six fixed dates and one weekday off one function. Both edges are tested to
# the minute, because a window an hour out fails silently at one end of the
# world and nothing reports it.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "when, expected",
    [
        (pacific(2026, 9, 30, 7, 59), False),  # one minute early
        (pacific(2026, 9, 30, 8, 0), True),  # midnight in Japan
        (pacific(2026, 10, 1, 0, 0), True),  # midnight Pacific
        (pacific(2026, 10, 2, 2, 59), True),  # last minute in Hawaii
        (pacific(2026, 10, 2, 3, 0), False),  # one minute late
    ],
)
def test_the_window_edges_to_the_minute(when, expected):
    assert triggers.in_window(when, date(2026, 10, 1)) is expected


def test_the_window_is_exactly_forty_three_hours():
    opens, closes = triggers.window_bounds(date(2026, 10, 1))
    assert closes - opens == timedelta(hours=43)


def test_a_player_in_japan_earns_it_on_their_own_first_of_october():
    """Midnight on 1 October in Japan is 30 September 08:00 Pacific."""
    japan = datetime(2026, 10, 1, 0, 30, tzinfo=timezone(timedelta(hours=9)))
    assert triggers.in_window(
        japan.astimezone(timezone.utc).replace(tzinfo=None), date(2026, 10, 1)
    )


def test_a_player_in_hawaii_earns_it_on_theirs():
    """The last minute of 1 October in Hawaii is 2 October 03:00 Pacific."""
    hawaii = datetime(2026, 10, 1, 23, 30, tzinfo=timezone(timedelta(hours=-10)))
    assert triggers.in_window(
        hawaii.astimezone(timezone.utc).replace(tzinfo=None), date(2026, 10, 1)
    )


def test_consecutive_windows_overlap_by_nineteen_hours():
    """Harmless only because they watch different things - and one more
    reason the dispatcher must not stop at the first match."""
    first = triggers.window_bounds(date(2026, 10, 1))
    second = triggers.window_bounds(date(2026, 10, 2))
    assert second[0] < first[1]
    assert first[1] - second[0] == timedelta(hours=19)


def test_no_october_window_crosses_a_daylight_saving_boundary():
    """US DST ends on 1 November 2026, so every Release 1 window is PDT."""
    for day in (1, 2, 15, 21, 25):
        opens, closes = triggers.window_bounds(date(2026, 10, day))
        assert closes - opens == timedelta(hours=43), day


async def test_a_date_achievement_fires_inside_its_window(playing):
    assert "brewing_trouble" in await earned(
        a_context("on_use", thing_id="coffee_maker", now=pacific(2026, 10, 1))
    )


async def test_a_date_achievement_does_not_fire_outside_it(playing):
    assert await earned(
        a_context("on_use", thing_id="coffee_maker", now=pacific(2026, 9, 20))
    ) == set()


async def test_the_right_day_but_the_wrong_thing_earns_nothing(playing):
    assert "brewing_trouble" not in await earned(
        a_context("on_use", thing_id="sink", now=pacific(2026, 10, 1))
    )


async def test_a_date_achievement_is_not_pinned_to_2026(playing):
    """Pinning the year would quietly retire seven achievements on 1 January."""
    assert "brewing_trouble" in await earned(
        a_context("on_use", thing_id="coffee_maker", now=pacific(2027, 10, 1))
    )


@pytest.mark.parametrize("mirror", sorted(triggers.MIRRORS))
async def test_say_cheese_takes_any_of_the_three_mirrors(playing, mirror):
    assert "say_cheese" in await earned(
        a_context("on_use", thing_id=mirror, now=pacific(2026, 10, 2))
    )


async def test_curbside_pickup_is_the_trash_can_on_a_tuesday(playing):
    tuesday = date(2026, 10, 6)
    assert tuesday.weekday() == 1
    assert "curbside_pickup" in await earned(
        a_context("on_use", thing_id="trash_can", now=pacific(2026, 10, 6))
    )


async def test_curbside_pickup_is_not_the_trash_can_on_a_thursday(playing):
    thursday = date(2026, 10, 8)
    assert thursday.weekday() == 3
    assert await earned(
        a_context("on_use", thing_id="trash_can", now=pacific(2026, 10, 8, 12))
    ) == set()


async def test_the_tuesday_window_widens_the_same_way(playing):
    """Monday 08:00 through Wednesday 03:00, or a player in Japan could only
    earn it between 17:00 Tuesday and 17:00 Wednesday their time."""
    assert "curbside_pickup" in await earned(
        a_context("on_use", thing_id="trash_can", now=pacific(2026, 10, 5, 8, 0))
    )


async def test_the_tuesday_windows_near_october_first_do_not_collide(playing):
    """*Trash Panda* and *Curbside Pickup* both watch the trash can. The
    nearest Tuesday windows close on 30 September at 03:00 and reopen on 5
    October at 08:00, both clear of the 1 October window."""
    both = await earned(
        a_context("on_use", thing_id="trash_can", now=pacific(2026, 10, 1, 12))
    )
    assert both == {"trash_panda"}


async def test_trash_panda_and_curbside_pickup_are_both_evaluated(playing):
    """Not chained with an elif. They cannot collide in 2026, but the
    dispatcher must not assume that."""
    assert set(achievements.listening_on("on_use")) >= {"trash_panda", "curbside_pickup"}


# --------------------------------------------------------------------------
# Green Thumb: three things, two hooks, one registration
# --------------------------------------------------------------------------

OCT_15 = pacific(2026, 10, 15)


async def test_green_thumb_from_the_watering_can(playing):
    assert "green_thumb" in await earned(
        a_context("on_use", thing_id="watering_can", now=OCT_15)
    )


async def test_green_thumb_from_carving_the_pumpkin(playing):
    assert "green_thumb" in await earned(
        a_context("on_use", thing_id="pumpkins", now=OCT_15)
    )


async def test_green_thumb_from_taking_herbs_from_the_garden(playing):
    assert "green_thumb" in await earned(
        a_context("on_take", thing_id="herbs", source_id="herb_garden", now=OCT_15)
    )


async def test_green_thumb_is_not_earned_by_scavenging(playing):
    """Picking up herbs somebody dropped in the Entryway is not gardening,
    and both paths hand over an identical `herbs`."""
    assert "green_thumb" not in await earned(
        a_context("on_take", thing_id="herbs", source_id=None, now=OCT_15)
    )


async def test_carving_a_pumpkin_on_the_fifteenth_earns_both(playing):
    """The dispatcher must not stop at the first match."""
    await database.take_from_source(ALICE, GUILD_A, "carving_tools")

    both = await earned(a_context("on_use", thing_id="pumpkins", now=OCT_15))
    assert both == {"gourd_job", "green_thumb"}


# --------------------------------------------------------------------------
# The three group achievements
# --------------------------------------------------------------------------


async def pile_into(room, thing_id, count, guild_id=GUILD_A):
    """Set how many of something a room holds.

    Sets rather than adds, so a test can top a pile up or empty it.

    Written straight into `room_contents`, which is what the three group
    predicates read. Two hundred round trips per room through `/drop` would
    add a minute to the suite and test the drop handler, which has its own
    file."""
    insert = database._upsert_statement()
    async with database._require_session()() as session:
        await session.execute(
            insert(database.RoomContents)
            .values(
                guild_id=guild_id,
                room_id=room,
                container_id=database.LOOSE_IN_ROOM,
                thing_id=thing_id,
                count=count,
            )
            .on_conflict_do_update(
                index_elements=[
                    database.RoomContents.guild_id,
                    database.RoomContents.room_id,
                    database.RoomContents.container_id,
                    database.RoomContents.thing_id,
                ],
                set_={"count": count},
            )
        )
        await session.commit()


async def test_strength_in_numbers_needs_twenty_five_of_one_thing(playing):
    await pile_into("EN", "cat_food_tuna", 24)
    assert "strength_in_numbers" not in await earned(a_context("on_drop"))

    await pile_into("EN", "cat_food_tuna", 25)
    assert "strength_in_numbers" in await earned(a_context("on_drop"))


async def test_strength_in_numbers_counts_one_thing_not_the_total(playing):
    """Twenty-four tuna and twenty-four chicken is forty-eight things and no
    achievement."""
    await pile_into("EN", "cat_food_tuna", 24)
    await pile_into("EN", "cat_food_chicken", 24)

    assert "strength_in_numbers" not in await earned(a_context("on_drop"))


async def test_a_group_achievement_lands_on_the_server_not_the_player(playing):
    await pile_into("EN", "cat_food_tuna", 25)
    await achievements.fire(a_context("on_drop"))

    assert set(await database.server_achievements_of(GUILD_A)) == {"strength_in_numbers"}
    assert await has() == set()


async def test_the_feline_collection_needs_both_numbers_in_one_room(playing):
    """120 cans spread over two rooms that each hold 200 things earns
    nothing, which is why the two numbers come from the same group."""
    # 120 cans in total, 200 things in each room, and neither room reaches
    # 100 cans on its own.
    await pile_into("EN", "cat_food_tuna", 60)
    await pile_into("EN", "candy", 140)
    await pile_into("KI", "cat_food_chicken", 60)
    await pile_into("KI", "candy", 140)

    got = await earned(a_context("on_drop"))
    assert "making_a_mess" in got
    assert "the_feline_collection" not in got


async def test_the_feline_collection_when_they_are_in_one_room(playing):
    await pile_into("EN", "cat_food_tuna", 100)
    await pile_into("EN", "candy", 100)

    assert "the_feline_collection" in await earned(a_context("on_drop"))


async def test_a_group_achievement_survives_the_room_being_emptied(playing):
    """It counts `room_contents`, not history - but once earned it is kept."""
    await pile_into("EN", "cat_food_tuna", 25)
    await achievements.fire(a_context("on_drop"))

    await pile_into("EN", "cat_food_tuna", 0)

    assert set(await database.server_achievements_of(GUILD_A)) == {"strength_in_numbers"}


async def test_a_server_that_reaches_the_threshold_twice_earns_once(playing):
    await pile_into("EN", "cat_food_tuna", 25)

    assert len(await achievements.fire(a_context("on_drop"))) == 1
    assert await achievements.fire(a_context("on_drop")) == []


async def test_group_achievements_are_scoped_to_one_server(playing, db):
    await db.ensure_user_exists(ALICE, GUILD_B)
    await pile_into("EN", "cat_food_tuna", 25)
    await achievements.fire(a_context("on_drop"))

    assert await database.server_achievements_of(GUILD_B) == {}


# --------------------------------------------------------------------------
# The blocked seven
# --------------------------------------------------------------------------

BLOCKED = [
    # Waiting on cat crossing, the ghosts, the doorbell and the letter.
    "unsticking_the_situation",
    "return_to_sender",
    "it_takes_a_village",
    "getting_into_the_spirit",
    "ghostbuster",
    "signed_sealed_delivered",
    "forwarding_address",
    # *Bowl Half Empty* left this list in drop 10, when feeding arrived
    # and gave it something to count - the same way the two toy ones
    # left it in drop 2.
]


@pytest.mark.parametrize("achievement_id", BLOCKED)
def test_a_blocked_achievement_is_still_registered(achievement_id):
    """Cheaper than maintaining a shipping subset, and it keeps the
    both-directions check meaningful."""
    assert achievements.trigger_for(achievement_id) is not None


@pytest.mark.parametrize("achievement_id", BLOCKED)
def test_a_blocked_achievement_says_what_it_waits_on(achievement_id):
    trigger = achievements.trigger_for(achievement_id)
    assert getattr(trigger.predicate, "blocked_on", None)


# --------------------------------------------------------------------------
# The one nobody can play for
# --------------------------------------------------------------------------


# Registered, and permanently unearnable. Kept apart from `BLOCKED`
# because the two mean opposite things: those are waiting on a system,
# this one is closed for good.
BY_HAND = ["bug_catcher"]


def test_the_hand_awarded_one_is_still_registered():
    """Same reason the blocked ones are: the both-directions check only
    means something if every row in the file has a trigger."""
    assert achievements.trigger_for("bug_catcher") is not None


def test_it_says_it_is_awarded_by_hand():
    """And says it differently from the blocked ones, which are waiting
    on a system rather than closed for good."""
    trigger = achievements.trigger_for("bug_catcher")
    assert getattr(trigger.predicate, "by_hand", None)
    assert getattr(trigger.predicate, "blocked_on", None) is None


async def test_no_command_can_earn_it(playing):
    """`on_command` fires after every slash command there is, which is
    the widest net in the game - and it still catches nothing."""
    got = await earned(a_context("on_command"))

    assert "bug_catcher" not in got


async def test_the_three_crossing_ones_listen_on_a_hook_with_no_call_site(playing):
    for key in ("unsticking_the_situation", "return_to_sender", "it_takes_a_village"):
        assert key in achievements.listening_on("on_cross")


async def test_nothing_blocked_can_be_earned_by_any_use(playing):
    got = await earned(a_context("on_use", thing_id="intercom"))
    assert not (got & set(BLOCKED))


def test_what_can_actually_be_earned():
    """Twenty-eight of Release 1's thirty-five, plus the eleven V3 adds
    that have content behind them: making first contact, the two score
    thresholds below 250, fluffing the bed, Tireless, drop 2's two toy
    achievements, the two October holidays, and drop 10's feeding pair -
    *Room Service* on the first can and *Bowl Half Empty* on the
    twenty-fifth.

    **Registration, not arrival.** A row parked at `NEVER` is still
    wired - *Met the Craving* is, and its predicate works - so this
    counts what the engine can answer for, and the drop decides
    separately whether anybody will ever be asked.

    Forty, still: *Bug Catcher* is registered like the rest and is not
    one of them, because no play produces it.
    """
    earnable = achievements.registered_ids() - set(BLOCKED) - set(BY_HAND)

    assert len(earnable) == 40


# --------------------------------------------------------------------------
# The rest, one test each
# --------------------------------------------------------------------------


async def test_found_the_specs(playing):
    assert "found_the_specs" in await earned(
        a_context("on_use", thing_id="reading_glasses")
    )


async def test_baby_talk(playing):
    assert "baby_talk" in await earned(a_context("on_use", thing_id="baby_monitor"))


async def test_dressed_for_the_season(playing):
    assert "dressed_for_the_season" in await earned(
        a_context("on_use", thing_id="costume")
    )


async def test_breaking_into_the_halloween_candy(playing):
    assert "breaking_into_the_halloween_candy" in await earned(
        a_context("on_use", thing_id="candy")
    )


async def test_gourd_job_needs_the_carving_tools(playing):
    assert "gourd_job" not in await earned(a_context("on_use", thing_id="pumpkins"))

    await database.take_from_source(ALICE, GUILD_A, "carving_tools")
    assert "gourd_job" in await earned(a_context("on_use", thing_id="pumpkins"))


async def test_follow_your_nose_reads_the_state(playing):
    assert "follow_your_nose" not in await earned(a_context("on_use", thing_id="sink"))

    await states.set_player_state(GUILD_A, ALICE, "drawer_unjammed")
    assert "follow_your_nose" in await earned(a_context("on_use", thing_id="sink"))


async def test_out_on_a_limb_is_the_tree(playing):
    assert "out_on_a_limb" in await earned(a_context("on_move", thing_id="CS", room_id="SE"))


async def test_out_on_a_limb_is_not_any_other_exit(playing):
    assert "out_on_a_limb" not in await earned(
        a_context("on_move", thing_id="EK", room_id="KI")
    )


async def test_not_so_picky_eater_needs_ten(playing):
    for n in range(1, 11):
        await database.record_use(ALICE, GUILD_A, "frozen_burrito")
        got = await earned(a_context("on_use", thing_id="frozen_burrito"))
        if n < 10:
            assert "not_so_picky_eater" not in got, n
    assert "not_so_picky_eater" in await has()


async def test_not_so_picky_eater_counts_only_burritos(playing):
    for _ in range(10):
        await database.record_use(ALICE, GUILD_A, "candy")

    assert "not_so_picky_eater" not in await earned(
        a_context("on_use", thing_id="frozen_burrito")
    )


async def test_charcuterie_board_needs_all_five(playing):
    for flavour in sorted(triggers.CAT_FOOD)[:4]:
        await database.take_from_source(ALICE, GUILD_A, flavour)
    assert "charcuterie_board" not in await earned(a_context("on_take"))

    await database.take_from_source(ALICE, GUILD_A, sorted(triggers.CAT_FOOD)[4])
    assert "charcuterie_board" in await earned(a_context("on_take"))


async def test_charcuterie_board_reads_the_inventory_directly(playing):
    """Fragile in a known way: drop one and the set breaks. Accepted, because
    every flavour comes from a source that cannot run out."""
    for flavour in triggers.CAT_FOOD:
        await database.take_from_source(ALICE, GUILD_A, flavour)
    await database.drop_into_room(ALICE, GUILD_A, "EN", "cat_food_tuna")

    assert "charcuterie_board" not in await earned(a_context("on_take"))


async def test_catproof_the_house_counts_clean_and_dirty_together(playing):
    """So a player who sanitizes what they collect does not lose progress."""
    for _ in range(3):
        await database.take_from_source(ALICE, GUILD_A, "used_baby_bottle")
    for _ in range(2):
        await database.take_from_source(ALICE, GUILD_A, "sanitized_baby_bottle")

    assert "catproof_the_house" in await earned(a_context("on_take"))


async def test_catproof_the_house_needs_five(playing):
    for _ in range(4):
        await database.take_from_source(ALICE, GUILD_A, "used_baby_bottle")

    assert "catproof_the_house" not in await earned(a_context("on_take"))


async def test_bulk_buyer_sums_across_flavours(playing):
    for _ in range(5):
        for flavour in triggers.CAT_FOOD:
            await database.take_from_source(ALICE, GUILD_A, flavour)

    assert "bulk_buyer" in await earned(a_context("on_take"))


async def test_bulk_buyer_needs_twenty_five(playing):
    for _ in range(4):
        for flavour in triggers.CAT_FOOD:
            await database.take_from_source(ALICE, GUILD_A, flavour)

    assert "bulk_buyer" not in await earned(a_context("on_take"))


async def petted(times, user_id=ALICE):
    """Put this player's lifetime pet count at `times`.

    Written directly rather than by calling `/pet` two hundred times. The
    count is all the fork reads now - which pets were friendly no longer
    matters, only how many there were and where the meter ended up.
    """
    async with database._require_session()() as session:
        await session.execute(
            database.update(database.User)
            .where(database.User.id == user_id, database.User.guild_id == GUILD_A)
            .values(pet_count=times)
        )
        await session.commit()


def after(score):
    """An `on_pet` context carrying the score as it stands after the pet."""
    return a_context("on_pet", extra={"relationship": score})


async def test_two_hundred_pets_and_a_cat_that_likes_you(playing):
    await petted(199)
    assert "making_friends" not in await earned(after(50))

    await petted(200)
    assert "making_friends" in await earned(after(50))


async def test_two_hundred_pets_and_a_cat_that_does_not(playing):
    await petted(200)

    got = await earned(after(-50))

    assert "trying_to_make_friends" in got
    assert "making_friends" not in got


async def test_zero_counts_as_does_not(playing):
    """The boundary the Story Bible was revised to state - "zero or
    below", not "negative". It matters more now than it did: every player
    starts there."""
    await petted(200)

    got = await earned(after(0))

    assert "trying_to_make_friends" in got
    assert "making_friends" not in got


async def test_a_mixed_two_hundred_now_earns_one_of_them(playing):
    """**The bug this change exists for.** This test used to assert the
    opposite - a hundred pets on each side of zero earned neither,
    because each half was tallied separately and neither tally reached
    two hundred. A player could pet the cat two hundred times and get
    nothing. One counter, and the sign at the end decides."""
    await petted(200)

    got = await earned(after(-10))

    assert "trying_to_make_friends" in got


async def test_the_two_are_mutually_exclusive(playing):
    """Both conditions are true the moment the count is reached, and only
    the sign separates them - so each refuses while the other is held."""
    await petted(200)
    first = await earned(after(50))
    assert "making_friends" in first

    second = await earned(after(-50))

    assert "trying_to_make_friends" not in second


async def test_passing_two_hundred_unnoticed_is_not_lost(playing):
    """"At least two hundred", not "exactly the two hundredth". A check
    that only fired on the 200th pet would be lost for good if the bot
    were down for it, or if two pets raced."""
    await petted(250)

    assert "making_friends" in await earned(after(50))


async def test_cats_best_friend_at_a_perfect_relationship(playing):
    assert "cats_best_friend" in await earned(
        a_context("on_relationship_change", extra={"relationship": database.PERFECT_RELATIONSHIP})
    )


async def test_cats_best_friend_not_below_it(playing):
    assert "cats_best_friend" not in await earned(
        a_context("on_relationship_change", extra={"relationship": 99})
    )


async def test_cats_best_friend_announces_once(playing):
    """True forever once true, which is the standing condition the idempotent
    award exists for."""
    top = {"relationship": database.PERFECT_RELATIONSHIP}

    first = await earned(a_context("on_relationship_change", extra=top))

    # A hundred passes fifty on the way, so both land in one move.
    assert {"cats_best_friend", "a_paw_in_the_door"} <= first
    for _ in range(5):
        assert await earned(a_context("on_relationship_change", extra=top)) == set()


async def test_a_threshold_passed_without_petting_still_fires(playing):
    """The reason these moved off `on_pet`. A player pushed past fifty by
    a bed fluff would otherwise go unchecked until their next pet."""
    assert "a_paw_in_the_door" in await earned(
        a_context("on_relationship_change", extra={"relationship": 50})
    )


async def test_favorite_human_needs_a_meter_with_no_ceiling(playing):
    assert "favorite_human" not in await earned(
        a_context("on_relationship_change", extra={"relationship": 249})
    )
    assert "favorite_human" in await earned(
        a_context("on_relationship_change", extra={"relationship": 250})
    )


async def test_passing_a_message_to_david(playing):
    said = "Alexa, remind David about the cat food delivery"
    assert "passing_a_message_to_david" in await earned(
        a_context("on_message", extra={"content": said})
    )


async def test_talking_to_alexa_about_anything_else_earns_nothing(playing):
    assert await earned(
        a_context("on_message", extra={"content": "Alexa, what's the weather"})
    ) == set()


async def test_met_the_craving(playing):
    """**Awarded now, where it used to be parked.**

    The game was wired end to end from drop 2 - `on_raw_reaction_add`
    judged a guess and fired `on_reaction` - but the achievement sat at
    drop 99, so the row never arrived and the predicate answered into
    nothing. The 26 October renumbering gave the craving a drop of its
    own and the award came with it.
    """
    guess = craving.Guess(outcome=craving.WIN, craving="\N{COOKIE}")
    context = a_context("on_reaction", extra={"guess": guess})

    assert await triggers.met_the_craving(context)
    assert await earned(context) == {"met_the_craving"}


async def test_a_win_that_paid_nothing_still_earns_it(playing):
    """A player who already took their five points today and clicks the
    answer again has still met the craving. The award is a one-off and
    cannot fire twice anyway, so gating it on the payment would only
    lose the player who found it the hard way after copying it once."""
    guess = craving.Guess(outcome=craving.WIN, craving="\N{COOKIE}", credited=False)

    assert await earned(a_context("on_reaction", extra={"guess": guess})) == {
        "met_the_craving"
    }


@pytest.mark.parametrize(
    "outcome",
    [craving.GREETING, craving.WRONG_CATEGORY, craving.RIGHT_CATEGORY,
     craving.RIGHT_TYPE],
)
async def test_no_rung_below_the_top_earns_anything(playing, outcome):
    guess = craving.Guess(outcome=outcome, craving="\N{COOKIE}")
    assert await earned(a_context("on_reaction", extra={"guess": guess})) == set()


# --------------------------------------------------------------------------
# A Little Bit Lost
# --------------------------------------------------------------------------


async def wander(rooms, start=None, gap=timedelta(seconds=30)):
    """Walk a route, one arrival per room, and return what the last one
    earned."""
    now = start or datetime(2026, 10, 8, 12, 0)
    got = set()
    for step, room in enumerate(rooms):
        got = await earned(
            a_context("on_move", room_id=room, now=now + gap * step)
        )
    return got


async def test_five_arrivals_in_one_room_inside_five_minutes(playing):
    """Not round trips and not total moves: Kitchen five times by any route."""
    route = ["KI", "CO", "KI", "EN", "KI", "LR", "KI", "CO", "KI"]
    assert "a_little_bit_lost" in await wander(route)


async def test_four_arrivals_is_not_enough(playing):
    route = ["KI", "CO", "KI", "EN", "KI", "LR", "KI"]
    assert "a_little_bit_lost" not in await wander(route)


async def test_five_arrivals_spread_over_more_than_five_minutes(playing):
    route = ["KI", "CO", "KI", "EN", "KI", "LR", "KI", "CO", "KI"]
    assert "a_little_bit_lost" not in await wander(route, gap=timedelta(minutes=1))


async def test_nine_moves_through_five_rooms_earns_nothing(playing):
    """Plenty of moving, no single room reached five times."""
    route = ["KI", "CO", "EN", "LR", "KI", "CO", "EN", "LR", "KI"]
    assert "a_little_bit_lost" not in await wander(route)


async def test_the_buffer_is_per_player(playing):
    route = ["KI", "CO", "KI", "EN", "KI", "LR", "KI", "CO"]
    await wander(route)

    now = datetime(2026, 10, 8, 12, 0)
    assert await earned(
        Context(guild_id=GUILD_A, hook="on_move", user_id=BOB, room_id="KI", now=now)
    ) == set()


# --------------------------------------------------------------------------
# Through the real commands, end to end
# --------------------------------------------------------------------------


async def test_using_the_reading_glasses_announces_it(playing, halloween):
    await database.update_current_room(ALICE, GUILD_A, "UH")
    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)

    await bot.use.callback(interaction, "reading glasses")

    assert halloween.text_channels[0].posted == [
        f"Player {ALICE} earned **Found the Specs**"
    ]
    # The description is the private half, and never the public one.
    assert "Found David's reading glasses" in interaction.reply
    assert "Found David's reading glasses" not in halloween.text_channels[0].posted[0]


async def test_cooking_on_the_stove_announces_it(playing, halloween):
    await database.update_current_room(ALICE, GUILD_A, "KI")
    for thing in ("herbs", "dark_chocolate", "spice_jar"):
        await database.take_from_source(ALICE, GUILD_A, thing)
    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)

    await bot.use.callback(interaction, "stove")

    assert halloween.text_channels[0].posted == [
        f"Player {ALICE} earned **Something's Cooking**"
    ]


async def test_an_empty_handed_stove_earns_nothing(playing, halloween):
    """The `requires` gate refuses before the hook, so the predicate can be
    "a successful on_use of the stove" and nothing more."""
    await database.update_current_room(ALICE, GUILD_A, "KI")
    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)

    await bot.use.callback(interaction, "stove")

    assert halloween.text_channels[0].posted == []
    assert await has() == set()


async def test_taking_the_fifth_flavour_announces_it(playing, halloween):
    await database.update_current_room(ALICE, GUILD_A, "KI")
    for flavour in ("cat_food_chicken", "cat_food_salmon", "cat_food_expired", "cat_food_gourmet"):
        await database.take_from_source(ALICE, GUILD_A, flavour)
    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)

    await bot.take.callback(interaction, "tuna")

    assert any(
        "earned **Charcuterie Board**" in line
        for line in halloween.text_channels[0].posted
    )


async def test_the_unlock_text_arrives_privately(playing, halloween):
    await database.update_current_room(ALICE, GUILD_A, "UH")
    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)

    await bot.use.callback(interaction, "reading glasses")

    private = [text for text, kwargs in interaction.sent if kwargs.get("ephemeral")]
    assert any("reading glasses in the desk" in (text or "") for text in private)


async def test_nacho_average_ghost(playing):
    assert "nacho_average_ghost" in await earned(
        a_context("on_use", thing_id="nacho_chips", now=pacific(2026, 10, 21))
    )


async def test_nacho_average_ghost_is_not_earnable_the_week_before(playing):
    assert await earned(
        a_context("on_use", thing_id="nacho_chips", now=pacific(2026, 10, 14))
    ) == set()


async def test_using_your_noodle(playing):
    assert "using_your_noodle" in await earned(
        a_context("on_use", thing_id="pasta_pot", now=pacific(2026, 10, 25))
    )


async def test_using_your_noodle_is_not_earnable_the_day_after_its_window(playing):
    assert await earned(
        a_context("on_use", thing_id="pasta_pot", now=pacific(2026, 10, 26, 12))
    ) == set()


async def test_catproof_cannot_be_farmed_by_dropping_and_re_taking(playing):
    """The award is idempotent, so a player who empties their bag and fills
    it again does not earn it twice."""
    for _ in range(5):
        await database.take_from_source(ALICE, GUILD_A, "used_baby_bottle")
    assert "catproof_the_house" in await earned(a_context("on_take"))

    for _ in range(5):
        await database.drop_into_room(ALICE, GUILD_A, "EN", "used_baby_bottle")
    for _ in range(5):
        await database.take_from_source(ALICE, GUILD_A, "used_baby_bottle")

    assert await earned(a_context("on_take")) == set()


async def test_charcuterie_cannot_be_farmed_either(playing):
    for flavour in triggers.CAT_FOOD:
        await database.take_from_source(ALICE, GUILD_A, flavour)
    assert "charcuterie_board" in await earned(a_context("on_take"))

    await database.drop_into_room(ALICE, GUILD_A, "EN", "cat_food_tuna")
    await database.take_from_source(ALICE, GUILD_A, "cat_food_tuna")

    assert await earned(a_context("on_take")) == set()


# --------------------------------------------------------------------------
# The boot guard
# --------------------------------------------------------------------------


async def test_an_unwired_row_is_reported_at_error_level(playing, caplog):
    """A row nobody registered can never be announced, and nothing raises at
    runtime to say so - so it is logged where Railway will show it."""
    achievements.clear()

    await bot._check_achievement_registry()

    assert "no registered trigger" in caplog.text
    assert "registration problem" in caplog.text


async def test_an_unwired_row_does_not_stop_the_bot(playing):
    """Writers edit the TSVs through GitHub's web editor, which cannot insert
    a tab. A mangled file or an unwired thirty-sixth row must not crash-loop
    the deploy and take the whole game down - the rest of the startup path
    degrades rather than dying, and this has to match it."""
    achievements.clear()

    await bot._check_achievement_registry()  # returns rather than raising


async def test_content_files_that_do_not_parse_do_not_stop_the_bot(playing, caplog, tmp_path):
    """The same rule one layer up: if the files are unreadable there is
    nothing to compare the registry against, and the database still holds the
    last good content."""
    broken = tmp_path / "creative content"
    broken.mkdir()
    (broken / "rooms.tsv").write_text("not a content file", encoding="utf-8")

    original = content_module.CONTENT_DIR
    try:
        content_module.CONTENT_DIR = broken
        await bot._check_achievement_registry()
    finally:
        content_module.CONTENT_DIR = original

    assert "did not parse" in caplog.text


async def test_the_boot_guard_is_quiet_when_everything_is_wired(playing, caplog):
    await bot._check_achievement_registry()

    assert "registration problem" not in caplog.text

# --------------------------------------------------------------------------
# The two October holidays
#
# Both are drop 0 and both are windows with no thing behind them, which
# makes the window itself most of what there is to get wrong. The
# writers specified the bounds in UTC and the engine derives them from
# Pacific, so the first test here is that those two agree.
# --------------------------------------------------------------------------


def test_the_windows_are_the_ones_the_writers_asked_for():
    """Asserted against the file's own notes column, in UTC.

    **The Halloween window crosses the end of daylight saving**, which
    is the first one in the game that does - 30 October is PDT and 1
    November is PST, so a fixed seven-hour offset would put the close
    an hour early and shut out whoever is last.
    """
    black_cat = triggers.window_bounds(date(2026, 10, triggers.BLACK_CAT_DAY))
    halloween = triggers.window_bounds(date(2026, 10, triggers.HALLOWEEN))

    assert black_cat == (datetime(2026, 10, 26, 15), datetime(2026, 10, 28, 10))
    assert halloween == (datetime(2026, 10, 30, 15), datetime(2026, 11, 1, 11))


async def test_petting_her_on_black_cat_day(playing):
    assert "lucky_black_cat" in await earned(
        a_context("on_pet", now=pacific(2026, 10, 27))
    )


async def test_a_standoffish_pet_still_counts(playing):
    """**Any pet, friendly or not.** The achievement is for spending
    the day with her, not for her enjoying it - the same reading the
    nightly drift takes, which also stamps on the attempt."""
    assert "lucky_black_cat" in await earned(
        a_context("on_pet", now=pacific(2026, 10, 27), extra={"friendly": False})
    )


@pytest.mark.parametrize("thing_id", ["cat_bed", "cat_food_salmon"])
async def test_the_other_ways_to_reach_her_count(playing, thing_id):
    assert "lucky_black_cat" in await earned(
        a_context("on_use", thing_id=thing_id, now=pacific(2026, 10, 27))
    )


TOYS = [t.thing_id for t in content_module.load_files().things if t.type == "toy"]


@pytest.mark.parametrize("thing_id", TOYS)
async def test_a_toy_counts_by_type(playing, thing_id):
    """Toys are a class everywhere else - the cap, the ramp and three
    achievements all count them by type - so a thirteenth toy must not
    need an edit here.

    One case per toy rather than a loop, because the award is
    idempotent: the second toy in a loop earns nothing, having already
    been earned by the first.
    """
    assert TOYS
    assert "lucky_black_cat" in await earned(
        a_context("on_use", thing_id=thing_id, now=pacific(2026, 10, 27))
    )


async def test_using_something_that_is_not_her_does_not_count(playing):
    assert "lucky_black_cat" not in await earned(
        a_context("on_use", thing_id="coffee_maker", now=pacific(2026, 10, 27))
    )


async def test_the_cat_on_the_wrong_day_earns_nothing(playing):
    assert "lucky_black_cat" not in await earned(
        a_context("on_pet", now=pacific(2026, 10, 20))
    )


async def test_any_command_at_all_on_halloween(playing):
    """No thing and no verb. Somebody who opened `/stats` on the
    thirty-first spent Halloween in a haunted house with a black
    cat."""
    assert "familiar" in await earned(
        a_context("on_command", now=pacific(2026, 10, 31))
    )


async def test_familiar_does_not_fire_on_the_thirtieth_morning(playing):
    """The window opens at 08:00 Pacific on the thirtieth, so the
    morning before it is outside - which is the edge a fixed calendar
    day would get wrong in the other direction."""
    assert await earned(
        a_context("on_command", now=pacific(2026, 10, 30, hour=7))
    ) == set()


async def test_familiar_reaches_the_far_side_of_the_time_change(playing):
    """01 November 10:00 UTC is inside; 11:00 is not. Both are after
    the clocks go back, so this is the assertion that would fail if the
    close were computed by subtracting seven hours."""
    assert "familiar" in await earned(
        a_context("on_command", now=datetime(2026, 11, 1, 10, 30))
    )
    assert await earned(a_context("on_command", now=datetime(2026, 11, 1, 11))) == set()


async def test_neither_is_pinned_to_2026(playing):
    """Year-agnostic, for the same reason the Release 1 seven are: a
    pinned year retires an achievement on 1 January."""
    assert "lucky_black_cat" in await earned(
        a_context("on_pet", now=pacific(2031, 10, 27))
    )
    assert "familiar" in await earned(
        a_context("on_command", now=pacific(2031, 10, 31))
    )

