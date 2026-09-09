"""Database layer for the cat petting bot.

Backend is chosen from DATABASE_URL:
  - unset            -> local SQLite file (zero setup, for local development)
  - postgres[ql]://  -> PostgreSQL via asyncpg (what Railway provides)

The same model and queries run on both, so local behaviour matches production.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from sqlalchemy import BigInteger, DateTime, Index, Integer, func, select
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

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


class Base(DeclarativeBase):
    pass


class PetResult(NamedTuple):
    """Outcome of a single pet: lifetime total, plus recent pets before this one."""

    total: int
    recent: int


def _utcnow() -> datetime:
    """Naive UTC timestamp.

    Stored without tzinfo so comparisons behave identically on PostgreSQL and
    SQLite - the SQLite driver returns naive datetimes regardless of what was
    written, which would otherwise make aware/naive comparisons raise.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """One row per Discord user who has petted the cat."""

    __tablename__ = "users"

    # Discord snowflake IDs exceed 32 bits, so BIGINT is required.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    pet_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[object] = mapped_column(
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

    Railway hands out `postgresql://...`, which SQLAlchemy maps to the *sync* psycopg
    driver. Rewriting the scheme keeps the deployment config unchanged.
    """
    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql://", 1)
    if raw.startswith("postgresql://"):
        raw = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


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

    log.info("Database ready (%s)", backend)


def _upsert_statement():
    """Return the dialect-specific INSERT ... ON CONFLICT builder.

    PostgreSQL and SQLite both support upsert-with-RETURNING, which lets us
    increment and read back the new total in a single atomic statement. That
    matters because a user can fire /pet faster than a read-then-write round trip.
    """
    assert _engine is not None
    return pg_insert if _engine.dialect.name == "postgresql" else sqlite_insert


async def increment_pet_count(user_id: int) -> PetResult:
    """Record a pet for this user, creating their row if needed.

    Returns the new lifetime total alongside the number of pets this user
    already made inside RECENT_PET_WINDOW - the caller uses that to weight how
    warmly the cat reacts. Counting happens before the new event is inserted, so
    `recent` describes the state the user arrived in, not including this pet.

    The count, the increment and the new event all share one transaction, so a
    burst of rapid /pet calls cannot interleave into a wrong reading.
    """
    if _session_factory is None:
        raise RuntimeError("init_db() must run before increment_pet_count()")

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
        async with _session_factory() as session:
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


async def get_pet_count(user_id: int) -> int:
    """Return this user's pet total, or 0 if they have never petted the cat."""
    if _session_factory is None:
        raise RuntimeError("init_db() must run before get_pet_count()")

    try:
        async with _session_factory() as session:
            result = await session.execute(select(User.pet_count).where(User.id == user_id))
            return result.scalar_one_or_none() or 0
    except SQLAlchemyError:
        log.exception("Failed to read pet count for user %s", user_id)
        raise


async def close_db() -> None:
    """Dispose of the connection pool on shutdown."""
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        log.info("Database connection closed")
