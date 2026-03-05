-- ============================================================================
-- QIDIStudio Cloud SQL Schema (PostgreSQL 14+)
-- GCP Project: crafty-hook-483415-b3 | Instance: qidistudio-db
-- ============================================================================
-- Run order: extensions → enums → tables → indexes → functions
-- Apply via: psql $CLOUD_SQL_DSN -f services/db/cloud_sql_schema.sql
-- ============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- ENUMs
-- ============================================================================

CREATE TYPE subscription_tier AS ENUM ('free', 'trial', 'monthly', 'yearly', 'lifetime');
CREATE TYPE subscription_status AS ENUM ('active', 'expired', 'cancelled', 'suspended', 'grace');
CREATE TYPE data_tier AS ENUM ('free', 'pro');
CREATE TYPE nozzle_material AS ENUM (
    'brass', 'hardened_steel', 'stainless_steel', 'ruby', 'tungsten_carbide',
    'copper', 'plated_brass', 'plated_copper', 'aluminum', 'silicon_carbide'
);
CREATE TYPE filament_category AS ENUM (
    'PLA', 'PLA_Plus', 'PETG', 'ABS', 'ASA', 'TPU', 'TPE', 'FLEX',
    'PA', 'PA_CF', 'PC', 'PC_CF', 'PP', 'PEI', 'PEKK', 'PEEK',
    'PVA', 'HIPS', 'BVOH', 'PETG_CF', 'PLA_CF', 'ABS_CF', 'ASA_CF',
    'SILK', 'MATTE', 'GLOW', 'WOOD', 'METAL_FILL', 'COMPOSITE', 'OTHER'
);
CREATE TYPE research_status AS ENUM ('draft', 'validated', 'published', 'deprecated');

-- ============================================================================
-- USERS & SUBSCRIPTIONS
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Digital fingerprint (SHA-256 of: cpu_id|mb_serial|os_install_id|mac_addr)
    -- Multiple fingerprints allowed per user (PC upgrade path)
    email               TEXT UNIQUE,
    display_name        TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    -- Stripe / payment processor customer ID
    stripe_customer_id  TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS device_fingerprints (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fingerprint     TEXT NOT NULL,  -- SHA-256 hex, 64 chars
    label           TEXT,           -- "Main workstation", "Laptop", etc.
    platform        TEXT,           -- 'windows', 'macos', 'linux'
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_revoked      BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (user_id, fingerprint)
);
CREATE INDEX idx_fingerprints_fingerprint ON device_fingerprints(fingerprint) WHERE NOT is_revoked;

CREATE TABLE IF NOT EXISTS subscriptions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tier            subscription_tier NOT NULL DEFAULT 'free',
    status          subscription_status NOT NULL DEFAULT 'active',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,            -- NULL = lifetime
    grace_period_ends_at TIMESTAMPTZ,       -- 3-day grace on expiry
    stripe_sub_id   TEXT UNIQUE,            -- Stripe subscription ID
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_subscriptions_user_id ON subscriptions(user_id);
CREATE INDEX idx_subscriptions_expires_at ON subscriptions(expires_at) WHERE status = 'active';

-- Auth tokens issued to clients (for revocation tracking)
CREATE TABLE IF NOT EXISTS issued_tokens (
    jti             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),  -- JWT ID (jti claim)
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fingerprint     TEXT NOT NULL,          -- device fingerprint this token was issued for
    tier            subscription_tier NOT NULL,
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    is_revoked      BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at      TIMESTAMPTZ,
    revoked_reason  TEXT
);
CREATE INDEX idx_issued_tokens_user_id ON issued_tokens(user_id);
CREATE INDEX idx_issued_tokens_jti ON issued_tokens(jti) WHERE NOT is_revoked;

-- ============================================================================
-- FILAMENT MANUFACTURERS
-- ============================================================================

CREATE TABLE IF NOT EXISTS filament_manufacturers (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug                TEXT NOT NULL UNIQUE,   -- kebab-case: "bambu-lab"
    name                TEXT NOT NULL,
    website             TEXT,
    amazon_storefront   TEXT,
    country_of_origin   TEXT,
    founded_year        INT,
    avg_amazon_rating   NUMERIC(3, 2),          -- e.g. 4.35
    amazon_review_count INT,
    notes               TEXT,
    data_tier           data_tier NOT NULL DEFAULT 'free',
    research_status     research_status NOT NULL DEFAULT 'draft',
    last_researched_at  TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- FILAMENTS (per manufacturer, per product)
-- ============================================================================

CREATE TABLE IF NOT EXISTS filaments (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    manufacturer_id         UUID NOT NULL REFERENCES filament_manufacturers(id) ON DELETE CASCADE,
    slug                    TEXT NOT NULL,          -- "bambu-lab-pla-basic-white"
    product_name            TEXT NOT NULL,          -- "PLA Basic — White"
    category                filament_category NOT NULL,
    color_name              TEXT,
    asin                    TEXT,                   -- Amazon ASIN for rating pull
    avg_amazon_rating       NUMERIC(3, 2),
    amazon_review_count     INT,
    sku                     TEXT,
    diameter_mm             NUMERIC(4, 2) NOT NULL DEFAULT 1.75,  -- 1.75 or 2.85

    -- Physical tolerances (from datasheet)
    diameter_tolerance_mm   NUMERIC(4, 3),          -- e.g. ±0.02 → stored as 0.02
    roundness_tolerance_mm  NUMERIC(4, 3),
    density_g_cm3           NUMERIC(5, 3),
    tensile_strength_mpa    NUMERIC(7, 2),
    elongation_at_break_pct NUMERIC(5, 2),
    impact_strength_kj_m2   NUMERIC(6, 2),
    heat_deflection_temp_c  NUMERIC(5, 1),
    glass_transition_temp_c NUMERIC(5, 1),
    vicat_softening_temp_c  NUMERIC(5, 1),
    moisture_absorption_pct NUMERIC(4, 2),
    shrinkage_pct           NUMERIC(4, 2),

    -- Print settings — free tier (manufacturer recommended)
    nozzle_temp_min_c       INT,
    nozzle_temp_max_c       INT,
    nozzle_temp_rec_c       INT,
    bed_temp_min_c          INT,
    bed_temp_max_c          INT,
    bed_temp_rec_c          INT,
    bed_temp_pei_c          INT,
    bed_temp_glass_c        INT,
    bed_temp_garolite_c     INT,
    chamber_temp_min_c      INT,
    chamber_temp_max_c      INT,
    chamber_temp_rec_c      INT,
    print_speed_min_mms     INT,
    print_speed_max_mms     INT,
    print_speed_rec_mms     INT,
    cooling_fan_min_pct     INT,
    cooling_fan_max_pct     INT,
    cooling_fan_rec_pct     INT,
    retraction_bowden_mm    NUMERIC(4, 1),
    retraction_direct_mm    NUMERIC(4, 1),
    retraction_speed_mms    INT,
    flow_rate_pct           NUMERIC(5, 1),

    -- Properties
    requires_enclosure      BOOLEAN,
    requires_dry_box        BOOLEAN,
    drying_temp_c           INT,
    drying_time_hours       INT,
    food_safe               BOOLEAN,
    flexible                BOOLEAN,
    uv_resistant            BOOLEAN,
    chemical_resistant      BOOLEAN,

    -- Pro-tier advanced settings (JSONB — nozzle-specific overrides)
    -- Structure: {"brass_0.4": {...settings...}, "hardened_steel_0.4": {...}, ...}
    pro_settings_by_nozzle  JSONB,

    -- Notes and metadata
    bed_adhesion_notes      TEXT,
    common_challenges       TEXT,
    post_processing_notes   TEXT,
    typical_use_cases       TEXT,
    incompatible_with       TEXT[],
    works_well_with         TEXT[],

    data_tier               data_tier NOT NULL DEFAULT 'free',
    research_status         research_status NOT NULL DEFAULT 'draft',
    last_researched_at      TIMESTAMPTZ,
    source_url              TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (manufacturer_id, slug)
);
CREATE INDEX idx_filaments_manufacturer ON filaments(manufacturer_id);
CREATE INDEX idx_filaments_category ON filaments(category);
CREATE INDEX idx_filaments_data_tier ON filaments(data_tier);
CREATE INDEX idx_filaments_pro_nozzle ON filaments USING gin(pro_settings_by_nozzle);

-- ============================================================================
-- NOZZLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS nozzle_types (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug                    TEXT NOT NULL UNIQUE,   -- "brass-0.4"
    name                    TEXT NOT NULL,          -- "Brass 0.4mm"
    material                nozzle_material NOT NULL,
    diameter_mm             NUMERIC(4, 2) NOT NULL,
    hardness_hrc            NUMERIC(4, 1),          -- Rockwell hardness
    thermal_conductivity    NUMERIC(6, 3),          -- W/m·K
    max_temp_c              INT,
    abrasion_resistance     TEXT,                   -- 'low' | 'medium' | 'high' | 'extreme'
    compatible_filaments    filament_category[],    -- which categories this nozzle handles
    abrasive_filaments_ok   BOOLEAN NOT NULL DEFAULT FALSE,

    -- How this nozzle type changes print settings vs. brass baseline
    -- Keys: temp_offset_c, flow_multiplier, retraction_multiplier, speed_multiplier,
    --       pressure_advance_notes, pa_recommended_value, cooling_notes
    settings_delta          JSONB,

    -- Full pro settings matrix — per filament category
    -- Structure: {"PLA": {nozzle_temp_offset: +5, flow_rate_pct: 98, ...}, "PA_CF": {...}}
    pro_settings_matrix     JSONB,

    manufacturer            TEXT,
    typical_cost_usd        NUMERIC(6, 2),
    lifespan_notes          TEXT,
    when_to_use             TEXT,
    maintenance_notes       TEXT,
    notes                   TEXT,

    data_tier               data_tier NOT NULL DEFAULT 'pro',
    research_status         research_status NOT NULL DEFAULT 'draft',
    last_researched_at      TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Nozzle × filament compatibility matrix with full validated pro settings
CREATE TABLE IF NOT EXISTS nozzle_filament_settings (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nozzle_type_id              UUID NOT NULL REFERENCES nozzle_types(id) ON DELETE CASCADE,
    filament_id                 UUID NOT NULL REFERENCES filaments(id) ON DELETE CASCADE,

    -- Validated print settings for this exact nozzle + filament combination
    nozzle_temp_c               INT,
    bed_temp_c                  INT,
    print_speed_mms             INT,
    first_layer_speed_mms       INT,
    outer_wall_speed_mms        INT,
    inner_wall_speed_mms        INT,
    infill_speed_mms            INT,
    travel_speed_mms            INT,
    cooling_fan_pct             INT,
    retraction_mm               NUMERIC(4, 1),
    retraction_speed_mms        INT,
    flow_rate_pct               NUMERIC(5, 1),
    pressure_advance            NUMERIC(6, 4),
    line_width_mm               NUMERIC(4, 2),
    layer_height_rec_mm         NUMERIC(4, 2),
    layer_height_max_mm         NUMERIC(4, 2),

    -- Quality notes
    quality_score               INT,                -- 0-100, measured by eval agent
    validation_notes            TEXT,
    validated_at                TIMESTAMPTZ,
    validated_by                TEXT,               -- 'research_agent' | 'community' | 'manufacturer'

    data_tier                   data_tier NOT NULL DEFAULT 'pro',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (nozzle_type_id, filament_id)
);
CREATE INDEX idx_nozzle_filament_nozzle ON nozzle_filament_settings(nozzle_type_id);
CREATE INDEX idx_nozzle_filament_filament ON nozzle_filament_settings(filament_id);

-- ============================================================================
-- SLICER PRESET CACHE (what the slicer bridge writes, slicer reads)
-- ============================================================================

CREATE TABLE IF NOT EXISTS slicer_preset_versions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tier            data_tier NOT NULL,
    version         TEXT NOT NULL,              -- semver: "1.0.0"
    checksum        TEXT NOT NULL,              -- SHA-256 of full payload
    payload_gzip    BYTEA,                      -- gzip-compressed JSON bundle
    published_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX idx_preset_versions_tier_active ON slicer_preset_versions(tier, is_active);

-- ============================================================================
-- RESEARCH SESSIONS (generic — any research task, not just filaments)
-- ============================================================================

CREATE TABLE IF NOT EXISTS research_sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         TEXT,                       -- orchestrator run ID
    domain          TEXT NOT NULL,              -- 'filaments' | 'nozzles' | 'custom'
    query           TEXT NOT NULL,              -- original research question
    method          TEXT,                       -- 'web_search' | 'scrape' | 'rag' | 'hybrid'
    status          research_status NOT NULL DEFAULT 'draft',
    agent_id        TEXT,                       -- which agent ran this
    findings_count  INT NOT NULL DEFAULT 0,
    quality_score   NUMERIC(4, 2),              -- 0.0–1.0, set by research evaluator
    eval_report     JSONB,                      -- full eval JSON from research_evaluator
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS research_findings (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      UUID NOT NULL REFERENCES research_sessions(id) ON DELETE CASCADE,
    fact            TEXT NOT NULL,
    source_url      TEXT,
    source_type     TEXT,                       -- 'web' | 'lancedb' | 'datasheet' | 'community'
    confidence      NUMERIC(3, 2),              -- 0.00–1.00
    domain_tag      TEXT,                       -- 'filament.pla.temps' etc.
    entity_type     TEXT,                       -- 'manufacturer' | 'filament' | 'nozzle' | 'setting'
    entity_id       UUID,                       -- FK to relevant entity (nullable — not all refs)
    verified        BOOLEAN NOT NULL DEFAULT FALSE,
    verified_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_findings_session ON research_findings(session_id);
CREATE INDEX idx_findings_confidence ON research_findings(confidence DESC);

-- ============================================================================
-- AUDIT LOG
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor       TEXT,                           -- user_id or 'system' or agent name
    action      TEXT NOT NULL,                  -- 'token_issued' | 'preset_fetched' | etc.
    resource    TEXT,                           -- table + id
    detail      JSONB
);
CREATE INDEX idx_audit_log_ts ON audit_log(ts DESC);
CREATE INDEX idx_audit_log_actor ON audit_log(actor);

-- ============================================================================
-- UPDATED_AT trigger function
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER trg_subscriptions_updated_at BEFORE UPDATE ON subscriptions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER trg_filaments_updated_at BEFORE UPDATE ON filaments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER trg_manufacturers_updated_at BEFORE UPDATE ON filament_manufacturers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER trg_nozzle_types_updated_at BEFORE UPDATE ON nozzle_types
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER trg_nozzle_fs_updated_at BEFORE UPDATE ON nozzle_filament_settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
