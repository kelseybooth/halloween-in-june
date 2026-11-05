"""Drop 30: the top steps, which need the ladder, and the award for them.

`test_the_staircase` is drop 20 and owns the repair as far as a person
can reach from the floor: ninety planks by default, one per player per
day, counted per server, stopping at seventy-two. This file is what drop
30 adds, which is the last fifth and the end of it.

**Why the gate is where it is.** Drop 20 shipped the stopping point
without the thing that passes it: in `stairs_upper` the lumber had a
refusal and no success, so `_state_refusal` turned the use down before
the cooldown was read - deliberately, because a player who already laid
a plank today has to be told about the steps rather than about their
muscles. Drop 30 gives that state a success line, so the refusal moved
into code and kept the same position.

**Why a ladder standing in the hall is enough.** `to_hand_in_room` on
the ladder's own row means carried *or* lying in the room counts as to
hand. Propped against the staircase it is furniture, so the eighteen
top-step planks can be laid back to back by eighteen different people
without anybody carrying anything - which is the only way one ladder
serves a server.

**Why the award is a shape of its own.** *Board Meeting* was written for
drop 20 and parked at 99 for two releases, because the engine had no
word for it: a `group` row awards the server and names nobody, and the
staircase is collective work that not everybody did. It goes to the
people who laid a plank and announces once.
"""

from types import SimpleNamespace

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import achievements
import bot
import content as content_module
import content_loader
import database
import reach
import resolve
import states
import triggers
import world


THIS_DROP = 31

# A third player, who turns up and never lifts a hammer. Local, the way
# every other file that wants one keeps theirs.
CAROL = 400

# Ten planks, so `stairs_upper` lands at eight and the last two are
# top-step planks. The same arithmetic as the shipped ninety, where it
# is 72 and 90. **Two rather than one**, which five would have given:
# with five, the single top-step plank is also the plank that finishes
# the staircase, and the lumber disappears on that - so a test about
# laying a second one off a ladder somebody left standing had nothing
# left to lay.
TARGET = 10
UPPER_AT = 8

# **Stops before the staircase, for the ladder's reason one step on.**
# The exit was named "grand staircase" and answered to `staircase` as a
# single-word alias, and `content.markable` does not bold those - they
# are "a convenience for the parser, not a noun a sentence is about".
# The rename on 5 November made `staircase` the *name*, and a name is
# always markable, so the word is bold here now and the phrase stopped
# matching itself. `plank` is still safe: it is a one-word alias of the
# lumber, so it stays plain.
FROM_THE_FLOOR = "hauls a plank over to the"
# Not "leans the ladder": `ladder` is a thing in the room, so the
# engine bolds the word and the phrase stops matching itself.
FROM_THE_LADDER = "climbs with a plank under one arm"
NO_LADDER = "too high to fix without something to stand on"
# **Not the same reason, and worth the note.** Making the finish
# sentence the use's own line put it through the noun marker for a day,
# which bolded "grand staircase" and broke this constant; `Effect.marked`
# turns the marking off for that one line, so the phrase matches itself
# again. `test_the_finish_line_is_not_bolded` is what keeps it true.
FINISHED = "The grand staircase is whole again"
BOARD_MEETING = "board_meeting"


@pytest.fixture(autouse=True)
def registry():
    achievements.clear()
    triggers.register_all()
    triggers.forget_arrivals()
    yield
    achievements.clear()


@pytest.fixture(autouse=True)
def forget_admissions():
    bot._ADMITTING.clear()
    yield
    bot._ADMITTING.clear()


@pytest.fixture
async def hall(db):
    """Drop 30, a five-plank staircase, three players in the Entryway.

    Three because *Board Meeting* needs somebody who did not help. The
    drop goes in before the load and the load is told the guild, for the
    reason `test_the_ladder` spells out: the ladder is stock, and the
    loader places stock into the servers it has heard of.
    """
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A,
        channels=[halloween],
        members=[FakeMember(ALICE), FakeMember(BOB), FakeMember(CAROL)],
    )
    for who in (ALICE, BOB, CAROL):
        await db.ensure_user_exists(who, GUILD_A)
    await db.set_setting(GUILD_A, resolve.DROP_KEY, THIS_DROP)
    await content_loader.load_content(
        content_module.load_files(), guild_ids=[GUILD_A]
    )
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await resolve.set_current_drop(GUILD_A, THIS_DROP)
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    await db.set_setting(GUILD_A, world.PLANKS_SETTING, TARGET)
    for who in (ALICE, BOB, CAROL):
        await db.start_game(who, GUILD_A, "EN", await resolve.rooms_open_at_launch())
        await db.notice(GUILD_A, who, content_module.FED_THE_CAT)
    return db, guild, halloween, rooms


def place(hall, room="EN"):
    _, _, halloween, rooms = hall
    return next(t for t in halloween.threads if t.name == rooms[room])


async def run(hall, command, arg=None, *, room="EN", who=ALICE):
    db, guild, _, _ = hall
    await db.update_current_room(who, GUILD_A, room)
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=place(hall, room))
    args = () if arg is None else (arg,)
    await command.callback(interaction, *args)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


def posted(hall, room="EN") -> str:
    return "\n".join(place(hall, room).posted)


def in_the_channel(hall) -> str:
    """What #halloween has seen, which is where awards are announced."""
    return "\n".join(hall[2].posted)


async def plank(hall, who=ALICE) -> str:
    """One `/use lumber`. What comes back is a refusal or nothing at all:
    a laid plank is posted to the room and sent to the player not at
    all, which is what `test_the_staircase` pins."""
    return replies(await run(hall, bot.use, "lumber", who=who))


async def floor_planks(hall, count=UPPER_AT):
    """Lay the planks a person can reach, one per player per day.

    `record_use` rather than the command, because the daily cooldown is
    `test_the_staircase`'s subject and would otherwise need four days
    of clock here.
    """
    for _ in range(count):
        await database.record_use(ALICE, GUILD_A, world.LUMBER, room_id=None)
    await world.check_staircase(GUILD_A)


async def ladder_in_the_hall():
    await database.place_in_room(GUILD_A, "EN", world.LADDER, 1)


async def carried_by(who=ALICE):
    await database.place_in_room(GUILD_A, "EN", world.LADDER, 1)
    await database.take_from_room(
        who, GUILD_A, "EN", database.LOOSE_IN_ROOM, world.LADDER
    )


async def earned_by(who=ALICE) -> set:
    return set(await database.player_achievements_of(GUILD_A, who))


async def floor_of(room="EN") -> dict:
    return dict(await database.loose_here(GUILD_A, room))


# --------------------------------------------------------------------------
# Below the top steps, nothing has changed
# --------------------------------------------------------------------------


async def test_a_plank_within_reach_needs_no_ladder(hall):
    """Seventy-two of the default ninety are like this, and the gate must
    be silent for all of them."""
    assert await plank(hall) == ""
    assert FROM_THE_FLOOR in posted(hall)


async def test_the_plank_that_crosses_into_the_top_steps_is_allowed(hall):
    """**The gate reads the state as it stood before this plank**, and
    the plank that crosses into `stairs_upper` is by definition one
    somebody could still reach from the floor. Asked because the
    off-by-one in the other direction would stop the repair one plank
    early and forever."""
    await floor_planks(hall, UPPER_AT - 1)

    assert await plank(hall, who=BOB) == ""
    assert world.STAIRS_UPPER in await states.in_force(GUILD_A, BOB)


# --------------------------------------------------------------------------
# The top steps need the ladder
# --------------------------------------------------------------------------


async def test_without_the_ladder_the_steps_are_out_of_reach(hall):
    await floor_planks(hall)

    assert NO_LADDER in await plank(hall, who=BOB)


async def test_and_nothing_is_counted(hall):
    """A refused use is not a use. The count must not move, or a server
    could grind the staircase out by bouncing off this line."""
    await floor_planks(hall)

    await plank(hall, who=BOB)

    placed, _ = await world.planks(GUILD_A)
    assert placed == UPPER_AT


async def test_a_carried_ladder_passes_the_gate(hall):
    await floor_planks(hall)
    await carried_by(BOB)

    assert await plank(hall, who=BOB) == ""
    assert FROM_THE_LADDER in posted(hall)


async def test_so_does_one_standing_in_the_hall(hall):
    """**The half of `to_hand_in_room` that makes one ladder enough.**
    Nobody picks it up: it is propped against the staircase, which is
    where the last plank left it, and the next person to turn up can lay
    theirs without going to find whoever had it."""
    await floor_planks(hall)
    await ladder_in_the_hall()

    assert await plank(hall, who=BOB) == ""
    assert await database.carried_of(BOB, GUILD_A, world.LADDER) == 0


async def test_but_not_one_standing_somewhere_else(hall):
    """It is in the Courtyard where the loader put it, which is where
    every server starts - so this is the state of a fresh drop 30 and
    not a contrivance."""
    await floor_planks(hall)

    assert NO_LADDER in await plank(hall, who=BOB)
    assert "ladder" in await floor_of("CO")


async def test_the_ladder_is_asked_about_before_the_clock(hall):
    """**Drop 20's rule, kept.** A player who laid a plank this morning
    and comes back without the ladder has to hear about the steps, not
    about their muscles: the steps are a puzzle and the cooldown is a
    wait, and telling them the wrong one sends them away for a day."""
    await floor_planks(hall)
    await plank(hall, who=BOB)  # refused, so nothing is on cooldown
    await database.record_use(BOB, GUILD_A, world.LUMBER, room_id=None)

    refusal = await plank(hall, who=BOB)

    assert NO_LADDER in refusal
    assert "muscles" not in refusal


# --------------------------------------------------------------------------
# A plank sets the ladder down
# --------------------------------------------------------------------------


async def test_laying_a_plank_sets_a_carried_ladder_down(hall):
    """The other half of the rule that every climb sets it down. Both
    hands are on a hammer the moment the plank goes in, and leaving it
    on their shoulder would mean the next person had to find them."""
    await floor_planks(hall)
    await carried_by(BOB)

    await plank(hall, who=BOB)

    assert await database.carried_of(BOB, GUILD_A, world.LADDER) == 0
    assert "ladder" in await floor_of("EN")


async def test_and_it_stays_there_for_the_next_person(hall):
    await floor_planks(hall)
    await carried_by(BOB)
    await plank(hall, who=BOB)

    assert await plank(hall, who=CAROL) == ""


async def test_a_plank_lower_down_sets_it_down_too(hall):
    """Unconditional on the state. The ladder is only ever up here
    because somebody brought it for the top steps, and a plank laid
    lower down by somebody holding it should put it down just the same."""
    await carried_by(ALICE)

    await plank(hall)

    assert await database.carried_of(ALICE, GUILD_A, world.LADDER) == 0


# --------------------------------------------------------------------------
# The last plank
# --------------------------------------------------------------------------


async def finish_it(hall, who=BOB):
    """Everything but the last plank, then the last one off the ladder."""
    await floor_planks(hall, TARGET - 1)
    await ladder_in_the_hall()
    await plank(hall, who=who)


async def test_the_last_plank_finishes_the_staircase(hall):
    await finish_it(hall)

    assert world.STAIRS_REPAIRED in await states.in_force(GUILD_A, ALICE)


async def test_the_room_reads_the_writers_line(hall):
    """**Which it did not until 30 October.** The announcement was a
    sentence typed into `world._place_a_plank` while
    `stairs.repaired.public` sat in the deck unread - written,
    approved, and reachable by nothing, which is the shipping box's
    failure in another costume."""
    await finish_it(hall)

    assert FINISHED in posted(hall)


async def test_and_it_names_who_hammered_it_in(hall):
    """The line opens with `{player}`, which only Discord can fill.

    **This used to read `"{name} hammers in the last plank"`**, and the
    two halves of that phrase are no longer adjacent: the name opens a
    sentence that reaches the hammering seventeen words later. So the
    assertion is the opening instead, which is where the token is.

    The note it carried is still the point. The display name used to
    appear in the thread either way, because the plank's own `use` line
    opened with it too, so an unfilled `{player}` in the finish sentence
    went unnoticed until a mutation run produced one. There is only one
    sentence now and the name appears once, which is what makes a bare
    opening assertion enough.
    """
    _, guild, _, _ = hall
    name = guild.get_member(BOB).display_name
    await finish_it(hall, who=BOB)

    assert f"{name} leans the" in posted(hall)
    assert "{player}" not in posted(hall)


async def test_the_ladder_finish_is_the_one_a_real_target_reaches(hall):
    """The other half of `test_the_floor_finish_does_not_mention_the
    _ladder`. A ten-plank staircase puts the last plank above the reach
    line, so the finish is the climb - and the floor line, which is
    right for a one-plank QA server, would be wrong here.
    """
    await finish_it(hall)
    room = posted(hall)

    assert "leans the ladder against the staircase" in room
    assert "hauls a plank over to the staircase" not in room


async def test_and_the_room_reads_one_sentence_rather_than_three(hall):
    """**The whole of the change of 5 November.** The room used to get
    the climb line, then the repair count on its own line, then the
    finish sentence under a blank line - which told it the plank went
    into "one of the top steps, then climbs back down" and then, two
    lines later, that it had been the last one.

    Asserted as the absence of the two parts that went away, because
    asserting the sentence itself is `test_the_room_reads_the_writers_line`
    directly above. The count is the sharper of the two: "10 of 10
    repairs done" is a progress line reporting that there is no more
    progress to make.
    """
    await finish_it(hall)
    room = posted(hall)

    assert FINISHED in room
    assert f"of {TARGET} repairs done" not in room
    assert "then climbs back down" not in room
    assert "\n\n" not in room


async def test_the_lumber_is_gone_afterwards(hall):
    """`present_when = !stairs_repaired`. The planks stop being a thing
    anybody can interact with, because the job is finished."""
    await finish_it(hall)

    found = await reach.find(GUILD_A, CAROL, "EN", "lumber", reach.Scope.REACH)

    assert isinstance(found, reach.NotFound)


async def test_the_cat_is_on_the_landing_until_drop_forty(hall):
    """The staircase is repaired and upstairs still is not open, so the
    exit has a refusal and no success at this drop. Content, not code -
    which is why the only thing worth asserting is that it is still
    true."""
    await finish_it(hall)

    refusal = replies(await run(hall, bot.go, "staircase", who=CAROL))

    assert "she won't let you past" in refusal
    assert (await hall[0].get_game_state(CAROL, GUILD_A)).current_room == "EN"


# --------------------------------------------------------------------------
# Board Meeting
# --------------------------------------------------------------------------


async def test_it_goes_to_everybody_who_laid_a_plank(hall):
    """Alice laid the first four and Bob the last. Both helped."""
    await finish_it(hall, who=BOB)

    assert BOARD_MEETING in await earned_by(ALICE)
    assert BOARD_MEETING in await earned_by(BOB)


async def test_and_to_nobody_who_did_not(hall):
    """**The whole reason this row waited two releases.** A `group` row
    awards the server, and a server row shows in every member's
    `/stats` - including the people who never picked up a hammer."""
    await finish_it(hall, who=BOB)

    assert BOARD_MEETING not in await earned_by(CAROL)


async def test_the_server_does_not_earn_it(hall):
    """Which is the mechanism behind the test above: `/stats` merges the
    server's achievements into every player's list, so a server row
    would hand it to Carol by another route."""
    await finish_it(hall, who=BOB)

    assert BOARD_MEETING not in await database.server_achievements_of(GUILD_A)


async def test_it_is_announced_once_in_the_group_style(hall):
    """Once however many contributors. It is still a `group` row - there
    is no single earner and nobody gets a private message - but since
    5 November the line names the contributors rather than the server.

    In the channel rather than in the room, which is where every
    achievement in the game is announced: the staircase is the
    Entryway's, and the news of it is the server's.
    """
    await finish_it(hall, who=BOB)

    assert in_the_channel(hall).count("Board Meeting") == 1


async def test_the_credit_line_names_everybody_who_laid_a_plank(hall):
    """**Which is the whole argument of the row, finally in the
    sentence.** It goes to the contributors rather than the server
    because the staircase is work not everybody did; a line crediting
    the server thanks the people who never picked up a hammer, which is
    the same objection that kept this row parked for two releases.

    Alice laid the first nine and Bob the last, so both are named on a
    line neither of them earned alone.
    """
    _, guild, _, _ = hall
    await finish_it(hall, who=BOB)
    announced = in_the_channel(hall)

    assert guild.get_member(ALICE).display_name in announced
    assert guild.get_member(BOB).display_name in announced


async def test_and_does_not_credit_the_player_who_never_helped(hall):
    """Carol stood in the Entryway for the whole repair. The award
    already passes her by; so does the thank-you."""
    _, guild, _, _ = hall
    await finish_it(hall, who=BOB)

    assert guild.get_member(CAROL).display_name not in in_the_channel(hall)


async def test_and_does_not_credit_the_server(hall):
    """The other three `group` rows still name the server, and this one
    stopped. Asserted because the fallback is a real branch: a line with
    no resolvable contributor on it goes back to the server's name
    rather than announcing a thank-you addressed to nobody."""
    _, guild, _, _ = hall
    await finish_it(hall, who=BOB)

    assert guild.name not in in_the_channel(hall)


async def test_a_contributor_discord_cannot_name_is_left_out(hall):
    """Somebody who laid a plank and then left the server has no display
    name to print, and a raw id in a sentence thanking people is worse
    than a shorter list. Their award row stays either way - this is the
    credit line, not the achievement.
    """
    _, guild, _, _ = hall
    gone = 999

    names = bot._contributors_of(
        SimpleNamespace(recipients=(ALICE, gone, BOB)), guild
    )

    assert names == sorted(
        [guild.get_member(ALICE).display_name, guild.get_member(BOB).display_name],
        key=str.casefold,
    )


async def test_the_credit_line_counts_what_it_could_not_fit(hall):
    """A ninety-plank staircase can be ninety different players, and a
    message over Discord's limit does not come back truncated - it fails
    to post. So the overflow is counted.

    Asked of the helper with a small budget rather than by building a
    guild of ninety members: the arithmetic is the subject and the
    members would be scenery. It takes `hall` all the same, because the
    clause that says what was left out is a writers' key and reading it
    needs the content in a database.
    """
    names = [f"Player {n}" for n in range(1, 21)]

    line = await bot._credit_list(names, budget=60)

    assert line.startswith("Player 1, Player 2")
    assert "others" in line
    assert len(line) <= 60 + len("and 00 others")


async def test_and_names_everybody_when_they_fit():
    """The ordinary case, and the one the request was about: all of them."""
    line = await bot._credit_list(["Ada", "Bo", "Cy"], budget=2000)

    assert line == "Ada, Bo, Cy"


async def test_it_does_not_fire_on_an_ordinary_plank(hall):
    await plank(hall)

    assert BOARD_MEETING not in await earned_by(ALICE)


async def test_nor_again_on_a_plank_after_the_last(hall):
    """A raised target can leave planks to lay after the staircase is
    already whole. `check_staircase` only reports the crossing, so there
    are no recipients on any use but that one."""
    await finish_it(hall, who=BOB)
    hall[2].posted.clear()
    await database.set_setting(GUILD_A, world.PLANKS_SETTING, TARGET + 2)

    await plank(hall, who=CAROL)

    assert BOARD_MEETING not in await earned_by(CAROL)
    assert "Board Meeting" not in in_the_channel(hall)


async def test_the_recipients_are_read_off_the_planks_laid(hall):
    """Asked of the world layer, because the list is what the award is.
    Three players in the hall and two of them worked."""
    await finish_it(hall, who=BOB)

    assert set(await database.users_of(GUILD_A, world.LUMBER)) == {ALICE, BOB}
