"""The config, which is now a history of itself.

**The table is the live config rather than a journal beside one**, and
that is the whole design: a journal drifts from the value it records,
silently, and the drift is found months later while analysing
something else. So what is tested here is mostly the invariant - one
open window per key, never two and never none - plus the two places a
window is closed without another opening after it.

Why it matters at all: every number the interaction log will carry is
uninterpretable without this. *Players pet forty times a day* means
nothing unless you know what a pet was worth that week.
"""

import pytest
from sqlalchemy import func, select

from conftest import ALICE, GUILD_A, GUILD_B

import content as content_module
import database
import resolve


async def windows(guild_id, key):
    """Every window for one key, oldest first, as (value, closed?)."""
    async with database._require_session()() as session:
        rows = await session.execute(
            select(
                database.ConfigHistory.value,
                database.ConfigHistory.effective_to,
            )
            .where(
                database.ConfigHistory.guild_id == guild_id,
                database.ConfigHistory.key == key,
            )
            .order_by(database.ConfigHistory.id)
        )
    return [(value, closed is not None) for value, closed in rows]


async def live(guild_id, key):
    async with database._require_session()() as session:
        return await session.scalar(
            select(func.count())
            .select_from(database.ConfigHistory)
            .where(
                database.ConfigHistory.guild_id == guild_id,
                database.ConfigHistory.key == key,
                database.ConfigHistory.effective_to.is_(None),
            )
        )


# --------------------------------------------------------------------------
# One open window
# --------------------------------------------------------------------------


async def test_setting_a_value_opens_a_window(db):
    await db.set_setting(GUILD_A, "planks_required", 4)

    assert await windows(GUILD_A, "planks_required") == [("4", False)]
    assert await db.get_setting(GUILD_A, "planks_required") == 4


async def test_changing_it_closes_the_old_one(db):
    await db.set_setting(GUILD_A, "planks_required", 4)
    await db.set_setting(GUILD_A, "planks_required", 9)

    assert await windows(GUILD_A, "planks_required") == [("4", True), ("9", False)]
    assert await live(GUILD_A, "planks_required") == 1


async def test_exactly_one_window_is_open_however_often_it_changes(db):
    """**The invariant the table rests on.** Two open rows and which
    one wins depends on row order; none and the setting silently
    reverts to its default."""
    for value in range(1, 8):
        await db.set_setting(GUILD_A, "planks_required", value)

    assert await live(GUILD_A, "planks_required") == 1
    assert await db.get_setting(GUILD_A, "planks_required") == 7


async def test_setting_it_to_what_it_already_was_still_records(db):
    """Not waste. *Somebody set the decay rate on the 14th* is worth
    knowing even when they set it to what it already was, and a row
    costs nothing."""
    await db.set_setting(GUILD_A, "planks_required", 4)
    await db.set_setting(GUILD_A, "planks_required", 4)

    assert await windows(GUILD_A, "planks_required") == [("4", True), ("4", False)]


async def test_an_unset_key_reads_its_default(db):
    assert await windows(GUILD_A, "bottles_per_day") == []
    assert await db.get_setting(GUILD_A, "bottles_per_day") == 8


async def test_servers_do_not_share_a_history(db):
    await db.set_setting(GUILD_A, "planks_required", 4)

    assert await windows(GUILD_B, "planks_required") == []
    assert await db.get_setting(GUILD_B, "planks_required") == 10


# --------------------------------------------------------------------------
# Closing without reopening
# --------------------------------------------------------------------------


async def test_clearing_closes_the_window_and_keeps_the_history(db):
    """Unsetting is itself a tuning decision and is dated like any
    other. A window that closed with nothing after it reads as "from
    here, the default", which is the truth."""
    await db.set_setting(GUILD_A, "planks_required", 4)

    await db.clear_setting(GUILD_A, "planks_required")

    assert await windows(GUILD_A, "planks_required") == [("4", True)]
    assert await db.get_setting(GUILD_A, "planks_required") == 10


async def test_clearing_something_never_set_does_nothing(db):
    await db.clear_setting(GUILD_A, "planks_required")

    assert await windows(GUILD_A, "planks_required") == []


# --------------------------------------------------------------------------
# Everything that used to live in `server_config`
# --------------------------------------------------------------------------


async def test_the_drop_pointer_is_config_like_everything_else(db):
    """It was the one key that read raw rather than through a default,
    and it still is - `None` means the game has not started and 0 is a
    real drop. Written through `set_setting` rather than
    `set_current_drop`, which validates against a calendar this
    fixture has not loaded."""
    await db.set_setting(GUILD_A, resolve.DROP_KEY, 1)
    await db.set_setting(GUILD_A, resolve.DROP_KEY, 2)

    assert (await windows(GUILD_A, resolve.DROP_KEY))[-1:] == [("2", False)]
    assert await resolve.current_drop(GUILD_A) == 2
    assert await live(GUILD_A, resolve.DROP_KEY) == 1


async def test_the_announcement_channel_too(db):
    await db.set_announcement_channel(GUILD_A, 1234)
    await db.set_announcement_channel(GUILD_A, 5678)

    assert await db.announcement_channel(GUILD_A) == 5678
    assert await live(GUILD_A, db.CONFIG_ANNOUNCE_CHANNEL) == 1


async def test_moving_the_channel_leaves_a_trail(db):
    """Not what the table was built for, and worth having anyway: when
    a server moved the game is a question somebody will ask."""
    await db.set_announcement_channel(GUILD_A, 1234)
    await db.set_announcement_channel(GUILD_A, 5678)

    assert await windows(GUILD_A, db.CONFIG_ANNOUNCE_CHANNEL) == [
        ("1234", True),
        ("5678", False),
    ]


# --------------------------------------------------------------------------
# The content version
# --------------------------------------------------------------------------


async def test_the_content_version_is_recorded_once_per_change(db):
    """**Only on a change**, unlike every other write here. This one
    runs on every boot rather than when somebody decides something, so
    a server restarting twice an hour would otherwise bury the one
    question the row exists to answer."""
    assert await db.record_content_version(GUILD_A, "files:abc")
    assert not await db.record_content_version(GUILD_A, "files:abc")
    assert await db.record_content_version(GUILD_A, "files:def")

    assert await windows(GUILD_A, db.CONFIG_CONTENT_VERSION) == [
        ("files:abc", True),
        ("files:def", False),
    ]


def test_the_version_changes_when_a_file_does(tmp_path):
    """A digest of the files, so a content reload that did not come
    from a deploy is still dated - which is the case a commit hash
    alone would miss."""
    (tmp_path / "a.tsv").write_text("key\tvalue\n", encoding="utf-8")
    before = content_module.version(tmp_path)

    (tmp_path / "a.tsv").write_text("key\tother\n", encoding="utf-8")

    assert content_module.version(tmp_path) != before
    assert content_module.version(tmp_path).startswith("files:")


def test_a_deploy_names_its_commit(tmp_path, monkeypatch):
    """Railway sets this, and a hash names a diff somebody can read."""
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "0123456789abcdef")

    assert content_module.version(tmp_path) == "git:0123456789ab"


# --------------------------------------------------------------------------
# The migration out of the old table
# --------------------------------------------------------------------------


async def test_an_old_database_keeps_its_settings(db):
    """**The upgrade path.** A database written before the history
    existed has its values in `server_config`, and a boot that did not
    carry them over would silently return every server to its
    defaults - the drop pointer included, which is the whole game.
    """
    async with database._require_session()() as session:
        await session.execute(
            database.ConfigHistory.__table__.delete()
        )
        session.add(
            database.ServerConfig(
                guild_id=GUILD_A, key="planks_required", value="6"
            )
        )
        await session.commit()

    async with database._engine.begin() as conn:
        await database._migrate_config_to_history(conn)

    assert await windows(GUILD_A, "planks_required") == [("6", False)]
    assert await db.get_setting(GUILD_A, "planks_required") == 6


async def test_it_does_not_run_twice(db):
    """Guarded on the history being empty, so a second boot cannot
    reopen a window somebody has since closed."""
    async with database._require_session()() as session:
        await session.execute(database.ConfigHistory.__table__.delete())
        session.add(
            database.ServerConfig(
                guild_id=GUILD_A, key="planks_required", value="6"
            )
        )
        await session.commit()

    for _ in range(3):
        async with database._engine.begin() as conn:
            await database._migrate_config_to_history(conn)

    assert await windows(GUILD_A, "planks_required") == [("6", False)]
