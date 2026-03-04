"""
agents/parts_catalog/schema.py

Canonical Pydantic schemas for every part category in the NexusMill parts catalog.
Every harvester normalises its scraped data into one of these models before writing
to Firestore / GCS / LanceDB.

Firestore layout:
    cnc_parts/motors/{doc_id}
    cnc_parts/drivers/{doc_id}
    cnc_parts/power_supplies/{doc_id}
    cnc_parts/rails/{doc_id}
    cnc_parts/lead_screws/{doc_id}
    cnc_parts/spindles/{doc_id}
    cnc_parts/controllers/{doc_id}
    cnc_parts/frames/{doc_id}
    cnc_parts/machine_templates/{doc_id}
    cnc_parts/kits/{doc_id}

GCS bucket: qidistudio-parts
    parts_catalog/{category}/{doc_id}/data.json
    parts_catalog/{category}/{doc_id}/image.jpg  (if available)

LanceDB table: cnc_parts
    Fields: doc_id, category, name, description_text, embedding (vector)
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─── Enums ────────────────────────────────────────────────────────────────────


class MotorType(str, Enum):
    STEPPER_BIPOLAR = "stepper_bipolar"
    STEPPER_UNIPOLAR = "stepper_unipolar"
    STEPPER_HYBRID = "stepper_hybrid"  # most NEMA motors
    SERVO_BRUSHED = "servo_brushed"
    SERVO_BRUSHLESS = "servo_brushless"
    SERVO_CLOSED_LOOP_STEPPER = "servo_closed_loop_stepper"  # StepServo / iHSS


class DriverType(str, Enum):
    # Legacy
    STEPPER_ANALOG = "stepper_analog"
    STEPPER_DIGITAL = "stepper_digital"
    STEPPER_TMC = "stepper_tmc"
    SERVO_DIGITAL = "servo_digital"
    INTEGRATED = "integrated"
    # Harvester-friendly
    STEPPER_MODULE = "stepper_module"  # Pololu-style breakout
    STEPPER_DIN = "stepper_din"  # enclosed DIN rail (DM542, DMA860S)
    SERVO_CLOSED_LOOP_STEPPER = "servo_closed_loop_stepper"  # CL57, iHSS
    SERVO_AC_BRUSHLESS = "servo_ac_brushless"  # full AC servo drive


class RailType(str, Enum):
    LINEAR_RAIL_MGN = "linear_rail_mgn"  # hiwin-style profiled
    LINEAR_RAIL_HGR = "linear_rail_hgr"  # heavy-duty hiwin
    LINEAR_SHAFT_ROUND = "linear_shaft_round"  # rod + linear bearing
    V_SLOT = "v_slot"  # V-wheels on extrusion
    DOVETAIL = "dovetail"
    BOX_WAY = "box_way"  # machine tool


class ScrewType(str, Enum):
    # Legacy
    ACME_TR = "acme_tr"
    BALL_SCREW = "ball_screw"
    RACK_PINION = "rack_pinion"
    LEAD_SCREW_IMPERIAL = "lead_screw_imperial"
    # Harvester-friendly
    BALL_SFU = "ball_sfu"
    BALL_CUSTOM = "ball_custom"
    RACK_GEAR = "rack_gear"
    BELT_DRIVE = "belt_drive"


class MachineType(str, Enum):
    # Legacy
    ROUTER_3_AXIS = "router_3_axis"
    ROUTER_COREXY = "router_corexy"
    ROUTER_5_AXIS = "router_5_axis"
    ROUTER_GANTRY = "router_gantry"
    MILL_BENCHTOP = "mill_benchtop"
    MILL_VERTICAL = "mill_vertical"
    LATHE = "lathe"
    PLASMA_CUTTER = "plasma_cutter"
    LASER_CO2 = "laser_co2"
    LASER_DIODE = "laser_diode"
    GRINDING = "grinding"
    EDM_WIRE = "edm_wire"
    # Harvester-friendly
    CNC_ROUTER_3AXIS = "cnc_router_3axis"
    BENCHTOP_MILL = "benchtop_mill"
    COREXY_PRINTER = "corexy_printer"
    CNC_LATHE = "cnc_lathe"
    CO2_LASER = "co2_laser"
    PLASMA_TABLE = "plasma_table"
    FIVE_AXIS_MILL = "five_axis_mill"


class Tier(str, Enum):
    HOBBY = "hobby"
    PROSUMER = "prosumer"
    INDUSTRIAL = "industrial"
    AEROSPACE = "aerospace"


# ─── Shared base ──────────────────────────────────────────────────────────────


class PartBase(BaseModel):
    """Common fields every part record must have."""

    doc_id: str = Field(
        description="Slug: {category}_{brand}_{model} lowercased, hyphens"
    )
    category: str
    name: str
    brand: str
    model: str
    tier: Tier = Tier.HOBBY
    description: str = ""
    datasheet_url: str = ""
    image_url: str = ""  # source URL (harvested → stored to GCS)
    image_gcs: str = ""  # gs:// path after download
    purchase_urls: list[dict[str, str]] = Field(
        default_factory=list,
        description="[{supplier: 'Amazon', url: 'https://...', price_usd: '24.99'}]",
    )
    affiliate_tags: dict[str, str] = Field(
        default_factory=dict, description="affiliate program tags per supplier"
    )
    tags: list[str] = Field(default_factory=list)
    scraped_at: str = ""
    source_urls: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)


# ─── Stepper / Servo Motors ───────────────────────────────────────────────────


class TorqueCurvePoint(BaseModel):
    rpm: float
    torque_nm: float


class Motor(PartBase):
    category: str = "motors"
    motor_type: MotorType = MotorType.STEPPER_HYBRID
    nema_size: int | None = None  # 8, 11, 14, 17, 23, 24, 34, 42
    frame_mm: float | None = None  # e.g. 42.3 for NEMA 17
    body_length_mm: float | None = None
    step_angle_deg: float = 1.8  # 1.8 or 0.9
    steps_per_rev: int = 200
    rated_current_a: float | None = None
    phase_resistance_ohm: float | None = None
    phase_inductance_mh: float | None = None
    holding_torque_nm: float | None = None
    detent_torque_nm: float | None = None
    rotor_inertia_gcm2: float | None = None
    weight_kg: float | None = None
    shaft_diameter_mm: float | None = None
    shaft_length_mm: float | None = None
    voltage_range_v: tuple[float, float] | None = None
    has_encoder: bool = False
    encoder_ppr: int | None = None
    torque_curve: list[TorqueCurvePoint] = Field(default_factory=list)
    ip_rating: str = ""  # e.g. "IP54"
    max_temp_c: float | None = None
    wiring: str = ""  # "4-wire", "6-wire", "8-wire"


# ─── Stepper / Servo Drivers ──────────────────────────────────────────────────


class MicrostepTable(BaseModel):
    """Map of divisor → steps_per_rev, e.g. {1: 200, 2: 400, 8: 1600, 400: 80000}"""

    divisors: list[int] = Field(default_factory=list)


class Driver(PartBase):
    category: str = "drivers"
    driver_type: DriverType = DriverType.STEPPER_DIN

    # Flat fields — harvesters use these
    input_voltage_min_v: float | None = None
    input_voltage_max_v: float | None = None
    peak_current_a: float | None = None
    rms_current_a: float | None = None
    microstep_divisors: list[int] = Field(default_factory=list)
    max_microstep_divisor: int | None = None
    logic_voltage_v: float | None = None
    control_interface: str = "step/dir"
    encoder_input: bool = False
    max_encoder_ppr: int | None = None
    has_stealthchop: bool = False
    has_spreadcycle: bool = False
    over_current_protection: bool = False
    over_temp_protection: bool = False
    short_circuit_protection: bool = False
    dimensions_mm: str | None = None
    weight_kg: float | None = None

    # Legacy compat
    microstep_table: MicrostepTable = Field(default_factory=MicrostepTable)
    input_voltage_ac: tuple[float, float] | None = None
    input_voltage_dc: tuple[float, float] | None = None
    accepts_ac: bool = False
    accepts_dc: bool = False
    output_current_peak_a: float | None = None
    output_current_rms_a: float | None = None
    step_pulse_input: str = ""
    has_anti_resonance: bool = False
    has_current_auto_halving: bool = False
    has_fault_protection: bool = False
    fault_outputs: list[str] = Field(default_factory=list)
    communication: str = ""
    compatible_motor_sizes: list[int] = Field(default_factory=list)


# ─── Power Supplies ───────────────────────────────────────────────────────────


class PowerSupply(PartBase):
    category: str = "power_supplies"
    psu_type: str = "dc_switching"

    # Flat fields — harvesters use these
    output_voltage_v: float | None = None
    output_current_a: float | None = None
    output_power_w: float | None = None
    input_voltage_range: str | None = None  # e.g. "85-264VAC"
    input_phases: int = 1
    efficiency_percent: float | None = None
    output_ripple_mv: float | None = None
    vfd_output_freq_min_hz: float | None = None
    vfd_output_freq_max_hz: float | None = None
    vfd_motor_hp: float | None = None
    vfd_control_modes: list[str] = Field(default_factory=list)
    laser_hv_kv: float | None = None
    laser_tube_current_ma: float | None = None
    protection_features: list[str] = Field(default_factory=list)
    dimensions_mm: str | None = None
    weight_kg: float | None = None

    # Legacy compat
    input_ac_v: tuple[float, float] | None = None
    input_frequency_hz: tuple[float, float] | None = None
    output_dc_v: float | None = None
    output_dc_v_adjustable: tuple[float, float] | None = None
    output_channels: int = 1
    regulation_percent: float | None = None
    ripple_mv: float | None = None
    protection: list[str] = Field(default_factory=list)
    form_factor: str = ""
    certifications: list[str] = Field(default_factory=list)
    suitable_for: list[str] = Field(default_factory=list)


# ─── Linear Rails ─────────────────────────────────────────────────────────────


class Rail(PartBase):
    category: str = "rails"
    rail_type: RailType = RailType.MGN_MINIATURE

    # Flat fields — harvesters use these
    rail_series: str | None = None
    rail_width_mm: float | None = None
    rail_height_mm: float | None = None
    shaft_diameter_mm: float | None = None
    block_model: str | None = None
    block_type: str | None = None
    static_load_rating_n: float | None = None
    dynamic_load_rating_n: float | None = None
    static_moment_rating_nm: float | None = None
    accuracy_class: str | None = None
    preload_class: str | None = None
    max_speed_m_s: float | None = None
    available_lengths_mm: list[int] = Field(default_factory=list)
    price_per_500mm_usd: float | None = None

    # Legacy compat
    model_series: str = ""
    carriage_model: str = ""
    carriage_preload: str = ""
    dynamic_load_n: float | None = None
    static_load_n: float | None = None
    moment_pitch_nm: float | None = None
    moment_yaw_nm: float | None = None
    moment_roll_nm: float | None = None
    material: str = "steel"
    hardness_hrc: float | None = None
    mounting: str = ""
    price_per_100mm_usd: float | None = None
    price_carriage_usd: float | None = None


# ─── Lead Screws & Ball Screws ────────────────────────────────────────────────


class LeadScrew(PartBase):
    category: str = "lead_screws"
    screw_type: ScrewType = ScrewType.BALL_SFU

    diameter_mm: float | None = None
    pitch_mm: float | None = None
    lead_mm: float | None = None
    starts: int = 1
    accuracy_class: str | None = None
    ball_size_mm: float | None = None

    # Load ratings in kN (harvester-preferred)
    dynamic_load_kn: float | None = None
    static_load_kn: float | None = None
    efficiency_percent: float | None = None
    standard_lengths_mm: list[int] = Field(default_factory=list)
    available_lengths_mm: list[int] = Field(default_factory=list)
    max_length_mm: float | None = None
    nut_type: str | None = None
    nut_material: str | None = None
    end_support_unit: str | None = None
    material: str | None = None

    # Legacy compat (N instead of kN)
    dynamic_load_n: float | None = None
    static_load_n: float | None = None
    nut_model: str = ""
    anti_backlash: bool = False
    backlash_um: float | None = None
    end_machining: str = ""
    lead_efficiency_percent: float | None = None
    price_per_100mm_usd: float | None = None
    price_nut_usd: float | None = None
    price_end_support_usd: float | None = None


# ─── Spindles ─────────────────────────────────────────────────────────────────


class Spindle(PartBase):
    category: str = "spindles"
    spindle_type: str = "water_cooled"

    # Power / speed — harvesters use these
    power_kw: float | None = None
    power_w: float | None = None  # legacy (W)
    voltage_v: float | None = None
    phases: int | None = None
    frequency_hz_min: float | None = None
    frequency_hz_max: float | None = None
    rpm_min: int | None = None
    rpm_max: int | None = None

    # Tooling
    collet_type: str | None = None
    max_collet_diameter_mm: float | None = None
    taper: str = ""

    # Accuracy
    tir_runout_mm: float | None = None
    runout_mm: float | None = None  # legacy

    # Cooling
    cooling_type: str | None = None
    water_flow_lpm: float | None = None
    cooling: str = ""  # legacy

    # Bearings
    bearing_type: str | None = None
    bearing_count: int | None = None

    # ATC
    atc: bool = False
    atc_tool_change_time_s: float | None = None
    atc_air_pressure_bar: float | None = None

    # Physical
    body_diameter_mm: float | None = None
    body_length_mm: float | None = None
    weight_kg: float | None = None
    noise_db: float | None = None

    # Legacy
    requires_vfd: bool = False
    vfd_model: str = ""
    input_voltage: str = ""
    collet_diameter_range_mm: tuple[float, float] | None = None
    nose_diameter_mm: float | None = None
    mount_diameter_mm: float | None = None


# ─── Motion Controllers ───────────────────────────────────────────────────────


class Controller(PartBase):
    category: str = "controllers"

    # Flat fields — harvesters use these
    firmware: str | None = None
    mcu: str | None = None
    axes: int | None = None
    max_step_rate_khz: float | None = None
    step_dir_outputs: int | None = None
    encoder_inputs: int = 0
    digital_inputs: int | None = None
    digital_outputs: int | None = None
    analog_inputs: int | None = None
    spindle_control: str | None = None
    spindle_pwm_hz: float | None = None
    communication: list[str] = Field(default_factory=list)
    realtime_required: bool = False
    driver_sockets: int | None = None
    integrated_drivers: bool = False
    max_driver_current_a: float | None = None
    input_voltage_v: float | None = None

    # Legacy compat
    controller_type: str = ""
    step_gen_hz: float | None = None
    inputs_digital: int | None = None
    outputs_digital: int | None = None
    spindle_pwm: bool = False
    requires_pc: bool = False
    standalone: bool = False
    processor: str = ""
    form_factor: str = ""
    compatible_software: list[str] = Field(default_factory=list)
    estop_input: bool = False
    probe_input: bool = False


# ─── Frames & Extrusion ───────────────────────────────────────────────────────


class Frame(PartBase):
    category: str = "frames"

    # Flat fields — harvesters use these
    frame_type: str = "extrusion_metric"
    profile_width_mm: float | None = None
    profile_height_mm: float | None = None
    slot_width_mm: float | None = None
    weight_per_meter_kg: float | None = None
    moment_of_inertia_cm4: float | None = None
    section_modulus_cm3: float | None = None
    tensile_strength_mpa: float | None = None
    alloy: str | None = None
    anodized: bool = True
    anodize_color: str | None = None
    t_nut_size_m: float | None = None
    available_lengths_mm: list[int] = Field(default_factory=list)
    prebuilt_work_area_mm: str | None = None
    prebuilt_footprint_mm: str | None = None
    prebuilt_weight_kg: float | None = None
    price_per_meter_usd: float | None = None

    # Legacy compat
    profile: str = ""
    mass_per_m_kg: float | None = None
    material: str = ""
    t_slot_compatible: bool = True
    price_per_m_usd: float | None = None


# ─── Machine Templates ────────────────────────────────────────────────────────


class PartRef(BaseModel):
    category: str
    doc_id: str
    name: str = ""
    quantity: int = 1
    notes: str = ""


class KitBundle(PartBase):
    """A curated known-good or premium machine construction kit."""

    category: str = "kits"
    machine_type: MachineType = MachineType.CNC_ROUTER_3AXIS
    parts: list[PartRef] = Field(default_factory=list)
    estimated_cost_usd: float | None = None
    work_envelope_mm: str | None = None  # "400x400x80"
    typical_resolution_um: float | None = None
    typical_max_feed_mm_min: float | None = None
    notes: str = ""
    affiliate_bundle_available: bool = False
    affiliate_bundle_url: str | None = None
    affiliate_bundle_discount_percent: float | None = None


class MachineTemplate(PartBase):
    """Structural template for a machine type: axis count, kinematic,
    required part categories, and optional curated kit references."""

    category: str = "templates"
    machine_type: MachineType = MachineType.CNC_ROUTER_3AXIS
    required_axis_count: int = 3
    required_categories: list[str] = Field(default_factory=list)
    typical_tier: str = "hobby"
    kinematic: str = ""
    axis_map: dict[str, str] = Field(default_factory=dict)
    typical_frame: str = ""
    kits: list[str] = Field(default_factory=list)
    notes: str = ""
    sound_asset_key: str = ""
