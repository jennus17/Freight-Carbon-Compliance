"""
Core carbon-footprint calculation engine.

Resolution order
----------------
    1. Base DEFRA factor                EMISSION_FACTORS[mode][sub_mode]
    2. Fuel substitution (if applicable) factor *= fuel_ratio   (GLEC v3.0 §6.3)
       — OR — switch to electric base + regional grid adjust    (ESRS E1 §49)
    3. Apply to activity metric         co2e_kg = (kg/1000) × km × factor

Every step is recorded in ``resolution_chain`` so that the final factor can
be reproduced by an auditor with nothing more than the response payload and
the published source documents.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.data.emission_factors import (
    EMISSION_FACTORS,
    METHODOLOGY,
    SUPPORTED_VERSIONS,
    get_factor,
    get_methodology,
    resolve_version,
)
from app.data.fuel_factors import (
    COMPATIBLE_FUELS_BY_MODE,
    DEFAULT_FUEL_BY_MODE,
    FUEL_FACTORS,
    FUEL_METHODOLOGY,
    fuel_substitution_ratio,
)
from app.data.grid_factors import GRID_FACTORS, GRID_METHODOLOGY, get_grid_factor
from app.models.emissions import (
    CalculationBreakdown,
    EmissionRequest,
    EmissionResponse,
    FuelType,
    MethodologyReference,
    ResolutionStep,
    TransportType,
)


_BASELINE_REGION = "GB"   # DEFRA factors embed the UK grid; adjustments are relative to this.
_ROUND_KG = 6
_ROUND_TONNES = 9
_ROUND_FACTOR = 7


class IncompatibleFuelError(Exception):
    """Raised when a fuel/transport_type combination is physically invalid."""


class UnknownRegionError(Exception):
    """Raised when an unknown region code is supplied."""


class EmissionCalculator:
    """Stateless service that turns a validated request into an audit-grade response."""

    @staticmethod
    def calculate(request: EmissionRequest) -> EmissionResponse:
        version_input = (
            request.methodology_version.value if request.methodology_version else None
        )
        resolved_version = resolve_version(version_input)
        methodology = get_methodology(resolved_version)

        factor, sub_mode_resolved, fuel_resolved, region_resolved, chain = (
            _resolve_factor(
                transport_type=request.transport_type.value,
                sub_mode=request.sub_mode,
                fuel_type=request.fuel_type.value if request.fuel_type else None,
                region=request.region,
                version=resolved_version,
            )
        )

        mass_tonnes = request.weight_kg / 1000.0
        tonne_km = mass_tonnes * request.distance_km
        co2e_kg = tonne_km * factor

        return EmissionResponse(
            shipment_id=request.shipment_id,
            transport_type=request.transport_type,
            co2e_kg=round(co2e_kg, _ROUND_KG),
            co2e_tonnes=round(co2e_kg / 1000.0, _ROUND_TONNES),
            calculation=CalculationBreakdown(
                mass_tonnes=round(mass_tonnes, 9),
                distance_km=request.distance_km,
                tonne_km=round(tonne_km, 9),
            ),
            methodology_reference=MethodologyReference(
                **methodology,
                factor_kg_co2e_per_tkm=round(factor, _ROUND_FACTOR),
                sub_mode_resolved=sub_mode_resolved,
                fuel_resolved=fuel_resolved,
                region_resolved=region_resolved,
                resolution_chain=chain,
                extra_references={
                    "fuel_substitution": FUEL_METHODOLOGY,
                    "grid_factor": GRID_METHODOLOGY,
                    "version_resolved": resolved_version,
                    "supported_versions": list(SUPPORTED_VERSIONS),
                },
            ),
            calculated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def list_supported_modes() -> dict[str, list[str]]:
        return {
            mode: sorted(k for k in factors if k != "default")
            for mode, factors in EMISSION_FACTORS.items()
            if mode in {t.value for t in TransportType}
        }

    @staticmethod
    def list_supported_fuels() -> dict[str, list[str]]:
        return {mode: sorted(fuels) for mode, fuels in COMPATIBLE_FUELS_BY_MODE.items()}

    @staticmethod
    def list_supported_regions() -> dict[str, float]:
        return dict(sorted(GRID_FACTORS.items()))


# ---------------------------------------------------------------------------
# Internal: factor resolution chain
# ---------------------------------------------------------------------------


def _resolve_factor(
    transport_type: str,
    sub_mode: str | None,
    fuel_type: str | None,
    region: str | None,
    version: str,
) -> tuple[float, str, str, str | None, list[ResolutionStep]]:
    """
    Returns ``(final_factor, sub_mode_resolved, fuel_resolved, region_resolved, chain)``.

    Raises ``KeyError`` for unknown sub_modes/regions, ``IncompatibleFuelError``
    for invalid fuel/mode combos, ``UnknownRegionError`` for unknown regions.
    """
    chain: list[ResolutionStep] = []
    methodology = get_methodology(version)

    # ── Step 1: base DEFRA activity factor ────────────────────────────────
    base_factor, sub_mode_resolved = get_factor(transport_type, sub_mode, version=version)
    chain.append(ResolutionStep(
        step="base_factor",
        description=(
            f"DEFRA {version} freight factor for {transport_type}/{sub_mode_resolved}"
        ),
        value_kg_co2e_per_tkm=round(base_factor, _ROUND_FACTOR),
        source=methodology["source"],
    ))
    final_factor = base_factor

    # ── Step 2: determine the effective fuel ──────────────────────────────
    fuel_resolved = _determine_effective_fuel(
        transport_type=transport_type,
        sub_mode_resolved=sub_mode_resolved,
        fuel_type=fuel_type,
    )

    # ── Step 3a: electric pathway (regional grid) ─────────────────────────
    region_resolved: str | None = None
    if fuel_resolved == "electric":
        if transport_type != "rail":
            raise IncompatibleFuelError(
                f"Electric pathway is only modelled for rail in this version "
                f"(received transport_type='{transport_type}'). EV-truck and "
                f"shore-power-ship pathways are on the roadmap."
            )

        # Switch to the electric rail base factor if not already there.
        if sub_mode_resolved != "electric":
            electric_base, _ = get_factor("rail", "electric", version=version)
            chain.append(ResolutionStep(
                step="switch_to_electric_base",
                description=(
                    f"Replaced base factor with DEFRA rail/electric "
                    f"({electric_base:.5f}) — fuel_type='electric' overrides sub_mode."
                ),
                value_kg_co2e_per_tkm=round(electric_base, _ROUND_FACTOR),
                source=methodology["source"],
            ))
            final_factor = electric_base
            sub_mode_resolved = "electric"

        # Regional grid adjustment (relative to UK baseline).
        if region:
            if region not in GRID_FACTORS:
                raise UnknownRegionError(
                    f"Unknown region '{region}'. See /api/v1/reference/regions."
                )
            region_resolved = region
            target_grid = get_grid_factor(region)
            baseline_grid = get_grid_factor(_BASELINE_REGION)
            ratio = target_grid / baseline_grid
            adjusted = final_factor * ratio
            chain.append(ResolutionStep(
                step="regional_grid_adjustment",
                description=(
                    f"Adjusted from {_BASELINE_REGION} grid ({baseline_grid:.5f} kgCO2e/kWh) "
                    f"to {region} grid ({target_grid:.5f} kgCO2e/kWh)."
                ),
                ratio=round(ratio, 5),
                value_kg_co2e_per_tkm=round(adjusted, _ROUND_FACTOR),
                source=GRID_METHODOLOGY["source"],
            ))
            final_factor = adjusted

    # ── Step 3b: fuel-substitution pathway (non-electric) ─────────────────
    else:
        default_fuel = DEFAULT_FUEL_BY_MODE[transport_type]
        if fuel_resolved != default_fuel:
            try:
                ratio = fuel_substitution_ratio(transport_type, fuel_resolved)
            except ValueError as exc:
                raise IncompatibleFuelError(str(exc)) from exc
            adjusted = base_factor * ratio
            target_meta = FUEL_FACTORS[fuel_resolved]
            chain.append(ResolutionStep(
                step="fuel_substitution",
                description=(
                    f"Substituted {default_fuel}→{fuel_resolved} "
                    f"(WTW intensity ratio {ratio:.5f}, GLEC v3.0 §6.3)."
                ),
                ratio=round(ratio, 5),
                value_kg_co2e_per_tkm=round(adjusted, _ROUND_FACTOR),
                source=target_meta["source"],
            ))
            final_factor = adjusted

        # If a region was supplied but not used (non-electric path), record that
        # we ignored it so the auditor isn't confused.
        if region:
            chain.append(ResolutionStep(
                step="region_ignored",
                description=(
                    f"region='{region}' was supplied but ignored — "
                    f"regional grid factors only apply when fuel_type='electric'."
                ),
            ))

    return final_factor, sub_mode_resolved, fuel_resolved, region_resolved, chain


def _determine_effective_fuel(
    transport_type: str,
    sub_mode_resolved: str,
    fuel_type: str | None,
) -> str:
    """
    Pick the fuel id that the calculation will actually use.

    Precedence:
      1. Explicit ``fuel_type`` (validated for compatibility).
      2. Implicit electric for rail when sub_mode_resolved == 'electric'.
      3. Mode default (DEFAULT_FUEL_BY_MODE).
    """
    if fuel_type is not None:
        if fuel_type not in COMPATIBLE_FUELS_BY_MODE[transport_type]:
            raise IncompatibleFuelError(
                f"fuel_type '{fuel_type}' is not compatible with transport_type "
                f"'{transport_type}'. Compatible: "
                f"{sorted(COMPATIBLE_FUELS_BY_MODE[transport_type])}."
            )
        return fuel_type

    if transport_type == "rail" and sub_mode_resolved == "electric":
        return "electric"

    return DEFAULT_FUEL_BY_MODE[transport_type]
