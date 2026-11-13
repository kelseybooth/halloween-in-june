"""The changeover: who yesterday's ghost was, and who got away with it.

Two pieces that read the same day from the same rows. The reveal says
what the channel is told; *Boo Who?* says whether the ghost earned
anything by not being worked out. Both run at the changeover, which is
the only moment either can run at, because what they are about is a day
that has finished.

**Driven through `nightly_job` wherever the behaviour is visible**,
rather than through `ghosts.reveal_for` alone. Three of the things that
can be wrong here are at a seam and not in the decision: the order the
two land in the channel, the mentions the reveal goes out with, and
whether the reveal happens before the pick replaces the row it reads. A
test calling the decision layer would prove the right line was chosen
and nothing about any of those.

**The order in the channel is load-bearing, not cosmetic.** *Boo Who?*
announces the ghost by name - that is what an achievement line does -
so an award that posted before the reveal would spell the name out
before the board does, and the day's ending would arrive backwards.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from conftest import ALICE, BOB, GUILD_A, GUILD_B, LAST_DROP
from fake_discord import FakeChannel, FakeGuild, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
import ghosts
import resolve
import triggers

CAROL = 100000000000000003

NAMES = {
    ALICE: ("Alice", "alice"),
    BOB: ("Bob", "bob_b"),
    CAROL: ("Carol", "carol.c"),
}


@pytest.fixture
async def house(db, monkeypatch):
    """Drop 50, a channel to post in, and three players in the server.

    Three because the pick that follows the reveal wants
    `ghost_min_players` of them: a server of two would skip every pick,
    and a test that then checked the reveal had happened before the
    pick would be checking nothing.
    """
    achievements.clear()
    triggers.register_all()
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A,
        channels=[halloween],
        members=[FakeMember(ALICE), FakeMember(BOB), FakeMember(CAROL)],
    )
    await content_loader.load_content(
        content_module.load_files(), guild_ids=[GUILD_A]
    )
    await database.set_setting(GUILD_A, resolve.DROP_KEY, LAST_DROP)
    await database.set_announcement_channel(GUILD_A, halloween.id)
    for who in (ALICE, BOB, CAROL):
        await database.start_game(who, GUILD_A, "LI", ["LI"])
    monkeypatch.setattr(
        bot,
        "bot",
        SimpleNamespace(
            guilds=[guild], get_guild=lambda gid: guild if gid == GUILD_A else None
        ),
    )
    yield db, guild, halloween
    achievements.clear()


async def yesterday(guild_id=GUILD_A):
    return await database.server_today(guild_id) - timedelta(days=1)


async def was_the_ghost(who, *, day=None, guild_id=GUILD_A, display_name=None):
    """The row the changeover wrote when it picked them. Returns the day."""
    if day is None:
        day = await yesterday(guild_id)
    await database.record_daily_ghost(
        guild_id,
        day,
        user_id=who,
        display_name=display_name or NAMES[who][0],
        username=NAMES[who][1],
        eligible=3,
    )
    return day


async def nobody_was_the_ghost(*, day=None, guild_id=GUILD_A):
    """The row a day with too few eligible players leaves behind."""
    if day is None:
        day = await yesterday(guild_id)
    await database.record_daily_ghost(
        guild_id, day, user_id=None, display_name=None, username=None, eligible=2
    )
    return day


async def _logged(action, who, day, *, thing_id, guild_id=GUILD_A, outcome=None, hour=12):
    start, _ = database.pacific_day_bounds_utc(day)
    await database.log_interaction(
        guild_id,
        user_id=who,
        action=action,
        outcome=outcome or database.SUCCESS,
        thing_id=thing_id,
        now=start + timedelta(hours=hour),
    )


async def haunted(who, day, *, times=1, guild_id=GUILD_A):
    for n in range(times):
        await _logged(
            database.HAUNTED,
            who,
            day,
            thing_id=ghosts.BEDSHEET,
            guild_id=guild_id,
            hour=9 + n,
        )


async def named_them(who, day, *, guild_id=GUILD_A):
    await _logged(
        database.BOARD_GUESS,
        who,
        day,
        thing_id=ghosts.SPIRIT_BOARD,
        guild_id=guild_id,
    )


async def guessed_wrong(who, day, *, guild_id=GUILD_A):
    await _logged(
        database.BOARD_GUESS,
        who,
        day,
        thing_id=ghosts.SPIRIT_BOARD,
        guild_id=guild_id,
        outcome=database.REFUSED,
    )


def posted(house):
    _, _, halloween = house
    return [line for line in halloween.posted if line]


async def the_night(house):
    """One whole changeover, exactly as midnight runs it."""
    await bot.nightly_job.coro()
    return posted(house)


# --------------------------------------------------------------------------
# Which line the day gets
# --------------------------------------------------------------------------


async def test_a_ghost_who_was_named_is_named_with_the_count(house):
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day)
    await named_them(BOB, day)
    await named_them(CAROL, day)

    reveal = await ghosts.reveal_for(GUILD_A)

    assert reveal == ghosts.Reveal(
        ghosts.REVEAL_NAMED, {"name": "Alice", "count": 2}
    )


async def test_a_ghost_nobody_named_gets_the_other_line(house):
    """Still named, and the count is gone rather than zero: the design
    writes the two endings as two sentences."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day)

    reveal = await ghosts.reveal_for(GUILD_A)

    assert reveal == ghosts.Reveal(ghosts.REVEAL_NOBODY, {"name": "Alice"})


async def test_a_ghost_who_never_haunted_is_not_named(house):
    """Amended into the design on 11 November. Nobody is called out for
    a day they did not play, so the name is kept and the line says so."""
    await was_the_ghost(ALICE)

    reveal = await ghosts.reveal_for(GUILD_A)

    assert reveal == ghosts.Reveal(ghosts.REVEAL_QUIET)
    assert "Alice" not in str(reveal.args)


async def test_a_day_nobody_wore_the_sheet_says_nothing(house):
    """**Not the quiet line**, which would be untrue. It says the board
    is keeping the name of whoever held the sheet to itself, and on a
    skipped day nobody held it - so there is nothing to keep and
    nothing to post."""
    await nobody_was_the_ghost()

    assert await ghosts.reveal_for(GUILD_A) is None


async def test_a_server_that_never_picked_says_nothing(house):
    """No row at all: this server was not playing part 2 yesterday."""
    assert await ghosts.reveal_for(GUILD_A) is None


async def test_before_the_library_opens_there_is_no_reveal(house):
    """The same gate the pick keeps. A server rolled back below 50 has
    a board nobody can reach, so a reveal would be a line about a game
    that is not running."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day)
    await database.set_setting(GUILD_A, resolve.DROP_KEY, LAST_DROP - 1)

    assert await ghosts.reveal_for(GUILD_A) is None


# --------------------------------------------------------------------------
# Counting the players who got it
# --------------------------------------------------------------------------


async def test_a_wrong_guess_is_not_a_right_one(house):
    """Both are a `board_guess` row and `outcome` is the only thing
    between them, which is why the guess is logged that way."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day)
    await guessed_wrong(BOB, day)

    reveal = await ghosts.reveal_for(GUILD_A)

    assert reveal == ghosts.Reveal(ghosts.REVEAL_NOBODY, {"name": "Alice"})


async def test_the_count_is_players_rather_than_rows(house):
    """One guess a day each makes the two the same number today. The
    line counts people - *2 of you named them* - so a later change that
    let somebody guess twice must not inflate it."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day)
    await named_them(BOB, day)
    await named_them(BOB, day)

    reveal = await ghosts.reveal_for(GUILD_A)

    assert reveal.args["count"] == 1


async def test_a_guess_from_the_day_before_does_not_count(house):
    """It was about a different ghost."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day)
    await named_them(BOB, day - timedelta(days=1))

    reveal = await ghosts.reveal_for(GUILD_A)

    assert reveal == ghosts.Reveal(ghosts.REVEAL_NOBODY, {"name": "Alice"})


async def test_another_servers_guesses_do_not_count(house):
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day)
    await named_them(BOB, day, guild_id=GUILD_B)

    reveal = await ghosts.reveal_for(GUILD_A)

    assert reveal == ghosts.Reveal(ghosts.REVEAL_NOBODY, {"name": "Alice"})


async def test_somebody_elses_haunting_does_not_make_a_quiet_day_loud(house):
    """The count is the ghost's own. A `haunted` row belonging to
    anybody else is a row that should not exist, and reading it would
    name a ghost who spent the day doing nothing."""
    day = await was_the_ghost(ALICE)
    await haunted(BOB, day, times=3)

    assert await ghosts.reveal_for(GUILD_A) == ghosts.Reveal(ghosts.REVEAL_QUIET)


async def test_a_haunting_the_day_before_does_not_count(house):
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day - timedelta(days=1))

    assert await ghosts.reveal_for(GUILD_A) == ghosts.Reveal(ghosts.REVEAL_QUIET)


# --------------------------------------------------------------------------
# Said once
# --------------------------------------------------------------------------


async def test_the_day_can_only_be_revealed_once(house):
    """The nightly job can run twice and `/qa-midnight` settles every
    night a server owes, so the stamp is the whole protection."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day)

    assert await ghosts.reveal_for(GUILD_A) is not None
    assert await ghosts.reveal_for(GUILD_A) is None


async def test_the_stamp_is_taken_even_on_a_quiet_day(house):
    """A quiet day still posts a line, so it still has to be spent."""
    await was_the_ghost(ALICE)

    assert await ghosts.reveal_for(GUILD_A) == ghosts.Reveal(ghosts.REVEAL_QUIET)
    assert await ghosts.reveal_for(GUILD_A) is None


async def test_revealing_one_server_does_not_spend_another(house):
    day = await was_the_ghost(ALICE)
    await was_the_ghost(ALICE, day=day, guild_id=GUILD_B)
    await database.set_setting(GUILD_B, resolve.DROP_KEY, LAST_DROP)

    assert await ghosts.reveal_for(GUILD_A) is not None
    assert await ghosts.reveal_for(GUILD_B) is not None


async def test_a_day_with_no_row_cannot_be_claimed(house):
    day = await yesterday()

    assert await database.claim_the_reveal(GUILD_A, day) is False


# --------------------------------------------------------------------------
# What the channel actually sees
# --------------------------------------------------------------------------


async def test_the_night_posts_the_name_in_the_channel(house):
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day)
    await named_them(BOB, day)

    lines = await the_night(house)

    assert "Alice" in lines[0]
    assert "1 of you named them" in lines[0]


async def test_the_night_posts_the_quiet_line_with_no_name(house):
    await was_the_ghost(ALICE)

    lines = await the_night(house)

    assert "Yesterday slipped by without a single haunting" in lines[0]
    assert "Alice" not in lines[0]


async def test_the_reveal_pings_nobody(house):
    """**The one thing that must not happen.** Somebody is being named
    in public for a day they spent under a sheet; their phone going off
    about it is the version of this that gets the feature turned off."""
    _, _, halloween = house
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day)

    await the_night(house)

    assert halloween.mentions[0].users is False
    assert halloween.mentions[0].everyone is False


async def test_a_display_name_cannot_smuggle_a_ping(house):
    """The name goes out as the writers' token in a line, and the line
    goes out with every mention class off, so a display name that is
    mention-shaped stays text."""
    _, _, halloween = house
    day = await was_the_ghost(ALICE, display_name="@everyone")
    await haunted(ALICE, day)

    lines = await the_night(house)

    assert "@everyone" in lines[0]
    assert halloween.mentions[0].everyone is False


async def test_the_reveal_happens_before_the_pick(house):
    """The order the work order asks for. The two read different rows,
    so this is not protecting against an overwrite - it is making sure
    the reveal can never be written against a row the pick decided."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day)
    for who in (ALICE, BOB, CAROL):
        await database.log_interaction(
            GUILD_A,
            user_id=who,
            action=database.LOOK,
            outcome=database.SUCCESS,
            now=database.pacific_day_bounds_utc(day)[0] + timedelta(hours=10),
        )

    lines = await the_night(house)

    assert "Alice" in lines[0]
    today = await database.server_today(GUILD_A)
    assert (await database.daily_ghost(GUILD_A, today)) is not None


async def test_a_second_night_says_nothing_again(house):
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day)

    first = await the_night(house)
    await bot.nightly_job.coro()

    assert posted(house) == first


async def test_a_server_with_no_channel_does_not_stop_the_night(house):
    """The stamp is already spent by then, which is the documented
    trade. What must not happen is the exception reaching the loop and
    costing every other server its changeover."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day)
    await database.set_announcement_channel(GUILD_A, 999999999)
    _, guild, _ = house
    guild.text_channels = []

    await bot.nightly_job.coro()

    assert posted(house) == []


# --------------------------------------------------------------------------
# Boo Who?
# --------------------------------------------------------------------------


async def earned_by(who, guild_id=GUILD_A):
    return await database.player_achievements_of(guild_id, who)


async def test_three_hauntings_and_nobody_guessing_earns_it(house):
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day, times=3)

    await bot.nightly_job.coro()

    assert "boo_who" in await earned_by(ALICE)


async def test_it_goes_to_the_ghost_and_to_nobody_else(house):
    """`on_midnight` fires with no player at all, so this is the only
    award in the game whose earner has to be looked up rather than
    taken from whoever acted."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day, times=3)

    await bot.nightly_job.coro()

    for who in (BOB, CAROL):
        assert "boo_who" not in await earned_by(who)


async def test_two_hauntings_are_not_enough(house):
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day, times=2)

    await bot.nightly_job.coro()

    assert "boo_who" not in await earned_by(ALICE)


async def test_one_right_guess_loses_it(house):
    """The sheet is a disguise and the award is for keeping it on, so
    being worked out once is being worked out."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day, times=3)
    await named_them(BOB, day)

    await bot.nightly_job.coro()

    assert "boo_who" not in await earned_by(ALICE)


async def test_a_wrong_guess_does_not_lose_it(house):
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day, times=3)
    await guessed_wrong(BOB, day)

    await bot.nightly_job.coro()

    assert "boo_who" in await earned_by(ALICE)


async def test_a_day_with_no_ghost_earns_nobody_anything(house):
    """The hook fires for every server every night, including the ones
    with nothing to say."""
    await nobody_was_the_ghost()

    await bot.nightly_job.coro()

    for who in (ALICE, BOB, CAROL):
        assert "boo_who" not in await earned_by(who)


async def test_the_award_lands_after_the_reveal(house):
    """**The spoiler guard.** An achievement line names its earner, so
    *Boo Who?* going out first would spell the name before the board
    does and the day would end backwards."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day, times=3)

    lines = await the_night(house)

    assert "slipped out of their sheet" in lines[0]
    assert "Boo Who?" in lines[1]


async def test_the_award_names_the_ghost_without_pinging_them(house):
    """**The reveal's rule, applied to the line that follows it.**

    `_announce` pings an earner it has no interaction to answer, which
    is right for *Met the Craving* - a reaction has no reply, so the
    public line is all its earner gets and a mention is what makes
    them read it. *Boo Who?* is earned on the midnight job, so it took
    that branch and went out as a mention.

    Being named here is fine and is the point: the reveal has already
    spelled the name out a line earlier, and #207 is what guarantees
    that order. The ping is not. Somebody is being told in public that
    they spent yesterday under a sheet and nobody worked it out, and
    their phone going off about it is the one thing `_reveal_the_ghost`
    already refuses to do. The two lines are the same sentence about
    the same person and now post the same way.
    """
    day = await was_the_ghost(ALICE, display_name="Alice")
    await haunted(ALICE, day, times=3)

    lines = await the_night(house)

    assert "Boo Who?" in lines[1]
    assert "<@" not in lines[1]
    # The name is still there, and it comes from the member cache
    # rather than from the row the pick wrote - `_earner_of` asks the
    # guild, `_reveal_the_ghost` reads `daily_ghosts.display_name`. The
    # two agree on a real server and are deliberately made to disagree
    # here, so that neither assertion can pass on the other's string.
    assert "Player 100000000000000001 earned" in lines[1]


async def test_the_reveal_still_carries_no_mention_either(house):
    """The half that was already true, kept beside the half that was
    not, so a change to either is read against the other."""
    day = await was_the_ghost(ALICE, display_name="Alice")
    await haunted(ALICE, day, times=3)

    lines = await the_night(house)

    assert "Alice" in lines[0]
    assert "<@" not in lines[0]


async def test_a_second_night_does_not_announce_it_again(house):
    """The predicate is still true the second time - the day has not
    changed - so what stops a second announcement is the award being
    idempotent per player."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day, times=3)
    await the_night(house)

    await bot.nightly_job.coro()

    assert len([line for line in posted(house) if "Boo Who?" in line]) == 1


# --------------------------------------------------------------------------
# A reveal that could not post
# --------------------------------------------------------------------------
#
# Running first stops the award overtaking the reveal. It does not stop
# the award going out on a night the reveal never managed to, and that
# is reachable without anything raising: `reveal_for` takes the claim
# before it hands the line back, so a server with nowhere to post spends
# the night's reveal, posts nothing, and used to go straight on to grant
# *Boo Who?* - naming the ghost by way of the achievement and never by
# way of the board, with the reveal burned and no second chance at it.
#
# **These check the database and not the channel.** `_announce_all`
# fails quietly when there is nowhere to post, so a test that only read
# the posted lines would pass against a granted award.


def nowhere_to_post(monkeypatch):
    """A server the game has no channel in.

    Patched rather than arranged, because a stale id is not this: the
    id is only `_game_channel`'s first guess and it falls back to
    `house_utils.find_channel`, so a server whose recorded channel is
    gone and whose #halloween is still there has somewhere to post. The
    branch under test is the one where both have failed.
    """

    async def gone(guild):
        return None

    monkeypatch.setattr(bot, "_game_channel", gone)


def no_line_to_post(monkeypatch):
    """The other half: content that shipped without the reveal lines."""
    import phrasing

    real = phrasing.default_say

    async def missing(key, **args):
        if key.startswith("ghost.reveal."):
            return ""
        return await real(key, **args)

    monkeypatch.setattr(phrasing, "default_say", missing)


def recording_hooks(monkeypatch):
    """Every hook `nightly_job` fires, in order, still doing its work."""
    fired = []
    real = bot._fire

    async def recording(context, **kwargs):
        fired.append(context.hook)
        return await real(context, **kwargs)

    monkeypatch.setattr(bot, "_fire", recording)
    return fired


async def test_the_award_is_withheld_when_there_is_nowhere_to_post(
    house, monkeypatch
):
    """**The hole the ordering could not see.** Granted-and-unannounced
    is the state this exists to prevent, not merely out-of-order."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day, times=3)
    nowhere_to_post(monkeypatch)

    await bot.nightly_job.coro()

    assert "boo_who" not in await earned_by(ALICE)


async def test_the_award_is_withheld_when_the_reveal_line_is_missing(
    house, monkeypatch
):
    """A content file that shipped without the line is the same failure
    as nowhere to post, and `_reveal_the_ghost` treats it as one."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day, times=3)
    no_line_to_post(monkeypatch)

    await bot.nightly_job.coro()

    assert "boo_who" not in await earned_by(ALICE)


async def test_the_hook_is_skipped_when_the_reveal_could_not_post(
    house, monkeypatch
):
    """The same seam from the other side: not just *no award* but *the
    hook did not run*, which is what the gate actually does."""
    fired = recording_hooks(monkeypatch)
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day, times=3)
    nowhere_to_post(monkeypatch)

    await bot.nightly_job.coro()

    assert "on_midnight" not in fired


async def test_the_award_does_not_post_when_the_board_could_not(
    house, monkeypatch
):
    """With the line missing the channel is still there, so this is the
    case where an award could have gone out alone.

    **Asserted on the award's own line and not on the display name**,
    which is what the first draft of this did and it passed against the
    defect. `_announce` fills `achievement.public` with `<@id>` rather
    than a name - deliberately, so that a display name shaped like a
    mention cannot become one - so "Alice" never appears literally and
    a test looking for it proves nothing either way.
    """
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day, times=3)
    no_line_to_post(monkeypatch)

    await bot.nightly_job.coro()

    assert not [line for line in posted(house) if "Boo Who?" in line]


async def test_a_quiet_night_still_fires_the_hook(house, monkeypatch):
    """**The line between the two silences.** A night with no ghost has
    no name to give away, and a hook that only ran on interesting nights
    would be a different hook."""
    fired = recording_hooks(monkeypatch)
    await nobody_was_the_ghost()

    await bot.nightly_job.coro()

    assert "on_midnight" in fired


async def test_the_pick_still_happens_when_the_reveal_could_not_post(
    house, monkeypatch
):
    """Today is owed a ghost either way: the pick reads a different day
    from the reveal, so one bad night is not two."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day, times=3)
    nowhere_to_post(monkeypatch)

    await bot.nightly_job.coro()
    today = await database.server_today(GUILD_A)

    assert await database.daily_ghost(GUILD_A, today) is not None


async def test_the_award_still_lands_on_a_night_that_posted(house):
    """Passes without the change. The guard that the gate did not close
    on the case it was built to protect."""
    day = await was_the_ghost(ALICE)
    await haunted(ALICE, day, times=3)

    lines = await the_night(house)

    assert "boo_who" in await earned_by(ALICE)
    assert "slipped out of their sheet" in lines[0]
    assert "Boo Who?" in lines[1]
