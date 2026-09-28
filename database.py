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

# A real zone, not a fixed offset, so midnight stays midnight across DST.
PACIFIC = ZoneInfo("America/Los_Angeles")

RELATIONSHIP_MIN = -100
RELATIONSHIP_MAX = 100

# Where a brand-new player starts. Above neutral, so the cat is friendly by
# default and has to be annoyed into hostility - but this is a starting point,
# not a resting one: the nightly decay below still pulls an inactive player back
# to 0, so a new player who never returns drifts to neutral over five days.
# Referenced by both the model default and the ALTER in _add_missing_columns;
# keep them reading from here so the two cannot disagree.
RELATIONSHIP_START = 50

# Nightly drift back toward neutral, applied only to users who did not pet that day.
DECAY_POSITIVE_THRESHOLD = 10   # at or above this, affection fades...
DECAY_POSITIVE_STEP = 10        # ...by this much, never past 0
DECAY_NEGATIVE_THRESHOLD = -20  # at or below this, grudges soften...
DECAY_NEGATIVE_STEP = 20        # ...by this much, never past 0

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


class GameState(NamedTuple):
    """A player's position in one server's haunted house."""

    user_id: int
    guild_id: int
    current_room: str
    rooms_unlocked: list[str]


class DecayChange(NamedTuple):
    """One player's relationship movement in one server during a nightly decay run."""

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
    """Today's calendar date in Pacific time, which is what the decay runs on."""
    return datetime.now(PACIFIC).date()


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
    # Last Pacific day the nightly decay was evaluated for this row. Lets the
    # bot catch up on days it was offline without double-applying any of them.
    last_decay_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PetEvent(Base):
    """One row per pet, used to count activity inside a sliding time window.

    The `users` table only carries a lifetime total, which cannot answer "how
    many pets in the last ten minutes" - that needs per-pet timestamps.
    """

    __tablename__ = "pet_events"
    __table_args__ = (
        Index("ix_pet_events_guild_user_time", "guild_id", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # The relationship score as it stood *before* this pet applied. Two
    # achievements count 200 pets while the relationship was positive or
    # negative, and no other table can answer that after the fact - the score is
    # a running total, so history cannot be reconstructed from it. Recorded now,
    # ahead of the achievements themselves, because the only moment backfill is
    # free is before a real server starts petting. Rows written before this
    # column existed read 0; reset_db.py is the intended way past that.
    relationship_at_pet: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


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
    """A room's description for one state, at one drop."""

    __tablename__ = "room_text"

    room_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    since_drop: Mapped[int] = mapped_column(Integer, primary_key=True)
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


class DefaultText(Base):
    """House fallback strings, used wherever a content cell is blank."""

    __tablename__ = "defaults"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    text_value: Mapped[str] = mapped_column("text", Text, nullable=False)


class EmojiGroup(Base):
    """The craving lookup, from emoji_groups.tsv.

    Content like any other: global, replaced wholesale on load, never mutated
    at runtime. `drawable` is separate from `subgroup` so a plate can never be
    the craving while still resolving to a known group - which is what lets a
    player guess one and get a straight "no" rather than an error.
    """

    __tablename__ = "emoji_groups"

    emoji: Mapped[str] = mapped_column(String(32), primary_key=True)
    subgroup: Mapped[str] = mapped_column(String(32), nullable=False)
    drawable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


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
    container: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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
    """

    __tablename__ = "server_config"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)


class ThingUse(Base):
    """One row per (player, thing): when they last used it, and how many times.

    Three jobs in one table. `last_used_at` answers the 48-hour lumber cooldown;
    counting distinct rows for a thing answers "{n} of {total} repairs done", which
    the staircase needs by distinct player; and `use_count` answers "do this N
    times" achievements, of which ten frozen burritos is the first.
    """

    __tablename__ = "thing_uses"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    thing_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ServerDrop(Base):
    """A drop that has arrived on this server, recorded so it cannot un-arrive.

    Only `event` and `manual` drops need rows. A `date` drop is answered by the
    calendar every time it is asked, so storing it would be a second source of
    truth. The reason arrival is recorded at all is that a condition can stop
    being true - a counter falls back, a thing is taken - and content must not
    vanish from a house it has already changed.
    """

    __tablename__ = "server_drops"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    drop_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    arrived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


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
    ("things", "cohort", "VARCHAR(1)"),
    ("things", "can_take", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("things", "removed_on_take", "BOOLEAN NOT NULL DEFAULT TRUE"),
    # Rows written before this column existed read 0 rather than their true score,
    # which cannot be recovered. Acceptable only because every such row is test
    # data; reset_db.py is the way past it.
    ("pet_events", "relationship_at_pet", "INTEGER NOT NULL DEFAULT 0"),
    ("room_contents", "container_id", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("thing_uses", "use_count", "INTEGER NOT NULL DEFAULT 0"),
]


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
            await conn.run_sync(Base.metadata.create_all)
            await _add_missing_columns(conn)
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


async def increment_pet_count(user_id: int, guild_id: int) -> PetResult:
    """Record a pet for this player in this server, creating their row if needed.

    Returns the new lifetime total alongside the number of pets this player
    already made inside RECENT_PET_WINDOW in this server - the caller uses that
    to weight how warmly the cat reacts. Counting happens before the new event
    is inserted, so `recent` describes the state the player arrived in.

    The count, the increment and the new event all share one transaction, so a
    burst of rapid /pet calls cannot interleave into a wrong reading.
    """
    session_factory = _require_session()

    now = _utcnow()
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
                select(func.count())
                .select_from(PetEvent)
                .where(
                    PetEvent.user_id == user_id,
                    PetEvent.guild_id == guild_id,
                    PetEvent.created_at >= cutoff,
                )
            )
            total, relationship_before = (await session.execute(stmt)).one()
            # The upsert touches pet_count, never relationship, so what comes back
            # is the score as it stood before this pet - which is exactly what the
            # achievements need, and what nothing could reconstruct afterwards. A
            # brand-new player reads RELATIONSHIP_START, their score at that moment.
            session.add(
                PetEvent(
                    user_id=user_id,
                    guild_id=guild_id,
                    created_at=now,
                    relationship_at_pet=relationship_before,
                )
            )
            await session.commit()

            log.info(
                "User %s petted the cat in guild %s (total: %s, recent: %s)",
                user_id,
                guild_id,
                total,
                recent,
            )
            return PetResult(total=total, recent=recent or 0)
    except SQLAlchemyError:
        log.exception("Failed to increment pet count for user %s in guild %s", user_id, guild_id)
        raise


async def adjust_relationship(user_id: int, guild_id: int, delta: int) -> int:
    """Move this player's relationship in this server by `delta`, clamped to [-100, 100].

    The clamp is expressed as a SQL CASE so the read, the arithmetic and the
    write are one atomic statement - two rapid pets cannot both read the same
    starting value and lose an update between them.
    """
    session_factory = _require_session()

    moved = User.relationship + delta
    stmt = (
        update(User)
        .where(User.id == user_id, User.guild_id == guild_id)
        .values(
            relationship=case(
                (moved > RELATIONSHIP_MAX, RELATIONSHIP_MAX),
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
# Nightly relationship decay, per (player, server)
# --------------------------------------------------------------------------


async def apply_daily_decay(day: date) -> list[DecayChange]:
    """Settle one Pacific calendar day, drifting idle players back toward neutral.

    Each (player, server) row is independent: a player is skipped in a server
    only if they petted *in that server* during `day`. Rows at or above
    DECAY_POSITIVE_THRESHOLD lose DECAY_POSITIVE_STEP without crossing below 0;
    rows at or below DECAY_NEGATIVE_THRESHOLD gain DECAY_NEGATIVE_STEP without
    crossing above 0. Scores between those thresholds are left alone.

    Every row considered has `last_decay_date` stamped to `day`, so a restart
    cannot apply the same night twice.
    """
    session_factory = _require_session()
    start, end = pacific_day_bounds_utc(day)
    changes: list[DecayChange] = []

    try:
        async with session_factory() as session:
            pending = (
                await session.execute(
                    select(User.id, User.guild_id, User.relationship).where(
                        (User.last_decay_date.is_(None)) | (User.last_decay_date < day)
                    )
                )
            ).all()

            for user_id, guild_id, score in pending:
                petted = await session.scalar(
                    select(func.count())
                    .select_from(PetEvent)
                    .where(
                        PetEvent.user_id == user_id,
                        PetEvent.guild_id == guild_id,
                        PetEvent.created_at >= start,
                        PetEvent.created_at < end,
                    )
                )

                if not petted:
                    if score >= DECAY_POSITIVE_THRESHOLD:
                        new_score = max(0, score - DECAY_POSITIVE_STEP)
                    elif score <= DECAY_NEGATIVE_THRESHOLD:
                        new_score = min(0, score + DECAY_NEGATIVE_STEP)
                    else:
                        new_score = score

                    if new_score != score:
                        await session.execute(
                            update(User)
                            .where(User.id == user_id, User.guild_id == guild_id)
                            .values(relationship=new_score)
                        )
                        changes.append(DecayChange(user_id, guild_id, score, new_score, day))

                await session.execute(
                    update(User)
                    .where(User.id == user_id, User.guild_id == guild_id)
                    .values(last_decay_date=day)
                )

            await session.commit()

        if changes:
            log.info("Nightly decay for %s adjusted %d row(s)", day, len(changes))
        return changes
    except SQLAlchemyError:
        log.exception("Nightly decay failed for %s", day)
        raise


async def run_pending_decay() -> list[DecayChange]:
    """Settle every fully elapsed Pacific day that has not been decayed yet.

    Called at startup and after each scheduled midnight run, so an outage of a
    few days is caught up rather than silently skipped. Only days that have
    fully ended are settled - today is still in progress and is left alone.
    """
    session_factory = _require_session()
    today = pacific_today()

    async with session_factory() as session:
        population = await session.scalar(select(func.count()).select_from(User))
        earliest = await session.scalar(select(func.min(User.last_decay_date)))

    if not population:
        return []

    # Never decayed before: settle yesterday only, rather than all of history.
    first_day = (earliest + timedelta(days=1)) if earliest else today - timedelta(days=1)
    first_day = max(first_day, today - timedelta(days=MAX_CATCHUP_DAYS))

    changes: list[DecayChange] = []
    day = first_day
    while day < today:
        changes.extend(await apply_daily_decay(day))
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
        )
        .on_conflict_do_update(
            index_elements=[
                RoomContents.guild_id,
                RoomContents.room_id,
                RoomContents.container_id,
                RoomContents.thing_id,
            ],
            set_={"count": RoomContents.count + delta},
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
    now = _utcnow()

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


async def pets_while_relationship(
    user_id: int, guild_id: int, *, positive: bool
) -> int:
    """Pets by this player with the relationship above zero, or at or below.

    The split is `> 0` against `<= 0`, so a pet at exactly zero counts toward
    *Trying to Make Friends*. The Story Bible was revised from "negative" to
    "zero or below" for exactly this boundary, and a relationship starting at
    zero means the first pet of the game lands on it.

    Reads `relationship_at_pet`, which is the score as it stood *before* the
    pet applied - the running total cannot answer this after the fact.
    """
    session_factory = _require_session()
    condition = (
        PetEvent.relationship_at_pet > 0 if positive else PetEvent.relationship_at_pet <= 0
    )
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(PetEvent)
            .where(
                PetEvent.guild_id == guild_id,
                PetEvent.user_id == user_id,
                condition,
            )
        )
    return int(count or 0)


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
}


async def get_setting(guild_id: int, key: str) -> int:
    """A server's value for a numeric setting, or its default.

    A value that will not parse falls back to the default and says so, rather
    than taking a command down over a row somebody hand-edited.
    """
    default, _ = CONFIG_KEYS.get(key, (0, ""))
    session_factory = _require_session()
    async with session_factory() as session:
        raw = await session.scalar(
            select(ServerConfig.value).where(
                ServerConfig.guild_id == guild_id, ServerConfig.key == key
            )
        )
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
    session_factory = _require_session()
    insert = _upsert_statement()
    async with session_factory() as session:
        await session.execute(
            insert(ServerConfig)
            .values(
                guild_id=guild_id,
                key=CONFIG_ANNOUNCE_CHANNEL,
                value=str(channel_id),
            )
            .on_conflict_do_update(
                index_elements=[ServerConfig.guild_id, ServerConfig.key],
                set_={"value": str(channel_id)},
            )
        )
        await session.commit()
    log.info("Guild %s announces achievements in channel %s", guild_id, channel_id)


async def announcement_channel(guild_id: int) -> int | None:
    """Where to post an achievement name, or None if never initialized."""
    session_factory = _require_session()
    async with session_factory() as session:
        raw = await session.scalar(
            select(ServerConfig.value).where(
                ServerConfig.guild_id == guild_id,
                ServerConfig.key == CONFIG_ANNOUNCE_CHANNEL,
            )
        )
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        log.warning("Guild %s has a non-numeric announce channel %r", guild_id, raw)
        return None


async def set_setting(guild_id: int, key: str, value: int) -> int:
    """Store a setting and return it. Takes effect from the next read."""
    session_factory = _require_session()
    insert = _upsert_statement()
    async with session_factory() as session:
        await session.execute(
            insert(ServerConfig)
            .values(guild_id=guild_id, key=key, value=str(value))
            .on_conflict_do_update(
                index_elements=[ServerConfig.guild_id, ServerConfig.key],
                set_={"value": str(value)},
            )
        )
        await session.commit()
    log.info("Guild %s set %s to %s", guild_id, key, value)
    return value


async def all_settings(guild_id: int) -> dict[str, int]:
    """Every known setting for a server, defaults filled in."""
    return {key: await get_setting(guild_id, key) for key in CONFIG_KEYS}
