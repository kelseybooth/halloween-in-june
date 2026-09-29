"""The cat, and the two messages a pet now sends.

Eunoia is functionally omnipresent: `room_id = ALL`, the same as `alexa`, so
she is in every room and `/pet` needs no location check. Nothing about her is
stored per room — the relationship meter is per player and that is the whole
model.

`/pet` is one command and two messages. The private one carries the blurb and
**no pet count**: two hundred is better as a surprise than as a countdown,
and a visible counter turns petting a cat into filling a progress bar. The
public one carries the event, so the command introduces itself to everybody
in the room.
"""

from datetime import timedelta

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember, a_room_thread

import bot
import content as content_module
import content_loader
import database
import resolve


@pytest.fixture(autouse=True)
def quiet_windows():
    bot.forget_public_pets()
    yield
    bot.forget_public_pets()


@pytest.fixture
async def house(db):
    halloween = FakeChannel(name="halloween")
    guild = FakeGuild(
        GUILD_A, channels=[halloween], members=[FakeMember(ALICE), FakeMember(BOB)]
    )
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    await content_loader.load_content(content_module.load_files())
    rooms = {rid: name for rid, name in await resolve.all_rooms()}
    halloween.add_active(*rooms.values())
    for who in (ALICE, BOB):
        await db.start_game(who, GUILD_A, "EN", await resolve.rooms_open_at_launch())
    threads = {t.name: t for t in halloween.threads}
    return db, guild, halloween, rooms, threads


async def act(house, fn, arg, room=None, who=ALICE, channel=None):
    db, guild, halloween, rooms, threads = house
    if room:
        await db.update_current_room(who, GUILD_A, room)
    where = channel if channel is not None else threads[rooms[room]]
    interaction = FakeInteraction(who, GUILD_A, guild=guild, channel=where)
    args = () if arg is None else (arg,)
    await fn.callback(interaction, *args)
    return interaction


def replies(interaction) -> str:
    return "\n".join(text for text, _ in interaction.sent if text)


# --------------------------------------------------------------------------
# She is everywhere
# --------------------------------------------------------------------------

EVERY_ROOM = ["EN", "DI", "KI", "CO", "LI", "SE", "UH", "BE", "NU"]


@pytest.mark.parametrize("room", EVERY_ROOM)
async def test_the_cat_can_be_looked_at_in_every_room(house, room):
    """`room_id = ALL`. Tested in all nine rather than one, because the
    failure mode is a room that quietly has no cat in it."""
    reply = replies(await act(house, bot.look, "cat", room))

    assert "sleek black cat" in reply


@pytest.mark.parametrize("word", ["cat", "black cat", "kitty", "kitten", "eunoia"])
async def test_every_name_for_her_resolves(house, word):
    assert "sleek black cat" in replies(await act(house, bot.look, word, "NU"))


async def test_she_is_never_listed_as_a_thing_in_the_room(house):
    """A fixture, so she never appears in `Also here:` — she is not a thing
    you find, she is a thing that is there."""
    reply = replies(await act(house, bot.look, None, "EN"))

    assert "cat" not in reply.split("Also here")[-1] if "Also here" in reply else True


async def test_taking_her_returns_her_own_refusal(house):
    assert "in the way of cats" in replies(await act(house, bot.take, "cat", "EN"))


async def test_using_her_hands_the_player_the_right_verb(house):
    """The tutorial no longer teaches `/pet`, so this is how somebody who
    types the verb they know finds the one they want."""
    reply = replies(await act(house, bot.use, "cat", "EN"))

    assert "try petting her" in reply
    assert "turn the cat over" not in reply


async def test_a_thing_with_a_refusal_and_no_success_refuses(house):
    """The rule that makes the line above land. Five rows have that shape
    today and four are exits, which refuse through their own gates."""
    parsed = content_module.load_files()
    text = {
        (r.entity_id, r.state): r.text for r in parsed.thing_text
    }
    shaped = {
        t.thing_id
        for t in parsed.things
        if text.get((t.thing_id, "default"), {}).get("use_fail")
        and not text.get((t.thing_id, "default"), {}).get("use")
    }

    # The cat, the four gated exits, and the five cans - whose `use` text
    # already read as a failed attempt ("looking for a pull-tab") and moved
    # to `use_fail` when feeding the cat came to need a can opener.
    assert shaped == {
        "eunoia", "EH", "HE", "LS", "SL",
        "cat_food_chicken", "cat_food_salmon", "cat_food_tuna",
        "cat_food_expired", "cat_food_gourmet",
    }


async def test_no_text_of_hers_names_her(house):
    """The player learns her name from the collar tag in the Bedroom. A
    `look` that opened with "Eunoia" would spend that on the first room."""
    parsed = content_module.load_files()
    hers = [r for r in parsed.thing_text if r.entity_id == "eunoia"]

    for row in hers:
        for column, value in row.text.items():
            assert "eunoia" not in (value or "").lower(), (column, value)


async def test_her_prose_never_mentions_furniture(house):
    """She reads the same in the Courtyard as in the Nursery, so nothing she
    says can assume a floor, a rug, a chair or a window."""
    parsed = content_module.load_files()
    hers = " ".join(
        v for r in parsed.thing_text if r.entity_id == "eunoia"
        for v in r.text.values() if v
    ).lower()

    for word in ("floor", "rug", "carpet", "chair", "sofa", "window", "doorway"):
        assert word not in hers, word


# --------------------------------------------------------------------------
# The private half
# --------------------------------------------------------------------------


async def test_the_private_reply_carries_the_blurb(house):
    interaction = await act(house, bot.pet, None, "KI")

    assert replies(interaction) in "\n".join(bot.PET_RESPONSES) or any(
        blurb in replies(interaction) for blurb in bot.PET_RESPONSES
    )


async def test_the_private_reply_is_ephemeral(house):
    interaction = await act(house, bot.pet, None, "KI")

    assert interaction.was_private


async def test_no_pet_count_appears_anywhere_in_it(house):
    """Progress toward *Making Friends* lives in `/stats` and nowhere else."""
    for _ in range(3):
        interaction = await act(house, bot.pet, None, "KI")

    reply = replies(interaction)
    assert "Total pets" not in reply
    assert "3" not in reply


async def test_the_tenth_pet_in_ten_minutes_nudges(house):
    for n in range(1, 11):
        interaction = await act(house, bot.pet, None, "KI")
        if n < 10:
            assert "give the cat some space" not in replies(interaction), n

    assert "give the cat some space" in replies(interaction)


async def test_and_so_does_the_eleventh(house):
    for _ in range(11):
        interaction = await act(house, bot.pet, None, "KI")

    assert "give the cat some space" in replies(interaction)


async def test_the_nudge_never_appears_in_public(house):
    """It is between that player and the cat. Broadcasting it would make it
    a scolding."""
    _, _, _, rooms, threads = house
    for _ in range(11):
        await act(house, bot.pet, None, "KI")

    assert not any(
        "give the cat some space" in line for line in threads["Kitchen"].posted
    )


async def test_crowding_does_not_stop_the_pet_counting(house):
    """A hint, not a limit. Two hundred pets still earn *Making Friends*."""
    db, *_ = house
    for _ in range(12):
        await act(house, bot.pet, None, "KI")

    assert await db.get_pet_count(ALICE, GUILD_A) == 12


# --------------------------------------------------------------------------
# The public half
# --------------------------------------------------------------------------


async def test_one_public_line_posts_where_the_command_was_run(house):
    _, _, _, _, threads = house

    await act(house, bot.pet, None, "KI")

    assert len(threads["Kitchen"].posted) == 1
    assert "pets the cat" in threads["Kitchen"].posted[0]


async def test_the_public_line_names_the_player_and_pings_nobody(house):
    _, _, _, _, threads = house

    await act(house, bot.pet, None, "KI")

    line = threads["Kitchen"].posted[0]
    assert "Player" in line
    assert f"<@{ALICE}>" not in line


async def test_the_branch_reads_the_meter_after_the_pet(house):
    """Above zero reads "seems to like it", zero or below "does not seem
    pleased" — the boundary *Making Friends* already splits on, so the game
    has one rule instead of two."""
    db, _, _, _, threads = house
    await db.adjust_relationship(ALICE, GUILD_A, -database.RELATIONSHIP_START - 50)

    await act(house, bot.pet, None, "KI")

    assert "does not seem pleased" in threads["Kitchen"].posted[0]


async def test_the_second_line_reads_continues(house):
    _, _, _, _, threads = house

    await act(house, bot.pet, None, "KI")
    await act(house, bot.pet, None, "KI")

    assert threads["Kitchen"].posted[1].endswith("continues to pet the cat.")


async def test_the_third_posts_nothing_while_its_reply_still_fires(house):
    _, _, _, _, threads = house

    for _ in range(3):
        interaction = await act(house, bot.pet, None, "KI")

    assert len(threads["Kitchen"].posted) == 2
    assert replies(interaction)


async def test_the_window_reopens_after_thirty_minutes(house):
    """Anchored to the first line, not rolling, so a player can never be
    surprised by which one they get."""
    _, _, _, _, threads = house
    for _ in range(3):
        await act(house, bot.pet, None, "KI")

    # Wind the window back rather than waiting half an hour.
    for key, (opened, spent) in list(bot._PUBLIC_PETS.items()):
        bot._PUBLIC_PETS[key] = (opened - timedelta(minutes=31), spent)
    await act(house, bot.pet, None, "KI")

    assert len(threads["Kitchen"].posted) == 3
    assert "continues" not in threads["Kitchen"].posted[2]


async def test_each_room_is_its_own_bucket(house):
    """One person moving between rooms gets two in each, because those are
    different audiences."""
    _, _, _, _, threads = house
    for _ in range(3):
        await act(house, bot.pet, None, "KI")

    await act(house, bot.pet, None, "LI")

    assert len(threads["Living Room"].posted) == 1


async def test_two_players_in_one_room_each_get_their_own_two(house):
    _, _, _, _, threads = house
    for _ in range(3):
        await act(house, bot.pet, None, "KI")

    await act(house, bot.pet, None, "KI", who=BOB)

    assert len(threads["Kitchen"].posted) == 3


async def test_the_halloween_channel_is_its_own_bucket(house):
    """A tenth bucket alongside the nine rooms."""
    _, _, halloween, _, _ = house
    for _ in range(3):
        await act(house, bot.pet, None, "KI")

    await act(house, bot.pet, None, channel=halloween)

    assert len(halloween.posted) == 1


async def test_petting_works_in_the_halloween_channel(house):
    """Which is what makes the discovery argument work: an admin can pet the
    cat there on day one, before anybody has run `/enter`."""
    db, guild, halloween, _, _ = house

    interaction = await act(house, bot.pet, None, channel=halloween)

    assert replies(interaction)
    assert halloween.posted


async def test_a_member_with_no_player_row_can_pet(house):
    """v1 behaviour, unchanged: the row is created, the meter starts, and
    the pet counts."""
    db, guild, halloween, _, _ = house
    stranger = 999
    await db.ensure_user_exists(stranger, GUILD_A)

    interaction = FakeInteraction(stranger, GUILD_A, guild=guild, channel=halloween)
    await bot.pet.callback(interaction)

    assert await db.get_pet_count(stranger, GUILD_A) == 1
    assert await db.get_game_state(stranger, GUILD_A) is None


@pytest.mark.parametrize("room", EVERY_ROOM)
async def test_petting_resolves_in_every_room(house, room):
    """No location check anywhere, Secret Library included."""
    interaction = await act(house, bot.pet, None, room)

    assert replies(interaction)


# --------------------------------------------------------------------------
# The strings
# --------------------------------------------------------------------------


def test_the_public_strings_live_in_defaults():
    defaults = content_module.load_files().defaults

    for key in (
        "pet.public.positive",
        "pet.public.negative",
        "pet.public.continues",
        "pet.crowding",
    ):
        assert defaults.get(key), key


def test_they_use_the_token_that_already_exists():
    """`{player}`, the one `move.depart` already substitutes. A second
    spelling for the same thing renders as literal text."""
    defaults = content_module.load_files().defaults

    for key in ("pet.public.positive", "pet.public.negative", "pet.public.continues"):
        assert "{player}" in defaults[key], key
