"""Database layer for the cat petting bot.

Backend is chosen from DATABASE_URL:
  - unset            -> local SQLite file (zero setup, for local development)
  - postgres[ql]://  -> PostgreSQL via asyncpg (what Railway provides)

The same model and queries run on both, so local behaviour matches production.
"""

import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import NamedTuple
from zoneinfo import ZoneInfo

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Index,
    Integer,
    case,
    func,
    inspect,
    select,
    text,
    update,
)
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

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


class Base(DeclarativeBase):
    pass


class PetResult(NamedTuple):
    """Outcome of a single pet: lifetime total, plus recent pets before this one."""

    total: int
    recent: int


class DecayChange(NamedTuple):
    """One user's relationship movement during a nightly decay run."""

    user_id: int
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
    """One row per Discord user who has petted the cat."""

    __tablename__ = "users"

    # Discord snowflake IDs exceed 32 bits, so BIGINT is required.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    pet_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # `default` is what actually sets a new player's score, since rows are only
    # ever created by the upsert in increment_pet_count; `server_default` writes
    # the same value into the CREATE TABLE DDL for databases built from scratch.
    relationship: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=RELATIONSHIP_START,
        server_default=text(str(RELATIONSHIP_START)),
    )
    # Last Pacific day the nightly decay was evaluated for this user. Lets the
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
    __table_args__ = (Index("ix_pet_events_user_time", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


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


async def _add_missing_columns(conn) -> None:
    """Add columns introduced after a database was first created.

    `create_all` creates missing *tables* but never missing *columns*, so a
    database predating the relationship meter would keep a stale `users` table
    and every query against it would fail. Both backends accept this ALTER form,
    and re-running it is a no-op once the columns exist.
    """

    def _existing(sync_conn):
        return {col["name"] for col in inspect(sync_conn).get_columns("users")}

    existing = await conn.run_sync(_existing)

    if "relationship" not in existing:
        # Interpolated rather than bound: DDL defaults cannot take a parameter.
        # RELATIONSHIP_START is an int constant defined above, never user input.
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN relationship "
                f"INTEGER NOT NULL DEFAULT {RELATIONSHIP_START}"
            )
        )
        log.info("Schema upgrade: added users.relationship")

    if "last_decay_date" not in existing:
        await conn.execute(text("ALTER TABLE users ADD COLUMN last_decay_date DATE"))
        log.info("Schema upgrade: added users.last_decay_date")


async def init_db() -> None:
    """Create the engine and ensure the schema exists. Safe to call once at startup."""
    global _engine, _session_factory

    if _engine is not None:
        return

    raw_url = os.getenv("DATABASE_URL", "").strip()
    if raw_url:
        url = _normalise_url(raw_url)
        backend = "PostgreSQL"
    else:
        url = DEFAULT_SQLITE_URL
        backend = "SQLite (local development)"
        log.warning("DATABASE_URL not set - falling back to local SQLite file catbot.db")

    _engine = create_async_engine(url, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _add_missing_columns(conn)

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


async def increment_pet_count(user_id: int) -> PetResult:
    """Record a pet for this user, creating their row if needed.

    Returns the new lifetime total alongside the number of pets this user
    already made inside RECENT_PET_WINDOW - the caller uses that to weight how
    warmly the cat reacts. Counting happens before the new event is inserted, so
    `recent` describes the state the user arrived in, not including this pet.

    The count, the increment and the new event all share one transaction, so a
    burst of rapid /pet calls cannot interleave into a wrong reading.
    """
    session_factory = _require_session()

    now = _utcnow()
    cutoff = now - RECENT_PET_WINDOW

    insert = _upsert_statement()
    stmt = (
        insert(User)
        .values(id=user_id, pet_count=1)
        .on_conflict_do_update(
            index_elements=[User.id],
            set_={"pet_count": User.pet_count + 1, "updated_at": func.now()},
        )
        .returning(User.pet_count)
    )

    try:
        async with session_factory() as session:
            recent = await session.scalar(
                select(func.count())
                .select_from(PetEvent)
                .where(PetEvent.user_id == user_id, PetEvent.created_at >= cutoff)
            )
            result = await session.execute(stmt)
            total = result.scalar_one()
            session.add(PetEvent(user_id=user_id, created_at=now))
            await session.commit()

            log.info(
                "User %s petted the cat (total: %s, recent: %s)", user_id, total, recent
            )
            return PetResult(total=total, recent=recent or 0)
    except SQLAlchemyError:
        log.exception("Failed to increment pet count for user %s", user_id)
        raise


async def adjust_relationship(user_id: int, delta: int) -> int:
    """Move this user's relationship by `delta`, clamped to [-100, 100].

    The clamp is expressed as a SQL CASE so the read, the arithmetic and the
    write are one atomic statement - two rapid pets cannot both read the same
    starting value and lose an update between them.
    """
    session_factory = _require_session()

    moved = User.relationship + delta
    stmt = (
        update(User)
        .where(User.id == user_id)
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
                # No row yet: the caller adjusted before the user existed.
                log.warning("adjust_relationship: no user row for %s", user_id)
                return 0
            log.info("User %s relationship %+d -> %s", user_id, delta, row)
            return row
    except SQLAlchemyError:
        log.exception("Failed to adjust relationship for user %s", user_id)
        raise


async def get_relationship(user_id: int) -> int:
    """Return this user's relationship score, or 0 if they have no row yet."""
    session_factory = _require_session()
    try:
        async with session_factory() as session:
            value = await session.scalar(select(User.relationship).where(User.id == user_id))
            return value or 0
    except SQLAlchemyError:
        log.exception("Failed to read relationship for user %s", user_id)
        raise


async def get_pet_count(user_id: int) -> int:
    """Return this user's pet total, or 0 if they have never petted the cat."""
    session_factory = _require_session()
    try:
        async with session_factory() as session:
            result = await session.execute(select(User.pet_count).where(User.id == user_id))
            return result.scalar_one_or_none() or 0
    except SQLAlchemyError:
        log.exception("Failed to read pet count for user %s", user_id)
        raise


async def apply_daily_decay(day: date) -> list[DecayChange]:
    """Settle one Pacific calendar day, drifting idle users back toward neutral.

    A user is skipped entirely if they petted at any point during `day`. Users at
    or above DECAY_POSITIVE_THRESHOLD lose DECAY_POSITIVE_STEP without crossing
    below 0; users at or below DECAY_NEGATIVE_THRESHOLD gain DECAY_NEGATIVE_STEP
    without crossing above 0. Scores between those thresholds are left alone.

    Every user considered has `last_decay_date` stamped to `day`, so a restart
    cannot apply the same night twice.
    """
    session_factory = _require_session()
    start, end = pacific_day_bounds_utc(day)
    changes: list[DecayChange] = []

    try:
        async with session_factory() as session:
            pending = (
                await session.execute(
                    select(User.id, User.relationship).where(
                        (User.last_decay_date.is_(None)) | (User.last_decay_date < day)
                    )
                )
            ).all()

            for user_id, score in pending:
                petted = await session.scalar(
                    select(func.count())
                    .select_from(PetEvent)
                    .where(
                        PetEvent.user_id == user_id,
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
                            .where(User.id == user_id)
                            .values(relationship=new_score)
                        )
                        changes.append(DecayChange(user_id, score, new_score, day))

                await session.execute(
                    update(User).where(User.id == user_id).values(last_decay_date=day)
                )

            await session.commit()

        if changes:
            log.info("Nightly decay for %s adjusted %d user(s)", day, len(changes))
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
