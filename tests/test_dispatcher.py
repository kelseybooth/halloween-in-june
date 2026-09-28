"""The dispatcher, the nine hooks, and how an award gets announced.

Still no real achievement conditions - the thirty-five predicates are the next
step. What is here is the machinery they will all run on, tested with
predicates written for the test, which is the only way to drive the awkward
cases: a predicate that raises, two firing from one action, one that is true
forever.

Three rules run through most of this file, and each exists because the
obvious implementation gets it wrong:

- a hook fires **every** predicate registered on it, never stopping at the first
- a predicate that raises must not cost the command that fired it, nor the
  other thirty-four achievements
- an award announces **once**, however many times the condition is true
"""

import pytest
from types import SimpleNamespace

from conftest import ALICE, BOB, GUILD_A, GUILD_B
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
from content import Achievement

from test_achievements import an_achievement
from test_drops import a_calendar, a_drop
from test_loader import a_thing, a_world


@pytest.fixture(autouse=True)
def empty_registry():
    """Every test builds the registry it needs and leaves none behind."""
    achievements.clear()
    yield
    achievements.clear()


async def always(context):
    return True


async def never(context):
    return False


async def explodes(context):
    raise RuntimeError("this predicate is broken")


async def a_world_with(*ids, db=None, kinds=None):
    """Load a tiny world carrying these achievements."""
    kinds = kinds or {}
    parsed = a_world(a_thing("candle"))
    parsed.achievements = [
        an_achievement(key, kind=kinds.get(key, "public")) for key in ids
    ]
    await content_loader.load_content(parsed)
    return parsed


@pytest.fixture
async def guild(db):
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    await db.ensure_user_exists(ALICE, GUILD_B)
    return db


def a_context(hook="on_take", **overrides):
    defaults = dict(guild_id=GUILD_A, hook=hook, user_id=ALICE)
    return achievements.Context(**{**defaults, **overrides})


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


def test_one_achievement_can_listen_on_several_hooks():
    """Green Thumb is the reason. Three ways to notice the date, across two
    hooks, and all of them should count - so this is ordinary rather than a
    special case."""
    achievements.register("green_thumb", ("on_use", "on_take"), always)

    assert achievements.listening_on("on_use") == ["green_thumb"]
    assert achievements.listening_on("on_take") == ["green_thumb"]


def test_a_single_hook_can_be_given_as_a_string():
    achievements.register("gourd_job", "on_use", always)

    assert achievements.listening_on("on_use") == ["gourd_job"]


def test_registering_against_no_hook_is_refused():
    with pytest.raises(ValueError, match="no hook"):
        achievements.register("gourd_job", (), always)


def test_registering_against_an_unknown_hook_is_refused():
    """A typo would otherwise register an achievement that never runs."""
    with pytest.raises(ValueError, match="not a hook"):
        achievements.register("gourd_job", "on_carve", always)


def test_registering_the_same_id_twice_is_refused():
    achievements.register("gourd_job", "on_use", always)

    with pytest.raises(ValueError, match="registered twice"):
        achievements.register("gourd_job", "on_take", always)


def test_every_hook_in_the_spec_exists():
    assert set(achievements.HOOKS) == {
        "on_take",
        "on_drop",
        "on_use",
        "on_move",
        "on_pet",
        "on_reaction",
        "on_message",
        "on_midnight",
        "on_cross",
    }


def test_on_cross_is_a_hook_with_no_call_site():
    """Three achievements wait on the cat carrying things to Dimension B,
    which is post-launch. They register and never fire, which is cheaper than
    maintaining a shipping subset."""
    achievements.register("return_to_sender", "on_cross", always)

    assert achievements.listening_on("on_cross") == ["return_to_sender"]


# --------------------------------------------------------------------------
# The both-directions check
#
# The one the work order singles out as worth building carefully: it catches a
# thirty-sixth achievement nobody wired up, and an id renamed while half the
# awards quietly stop landing.
# --------------------------------------------------------------------------


def test_a_row_with_no_trigger_is_caught():
    problems = achievements.registration_problems({"gourd_job"})

    assert any("no registered trigger" in p for p in problems)


def test_a_trigger_with_no_row_is_caught():
    achievements.register("gourd_job", "on_use", always)

    problems = achievements.registration_problems(set())
    assert any("not in achievements.tsv" in p for p in problems)


def test_a_matched_pair_is_no_problem():
    achievements.register("gourd_job", "on_use", always)

    assert achievements.registration_problems({"gourd_job"}) == []


def test_a_rename_is_caught_from_both_ends_at_once():
    """The failure this exists for: an id changes in the file, the trigger
    keeps the old one, and awards stop landing without anything erroring."""
    achievements.register("gourd_job", "on_use", always)

    problems = achievements.registration_problems({"gourd_work"})
    assert len(problems) == 2


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


async def test_a_hook_with_nothing_registered_does_nothing(guild):
    assert await achievements.fire(a_context()) == []


async def test_a_passing_predicate_earns_it(guild):
    await a_world_with("gourd_job")
    achievements.register("gourd_job", "on_take", always)

    earned = await achievements.fire(a_context())
    assert [e.achievement_id for e in earned] == ["gourd_job"]
    assert set(await database.player_achievements_of(GUILD_A, ALICE)) == {"gourd_job"}


async def test_a_failing_predicate_earns_nothing(guild):
    await a_world_with("gourd_job")
    achievements.register("gourd_job", "on_take", never)

    assert await achievements.fire(a_context()) == []
    assert await database.player_achievements_of(GUILD_A, ALICE) == {}


async def test_only_the_predicates_on_this_hook_run(guild):
    """Nothing re-evaluates thirty-five conditions after every action."""
    ran = []

    async def note(name):
        async def predicate(context):
            ran.append(name)
            return False

        return predicate

    await a_world_with("gourd_job", "say_cheese")
    achievements.register("gourd_job", "on_take", await note("take"))
    achievements.register("say_cheese", "on_pet", await note("pet"))

    await achievements.fire(a_context(hook="on_take"))
    assert ran == ["take"]


async def test_one_action_can_earn_two(guild):
    """Carving a pumpkin on 15 October earns Gourd Job and Green Thumb, and
    that is intended - so the dispatcher must not stop at the first match."""
    await a_world_with("gourd_job", "green_thumb")
    achievements.register("gourd_job", "on_use", always)
    achievements.register("green_thumb", "on_use", always)

    earned = await achievements.fire(a_context(hook="on_use"))
    assert {e.achievement_id for e in earned} == {"gourd_job", "green_thumb"}


async def test_a_raising_predicate_does_not_stop_the_others(guild):
    """A player who loses an achievement to an exception can earn it next
    time. Losing the other thirty-four with it would not be recoverable."""
    await a_world_with("gourd_job", "say_cheese")
    achievements.register("gourd_job", "on_use", explodes)
    achievements.register("say_cheese", "on_use", always)

    earned = await achievements.fire(a_context(hook="on_use"))
    assert [e.achievement_id for e in earned] == ["say_cheese"]


async def test_a_raising_predicate_is_logged(guild, caplog):
    await a_world_with("gourd_job")
    achievements.register("gourd_job", "on_use", explodes)

    await achievements.fire(a_context(hook="on_use"))
    assert "gourd_job raised on on_use" in caplog.text


async def test_awarding_the_same_thing_twice_reports_it_once(guild):
    """Cat's Best Friend is true forever once true. Without this it would
    re-announce on every `/pet` for the rest of October."""
    await a_world_with("cats_best_friend")
    achievements.register("cats_best_friend", "on_pet", always)

    assert len(await achievements.fire(a_context(hook="on_pet"))) == 1
    assert await achievements.fire(a_context(hook="on_pet")) == []


async def test_a_group_achievement_lands_on_the_server(guild):
    await a_world_with("making_a_mess", kinds={"making_a_mess": "group"})
    achievements.register("making_a_mess", "on_drop", always)

    earned = await achievements.fire(a_context(hook="on_drop"))
    assert earned[0].user_id is None
    assert set(await database.server_achievements_of(GUILD_A)) == {"making_a_mess"}
    assert await database.player_achievements_of(GUILD_A, ALICE) == {}


async def test_a_group_achievement_is_earned_once_for_everybody(guild):
    """Bob dropping the two hundred and first thing does not earn it again."""
    await a_world_with("making_a_mess", kinds={"making_a_mess": "group"})
    achievements.register("making_a_mess", "on_drop", always)

    await achievements.fire(a_context(hook="on_drop", user_id=ALICE))
    assert await achievements.fire(a_context(hook="on_drop", user_id=BOB)) == []


async def test_an_achievement_whose_drop_has_not_arrived_cannot_be_earned(guild):
    """It does not exist on this server yet, and awarding it would announce a
    name nobody can read."""
    from datetime import date, timedelta

    tomorrow = date.today() + timedelta(days=30)
    parsed = a_calendar(a_drop(1, value="launch"), a_drop(2, value=str(tomorrow)))
    parsed.achievements = [an_achievement("gourd_job", since_drop=2)]
    await content_loader.load_content(parsed)
    achievements.register("gourd_job", "on_use", always)

    assert await achievements.fire(a_context(hook="on_use")) == []


async def test_the_award_carries_the_name_and_unlock_from_the_file(guild):
    """So a caller can announce what it is handed without a second read."""
    parsed = a_world(a_thing("candle"))
    parsed.achievements = [
        an_achievement("gourd_job", name="Gourd Job", unlock="Carved a pumpkin.")
    ]
    await content_loader.load_content(parsed)
    achievements.register("gourd_job", "on_use", always)

    award = (await achievements.fire(a_context(hook="on_use")))[0]
    assert (award.name, award.unlock) == ("Gourd Job", "Carved a pumpkin.")


async def test_a_player_award_in_one_server_is_not_one_in_another(guild):
    await a_world_with("gourd_job")
    achievements.register("gourd_job", "on_use", always)

    await achievements.fire(a_context(hook="on_use", guild_id=GUILD_A))
    assert len(await achievements.fire(a_context(hook="on_use", guild_id=GUILD_B))) == 1


async def test_a_predicate_reads_the_context_it_was_given(guild):
    seen = []

    async def remember(context):
        seen.append((context.thing_id, context.source_id, context.room_id))
        return False

    await a_world_with("green_thumb")
    achievements.register("green_thumb", "on_take", remember)

    await achievements.fire(
        a_context(thing_id="herbs", source_id="herb_garden", room_id="CO")
    )
    assert seen == [("herbs", "herb_garden", "CO")]


# --------------------------------------------------------------------------
# Announcing
#
# The name in public, the description to the earner and nobody else. A group
# achievement announces its name and tells nobody, because there is no earner.
# --------------------------------------------------------------------------


@pytest.fixture
def halloween():
    """A guild with a #halloween channel and two members in it."""
    channel = FakeChannel(name="halloween")
    alice, bobby = FakeMember(ALICE), FakeMember(BOB)
    return FakeGuild(GUILD_A, channels=[channel], members=[alice, bobby])


def an_award(**overrides):
    defaults = dict(
        achievement_id="gourd_job",
        kind="public",
        name="Gourd Job",
        unlock="Carved a pumpkin in the courtyard.",
        user_id=ALICE,
    )
    return achievements.Earned(**{**defaults, **overrides})


async def test_the_name_goes_up_in_the_halloween_channel(guild, halloween):
    await bot._announce(an_award(), guild=halloween)

    assert halloween.text_channels[0].posted == ["Gourd Job"]


async def test_the_description_never_goes_up_publicly(guild, halloween):
    """The public post is the name only, including for a secret achievement -
    the name appearing is itself the hint that something is there to find."""
    await bot._announce(an_award(kind="secret"), guild=halloween)

    assert "Carved a pumpkin" not in " ".join(halloween.text_channels[0].posted)


async def test_the_description_arrives_ephemerally_from_a_command(guild, halloween):
    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)

    await bot._announce(an_award(), interaction=interaction)

    assert interaction.reply == "Carved a pumpkin in the courtyard."
    assert interaction.was_private


async def test_the_description_arrives_by_dm_without_a_command(guild, halloween):
    """A reaction carries no interaction token, which is already why the
    craving's confirmation is a public reaction with no private fallback."""
    await bot._announce(an_award(), guild=halloween)

    assert halloween.get_member(ALICE).dms == ["Carved a pumpkin in the courtyard."]


async def test_a_closed_dm_is_not_an_error(guild, halloween):
    """People close their DMs. `/stats` holds the description permanently, so
    this is logged and dropped rather than retried or posted publicly."""
    halloween.add_member(FakeMember(ALICE, dms_open=False))

    await bot._announce(an_award(), guild=halloween)

    assert halloween.text_channels[0].posted == ["Gourd Job"]


async def test_a_closed_dm_does_not_fall_back_to_posting_it_publicly(guild, halloween):
    """That would spoil a secret achievement for everyone in the server."""
    halloween.add_member(FakeMember(ALICE, dms_open=False))

    await bot._announce(an_award(kind="secret"), guild=halloween)

    assert halloween.text_channels[0].posted == ["Gourd Job"]


async def test_a_group_achievement_tells_nobody(guild, halloween):
    await bot._announce(an_award(kind="group", user_id=None), guild=halloween)

    assert halloween.text_channels[0].posted == ["Gourd Job"]
    assert halloween.get_member(ALICE).dms == []


async def test_a_failed_announcement_does_not_raise(guild, halloween):
    """The award is already written. `/stats` still shows it."""
    halloween.text_channels[0].send_fails = True

    await bot._announce(an_award(), guild=halloween)

    assert halloween.get_member(ALICE).dms == ["Carved a pumpkin in the courtyard."]


async def test_the_recorded_channel_wins_over_the_name(guild, halloween):
    """Recorded by id at init, so renaming #halloween does not silently stop
    the announcements."""
    other = FakeChannel(name="somewhere-else")
    guild_with_two = FakeGuild(
        GUILD_A, channels=[halloween.text_channels[0], other], members=[FakeMember(ALICE)]
    )
    await database.set_announcement_channel(GUILD_A, other.id)

    await bot._announce(an_award(), guild=guild_with_two)

    assert other.posted == ["Gourd Job"]
    assert guild_with_two.text_channels[0].posted == []


async def test_a_server_with_no_recorded_channel_falls_back_to_the_name(guild, halloween):
    """Servers initialized before the id was recorded keep working."""
    await bot._announce(an_award(), guild=halloween)

    assert halloween.text_channels[0].posted == ["Gourd Job"]


async def test_a_recorded_channel_that_is_gone_falls_back_too(guild, halloween):
    await database.set_announcement_channel(GUILD_A, 999999)

    await bot._announce(an_award(), guild=halloween)

    assert halloween.text_channels[0].posted == ["Gourd Job"]


async def test_no_channel_at_all_still_sends_the_description(guild):
    """An announcement failure must never cost the player the description."""
    empty = FakeGuild(GUILD_A, channels=[], members=[FakeMember(ALICE)])

    await bot._announce(an_award(), guild=empty)

    assert empty.get_member(ALICE).dms == ["Carved a pumpkin in the courtyard."]


# --------------------------------------------------------------------------
# The whole path, from a hook to an announcement
# --------------------------------------------------------------------------


async def test_fire_awards_and_announces_in_one_go(guild, halloween):
    await a_world_with("gourd_job")
    achievements.register("gourd_job", "on_use", always)
    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)

    await bot._fire(a_context(hook="on_use"), interaction=interaction)

    assert halloween.text_channels[0].posted == ["Gourd Job"]
    assert interaction.was_private


async def test_fire_announces_nothing_the_second_time(guild, halloween):
    await a_world_with("cats_best_friend")
    achievements.register("cats_best_friend", "on_pet", always)

    await bot._fire(a_context(hook="on_pet"), guild=halloween)
    await bot._fire(a_context(hook="on_pet"), guild=halloween)

    assert len(halloween.text_channels[0].posted) == 1


async def test_fire_is_quiet_when_the_content_is_not_loaded(guild, halloween):
    """A registered trigger whose row is not in the database earns nothing and
    announces nothing. The both-directions check is what catches that as a
    problem; the dispatcher's job is to not make it a crash."""
    achievements.register("gourd_job", "on_use", always)

    await bot._fire(
        achievements.Context(guild_id=GUILD_A, hook="on_use", user_id=ALICE),
        guild=halloween,
    )
    assert halloween.text_channels[0].posted == []


# --------------------------------------------------------------------------
# The hooks, driven through the real commands
#
# Every hook 2d listens on is a line of code that already ran before this
# phase; these assert the call was actually added, and that it carries what a
# predicate needs.
# --------------------------------------------------------------------------


@pytest.fixture
async def playing(db, halloween):
    """Alice in the Courtyard of the real house, with the real content."""
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.start_game(ALICE, GUILD_A, "CO", ["CO", "KI", "EN"])
    await content_loader.load_content(content_module.load_files())
    await db.set_announcement_channel(GUILD_A, halloween.text_channels[0].id)
    return db


def watching(hook, seen):
    async def predicate(context):
        seen.append(context)
        return False

    return predicate


async def test_take_fires_on_take_with_the_source(playing, halloween):
    """The whole reason `source_id` exists. Taking herbs from the herb garden
    is gardening; picking up herbs off the floor is not, and the thing id is
    identical either way."""
    seen = []
    achievements.register("green_thumb", "on_take", watching("on_take", seen))

    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)
    await bot.take.callback(interaction, "herbs")

    assert [(c.thing_id, c.source_id, c.room_id) for c in seen] == [
        ("herbs", "herb_garden", "CO")
    ]


async def test_taking_a_loose_copy_fires_with_no_source(playing, halloween):
    seen = []
    await database.take_from_source(ALICE, GUILD_A, "herbs")
    await database.drop_into_room(ALICE, GUILD_A, "CO", "herbs")
    achievements.register("green_thumb", "on_take", watching("on_take", seen))

    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)
    await bot.take.callback(interaction, "herbs")

    assert [c.source_id for c in seen] == [None]


async def test_drop_fires_on_drop(playing, halloween):
    seen = []
    await database.take_from_source(ALICE, GUILD_A, "herbs")
    achievements.register("making_a_mess", "on_drop", watching("on_drop", seen))

    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)
    await bot.drop.callback(interaction, "herbs")

    assert [(c.thing_id, c.room_id) for c in seen] == [("herbs", "CO")]


async def test_use_fires_on_use(playing, halloween):
    seen = []
    achievements.register("green_thumb", "on_use", watching("on_use", seen))

    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)
    await bot.use.callback(interaction, "watering can")

    assert [(c.thing_id, c.room_id) for c in seen] == [("watering_can", "CO")]


async def test_a_refused_use_does_not_fire_the_hook(playing, halloween):
    """A refused use is not a use. The stove's `requires` gate returns before
    anything is recorded, so *Something's Cooking* cannot fire on empty
    hands."""
    seen = []
    await database.update_current_room(ALICE, GUILD_A, "KI")
    achievements.register("somethings_cooking", "on_use", watching("on_use", seen))

    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)
    await bot.use.callback(interaction, "stove")

    assert seen == []


async def test_a_met_requires_does_fire_the_hook(playing, halloween):
    seen = []
    await database.update_current_room(ALICE, GUILD_A, "KI")
    for thing in ("herbs", "dark_chocolate", "spice_jar"):
        await database.take_from_source(ALICE, GUILD_A, thing)
    achievements.register("somethings_cooking", "on_use", watching("on_use", seen))

    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)
    await bot.use.callback(interaction, "stove")

    assert [c.thing_id for c in seen] == ["stove"]


async def test_pet_fires_on_pet_with_the_relationship(playing, halloween):
    """*Making Friends* and *Trying to Make Friends* split on it, so it rides
    on the context rather than being re-read."""
    seen = []
    achievements.register("making_friends", "on_pet", watching("on_pet", seen))

    interaction = FakeInteraction(ALICE, GUILD_A, guild=halloween)
    await bot.pet.callback(interaction)

    assert len(seen) == 1
    assert "relationship" in seen[0].extra
    assert "total" in seen[0].extra
