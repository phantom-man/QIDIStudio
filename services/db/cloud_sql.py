"""
services/db/cloud_sql.py — Async Cloud SQL (PostgreSQL) connection pool and CRUD helpers.

Uses SQLAlchemy 2.x async engine via the Cloud SQL Python Connector (asyncpg driver).
Falls back to a direct DSN string (`CLOUD_SQL_DSN` env var) for local dev / CI.

Environment variables:
    CLOUD_SQL_INSTANCE_CONNECTION_NAME  e.g. crafty-hook-483415-b3:us-central1:qidistudio-db
    CLOUD_SQL_DB_NAME                   e.g. qidistudio
    CLOUD_SQL_DB_USER                   e.g. qidistudio_app
    CLOUD_SQL_DB_PASS                   secret / GCP Secret Manager
    CLOUD_SQL_DSN                       override — use direct postgres DSN (local dev only)

Usage:
    from services.db.cloud_sql import get_session, upsert_manufacturer, upsert_filament

    async with get_session() as session:
        mfr = await upsert_manufacturer(session, manufacturer_data)
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from services.db.models import (
    Base,
    DataTier,
    Filament,
    FilamentManufacturer,
    NozzleFilamentSetting,
    NozzleType,
    ResearchStatus,
    Subscription,
    SubscriptionStatus,
    SubscriptionTier,
    User,
)

load_dotenv()

# ── Engine singleton ──────────────────────────────────────────────────────────

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine() -> AsyncEngine:
    """
    Build the async engine. Prefers Cloud SQL Python Connector in production;
    falls back to direct DSN string for local dev.
    """
    # Local dev override
    direct_dsn = os.getenv("CLOUD_SQL_DSN")
    if direct_dsn:
        return create_async_engine(
            direct_dsn,
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )

    # Production: Cloud SQL Python Connector
    try:
        from google.cloud.sql.connector import Connector, create_async_connector
    except ImportError as e:
        raise RuntimeError(
            "cloud-sql-python-connector not installed. "
            "Run: pip install cloud-sql-python-connector[asyncpg]"
        ) from e

    instance_conn_name = os.environ["CLOUD_SQL_INSTANCE_CONNECTION_NAME"]
    db_user = os.environ["CLOUD_SQL_DB_USER"]
    db_pass = os.environ["CLOUD_SQL_DB_PASS"]
    db_name = os.environ["CLOUD_SQL_DB_NAME"]

    async def _get_conn() -> Any:
        connector = await create_async_connector()
        return await connector.connect_async(
            instance_conn_name,
            "asyncpg",
            user=db_user,
            password=db_pass,
            db=db_name,
        )

    return create_async_engine(
        "postgresql+asyncpg://",
        async_creator=_get_conn,
        echo=os.getenv("SQL_ECHO", "false").lower() == "true",
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async session, auto-committing on clean exit, rolling back on exception."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Schema management ─────────────────────────────────────────────────────────


async def create_all_tables() -> None:
    """Create all tables defined in models.py. Safe to call multiple times (no-op if exist)."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def health_check() -> bool:
    """Return True if the database is reachable and responsive."""
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# ── Manufacturer CRUD ─────────────────────────────────────────────────────────


async def upsert_manufacturer(
    session: AsyncSession,
    data: dict[str, Any],
) -> FilamentManufacturer:
    """
    Insert or update a filament manufacturer by slug.
    Returns the persisted ORM row.
    """
    stmt = (
        pg_insert(FilamentManufacturer)
        .values(**data)
        .on_conflict_do_update(
            index_elements=["slug"],
            set_={k: v for k, v in data.items() if k != "slug"},
        )
        .returning(FilamentManufacturer.id)
    )
    result = await session.execute(stmt)
    row_id = result.scalar_one()
    return await session.get(FilamentManufacturer, row_id)


async def get_manufacturer_by_slug(
    session: AsyncSession, slug: str
) -> FilamentManufacturer | None:
    result = await session.execute(
        select(FilamentManufacturer).where(FilamentManufacturer.slug == slug)
    )
    return result.scalar_one_or_none()


async def list_manufacturers(
    session: AsyncSession,
    tier: DataTier | None = None,
    status: ResearchStatus | None = None,
) -> list[FilamentManufacturer]:
    stmt = select(FilamentManufacturer)
    if tier:
        stmt = stmt.where(FilamentManufacturer.data_tier == tier)
    if status:
        stmt = stmt.where(FilamentManufacturer.research_status == status)
    result = await session.execute(stmt.order_by(FilamentManufacturer.name))
    return list(result.scalars().all())


# ── Filament CRUD ─────────────────────────────────────────────────────────────


async def upsert_filament(
    session: AsyncSession,
    data: dict[str, Any],
) -> Filament:
    """
    Insert or update a filament by (manufacturer_id, slug).
    data must include 'manufacturer_id' and 'slug'.
    """
    stmt = (
        pg_insert(Filament)
        .values(**data)
        .on_conflict_do_update(
            constraint="filaments_manufacturer_id_slug_key",
            set_={
                k: v for k, v in data.items() if k not in ("manufacturer_id", "slug")
            },
        )
        .returning(Filament.id)
    )
    result = await session.execute(stmt)
    row_id = result.scalar_one()
    return await session.get(Filament, row_id)


async def get_filaments_for_tier(
    session: AsyncSession,
    tier: DataTier,
    include_drafts: bool = False,
) -> list[Filament]:
    stmt = select(Filament).where(Filament.data_tier == tier)
    if not include_drafts:
        stmt = stmt.where(Filament.research_status == ResearchStatus.published)
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ── Nozzle CRUD ──────────────────────────────────────────────────────────────


async def upsert_nozzle_type(
    session: AsyncSession,
    data: dict[str, Any],
) -> NozzleType:
    stmt = (
        pg_insert(NozzleType)
        .values(**data)
        .on_conflict_do_update(
            index_elements=["slug"],
            set_={k: v for k, v in data.items() if k != "slug"},
        )
        .returning(NozzleType.id)
    )
    result = await session.execute(stmt)
    row_id = result.scalar_one()
    return await session.get(NozzleType, row_id)


async def upsert_nozzle_filament_setting(
    session: AsyncSession,
    data: dict[str, Any],
) -> NozzleFilamentSetting:
    stmt = (
        pg_insert(NozzleFilamentSetting)
        .values(**data)
        .on_conflict_do_update(
            constraint="nozzle_filament_settings_nozzle_type_id_filament_id_key",
            set_={
                k: v
                for k, v in data.items()
                if k not in ("nozzle_type_id", "filament_id")
            },
        )
        .returning(NozzleFilamentSetting.id)
    )
    result = await session.execute(stmt)
    row_id = result.scalar_one()
    return await session.get(NozzleFilamentSetting, row_id)


# ── Auth CRUD ─────────────────────────────────────────────────────────────────


async def get_or_create_user_by_fingerprint(
    session: AsyncSession,
    fingerprint: str,
    platform: str = "windows",
) -> tuple[User, bool]:
    """
    Look up a user by device fingerprint hash. Creates one if not found.
    Returns (user, created: bool).
    """
    from services.db.models import DeviceFingerprint  # local import to avoid circulars

    # Find existing fingerprint
    result = await session.execute(
        select(DeviceFingerprint)
        .where(DeviceFingerprint.fingerprint == fingerprint)
        .where(DeviceFingerprint.is_revoked.is_(False))
    )
    fp_row = result.scalar_one_or_none()
    if fp_row:
        user = await session.get(User, fp_row.user_id)
        return user, False

    # Create new user + fingerprint
    user = User()
    session.add(user)
    await session.flush()

    fp = DeviceFingerprint(
        user_id=user.id,
        fingerprint=fingerprint,
        platform=platform,
    )
    session.add(fp)

    # Give them a free subscription
    sub = Subscription(
        user_id=user.id,
        tier=SubscriptionTier.free,
        status=SubscriptionStatus.active,
    )
    session.add(sub)

    return user, True


async def get_active_subscription(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> Subscription | None:
    """Return the first active subscription for a user, or None."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .where(Subscription.status == SubscriptionStatus.active)
        .where((Subscription.expires_at.is_(None)) | (Subscription.expires_at > now))
        .order_by(Subscription.expires_at.desc().nulls_last())
        .limit(1)
    )
    return result.scalar_one_or_none()
