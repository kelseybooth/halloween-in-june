"""Database layer for the cat petting bot.

Backend is chosen from DATABASE_URL:
  - unset            -> local SQLite file (zero setup, for local development)
  - postgres[ql]://  -> PostgreSQL via asyncpg (what Railway provides)

The same model and queries run on both, so local behaviour matches production.

Everything is scoped per Discord server. A player who meets the bot in two
servers has two independent cats and two independent haunted-house positions:
every table is keyed by (user_id, guild_id), and every query filters on both.

Cohorts were removed in phase 2a. Two columns survive them - see
PlayerGameState.room_version_assignment and Thing.cohort - because dropping a
column is not something the additive startup migration can do. Nothing reads
either one.
"""

import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from collections.abc import Iterable
from typing import NamedTuple
from zoneinfo import ZoneInfo

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    case,
    delete,
    func,
    inspect,
    or_,
    select,
    text,
    update,
)
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

log = logging.getLogger(__name__)

# Local fallback so `python bot.py` works before any database is provisioned.
DEFAULT_SQLITE_URL = "sqlite+aiosqlite:///./catbot.db"

# How far back a pet still counts as "recent" when weighting the cat's mood.
RECENT_PET_WINDOW = timedelta(minutes=10)

# The vocabulary of `interaction_log`. Spelled out as constants because
# every one of them is a value some later query will have to match
# exactly, and a typo in a string literal is a row that silently never
# joins rather than an error anybody sees.
PLAYER = "player"
SYSTEM = "system"

SUCCESS = "success"
REFUSED = "refused"

# What a player did. `look` is looking around; looking *at* something
# that is not there is `unknown_noun`, which is a different question and
# the more useful of the two.
PET = "pet"
USE = "use"
TAKE = "take"
DROP = "drop"
LOOK = "look"
# Going somewhere, including out to the road and back. One row per move and
# not also a `use`, even though `/use front door` is how most of them are
# typed: two rows for one event is how a count ends up doubled. What the
# achievements read is `thing_uses`, which the move still writes.
MOVE = "move"
# Offering the cat a can, and **not also a `use`** for the same reason a
# move is not: two rows for one event is how a count ends up doubled.
# Every attempt writes one, successful or not, because the question the
# column answers is how often players reach for her and what stops them
# - and the four refusals are most of the interesting half.
FEED = "feed"
# A world verb typed somewhere the player's body is not. Its own action
# rather than a `reason` on each verb, because the question it answers is
# about the interface rather than about the game: how often does anybody
# try to play from the wrong window, and which verb were they holding.
WRONG_PLACE = "wrong_place"
# The bot taking somebody out of a room thread they do not belong in.
# `actor` is the system: nobody asked for it, which is the whole point.
THREAD_REMOVED = "thread_removed"
HINT = "hint"
UNKNOWN_NOUN = "unknown_noun"
RECOVERY = "recovery"
# A guess at the day's craving, made by reacting rather than by a command.
# `outcome` is the usual success or refused - a win against everything
# else - and which rung of the ladder it earned is in `detail`, because
# the ladder is five-valued and the column that answers "did it work" is
# two-valued everywhere else in this table.
CRAVING_GUESS = "craving_guess"
# The bed giving up a brass key, and somebody turning one in the front
# door. The first is a system row - nobody asked for the key, the bed
# produced it - and `detail` says whether it was the server's first or a
# spare, which is the question the day's interval exists to answer.
# **The first is also load-bearing rather than only telemetry**: it is
# what `world` reads to date the last key.
KEY_DROPPED = "key_dropped"
UNLOCK = "unlock"

# Why a refusal refused. Open-ended on purpose - a new gate adds a new
# reason here rather than reusing an approximate one, because the whole
# value of the column is that it distinguishes.
NO_GAME_YET = "no_game"
WRONG_ROOM = "wrong_room"
AMBIGUOUS = "ambiguous"
ABSENT = "absent"
UNKNOWN = "unknown"
REQUIRES_MISSING = "requires_missing"
NOT_CARRIED = "not_carried"
COOLDOWN = "cooldown"
ONCE_A_DAY = "once_a_day"
NOT_TAKEABLE = "not_takeable"
# The toy's own refusal, which is not a gate but the mechanic working:
# the cat declines, the ramp advances, and the next offer is likelier.
RAMP = "ramp"
NOT_HELD = "not_held"
FULL_HANDS = "full_hands"
# `/go` at something that is not a way out. Its own refusal is what the
# player reads, which is what keeps a disguised exit disguised - so the
# only place the difference is visible at all is this column.
NOT_AN_EXIT = "not_an_exit"
# A use whose whole effect has already happened, and cannot happen
# twice. The brass key in an unlocked door is the only one: the thing
# still works, the player still holds it, and there is nothing left for
# it to do.
ALREADY_DONE = "already_done"

# The four ways a feed can be turned down, and they are four rather than
# two because the questions behind them are independent: is she hungry,
# and is the kit to hand. `not_hungry` is the mechanic working;
# `wrong_time_and_place` is that same answer given to somebody who is
# also nowhere near her bowl. `no_bowl` and `no_opener` are the hungry
# half, split because they point at different drops - the bowl is in the
# Entryway from drop 10 and the opener is in the kitchen at 30, so which
# one players hit says which room they are stuck outside of.
NOT_HUNGRY = "not_hungry"
WRONG_TIME_AND_PLACE = "wrong_time_and_place"
NO_BOWL = "no_bowl"
NO_OPENER = "no_opener"

# A real zone, not a fixed offset, so midnight stays midnight across DST.
PACIFIC = ZoneInfo("America/Los_Angeles")

# The floor, and there is deliberately no ceiling. A grudge bottoms out -
# a cat that already wants nothing to do with you cannot want less - but
# affection is the thing the game is about, and *Favorite Human* asks for
# 250. A clamp at 100 would have made that unreachable while looking like
# a balance number rather than a bug.
RELATIONSHIP_MIN = -100

# Not the clamp any more: the score at which the cat is as fond of you as
# the game has a name for. *Cat's Best Friend* reads this and nothing
# else does.
PERFECT_RELATIONSHIP = 100

# Where a brand-new player starts: nowhere. The cat has no opinion of
# somebody she has never met, and every point after this one was earned.
# Starting above neutral made the first several days a slow loss of
# something the player was given rather than a gain of something they
# did, and the drift pulled them to 0 whether they played or not.
#
# Referenced by both the model default and the ALTER in
# _add_missing_columns; keep them reading from here so the two cannot
# disagree.
RELATIONSHIP_START = 0

# Grudges soften overnight. A score at or below RECOVERY_THRESHOLD
# climbs by RECOVERY_STEP each Pacific day, never past 0.
#
# **This used to be half of a two-sided drift**, and the other half -
# affection fading by ten a day for anybody who stayed away - is gone
# rather than dormant. A score that falls while somebody is absent
# punishes exactly the players a staged release is hardest on. A score
# that climbs back toward neutral does the opposite, and matters more
# the larger the single swings get: a later drop puts a can in the
# house worth -75, and without this a player who opens it has no route
# back except petting at poor odds.
#
# **It applies whether or not they played that day**, unlike the drift
# it came from. Making recovery conditional on absence would mean the
# player who keeps showing up is the one who stays in the hole
# longest, which is backwards.
RECOVERY_THRESHOLD = -20
RECOVERY_STEP = 20

# Ceiling on catch-up work after a long outage.
MAX_CATCHUP_DAYS = 30

# Written into the vestigial room_version_assignment column, which is NOT NULL
# and which nothing reads. See PlayerGameState.
VESTIGIAL_ROOM_VERSION = "A"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


class StartupError(RuntimeError):
    """A problem the bot should stop and report rather than run through."""


class SchemaOutdatedError(StartupError):
    """The database predates per-server scoping and must be rebuilt."""


class MissingDatabaseError(StartupError):
    """Running in production with no DATABASE_URL configured."""


class Base(DeclarativeBase):
    pass


class PetResult(NamedTuple):
    """Outcome of a single pet: lifetime total, plus recent pets before this one."""

    total: int
    recent: int
    # The `interaction_log` row this pet opened, for the caller to
    # finish once the roll has decided what the pet was worth. None
    # only when the row could not be written, which must not stop the
    # pet.
    log_id: int | None = None


class GameState(NamedTuple):
    """A player's position in one server's haunted house."""

    user_id: int
    guild_id: int
    current_room: str
    rooms_unlocked: list[str]


class RecoveryChange(NamedTuple):
    """One player's climb back toward neutral on one night, in one server."""

    user_id: int
    guild_id: int
    before: int
    after: int
    day: date


def _utcnow() -> datetime:
    """Naive UTC timestamp.

    Stored without tzinfo so comparisons behave identically on PostgreSQL and
    SQLite - the SQLite driver returns naive datetimes regardless of what was
    written, which would otherwise make aware/naive comparisons raise.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def pacific_today() -> date:
    """Today's calendar date in Pacific time, by the real clock.

    Almost nothing should call this. The game's clock is
    `server_today`, which is this shifted by whatever `/qa-clock` has
    set on that server - see the note on `CLOCK_KEY`.
    """
    return datetime.now(PACIFIC).date()


# How many days this server's clock is shifted by. Deliberately not in
# `CONFIG_KEYS`: `/admin_config` is for numbers an admin tunes mid-game
# and refuses anything below 1, and this one is a QA lever that wants
# zero and negatives.
#
# **One offset moves every dated behaviour at once**, which is the whole
# argument for routing the clock through one pair of functions: the
# nightly drift, the bed's cooldown, the ten-minute pet window and the
# date-gated achievements all read it, so a tester can age a server a
# week with one command instead of waiting one.
CLOCK_KEY = "clock_offset_days"


async def clock_offset(guild_id: int) -> int:
    """How many days ahead this server's clock is running."""
    raw = await get_config_raw(guild_id, CLOCK_KEY)
    if raw is None:
        return 0
    try:
        return int(raw)
    except ValueError:
        log.warning(
            "server_config %s is %r in guild %s, which is not a number of "
            "days; using the real clock",
            CLOCK_KEY,
            raw,
            guild_id,
        )
        return 0


async def server_now(guild_id: int) -> datetime:
    """This server's idea of now, as a naive UTC timestamp.

    Every time-of-day read in the game goes through here or through
    `server_today`. Nothing else calls the system clock - which is an
    hour's work once and a week of hunting later, and is what makes a
    single `clock_offset_days` test every dated behaviour at the same
    time.
    """
    return _utcnow() + timedelta(days=await clock_offset(guild_id))


async def server_today(guild_id: int) -> date:
    """This server's calendar date, in Pacific time.

    Shifted in whole days, so a server running a week ahead is at the
    same time of day a week later rather than at some hour nobody
    chose. Pacific midnight is still the boundary.
    """
    offset = await clock_offset(guild_id)
    return (datetime.now(PACIFIC) + timedelta(days=offset)).date()


def pacific_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """Half-open [start, end) UTC bounds of one Pacific calendar day.

    Built by combining local midnights rather than adding 24 hours, so DST
    transition days (23 or 25 hours long) still map to exactly one day.
    """
    start_local = datetime.combine(day, time.min, tzinfo=PACIFIC)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=PACIFIC)
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )


class User(Base):
    """One row per (player, server): each server has its own cat.

    A player's pet count and relationship in one server say nothing about the
    same player in another. The composite key is what enforces that.
    """

    __tablename__ = "users"

    # Discord snowflake IDs exceed 32 bits, so BIGINT is required.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    pet_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # `default` is what actually sets a new player's score, since rows are only
    # ever created by the upserts below; `server_default` writes the same value
    # into the CREATE TABLE DDL for databases built from scratch.
    relationship: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=RELATIONSHIP_START,
        server_default=text(str(RELATIONSHIP_START)),
    )
    # Last Pacific day the nightly job was evaluated for this row. Lets the
    # bot catch up on days it was offline without double-applying any of
    # them. Named for the drift it was written for; the mechanic it serves
    # now only ever raises a score.
    last_decay_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # The last Pacific day this player touched the cat in this server, by
    # any means and whether or not it worked.
    #
    # **The recovery no longer reads it** - grudges soften whether or not
    # somebody played that day. It stays because the leaderboard does read
    # it: a player with no recorded interaction is not on the board, which
    # is what keeps day one from being a wall of zeroes.
    last_cat_interaction_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # How willing the cat is to play with this player right now, as the
    # number of refusals since their last success. The chance of a
    # successful play is 25 percentage points per rung - 0, 25, 50, 75,
    # 100 - so the fifth attempt always lands and a run of five refusals
    # is impossible.
    #
    # **Per player and per server, not per toy.** It means her
    # willingness to play with *you*; the toys are interchangeable keys.
    # Keyed per toy, carrying a second one would hand out a second fresh
    # ramp and a way around the cooldown.
    toy_ramp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # When this player may next play. Minutes rather than the hours
    # `use_cooldown_hours` deals in, and hers rather than the toy's, for
    # the same reason the ramp is.
    toy_cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    # How many successful plays this player has had today, and which
    # day that is.
    #
    # **A count of plays, not a total of points.** What a play pays
    # falls away with each one - the curve is in `world.play_value` -
    # so the only thing that has to be remembered is how far down it
    # the player already is. Storing the points instead would make the
    # same number unrecoverable the first time the curve is retuned.
    #
    # **Successes only.** A refusal is not a play; the ramp is what
    # notices those, and counting them here would have a player paid
    # less for the cat having said no to them.
    #
    # Dated rather than reset by a job. A nightly sweep over every
    # player to zero a counter is work the read can do for nothing: a
    # stamp from an earlier day simply reads as no plays yet today.
    toy_plays_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    toy_plays_today: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class InteractionLog(Base):
    """One row per thing that happened, kept for tuning rather than for play.

    Nothing in the game reads this to decide anything, with a single
    exception: the mood roll counts a player's recent `pet` rows, which
    is what `pet_events` existed for. That table is gone, absorbed here
    - two logs of the same event can disagree with each other, and this
    one answers the narrower question with a filter on `action`.

    **Written generously and pruned never.** A few dozen people playing
    a cat bot produce nothing worth partitioning, so the only expensive
    mistake available is the column nobody wrote: rows can be thrown
    away afterwards, and a field that was never recorded cannot be
    recovered.
    """

    __tablename__ = "interaction_log"
    __table_args__ = (
        # The mood roll: one player's recent rows of one action.
        Index(
            "ix_interaction_log_player",
            "guild_id", "user_id", "action", "created_at",
        ),
        # Everything analytical: one server's rows in order.
        Index("ix_interaction_log_server", "guild_id", "created_at"),
    )

    # Monotonic, so two rows inside the same second still order
    # correctly - which is not pedantry here, because the timestamp is
    # `server_now` and a QA clock offset can move it backwards between
    # one row and the next.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Null on a system row. The nightly recovery acts on a whole server
    # at once and belongs to no player.
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actor: Mapped[str] = mapped_column(String(16), nullable=False, default=PLAYER)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    thing_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Only on a refusal, and it is the half that says where to fix the
    # game: a count of refusals tells you players are bouncing off
    # something, and this tells you off what.
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # **Null rather than zero where it is unknown**, because zero is a
    # real answer here - a refusal moves nothing - and a row backfilled
    # from `pet_events` cannot say which of the two it was.
    relationship_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The score once this row applied, so a row is self-describing
    # rather than a figure you reconstruct by summing deltas correctly
    # from the beginning of time. The score *before* is this minus the
    # delta, which is exactly what `pet_events.relationship_at_pet`
    # recorded.
    score_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Joinable from the config history, stored anyway: it is the most
    # useful slicer there is and it costs an integer.
    drop: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The hint rung for `hint`, the typed noun for `unknown_noun`.
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PlayerGameState(Base):
    """One row per (player, server) that has started the haunted house (Phase 2).

    Separate from `users`, which counts petting: a player can pet the cat without
    entering the house. The foreign key means the reverse is not true, so game
    start must ensure a `users` row exists before inserting here.
    """

    __tablename__ = "player_game_state"
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "guild_id"], ["users.id", "users.guild_id"]),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    # Vestigial. Cohorts are gone: every player now sees the same nine rooms, and
    # nothing reads this. It stays because the column is NOT NULL and the startup
    # migration can only add columns, never alter or drop one - and on SQLite a
    # primary key cannot be altered in place at all. A constant is written on
    # insert purely to satisfy the constraint. Drop the column in a later cleanup
    # once the new schema has settled.
    room_version_assignment: Mapped[str] = mapped_column(
        String(1), nullable=False, default=VESTIGIAL_ROOM_VERSION
    )
    current_room: Mapped[str] = mapped_column(String(50), nullable=False)
    # JSON rather than a PostgreSQL array: arrays have no SQLite equivalent, and
    # SQLite is what runs locally whenever DATABASE_URL is unset.
    rooms_unlocked: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Room(Base):
    """One row per (server, room): the writer-supplied description of a room.

    The room *layout* lives in code (house_utils.ROOMS and NAVIGATION_GRAPH);
    this table only holds per-server flavour text, so writers can change it
    without a deploy. A missing or empty description shows a generic fallback.
    """

    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("guild_id", "room_name"),)

    room_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    room_name: Mapped[str] = mapped_column(String(50), nullable=False)
    room_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Thing(Base):
    """One row per *instance* of a thing in a server's house.

    Five cans of cat food in the Kitchen are five rows sharing a thing_name.
    `room_id` is where the instance was placed.

    Two properties shape what players can do with it:

    - `can_take`: whether /take (a later phase) may move it into an inventory.
      Exits and scenery cannot be taken.
    - `removed_on_take`: whether taking it removes it from the room. True for a
      unique item like a secret note - once one player has it, nobody else can -
      and False for something a player merely gets a copy of, which stays in the
      room for everyone.

    Room visibility follows from these: an instance is hidden from its room only
    when it is `removed_on_take` AND someone holds it. An instance a player
    merely has a copy of is still there for the next player.
    """

    __tablename__ = "things"
    __table_args__ = (Index("ix_things_guild_room", "guild_id", "room_id"),)

    thing_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    room_id: Mapped[int] = mapped_column(Integer, ForeignKey("rooms.room_id"), nullable=False)
    thing_name: Mapped[str] = mapped_column(String(100), nullable=False)
    thing_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Vestigial, like room_version_assignment above. Already nullable, so nothing
    # writes it and it simply stays NULL. Dropped in a later cleanup.
    cohort: Mapped[str | None] = mapped_column(String(1), nullable=True)
    can_take: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    removed_on_take: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class InventoryItem(Base):
    """A specific thing instance held by a player in a server.

    Keyed by the instance, so five cans held are five rows. The unique constraint
    stops the same instance being held twice; the composite foreign key means a
    player must have a `users` row for that server, as with player_game_state.
    """

    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("user_id", "guild_id", "thing_id"),
        ForeignKeyConstraint(["user_id", "guild_id"], ["users.id", "users.guild_id"]),
    )

    inventory_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    thing_id: Mapped[int] = mapped_column(Integer, ForeignKey("things.thing_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# --------------------------------------------------------------------------
# Content, loaded from the files in `creative content/`
#
# Global, not keyed by guild: the house is the same house in every server. These
# tables are never mutated at runtime, which is what makes a reload safe - the
# loader can replace them wholesale without touching anything a player did.
#
# The three tables above this comment - rooms, things, inventory - are the
# per-guild content tables these replace. They are left in place and unread, as
# the cohort columns were: dropping a table is not something the additive startup
# migration can do. Nothing writes them once the loader lands.
# --------------------------------------------------------------------------

# Written into room_contents.container_id for a thing lying loose in a room.
# An empty string rather than NULL, because it is part of a composite primary key
# and NULLs in a key compare as distinct from each other on some backends.
LOOSE_IN_ROOM = ""

# server_config key holding the Pacific date a guild first initialized its house.
# Restock day numbers count from it, so it is per-server rather than global.
CONFIG_INITIALIZED_ON = "initialized_on"

# The channel the house was initialized in, where achievement names are posted.
# Stored as an id rather than looked up by name at announce time, so a rename
# does not silently stop the announcements - and so there is no second setting
# to keep in sync with where the room threads actually live.
CONFIG_ANNOUNCE_CHANNEL = "announce_channel_id"


class RoomType(Base):
    """One row per room in the house, from rooms.tsv."""

    __tablename__ = "room_types"

    room_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_at_launch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ThingType(Base):
    """One row per thing, from things.tsv.

    A *type*, not an instance: five baby bottles in a room are one row here and a
    count of five in room_contents. See "Why types" in the phase 2b work order -
    the finite world is six copies across six things, while sources feed fourteen
    objects with no cap, so per-copy rows would grow without bound to model the
    part of the world that does not need them.
    """

    __tablename__ = "thing_types"

    thing_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # JSON rather than a delimited string: the files use pipes, but a list is what
    # the resolver wants, and JSON is already how rooms_unlocked is stored.
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    room_id: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # NULL means `many` - a shared pool with no count, which only lumber uses.
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    takeable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    droppable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Used up when used. The only thing in the game that destroys an object,
    # which is why content.py refuses it on anything a player cannot get
    # another of.
    consumed_on_use: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    # Usable once per Pacific day, which resets for everybody at the
    # same instant - the boundary the midnight job already keeps. The
    # hours column cannot say this: a rolling window drifts later every
    # day for anyone who uses the thing at their first opportunity.
    use_cooldown_daily: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    cross_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_per_player: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires: Mapped[str | None] = mapped_column(String(64), nullable=True)
    present_when: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transforms_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transform_room: Mapped[str | None] = mapped_column(String(8), nullable=True)
    yields: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination_room_id: Mapped[str | None] = mapped_column(String(8), nullable=True)
    contained_in: Mapped[str | None] = mapped_column(String(64), nullable=True)
    use_cooldown_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    since_drop: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RoomText(Base):
    """A room's description for one state, at one drop - in fragments.

    Most rooms are one fragment and read exactly as they always did. The
    channel is six, because its description arrives in two stages: three
    sentences for a player who has just turned up, and six once they
    have looked at the cat bed.

    **Order follows `fragment`, never arrival.** An unlocked fragment
    slots into its numbered place in the paragraph rather than being
    appended, which is what puts the branches back in second position
    when they appear rather than after the tire tracks.
    """

    __tablename__ = "room_text"

    room_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    since_drop: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Which sentence of the paragraph this is. One row per room is the
    # ordinary case and sorts first at 0; the channel numbers its six.
    fragment: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)
    # What this player must have done to see it. Null means everybody,
    # which is every fragment but three.
    #
    # **Deliberately an enum with one member**, not a condition
    # language: the only value is `looked_at_bed`, and it is answered by
    # one lookup in the table the hint rail already keeps. The general
    # per-player `present_when` is a separate design, parked in V3.2,
    # and reaching for it here would have cost a staged paragraph the
    # same as the whole onboarding corridor.
    visible_when: Mapped[str | None] = mapped_column(String(32), nullable=True)
    look: Mapped[str | None] = mapped_column(Text, nullable=True)


class ThingText(Base):
    """A thing's text for one state, at one drop.

    Every column is nullable: a blank cell means "use the house default", which is
    the whole point of defaults.tsv. Most things fill only `look`.
    """

    __tablename__ = "thing_text"

    thing_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    since_drop: Mapped[int] = mapped_column(Integer, primary_key=True)
    look: Mapped[str | None] = mapped_column(Text, nullable=True)
    look_carried: Mapped[str | None] = mapped_column(Text, nullable=True)
    use: Mapped[str | None] = mapped_column(Text, nullable=True)
    take: Mapped[str | None] = mapped_column(Text, nullable=True)
    drop: Mapped[str | None] = mapped_column(Text, nullable=True)
    use_fail: Mapped[str | None] = mapped_column(Text, nullable=True)
    take_fail: Mapped[str | None] = mapped_column(Text, nullable=True)
    drop_fail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What the rooms either side of a move are told. The house default names
    # the room somebody came from, which is exactly what a secret exit must
    # not do.
    move_depart: Mapped[str | None] = mapped_column(Text, nullable=True)
    move_arrive: Mapped[str | None] = mapped_column(Text, nullable=True)


class DefaultText(Base):
    """House fallback strings, used wherever a content cell is blank."""

    __tablename__ = "defaults"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    text_value: Mapped[str] = mapped_column("text", Text, nullable=False)


class EmojiGroup(Base):
    """The craving lookup, from emoji_groups.tsv.

    Content like any other: global, replaced wholesale on load, never mutated
    at runtime. `drawable` is separate from the grouping so a plate can never
    be the craving while still resolving to a known category and type - which
    is what lets a player guess one and get a straight "no" rather than an
    error.

    `category` and `type` are the pair the reaction ladder judges by: right
    category and wrong type is a different answer from both wrong, and a
    single column could not say which.
    """

    __tablename__ = "emoji_groups"

    emoji: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    drawable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The emoji this one answers for, "" if it answers for itself.
    same_as: Mapped[str] = mapped_column(String(32), nullable=False, default="")


class CravingReaction(Base):
    """The ladder the bot answers a craving guess with, from
    craving_reactions.tsv.

    Content, so the writers can swap a face without a release. Six rows: one
    per outcome, each with the emoji to react with and where it sits on the
    ladder. `progression` is null for `out_of_guesses`, which is not a rung -
    it is what the bot says when a message has no reaction slots left.
    """

    __tablename__ = "craving_reactions"

    outcome: Mapped[str] = mapped_column(String(32), primary_key=True)
    progression: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emoji: Mapped[str] = mapped_column(String(32), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    meaning: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    notes: Mapped[str] = mapped_column("when_text", Text, nullable=False, default="")


class Drop(Base):
    """The unlock calendar: when each slice of content becomes visible.

    A drop is a moment content reaches players; a release is a deployment. One
    release can carry a month of drops, which is why no release number is stored
    anywhere and no command advances one.
    """

    __tablename__ = "drops"

    drop_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    # Either an ISO date or the literal "launch", which arrives immediately.
    date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Restock(Base):
    """A schedule for things that reappear over time, from restocks.tsv.

    Loaded and validated in 2b; the job that acts on it is 2c. Nothing here runs
    on a clock yet.
    """

    __tablename__ = "restocks"

    restock_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    thing_id: Mapped[str] = mapped_column(String(64), nullable=False)
    placement: Mapped[str] = mapped_column(String(16), nullable=False)
    # What `placement` points at: a container id, a room id, or nothing
    # when the row scatters at random. Called `container` until drop 2,
    # which is when a restock first targeted a room and the old name
    # stopped being true.
    destination: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # How many of this thing's class may be present before the scheduler
    # stops topping up. Null means no cap, which is every row but the
    # toys: the others top up by rate alone.
    max_present: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Separate occurrences, not one delivery of `amount` - eight bottles a day is
    # eight arrivals at eight independently drawn times.
    times_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    every_n_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    window_start: Mapped[str] = mapped_column(String(5), nullable=False, default="00:00")
    window_end: Mapped[str] = mapped_column(String(5), nullable=False, default="23:59")
    # Where set, names a server_config key an admin can retune mid-game.
    config_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    since_drop: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# --------------------------------------------------------------------------
# World state: per guild, mutable, and never written by the loader except when
# it first places things in a server that has none.
# --------------------------------------------------------------------------


class PlayerInventory(Base):
    """What a player carries, as counts rather than rows per copy."""

    __tablename__ = "player_inventory"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    thing_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RoomContents(Base):
    """What is in a room, or in a container in a room.

    `container_id` is LOOSE_IN_ROOM for something lying out in the open, and a
    thing_id for something inside a container. It is part of the key because the
    same thing can be both at once: a spice jar in the Amazon box and another one
    dropped on the floor beside it are two rows, and only the loose one shows in
    the room's `Also here:` line.
    """

    __tablename__ = "room_contents"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    room_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    container_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=LOOSE_IN_ROOM, server_default=text("''")
    )
    thing_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # When this stack was last added to - by the scheduler, by a player
    # putting something down, or by the bed giving something up.
    #
    # **Nothing reads it yet.** It is the prerequisite for the toy
    # drain, which is what stops the channel deadlocking once there is
    # more than one toy: without a placement time there is no telling a
    # toy that arrived an hour ago from one nobody has wanted for a
    # week. One column and one write site now, and it cannot be
    # backfilled for things already lying in a channel.
    placed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PlayerState(Base):
    """A discovery one player has made: has_key, drawer_unjammed and the rest.

    Per player because the discovery *is* the content - making these server-wide
    would mean only the first player ever experiences them.
    """

    __tablename__ = "player_states"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ServerState(Base):
    """A state the whole server shares. Only stairs_repaired today.

    Collective labour earns a collective reward, so the staircase lands for
    everyone at once.
    """

    __tablename__ = "server_states"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ServerConfig(Base):
    """Per-server numbers an admin can retune: planks_required, bottles_per_day.

    Values are strings so one table serves every type; callers coerce. Also holds
    CONFIG_INITIALIZED_ON, the date restock day numbers count from.

    **Superseded by `config_history`, and read nowhere.** It survives only
    so that a database written before the change can be migrated out of
    it on the next boot; `_migrate_config_to_history` does that once and
    the rows stay here, inert, as the thing to restore from if the move
    turns out to have been wrong. Nothing writes it. Delete the table
    when the beta server has been up long enough to be sure.
    """

    __tablename__ = "server_config"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)


class ConfigHistory(Base):
    """Every value this server's config has ever held, and when.

    **This is the config, not a journal beside it.** The live value is
    the row whose `effective_to` is null, and there is no other copy -
    which is the whole point. A table that merely *records* changes to
    some other live value drifts from it, silently, and the drift is
    found while analysing something else months later.

    It matters more than it looks, because every number in the
    interaction log is uninterpretable without it: *players pet forty
    times a day* means nothing unless you know what a pet was worth
    that week and how fast the drift pulled it back.

    **Narrow rather than snapshots** - one row per
    `(guild, key, value, window)`, not one row per whole-config state.
    A snapshot table answers "what was the config on 14 October" more
    directly; a narrow one answers "when did the decay rate last
    change", survives a single-value edit without rewriting the set,
    and joins per key to each logged event. The snapshot question is a
    group-by.

    **Windows never overlap per `(guild_id, key)`**, and exactly one is
    open. That invariant lives in `set_setting`, which closes the
    standing row and opens the next inside one transaction, rather than
    in a partial unique index - SQLite and PostgreSQL both have those,
    but the dialects spell them differently and the writer is one
    function.
    """

    __tablename__ = "config_history"
    __table_args__ = (
        Index("ix_config_history_live", "guild_id", "key", "effective_to"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    # Through `server_now`, per the single-clock rule: a QA clock offset
    # that moved every dated behaviour but not this one would make the
    # history incoherent the first time anybody tested a dated feature.
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ThingUse(Base):
    """One row per (player, thing): when they last used it, and how often.

    Three jobs in one table. `last_used_at` answers the 48-hour lumber
    cooldown and the bed's 24; counting distinct rows for a thing answers
    "{n} of {total} repairs done", which the staircase needs by distinct
    player; and `use_count` answers "do this N times" achievements - ten
    frozen burritos, and now twenty-five toy plays, where the rows count
    *which* toys and the sum counts *how many* plays.

    A `miss_streak` column lived here briefly, for the toy's play ramp.
    It was the wrong home and nothing ever wrote it: 3b settles that the
    ramp is the cat's willingness to play with *you*, not with one toy,
    so it is a column on the player row and toys are interchangeable
    keys. Carrying a second toy must not hand out a second fresh ramp.
    """

    __tablename__ = "thing_uses"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    thing_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ServerRestock(Base):
    """Where a server has got to in one restock schedule.

    Written by the 2c scheduler, created empty here. `last_applied_at` is what
    makes a window missed during an outage get applied at the next opportunity
    rather than skipped; `next_at` holds the random time already drawn, so a
    restart does not redraw it and double-place.
    """

    __tablename__ = "server_restocks"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    restock_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# --------------------------------------------------------------------------
# The daily craving
#
# One emoji a day per server, guessed by reacting to anything the bot posted.
# Both tables are per guild: the craving is shared by everyone on a server so
# they can tell each other, which is the whole point of one per server.
# --------------------------------------------------------------------------


class CravingDay(Base):
    """What the cat wanted on one day, on one server.

    Stored rather than derived from the date. A derived craving would change
    under the players if a writer edited emoji_groups.tsv mid-day, and the one
    thing this game cannot survive is the answer moving while people guess.
    """

    __tablename__ = "craving_days"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    emoji: Mapped[str] = mapped_column(String(32), nullable=False)
    # Who found it first, and when. Nobody scores extra for it - this is for
    # knowing whether the day is already solved, and for 2d to look back on.
    found_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    found_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CravingMessage(Base):
    """The best answer one message has shown, on one day.

    **Per message, because the bot's reactions describe the message.**
    Discord lets the bot put each emoji on a message only once, so it cannot
    answer each guess; it carries the best answer so far and replaces it when
    a guess beats it.

    **Per day, because the answer moves and the reactions do not.** A 😻 left
    on last night's message points at yesterday's craving, which is a lie
    told to anybody scrolling up. The day is stored so that the first guess
    to land on an old message clears what the bot left there before judging.

    What is deliberately *not* here is how many reaction slots the message
    has left. A player who also clicked the bot's emoji keeps it on the
    message after the bot removes its own, so any count kept here would drift
    from Discord's within a day. The live reaction list is read every time.
    """

    __tablename__ = "craving_messages"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)


class CravingTally(Base):
    """How many distinct days a player has guessed the craving on.

    `last_credited_day` is what stops a player scoring twice for one day by
    removing and re-adding a reaction, or by reacting on a second bot message.
    The count measures showing up, not solving: a player who reacts after
    somebody else has already found it still scores the day.
    """

    __tablename__ = "craving_tally"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_credited_day: Mapped[date | None] = mapped_column(Date, nullable=True)


class Art(Base):
    """One image, as the content files describe it. Global, like all content."""

    __tablename__ = "art"

    art_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file: Mapped[str] = mapped_column(String(255), nullable=False)
    alt: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ServerArt(Base):
    """Where one server's copy of an image lives, once uploaded.

    Per guild because the upload is: the bot posts each file into a channel
    the admin picks and keeps the URL Discord hands back. Every message after
    that references the string, so nothing re-uploads and no send carries an
    attachment.
    """

    __tablename__ = "server_art"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    art_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Achievement(Base):
    """The ninth content file: what an achievement is called and what it says.

    Content, so global and reloadable - a name can change at a later drop
    without a deploy, which is the whole reason this is not a dict in code.
    Keyed with `since_drop` for the same reason every text table is: a later
    drop supersedes an earlier row rather than replacing it.

    There is deliberately no `trigger` column. The conditions involve counts,
    time windows, sets and cross-table joins; a half-expressive mini-language
    in a spreadsheet cell would be worse than a function per achievement. The
    file carries what a writer owns, and the condition lives next to the hook
    it listens on.
    """

    __tablename__ = "achievements"

    achievement_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    since_drop: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # Public, posted the moment anyone earns it.
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Private, sent to the earner and shown again in /stats.
    unlock: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A public achievement with a prerequisite is a quest: shown before it
    # is earned, in the prospective wording, to the players who hold what
    # it asks for.
    offered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PlayerNotice(Base):
    """What this player has already been told, once per thing.

    One table for three jobs, because they are the same shape and the
    alternative is three tables of two columns: the hints they have seen,
    the quests they have been notified about, and the flags that are
    simply true once something has happened - `opened_stats` is one.

    A handful of rows per player. `/qa-reset-player` must clear it, or
    the hint ladder is one-shot per tester per server.

    The autoincrementing id is load-bearing rather than decoration: it is
    the order quests became visible, which is the order `/stats` lists
    them in.
    """

    __tablename__ = "player_notices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notice_id: Mapped[str] = mapped_column(String(64), nullable=False)
    noticed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("guild_id", "user_id", "notice_id", name="uq_player_notice"),
    )


class PlayerAchievement(Base):
    """One player has earned one achievement on one server.

    The unique key is the whole primary key, which is what makes an award
    idempotent: a standing condition like *Cat's Best Friend* stays true
    forever once true, and without this it would re-announce on every `/pet`
    for the rest of October.
    """

    __tablename__ = "player_achievements"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    achievement_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    earned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ServerAchievement(Base):
    """A whole server has earned one achievement.

    No user column, and that is the point: a group achievement has no earner.
    Nobody is credited, nobody gets the description, and it shows in the
    `/stats` of every current member.
    """

    __tablename__ = "server_achievements"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    achievement_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    earned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def _normalise_url(raw: str) -> str:
    """Convert a stock PostgreSQL URL into the async (asyncpg) form SQLAlchemy needs.

    Railway hands out `postgresql://...`, which SQLAlchemy maps to the *sync*
    psycopg driver. Rewriting the scheme keeps the deployment config unchanged.
    """
    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql://", 1)
    if raw.startswith("postgresql://"):
        raw = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


async def _reject_pre_guild_schema(conn) -> None:
    """Refuse to run against a database built before per-server scoping.

    Adding `guild_id` to a primary key cannot be done with ALTER TABLE on
    SQLite, and there is no correct value to backfill for existing rows anyway -
    the database never recorded which server a pet happened in. Rather than
    guess or silently drop data, stop and say what to do.
    """

    def _columns(sync_conn):
        insp = inspect(sync_conn)
        if "users" not in insp.get_table_names():
            return None
        return {col["name"] for col in insp.get_columns("users")}

    columns = await conn.run_sync(_columns)
    if columns is not None and "guild_id" not in columns:
        raise SchemaOutdatedError(
            "This database predates per-server scoping and cannot be upgraded in "
            "place. Run `python reset_db.py --yes --fresh` to rebuild it (the "
            "SQLite file is backed up first), then start the bot again."
        )


# Columns added after a table first shipped, as (table, column, DDL). `create_all`
# creates missing tables but never missing columns, so each is ALTERed in if
# absent. Both backends accept this form, and re-running is a no-op once present.
# DDL defaults cannot take bound parameters, so values are interpolated - every
# one is a constant defined in this file, never user input.
_LATER_COLUMNS: list[tuple[str, str, str]] = [
    ("users", "relationship", f"INTEGER NOT NULL DEFAULT {RELATIONSHIP_START}"),
    ("users", "last_decay_date", "DATE"),
    ("users", "last_cat_interaction_date", "DATE"),
    ("achievements", "offered", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("achievements", "prompt", "TEXT"),
    ("achievements", "requires", "VARCHAR(64)"),
    ("things", "cohort", "VARCHAR(1)"),
    ("thing_types", "consumed_on_use", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("thing_types", "use_cooldown_daily", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("thing_text", "move_depart", "TEXT"),
    ("thing_text", "move_arrive", "TEXT"),
    ("things", "can_take", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("things", "removed_on_take", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("room_contents", "container_id", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("thing_uses", "use_count", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "toy_ramp", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "toy_cooldown_until", "TIMESTAMP"),
    ("users", "toy_plays_date", "DATE"),
    ("users", "toy_plays_today", "INTEGER NOT NULL DEFAULT 0"),
    ("room_contents", "placed_at", "TIMESTAMP"),
    # Drop 2 renamed `restocks.container` to `destination` and added
    # `max_present`. A rename is two steps for a live database: the new
    # column is added here, and the old one is left orphaned and
    # nullable rather than dropped, because dropping a column is the
    # one migration that cannot be undone by rolling back the code.
    #
    # **This list is why drop 2 looked like it had not shipped.** Both
    # were missing, so every boot tried to write `destination` into a
    # table that had no such column, the content load failed, and
    # `load_content_at_startup` did exactly what it promises - kept
    # serving the last good content. The bot ran happily on drop 1's
    # world while the files on disk had drop 2 in them.
    ("restocks", "destination", "VARCHAR(64)"),
    ("restocks", "max_present", "INTEGER"),
    ("room_text", "visible_when", "VARCHAR(32)"),
]

# `room_text.fragment` is deliberately *not* in that list. It joined the
# primary key, and `ALTER TABLE ADD COLUMN` cannot widen one - the column
# would appear, the table would look migrated, and the first load would
# still die on six channel rows sharing (CH, default, 1). See
# `_rebuild_room_text_if_narrow`. `visible_when` stays, because it is an
# ordinary nullable column and the list is where one belongs.


async def _rebuild_room_text_if_narrow(conn) -> None:
    """Drop `room_text` when its primary key predates `fragment`.

    **The one migration in this file that is a rebuild rather than an
    ALTER**, because `fragment` joined the primary key and neither
    backend can widen one in place. Left as an ADD COLUMN it would be
    the drop 2 failure exactly: the column appears, the schema looks
    current, and the content load dies at startup on six channel rows
    that all read (CH, default, 1) - after which
    `load_content_at_startup` keeps serving the last good content and
    the release looks like it never shipped.

    **Dropping it is safe in a way dropping any other table would not
    be.** `room_text` is content, not world state: it carries no
    guild_id, nothing mutates it at runtime, and `_replace_content`
    already deletes and rewrites every row of it on every boot. The
    rebuild throws away rows that were about to be thrown away.

    Runs before `create_all`, which then creates it with the four-column
    key. A database that already has that key is untouched, so this is a
    no-op from the second boot onward and on every fresh install.
    """

    def _narrow(sync_conn) -> bool:
        insp = inspect(sync_conn)
        if "room_text" not in insp.get_table_names():
            return False
        key = insp.get_pk_constraint("room_text").get("constrained_columns") or []
        return "fragment" not in key

    if await conn.run_sync(_narrow):
        await conn.execute(text("DROP TABLE room_text"))
        log.warning(
            "Schema upgrade: rebuilt room_text for the fragment key. Its rows "
            "are rewritten from the content files on this same boot."
        )


async def _rebuild_emoji_groups_if_old(conn) -> None:
    """Drop `emoji_groups` when it is missing a column the loader writes.

    **Safe for the same reason the `room_text` rebuild is.** This is
    content, not world state: it carries no `guild_id`, nothing mutates
    it at runtime, and `_replace_content` deletes and rewrites every row
    of it on every boot. The rebuild throws away rows that were about to
    be thrown away.

    The columns cannot be ALTERed in: they are NOT NULL and the old file
    has nothing to put in them, so the first insert after an upgrade
    would fail on a table that cannot be fixed forward.

    **The check is every column the loader writes, not a named one.**
    Written against `category` alone it answered correctly for exactly
    one upgrade and then silently stopped - `same_as` arrived three days
    later into a table that already had `category`, and the rebuild
    skipped it. Comparing the whole set means the next column added to
    the model is handled by this function without anybody remembering it
    exists.

    Runs before `create_all`, which then creates it in the new shape. A
    database that already matches is untouched, so this is a no-op from
    the second boot onward and on every fresh install.
    """
    wanted = {col.name for col in EmojiGroup.__table__.columns}

    def _old(sync_conn) -> bool:
        insp = inspect(sync_conn)
        if "emoji_groups" not in insp.get_table_names():
            return False
        columns = {col["name"] for col in insp.get_columns("emoji_groups")}
        return not wanted <= columns

    if await conn.run_sync(_old):
        await conn.execute(text("DROP TABLE emoji_groups"))
        log.warning(
            "Schema upgrade: rebuilt emoji_groups to match the model. Its "
            "rows are rewritten from the content files on this same boot."
        )


async def _add_missing_columns(conn) -> None:
    """Add every column in _LATER_COLUMNS that the database does not have yet."""

    def _columns_of(sync_conn):
        insp = inspect(sync_conn)
        return {
            table: {col["name"] for col in insp.get_columns(table)}
            for table in {t for t, _, _ in _LATER_COLUMNS}
            if table in insp.get_table_names()
        }

    existing = await conn.run_sync(_columns_of)
    for table, column, ddl in _LATER_COLUMNS:
        if table in existing and column not in existing[table]:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            log.info("Schema upgrade: added %s.%s", table, column)


async def _migrate_config_to_history(conn) -> None:
    """Move an old database's settings into the history, once.

    **Every existing value becomes an open window**, dated now rather
    than when it was actually set - which is a lie, and the least bad
    one available: nothing recorded the real date, and the alternative
    is either no history at all or a fabricated one further back. A
    value that has been standing since before the history existed reads
    as "set when the history started", which is true of the record even
    though it is not true of the value.

    Runs only when the history is empty and `server_config` is not, so
    it cannot fire twice and cannot touch a server that has set
    anything since. The old rows are left in place as the thing to
    restore from.
    """
    def _has_config(sync_conn) -> bool:
        return "server_config" in inspect(sync_conn).get_table_names()

    if not await conn.run_sync(_has_config):
        return
    if await conn.scalar(select(func.count()).select_from(ConfigHistory.__table__)):
        return

    moved = await conn.execute(
        ConfigHistory.__table__.insert().from_select(
            ["guild_id", "key", "value", "effective_from"],
            select(
                ServerConfig.guild_id,
                ServerConfig.key,
                ServerConfig.value,
                func.now(),
            ),
        )
    )
    if moved.rowcount:
        log.info(
            "Schema upgrade: moved %d server_config row(s) into config_history, "
            "which is the live config from now on",
            moved.rowcount,
        )


async def _migrate_pet_events(conn) -> None:
    """Move the old pet log into the interaction log, once, and drop it.

    `pet_events` answered one question - how many pets in the last ten
    minutes - and the interaction log answers it with a filter on
    `action`. Two logs of the same event can disagree, so the old one
    goes rather than sitting beside the new one.

    **The rows are copied rather than abandoned**, for two reasons that
    are both about the same ten minutes. A server upgraded mid-evening
    would otherwise read every player as having pet nobody recently,
    so the cat would turn friendly for everyone at once and the
    crowding nudge would fire again on the next pet. And
    `relationship_at_pet` is the only record of where a player's meter
    stood over a month of petting, which no other table can
    reconstruct - the score is a running total.

    **What does not survive is honest about not surviving.** The old
    row recorded the score *before* the pet and never the outcome, so a
    copied row cannot say whether the cat was friendly or what the pet
    was worth: `relationship_delta` and `score_after` stay null, and
    the score before goes into `detail` where it cannot be mistaken for
    either. Rows from here on carry all three.
    """

    def _state(sync_conn):
        insp = inspect(sync_conn)
        if "pet_events" not in insp.get_table_names():
            return None
        return {col["name"] for col in insp.get_columns("pet_events")}

    columns = await conn.run_sync(_state)
    if columns is None:
        return

    # A database old enough to predate the column gets the rows without
    # the history, which is all there is to give.
    before = (
        "'score_before=' || relationship_at_pet"
        if "relationship_at_pet" in columns
        else "NULL"
    )
    moved = await conn.execute(
        text(
            f"""
            INSERT INTO interaction_log
                (guild_id, user_id, actor, action, outcome, detail, created_at)
            SELECT guild_id, user_id, '{PLAYER}', '{PET}', '{SUCCESS}',
                   {before}, created_at
            FROM pet_events
            """
        )
    )
    await conn.execute(text("DROP TABLE pet_events"))
    log.info(
        "Schema upgrade: moved %d pet_events row(s) into interaction_log and "
        "dropped the old table",
        moved.rowcount or 0,
    )


def _enforce_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """Turn on foreign key enforcement for SQLite, which defaults it off.

    PostgreSQL enforces the foreign keys in this file; SQLite ignores them
    entirely unless each connection issues this pragma. Left off, the local and
    CI backend accepts rows production would refuse - an inventory row pointing
    at a thing that does not exist, say, which `get_inventory` then drops on its
    join while `inventory_count` still counts. Bugs like that reach production
    precisely because the cheap backend was more permissive than the real one.
    """
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection, _record):  # pragma: no cover - driver callback
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Migrated(NamedTuple):
    """What the pre-2b repair had to touch."""

    positions: int
    unlocked_lists: int


async def unlock_room(user_id: int, guild_id: int, room_id: str) -> bool:
    """Open a room for one player, permanently. False if it already was.

    The first thing since 2a to write to `rooms_unlocked`, which until now was
    set once at entry and never touched. The Secret Library is
    `open_at_launch = no`, so climbing the oak is what puts it in the list -
    per player, because the discovery is the content.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        state = await session.get(PlayerGameState, (user_id, guild_id))
        if state is None or room_id in (state.rooms_unlocked or []):
            return False
        # Reassigned rather than appended: SQLAlchemy does not track mutation
        # inside a JSON column, so an in-place append would never be written.
        state.rooms_unlocked = [*state.rooms_unlocked, room_id]
        await session.commit()

    log.info("Guild %s, player %s unlocked %s", guild_id, user_id, room_id)
    return True


async def migrate_room_names_to_ids() -> Migrated:
    """Translate pre-2b room names to room ids, once, in both places they hide.

    Before phase 2b a player's position was a name - "Entryway". The content
    files key on ids - "EN" - and everything now joins on those, so a row still
    holding a name matches no room and its owner is nowhere: no description, no
    exits, no thread.

    **`rooms_unlocked` holds names too, and used to be missed.** `/use` on an
    exit checks `destination_room_id` - an id - against that list, so for a
    player who entered before 2b it never matched and *every* exit refused
    with the house's generic `use_fail`. `/look` at the same exit worked,
    because looking does not consult the list, which is what made it read as
    one broken doorway rather than a broken player.

    A stale list is reset to the rooms open at launch rather than translated
    entry by entry. Nothing in the game has ever unlocked a room after entry,
    so there is no progress in that list to preserve - and a verbatim
    translation would hand those players the Secret Library, which is
    deliberately shut until 2e.

    Matched on names throughout, so it can only affect rows written by the old
    code; a row already holding ids is left alone, which is what makes this
    safe to run on every boot. Runs after content loads, since it needs
    room_types to translate against.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        rooms = (
            await session.execute(
                select(RoomType.room_id, RoomType.name, RoomType.open_at_launch)
            )
        ).all()
        if not rooms:
            return Migrated(0, 0)

        names = {name for _, name, _ in rooms}
        at_launch = [room_id for room_id, _, open_at_launch in rooms if open_at_launch]

        moved = 0
        for room_id, name, _ in rooms:
            result = await session.execute(
                update(PlayerGameState)
                .where(PlayerGameState.current_room == name)
                .values(current_room=room_id)
            )
            moved += result.rowcount or 0

        stale = [
            (guild_id, user_id)
            for guild_id, user_id, unlocked in (
                await session.execute(
                    select(
                        PlayerGameState.guild_id,
                        PlayerGameState.user_id,
                        PlayerGameState.rooms_unlocked,
                    )
                )
            ).all()
            if any(entry in names for entry in (unlocked or []))
        ]
        for guild_id, user_id in stale:
            await session.execute(
                update(PlayerGameState)
                .where(
                    PlayerGameState.guild_id == guild_id,
                    PlayerGameState.user_id == user_id,
                )
                .values(rooms_unlocked=at_launch)
            )

        if moved or stale:
            await session.commit()
            log.info(
                "Migrated %d player position(s) and repaired %d unlocked-room "
                "list(s) from room names to room ids",
                moved,
                len(stale),
            )
        return Migrated(moved, len(stale))


async def init_db() -> None:
    """Create the engine and ensure the schema exists. Safe to call once at startup."""
    global _engine, _session_factory

    if _engine is not None:
        return

    raw_url = os.getenv("DATABASE_URL", "").strip()
    if raw_url:
        url = _normalise_url(raw_url)
        backend = "PostgreSQL"
    elif os.getenv("RAILWAY_ENVIRONMENT"):
        # Railway sets this on every deployment. Falling back to SQLite there
        # would write to the container's disk, which is discarded on every
        # redeploy - all player data would silently vanish. Refuse instead.
        raise MissingDatabaseError(
            "DATABASE_URL is not set, but this is running on Railway. Add it to "
            "the service's Variables as a reference to the Postgres service "
            "(${{Postgres.DATABASE_URL}}). Refusing to fall back to SQLite, which "
            "would lose all data on the next redeploy."
        )
    else:
        url = DEFAULT_SQLITE_URL
        backend = "SQLite (local development)"
        log.warning("DATABASE_URL not set - falling back to local SQLite file catbot.db")

    _engine = create_async_engine(url, pool_pre_ping=True)
    _enforce_sqlite_foreign_keys(_engine)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    try:
        async with _engine.begin() as conn:
            await _reject_pre_guild_schema(conn)
            await _rebuild_room_text_if_narrow(conn)
            await _rebuild_emoji_groups_if_old(conn)
            await conn.run_sync(Base.metadata.create_all)
            await _add_missing_columns(conn)
            await _migrate_config_to_history(conn)
            await _migrate_pet_events(conn)
    except StartupError:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        raise

    log.info("Database ready (%s)", backend)


def _upsert_statement():
    """Return the dialect-specific INSERT ... ON CONFLICT builder.

    PostgreSQL and SQLite both support upsert-with-RETURNING, which lets us
    increment and read back the new total in a single atomic statement. That
    matters because a user can fire /pet faster than a read-then-write round trip.
    """
    assert _engine is not None
    return pg_insert if _engine.dialect.name == "postgresql" else sqlite_insert


def _require_session() -> async_sessionmaker:
    if _session_factory is None:
        raise RuntimeError("init_db() must run before database queries")
    return _session_factory


# --------------------------------------------------------------------------
# Cat: petting and relationship (Phase 1), per server
# --------------------------------------------------------------------------


async def increment_pet_count(
    user_id: int, guild_id: int, *, drop: int | None = None
) -> PetResult:
    """Record a pet for this player in this server, creating their row if needed.

    Returns the new lifetime total alongside the number of pets this player
    already made inside RECENT_PET_WINDOW in this server - the caller uses that
    to weight how warmly the cat reacts. Counting happens before the new event
    is inserted, so `recent` describes the state the player arrived in.

    The count, the increment and the new event all share one transaction, so a
    burst of rapid /pet calls cannot interleave into a wrong reading. That is
    why the log row is opened here rather than by the caller after the roll:
    the row has to exist before the next pet counts the window, and what this
    one was worth is not known until afterwards. `close_interaction` finishes
    it.
    """
    session_factory = _require_session()

    now = await server_now(guild_id)
    cutoff = now - RECENT_PET_WINDOW

    insert = _upsert_statement()
    stmt = (
        insert(User)
        .values(id=user_id, guild_id=guild_id, pet_count=1)
        .on_conflict_do_update(
            index_elements=[User.id, User.guild_id],
            set_={"pet_count": User.pet_count + 1, "updated_at": func.now()},
        )
        .returning(User.pet_count, User.relationship)
    )

    try:
        async with session_factory() as session:
            recent = await session.scalar(
                _recent_pet_count(user_id, guild_id, cutoff)
            )
            total, _relationship_before = (await session.execute(stmt)).one()
            # The upsert touches pet_count, never relationship, so what comes back
            # is the score as it stood before this pet. Nothing needs it here any
            # more: the log records the score *after*, and the score before is
            # that minus the delta on the same row.
            row = InteractionLog(
                guild_id=guild_id,
                user_id=user_id,
                actor=PLAYER,
                action=PET,
                outcome=SUCCESS,
                drop=drop,
                created_at=now,
            )
            session.add(row)
            await session.commit()
            log_id = row.id

            log.info(
                "User %s petted the cat in guild %s (total: %s, recent: %s)",
                user_id,
                guild_id,
                total,
                recent,
            )
            return PetResult(total=total, recent=recent or 0, log_id=log_id)
    except SQLAlchemyError:
        log.exception("Failed to increment pet count for user %s in guild %s", user_id, guild_id)
        raise


async def adjust_relationship(user_id: int, guild_id: int, delta: int) -> int:
    """Move this player's relationship in this server by `delta`.

    Floored at RELATIONSHIP_MIN and **not capped**. A grudge bottoms out,
    because a cat that already wants nothing to do with you cannot want
    less; affection does not, because the game asks for 250 of it.

    The floor is expressed as a SQL CASE so the read, the arithmetic and
    the write are one atomic statement - two rapid pets cannot both read
    the same starting value and lose an update between them.
    """
    session_factory = _require_session()

    moved = User.relationship + delta
    stmt = (
        update(User)
        .where(User.id == user_id, User.guild_id == guild_id)
        .values(
            relationship=case(
                (moved < RELATIONSHIP_MIN, RELATIONSHIP_MIN),
                else_=moved,
            ),
            updated_at=func.now(),
        )
        .returning(User.relationship)
    )

    try:
        async with session_factory() as session:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            await session.commit()
            if row is None:
                # No row yet: the caller adjusted before the player existed here.
                log.warning("adjust_relationship: no row for %s in guild %s", user_id, guild_id)
                return 0
            log.info("User %s in guild %s relationship %+d -> %s", user_id, guild_id, delta, row)
            return row
    except SQLAlchemyError:
        log.exception("Failed to adjust relationship for %s in guild %s", user_id, guild_id)
        raise


async def touched_the_cat(user_id: int, guild_id: int, day: date) -> None:
    """Record that this player interacted with the cat today.

    **Attempts count, not just successes.** Three of the four ways to
    touch the cat can fail - the toy's first offer is a guaranteed
    refusal, the bed refuses inside its window, and a pet can roll
    standoffish. The drift exists to notice absence, and a player who
    tried four times was not absent.

    Called from every one of them, which is why it is one column and not
    a branch per interaction in the nightly query.
    """
    session_factory = _require_session()
    try:
        async with session_factory() as session:
            await session.execute(
                update(User)
                .where(User.id == user_id, User.guild_id == guild_id)
                .values(last_cat_interaction_date=day)
            )
            await session.commit()
    except SQLAlchemyError:
        # Decoration on an action that has already happened. Losing the
        # stamp costs the player ten points overnight, which is worth less
        # than failing the command they actually ran.
        log.exception(
            "Could not stamp a cat interaction for %s in guild %s", user_id, guild_id
        )


async def get_relationship(user_id: int, guild_id: int) -> int:
    """This player's relationship score in this server, or 0 if they have no row."""
    session_factory = _require_session()
    try:
        async with session_factory() as session:
            value = await session.scalar(
                select(User.relationship).where(User.id == user_id, User.guild_id == guild_id)
            )
            return value or 0
    except SQLAlchemyError:
        log.exception("Failed to read relationship for %s in guild %s", user_id, guild_id)
        raise


async def get_pet_count(user_id: int, guild_id: int) -> int:
    """This player's pet total in this server, or 0 if they have never petted here."""
    session_factory = _require_session()
    try:
        async with session_factory() as session:
            value = await session.scalar(
                select(User.pet_count).where(User.id == user_id, User.guild_id == guild_id)
            )
            return value or 0
    except SQLAlchemyError:
        log.exception("Failed to read pet count for %s in guild %s", user_id, guild_id)
        raise


# --------------------------------------------------------------------------
# Haunted house: game state (Phase 2), per server
# --------------------------------------------------------------------------


async def ensure_user_exists(user_id: int, guild_id: int) -> None:
    """Create this player's `users` row for this server if they have never petted here.

    `player_game_state` has a foreign key to `users`, but a `users` row is
    otherwise only created by /pet. Without this, a player who joins the haunted
    house before ever petting would fail on the constraint.
    """
    session_factory = _require_session()
    insert = _upsert_statement()
    stmt = (
        insert(User)
        .values(id=user_id, guild_id=guild_id, pet_count=0)
        .on_conflict_do_nothing(index_elements=[User.id, User.guild_id])
    )
    try:
        async with session_factory() as session:
            await session.execute(stmt)
            await session.commit()
    except SQLAlchemyError:
        log.exception("Failed to ensure users row for %s in guild %s", user_id, guild_id)
        raise


async def start_game(
    user_id: int,
    guild_id: int,
    starting_room: str,
    rooms_unlocked: list[str],
) -> bool:
    """Enrol a player in this server's haunted house.

    Returns True if this call enrolled them, False if they were already in.

    The `users` row is ensured first to satisfy the foreign key, then the game
    state is inserted with ON CONFLICT DO NOTHING so two rapid invocations for
    the same player cannot both believe they enrolled them.
    """
    session_factory = _require_session()
    await ensure_user_exists(user_id, guild_id)

    insert = _upsert_statement()
    try:
        async with session_factory() as session:
            stmt = (
                insert(PlayerGameState)
                .values(
                    user_id=user_id,
                    guild_id=guild_id,
                    room_version_assignment=VESTIGIAL_ROOM_VERSION,
                    current_room=starting_room,
                    rooms_unlocked=rooms_unlocked,
                )
                .on_conflict_do_nothing(
                    index_elements=[PlayerGameState.user_id, PlayerGameState.guild_id]
                )
                .returning(PlayerGameState.user_id)
            )
            result = await session.execute(stmt)
            created = result.scalar_one_or_none() is not None
            await session.commit()

            if created:
                log.info("Player %s entered the house in guild %s", user_id, guild_id)
            return created
    except SQLAlchemyError:
        log.exception("Failed to start game for %s in guild %s", user_id, guild_id)
        raise


async def get_game_state(user_id: int, guild_id: int) -> GameState | None:
    """This player's position in this server's house, or None if not in it."""
    session_factory = _require_session()
    try:
        async with session_factory() as session:
            row = (
                await session.execute(
                    select(
                        PlayerGameState.user_id,
                        PlayerGameState.guild_id,
                        PlayerGameState.current_room,
                        PlayerGameState.rooms_unlocked,
                    ).where(
                        PlayerGameState.user_id == user_id,
                        PlayerGameState.guild_id == guild_id,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            return GameState(row[0], row[1], row[2], list(row[3] or []))
    except SQLAlchemyError:
        log.exception("Failed to read game state for %s in guild %s", user_id, guild_id)
        raise


async def update_current_room(user_id: int, guild_id: int, room_name: str) -> None:
    """Move a player to a different room in this server's house."""
    session_factory = _require_session()
    try:
        async with session_factory() as session:
            await session.execute(
                update(PlayerGameState)
                .where(
                    PlayerGameState.user_id == user_id,
                    PlayerGameState.guild_id == guild_id,
                )
                .values(current_room=room_name, updated_at=func.now())
            )
            await session.commit()
            log.info("Player %s moved to %s in guild %s", user_id, room_name, guild_id)
    except SQLAlchemyError:
        log.exception("Failed to move %s to %s in guild %s", user_id, room_name, guild_id)
        raise


async def locations_in(guild_id: int) -> dict[int, str]:
    """Where everybody in this server is standing, by user id.

    One read for a whole sweep rather than one per thread member: the
    sweep asks the same question of every room, and a server with nine
    rooms and thirty players would otherwise be thirty round trips an
    hour to answer it.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(PlayerGameState.user_id, PlayerGameState.current_room).where(
                PlayerGameState.guild_id == guild_id
            )
        )
    return {user_id: room for user_id, room in rows if room}


async def send_players_home(guild_id: int, valid: set[str], home: str) -> int:
    """Put every player who is nowhere real into `home`. Returns how many.

    **A location has to be somewhere that exists.** A build where a room
    arrives later, a drop renumbered under a running server, a row written
    by a version that is now two deploys old: each can leave a player
    standing in a room their server has not got, and every verb they type
    then answers about it. Out on the road is the one place that is always
    there.

    Idempotent, and cheap when there is nothing to do - which is the usual
    case, and why this can run on every boot.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        result = await session.execute(
            update(PlayerGameState)
            .where(
                PlayerGameState.guild_id == guild_id,
                or_(
                    PlayerGameState.current_room.is_(None),
                    PlayerGameState.current_room.not_in(valid),
                ),
            )
            .values(current_room=home, updated_at=func.now())
        )
        await session.commit()
    return result.rowcount or 0


async def delete_game_state(user_id: int, guild_id: int) -> None:
    """Remove a player's game state in this server.

    Used to roll back an enrolment that could not be completed in Discord, so the
    player is not left recorded as inside a house they were never added to.
    """
    session_factory = _require_session()
    try:
        async with session_factory() as session:
            await session.execute(
                delete(PlayerGameState).where(
                    PlayerGameState.user_id == user_id,
                    PlayerGameState.guild_id == guild_id,
                )
            )
            await session.commit()
            log.info("Rolled back game state for %s in guild %s", user_id, guild_id)
    except SQLAlchemyError:
        log.exception("Failed to roll back game state for %s in guild %s", user_id, guild_id)
        raise


async def get_all_player_locations(guild_id: int) -> list[tuple[int, str]]:
    """Every player's (user_id, current_room) in one server.

    Used when rebuilding that server's house: the database says who belongs in
    which thread, so recreating threads does not strand anyone. Filtered by
    guild so rebuilding one server never touches another's players.
    """
    session_factory = _require_session()
    try:
        async with session_factory() as session:
            rows = await session.execute(
                select(
                    PlayerGameState.user_id,
                    PlayerGameState.current_room,
                ).where(PlayerGameState.guild_id == guild_id)
            )
            return [(row[0], row[1]) for row in rows]
    except SQLAlchemyError:
        log.exception("Failed to read player locations for guild %s", guild_id)
        raise


# --------------------------------------------------------------------------
# Rooms, things and inventory
#
# The per-guild query layer that used to live here is gone: it read the rooms,
# things and inventory tables, which the phase 2b loader no longer writes. Its
# replacement reads the content tables instead and is further down, under
# "Reading the world".
#
# The tables themselves stay, unread, because dropping a table is not something
# the additive startup migration can do.
# --------------------------------------------------------------------------


class LookResult(NamedTuple):
    """What /look found: the description shown, and how many instances matched."""

    description: str | None
    count: int


# --------------------------------------------------------------------------
# The nightly climb back toward neutral, per (player, server)
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Grudges soften
#
# What is left of the nightly drift. The downward half - affection
# fading by ten a day for anybody who stayed away - was withdrawn and
# is not coming back here; a score that falls during an absence
# punishes the players a staged release is hardest on. The upward half
# is the opposite and stays: somebody who annoyed the cat can climb
# back to neutral whether or not they keep playing.
#
# The names changed with the meaning. A function called "decay" that
# only ever raises a score is a trap for whoever reads it next.
# --------------------------------------------------------------------------


async def apply_daily_recovery(
    day: date, *, guild_id: int | None = None
) -> list[RecoveryChange]:
    """Settle one Pacific calendar day, softening grudges back toward 0.

    A score at or below `RECOVERY_THRESHOLD` climbs by `RECOVERY_STEP`,
    never crossing above 0. Everything else is left exactly where it
    is: there is no longer a downward half, so a positive score only
    ever moves because somebody did something.

    **No interaction test.** The drift this came from skipped any day
    a player touched the cat, which was right when the question was
    whether to punish an absence. It is wrong for recovery - it would
    leave the player who turns up every day stuck below zero longest,
    while somebody who walked away climbed out for free.

    Each (player, server) row is independent, and every row considered
    has `last_decay_date` stamped to `day`, so a restart cannot apply
    the same day twice.
    """
    session_factory = _require_session()
    changes: list[RecoveryChange] = []

    try:
        async with session_factory() as session:
            pending = (
                await session.execute(
                    select(
                        User.id,
                        User.guild_id,
                        User.relationship,
                        User.last_cat_interaction_date,
                    ).where(
                        (User.last_decay_date.is_(None)) | (User.last_decay_date < day),
                        *( [User.guild_id == guild_id] if guild_id is not None else [] ),
                    )
                )
            ).all()

            for user_id, guild_id, score, _touched in pending:
                if score <= RECOVERY_THRESHOLD:
                    new_score = min(0, score + RECOVERY_STEP)
                    await session.execute(
                        update(User)
                        .where(User.id == user_id, User.guild_id == guild_id)
                        .values(relationship=new_score)
                    )
                    changes.append(
                        RecoveryChange(user_id, guild_id, score, new_score, day)
                    )

                await session.execute(
                    update(User)
                    .where(User.id == user_id, User.guild_id == guild_id)
                    .values(last_decay_date=day)
                )

            await session.commit()

        if changes:
            log.info("Recovery for %s raised %d score(s)", day, len(changes))
        return changes
    except SQLAlchemyError:
        log.exception("Nightly recovery failed for %s", day)
        raise


async def run_pending_recovery() -> list[RecoveryChange]:
    """Settle every fully elapsed day that has not been settled yet.

    Called at startup and after each scheduled midnight run, so an outage
    of a few days is caught up rather than silently skipped. Only days
    that have fully ended are settled - today is still in progress.

    **Per server, because each server has its own today.** A test server
    running a week ahead on `/qa-clock` has a week of nights to settle
    that the live one does not, and settling them all against one
    calendar would either skip its days or settle everybody else's
    future.
    """
    session_factory = _require_session()

    async with session_factory() as session:
        guilds = (
            await session.execute(select(User.guild_id).distinct())
        ).scalars().all()

    changes: list[RecoveryChange] = []
    for guild_id in sorted(guilds):
        changes.extend(await _catch_up(guild_id))
    return changes


async def _catch_up(guild_id: int) -> list[RecoveryChange]:
    """Every night one server owes, oldest first."""
    session_factory = _require_session()
    today = await server_today(guild_id)

    async with session_factory() as session:
        earliest = await session.scalar(
            select(func.min(User.last_decay_date)).where(User.guild_id == guild_id)
        )

    # Never settled before: yesterday only, rather than all of history.
    first_day = (earliest + timedelta(days=1)) if earliest else today - timedelta(days=1)
    first_day = max(first_day, today - timedelta(days=MAX_CATCHUP_DAYS))

    changes: list[RecoveryChange] = []
    day = first_day
    while day < today:
        changes.extend(await apply_daily_recovery(day, guild_id=guild_id))
        day += timedelta(days=1)
    return changes


async def close_db() -> None:
    """Dispose of the connection pool on shutdown."""
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        log.info("Database connection closed")


# --------------------------------------------------------------------------
# Reading the world (/look, /inventory) from the content tables
#
# These replace the per-guild rooms/things queries above, which read tables the
# loader no longer writes. Behaviour is deliberately unchanged from phase 2a:
# the resolution ladder, `Also here:`, containers and sources are 2c.
# --------------------------------------------------------------------------


async def _thing_names(session, thing_ids: set[str]) -> dict[str, tuple[str, list[str]]]:
    if not thing_ids:
        return {}
    rows = await session.execute(
        select(ThingType.thing_id, ThingType.name, ThingType.aliases).where(
            ThingType.thing_id.in_(thing_ids)
        )
    )
    return {row[0]: (row[1], list(row[2] or [])) for row in rows}


def _matches(typed: str, name: str, aliases: list[str]) -> bool:
    needle = typed.strip().lower()
    return bool(needle) and (
        needle == name.lower() or needle in {a.strip().lower() for a in aliases}
    )


async def look_at_thing_here(
    user_id: int, guild_id: int, room_id: str, typed: str
) -> LookResult | None:
    """Find a thing by what the player typed, in their room or their bag.

    Three places a thing can be. Fixtures, sources and exits sit in the room by
    virtue of `thing_types.room_id` and are never stock, so they are not counted -
    there is one fireplace. Objects sit in `room_contents`, which is where a count
    above one is real. What the player carries comes from `player_inventory`.

    Matching is on name or alias, case-insensitively. The loader guarantees
    aliases are unique within a room, so a name cannot mean two things at once.
    """
    if not typed or not typed.strip():
        return None

    session_factory = _require_session()
    try:
        async with session_factory() as session:
            fixed = (
                await session.execute(
                    select(ThingType.thing_id, ThingType.name, ThingType.aliases, ThingType.type)
                    .where(ThingType.room_id == room_id)
                )
            ).all()

            stock = {
                row[0]: row[1]
                for row in await session.execute(
                    select(RoomContents.thing_id, RoomContents.count).where(
                        RoomContents.guild_id == guild_id,
                        RoomContents.room_id == room_id,
                        RoomContents.count > 0,
                    )
                )
            }
            carried = {
                row[0]: row[1]
                for row in await session.execute(
                    select(PlayerInventory.thing_id, PlayerInventory.count).where(
                        PlayerInventory.guild_id == guild_id,
                        PlayerInventory.user_id == user_id,
                        PlayerInventory.count > 0,
                    )
                )
            }

            named = await _thing_names(session, set(stock) | set(carried))

            candidates: dict[str, tuple[str, list[str], str | None]] = {}
            for thing_id, name, aliases, kind in fixed:
                candidates[thing_id] = (name, list(aliases or []), kind)
            for thing_id, (name, aliases) in named.items():
                candidates.setdefault(thing_id, (name, aliases, "object"))

            match = next(
                (
                    thing_id
                    for thing_id, (name, aliases, _) in candidates.items()
                    if _matches(typed, name, aliases)
                ),
                None,
            )
            if match is None:
                return None

            count = stock.get(match, 0) + carried.get(match, 0)
            if count == 0:
                # A fixture, a source or an exit: present, but not stock.
                kind = candidates[match][2]
                if kind == "object":
                    return None
                count = 1

            description = await session.scalar(
                select(ThingText.look).where(
                    ThingText.thing_id == match, ThingText.state == "default"
                )
            )
            return LookResult(description=description, count=count)
    except SQLAlchemyError:
        log.exception("Failed to look at %r in %s for guild %s", typed, room_id, guild_id)
        raise


async def get_carried(user_id: int, guild_id: int) -> list[tuple[str, int]]:
    """(name, count) for everything the player carries, alphabetical."""
    session_factory = _require_session()
    try:
        async with session_factory() as session:
            rows = await session.execute(
                select(ThingType.name, PlayerInventory.count)
                .join(ThingType, ThingType.thing_id == PlayerInventory.thing_id)
                .where(
                    PlayerInventory.user_id == user_id,
                    PlayerInventory.guild_id == guild_id,
                    PlayerInventory.count > 0,
                )
                .order_by(ThingType.name)
            )
            return [(row[0], row[1]) for row in rows]
    except SQLAlchemyError:
        log.exception("Failed to read inventory for %s in guild %s", user_id, guild_id)
        raise


async def carried_count(user_id: int, guild_id: int) -> int:
    """How many things the player is carrying, counting duplicates."""
    session_factory = _require_session()
    try:
        async with session_factory() as session:
            return (
                await session.scalar(
                    select(func.coalesce(func.sum(PlayerInventory.count), 0)).where(
                        PlayerInventory.user_id == user_id,
                        PlayerInventory.guild_id == guild_id,
                    )
                )
            ) or 0
    except SQLAlchemyError:
        log.exception("Failed to count inventory for %s in guild %s", user_id, guild_id)
        raise


# --------------------------------------------------------------------------
# Moving things: /take, /drop, /use
#
# Counts, not rows. Every write is an upsert that adds to a count, or an update
# conditional on the count still being positive - never a read followed by a
# write. Two players reaching for the last of something in the same instant
# resolve correctly because the decrement itself is the check.
# --------------------------------------------------------------------------


async def carries_all(user_id: int, guild_id: int, thing_ids: list[str]) -> bool:
    """Whether this player is holding at least one of each of these.

    Used for `requires`, which is checked at the moment of use rather than
    recorded - so a player who puts an ingredient down stops satisfying it.
    """
    if not thing_ids:
        return False
    session_factory = _require_session()
    async with session_factory() as session:
        held = {
            row[0]
            for row in await session.execute(
                select(PlayerInventory.thing_id).where(
                    PlayerInventory.user_id == user_id,
                    PlayerInventory.guild_id == guild_id,
                    PlayerInventory.thing_id.in_(thing_ids),
                    PlayerInventory.count > 0,
                )
            )
        }
    return held.issuperset(thing_ids)


async def carried_of(user_id: int, guild_id: int, thing_id: str) -> int:
    """How many of one thing this player is carrying."""
    session_factory = _require_session()
    async with session_factory() as session:
        return (
            await session.scalar(
                select(PlayerInventory.count).where(
                    PlayerInventory.user_id == user_id,
                    PlayerInventory.guild_id == guild_id,
                    PlayerInventory.thing_id == thing_id,
                )
            )
        ) or 0


def _add_to_inventory(insert, user_id: int, guild_id: int, thing_id: str, delta: int):
    return (
        insert(PlayerInventory)
        .values(user_id=user_id, guild_id=guild_id, thing_id=thing_id, count=delta)
        .on_conflict_do_update(
            index_elements=[
                PlayerInventory.guild_id,
                PlayerInventory.user_id,
                PlayerInventory.thing_id,
            ],
            set_={"count": PlayerInventory.count + delta},
        )
    )


def _add_to_room(
    insert, guild_id: int, room_id: str, container_id: str, thing_id: str, delta: int
):
    return (
        insert(RoomContents)
        .values(
            guild_id=guild_id,
            room_id=room_id,
            container_id=container_id,
            thing_id=thing_id,
            count=delta,
            placed_at=_utcnow(),
        )
        .on_conflict_do_update(
            index_elements=[
                RoomContents.guild_id,
                RoomContents.room_id,
                RoomContents.container_id,
                RoomContents.thing_id,
            ],
            set_={"count": RoomContents.count + delta, "placed_at": _utcnow()},
        )
    )


async def take_from_source(user_id: int, guild_id: int, thing_id: str) -> None:
    """Hand a player one of what a source yields. The source is not consumed."""
    session_factory = _require_session()
    insert = _upsert_statement()
    await ensure_user_exists(user_id, guild_id)
    async with session_factory() as session:
        await session.execute(_add_to_inventory(insert, user_id, guild_id, thing_id, 1))
        await session.commit()
    log.info("User %s drew %s from a source in guild %s", user_id, thing_id, guild_id)


async def take_from_room(
    user_id: int, guild_id: int, room_id: str, container_id: str, thing_id: str
) -> bool:
    """Move one copy out of the room and into the bag. False if none was left.

    The decrement is conditional on the count still being above zero, so two
    players racing for the last of something cannot both win it.
    """
    session_factory = _require_session()
    insert = _upsert_statement()
    await ensure_user_exists(user_id, guild_id)

    async with session_factory() as session:
        taken = await session.execute(
            update(RoomContents)
            .where(
                RoomContents.guild_id == guild_id,
                RoomContents.room_id == room_id,
                RoomContents.container_id == container_id,
                RoomContents.thing_id == thing_id,
                RoomContents.count > 0,
            )
            .values(count=RoomContents.count - 1)
        )
        if not taken.rowcount:
            await session.rollback()
            return False

        await session.execute(_add_to_inventory(insert, user_id, guild_id, thing_id, 1))
        await session.commit()

    log.info("User %s took %s in guild %s", user_id, thing_id, guild_id)
    return True


async def drop_into_room(user_id: int, guild_id: int, room_id: str, thing_id: str) -> bool:
    """Move one copy out of the bag and into the room, loose.

    Always loose: dropping a spice jar in the Entryway does not put it back
    inside the Amazon box.
    """
    session_factory = _require_session()
    insert = _upsert_statement()

    async with session_factory() as session:
        dropped = await session.execute(
            update(PlayerInventory)
            .where(
                PlayerInventory.guild_id == guild_id,
                PlayerInventory.user_id == user_id,
                PlayerInventory.thing_id == thing_id,
                PlayerInventory.count > 0,
            )
            .values(count=PlayerInventory.count - 1)
        )
        if not dropped.rowcount:
            await session.rollback()
            return False

        await session.execute(
            _add_to_room(insert, guild_id, room_id, LOOSE_IN_ROOM, thing_id, 1)
        )
        await session.commit()

    log.info("User %s dropped %s in %s, guild %s", user_id, thing_id, room_id, guild_id)
    return True


async def consume_carried(user_id: int, guild_id: int, thing_id: str) -> bool:
    """Use one up. False if they were not carrying one.

    Conditional on `count > 0` in the same statement, so two rapid uses of a
    last burrito cannot both succeed and leave the count at minus one.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        result = await session.execute(
            update(PlayerInventory)
            .where(
                PlayerInventory.user_id == user_id,
                PlayerInventory.guild_id == guild_id,
                PlayerInventory.thing_id == thing_id,
                PlayerInventory.count > 0,
            )
            .values(count=PlayerInventory.count - 1)
        )
        await session.commit()
    return bool(result.rowcount)


async def transform_carried(user_id: int, guild_id: int, thing_id: str, into: str) -> bool:
    """Swap one carried thing for another: one used bottle becomes one sanitized."""
    session_factory = _require_session()
    insert = _upsert_statement()

    async with session_factory() as session:
        used = await session.execute(
            update(PlayerInventory)
            .where(
                PlayerInventory.guild_id == guild_id,
                PlayerInventory.user_id == user_id,
                PlayerInventory.thing_id == thing_id,
                PlayerInventory.count > 0,
            )
            .values(count=PlayerInventory.count - 1)
        )
        if not used.rowcount:
            await session.rollback()
            return False

        await session.execute(_add_to_inventory(insert, user_id, guild_id, into, 1))
        await session.commit()

    log.info("User %s transformed %s into %s in guild %s", user_id, thing_id, into, guild_id)
    return True


class UseRecord(NamedTuple):
    """When this player last used a thing, and how many times including this one."""

    last_used_at: datetime | None
    use_count: int


async def record_use(user_id: int, guild_id: int, thing_id: str) -> UseRecord:
    """Stamp a use, and report what the row said *before* it.

    One row, three jobs. `last_used_at` answers the cooldown, counting distinct
    rows answers "how many players have placed a plank", and `use_count` answers
    "do this N times". The previous timestamp is returned because the cooldown
    needs the value from before this use overwrote it.

    2b added the use_count column and wired nothing to it; this is the only
    place that increments, so it cannot be double-counted.
    """
    session_factory = _require_session()
    insert = _upsert_statement()
    now = await server_now(guild_id)

    async with session_factory() as session:
        previous = (
            await session.execute(
                select(ThingUse.last_used_at, ThingUse.use_count).where(
                    ThingUse.guild_id == guild_id,
                    ThingUse.user_id == user_id,
                    ThingUse.thing_id == thing_id,
                )
            )
        ).one_or_none()

        await session.execute(
            insert(ThingUse)
            .values(
                guild_id=guild_id,
                user_id=user_id,
                thing_id=thing_id,
                last_used_at=now,
                use_count=1,
            )
            .on_conflict_do_update(
                index_elements=[ThingUse.guild_id, ThingUse.user_id, ThingUse.thing_id],
                set_={"last_used_at": now, "use_count": ThingUse.use_count + 1},
            )
        )
        await session.commit()

    return UseRecord(
        last_used_at=previous[0] if previous else None,
        use_count=(previous[1] if previous else 0) + 1,
    )


async def last_used_any(
    user_id: int, guild_id: int, thing_ids: Iterable[str]
) -> datetime | None:
    """The most recent use of any one of these, or None for none of them.

    Written for hunger, which is "eight hours since this player's last
    successful feed" and does not care which can it was. A `MAX` over
    the rows rather than a column on the player, because `thing_uses`
    already holds exactly this and a column would be a second place the
    same fact lives.
    """
    wanted = sorted(set(thing_ids))
    if not wanted:
        return None
    session_factory = _require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(func.max(ThingUse.last_used_at)).where(
                ThingUse.guild_id == guild_id,
                ThingUse.user_id == user_id,
                ThingUse.thing_id.in_(wanted),
            )
        )


async def log_interaction(
    guild_id: int,
    *,
    action: str,
    user_id: int | None = None,
    actor: str = PLAYER,
    outcome: str | None = None,
    reason: str | None = None,
    thing_id: str | None = None,
    relationship_delta: int | None = None,
    score_after: int | None = None,
    drop: int | None = None,
    detail: str | None = None,
    now: datetime | None = None,
) -> int | None:
    """Write one row to `interaction_log` and return its id.

    **This never raises.** A telemetry write that fails is a row nobody
    gets to read later; a telemetry write that *throws* turns a pet the
    player already made into an error message, and rolls back the
    command around it. The log is worth a great deal and worth nothing
    at all next to that, so every failure here is logged and swallowed,
    and the caller gets None.

    The timestamp goes through `server_now` like every other dated
    thing in the game, so a QA clock offset moves the log with the
    world rather than leaving the two disagreeing about what day it is.
    """
    session_factory = _session_factory
    if session_factory is None:
        return None
    try:
        stamp = now if now is not None else await server_now(guild_id)
        async with session_factory() as session:
            row = InteractionLog(
                guild_id=guild_id,
                user_id=user_id,
                actor=actor,
                action=action,
                thing_id=thing_id,
                outcome=outcome,
                reason=reason,
                relationship_delta=relationship_delta,
                score_after=score_after,
                drop=drop,
                detail=detail,
                created_at=stamp,
            )
            session.add(row)
            await session.commit()
            return row.id
    except SQLAlchemyError:
        log.exception(
            "Could not log %s/%s for user %s in guild %s",
            action, outcome, user_id, guild_id,
        )
        return None


async def close_interaction(
    log_id: int | None,
    *,
    relationship_delta: int | None = None,
    score_after: int | None = None,
    outcome: str | None = None,
    reason: str | None = None,
    detail: str | None = None,
) -> None:
    """Fill in what a row could not know when it was opened.

    One case needs this: a pet is written inside the same transaction
    that counts the window, so that two rapid pets cannot both read the
    same count - but what the pet was *worth* is decided afterwards, by
    a roll that needs that count as its input. The row therefore exists
    before its delta does.

    Silent on a None id, which is what a failed open returns, and
    silent on its own failure for the same reason as the open.
    """
    if log_id is None:
        return
    values = {
        name: value
        for name, value in (
            ("relationship_delta", relationship_delta),
            ("score_after", score_after),
            ("outcome", outcome),
            ("reason", reason),
            ("detail", detail),
        )
        if value is not None
    }
    if not values:
        return
    session_factory = _session_factory
    if session_factory is None:
        return
    try:
        async with session_factory() as session:
            await session.execute(
                update(InteractionLog)
                .where(InteractionLog.id == log_id)
                .values(**values)
            )
            await session.commit()
    except SQLAlchemyError:
        log.exception("Could not complete interaction_log row %s", log_id)


async def recent_interactions(guild_id: int, user_id: int, limit: int = 10):
    """This player's last few logged rows, newest first.

    For `/qa-inspect`, which is the only way to see the log from inside
    Discord. It is a QA command, so this reads the two test servers -
    where the point is to confirm rows are landing at all before a beta
    server starts producing ones worth analysing.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(InteractionLog)
                    .where(
                        InteractionLog.guild_id == guild_id,
                        InteractionLog.user_id == user_id,
                    )
                    .order_by(InteractionLog.id.desc())
                    .limit(limit)
                )
            ).all()
        )


async def recent_pets(user_id: int, guild_id: int) -> int:
    """How many pets this player has inside the window, without adding one.

    `increment_pet_count` returns the same figure, but only by petting.
    `/stats` has to ask the question without answering it, which is the
    whole difference between a status line and a mood roll.
    """
    session_factory = _require_session()
    cutoff = await server_now(guild_id) - RECENT_PET_WINDOW
    async with session_factory() as session:
        return await session.scalar(_recent_pet_count(user_id, guild_id, cutoff)) or 0


def _recent_pet_count(user_id: int, guild_id: int, cutoff: datetime):
    """The mood roll's question, in one place because it is asked twice.

    Once by `/stats`, which wants the answer without petting, and once
    inside the pet itself, which wants it in the same transaction as
    the row it is about to write.
    """
    return (
        select(func.count())
        .select_from(InteractionLog)
        .where(
            InteractionLog.user_id == user_id,
            InteractionLog.guild_id == guild_id,
            InteractionLog.action == PET,
            InteractionLog.created_at >= cutoff,
        )
    )


async def last_used(user_id: int, guild_id: int, thing_id: str) -> datetime | None:
    """When this player last used a thing, without recording a new use."""
    session_factory = _require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(ThingUse.last_used_at).where(
                ThingUse.guild_id == guild_id,
                ThingUse.user_id == user_id,
                ThingUse.thing_id == thing_id,
            )
        )


# --------------------------------------------------------------------------
# Achievements
#
# Awarding is idempotent and says whether it was the first time, because the
# announcement hangs on that answer. A standing condition - *Cat's Best
# Friend* is true forever once true - would otherwise re-announce on every
# `/pet` for the rest of October.
# --------------------------------------------------------------------------


class RoomTotals(NamedTuple):
    """What one room holds, for the three group achievements.

    All three are the same `GROUP BY room_id` with a different `HAVING`, so
    they are answered together rather than three times per drop. `cat_food` is
    read from the same group as `total`, because *The Feline Collection* needs
    both numbers from the **same** room - 120 cans spread over two rooms that
    each hold 200 things earns nothing.
    """

    room_id: str
    total: int
    most_of_one: int
    cat_food: int


async def room_totals(guild_id: int, cat_food_ids: set[str]) -> list[RoomTotals]:
    """Per-room totals across every room in this server that holds anything.

    Counts `room_contents`, not history. A server that reaches 200 and then
    takes things out keeps the achievement, and a server that reaches 199
    twice earns nothing - both correct.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    RoomContents.room_id,
                    RoomContents.thing_id,
                    func.sum(RoomContents.count),
                )
                .where(RoomContents.guild_id == guild_id)
                .group_by(RoomContents.room_id, RoomContents.thing_id)
            )
        ).all()

    per_room: dict[str, list[int]] = {}
    for room_id, thing_id, count in rows:
        count = int(count or 0)
        totals = per_room.setdefault(room_id, [0, 0, 0])
        totals[0] += count
        totals[1] = max(totals[1], count)
        if thing_id in cat_food_ids:
            totals[2] += count
    return [RoomTotals(room, *numbers) for room, numbers in per_room.items()]


async def carried_total_of(user_id: int, guild_id: int, thing_ids: set[str]) -> int:
    """How many the player holds across a set of things, counting duplicates.

    *Bulk Buyer* sums cat food across flavours; *Catproof the House* counts
    used and sanitized bottles together, so a player who cleans what they
    collect does not lose progress.
    """
    if not thing_ids:
        return 0
    session_factory = _require_session()
    async with session_factory() as session:
        total = await session.scalar(
            select(func.sum(PlayerInventory.count)).where(
                PlayerInventory.user_id == user_id,
                PlayerInventory.guild_id == guild_id,
                PlayerInventory.thing_id.in_(thing_ids),
                PlayerInventory.count > 0,
            )
        )
    return int(total or 0)


async def use_count_of(user_id: int, guild_id: int, thing_id: str) -> int:
    """How many times this player has used a thing. Zero if never."""
    session_factory = _require_session()
    async with session_factory() as session:
        count = await session.scalar(
            select(ThingUse.use_count).where(
                ThingUse.guild_id == guild_id,
                ThingUse.user_id == user_id,
                ThingUse.thing_id == thing_id,
            )
        )
    return int(count or 0)


async def uses_of_any(user_id: int, guild_id: int, thing_ids: Iterable[str]) -> int:
    """How many times this player has used any one of these, in total.

    `toy_plays` by another route: a sum of `use_count` over several rows
    rather than one, because `thing_uses` counts uses per thing and the
    question is about a class of them. The toy version joins on `type`
    because toys are a type; the cans are a set of ids, so this takes
    the ids.

    **Successes only, and that falls out rather than being enforced** -
    `record_use` is the only writer and a refused use returns before it.
    """
    wanted = sorted(set(thing_ids))
    if not wanted:
        return 0
    session_factory = _require_session()
    async with session_factory() as session:
        total = await session.scalar(
            select(func.sum(ThingUse.use_count)).where(
                ThingUse.guild_id == guild_id,
                ThingUse.user_id == user_id,
                ThingUse.thing_id.in_(wanted),
            )
        )
    return int(total or 0)


async def art_urls(guild_id: int) -> dict[str, str]:
    """Every image this server has uploaded, by art_id."""
    session_factory = _require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(ServerArt.art_id, ServerArt.url).where(ServerArt.guild_id == guild_id)
        )
    return {row[0]: row[1] for row in rows}


async def record_art(guild_id: int, art_id: str, url: str) -> None:
    """Remember where an uploaded image ended up."""
    session_factory = _require_session()
    insert = _upsert_statement()
    async with session_factory() as session:
        await session.execute(
            insert(ServerArt)
            .values(guild_id=guild_id, art_id=art_id, url=url)
            .on_conflict_do_update(
                index_elements=[ServerArt.guild_id, ServerArt.art_id],
                set_={"url": url},
            )
        )
        await session.commit()


async def award_player_achievement(
    guild_id: int, user_id: int, achievement_id: str
) -> bool:
    """Award it to one player. True only if this call created the row.

    One statement rather than a read and a write, so two hooks firing for the
    same player at once cannot both conclude they were first and announce
    twice. `ON CONFLICT DO NOTHING` returns no row on the second, which is
    exactly the answer needed.
    """
    session_factory = _require_session()
    insert = _upsert_statement()
    async with session_factory() as session:
        created = await session.scalar(
            insert(PlayerAchievement)
            .values(guild_id=guild_id, user_id=user_id, achievement_id=achievement_id)
            .on_conflict_do_nothing(
                index_elements=[
                    PlayerAchievement.guild_id,
                    PlayerAchievement.user_id,
                    PlayerAchievement.achievement_id,
                ]
            )
            .returning(PlayerAchievement.achievement_id)
        )
        await session.commit()

    if created is not None:
        log.info("Guild %s, player %s earned %s", guild_id, user_id, achievement_id)
    return created is not None


async def award_server_achievement(guild_id: int, achievement_id: str) -> bool:
    """Award it to a whole server. True only if this call created the row."""
    session_factory = _require_session()
    insert = _upsert_statement()
    async with session_factory() as session:
        created = await session.scalar(
            insert(ServerAchievement)
            .values(guild_id=guild_id, achievement_id=achievement_id)
            .on_conflict_do_nothing(
                index_elements=[
                    ServerAchievement.guild_id,
                    ServerAchievement.achievement_id,
                ]
            )
            .returning(ServerAchievement.achievement_id)
        )
        await session.commit()

    if created is not None:
        log.info("Guild %s earned %s", guild_id, achievement_id)
    return created is not None


async def relationship_ranking(guild_id: int) -> list[tuple[int, int]]:
    """(player, score) for everyone in this server who has met the cat, best first.

    **Players who have never touched her are left out.** Without that,
    day one is a wall of zeroes in whatever order the rows were created,
    which is a list of who happens to be in the Discord rather than a
    leaderboard. The test is `last_cat_interaction_date`, which every
    pet, play, fluff and feed stamps - attempts included - plus a pet
    count for anybody who played before that column existed.

    **Ties break on the older row**, so two players on the same score do
    not swap places between one viewing and the next. `created_at` is
    the row's birth, which is the first pet or the first way in: near
    enough to "first interaction" to order by, and the only such date
    stored.

    Whole server in one list. A few dozen rows is not worth paginating
    in SQL, and the caller needs the full order anyway to say where the
    viewer sits in it.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(User.id, User.relationship)
            .where(
                User.guild_id == guild_id,
                or_(
                    User.last_cat_interaction_date.is_not(None),
                    User.pet_count > 0,
                ),
            )
            .order_by(User.relationship.desc(), User.created_at.asc(), User.id.asc())
        )
    return [(row[0], row[1]) for row in rows]


async def recent_achievements(
    guild_id: int, limit: int
) -> list[tuple[str, int | None, datetime]]:
    """The last few earned here: (achievement, who earned it, when).

    `None` for the player on a server achievement, which has no earner
    by design - nobody is credited and everyone holds it.

    **No new column.** `earned_at` has been on both tables since they
    were written, which is the whole answer to "find a way to list the
    last five": a rolling five-row list would throw away the history
    the telemetry plan wants and add a pruning rule that can be wrong.

    Ties break on the id, because Postgres gives two awards in one
    transaction the same `now()` and the list has to render the same way
    twice. `_earned_lines` already breaks ties the same way.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        mine = await session.execute(
            select(
                PlayerAchievement.achievement_id,
                PlayerAchievement.user_id,
                PlayerAchievement.earned_at,
            ).where(PlayerAchievement.guild_id == guild_id)
        )
        ours = await session.execute(
            select(
                ServerAchievement.achievement_id,
                ServerAchievement.earned_at,
            ).where(ServerAchievement.guild_id == guild_id)
        )

    rows = [(row[0], row[1], row[2]) for row in mine]
    rows += [(row[0], None, row[1]) for row in ours]
    rows.sort(key=lambda row: (row[2], row[0]), reverse=True)
    return rows[:limit]


async def player_achievements_of(guild_id: int, user_id: int) -> dict[str, datetime]:
    """What this player has earned here, and when."""
    session_factory = _require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(
                PlayerAchievement.achievement_id, PlayerAchievement.earned_at
            ).where(
                PlayerAchievement.guild_id == guild_id,
                PlayerAchievement.user_id == user_id,
            )
        )
    return {row[0]: row[1] for row in rows}


async def server_achievements_of(guild_id: int) -> dict[str, datetime]:
    """What this whole server has earned, and when.

    Shown in every current member's `/stats`, which is why it is read by
    guild alone and never joined to a user.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(
                ServerAchievement.achievement_id, ServerAchievement.earned_at
            ).where(ServerAchievement.guild_id == guild_id)
        )
    return {row[0]: row[1] for row in rows}


async def distinct_users_of(guild_id: int, thing_id: str) -> int:
    """How many different players have used a thing in this server.

    The staircase counts planks by distinct player, so somebody using lumber
    twice still contributes one.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        return (
            await session.scalar(
                select(func.count(func.distinct(ThingUse.user_id))).where(
                    ThingUse.guild_id == guild_id, ThingUse.thing_id == thing_id
                )
            )
        ) or 0


# --------------------------------------------------------------------------
# Listings: what `/look` shows in a room or inside a container
# --------------------------------------------------------------------------


async def loose_here(
    guild_id: int,
    room_id: str,
    container_id: str = LOOSE_IN_ROOM,
    *,
    held_states: set[str] | None = None,
) -> list[tuple[str, int]]:
    """(name, count) for the takeable things lying out in a room or container.

    Takeable and finite only. A source is never listed anywhere - it is
    inexhaustible, and the prose that reveals it is what a player reads instead,
    which the loader checks. Fixtures and exits are not listed either: they are
    the room, not things in it.

    Passing a container_id lists what is inside that container rather than what
    is loose in the room, which is the same rule applied one level down.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(ThingType.name, RoomContents.count, ThingType.present_when)
            .join(ThingType, ThingType.thing_id == RoomContents.thing_id)
            .where(
                RoomContents.guild_id == guild_id,
                RoomContents.room_id == room_id,
                RoomContents.container_id == container_id,
                RoomContents.count > 0,
                ThingType.takeable.is_(True),
            )
            .order_by(ThingType.sort_order, ThingType.name)
        )
        # Filtered here rather than in SQL: a gate is a small expression over
        # states already in hand, and the row counts are tiny.
        import states as _states

        held = held_states or set()
        return [
            (row[0], row[1]) for row in rows if _states.passes(row[2], held)
        ]


async def states_of(guild_id: int, user_id: int) -> set[str]:
    """Every state in force for this player: their own, plus the server's.

    Nothing sets either in 2c - the staircase and the drawer are 2c.5 - so this
    is empty today and every lookup falls through to `default`. It is wired now
    so the text resolution is already correct when states start being set.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        mine = await session.execute(
            select(PlayerState.state).where(
                PlayerState.guild_id == guild_id, PlayerState.user_id == user_id
            )
        )
        shared = await session.execute(
            select(ServerState.state).where(ServerState.guild_id == guild_id)
        )
        return {row[0] for row in mine} | {row[0] for row in shared}


# --------------------------------------------------------------------------
# Per-server settings an admin can retune
#
# A registry rather than a Literal on the command, deliberately. Slash command
# signatures cost an hour of propagation to change, so a new key should be a
# code change and not a re-registration. The trade is that a typo comes back as
# a refusal listing the real keys rather than as a dropdown that never offered
# the wrong one.
# --------------------------------------------------------------------------

CONFIG_KEYS: dict[str, tuple[int, str]] = {
    "planks_required": (
        10,
        "How many different players must place a plank before the staircase is "
        "repaired.",
    ),
    "bottles_per_day": (
        8,
        "How many used baby bottles are scattered through the house each day.",
    ),
    "toys_present": (
        2,
        "How many cat toys the channel is kept topped up to.",
    ),
    # All three are here rather than in code because they are the
    # drop's balance, and the whole argument for the config history is
    # that a number you retune mid-beta has to leave a dated trace -
    # otherwise the interaction rows from before and after it cannot be
    # told apart.
    "toy_base_points": (
        10,
        "What the first successful toy play of the day is worth. Each one "
        "after it pays less.",
    ),
    # **A percentage because this registry holds integers**, and
    # `/admin_config` takes a whole number of at least one. The
    # quantity is a ratio - each play is worth this much of the one
    # before - and the name says percent so that nobody retuning it
    # types 0.75 and silently turns every play after the first into
    # nothing.
    "toy_daily_decay_percent": (
        75,
        "What each toy play is worth as a percentage of the one before it, "
        "within the same day.",
    ),
    "toy_cooldown_minutes": (
        10,
        "How long after a successful play before the cat will play again.",
    ),
    # **Declared, never derived**, and that is the whole reason it is a
    # setting rather than a query. The collection achievement that reads
    # it wants every toy *planned for the game*; a count of the toy rows
    # in `things.tsv` reads as 2 while only drop 2's two exist, which
    # would award it on a player's first successful play.
    #
    # Seeded now though nothing reads it yet, so the figure is agreed
    # once here rather than invented by whoever builds the drop that
    # needs it. Raising it later must not take the award back from
    # anybody already holding it.
    # The craving is worth less than a toy play on purpose. Copying
    # somebody else's correct guess is a reaction away, and that is
    # fine - the game is a thing to notice, not a thing to solve - so
    # the figure has to be small enough that copying it is not the
    # cheapest relationship in the game.
    # Minutes between membership sweeps. A number rather than a constant
    # because it is the kind of thing that wants turning down for an hour
    # while somebody watches it work, and turning back up afterwards -
    # and a deploy to do that is a deploy nobody makes.
    "thread_sweep_minutes": (
        60,
        "How often the bot checks that every room thread holds exactly the "
        "players standing in that room.",
    ),
    "craving_points": (
        5,
        "What finding the cat's daily craving is worth, once per player per "
        "day.",
    ),
    "toy_set_total": (
        13,
        "How many cat toys the whole game will have. Used by the toy-collection "
        "achievement, which counts toward a declared total rather than the toys "
        "that have arrived so far.",
    ),
}


# --------------------------------------------------------------------------
# What a player has already been told
# --------------------------------------------------------------------------


async def notice(guild_id: int, user_id: int, notice_id: str) -> bool:
    """Record that this player has been told one thing. False if they had.

    The return value is the whole point for a hint: it fires on the
    transition, so a caller can say "if await notice(...)" and append the
    line only the first time.
    """
    session_factory = _require_session()
    insert = _upsert_statement()
    stmt = (
        insert(PlayerNotice)
        .values(guild_id=guild_id, user_id=user_id, notice_id=notice_id)
        .on_conflict_do_nothing(
            index_elements=[
                PlayerNotice.guild_id,
                PlayerNotice.user_id,
                PlayerNotice.notice_id,
            ]
        )
        .returning(PlayerNotice.id)
    )
    try:
        async with session_factory() as session:
            created = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
            return created is not None
    except SQLAlchemyError:
        # Decoration on something that has already happened. Losing the
        # row means a hint may be shown twice, which is better than
        # failing the command that carried it.
        log.exception("Could not record notice %s for %s", notice_id, user_id)
        return False


async def has_been_told(guild_id: int, user_id: int, notice_id: str) -> bool:
    session_factory = _require_session()
    async with session_factory() as session:
        found = await session.scalar(
            select(PlayerNotice.id).where(
                PlayerNotice.guild_id == guild_id,
                PlayerNotice.user_id == user_id,
                PlayerNotice.notice_id == notice_id,
            )
        )
    return found is not None


async def notices_with_prefix(guild_id: int, user_id: int, prefix: str) -> set[str]:
    """Every notice this player holds whose id starts with `prefix`.

    `has_been_told` answers one id at a time, which is right for a hint
    rung and wrong for a set: marking the new sentences in a room asks
    about every fragment in it at once, and a query per sentence is a
    query per sentence.

    The caller owns the id format. This knows only that ids are strings
    with a shape somebody else chose.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        rows = await session.scalars(
            select(PlayerNotice.notice_id).where(
                PlayerNotice.guild_id == guild_id,
                PlayerNotice.user_id == user_id,
                PlayerNotice.notice_id.startswith(prefix),
            )
        )
        return set(rows)


async def last_logged_at(guild_id: int, action: str) -> datetime | None:
    """When this server last logged one kind of action. None for never.

    Through `created_at`, which goes through `server_now` like every
    other dated column here, so a QA clock offset moves it with
    everything else.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(func.max(InteractionLog.created_at)).where(
                InteractionLog.guild_id == guild_id,
                InteractionLog.action == action,
            )
        )


async def notices_of(
    guild_id: int, user_id: int, notice_ids: Iterable[str]
) -> set[str]:
    """Which of these this player holds. One query for the lot.

    `has_been_told` is right for one rung of the hint ladder and wrong
    for a question made of several: deciding which fragments of a room
    a player can see asks about four unrelated ids at once, and four
    round trips to answer one `/look` is three too many.

    Unlike `notices_with_prefix` the ids need share nothing, which is
    the point - the four this was written for are two hint flags and
    two visibility gates.
    """
    wanted = sorted(set(notice_ids))
    if not wanted:
        return set()
    session_factory = _require_session()
    async with session_factory() as session:
        rows = await session.scalars(
            select(PlayerNotice.notice_id).where(
                PlayerNotice.guild_id == guild_id,
                PlayerNotice.user_id == user_id,
                PlayerNotice.notice_id.in_(wanted),
            )
        )
        return set(rows)


async def notice_many(guild_id: int, user_id: int, notice_ids: Iterable[str]) -> None:
    """Record several at once, ignoring the ones already there.

    No return value, unlike `notice`: that one reports the transition
    because a hint fires on it. Here the caller has already worked out
    which ids are new - that is what decided the formatting - and is
    writing them down afterwards.

    Swallows its errors for the same reason `notice` does. A lost row
    means a sentence is marked new twice, which is better than failing
    the `/look` that carried it.
    """
    wanted = sorted(set(notice_ids))
    if not wanted:
        return
    session_factory = _require_session()
    insert = _upsert_statement()
    stmt = (
        insert(PlayerNotice)
        .values([
            {"guild_id": guild_id, "user_id": user_id, "notice_id": one}
            for one in wanted
        ])
        .on_conflict_do_nothing(
            index_elements=[
                PlayerNotice.guild_id,
                PlayerNotice.user_id,
                PlayerNotice.notice_id,
            ]
        )
    )
    try:
        async with session_factory() as session:
            await session.execute(stmt)
            await session.commit()
    except SQLAlchemyError:
        log.exception("Could not record notices %s for %s", wanted, user_id)


async def notice_order(guild_id: int, user_id: int) -> dict[str, int]:
    """Everything this player has been told, by the order it was told.

    The id rather than the timestamp: two notices written in one
    transaction share a `now()` in Postgres, and the order still has to
    be total for `/stats` to render the same way twice.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(PlayerNotice.notice_id, PlayerNotice.id).where(
                PlayerNotice.guild_id == guild_id,
                PlayerNotice.user_id == user_id,
            )
        )
    return {notice_id: row_id for notice_id, row_id in rows}


async def play_state(guild_id: int, user_id: int) -> tuple[int, datetime | None]:
    """This player's ramp, and when their cooldown lifts."""
    session_factory = _require_session()
    async with session_factory() as session:
        row = (
            await session.execute(
                select(User.toy_ramp, User.toy_cooldown_until).where(
                    User.id == user_id, User.guild_id == guild_id
                )
            )
        ).first()
    return (row[0], row[1]) if row else (0, None)


async def record_play(
    guild_id: int, user_id: int, *, succeeded: bool, cooldown_until: datetime | None
) -> int:
    """Move the ramp after an attempt, and return where it landed.

    A success resets it to zero and starts the cooldown; a refusal
    advances it one rung and starts nothing. An attempt made *inside*
    the cooldown never reaches here - it advances nothing, which is what
    stops a player banking four refusals and converting the moment it
    lifts.
    """
    ramp = 0 if succeeded else await _bump_ramp(guild_id, user_id)
    session_factory = _require_session()
    async with session_factory() as session:
        values = {"toy_ramp": ramp, "updated_at": func.now()}
        if succeeded:
            values["toy_cooldown_until"] = cooldown_until
        await session.execute(
            update(User)
            .where(User.id == user_id, User.guild_id == guild_id)
            .values(**values)
        )
        await session.commit()
    return ramp


async def count_toy_play(guild_id: int, user_id: int, today: date) -> int:
    """Record one successful play and say which of the day's it is.

    Returns a 1-based index, so the first play of the day is 1 - which
    is the `n` the paying curve is written in terms of. The caller
    works out what that is worth; this only knows how far down the day
    the player has got.

    **The day rolls over on the read.** A stamp from an earlier day
    counts as no plays yet, so there is no nightly sweep to write and
    no server that misses one because the bot was down.

    Counted here rather than derived from `interaction_log`, which
    could answer the same question: a derived count would make the
    curve depend on a table that started empty, and this one has to be
    right from the first play of drop 2.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        row = (
            await session.execute(
                select(User.toy_plays_date, User.toy_plays_today).where(
                    User.id == user_id, User.guild_id == guild_id
                )
            )
        ).one_or_none()
        stamped, played = row if row is not None else (None, 0)
        nth = (played if stamped == today else 0) + 1

        await session.execute(
            update(User)
            .where(User.id == user_id, User.guild_id == guild_id)
            .values(
                toy_plays_date=today,
                toy_plays_today=nth,
                updated_at=func.now(),
            )
        )
        await session.commit()
    return nth


async def toy_plays_today(guild_id: int, user_id: int, today: date) -> int:
    """How many successful plays this player has had today."""
    session_factory = _require_session()
    async with session_factory() as session:
        row = (
            await session.execute(
                select(User.toy_plays_date, User.toy_plays_today).where(
                    User.id == user_id, User.guild_id == guild_id
                )
            )
        ).one_or_none()
    if row is None or row[0] != today:
        return 0
    return row[1]


async def set_toy_plays(guild_id: int, user_id: int, count: int) -> str | None:
    """Put this player's lifetime toy-play count at `count`, for QA.

    Returns the toy the count was written against, or None if the
    content has no toys to write it to.

    **Written as a use count on one toy rather than as rows.**
    `toy_plays` sums `use_count` over the player's toy rows, so one row
    holding the whole figure answers it exactly - and the alternative,
    inserting `count` separate rows, would be slower and no more
    truthful, because `thing_uses` keeps a count and not a history.

    It deliberately does **not** touch the day's play count or the
    interaction log. A lifetime total is what *Tireless* reads; where a
    player sits on today's paying curve is a different question with
    its own lever.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        toy = await session.scalar(
            select(ThingType.thing_id).where(ThingType.type == "toy").order_by(
                ThingType.thing_id
            )
        )
        if toy is None:
            return None
        insert = _upsert_statement()
        await session.execute(
            insert(ThingUse)
            .values(
                guild_id=guild_id,
                user_id=user_id,
                thing_id=toy,
                last_used_at=await server_now(guild_id),
                use_count=count,
            )
            .on_conflict_do_update(
                index_elements=[ThingUse.guild_id, ThingUse.user_id, ThingUse.thing_id],
                set_={"use_count": count},
            )
        )
        await session.commit()
    return toy


async def set_toy_plays_today(guild_id: int, user_id: int, count: int) -> None:
    """Put this player `count` plays into today's paying curve, for QA.

    The lever for the far end of the curve. Set it to eleven and the
    next successful play is worth nothing, which is the state two
    achievements and a good deal of copy depend on and which otherwise
    costs eleven plays and an hour of cooldowns to reach.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        await session.execute(
            update(User)
            .where(User.id == user_id, User.guild_id == guild_id)
            .values(
                toy_plays_date=await server_today(guild_id),
                toy_plays_today=count,
                updated_at=func.now(),
            )
        )
        await session.commit()


async def _bump_ramp(guild_id: int, user_id: int) -> int:
    current, _ = await play_state(guild_id, user_id)
    return current + 1


async def set_play_ramp(guild_id: int, user_id: int, ramp: int) -> None:
    """Put the ramp at an exact rung. For `/qa-state` only."""
    session_factory = _require_session()
    async with session_factory() as session:
        await session.execute(
            update(User)
            .where(User.id == user_id, User.guild_id == guild_id)
            .values(toy_ramp=ramp)
        )
        await session.commit()


async def clear_play_state(guild_id: int, user_id: int) -> None:
    """Forget the ramp, the cooldown and the day's play count.

    For `/qa-cooldown`. The count goes with the other two because it
    blocks testing in the same way they do: a tester eleven plays into
    a day cannot see what a full-value play looks like until tomorrow,
    which is the same afternoon the cooldown used to cost them.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        await session.execute(
            update(User)
            .where(User.id == user_id, User.guild_id == guild_id)
            .values(
                toy_ramp=0,
                toy_cooldown_until=None,
                toy_plays_date=None,
                toy_plays_today=0,
            )
        )
        await session.commit()


async def clear_unreachable_room_contents(
    guild_id: int, arrived_drops: set[int], arrived_rooms: set[str]
) -> int:
    """Delete room contents nobody on this server could reach, and count them.

    **One rule, three ways to break it.** A row is unreachable when the
    room it is in has not arrived here, when the thing itself has not,
    or when the container holding it has not - and in every case a
    player standing where they are allowed to stand cannot see it, take
    it or be told it is there.

    It exists because the restock scheduler spent a month not reading
    the drop column it was given. Eight used baby bottles a day, drop 30
    content, scattered across servers on drop 3: most of them into rooms
    whose prose nobody can read yet, where they sat as rows waiting to
    surface the day the room opened holding a month of litter, and the
    rest into the Entryway where the room listed them under `Also here:`
    and no word reached them. Stopping the scheduler stops it growing;
    this is what clears what is already there.

    **Room contents only.** What a player is carrying is theirs, and a
    bag emptied by a background job is worse than a bag with something
    odd in it - the same reason the thread sweep moves people rather
    than taking their things.

    `arrived_rooms` is the caller's to compute, because which rooms exist
    is a question about prose and this module does not read content. The
    channel belongs in it on every drop: standing on the road is valid
    from drop 0, before the road has its own first fragment.
    """
    # Nothing arrived is a server with no game - one the bot is only a
    # member of. It has no reachable rooms at all, so the rule would
    # empty it; there is nothing there to clear, and a sweep that treats
    # "no pointer" as "delete everything" is one bad migration away from
    # being a disaster.
    if not arrived_drops or not arrived_rooms:
        return 0

    too_new = select(ThingType.thing_id).where(
        ThingType.since_drop.not_in(sorted(arrived_drops))
    )
    session_factory = _require_session()
    async with session_factory() as session:
        result = await session.execute(
            delete(RoomContents).where(
                RoomContents.guild_id == guild_id,
                or_(
                    RoomContents.room_id.not_in(sorted(arrived_rooms)),
                    RoomContents.thing_id.in_(too_new),
                    # LOOSE_IN_ROOM is the empty string and no thing
                    # answers to it, so a loose row never matches here
                    # and needs no second condition to say so.
                    RoomContents.container_id.in_(too_new),
                ),
            )
        )
        await session.commit()
    return result.rowcount or 0


async def place_in_room(guild_id: int, room_id: str, thing_id: str, amount: int) -> None:
    """Put something loose on a room's floor, from outside the scheduler.

    The bed stash uses it. Deliberately not routed through the restock
    path: the cap governs the scheduler, and a thing the game hands a
    player directly is not the scheduler's to tidy away.
    """
    session_factory = _require_session()
    insert = _upsert_statement()
    async with session_factory() as session:
        await session.execute(
            _add_to_room(insert, guild_id, room_id, LOOSE_IN_ROOM, thing_id, amount)
        )
        await session.commit()


async def count_of_type(guild_id: int, room_id: str, kind: str) -> int:
    """How many things of one kind are lying in a room.

    **Counted across the class, not per row.** The rule is *keep two
    toys in the channel*, not *keep two of each toy*: per row, drop 2's
    two toys would already allow four, and the thirteen already written
    would allow twenty-six and turn `Also here:` into a wall of nouns.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        total = await session.scalar(
            select(func.sum(RoomContents.count))
            .select_from(RoomContents)
            .join(ThingType, ThingType.thing_id == RoomContents.thing_id)
            .where(
                RoomContents.guild_id == guild_id,
                RoomContents.room_id == room_id,
                ThingType.type == kind,
            )
        )
    return int(total or 0)


async def ids_of_type(kind: str, arrived: set[int]) -> list[str]:
    """Every thing of one kind whose drop has arrived, in a stable order.

    The pool a class selector draws from. Ordered so a seeded draw gives
    the same answer twice, which is what makes a restock reproducible.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(ThingType.thing_id, ThingType.since_drop)
            .where(ThingType.type == kind)
            .order_by(ThingType.sort_order, ThingType.thing_id)
        )
    return [thing_id for thing_id, since_drop in rows if since_drop in arrived]


async def present_of_type(guild_id: int, room_id: str, kind: str) -> list[str]:
    """Names of things of one kind actually lying in a room, in order.

    Reads `room_contents` rather than a thing's home room: a toy's home
    is the channel, but whether one is *there* changes as players take
    them, and the hint that names one has to name one that is present.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        rows = await session.execute(
            select(ThingType.name)
            .select_from(RoomContents)
            .join(ThingType, ThingType.thing_id == RoomContents.thing_id)
            .where(
                RoomContents.guild_id == guild_id,
                RoomContents.room_id == room_id,
                RoomContents.count > 0,
                ThingType.type == kind,
                ThingType.takeable.is_(True),
            )
            .order_by(ThingType.sort_order, ThingType.thing_id)
        )
    return [row[0] for row in rows]


async def toy_plays(guild_id: int, user_id: int) -> int:
    """How many times this player has successfully played with any toy.

    A sum of `use_count` rather than a count of rows: `thing_uses` holds
    one row per (player, thing) and counts the uses on it, so the rows
    answer *how many toys* and the sum answers *how many plays*. The
    three collection achievements want both - 25 plays here, 5 and 13
    distinct toys later - and both come off this one table without a
    history table or a counter of their own.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        total = await session.scalar(
            select(func.sum(ThingUse.use_count))
            .select_from(ThingUse)
            .join(ThingType, ThingType.thing_id == ThingUse.thing_id)
            .where(
                ThingUse.guild_id == guild_id,
                ThingUse.user_id == user_id,
                ThingType.type == "toy",
            )
        )
    return int(total or 0)


async def free_toy_plays(guild_id: int, user_id: int) -> int:
    """Successful toy plays that paid nothing, ever.

    **Counted from the interaction log**, which is the only table that
    knows what a play was worth: `thing_uses` counts plays and cannot
    tell a ten-point one from a nothing one. Safe to derive because
    the behaviour starts when drop 2 opens and the log was already
    there - the rule everywhere else is that a count comes off the log
    only when nothing could have happened before the log existed.

    Joined on the thing's type rather than filtered on the delta
    alone: nothing but a toy writes an integer delta on a `use` today,
    but that is an invariant across two modules rather than a fact
    about this query, and it would fail silently.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(func.count())
            .select_from(InteractionLog)
            .join(ThingType, ThingType.thing_id == InteractionLog.thing_id)
            .where(
                InteractionLog.guild_id == guild_id,
                InteractionLog.user_id == user_id,
                InteractionLog.action == USE,
                InteractionLog.outcome == SUCCESS,
                InteractionLog.relationship_delta == 0,
                ThingType.type == "toy",
            )
        ) or 0


async def clear_setting(guild_id: int, key: str) -> None:
    """Close the standing window, so the next read falls back to its default.

    **The history is not deleted.** Unsetting a value is itself a
    tuning decision and dated like any other - a window that closed
    with nothing after it says "from here, the default", which is the
    truth and is exactly what an analysis needs to read.
    """
    now = await server_now(guild_id)
    session_factory = _require_session()
    async with session_factory() as session:
        await session.execute(
            update(ConfigHistory)
            .where(
                ConfigHistory.guild_id == guild_id,
                ConfigHistory.key == key,
                ConfigHistory.effective_to.is_(None),
            )
            .values(effective_to=now)
        )
        await session.commit()


async def last_cat_interaction(guild_id: int, user_id: int) -> date | None:
    """The last day this player touched the cat here, for `/qa-inspect`."""
    session_factory = _require_session()
    async with session_factory() as session:
        return await session.scalar(
            select(User.last_cat_interaction_date).where(
                User.id == user_id, User.guild_id == guild_id
            )
        )


async def forget_player(guild_id: int, user_id: int) -> dict[str, int]:
    """Wipe one player from one server, and say what went.

    **Including the hint rows**, which is the half that is easy to
    forget and the half that matters: without them the hint ladder is
    one-shot per tester per server, and the second run through the
    tutorial is silent.

    Scoped to tables that carry both a guild and a user. A server-wide
    row is not this player's to delete - resetting one tester must not
    un-repair the staircase for everybody.
    """
    cleared: dict[str, int] = {}
    session_factory = _require_session()
    async with session_factory() as session:
        for table in reversed(Base.metadata.sorted_tables):
            columns = table.c
            if "guild_id" not in columns:
                continue
            who = next((c for c in ("user_id", "id") if c in columns), None)
            if who is None or (who == "id" and table.name != "users"):
                continue
            result = await session.execute(
                table.delete().where(
                    columns.guild_id == guild_id, columns[who] == user_id
                )
            )
            if result.rowcount:
                cleared[table.name] = result.rowcount
        await session.commit()
    log.info("QA wiped player %s in guild %s: %s", user_id, guild_id, cleared)
    return cleared


async def set_relationship(guild_id: int, user_id: int, score: int) -> int:
    """Put the meter at an exact value. For `/qa-relationship` only -
    fifty and two hundred and fifty are days of honest play away."""
    session_factory = _require_session()
    async with session_factory() as session:
        await session.execute(
            update(User)
            .where(User.id == user_id, User.guild_id == guild_id)
            .values(relationship=score, updated_at=func.now())
        )
        await session.commit()
    return score


async def clear_cooldowns(guild_id: int, user_id: int) -> int:
    """Forget every cooldown this player is inside.

    The bed's twenty-four hours live in `thing_uses`; the ten-minute pet
    window is a count of recent `pet` rows in the interaction log, so those
    rows go too. The lifetime pet count on the user row is left alone - it is
    progress, not a cooldown, and a tester clearing a window should not lose
    their march on two hundred.

    **It costs telemetry, and that is the right trade here.** Deleting the
    rows is the only way to clear a window counted from them, and the
    alternative - backdating them - would put a lie in the log instead of a
    hole. This is a QA command, so the rows it destroys are on the two test
    servers whose data is excluded from the analysis anyway.
    """
    session_factory = _require_session()
    cleared = 0
    async with session_factory() as session:
        result = await session.execute(
            ThingUse.__table__.delete().where(
                ThingUse.guild_id == guild_id, ThingUse.user_id == user_id
            )
        )
        cleared += result.rowcount or 0
        result = await session.execute(
            delete(InteractionLog).where(
                InteractionLog.guild_id == guild_id,
                InteractionLog.user_id == user_id,
                InteractionLog.action == PET,
            )
        )
        cleared += result.rowcount or 0
        await session.commit()
    return cleared


def _live_value(guild_id: int, key: str):
    """The standing row for one key: the window nobody has closed."""
    return select(ConfigHistory.value).where(
        ConfigHistory.guild_id == guild_id,
        ConfigHistory.key == key,
        ConfigHistory.effective_to.is_(None),
    )


async def get_config_raw(guild_id: int, key: str) -> str | None:
    """One setting exactly as stored, or None if this server has never set it.

    `get_setting` answers with a default, which is right for a tunable and
    wrong for the drop pointer: there, "never set" is a state of its own and
    0 is a real drop.
    """
    session_factory = _require_session()
    async with session_factory() as session:
        return await session.scalar(_live_value(guild_id, key))


async def get_setting(guild_id: int, key: str) -> int:
    """A server's value for a numeric setting, or its default.

    A value that will not parse falls back to the default and says so, rather
    than taking a command down over a row somebody hand-edited.
    """
    default, _ = CONFIG_KEYS.get(key, (0, ""))
    session_factory = _require_session()
    async with session_factory() as session:
        raw = await session.scalar(_live_value(guild_id, key))
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning(
            "server_config %s is %r in guild %s, which is not a number; using %s",
            key,
            raw,
            guild_id,
            default,
        )
        return default


async def set_announcement_channel(guild_id: int, channel_id: int) -> None:
    """Record where this server's achievements are announced.

    Written every time the house is initialized rather than only the first
    time, so moving the house to another channel moves the announcements with
    it. If the bot can post the rooms there it can post the names there.
    """
    await set_config(guild_id, CONFIG_ANNOUNCE_CHANNEL, str(channel_id))
    log.info("Guild %s announces achievements in channel %s", guild_id, channel_id)


async def announcement_channel(guild_id: int) -> int | None:
    """Where to post an achievement name, or None if never initialized."""
    session_factory = _require_session()
    async with session_factory() as session:
        raw = await session.scalar(_live_value(guild_id, CONFIG_ANNOUNCE_CHANNEL))
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        log.warning("Guild %s has a non-numeric announce channel %r", guild_id, raw)
        return None


async def set_setting(guild_id: int, key: str, value: int) -> int:
    """Store a setting and return it. Takes effect from the next read."""
    return int(await set_config(guild_id, key, str(value)))


CONFIG_CONTENT_VERSION = "content_version"


async def record_content_version(guild_id: int, version: str) -> bool:
    """Date this server's content, if it has changed. True when it had.

    **Only on a change.** `set_config` deliberately writes a row even
    when the value repeats, because setting a number back to itself is
    still a decision somebody made. This is not a decision - it runs on
    every boot - so a server that restarts twice an hour would collect
    a row an hour saying nothing happened, and the one question the
    column exists to answer, *when did the content last change*, would
    be buried in them.
    """
    if await get_config_raw(guild_id, CONFIG_CONTENT_VERSION) == version:
        return False
    await set_config(guild_id, CONFIG_CONTENT_VERSION, version)
    return True


async def set_config(guild_id: int, key: str, value: str) -> str:
    """Close the standing window for this key and open the next one.

    **Both halves in one transaction**, because the invariant the whole
    table rests on is that exactly one window per `(guild, key)` is
    open. A crash between the two would leave either two live rows,
    where which one wins depends on row order, or none, where the
    setting silently reverts to its default.

    Writing the same value again still closes and reopens. That looks
    wasteful and is not: *somebody set the decay rate on the 14th* is a
    fact worth having even when they set it to what it already was, and
    a row costs nothing.
    """
    now = await server_now(guild_id)
    session_factory = _require_session()
    async with session_factory() as session:
        await session.execute(
            update(ConfigHistory)
            .where(
                ConfigHistory.guild_id == guild_id,
                ConfigHistory.key == key,
                ConfigHistory.effective_to.is_(None),
            )
            .values(effective_to=now)
        )
        session.add(
            ConfigHistory(
                guild_id=guild_id, key=key, value=value, effective_from=now
            )
        )
        await session.commit()
    log.info("Guild %s set %s to %s", guild_id, key, value)
    return value


async def all_settings(guild_id: int) -> dict[str, int]:
    """Every known setting for a server, defaults filled in."""
    return {key: await get_setting(guild_id, key) for key in CONFIG_KEYS}
