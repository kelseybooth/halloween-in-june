"""Drop 2: the toys, and the ramp that decides whether the cat plays.

The ramp is the mechanic, and nearly everything here is about it. It
starts at a guaranteed refusal, climbs twenty-five points per refusal,
resets on a success and starts a ten-minute cooldown - and attempts made
inside that cooldown advance nothing, which is what stops a player
banking four refusals and converting the moment it lifts.

**It belongs to the player, not to the toy.** That is the rule most of
these tests are really pinning: carrying a feather wand and a crinkle
ball must not give you two ramps and a way around the cooldown.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
import resolve
import triggers
import world

WAND = "feather_wand"
BALL = "crinkle_ball"
WAND_SUCCESS = "flicks the ribbon"
COOLDOWN_LINE = "pretending the last few minutes"


@pytest.fixture
async def channel(db):
    """A server on drop 2, with both toys in the channel.

    **Placed here rather than by the drop.** The toys used to arrive
    with drop 2 and sit on the floor from the first minute; they are
    `quantity = 0` now, and the restock schedule is what puts them
    there. Everything below is about what a player does with a toy
    they have found, so these tests put one in front of them and the
    scheduler is `test_toy_arrival`'s subject.
    """
    achievements.clear()
    triggers.register_all()
    await content_loader.load_content(content_module.load_files())
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, name="Test Server", channels=[halloween],
        members=[FakeMember(ALICE), FakeMember(BOB)],
    )
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, 2)
    await content_loader.place_arrived(GUILD_A)
    for toy in (WAND, BALL):
        await database.place_in_room(
            GUILD_A, content_module.CHANNEL_ROOM, toy, 1
        )
    await database.ensure_user_exists(ALICE, GUILD_A)
    bot.forget_public_pets()
    yield db, guild, halloween
    achievements.clear()


async def run(channel, command, *args, who=ALICE):
    _, guild, halloween = channel
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=halloween)
    await command.callback(interaction, *args)
    return interaction


def said(interaction) -> str:
    return "\n".join(t for t, _ in interaction.sent if t)


def posted(channel) -> str:
    """Everything the channel has seen, joined.

    A successful play is **public and nothing else** now, so the text a
    player reads for the best moment in the drop lives here rather than
    in `said`. The two used to carry the same sentence.
    """
    _, _, halloween = channel
    return "\n".join(halloween.posted)


async def take(channel, thing="feather wand", who=ALICE):
    return said(await run(channel, bot.take, thing, who=who))


async def play(channel, thing="feather wand", who=ALICE):
    return said(await run(channel, bot.use, thing, who=who))


async def a_success(channel, monkeypatch, thing="feather wand", who=ALICE):
    """Play until one lands, and return what the player read.

    **The first offer cannot succeed**, whatever the dice say: the ramp
    starts at 0%. So a test that wants a success has to earn a rung
    first, which is the mechanic rather than an inconvenience - it is
    exactly what a player does.
    """
    always(monkeypatch, succeed=False)
    await play(channel, thing, who=who)
    always(monkeypatch, succeed=True)
    await play(channel, thing, who=who)
    return posted(channel)


def always(monkeypatch, *, succeed):
    """Pin the roll. 0.0 lands under any chance above zero; 0.999 over
    any chance below a hundred."""
    monkeypatch.setattr(world, "random", _Loaded(0.0 if succeed else 0.999))


class _Loaded:
    def __init__(self, value):
        self._value = value

    def random(self):
        return self._value


# --------------------------------------------------------------------------
# The ramp
# --------------------------------------------------------------------------


def test_the_chance_climbs_by_a_quarter_each_refusal():
    assert [world.play_chance(n) for n in range(5)] == [0, 25, 50, 75, 100]


def test_the_first_offer_cannot_succeed():
    """A new player's first `/use` is designed to fail, which is the
    thing the refusal copy is written to leave open."""
    assert world.play_chance(0) == 0


def test_the_fifth_always_lands():
    """Which is why four refusals running is the rarest thing
    *Impressively Bad Luck* can ask for, and five is impossible."""
    assert world.play_chance(4) == 100


async def test_a_refusal_advances_the_ramp(channel, monkeypatch):
    always(monkeypatch, succeed=False)
    await take(channel)

    await play(channel)

    ramp, until = await database.play_state(GUILD_A, ALICE)
    assert (ramp, until) == (1, None)


async def test_a_success_resets_it_and_starts_the_cooldown(channel, monkeypatch):
    await take(channel)

    await a_success(channel, monkeypatch)

    ramp, until = await database.play_state(GUILD_A, ALICE)
    assert ramp == 0
    assert until is not None


async def test_attempts_inside_the_cooldown_advance_nothing(channel, monkeypatch):
    """Otherwise a player banks four refusals during the ten minutes and
    converts the instant it lifts, and the cooldown is decoration."""
    await take(channel)
    await a_success(channel, monkeypatch)
    always(monkeypatch, succeed=False)

    for _ in range(4):
        reply = await play(channel)

    assert COOLDOWN_LINE in reply
    assert (await database.play_state(GUILD_A, ALICE))[0] == 0


async def test_the_ramp_is_the_players_not_the_toys(channel, monkeypatch):
    """**The rule the whole storage decision turns on.** Two toys must
    not mean two ramps - otherwise swapping toys is a way around the
    cooldown."""
    always(monkeypatch, succeed=False)
    await take(channel)
    await take(channel, "crinkle ball")

    await play(channel, "feather wand")
    await play(channel, "crinkle ball")

    assert (await database.play_state(GUILD_A, ALICE))[0] == 2


async def test_the_cooldown_is_the_players_too(channel, monkeypatch):
    await take(channel)
    await take(channel, "crinkle ball")
    await a_success(channel, monkeypatch, "feather wand")

    assert COOLDOWN_LINE in await play(channel, "crinkle ball")


async def test_one_player_s_ramp_is_not_another_s(channel, monkeypatch):
    always(monkeypatch, succeed=False)
    await take(channel)
    await play(channel)
    await play(channel)

    assert (await database.play_state(GUILD_A, BOB))[0] == 0


# --------------------------------------------------------------------------
# It has to be held
# --------------------------------------------------------------------------


async def test_a_toy_on_the_floor_cannot_be_played_with(channel):
    """Without this `/take` has no purpose in the drop that exists to
    teach it."""
    reply = await play(channel)

    assert "pick it up first" in reply
    assert WAND_SUCCESS not in reply


async def test_and_can_be_once_it_is_picked_up(channel, monkeypatch):
    await take(channel)

    assert WAND_SUCCESS in await a_success(channel, monkeypatch)


async def test_a_fixture_is_never_carry_checked(channel, monkeypatch):
    """**The check is keyed on `takeable`, not on `/use`.** Written as a
    property of the verb it would make every fixture permanently
    unusable - starting with the cat bed, which nobody can pocket."""
    reply = said(await run(channel, bot.use, "cat bed")) + posted(channel)

    assert "pick it up first" not in reply
    # Either half will do: a fluff that dislodges something now says so
    # publicly and says nothing privately at all.
    assert "shake out the cushion" in reply or "something falls out" in reply


# --------------------------------------------------------------------------
# What the player reads
# --------------------------------------------------------------------------


async def test_the_refusals_rotate(channel, monkeypatch):
    """Twelve of them, because at 3.2 attempts per success one string
    would be the most repeated line in the game inside a week."""
    always(monkeypatch, succeed=False)
    await take(channel)
    seen = set()
    for _ in range(40):
        await database.clear_play_state(GUILD_A, ALICE)
        seen.add(await play(channel))

    assert len(seen) > 1


async def test_every_refusal_names_the_toy(channel):
    texts = await resolve.defaults_matching("use_fail.toy.")

    assert len(texts) == 12
    assert len(set(texts)) == 12
    # Most name the toy; two deliberately do not, because a cat
    # declining to get up is not about the object.
    assert sum("{name}" in t for t in texts) >= 10


async def test_the_success_line_is_the_toys_own(channel, monkeypatch):
    """The refusals generalise; the success is the payoff and the whole
    reason a player cares which toy turned up."""
    await take(channel, "crinkle ball")

    assert "rolls a crinkle ball" in await a_success(
        channel, monkeypatch, "crinkle ball"
    )


async def test_the_success_is_public_and_the_refusal_is_not(channel, monkeypatch):
    """And the success is public *only*.

    It used to be both, so the player who had just coaxed the cat into
    playing read the same sentence twice - once in their own reply and
    once in the channel directly below it.
    """
    _, _, halloween = channel
    always(monkeypatch, succeed=False)
    await take(channel)
    refusal = said(await run(channel, bot.use, "feather wand"))

    assert refusal
    assert not any(WAND_SUCCESS in line for line in halloween.posted)

    always(monkeypatch, succeed=True)
    success = await run(channel, bot.use, "feather wand")

    assert any(WAND_SUCCESS in line for line in halloween.posted)
    assert WAND_SUCCESS not in said(success)
    assert success.withdrawn, "the spinner has to be taken back"


async def test_a_success_still_speaks_when_the_channel_is_rate_limited(
    channel, monkeypatch
):
    """**The private line is the fallback, not the default.**

    Deleting it outright would mean a success that says nothing
    anywhere once the public budget is spent - which reads as the cat
    ignoring you, the one thing a success must never look like.
    """
    await take(channel)
    always(monkeypatch, succeed=False)
    await play(channel)
    monkeypatch.setattr(bot, "_public_play_line", lambda *a, **k: None)
    always(monkeypatch, succeed=True)

    interaction = await run(channel, bot.use, "feather wand")

    assert WAND_SUCCESS in said(interaction)
    assert not interaction.withdrawn


# --------------------------------------------------------------------------
# What it pays, and what it tells the rest of the game
# --------------------------------------------------------------------------


async def test_a_success_is_worth_ten(channel, monkeypatch):
    await take(channel)

    await a_success(channel, monkeypatch)

    assert await database.get_relationship(ALICE, GUILD_A) == world.TOY_PLAY


async def test_a_refusal_is_worth_nothing(channel, monkeypatch):
    always(monkeypatch, succeed=False)
    await take(channel)

    await play(channel)

    assert await database.get_relationship(ALICE, GUILD_A) == 0


@pytest.mark.parametrize("succeed", [True, False])
async def test_every_attempt_counts_as_turning_up(channel, monkeypatch, succeed):
    """Attempts, not successes. The first offer is a guaranteed refusal,
    and a player whose only interaction that day was an honest attempt
    should not be hit by the nightly drift."""
    await take(channel)
    always(monkeypatch, succeed=succeed)

    await play(channel)

    assert await database.last_cat_interaction(GUILD_A, ALICE) == database.pacific_today()


async def test_a_cooldown_refusal_counts_too(channel, monkeypatch):
    await take(channel)
    await a_success(channel, monkeypatch)
    await database.touched_the_cat(GUILD_A, ALICE, None)

    await play(channel)

    assert await database.last_cat_interaction(GUILD_A, ALICE) is not None


# --------------------------------------------------------------------------
# The two achievements
# --------------------------------------------------------------------------


async def test_the_first_success_earns_persuasive(channel, monkeypatch):
    await take(channel)

    await a_success(channel, monkeypatch)

    assert "persuasive" in await database.player_achievements_of(GUILD_A, ALICE)


async def test_a_refusal_does_not(channel, monkeypatch):
    always(monkeypatch, succeed=False)
    await take(channel)

    await play(channel)

    assert "persuasive" not in await database.player_achievements_of(GUILD_A, ALICE)


async def test_four_refusals_running_is_impressively_bad_luck(channel, monkeypatch):
    """**The ramp already is the consecutive-refusal count**, so this
    needs no counter of its own."""
    always(monkeypatch, succeed=False)
    await take(channel)

    for _ in range(4):
        await play(channel)

    assert "impressively_bad_luck" in await database.player_achievements_of(GUILD_A, ALICE)


async def test_three_is_not_enough(channel, monkeypatch):
    always(monkeypatch, succeed=False)
    await take(channel)

    for _ in range(3):
        await play(channel)

    assert "impressively_bad_luck" not in await database.player_achievements_of(
        GUILD_A, ALICE
    )


async def test_a_success_in_the_middle_breaks_the_run(channel, monkeypatch):
    always(monkeypatch, succeed=False)
    await take(channel)
    for _ in range(3):
        await play(channel)
    always(monkeypatch, succeed=True)
    await play(channel)  # ramp is 3, so this one lands and resets it
    await database.clear_play_state(GUILD_A, ALICE)
    always(monkeypatch, succeed=False)

    await play(channel)

    assert "impressively_bad_luck" not in await database.player_achievements_of(
        GUILD_A, ALICE
    )


async def test_twenty_five_plays_earns_tireless(channel, monkeypatch):
    """Counted off `thing_uses` rather than a counter of its own - the
    rows say which toys, the sum says how many plays."""
    await take(channel)
    for _ in range(25):
        # A cleared ramp means the next offer is a guaranteed refusal,
        # so every success here is earned the way a player earns one.
        await database.clear_play_state(GUILD_A, ALICE)
        await a_success(channel, monkeypatch)

    assert await database.toy_plays(GUILD_A, ALICE) == 25
    assert "tireless" in await database.player_achievements_of(GUILD_A, ALICE)


# --------------------------------------------------------------------------
# Nothing of this exists before drop 2
# --------------------------------------------------------------------------


async def test_no_toy_is_reachable_at_drop_one(channel):
    await resolve.set_current_drop(GUILD_A, 1)

    assert WAND not in await resolve.visible_thing_ids(GUILD_A)
    assert BALL not in await resolve.visible_thing_ids(GUILD_A)


async def test_the_three_verbs_arrive_with_the_drop(channel):
    import gating

    assert not ({"take", "drop", "inventory"} & gating.commands_for(1))
    assert {"take", "drop", "inventory"} <= gating.commands_for(2)


# --------------------------------------------------------------------------
# The hint ladder
#
# Four rungs chained so each one's completion is the next one's
# precondition - which is what keeps the drop 0 invariant true: a player
# who skips ahead is never told to do a thing they have already done.
# --------------------------------------------------------------------------


async def look(channel, thing=None, who=ALICE):
    return said(await run(channel, bot.look, thing, who=who))


async def test_the_first_look_points_at_a_toy(channel):
    assert "Try /look" in the_hint(await look(channel))


async def test_looking_at_a_toy_points_at_take(channel):
    await look(channel)

    assert "Try /take" in the_hint(await look(channel, "feather wand"))


async def test_taking_one_points_at_use(channel):
    await look(channel)
    await look(channel, "feather wand")

    assert "Try /use" in the_hint(await take(channel))


async def test_the_rung_names_the_toy_just_taken(channel):
    """`{name}` here is the one they are holding, not whichever is
    lying in the channel - naming a different one would be nonsense."""
    await look(channel)
    await look(channel, "crinkle ball")

    assert "crinkle ball" in the_hint(await take(channel, "crinkle ball"))


def the_hint(reply: str) -> str:
    """Just the hint line. The rest of the reply names things too - the
    channel listing names both toys - so an assertion about what a hint
    points at has to read the hint."""
    for line in reply.splitlines():
        if line.startswith("*Hint:"):
            return line
    return ""


async def test_no_rung_names_a_toy_that_is_not_there(channel):
    """Both toys draw against the same two slots, so a hint naming one
    by name could point at a toy nobody can see - and the player's
    first guided action would come back `take_fail.absent`."""
    line = the_hint(await look(channel))
    named = [n for n in ("feather wand", "crinkle ball") if n in line]

    assert len(named) == 1
    assert named[0] in await look(channel)  # still there to be taken


async def test_a_player_who_skips_ahead_is_not_told_to_catch_up(channel):
    """The invariant. Taking a toy without ever looking at one retires
    both the toy-looking rungs.

    Drop 1's bed hint is not retired by this and should not be: it is a
    different lesson about a different object, and the player has not
    looked at the bed."""
    await take(channel)

    line = the_hint(await look(channel))
    assert "feather wand" not in line and "crinkle ball" not in line


async def test_each_rung_fires_once(channel):
    """The toy rung is spent. Drop 1's bed hint takes the next turn,
    which is the rail working rather than repeating itself."""
    first = the_hint(await look(channel))
    assert "feather wand" in first or "crinkle ball" in first

    second = the_hint(await look(channel))

    assert "feather wand" not in second and "crinkle ball" not in second


async def test_being_told_to_pick_it_up_is_its_own_rung(channel):
    reply = await play(channel)  # not holding it

    assert "You need to hold it to use it" in reply


async def test_the_newest_drops_hint_wins_on_a_first_look(channel):
    """A player who never looked at the bed is eligible for drop 1's
    hint and drop 2's on the same `/look`. The newer one points at
    content they have not seen."""
    line = the_hint(await look(channel))

    assert "cat bed" not in line
    assert "Try /look" in line
