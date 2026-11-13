"""The spirit board: one letter a day, one name a day, and no more.

Two halves, tested two ways. **The spelling is pure and tested as a
table**, because it is a list of rules written down in prose and the
only way to know they all hold is to check each one - and because the
cost of getting one wrong is a clue that is wrong all day for one
player, which nobody can tell from bad luck.

**Everything else is driven through the buttons.** The board's rules
are almost all about what does *not* happen - a turn not spent, a row
not written, an award not given - and a test that called
`ask_the_board` directly would prove the rule and nothing about whether
the button reaches it. `UserSelect.values` is a read-only property
backed by `_values`, the same seam the room picker uses, so a chosen
suspect is a member object dropped into that list.
"""

from datetime import timedelta

import pytest

from conftest import ALICE, BOB, GUILD_A, LAST_DROP
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember

import bot
import content as content_module
import content_loader
import database
import ghosts
import resolve
import triggers

# Somebody in the server who has never entered the house. The member
# picker lists them, which is the whole reason the board has a line for
# them.
NOBODY = 100000000000000009


# --------------------------------------------------------------------------
# What the board can spell
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "display_name, username, expected",
    [
        # The design's four worked examples, verbatim.
        ("Kate (Ollie's mom)", "kate_s.92", "KATE"),
        ("\U0001f319 Jess | she/her", "jess_h", "JESS"),
        ("Mary-Beth", "marybeth", "MARYBETH"),
        ("O'Brien", "obrien", "OBRIEN"),
        # An accent folds; a curly apostrophe joins like a straight one.
        ("Élodie", "elodie", "ELODIE"),
        ("O’Brien", "obrien", "OBRIEN"),
        # The stroke inside the codepoint, which NFKD does not undo.
        ("Bjørn", "bjorn", "BJORN"),
        # Longer than the board can count, cut at eight.
        ("Maximilianus", "max", "MAXIMILI"),
        # Nothing to spell in the display name, so the username.
        ("\U0001f380", "kate_s.92", "KATE"),
        ("中文", "hiro", "HIRO"),
        ("", "kate", "KATE"),
        # Neither spells. A real answer, not an error.
        ("\U0001f380", "\U0001f380", ""),
        (None, None, ""),
    ],
)
def test_the_first_word_is_what_the_board_spells(display_name, username, expected):
    assert ghosts.letters_of(display_name, username) == expected


def test_the_count_is_written_out_for_every_place_there_can_be():
    """One phrase per place, and no place without a phrase.

    `MAX_PLACES` and the phrases are two statements of the same number,
    and the planchette circles once per place - so a ninth letter with
    no ninth phrase would be an `IndexError` in front of a player.
    """
    assert [ghosts.circles(n) for n in range(1, ghosts.MAX_PLACES + 1)] == [
        "once",
        "twice",
        "three times",
        "four times",
        "five times",
        "six times",
        "seven times",
        "eight times",
    ]


def test_no_name_is_ever_spelled_past_the_cap():
    assert len(ghosts.letters_of("a" * 40, "b" * 40)) == ghosts.MAX_PLACES


# --------------------------------------------------------------------------
# Which place each player gets
# --------------------------------------------------------------------------


def test_the_place_is_always_one_of_the_places_there_are():
    """Which is what makes `letters[place - 1]` safe.

    Every player on a 200-player server, against a name of every
    length the board can spell.
    """
    day = database.pacific_today()
    for places in range(1, ghosts.MAX_PLACES + 1):
        for offset in range(200):
            place = ghosts.place_for(day, GUILD_A, ALICE + offset, places)
            assert 1 <= place <= places


def test_the_same_player_gets_the_same_place_all_day():
    """**The whole reason it is a hash.** Pressing the button again
    after a restart must not hand out a different letter, and this is
    cheaper than a row per player per day whose only job is to repeat
    itself."""
    day = database.pacific_today()
    first = ghosts.place_for(day, GUILD_A, ALICE, 8)

    assert ghosts.place_for(day, GUILD_A, ALICE, 8) == first


def test_the_place_moves_with_the_day_and_with_the_player():
    """Otherwise the same two players would compare the same two
    letters every day, and the board would be one clue wide."""
    day = database.pacific_today()
    mine = [ghosts.place_for(day, GUILD_A, ALICE + n, 8) for n in range(40)]
    tomorrow = [
        ghosts.place_for(day + timedelta(days=1), GUILD_A, ALICE + n, 8)
        for n in range(40)
    ]

    assert len(set(mine)) > 1
    assert mine != tomorrow


# --------------------------------------------------------------------------
# The house
# --------------------------------------------------------------------------


@pytest.fixture
async def library(db, monkeypatch):
    """Drop 50, Alice and Bob standing in the Secret Library."""
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A,
        channels=[halloween],
        members=[FakeMember(ALICE), FakeMember(BOB), FakeMember(NOBODY)],
    )
    triggers.register_all()
    await content_loader.load_content(content_module.load_files(), guild_ids=[GUILD_A])
    await database.set_setting(GUILD_A, resolve.DROP_KEY, LAST_DROP)
    rooms = {room_id: name for room_id, name in await resolve.all_rooms()}
    halloween.add_active(*[name for rid, name in rooms.items() if rid != "CH"])
    await database.set_announcement_channel(GUILD_A, halloween.id)
    for who in (ALICE, BOB):
        await database.start_game(who, GUILD_A, ghosts.LIBRARY, [ghosts.LIBRARY])
    return db, guild, halloween, rooms


async def a_ghost(display_name="Kate", username="kate_s.92", who=ALICE):
    """Today's row, written straight rather than through the pick."""
    today = await database.server_today(GUILD_A)
    await database.record_daily_ghost(
        GUILD_A,
        today,
        user_id=who,
        display_name=display_name,
        username=username,
        eligible=3,
    )
    return today


async def a_haunting(who=ALICE, room_id="LI"):
    """One haunting, which is what *Name the ghost* waits for."""
    await ghosts.record_haunting(GUILD_A, who, [room_id], "boo")


def the_view(interaction):
    for _, kwargs in interaction.sent:
        if kwargs.get("view") is not None:
            return kwargs["view"]
    for kwargs in interaction.edited:
        if kwargs.get("view") is not None:
            return kwargs["view"]
    return None


def answered(interaction):
    """Whatever the player was told, however it was delivered."""
    lines = [text for text, _ in interaction.sent if text]
    lines += [
        str(kwargs.get("content"))
        for kwargs in interaction.edited
        if kwargs.get("content")
    ]
    return "\n".join(lines)


async def open_the_board(library, who=BOB):
    _, guild, _, _ = library
    interaction = FakeInteraction(who, GUILD_A, guild=guild)
    await bot.use.callback(interaction, "spirit board")
    return interaction


async def press(library, label, who=BOB):
    """Press one of the board's two buttons and return its interaction."""
    _, guild, _, _ = library
    menu = the_view(await open_the_board(library, who))
    button = next(item for item in menu.children if item.label == label)
    pressed = FakeInteraction(who, GUILD_A, guild=guild)
    await button.callback(pressed)
    return pressed


async def accuse(library, suspect_id, who=BOB):
    """The whole flow: open the board, press Name, choose a suspect."""
    _, guild, _, _ = library
    pressed = await press(library, "Name the ghost", who)
    picker = the_view(pressed)
    if picker is None:
        return pressed
    select = picker.children[0]
    select._values = [FakeMember(suspect_id)]
    chose = FakeInteraction(who, GUILD_A, guild=guild)
    await select.callback(chose)
    return chose


async def earned(user_id=BOB):
    return set(await database.player_achievements_of(GUILD_A, user_id))


async def logged(action):
    from sqlalchemy import select

    async with database._require_session()() as session:
        rows = await session.scalars(
            select(database.InteractionLog)
            .where(database.InteractionLog.action == action)
            .order_by(database.InteractionLog.id)
        )
        return list(rows.all())


async def said(key, **tokens):
    import phrasing

    return await phrasing.default_say(key, **tokens)


# --------------------------------------------------------------------------
# Opening it
# --------------------------------------------------------------------------


async def test_using_the_board_offers_two_buttons(library):
    menu = the_view(await open_the_board(library))

    assert menu is not None
    assert [item.label for item in menu.children] == [
        "Ask the board",
        "Name the ghost",
    ]


async def test_opening_the_board_is_not_using_it(library):
    """Neither turn is spent and nothing is written, which is what keeps
    both limits meaning *you got an answer*."""
    await a_ghost()
    await open_the_board(library)

    assert await logged(database.BOARD_ASK) == []
    assert await logged(database.BOARD_GUESS) == []
    assert await database.carried_of(BOB, GUILD_A, ghosts.SPIRIT_BOARD) == 0


async def test_the_board_has_nothing_left_to_say_in_its_own_text(library):
    """Change 15: the *isn't ready for you yet* line is gone.

    The code branches on the board before any `use` text is read, so a
    line left in the cell would never be printed - and would be the
    only record anywhere claiming the board does not work. The `look`
    line carries GOODBYE now, which is the corner the planchette rests
    on when the house is quiet: a player who has only ever seen a day
    with a ghost still knows the word is there.
    """
    import phrasing

    assert not await phrasing.say(GUILD_A, ghosts.SPIRIT_BOARD, "use")
    assert "GOODBYE" in await phrasing.say(GUILD_A, ghosts.SPIRIT_BOARD, "look")


# --------------------------------------------------------------------------
# Ask the board
# --------------------------------------------------------------------------


async def test_a_quiet_day_rests_on_goodbye(library):
    """No row at all, which is what a server that has not picked looks
    like to a player."""
    pressed = await press(library, "Ask the board")

    assert await said(ghosts.NO_GHOST) in answered(pressed)
    assert await logged(database.BOARD_ASK) == []


async def test_a_day_that_picked_nobody_rests_on_goodbye_too(library):
    today = await database.server_today(GUILD_A)
    await database.record_daily_ghost(
        GUILD_A, today, user_id=None, display_name=None, username=None, eligible=1
    )

    pressed = await press(library, "Ask the board")

    assert await said(ghosts.NO_GHOST) in answered(pressed)


async def test_the_clue_is_the_letter_in_the_place_the_hash_picked(library):
    """The wiring between the two halves, and the off-by-one in it.

    `place_for` counts from one and a string is indexed from zero, so a
    board reading `letters[place]` would be one letter along all day -
    which no player could tell from a board working.
    """
    today = await a_ghost(display_name="Kate")
    place = ghosts.place_for(today, GUILD_A, BOB, 4)

    pressed = await press(library, "Ask the board")

    assert await said(
        ghosts.ASK_CLUE, count=ghosts.circles(place), letter="KATE"[place - 1]
    ) in answered(pressed)


async def test_the_clue_comes_from_the_name_stored_at_the_pick(library):
    """Not from the member's name now. Renaming yourself mid-day would
    otherwise scramble every clue already given out."""
    await a_ghost(display_name="Zebedee")

    pressed = await press(library, "Ask the board")
    out = answered(pressed)

    assert any("slides to " + letter + " and stops" in out for letter in "ZEBEDE")


async def test_the_ghost_asking_gets_the_joke_line(library):
    await a_ghost()

    pressed = await press(library, "Ask the board", who=ALICE)

    assert await said(ghosts.ASK_GHOST) in answered(pressed)


async def test_a_name_that_does_not_spell_wont_settle(library):
    await a_ghost(display_name="\U0001f380", username="\U0001f380")

    pressed = await press(library, "Ask the board")

    assert await said(ghosts.ASK_NO_LETTERS) in answered(pressed)


async def test_asking_twice_in_a_day_is_refused(library):
    await a_ghost()
    await press(library, "Ask the board")

    pressed = await press(library, "Ask the board")

    assert await said(ghosts.ASK_ALREADY) in answered(pressed)
    assert len(await logged(database.BOARD_ASK)) == 1


async def test_the_limit_is_per_player(library):
    """Two players comparing notes is the game. A limit that counted the
    server would make the second one to ask the loser of a race."""
    await a_ghost()
    await press(library, "Ask the board")

    pressed = await press(library, "Ask the board", who=ALICE)

    assert await said(ghosts.ASK_ALREADY) not in answered(pressed)


async def test_a_clue_is_written_down_with_what_it_gave(library):
    """So the hash can be checked against real servers rather than
    trusted: a letter nobody ever gets is a bug only the rows show."""
    await a_ghost()
    await press(library, "Ask the board")
    rows = await logged(database.BOARD_ASK)

    assert len(rows) == 1
    assert rows[0].user_id == BOB
    assert rows[0].outcome == database.SUCCESS
    assert "letter=" in rows[0].detail


async def test_asking_the_board_earns_nothing(library):
    """**The guard on `_used(SPIRIT_BOARD)`.** *Ghostbuster* has no
    predicate of its own, so the only thing keeping it off the other
    button is that asking fires no hook at all."""
    await a_ghost()

    await press(library, "Ask the board")

    assert await earned() == set()


# --------------------------------------------------------------------------
# Name the ghost
# --------------------------------------------------------------------------


async def test_naming_before_the_house_stirs_is_refused(library):
    """And the picker never opens, so the player has not chosen
    anybody. The design is explicit that the turn survives."""
    await a_ghost()

    pressed = await press(library, "Name the ghost")

    assert await said(ghosts.NAME_NOT_YET) in answered(pressed)
    assert the_view(pressed) is None


async def test_the_turn_survives_the_early_try(library):
    await a_ghost()
    await press(library, "Name the ghost")
    await a_haunting()

    chose = await accuse(library, ALICE)

    assert await said(ghosts.NAME_YES) in answered(chose)


async def test_naming_the_ghost_gets_yes_and_the_award(library):
    await a_ghost()
    await a_haunting()

    chose = await accuse(library, ALICE)

    assert await said(ghosts.NAME_YES) in answered(chose)
    assert "ghostbuster" in await earned()


async def test_a_wrong_guess_gets_no_and_no_award(library):
    """Bob guesses Nobody, who has at least entered the house."""
    await database.start_game(NOBODY, GUILD_A, "LI", ["LI"])
    await a_ghost()
    await a_haunting()

    chose = await accuse(library, NOBODY)

    assert await said(ghosts.NAME_NO) in answered(chose)
    assert await earned() == set()


async def test_picking_yourself_costs_nothing(library):
    await a_ghost()
    await a_haunting()

    await accuse(library, BOB)
    chose = await accuse(library, ALICE)

    assert await said(ghosts.NAME_YES) in answered(chose)


async def test_picking_somebody_who_never_entered_costs_nothing(library):
    """Discord's picker lists everybody in the server and cannot be told
    to leave them out, which is exactly why it is free."""
    await a_ghost()
    await a_haunting()

    first = await accuse(library, NOBODY)
    chose = await accuse(library, ALICE)

    assert await said(ghosts.NAME_NON_PLAYER) in answered(first)
    assert await said(ghosts.NAME_YES) in answered(chose)


async def test_guessing_twice_in_a_day_is_refused(library):
    await database.start_game(NOBODY, GUILD_A, "LI", ["LI"])
    await a_ghost()
    await a_haunting()
    await accuse(library, NOBODY)

    pressed = await press(library, "Name the ghost")

    assert await said(ghosts.NAME_ALREADY) in answered(pressed)
    assert len(await logged(database.BOARD_GUESS)) == 1


async def test_a_right_guess_does_not_end_the_ghosts_day(library):
    """Alice keeps the sheet and Alice stays the ghost: the award is for
    working it out, not for getting there first."""
    today = await a_ghost()
    await a_haunting()
    await accuse(library, ALICE)

    row = await database.daily_ghost(GUILD_A, today)
    assert row.user_id == ALICE


async def test_a_guess_is_written_down_with_who_was_named(library):
    await database.start_game(NOBODY, GUILD_A, "LI", ["LI"])
    await a_ghost()
    await a_haunting()

    await accuse(library, NOBODY)
    rows = await logged(database.BOARD_GUESS)

    assert len(rows) == 1
    assert rows[0].user_id == BOB
    assert rows[0].outcome == database.REFUSED
    assert str(NOBODY) in rows[0].detail


async def test_a_right_guess_is_the_row_the_reveal_will_count(library):
    """`outcome` rather than a word in `detail`, so the changeover's
    count of who named the ghost is one filter and not a LIKE."""
    await a_ghost()
    await a_haunting()

    await accuse(library, ALICE)
    rows = await logged(database.BOARD_GUESS)

    assert [row.outcome for row in rows] == [database.SUCCESS]


async def test_naming_on_a_quiet_day_rests_on_goodbye(library):
    pressed = await press(library, "Name the ghost")

    assert await said(ghosts.NO_GHOST) in answered(pressed)


# --------------------------------------------------------------------------
# The two turns are separate
# --------------------------------------------------------------------------


async def test_the_clue_and_the_guess_are_separate_turns(library):
    """A letter is evidence and a guess is a commitment. Spending one
    must leave the other, or a player who asked first could never
    guess."""
    await a_ghost()
    await a_haunting()
    await press(library, "Ask the board")

    chose = await accuse(library, ALICE)

    assert await said(ghosts.NAME_YES) in answered(chose)


async def test_a_guess_does_not_spend_the_clue(library):
    await database.start_game(NOBODY, GUILD_A, "LI", ["LI"])
    await a_ghost()
    await a_haunting()
    await accuse(library, NOBODY)

    pressed = await press(library, "Ask the board")

    assert await said(ghosts.ASK_ALREADY) not in answered(pressed)


async def test_yesterdays_turn_is_not_todays(library):
    """The limits are per Pacific day, counted from the log, so a day
    rolling over hands both turns back."""
    today = await database.server_today(GUILD_A)
    await a_ghost()
    await press(library, "Ask the board")

    assert await database.player_actions_on(
        GUILD_A, BOB, today, database.BOARD_ASK
    ) == 1
    assert await database.player_actions_on(
        GUILD_A, BOB, today - timedelta(days=1), database.BOARD_ASK
    ) == 0
