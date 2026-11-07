"""Drop 40: the stuck sash, and the ivy it is the only way onto.

Graphite unsticks the bedroom window, and the ivy outside becomes a way
between the Bedroom and the Courtyard. The content for all of it shipped
on 30 October and none of it has ever worked: `window_open` was written
through `thing_text` and nothing in the engine set it. Production says so
plainly - 29 attempts to climb either ivy, 12 players, 2 to 7 November,
every one refused `wrong_state`, and not one `window_open` row in
`player_states` on any guild.

**Why the refusal was right and still useless.** Both ivy exits keep
their only success line on a `window_open` row and leave `use` empty on
every other, which is how a writer says "not yet": `_state_refusal`
walks the held states, finds a refusal with no success, and turns the
move away. Correct, and unreachable past, because the state it waits for
could not be held.

**Why the state is per player.** The drawer's reason, sharper here: the
window's success line is the only place in the game the ivy is named as
a way down. A window opened server-wide would hand later players a route
whose discovery they never had - and `/look window` would describe an
open sash to somebody who had not touched it.

**Why `window_open` outranks `stairs_repaired`.** A player who has
opened the window holds both, and the courtyard ivy is written for each.
The other order would have them climb up to the window they had just
opened and be told it was shut.
"""

import pytest
from types import SimpleNamespace

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import resolve
import states
import world


THIS_DROP = 40

# Phrases quoted off `thing_text.tsv`, each one in the row it belongs to
# and in no other. Matching on "ivy" would pass on any of the four.
CLIMBED_DOWN = "swing a leg over the sill"
CLIMBED_UP = "haul yourself in over the sill"
WINDOW_SHUT = "the window between you is stuck shut"
NO_WAY_IN = "no way to open it from out here"
NOT_YET = "Not this way. Not yet."
OPENED = "slides up smoothly"


@pytest.fixture
async def house(db, monkeypatch):
    """The shipped content at drop 40, with the staircase repaired."""
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    await db.set_setting(GUILD_A, resolve.DROP_KEY, THIS_DROP)
    # **The fall off the ivy is turned off for this whole file.** It
    # arrived after these tests did and made two of them flaky at one in
    # ten: a fall replaces the climb-down line, so anything asserting
    # that line fails whenever the dice land. Nothing here is about
    # falling - `test_falling_off_the_ivy` is - and a mechanic that
    # quietly randomises an existing suite is worth switching off by name
    # rather than living with.
    await db.set_setting(GUILD_A, world.IVY_FALL_PERCENT, 0)
    await content_loader.load_content(content_module.load_files(), guild_ids=[GUILD_A])
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    await states.set_server_state(GUILD_A, world.HOUSE_UNLOCKED)
    await states.set_server_state(GUILD_A, world.STAIRS_UPPER)
    for who in (ALICE, BOB):
        await db.start_game(who, GUILD_A, "EN", await resolve.rooms_open_at_launch())
    monkeypatch.setattr(
        bot,
        "bot",
        SimpleNamespace(
            guilds=[guild], get_guild=lambda gid: guild if gid == GUILD_A else None
        ),
    )
    return db, guild, halloween, rooms


def place(house, room):
    _, _, halloween, rooms = house
    return next(t for t in halloween.threads if t.name == rooms[room])


async def run(house, command, arg, *, room, who=ALICE):
    db, guild, _, _ = house
    await db.update_current_room(who, GUILD_A, room)
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=place(house, room))
    await command.callback(interaction, arg)
    return "\n".join(text for text, _ in interaction.sent if text)


async def where_is(who=ALICE) -> str:
    return (await database.get_game_state(who, GUILD_A)).current_room


async def carry(db, thing_id, who=ALICE):
    """One of something in somebody's bag, however many times it is called.

    An insert would do for the first call and fail on the second: the
    powder is `consumed_on_use`, which leaves the row behind at zero
    rather than deleting it, so handing somebody a second twist of it
    means setting the count rather than adding a row.
    """
    from sqlalchemy import select, update

    async with db._require_session()() as session:
        existing = await session.scalar(
            select(database.PlayerInventory.count).where(
                database.PlayerInventory.guild_id == GUILD_A,
                database.PlayerInventory.user_id == who,
                database.PlayerInventory.thing_id == thing_id,
            )
        )
        if existing is None:
            session.add(
                database.PlayerInventory(
                    guild_id=GUILD_A, user_id=who, thing_id=thing_id, count=1
                )
            )
        else:
            await session.execute(
                update(database.PlayerInventory)
                .where(
                    database.PlayerInventory.guild_id == GUILD_A,
                    database.PlayerInventory.user_id == who,
                    database.PlayerInventory.thing_id == thing_id,
                )
                .values(count=1)
            )
        await session.commit()


async def repair_the_staircase():
    """Set once and never cleared, so the tests that want it ask for it.

    `states` has no `clear_server_state` - a state is something that has
    become true - so the fixture leaves it off and the two tests that
    need an upstairs a player could have reached set it themselves.
    """
    await states.set_server_state(GUILD_A, world.STAIRS_REPAIRED)


async def open_the_window(house, who=ALICE) -> str:
    """The way a player does it: powder in hand, then use the window."""
    await carry(house[0], world.GRAPHITE, who=who)
    return await run(house, bot.use, "window", room="BE", who=who)


# ---------------------------------------------------------------------------
# The words the prose uses are the words the parser takes


@pytest.mark.parametrize("word", ["graphite", "powder", "packet", "twist"])
async def test_the_powder_answers_to_every_word_the_house_calls_it(house, word):
    """Three names for one object, and now all three are typable.

    The copy calls it three things. The item list and the achievement
    call it graphite powder; its own `look` calls it "A twist of paper";
    and its `use` line, as of Kelsey's 7 November pass, says "You
    untwist the packet". Only the first was a word the parser accepted,
    so a player who read either of the others and typed it back was told
    the house had no such thing - the worst shape of refusal there is,
    because the game chose the word.

    Four aliases rather than two assertions, because the point is the
    set: whichever noun a future copy pass reaches for, the test that
    fails should be the one that says the parser has not heard of it.

    Safe to widen here and nowhere else. `_check_aliases` forbids two
    things in one room answering to the same word, and the powder is
    roomless - it exists only in a bag - so it is excluded from that
    check entirely, and nothing else in the files answers to "packet" or
    "twist". Checked both before adding them.

    **Used in the Kitchen on purpose.** The two rooms the powder is
    actually for both answer with somebody else's sentence on a first
    use - the Bedroom borrows the window's line and the Hallway the
    desk's, which is what `line_from` is for and what #170 fixed the
    repeat of. Either would have tested the handler rather than the
    parser, and the first draft of this test asserted the powder's line
    in the Hallway and read back the drawer's. The Kitchen has no
    handler, so what comes back is the powder's own row and nothing
    else.
    """
    await carry(house[0], world.GRAPHITE)

    reply = await run(house, bot.use, word, room="KI")

    assert "gets absolutely everywhere" in reply
    assert "untwist the packet" in reply


# ---------------------------------------------------------------------------
# Point 1: using the window sets the state


async def test_the_window_opens_and_says_so(house):
    reply = await open_the_window(house)

    assert OPENED in reply
    assert await states.has(GUILD_A, ALICE, world.WINDOW_OPEN)


async def test_without_powder_it_is_refused_and_nothing_is_set(house):
    reply = await run(house, bot.use, "window", room="BE")

    assert OPENED not in reply
    assert not await states.has(GUILD_A, ALICE, world.WINDOW_OPEN)


async def test_and_it_opens_for_one_player_only(house):
    """Per player, so a second player still has the discovery to make."""
    await open_the_window(house, who=ALICE)

    assert await states.has(GUILD_A, ALICE, world.WINDOW_OPEN)
    assert not await states.has(GUILD_A, BOB, world.WINDOW_OPEN)


async def test_the_window_then_describes_itself_as_open(house):
    await open_the_window(house)

    assert "pushed all the way up" in await run(
        house, bot.look, "window", room="BE"
    )


# ---------------------------------------------------------------------------
# Point 2: the ivy, both ends, before and after


async def test_the_ivy_down_is_refused_until_the_window_is_open(house):
    """The bug the playtester hit, from the bedroom side."""
    reply = await run(house, bot.use, "ivy", room="BE")

    assert WINDOW_SHUT in reply
    assert await where_is() == "BE"


async def test_and_then_climbs_down_to_the_courtyard(house):
    await open_the_window(house)

    reply = await run(house, bot.use, "ivy", room="BE")

    assert CLIMBED_DOWN in reply
    assert await where_is() == "CO"


async def test_the_ivy_up_is_refused_while_the_sash_is_shut(house):
    """And with the staircase repaired, which is the row that was unreachable.

    `stairs_repaired` is held here, so this is the line a player who has
    been upstairs gets - not the drop 30 one about the curtain of ivy
    peeling away. It is the proof that `window_open` leading
    `STATE_PRIORITY` did not cost the state below it its own row.
    """
    await repair_the_staircase()

    reply = await run(house, bot.use, "ivy", room="CO")

    assert NO_WAY_IN in reply
    assert NOT_YET not in reply
    assert await where_is() == "CO"


async def test_and_then_climbs_up_into_the_bedroom(house):
    await open_the_window(house)
    await run(house, bot.use, "ivy", room="BE")

    reply = await run(house, bot.use, "ivy", room="CO")

    assert CLIMBED_UP in reply
    assert await where_is() == "BE"


async def test_before_the_staircase_the_ivy_up_says_not_yet(house):
    """The drop 30 line still wins when it is the most specific one held."""
    reply = await run(house, bot.use, "ivy", room="CO")

    assert NOT_YET in reply
    assert NO_WAY_IN not in reply


async def test_go_is_gated_the_same_way_as_use(house):
    """One gate, not two: `_state_refusal` is read by both verbs."""
    assert WINDOW_SHUT in await run(house, bot.go, "ivy", room="BE")
    assert await where_is() == "BE"

    await open_the_window(house)

    await run(house, bot.go, "ivy", room="BE")
    assert await where_is() == "CO"


# ---------------------------------------------------------------------------
# The orderings, which are the part a future state could quietly break


def test_window_open_outranks_the_staircase_in_both_orderings():
    """Two orderings decide this, and they are not the same list.

    `in_priority_order` is what `_state_refusal` walks; `exit_state` is
    what both of an exit's texts resolve against. A state in one and not
    the other reads correctly in one verb and not the other, which is
    the shape of bug this pins.
    """
    held = {"stairs_repaired", "stairs_upper", "house_unlocked", "window_open"}

    assert states.in_priority_order(held)[0] == world.WINDOW_OPEN
    assert world.exit_state(held)[0] == world.WINDOW_OPEN


def test_the_staircase_states_stay_out_of_the_exit_list():
    """Deliberate, and worth a test because adding them looks like a fix.

    `exit_state` picks an exit's success line as well as its refusal, and
    the Entryway staircase has `stairs_upper` and `stairs_repaired` rows.
    Putting those states in here to shorten the courtyard ivy's path
    would change which line a repaired staircase prints on a climb -
    drop 20's content, and nobody's ask. The ivy's own refusal comes
    through `_state_refusal`, which does know them.
    """
    assert world.STAIRS_REPAIRED not in world.EXIT_STATES
    assert world.STAIRS_UPPER not in world.EXIT_STATES


def test_every_state_an_exit_is_written_for_is_one_the_engine_can_set():
    """The invariant `window_open` broke, scoped to where it bites.

    An exit's success row keyed on a state nobody can hold is a door
    nobody can open, and the content checker cannot see it: it asks
    whether a state name is *known*, and a text row declaring the state
    is what makes it known. So `window_open` sat in the files for a week,
    passing every check, with 29 refusals and no successes behind it.

    **Asked of exits only, on purpose.** A fixture written for a state
    that never arrives is a paragraph nobody reads, which is a waste; an
    exit written that way is a room nobody reaches. And the house has
    three other ways to set a state - a thing's own (`full`, `empty`),
    and the transient one an `Effect` names for a single line (`cat`,
    `guarded`, `reminded`) - none of which lives in a registry this
    could check. Widening it would need a hand-kept list of six
    unrelated names, which is the kind of list that is wrong by the time
    anybody reads it.
    """
    files = content_module.load_files()
    exits = {thing.thing_id for thing in files.things if thing.type == "exit"}
    settable = (
        states.SERVER_STATES
        | states.PLAYER_STATES
        | {world.HAS_KEY, resolve.DEFAULT_STATE}
    )

    unreachable = sorted(
        {
            (row.entity_id, row.state)
            for row in files.thing_text
            if row.entity_id in exits
            and row.state not in settable
            and not row.state.startswith(content_module.ROOM_STATE_PREFIX)
        }
    )

    assert unreachable == [], unreachable


# ---------------------------------------------------------------------------
# The other way in: `/use graphite powder`, which borrows the window's line


async def test_using_the_powder_in_the_bedroom_opens_the_window(house):
    """What a player types, and what cost one playtester a trip to the tin.

    `/use graphite powder` used to print the powder's own line - a puff
    on the palm, slippery, everywhere - spend the powder, and leave the
    sash shut. The resolver was never the problem: a source is merged
    with what it yields into one candidate, so the tin and the powder
    are one thing to the parser and a carried copy outranks the source.
    """
    await carry(house[0], world.GRAPHITE)

    reply = await run(house, bot.use, "graphite powder", room="BE")

    assert OPENED in reply
    assert "onto your palm" not in reply
    assert await states.has(GUILD_A, ALICE, world.WINDOW_OPEN)


async def test_and_the_ivy_is_climbable_straight_afterwards(house):
    """The whole point: the line a player reads is the one naming the ivy."""
    await carry(house[0], world.GRAPHITE)
    await run(house, bot.use, "graphite powder", room="BE")

    reply = await run(house, bot.use, "ivy", room="BE")

    assert CLIMBED_DOWN in reply
    assert await where_is() == "CO"


async def test_the_powder_elsewhere_still_says_its_own_line(house):
    """`line_from` is per room, so the powder keeps its own words.

    The Nursery is neither room the powder is the answer to, so nothing
    is redirected and nothing is set.
    """
    await carry(house[0], world.GRAPHITE)

    reply = await run(house, bot.use, "graphite powder", room="NU")

    assert "onto your palm" in reply
    assert OPENED not in reply
    assert not await states.has(GUILD_A, ALICE, world.WINDOW_OPEN)


async def test_the_drawer_upstairs_says_so_as_well(house):
    """The other room the powder is the answer to, closed the same way.

    The hallway opens on a bad smell, the smell points at the desk, the
    desk says its bottom drawer is swollen shut, and the manual on it
    says to apply powdered graphite. This is the end of that chain, and
    it used to be answered with the powder's palm line.
    """
    await carry(house[0], world.GRAPHITE)

    reply = await run(house, bot.use, "graphite powder", room="UH")

    assert "bottom drawer slides out easily now" in reply
    assert "onto your palm" not in reply
    assert await states.has(GUILD_A, ALICE, world.DRAWER_UNJAMMED)
    assert not await states.has(GUILD_A, ALICE, world.WINDOW_OPEN)


async def test_and_names_the_cans_which_nothing_else_does(house):
    """The reason it is worth a redirect rather than only reading better.

    `cat_food_stash_drawer` is a source `contained_in` the desk, so
    nothing ever lists it, and the desk's `drawer_unjammed` use row is
    the only sentence in the game that names those cans. Pinned, because
    a writer trimming that clause would silently strip the end off the
    puzzle.
    """
    await carry(house[0], world.GRAPHITE)

    reply = await run(house, bot.use, "graphite powder", room="UH")

    assert "expired" in reply or "expired cat food" in reply
    assert "cans" in reply


async def test_but_a_second_use_upstairs_is_just_powder_again(house):
    """Once the drawer is open, using powder on nothing in particular.

    The desk has no "again" row and does not need one: `line_from` falls
    away on a repeat and the powder says what it says everywhere else.
    """
    await carry(house[0], world.GRAPHITE)
    await run(house, bot.use, "graphite powder", room="UH")
    await carry(house[0], world.GRAPHITE)

    reply = await run(house, bot.use, "graphite powder", room="UH")

    assert "onto your palm" in reply
    assert "slides out easily now" not in reply


async def test_opening_it_twice_reads_as_a_second_look(house):
    """The bug the first cut of this shipped, pinned.

    `text_state` was pinned to `default` on every open, so a second
    `/use window` reprinted the whole opening paragraph and the
    `window_open` row - written for exactly this - could never be read.
    The sash is only unstuck once.
    """
    await open_the_window(house)

    reply = await run(house, bot.use, "window", room="BE")

    assert OPENED not in reply
    assert "lean out over the courtyard again" in reply


# ---------------------------------------------------------------------------
# A second puff at a sash already up, reported from a test server on
# 7 November: the powder answered as the window, for a use nobody made


async def test_a_second_puff_in_the_bedroom_is_just_powder_again(house):
    """What the playtester did, in the order they did it.

    They were in a bedroom whose window was already open, took the
    powder, used it, and were told "you lean out over the courtyard
    again" - the window's `window_open` row, which is a sentence about
    looking out of a window they had not touched this time.

    `line_from` was unconditional here, so the powder borrowed the
    window's words on every use rather than on the open. The drawer
    upstairs has always fallen away on a repeat; this is the window
    doing the same.
    """
    await open_the_window(house)
    await carry(house[0], world.GRAPHITE)

    reply = await run(house, bot.use, "graphite powder", room="BE")

    assert "gets absolutely everywhere" in reply
    assert "lean out over the courtyard again" not in reply
    assert OPENED not in reply


async def test_and_the_same_when_the_powder_was_what_opened_it(house):
    """The other route into the open state, which must read the same.

    Opening with `/use graphite powder` and then puffing again is the
    one case where both uses are the same command, so a fix keyed to
    anything but the state would show up here.
    """
    await carry(house[0], world.GRAPHITE)
    first = await run(house, bot.use, "graphite powder", room="BE")
    await carry(house[0], world.GRAPHITE)

    second = await run(house, bot.use, "graphite powder", room="BE")

    assert OPENED in first
    assert "gets absolutely everywhere" in second
    assert OPENED not in second


async def test_the_sash_stays_open_and_the_ivy_stays_climbable(house):
    """The thing a repeat must not quietly undo.

    `set_player_state` is idempotent and nothing here clears it, so the
    second puff changes the line and nothing else - checked through the
    exit rather than the state, because the exit is what a player would
    notice.
    """
    await open_the_window(house)
    await carry(house[0], world.GRAPHITE)
    await run(house, bot.use, "graphite powder", room="BE")

    assert await states.has(GUILD_A, ALICE, world.WINDOW_OPEN)
    reply = await run(house, bot.use, "ivy", room="BE")
    assert CLIMBED_DOWN in reply
    assert await where_is() == "CO"


async def test_an_open_sash_does_not_follow_the_player_out_of_the_room(house):
    """The repeat is keyed on the state, and the line is keyed on the room.

    Raised off the 7 November playtest, where the player's later puffs
    could not be placed: `interaction_log` has no room column and
    `detail` is null on every `graphite_powder` row, so which room a use
    happened in is not recoverable from it. Worth settling by test
    rather than by argument, since the two facts are easy to conflate -
    `window_open` is a player state that travels with them, and
    `line_from` is handed out per room by `after_use`.

    A player holding `window_open` who puffs powder in the Nursery gets
    the powder's own line, which is also what they got before the sash
    was ever opened. Nothing about carrying the state changes a room
    that was never the answer to the powder.
    """
    await open_the_window(house)
    await carry(house[0], world.GRAPHITE)

    reply = await run(house, bot.use, "graphite powder", room="NU")

    assert "gets absolutely everywhere" in reply
    assert "lean out over the courtyard again" not in reply
    assert OPENED not in reply
    assert await states.has(GUILD_A, ALICE, world.WINDOW_OPEN)


async def test_the_first_puff_still_carries_the_discovery(house):
    """The sentence the redirect exists for, pinned against over-reach.

    Dropping `line_from` one use too early would cost the only place in
    the game the ivy is named as a way down - so the fix is only right
    if a first puff still reads the window's opening paragraph.
    """
    await carry(house[0], world.GRAPHITE)

    reply = await run(house, bot.use, "graphite powder", room="BE")

    assert OPENED in reply
    assert "ivy" in reply
    assert "gets absolutely everywhere" not in reply
