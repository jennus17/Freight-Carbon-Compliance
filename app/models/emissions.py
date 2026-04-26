"""Pydantic schemas for the carbon footprint calculation endpoints."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator


class TransportType(str, Enum):
    TRUCK = "truck"
    SHIP = "ship"
    AIR = "air"
    RAIL = "rail"


class MethodologyVersion(str, Enum):
    """
    Pin the calculation to a specific methodology vintage. ``LATEST`` always
    tracks the most recent published vintage; an explicit year is frozen so
    historical CSRD reports stay reproducible across DEFRA updates.
    """

    LATEST = "latest"
    DEFRA_2023 = "2023"
    DEFRA_2024 = "2024"
    DEFRA_2025 = "2025"


class FuelType(str, Enum):
    """Operator-specified fuel/energy carrier — overrides the mode default."""

    DIESEL = "diesel"
    DIESEL_B7 = "diesel_b7"
    HVO100 = "hvo100"
    BIODIESEL_B20 = "biodiesel_b20"
    LNG = "lng"
    HFO = "hfo"
    MGO = "mgo"
    JET_A1 = "jet_a1"
    SAF_BLEND_30 = "saf_blend_30"
    SAF_NEAT = "saf_neat"
    METHANOL_GREY = "methanol_grey"
    METHANOL_GREEN = "methanol_green"
    ELECTRIC = "electric"


# Reasonable real-world bounds — anything outside these is almost certainly a
# data-entry error, and rejecting at the boundary protects audit integrity.
MAX_WEIGHT_KG = 1_000_000_000.0   # 1 megatonne — covers full bulk-carrier loads
MAX_DISTANCE_KM = 50_000.0        # > circumference of Earth (40,075 km)


class EmissionRequest(BaseModel):
    """Input for a single shipment carbon-footprint calculation."""

    weight_kg: Annotated[float, Field(
        gt=0,
        le=MAX_WEIGHT_KG,
        description="Gross shipment weight in kilograms. Must be > 0.",
        examples=[1500.0],
    )]
    distance_km: Annotated[float, Field(
        gt=0,
        le=MAX_DISTANCE_KM,
        description="Transport distance in kilometres. Must be > 0.",
        examples=[420.5],
    )]
    transport_type: Annotated[TransportType, Field(
        description="Primary transport mode.",
        examples=["truck"],
    )]
    sub_mode: Annotated[str | None, Field(
        default=None,
        description=(
            "Optional vehicle/vessel sub-classification (e.g. 'articulated_average', "
            "'long_haul', 'electric'). When omitted, a sensible default for the "
            "transport_type is applied."
        ),
        examples=["articulated_average"],
        max_length=64,
    )] = None
    fuel_type: Annotated[FuelType | None, Field(
        default=None,
        description=(
            "Optional fuel/energy carrier override. When provided, the base activity "
            "factor is adjusted by the fuel-substitution ratio (GLEC v3.0 §6.3) — or, "
            "for 'electric', by the regional grid factor. Must be compatible with the "
            "transport_type (e.g. 'jet_a1' is only valid for 'air')."
        ),
        examples=["hvo100"],
    )] = None
    region: Annotated[str | None, Field(
        default=None,
        description=(
            "Optional ISO-3166-1 alpha-2 country code (or 'EU27' / 'WORLD' aggregate, "
            "or 'US-CA'-style sub-national code). Used to localise the electricity "
            "grid factor when fuel_type='electric'. Ignored for non-electric fuels."
        ),
        examples=["FR"],
        max_length=8,
    )] = None
    methodology_version: Annotated[MethodologyVersion | None, Field(
        default=None,
        description=(
            "Pin the calculation to a specific methodology vintage. Defaults to "
            "the latest published version. Pin to e.g. '2023' to guarantee "
            "stable historical results across future DEFRA updates."
        ),
        examples=["2023"],
    )] = None
    shipment_id: Annotated[str | None, Field(
        default=None,
        description="Optional client-supplied identifier echoed back in the response.",
        max_length=128,
    )] = None

    @field_validator("sub_mode")
    @classmethod
    def _normalise_sub_mode(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        return v or None

    @field_validator("region")
    @classmethod
    def _normalise_region(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().upper()
        return v or None


class ResolutionStep(BaseModel):
    """One step in the factor-derivation chain — preserved for auditors."""

    step: str = Field(description="Machine-readable step identifier.")
    description: str
    value_kg_co2e_per_tkm: float | None = None
    ratio: float | None = None
    source: str | None = None


class MethodologyReference(BaseModel):
    """Auditable provenance of the emission factor used."""

    source: str
    dataset: str
    scope: str
    unit: str
    version: str
    url: str
    csrd_alignment: str
    factor_kg_co2e_per_tkm: float = Field(
        description="Final emission factor applied (after any fuel/region adjustments)."
    )
    sub_mode_resolved: str = Field(
        description="The sub_mode that was actually applied (after defaulting)."
    )
    fuel_resolved: str = Field(
        description="The fuel/energy carrier the calculation effectively used."
    )
    region_resolved: str | None = Field(
        default=None,
        description="The region used for grid-factor lookup, if any.",
    )
    resolution_chain: list[ResolutionStep] = Field(
        default_factory=list,
        description=(
            "Step-by-step derivation of the final factor — base DEFRA factor → "
            "fuel substitution → regional grid adjustment. Reproducible by hand."
        ),
    )
    extra_references: dict[str, Any] = Field(
        default_factory=dict,
        description="Supplementary methodology fields (e.g. fuel-substitution method, grid source).",
    )


class CalculationBreakdown(BaseModel):
    """Intermediate values to make the result reproducible."""

    mass_tonnes: float = Field(description="weight_kg converted to tonnes.")
    distance_km: float
    tonne_km: float = Field(description="mass_tonnes × distance_km — the activity metric.")


class EmissionResponse(BaseModel):
    """Carbon-footprint calculation result for a single shipment."""

    shipment_id: str | None = None
    transport_type: TransportType
    co2e_kg: float = Field(description="Total emissions in kilograms of CO2 equivalent.")
    co2e_tonnes: float = Field(description="Total emissions in tonnes of CO2 equivalent.")
    calculation: CalculationBreakdown
    methodology_reference: MethodologyReference
    calculated_at: datetime = Field(description="UTC timestamp of the calculation.")


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


# ---------------------------------------------------------------------------
# Batch endpoint models
# ---------------------------------------------------------------------------


MAX_BATCH_ITEMS = 1000


class BatchRequest(BaseModel):
    """Up to ``MAX_BATCH_ITEMS`` shipments calculated in a single API call."""

    items: Annotated[list[EmissionRequest], Field(
        min_length=1,
        max_length=MAX_BATCH_ITEMS,
        description=f"List of shipment requests, 1–{MAX_BATCH_ITEMS}.",
    )]


class BatchItemError(BaseModel):
    type: str = Field(description="Machine-readable error class (e.g. 'IncompatibleFuelError').")
    detail: str


class BatchItem(BaseModel):
    """One row of the batch response — either a successful result or an error."""

    index: int = Field(description="Zero-based index in the original request list.")
    status: Literal["ok", "error"]
    result: EmissionResponse | None = None
    error: BatchItemError | None = None


class BatchAggregate(BaseModel):
    """Totals across the *successful* items only."""

    total_items: int
    successful: int
    failed: int
    total_co2e_kg: float
    total_co2e_tonnes: float
    by_transport_type_kg_co2e: dict[str, float] = Field(
        description="Sum of co2e_kg grouped by transport_type, useful for Scope 3 splits."
    )


class BatchResponse(BaseModel):
    aggregate: BatchAggregate
    items: list[BatchItem]
    methodology_version_used: str | None = Field(
        default=None,
        description="Resolved methodology version actually applied (e.g. '2023').",
    )
