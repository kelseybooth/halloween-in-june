"""The ten images: uploaded once, referenced forever, and used sparingly.

**Art fires on things that happen, never on a state that can flip.** An
achievement has a before and an after and an image marks it once; a
relationship score is a value that can go back the other way an hour later,
and an image that blinks on and off with it stops being a reward and becomes
a status bar.

The other half of that argument is where art must *not* appear, which is most
places. An image seen twice a minute stops being a reward and becomes
latency, and the entire value of this set is that each one marks something.
"""

import pytest

from conftest import ALICE, BOB, GUILD_A
from fake_discord import FakeChannel, FakeGuild, FakeInteraction, FakeMember, a_room_thread

import achievements
import bot
import content as content_module
import content_loader
import database
import resolve
import triggers


@pytest.fixture(autouse=True)
def quiet():
    bot.forget_public_pets()
    achievements.clear()
    triggers.register_all()
    yield
    bot.forget_public_pets()
    achievements.clear()


@pytest.fixture
async def house(db):
    halloween = FakeChannel(name="halloween")
    assets = FakeChannel(name="bot-testing")
    guild = FakeGuild(
        GUILD_A,
        name="Halloween in June",
        channels=[halloween, assets],
        members=[FakeMember(ALICE), FakeMember(BOB)],
    )
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    await content_loader.load_content(content_module.load_files())
    halloween.add_active(*[name for _, name in await resolve.all_rooms()])
    for who in (ALICE, BOB):
        await db.start_game(who, GUILD_A, "EN", await resolve.rooms_open_at_launch())
    await db.set_announcement_channel(GUILD_A, halloween.id)
    return db, guild, halloween, assets


def image_of(interaction, which: int = -1) -> str | None:
    """The image on one of the things sent, by file name.

    The last by default, which is what an achievement test wants. The
    pet tests pass 0 for the first, and have to: a pet can now award
    *Making First Contact*, which sends its own private line afterwards,
    so "the last thing sent" stopped meaning "the reply to the pet" on
    four pets in five.
    """
    if not interaction.sent:
        # `/take` and `/drop` say their one line to the room and send
        # the player nothing, so there is no embed to carry an image -
        # which is the answer these tests are looking for.
        return None
    embed = interaction.sent[which][1].get("embed")
    if embed is None or not embed.image:
        return None
    return embed.image.url.rsplit("/", 1)[-1]


def pet_image_of(interaction) -> str | None:
    """The image on the reply to the pet itself, whatever followed it."""
    return image_of(interaction, 0)


def text_of(interaction) -> str:
    text, kwargs = interaction.sent[-1]
    embed = kwargs.get("embed")
    return text or (embed.description if embed else "")


async def an_interaction(house, room="Entryway", who=ALICE):
    _, guild, _, _ = house
    return FakeInteraction(who, GUILD_A, guild=guild, channel=a_room_thread(room))


async def pet(house, who=ALICE):
    interaction = await an_interaction(house, who=who)
    await bot.pet.callback(interaction)
    return interaction


# --------------------------------------------------------------------------
# The file
# --------------------------------------------------------------------------


def test_ten_images_and_every_file_is_there():
    """The check worth having: an image is uploaded once at initialization,
    so a row pointing at a missing PNG fails inside an admin command on
    somebody else's server."""
    parsed = content_module.load_files()

    assert len(parsed.art) == 10
    for row in parsed.art:
        assert (content_module.ART_DIR / row.file).is_file(), row.art_id


def test_every_image_has_alt_text():
    """A black cat on a transparent background is invisible to a screen
    reader and nearly invisible in some Discord themes."""
    for row in content_module.load_files().art:
        assert row.alt.strip(), row.art_id


def test_a_missing_file_is_caught_at_load():
    from dataclasses import replace

    parsed = content_module.load_files()
    parsed.art = [replace(parsed.art[0], file="not_a_real_cat.png")]

    assert any("is not in artwork/" in p for p in content_module.validate(parsed))


def test_a_blank_alt_is_caught_at_load():
    from dataclasses import replace

    parsed = content_module.load_files()
    parsed.art = [replace(parsed.art[0], alt="")]

    assert any("no alt text" in p for p in content_module.validate(parsed))


def test_every_art_id_the_code_uses_exists_in_the_file():
    """A rename in the file would otherwise silently stop an image
    appearing, with nothing raising anywhere."""
    known = {row.art_id for row in content_module.load_files().art}
    used = set(bot.ART_FOR_ACHIEVEMENT.values()) | {
        bot.ART_FIRST_PET, bot.ART_CROWDING,
        bot.ART_DIAPER, bot.ART_AVATAR,
    }

    assert used <= known, sorted(used - known)


def test_every_achievement_the_art_map_names_exists():
    known = content_module.load_files().achievement_ids

    assert set(bot.ART_FOR_ACHIEVEMENT) <= known


# --------------------------------------------------------------------------
# Uploading
# --------------------------------------------------------------------------


async def test_upload_posts_every_file_once(house):
    _, guild, _, assets = house

    uploaded, problems = await bot.upload_art(guild, assets)

    assert uploaded == 10
    assert problems == []
    assert len(assets.uploaded) == 10


async def test_the_urls_are_recorded(house):
    db, guild, _, assets = house

    await bot.upload_art(guild, assets)

    assert len(await db.art_urls(GUILD_A)) == 10


async def test_running_it_again_uploads_nothing(house):
    """Upload once, reference by URL forever. Re-running initialization must
    not post ten more pictures."""
    _, guild, _, assets = house
    await bot.upload_art(guild, assets)

    uploaded, _ = await bot.upload_art(guild, assets)

    assert uploaded == 0
    assert len(assets.uploaded) == 10


async def test_a_failed_upload_is_reported_not_raised(house):
    """The house is worth building even if the art fails."""
    _, guild, _, assets = house
    assets.send_fails = True

    uploaded, problems = await bot.upload_art(guild, assets)

    assert uploaded == 0
    assert len(problems) == 10


# --------------------------------------------------------------------------
# Where the cat appears
# --------------------------------------------------------------------------


async def test_the_first_pet_of_all(house):
    _, guild, _, assets = house
    await bot.upload_art(guild, assets)

    assert pet_image_of(await pet(house)) == "black_cat_alert.png"


def standoffish(monkeypatch):
    """Force the mood roll. The crossing's image now depends on it, so a
    test that left it to the dice would pass six times in ten.

    Patches `choose_response` rather than the module's `random`, because the
    rng is a default argument and was bound at definition time - rebinding
    `bot.random` leaves the default pointing at the original module and the
    test runs on real dice while appearing not to.
    """
    reaction = bot.Reaction(bot.STANDOFFISH_RESPONSES[0], False, 0)
    monkeypatch.setattr(bot, "choose_response", lambda *a, **k: reaction)


async def test_and_nothing_until_the_crowding_nudge(house, monkeypatch):
    """Pets two to four earn nothing. The fifth is where petting starts
    costing score, and the over-the-shoulder look is what the standoffish
    nudge beside it says without words."""
    _, guild, _, assets = house
    await bot.upload_art(guild, assets)
    await pet(house)

    for n in range(2, 5):
        assert pet_image_of(await pet(house)) is None, n

    standoffish(monkeypatch)
    assert pet_image_of(await pet(house)) == "black_cat_suspicious.png"


async def test_and_nothing_on_a_friendly_crossing(house, monkeypatch):
    """She did not pull away, so the picture of her pulling away would say
    the opposite of the pet the player just earned. The warning on that roll
    is carried in words alone."""
    _, guild, _, assets = house
    await bot.upload_art(guild, assets)
    await pet(house)
    for _ in range(2, 5):
        await pet(house)

    reaction = bot.Reaction(bot.FRIENDLY_RESPONSES[0], True, 80)
    monkeypatch.setattr(bot, "choose_response", lambda *a, **k: reaction)

    assert pet_image_of(await pet(house)) is None


async def test_and_nothing_after_it_either(house):
    """The image rides the nudge, so it inherits once-per-window. An
    image seen twice a minute stops being a reward and becomes
    latency - which used to be a comment and is now the behaviour."""
    _, guild, _, assets = house
    await bot.upload_art(guild, assets)
    for _ in range(5):
        await pet(house)

    for n in range(6, 13):
        assert pet_image_of(await pet(house)) is None, n


async def test_the_nudge_image_rides_the_private_reply_only(house):
    """The nudge is between that player and the cat. It never appears in the
    room, and neither does its picture."""
    _, guild, halloween, assets = house
    await bot.upload_art(guild, assets)
    for _ in range(10):
        await pet(house)

    for thread in halloween.threads:
        assert all("eunoia" not in (line or "") for line in thread.posted)


async def test_an_achievement_image_rides_the_private_line(house):
    _, guild, halloween, assets = house
    await bot.upload_art(guild, assets)
    interaction = await an_interaction(house)

    await bot._announce(
        achievements.Earned(
            "follow_your_nose", "public", "Follow Your Nose", "Unstuck the drawer", ALICE
        ),
        interaction=interaction,
    )

    assert image_of(interaction) == "black_cat_sniffing.png"


async def test_the_public_line_carries_no_image(house):
    """It carries the name only. The description and the picture are both
    the earner's."""
    _, guild, halloween, assets = house
    await bot.upload_art(guild, assets)
    interaction = await an_interaction(house)

    await bot._announce(
        achievements.Earned(
            "follow_your_nose", "public", "Follow Your Nose", "Unstuck the drawer", ALICE
        ),
        interaction=interaction,
    )

    assert halloween.posted[-1] == f"Player {ALICE} earned **Follow Your Nose**"


async def test_a_group_achievement_puts_its_image_in_public(house):
    """There is no private message to put it in, so the public line is where
    both the description and the picture go."""
    _, guild, halloween, assets = house
    await bot.upload_art(guild, assets)

    await bot._announce(
        achievements.Earned(
            "the_feline_collection", "group", "The Feline Collection",
            "A LOT of cat food", None,
        ),
        guild=guild,
    )

    assert halloween.posted[-1] is None  # the text moved into the embed


async def test_the_first_dirty_diaper_a_player_looks_at(house):
    """Once ever, not once per diaper. Eight a day scatter through the
    house and the joke is only funny the first time."""
    db, guild, _, assets = house
    await bot.upload_art(guild, assets)
    insert = db._upsert_statement()
    async with db._require_session()() as session:
        await session.execute(
            db._add_to_room(insert, GUILD_A, "EN", db.LOOSE_IN_ROOM, "dirty_diaper", 3)
        )
        await session.commit()

    first = await an_interaction(house)
    await bot.look.callback(first, "diaper")
    second = await an_interaction(house)
    await bot.look.callback(second, "diaper")

    assert image_of(first) == "black_cat_sniffing.png"
    assert image_of(second) is None


async def test_the_diaper_is_per_player(house):
    db, guild, _, assets = house
    await bot.upload_art(guild, assets)
    insert = db._upsert_statement()
    async with db._require_session()() as session:
        await session.execute(
            db._add_to_room(insert, GUILD_A, "EN", db.LOOSE_IN_ROOM, "dirty_diaper", 3)
        )
        await session.commit()
    mine = await an_interaction(house)
    await bot.look.callback(mine, "diaper")

    theirs = await an_interaction(house, who=BOB)
    await bot.look.callback(theirs, "diaper")

    assert image_of(theirs) == "black_cat_sniffing.png"


# --------------------------------------------------------------------------
# Where it must not appear
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verb, arg",
    [
        ("look", None),
        ("look", "coat rack"),
        ("take", "cat food"),
        ("use", "xyzzy"),
        ("inventory", None),
    ],
)
async def test_no_image_on_the_ordinary_verbs(house, verb, arg):
    """An image seen twice a minute stops being a reward and becomes
    latency."""
    _, guild, _, assets = house
    await bot.upload_art(guild, assets)
    interaction = await an_interaction(house)

    args = () if arg is None else (arg,)
    await getattr(bot, verb).callback(interaction, *args)

    assert image_of(interaction) is None


async def test_no_image_on_a_movement_line(house):
    _, guild, halloween, assets = house
    await bot.upload_art(guild, assets)
    interaction = await an_interaction(house)

    await bot.use.callback(interaction, "wide doorway")

    for thread in halloween.threads:
        assert all("eunoia" not in (line or "") for line in thread.posted)


async def test_the_avatar_is_never_sent_as_an_image(house):
    """An avatar and a thumbnail of the same face six pixels apart looks
    like a mistake."""
    assert bot.ART_AVATAR not in bot.ART_FOR_ACHIEVEMENT.values()
    assert bot.ART_AVATAR not in (
        bot.ART_FIRST_PET, bot.ART_CROWDING, bot.ART_DIAPER,
    )


async def test_no_image_is_tied_to_the_relationship_meter(house):
    """`black_cat_content` and `black_cat_disdain` are the two endings of the
    relationship arc, and both fire on their achievement and nowhere else.
    A score that can swing back and forth would make them blink."""
    assert bot.ART_FOR_ACHIEVEMENT["making_friends"] == "black_cat_content"
    assert bot.ART_FOR_ACHIEVEMENT["trying_to_make_friends"] == "black_cat_disdain"
    assert "black_cat_content" not in (
        bot.ART_FIRST_PET, bot.ART_CROWDING,
    )


# --------------------------------------------------------------------------
# A picture is never load-bearing
# --------------------------------------------------------------------------


async def test_a_message_still_sends_with_nothing_uploaded(house):
    interaction = await an_interaction(house)

    await bot._announce(
        achievements.Earned(
            "follow_your_nose", "public", "Follow Your Nose", "Unstuck the drawer", ALICE
        ),
        interaction=interaction,
    )

    assert image_of(interaction) is None
    assert "You earned" in text_of(interaction)


async def test_a_broken_url_still_sends_the_message(house):
    db, guild, _, assets = house
    await bot.upload_art(guild, assets)
    await db.record_art(GUILD_A, "black_cat_sniffing", "")
    interaction = await an_interaction(house)

    await bot._announce(
        achievements.Earned(
            "follow_your_nose", "public", "Follow Your Nose", "Unstuck the drawer", ALICE
        ),
        interaction=interaction,
    )

    assert "You earned" in text_of(interaction)

# --------------------------------------------------------------------------
# How the art gets there at all
#
# It did not, for the whole of drops 0 and 1. `upload_art` had one
# caller, `/initialize-haunted-house`, which also builds nine room
# threads and is therefore registered only from drop 3 - so on a
# drop-0 server there was no way to run it, `server_art` stayed empty,
# and every message quietly took the degrade-to-text path. The
# playtesters reported seeing no pictures at all, which was exactly
# right.
#
# These are the tests that would have caught it: they drive the command
# an admin actually runs first, and then check a player can see the
# result.
# --------------------------------------------------------------------------


@pytest.fixture
async def fresh(db, registrations):
    """A server nobody has started, which is where `/start-game` runs.

    The `db` fixture opens the house in both test guilds so that the
    rest of the suite has nine rooms to assert against; this file needs
    the opposite, because the command under test refuses a server that
    is already running.
    """
    async with database._require_session()() as session:
        table = database.ConfigHistory.__table__
        await session.execute(
            table.delete().where(
                table.c.guild_id == GUILD_A, table.c.key == resolve.DROP_KEY
            )
        )
        await session.commit()
    await content_loader.load_content(content_module.load_files())

    halloween = FakeChannel(name="halloween")
    assets = FakeChannel(name="bot-testing")
    guild = FakeGuild(
        GUILD_A,
        name="Halloween in June",
        channels=[halloween, assets],
        members=[FakeMember(ALICE), FakeMember(BOB)],
    )
    for who in (ALICE, BOB):
        await db.ensure_user_exists(who, GUILD_A)
    return db, guild, halloween, assets


async def starting(db, guild, channel, art_channel=None):
    interaction = FakeInteraction(ALICE, GUILD_A, guild=guild, channel=channel)
    await bot.start_game.callback(interaction, channel, art_channel)
    return interaction


async def test_starting_the_game_uploads_the_art(fresh):
    db, guild, halloween, assets = fresh

    await starting(db, guild, halloween, assets)

    assert len(await db.art_urls(GUILD_A)) == 10
    assert len(assets.posted) == 10


async def test_a_first_pet_on_a_started_server_has_a_picture(fresh):
    """**The end-to-end one, and the whole point.** Everything else
    here could pass while a player still saw nothing."""
    db, guild, halloween, assets = fresh
    await starting(db, guild, halloween, assets)

    petting = FakeInteraction(BOB, GUILD_A, guild=guild, channel=halloween)
    await bot.pet.callback(petting)

    assert pet_image_of(petting) == "black_cat_alert.png"


async def test_without_an_art_channel_the_game_still_opens(fresh):
    """Optional, and the reply says what was skipped rather than
    leaving an admin to discover it from a playtester weeks later."""
    db, guild, halloween, _ = fresh

    interaction = await starting(db, guild, halloween)

    assert await resolve.current_drop(GUILD_A) == 0
    assert await db.art_urls(GUILD_A) == {}
    assert "no art channel given" in interaction.sent[-1][0]


async def test_art_that_will_not_upload_does_not_stop_the_game(
    fresh, monkeypatch
):
    """The same reasoning that makes every message degrade to text: a
    picture is never load-bearing."""
    db, guild, halloween, assets = fresh

    async def explode(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(bot, "upload_art", explode)
    interaction = await starting(db, guild, halloween, assets)

    assert await resolve.current_drop(GUILD_A) == 0
    assert "did not upload" in interaction.sent[-1][0]


async def test_running_it_twice_does_not_upload_twice(fresh):
    """`/start-game` is idempotent, and the upload already skips what a
    server has - so a second run is free either way."""
    db, guild, halloween, assets = fresh
    await starting(db, guild, halloween, assets)

    await starting(db, guild, halloween, assets)

    assert len(assets.posted) == 10


def test_no_image_is_named_after_her():
    """The player learns her name from the collar tag in the Bedroom,
    and `upload_art` posts each file under its own name - so the
    attachment URL on every embed used to read `eunoia_alert.png`,
    three drops before the collar exists."""
    for row in content_module.load_files().art:
        assert "eunoia" not in row.art_id, row.art_id
        assert "eunoia" not in row.file, row.file

