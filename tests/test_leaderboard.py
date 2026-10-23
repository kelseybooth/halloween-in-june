"""The leaderboard, and the public half of `/stats`.

Three things are being tested, and they fail in different ways.

**The ranking** is arithmetic: who is in it, in what order, and where
the viewer sits when they are off the first page. Wrong here and the
list is merely wrong.

**The disclosure** is not. `/stats @somebody` is the first command in
the game that shows one player another player's state, and the line it
must not cross is progress toward a secret - *Trash Panda* is safe
because the bot already shouted the name in the channel, *3 of 5 baby
bottles* is not. Wrong here and the game spoils itself.

**The buttons** are the first components in the project. What matters
is that a click replaces the message rather than stacking another, and
that the way back is always to the clicker's own stats.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import leaderboard
import resolve


CAROL, DAVE, ERIN = 400, 500, 600
EVERYONE = (ALICE, BOB, CAROL, DAVE, ERIN)


@pytest.fixture
async def server(db):
    await content_loader.load_content(content_module.load_files())
    guild = FakeGuild(
        GUILD_A,
        name="Test Server",
        members=[FakeMember(who, display_name=f"P{who}") for who in EVERYONE],
    )
    await resolve.set_current_drop(GUILD_A, 1)
    return db, guild


async def met_the_cat(db, who, score):
    """A player with a relationship and a recorded interaction."""
    await db.ensure_user_exists(who, GUILD_A)
    await db.adjust_relationship(who, GUILD_A, score)
    await db.touched_the_cat(who, GUILD_A, await db.server_now(GUILD_A))


async def stats(server, who=ALICE, player=None):
    _, guild = server
    interaction = FakeInteraction(who, GUILD_A, guild=guild)
    await bot.stats.callback(interaction, player)
    return interaction


def embed_of(interaction):
    return interaction.sent[-1][1]["embed"]


async def click(server, item, who=ALICE):
    _, guild = server
    interaction = FakeInteraction(who, GUILD_A, guild=guild)
    await item.callback(interaction)
    return interaction


# --------------------------------------------------------------------------
# Who is on it
# --------------------------------------------------------------------------


async def test_a_player_who_never_met_the_cat_is_left_off(server):
    """**Otherwise day one is a wall of zeroes in membership order.**
    A leaderboard of everybody who happens to be in the Discord is a
    member list, and it buries the handful of people actually playing."""
    db, guild = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)
    await db.ensure_user_exists(DAVE, GUILD_A)

    standings = await database.relationship_ranking(GUILD_A)

    assert {who for who, _ in standings} == {ALICE, BOB, CAROL}


async def test_an_interaction_counts_even_when_it_scored_nothing(server):
    """`last_cat_interaction_date` is stamped by attempts, not just
    successes - the toy's first offer is a guaranteed refusal. Somebody
    who tried is playing, whatever the meter says."""
    db, guild = server
    await db.ensure_user_exists(ALICE, GUILD_A)
    await db.touched_the_cat(ALICE, GUILD_A, await db.server_now(GUILD_A))

    assert [who for who, _ in await database.relationship_ranking(GUILD_A)] == [ALICE]


async def test_order_is_by_score_descending(server):
    db, _ = server
    await met_the_cat(db, ALICE, 10)
    await met_the_cat(db, BOB, 90)
    await met_the_cat(db, CAROL, 50)

    standings = await database.relationship_ranking(GUILD_A)

    assert [who for who, _ in standings] == [BOB, CAROL, ALICE]


async def test_a_negative_score_is_shown_as_one(server):
    """Raw scores, not bands. The floor is -100 and the number is the
    whole point of a ranking - rounding it into *the cat is mildly
    irritated* would make two players indistinguishable."""
    db, guild = server
    await met_the_cat(db, ALICE, 10)
    await met_the_cat(db, BOB, 10)
    await met_the_cat(db, CAROL, -40)

    body = "\n".join(await leaderboard.lines(guild, ALICE))

    assert "-40" in body


async def test_ties_do_not_shuffle_between_views(server):
    """Equal scores break on the older row, so a player does not appear
    to overtake somebody by refreshing."""
    db, guild = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 25)

    once = await database.relationship_ranking(GUILD_A)
    again = await database.relationship_ranking(GUILD_A)

    # Asserted as stability rather than as a specific sequence: rows
    # created inside one second share a `created_at`, so the id decides,
    # and which player that favours is not the contract. That it decides
    # the same way twice is exactly the contract.
    assert once == again
    assert {who for who, _ in once} == {ALICE, BOB, CAROL}


async def test_too_few_players_says_so_rather_than_rendering_a_stub(server):
    """A list of two reads as broken rather than as a standing."""
    db, guild = server
    await met_the_cat(db, ALICE, 10)
    await met_the_cat(db, BOB, 20)

    body = "\n".join(await leaderboard.lines(guild, ALICE))

    assert "Too few people" in body
    assert "1." not in body


# --------------------------------------------------------------------------
# Where the viewer sits
# --------------------------------------------------------------------------


async def a_crowd(db, guild, size, viewer_score):
    """`size` strangers scoring 1000 downward, plus the viewer.

    The viewer's own score decides where they land, so a test can put
    them at the top, in the middle, or off the end of the first page.
    """
    for n in range(size):
        guild.add_member(FakeMember(1000 + n, display_name=f"Q{n}"))
        await met_the_cat(db, 1000 + n, 1000 - n)
    await met_the_cat(db, ALICE, viewer_score)


async def test_a_viewer_inside_the_top_ten_is_not_repeated(server):
    db, guild = server
    await a_crowd(db, guild, 5, 1)

    body = await leaderboard.lines(guild, ALICE)

    assert sum("P400" in line or "Player" in line for line in body) <= 1
    assert "..." not in body


async def test_a_viewer_below_the_top_ten_gets_their_own_block(server):
    """Somebody sitting 34th should see where they stand without paging
    to find themselves."""
    db, guild = server
    await a_crowd(db, guild, 20, 1)

    body = await leaderboard.lines(guild, ALICE)

    assert "..." in body
    assert any("21." in line for line in body)


async def test_the_block_carries_one_player_either_side(server):
    """The rank alone is a number with nothing on it. One player each
    way answers who to catch and who is catching you."""
    db, guild = server
    await a_crowd(db, guild, 20, 985)

    body = await leaderboard.lines(guild, ALICE)
    after = body[body.index("...") + 1:]

    assert len(after) == 3
    assert any(line.startswith("**") for line in after)


async def test_the_own_rank_block_is_the_first_pages_alone(server):
    """Paging through the middle of the table is reading other people's
    standings. Repeating yours under every page is interface noise."""
    db, guild = server
    await a_crowd(db, guild, 20, 1)

    assert "..." not in await leaderboard.lines(guild, ALICE, page=1)


async def test_the_viewers_own_row_is_marked(server):
    db, guild = server
    await a_crowd(db, guild, 3, 1)

    body = await leaderboard.lines(guild, ALICE)

    assert any(line.startswith("**4.") for line in body)


async def test_a_player_who_left_is_not_shown(server):
    """**A leaderboard is read every day, and a row for somebody who
    has gone makes every reader notice the leaving.** The numbers below
    them shift, which is the trade: nobody is owed a permanent rank,
    and nobody should be reminded.
    """
    db, guild = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)
    await met_the_cat(db, 9999, 500)

    body = await leaderboard.lines(guild, ALICE)

    assert not any("500" in line for line in body)
    assert any(line.lstrip("*").startswith("1.") for line in body)


async def test_their_achievements_go_with_them(server):
    """Same rule, same reason. Naming them under *Recently Earned*
    would say they have gone just as loudly."""
    db, guild = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)
    await met_the_cat(db, 9999, 10)
    await db.award_player_achievement(GUILD_A, 9999, "making_first_contact")

    body = await leaderboard.lines(guild, ALICE)

    assert not any("Recently Earned" in line for line in body)


async def test_the_rank_in_stats_matches_the_board(server):
    """One filter, shared. A rank computed off the unfiltered query
    would count the departed and put everybody a place or two lower
    than the board they are looking at."""
    db, guild = server
    await met_the_cat(db, 9999, 500)
    for score, who in ((100, ALICE), (50, BOB), (10, CAROL)):
        await met_the_cat(db, who, score)

    body = embed_of(await stats(server, ALICE, guild.get_member(BOB))).description

    assert "Leaderboard rank: 2" in body


# --------------------------------------------------------------------------
# Recently earned
# --------------------------------------------------------------------------


async def test_the_recent_list_waits_for_drop_one(server):
    """At drop 0 the only thing anybody can earn is the first pet, so
    five rows of it would be a list of who has played at all."""
    db, guild = server
    await resolve.set_current_drop(GUILD_A, 0)
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)
        await db.award_player_achievement(GUILD_A, who, "making_first_contact")

    assert "Recently Earned" not in "\n".join(await leaderboard.lines(guild, ALICE))


async def test_it_names_the_achievement_and_the_player(server):
    db, guild = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)
    await db.award_player_achievement(GUILD_A, BOB, "making_first_contact")

    body = "\n".join(await leaderboard.lines(guild, ALICE))

    assert "Recently Earned" in body
    assert f"P{BOB}" in body


async def test_it_carries_no_unlock_text(server):
    """**The line the disclosure must not cross.** The bot already
    posts every achievement's name in the channel as it is earned,
    secrets included, so a name beside a player gives away nothing the
    room has not seen. The unlock blurb is the part `/stats` is
    ephemeral to protect."""
    db, guild = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)
    await db.award_player_achievement(GUILD_A, BOB, "making_first_contact")

    available = await resolve.achievements(GUILD_A)
    body = "\n".join(await leaderboard.lines(guild, ALICE))

    assert available["making_first_contact"].unlock not in body


async def test_at_most_five(server):
    db, guild = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)
    earned = list((await resolve.achievements(GUILD_A)).keys())[:8]
    for achievement_id in earned:
        await db.award_player_achievement(GUILD_A, ALICE, achievement_id)

    rows = await database.recent_achievements(GUILD_A, leaderboard.RECENT)

    assert len(rows) == 5


# --------------------------------------------------------------------------
# `/stats @player`
# --------------------------------------------------------------------------


async def test_looking_at_somebody_else_shows_their_score(server):
    db, guild = server
    await met_the_cat(db, BOB, 70)

    looked = embed_of(await stats(server, ALICE, guild.get_member(BOB)))

    assert "70" in looked.description
    assert looked.title == f"P{BOB}'s stats"


@pytest.mark.parametrize("hidden", ["Open Quests", "Total pets"])
async def test_it_hides_what_is_nobody_elses_business(server, hidden):
    """Open quests are a player's own plan, and the pet count is a
    per-player mechanic. Neither is a result the room has watched."""
    db, guild = server
    await met_the_cat(db, BOB, 70)

    body = embed_of(await stats(server, ALICE, guild.get_member(BOB))).description

    assert hidden not in body


async def test_it_hides_the_unlock_blurbs(server):
    db, guild = server
    await met_the_cat(db, BOB, 70)
    await db.award_player_achievement(GUILD_A, BOB, "making_first_contact")

    available = await resolve.achievements(GUILD_A)
    body = embed_of(await stats(server, ALICE, guild.get_member(BOB))).description

    assert available["making_first_contact"].name in body
    assert available["making_first_contact"].unlock not in body


async def test_my_own_stats_still_carry_everything(server):
    """The public view is a subtraction, so the private one has to be
    checked alongside it or the subtraction quietly applies to both."""
    db, _ = server
    await met_the_cat(db, ALICE, 70)
    await db.award_player_achievement(GUILD_A, ALICE, "making_first_contact")

    body = embed_of(await stats(server, ALICE)).description
    available = await resolve.achievements(GUILD_A)

    assert "Total pets" in body
    assert available["making_first_contact"].unlock in body


async def test_neither_view_counts_out_of_a_total(server):
    """A player's own list is what they have done, not a checklist of
    what they have not - and from outside, "nine of twenty-two" would
    turn somebody else's play into a completion percentage."""
    db, guild = server
    await met_the_cat(db, ALICE, 10)
    await met_the_cat(db, BOB, 10)
    await db.award_player_achievement(GUILD_A, BOB, "making_first_contact")

    public = embed_of(await stats(server, ALICE, guild.get_member(BOB))).description
    private = embed_of(await stats(server, ALICE)).description

    for body in (public, private):
        assert " of " not in body.split("Completed Achievements")[1]


# --------------------------------------------------------------------------
# The buttons
# --------------------------------------------------------------------------


async def test_stats_carries_a_leaderboard_button(server):
    db, _ = server
    await met_the_cat(db, ALICE, 10)

    view = (await stats(server)).sent[-1][1]["view"]

    assert [item.item.label for item in view.children] == ["Leaderboard"]


async def test_a_click_replaces_the_message_rather_than_adding_one(server):
    """Going back and forth between the two views must never stack
    replies - an ephemeral `/stats` is one message, and it stays one."""
    db, _ = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)

    clicked = await click(server, bot._OpenLeaderboard(0))

    assert clicked.sent == []
    assert len(clicked.edited) == 1


async def test_the_way_back_is_to_the_clickers_own_stats(server):
    """Not the player they were looking at. Bob opens the leaderboard
    from Alice's stats; See my stats returns Bob to Bob."""
    db, guild = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)

    clicked = await click(server, bot._MyStats(), who=BOB)

    assert clicked.edited[0]["embed"].title == f"Player {BOB}'s stats"


async def test_paging_appears_only_when_there_is_somewhere_to_go(server):
    db, _ = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)

    view = (await click(server, bot._OpenLeaderboard(0))).edited[0]["view"]

    assert [item.item.label for item in view.children] == ["See my stats"]


async def test_a_long_board_pages(server):
    db, guild = server
    await a_crowd(db, guild, 25, 1)

    first = (await click(server, bot._OpenLeaderboard(0))).edited[0]
    second = (await click(server, bot._OpenLeaderboard(1))).edited[0]

    assert [i.item.label for i in first["view"].children] == ["See my stats", "Next"]
    assert [i.item.label for i in second["view"].children] == [
        "See my stats", "Previous", "Next",
    ]
    assert "11." in second["embed"].description


async def test_a_page_past_the_end_lands_on_the_last_one(server):
    """The page number rides in the `custom_id`, so a stale button from
    before somebody dropped off the board can ask for a page that is no
    longer there."""
    db, _ = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)

    edited = (await click(server, bot._OpenLeaderboard(9))).edited[0]

    assert "1." in edited["embed"].description


async def test_the_buttons_survive_a_restart(server):
    """**Persistence is the whole reason the page is in the id.** An
    ephemeral `/stats` sits open for hours, and a deploy in the middle
    of that must not turn its buttons into dead rectangles. Nothing
    about a click reads state held in the process."""
    import re

    for cls, custom_id in (
        (bot._OpenLeaderboard, "hij:lb:3"),
        (bot._MyStats, "hij:me"),
    ):
        assert re.fullmatch(cls.__discord_ui_compiled_template__, custom_id), custom_id

# --------------------------------------------------------------------------
# Whose sentence it is
# --------------------------------------------------------------------------


async def test_the_band_is_about_them_not_about_you(server):
    """**Nine strings written for the one person reading them.**

    Every relationship band is second person, which is right in a
    player's own `/stats` and wrong the moment it is shown to somebody
    else: *the cat adores you*, printed under Max's name, to Alice. The
    same mistake the take and drop lines made when they went public,
    and found the same way - by reading the output rather than the
    code.
    """
    db, guild = server
    await met_the_cat(db, BOB, 250)

    body = embed_of(await stats(server, ALICE, guild.get_member(BOB))).description

    assert f"The cat adores P{BOB}." in body
    assert "adores you" not in body


async def test_my_own_band_still_speaks_to_me(server):
    """The other half. A subtraction applied to both views would have
    Kelsey reading about Kelsey in the third person."""
    db, _ = server
    await met_the_cat(db, ALICE, 250)

    assert "The cat adores you." in embed_of(await stats(server, ALICE)).description


def test_an_other_line_that_says_you_fails_to_load():
    """What stops the tenth band arriving in the first person's voice.
    The suffix is the whole rule, so it covers whatever needs one next."""
    parsed = content_module.load_files()
    parsed.defaults["stats.rel.adores.other"] = "The cat adores you."

    problems = content_module.validate(parsed)

    assert any("stats.rel.adores.other" in problem for problem in problems)


def test_a_third_person_line_that_names_nobody_is_fine():
    """*The cat is mildly irritated* is correct for either audience, so
    the check is on the pronoun rather than on a required token."""
    parsed = content_module.load_files()

    assert "you" not in parsed.defaults["stats.rel.irritated.other"]
    assert not content_module.validate(parsed)

# --------------------------------------------------------------------------
# When the server cannot say who is in it
#
# The bot asked `guild.get_member` whether each player was still a
# member and kept only the ones it confirmed. That reads as "everybody"
# until the cache is empty - and it was, because `Intents.default()`
# does not include members and nothing had turned it on. A test server
# with three testers who had all petted the cat reported that too few
# people had met her.
#
# Two fixes, and these cover the second: the intent is requested now,
# and the filter no longer treats an unanswerable question as a no.
# --------------------------------------------------------------------------


def a_cold_guild():
    """A guild whose member cache cannot answer - no members intent."""
    return FakeGuild(
        GUILD_A,
        name="Test Server",
        members=[FakeMember(who, display_name=f"P{who}") for who in EVERYONE],
        chunked=False,
    )


async def test_an_unanswerable_cache_leaves_everybody_on(server):
    """**The bug, exactly.** Three testers, all of whom had petted, and
    a board that said too few people had met the cat."""
    db, _ = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)

    body = await leaderboard.lines(a_cold_guild(), ALICE)

    assert "Too few" not in "\n".join(body)
    assert len(await leaderboard.standings(a_cold_guild())) == 3


async def test_a_cold_cache_still_ranks_the_viewer(server):
    """`/stats @somebody` reads the same standings, so a rank of None
    was the same bug wearing different clothes."""
    db, _ = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)

    assert await leaderboard.rank_of(a_cold_guild(), BOB) is not None


async def test_a_cold_cache_does_not_empty_recently_earned(server):
    db, _ = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)
    await db.award_player_achievement(GUILD_A, BOB, "making_first_contact")

    body = "\n".join(await leaderboard.lines(a_cold_guild(), ALICE))

    assert "Recently Earned" in body


async def test_a_warm_cache_still_hides_the_departed(server):
    """The other half. Failing open must not quietly retire the
    behaviour it was added for."""
    db, guild = server
    for who in (ALICE, BOB, CAROL):
        await met_the_cat(db, who, 10)
    await met_the_cat(db, 9999, 500)

    assert not any("500" in line for line in await leaderboard.lines(guild, ALICE))


def test_the_bot_asks_for_the_intent_that_makes_this_work():
    """Requested in code *and* granted in the developer portal - and
    asking for one the portal has not granted makes the login fail, so
    the two have to move together."""
    import bot

    assert bot.bot.intents.members
    assert bot.bot.intents.message_content

