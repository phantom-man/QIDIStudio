"""
services/db/models.py — SQLAlchemy 2.x async ORM models for Cloud SQL (PostgreSQL).

These mirror the DDL in cloud_sql_schema.sql. Use async sessions for all operations
to avoid blocking the event loop in agent pipelines.

Usage:
    from services.db.cloud_sql import get_session
    from services.db.models import Filament, FilamentManufacturer

    async with get_session() as session:
        mfr = await session.get(FilamentManufacturer, mfr_id)
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ── Base ──────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


# ── Enums ───────────────────────────────────────────────────────────────────


class SubscriptionTier(str, enum.Enum):
    free = "free"
    trial = "trial"
    monthly = "monthly"
    yearly = "yearly"
    lifetime = "lifetime"


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    expired = "expired"
    cancelled = "cancelled"
    suspended = "suspended"
    grace = "grace"


class DataTier(str, enum.Enum):
    free = "free"
    pro = "pro"


class NozzleMaterial(str, enum.Enum):
    brass = "brass"
    hardened_steel = "hardened_steel"
    stainless_steel = "stainless_steel"
    ruby = "ruby"
    tungsten_carbide = "tungsten_carbide"
    copper = "copper"
    plated_brass = "plated_brass"
    plated_copper = "plated_copper"
    aluminum = "aluminum"
    silicon_carbide = "silicon_carbide"


class FilamentCategory(str, enum.Enum):
    PLA = "PLA"
    PLA_Plus = "PLA_Plus"
    PETG = "PETG"
    ABS = "ABS"
    ASA = "ASA"
    TPU = "TPU"
    TPE = "TPE"
    FLEX = "FLEX"
    PA = "PA"
    PA_CF = "PA_CF"
    PC = "PC"
    PC_CF = "PC_CF"
    PP = "PP"
    PEI = "PEI"
    PEKK = "PEKK"
    PEEK = "PEEK"
    PVA = "PVA"
    HIPS = "HIPS"
    BVOH = "BVOH"
    PETG_CF = "PETG_CF"
    PLA_CF = "PLA_CF"
    ABS_CF = "ABS_CF"
    ASA_CF = "ASA_CF"
    SILK = "SILK"
    MATTE = "MATTE"
    GLOW = "GLOW"
    WOOD = "WOOD"
    METAL_FILL = "METAL_FILL"
    COMPOSITE = "COMPOSITE"
    OTHER = "OTHER"


class ResearchStatus(str, enum.Enum):
    draft = "draft"
    validated = "validated"
    published = "published"
    deprecated = "deprecated"


# ── Users & Auth ──────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    email: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    stripe_customer_id: Mapped[str | None] = mapped_column(
        Text, unique=True, nullable=True
    )

    fingerprints: Mapped[list[DeviceFingerprint]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    issued_tokens: Mapped[list[IssuedToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class DeviceFingerprint(Base):
    __tablename__ = "device_fingerprints"
    __table_args__ = (UniqueConstraint("user_id", "fingerprint"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)  # SHA-256 hex
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="fingerprints")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tier: Mapped[SubscriptionTier] = mapped_column(
        Enum(SubscriptionTier), nullable=False, default=SubscriptionTier.free
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), nullable=False, default=SubscriptionStatus.active
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    grace_period_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stripe_sub_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="subscriptions")


class IssuedToken(Base):
    __tablename__ = "issued_tokens"

    jti: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[SubscriptionTier] = mapped_column(
        Enum(SubscriptionTier), nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="issued_tokens")


# ── Filament Data ─────────────────────────────────────────────────────────────


class FilamentManufacturer(Base):
    __tablename__ = "filament_manufacturers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    amazon_storefront: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_of_origin: Mapped[str | None] = mapped_column(Text, nullable=True)
    founded_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_amazon_rating: Mapped[float | None] = mapped_column(
        Numeric(3, 2), nullable=True
    )
    amazon_review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_tier: Mapped[DataTier] = mapped_column(
        Enum(DataTier), nullable=False, default=DataTier.free
    )
    research_status: Mapped[ResearchStatus] = mapped_column(
        Enum(ResearchStatus), nullable=False, default=ResearchStatus.draft
    )
    last_researched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    filaments: Mapped[list[Filament]] = relationship(
        back_populates="manufacturer", cascade="all, delete-orphan"
    )


class Filament(Base):
    __tablename__ = "filaments"
    __table_args__ = (UniqueConstraint("manufacturer_id", "slug"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    manufacturer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("filament_manufacturers.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[FilamentCategory] = mapped_column(
        Enum(FilamentCategory), nullable=False
    )
    color_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    asin: Mapped[str | None] = mapped_column(Text, nullable=True)
    avg_amazon_rating: Mapped[float | None] = mapped_column(
        Numeric(3, 2), nullable=True
    )
    amazon_review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diameter_mm: Mapped[float] = mapped_column(
        Numeric(4, 2), nullable=False, default=1.75
    )

    # Physical tolerances
    diameter_tolerance_mm: Mapped[float | None] = mapped_column(
        Numeric(4, 3), nullable=True
    )
    roundness_tolerance_mm: Mapped[float | None] = mapped_column(
        Numeric(4, 3), nullable=True
    )
    density_g_cm3: Mapped[float | None] = mapped_column(Numeric(5, 3), nullable=True)
    tensile_strength_mpa: Mapped[float | None] = mapped_column(
        Numeric(7, 2), nullable=True
    )
    elongation_at_break_pct: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    impact_strength_kj_m2: Mapped[float | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    heat_deflection_temp_c: Mapped[float | None] = mapped_column(
        Numeric(5, 1), nullable=True
    )
    glass_transition_temp_c: Mapped[float | None] = mapped_column(
        Numeric(5, 1), nullable=True
    )
    vicat_softening_temp_c: Mapped[float | None] = mapped_column(
        Numeric(5, 1), nullable=True
    )
    moisture_absorption_pct: Mapped[float | None] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    shrinkage_pct: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)

    # Print settings
    nozzle_temp_min_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nozzle_temp_max_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nozzle_temp_rec_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bed_temp_min_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bed_temp_max_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bed_temp_rec_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bed_temp_pei_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bed_temp_glass_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bed_temp_garolite_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chamber_temp_min_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chamber_temp_max_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chamber_temp_rec_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    print_speed_min_mms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    print_speed_max_mms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    print_speed_rec_mms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cooling_fan_min_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cooling_fan_max_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cooling_fan_rec_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retraction_bowden_mm: Mapped[float | None] = mapped_column(
        Numeric(4, 1), nullable=True
    )
    retraction_direct_mm: Mapped[float | None] = mapped_column(
        Numeric(4, 1), nullable=True
    )
    retraction_speed_mms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flow_rate_pct: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)

    # Properties
    requires_enclosure: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    requires_dry_box: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    drying_temp_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drying_time_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    food_safe: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    flexible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    uv_resistant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    chemical_resistant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Pro tier JSONB
    pro_settings_by_nozzle: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    # Notes
    bed_adhesion_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    common_challenges: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_processing_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    typical_use_cases: Mapped[str | None] = mapped_column(Text, nullable=True)
    incompatible_with: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )
    works_well_with: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )

    data_tier: Mapped[DataTier] = mapped_column(
        Enum(DataTier), nullable=False, default=DataTier.free
    )
    research_status: Mapped[ResearchStatus] = mapped_column(
        Enum(ResearchStatus), nullable=False, default=ResearchStatus.draft
    )
    last_researched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    manufacturer: Mapped[FilamentManufacturer] = relationship(
        back_populates="filaments"
    )
    nozzle_settings: Mapped[list[NozzleFilamentSetting]] = relationship(
        back_populates="filament", cascade="all, delete-orphan"
    )


# ── Nozzle Data ───────────────────────────────────────────────────────────────


class NozzleType(Base):
    __tablename__ = "nozzle_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    material: Mapped[NozzleMaterial] = mapped_column(
        Enum(NozzleMaterial), nullable=False
    )
    diameter_mm: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    hardness_hrc: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    thermal_conductivity: Mapped[float | None] = mapped_column(
        Numeric(6, 3), nullable=True
    )
    max_temp_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    abrasion_resistance: Mapped[str | None] = mapped_column(Text, nullable=True)
    compatible_filaments: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )
    abrasive_filaments_ok: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    settings_delta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    pro_settings_matrix: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    manufacturer: Mapped[str | None] = mapped_column(Text, nullable=True)
    typical_cost_usd: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    lifespan_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    when_to_use: Mapped[str | None] = mapped_column(Text, nullable=True)
    maintenance_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_tier: Mapped[DataTier] = mapped_column(
        Enum(DataTier), nullable=False, default=DataTier.pro
    )
    research_status: Mapped[ResearchStatus] = mapped_column(
        Enum(ResearchStatus), nullable=False, default=ResearchStatus.draft
    )
    last_researched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    filament_settings: Mapped[list[NozzleFilamentSetting]] = relationship(
        back_populates="nozzle_type", cascade="all, delete-orphan"
    )


class NozzleFilamentSetting(Base):
    __tablename__ = "nozzle_filament_settings"
    __table_args__ = (UniqueConstraint("nozzle_type_id", "filament_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nozzle_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nozzle_types.id", ondelete="CASCADE"), nullable=False
    )
    filament_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("filaments.id", ondelete="CASCADE"), nullable=False
    )
    nozzle_temp_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bed_temp_c: Mapped[int | None] = mapped_column(Integer, nullable=True)
    print_speed_mms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_layer_speed_mms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outer_wall_speed_mms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inner_wall_speed_mms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    infill_speed_mms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    travel_speed_mms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cooling_fan_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retraction_mm: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    retraction_speed_mms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flow_rate_pct: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    pressure_advance: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    line_width_mm: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)
    layer_height_rec_mm: Mapped[float | None] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    layer_height_max_mm: Mapped[float | None] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    validated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_tier: Mapped[DataTier] = mapped_column(
        Enum(DataTier), nullable=False, default=DataTier.pro
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    nozzle_type: Mapped[NozzleType] = relationship(back_populates="filament_settings")
    filament: Mapped[Filament] = relationship(back_populates="nozzle_settings")
