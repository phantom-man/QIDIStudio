"""
schemas/research_data.py — Generic Pydantic v2 models for research recording.

Designed to be domain-agnostic: used by the filament pipeline, nozzle pipeline,
and any future research agent. All structured research outputs land in these types
before being written to BigQuery (raw) or Cloud SQL (validated).

Usage:
    from schemas.research_data import ResearchRun, ResearchFinding, ResearchReport

    finding = ResearchFinding(
        fact="Bambu Lab PLA Basic prints best at 220°C on a 35°C bed",
        source="https://wiki.bambulab.com/...",
        confidence=0.92,
        domain_tag="filament.pla.temps",
    )
    run = ResearchRun(query="Bambu Lab PLA settings", findings=[finding])
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ── Source / Provenance ──────────────────────────────────────────────────────


class ResearchSource(BaseModel):
    """A single source citation used in a research run."""

    model_config = ConfigDict(frozen=True)

    url: str
    title: str | None = None
    domain: str | None = None  # 'amazon.com', 'wiki.bambulab.com', ...
    source_type: str = "web"  # web | datasheet | community | lancedb | amazon
    scraped_at: datetime | None = None
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("url")
    @classmethod
    def url_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Source URL must not be empty")
        return v.strip()


# ── Individual Finding ────────────────────────────────────────────────────────


class ResearchFinding(BaseModel):
    """
    A single atomic research finding.

    A 'finding' is one discrete, citable fact from a research run:
        - "Bambu Lab PLA Basic nozzle temp range: 190–230°C"
        - "Ruby nozzle outperforms hardened steel for abrasive PA-CF at 0.4mm"
    Findings are the unit of quality evaluation and LanceDB storage.
    """

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    fact: str = Field(
        min_length=5, description="The precise research finding as a complete sentence"
    )
    source: ResearchSource | None = None
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="0.0 = speculation | 0.5 = single source | 1.0 = multi-source verified",
    )
    domain_tag: str | None = Field(
        default=None, description="Hierarchical dot-path tag, e.g. 'filament.pla.temps'"
    )
    entity_type: str | None = Field(
        default=None,
        description="manufacturer | filament | nozzle | setting | hardware",
    )
    entity_id: uuid.UUID | None = None  # FK to Cloud SQL entity when available
    verified: bool = False
    verified_by: str | None = None  # 'research_agent' | 'evaluator' | 'human'
    verified_at: datetime | None = None
    raw_snippet: str | None = Field(
        default=None, description="Raw text that this finding was extracted from"
    )

    @field_validator("domain_tag")
    @classmethod
    def valid_domain_tag(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Sanitize: lowercase, replace spaces/slashes with _, strip disallowed chars
        import re as _re
        v = v.strip().lower()
        v = _re.sub(r"[ /\\]+", "_", v)     # spaces/slashes → underscore
        v = _re.sub(r"[^a-z0-9._\-]", "", v)  # strip anything else
        v = _re.sub(r"_+", "_", v)            # collapse repeated underscores
        v = v.strip("._-")                    # trim leading/trailing punctuation
        return v or None


# ── Knowledge Gap ─────────────────────────────────────────────────────────────


class KnowledgeGap(BaseModel):
    """Something we could not find or verify during this research run."""

    model_config = ConfigDict(frozen=True)

    description: str
    importance: str = "medium"  # low | medium | high | critical
    suggested_query: str | None = None
    domain_tag: str | None = None


# ── Research Run ─────────────────────────────────────────────────────────────


class ResearchRun(BaseModel):
    """
    A single complete research run by an agent.

    Maps to: BigQuery `raw_research_runs` + Cloud SQL `research_sessions`.
    One ResearchRun = one agent invocation for one query.
    """

    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    duration_secs: int | None = None

    # Query context
    query: str = Field(min_length=3, description="The original research question")
    domain: str = Field(description="filaments | nozzles | hardware | custom")
    method: str = "hybrid"  # web_search | scrape | rag | hybrid
    agent_id: str | None = None

    # Results
    findings: list[ResearchFinding] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)
    knowledge_gaps: list[KnowledgeGap] = Field(default_factory=list)
    learned_facts: list[str] = Field(
        default_factory=list,
        description="High-level bullet-point synthesis of all findings",
    )

    # Evaluation (filled in by ResearchEvaluator)
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    eval_report: "ResearchEvalReport | None" = None
    status: str = "draft"  # draft | validated | published | deprecated

    # LangSmith / BQ tracking
    langsmith_run_id: str | None = None
    bq_row_id: str | None = None  # BigQuery insert ID for this row

    @model_validator(mode="after")
    def compute_duration(self) -> "ResearchRun":
        if self.completed_at and self.started_at and self.duration_secs is None:
            object.__setattr__(
                self,
                "duration_secs",
                int((self.completed_at - self.started_at).total_seconds()),
            )
        return self

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def high_confidence_findings(self) -> list[ResearchFinding]:
        return [f for f in self.findings if f.confidence >= 0.8]


# ── Evaluation Sub-Scores ─────────────────────────────────────────────────────


class ResearchEvalScores(BaseModel):
    """Numeric breakdown from the research_evaluator agent."""

    model_config = ConfigDict(frozen=True)

    source_quality: float = Field(
        ge=0.0, le=1.0, description="Are sources authoritative and citable?"
    )
    completeness: float = Field(
        ge=0.0, le=1.0, description="Were all required fields found?"
    )
    accuracy: float = Field(
        ge=0.0, le=1.0, description="Internal consistency, cross-source agreement"
    )
    consistency: float = Field(
        ge=0.0, le=1.0, description="No contradictions within findings"
    )
    actionability: float = Field(
        ge=0.0, le=1.0, description="Can the slicer actually use this data?"
    )
    overall: float = Field(ge=0.0, le=1.0, description="Weighted composite score")

    @model_validator(mode="after")
    def overall_in_range(self) -> "ResearchEvalScores":
        expected = round(
            0.25 * self.source_quality
            + 0.20 * self.completeness
            + 0.25 * self.accuracy
            + 0.15 * self.consistency
            + 0.15 * self.actionability,
            4,
        )
        # Allow specified override (e.g. evaluator gave a different weight)
        if abs(self.overall - expected) > 0.1:
            pass  # Warn but don't reject — evaluator may use custom weights
        return self


class ResearchEvalReport(BaseModel):
    """Full quality evaluation report for a ResearchRun."""

    model_config = ConfigDict(frozen=True)

    eval_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: uuid.UUID
    domain: str
    scores: ResearchEvalScores
    verdict: str = Field(
        description="PASS | FAIL | NEEDS_IMPROVEMENT",
        pattern=r"^(PASS|FAIL|NEEDS_IMPROVEMENT)$",
    )
    gaps_found: list[KnowledgeGap] = Field(default_factory=list)
    improvements: list[str] = Field(
        default_factory=list, description="Concrete improvement suggestions"
    )
    evaluator_notes: str | None = None


# ── Multi-Run Research Report ─────────────────────────────────────────────────


class ResearchReport(BaseModel):
    """
    A synthesized report across multiple ResearchRun instances.

    Use this when you ran 3 parallel research queries on the same topic
    (e.g. filament manufacturer data from Amazon + manufacturer site + YouTube)
    and want to merge them into one structured output.
    """

    model_config = ConfigDict(frozen=True)

    report_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    topic: str
    domain: str

    runs: list[ResearchRun] = Field(min_length=1)
    synthesis: str = Field(
        description="Narrative synthesis of all findings across all runs"
    )
    all_findings: list[ResearchFinding] = Field(default_factory=list)
    all_gaps: list[KnowledgeGap] = Field(default_factory=list)

    evaluator_score: float | None = Field(default=None, ge=0.0, le=1.0)
    is_ready_for_db: bool = False  # True once evaluator passed it

    @model_validator(mode="after")
    def aggregate_findings(self) -> "ResearchReport":
        if not self.all_findings:
            all_f: list[ResearchFinding] = []
            for run in self.runs:
                all_f.extend(run.findings)
            object.__setattr__(
                self,
                "all_findings",
                sorted(all_f, key=lambda x: x.confidence, reverse=True),
            )
        return self

    @property
    def total_findings(self) -> int:
        return len(self.all_findings)

    @property
    def best_findings(self) -> list[ResearchFinding]:
        """Top 20 highest-confidence findings across all runs."""
        return self.all_findings[:20]


# ── Filament-Specific Research Schema ────────────────────────────────────────


class FilamentResearchData(BaseModel):
    """
    Structured output from a filament research run.
    Normalised into ResearchFinding list before storage.
    Also maps directly to Cloud SQL `filaments` columns.
    """

    manufacturer_name: str
    manufacturer_slug: str
    product_name: str
    product_slug: str
    category: str  # FilamentCategory value
    color_name: str | None = None
    asin: str | None = None
    amazon_rating: float | None = None
    amazon_review_count: int | None = None

    # Print settings
    nozzle_temp_min_c: int | None = None
    nozzle_temp_max_c: int | None = None
    nozzle_temp_rec_c: int | None = None
    bed_temp_min_c: int | None = None
    bed_temp_max_c: int | None = None
    bed_temp_rec_c: int | None = None
    chamber_temp_rec_c: int | None = None
    print_speed_rec_mms: int | None = None
    cooling_fan_rec_pct: int | None = None
    retraction_direct_mm: float | None = None
    retraction_bowden_mm: float | None = None
    retraction_speed_mms: int | None = None
    flow_rate_pct: float | None = None

    # Physical properties
    diameter_mm: float = 1.75
    diameter_tolerance_mm: float | None = None
    density_g_cm3: float | None = None
    tensile_strength_mpa: float | None = None
    glass_transition_temp_c: float | None = None
    heat_deflection_temp_c: float | None = None

    # Boolean flags
    requires_enclosure: bool | None = None
    requires_dry_box: bool | None = None
    drying_temp_c: int | None = None
    drying_time_hours: int | None = None
    food_safe: bool | None = None
    flexible: bool | None = None
    uv_resistant: bool | None = None

    # Notes
    common_challenges: str | None = None
    bed_adhesion_notes: str | None = None
    typical_use_cases: str | None = None
    incompatible_with: list[str] = Field(default_factory=list)

    # Source
    source_url: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    raw_data: dict[str, Any] = Field(default_factory=dict)


# ── Nozzle-Specific Research Schema ──────────────────────────────────────────


class NozzleResearchData(BaseModel):
    """
    Structured output from a nozzle research run.
    Maps directly to Cloud SQL `nozzle_types` columns.

    A permissive model_validator(mode='before') strips null values and coerces
    LLM quirks (confidence as string, null lists, null bool) before Pydantic
    strict validation fires.
    """

    model_config = ConfigDict(populate_by_name=True)

    slug: str
    name: str
    material: str = "unknown"  # NozzleMaterial value
    diameter_mm: float = 0.4
    hardness_hrc: float | None = None
    thermal_conductivity_w_mk: float | None = None
    max_temp_c: int | None = None
    abrasion_resistance: str | None = None  # low | medium | high | extreme

    # Temp delta vs brass baseline (positive = hotter)
    temp_offset_c: int | None = None
    flow_multiplier: float | None = None  # 1.0 = no change; 0.95 = 5% less
    retraction_multiplier: float | None = None
    speed_multiplier: float | None = None
    pressure_advance_offset: float | None = None

    # Per-material category pro settings
    # {"PLA": {"nozzle_temp_offset": +5, "flow_rate_pct": 98, ...}, ...}
    pro_settings_matrix: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # Compatibility
    compatible_filaments: list[str] = Field(default_factory=list)
    damages_from: list[str] = Field(
        default_factory=list, description="Filament categories that DAMAGE this nozzle"
    )
    abrasive_filaments_ok: bool = False

    # Metadata
    manufacturer: str | None = None
    typical_cost_usd: float | None = None
    when_to_use: str | None = None
    lifespan_notes: str | None = None
    maintenance_notes: str | None = None
    notes: str | None = None

    # Source
    source_url: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _sanitize_llm_output(cls, values: Any) -> Any:
        """
        Coerce common LLM output quirks before Pydantic strict validation.
        - null str   → "unknown" or None depending on field
        - null list  → []
        - null bool  → False
        - null dict  → {}
        - list str   → joined string (manufacturer, source_url take first element)
        - confidence as string ("low"/"medium"/"high" or "unavailable") → float
        - confidence on 1–10 scale → divide by 10
        - cost range string ("1-10") → midpoint float
        """
        if not isinstance(values, dict):
            return values

        _conf_map: dict[str, float] = {
            "very low": 0.1, "low": 0.25, "medium": 0.5,
            "high": 0.75, "very high": 0.9, "unavailable": 0.0, "unknown": 0.0,
        }

        for k, v in list(values.items()):
            if v is None:
                if k == "material":
                    values[k] = "unknown"
                elif k in ("compatible_filaments", "damages_from"):
                    values[k] = []
                elif k == "pro_settings_matrix":
                    values[k] = {}
                elif k == "abrasive_filaments_ok":
                    values[k] = False
                # Other None fields → pass through as None (Optional fields)

            # List where a single string is expected
            elif isinstance(v, list):
                if k == "manufacturer":
                    values[k] = ", ".join(str(i) for i in v) if v else None
                elif k == "source_url":
                    values[k] = str(v[0]) if v else None
                elif k == "compatible_filaments":
                    values[k] = [str(i) for i in v]
                elif k == "damages_from":
                    values[k] = [str(i) for i in v]

            # Cost as range string e.g. "1-10" or "$5-15" → midpoint float
            elif k == "typical_cost_usd" and isinstance(v, str):
                import re as _re
                nums = [float(x) for x in _re.findall(r"\d+(?:\.\d+)?", v)]
                values[k] = (nums[0] + nums[-1]) / 2 if len(nums) >= 2 else (nums[0] if nums else None)

        # Confidence coercion (run after the loop so None is already replaced)
        raw_conf = values.get("confidence")
        if isinstance(raw_conf, str):
            normalized = raw_conf.strip().lower()
            values["confidence"] = _conf_map.get(normalized, 0.0)
        elif raw_conf is None:
            values["confidence"] = 0.0
        elif isinstance(raw_conf, (int, float)) and raw_conf > 1.0:
            # LLM used a 1–10 scale — normalize to 0–1
            values["confidence"] = min(raw_conf / 10.0, 1.0)

        return values
