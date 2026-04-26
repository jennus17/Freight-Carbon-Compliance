"""
Tests for the regional grid + alternative-fuel resolution chain.

These cover the second-tier complexity: same shipment, different fuel or
different country grid → very different emissions, with full audit trail.
"""

from __future__ import annotations

import pytest

from app.data.fuel_factors import FUEL_FACTORS
from app.data.grid_factors import GRID_FACTORS
from app.models.emissions import EmissionRequest, FuelType, TransportType
from app.services.emission_calculator import (
    EmissionCalculator,
    IncompatibleFuelError,
    UnknownRegionError,
)


@pytest.fixture
def calc() -> EmissionCalculator:
    return EmissionCalculator()


# ---------------------------------------------------------------------------
# Backwards compatibility: omitting region + fuel_type must reproduce v0.1
# ---------------------------------------------------------------------------


class TestBackwardsCompatibility:
    def test_no_fuel_no_region_matches_legacy_factor(self, calc: EmissionCalculator) -> None:
        # Pin to 2023 so this regression test stays anchored to the v0.1 behaviour.
        from app.models.emissions import MethodologyVersion
        req = EmissionRequest(
            weight_kg=1000.0,
            distance_km=100.0,
            transport_type=TransportType.TRUCK,
            methodology_version=MethodologyVersion.DEFRA_2023,
        )
        result = calc.calculate(req)
        assert result.co2e_kg == pytest.approx(10.749, rel=1e-6)
        assert result.methodology_reference.fuel_resolved == "diesel"
        assert result.methodology_reference.region_resolved is None
        # Only the base step in the chain — no adjustments.
        assert len(result.methodology_reference.resolution_chain) == 1
        assert result.methodology_reference.resolution_chain[0].step == "base_factor"


# ---------------------------------------------------------------------------
# Fuel substitution — non-electric pathways
# ---------------------------------------------------------------------------


class TestFuelSubstitution:
    def test_hvo100_truck_reduces_emissions_by_substitution_ratio(
        self, calc: EmissionCalculator
    ) -> None:
        req_diesel = EmissionRequest(
            weight_kg=10_000.0, distance_km=500.0, transport_type=TransportType.TRUCK
        )
        req_hvo = EmissionRequest(
            weight_kg=10_000.0,
            distance_km=500.0,
            transport_type=TransportType.TRUCK,
            fuel_type=FuelType.HVO100,
        )
        diesel = calc.calculate(req_diesel)
        hvo = calc.calculate(req_hvo)

        expected_ratio = (
            FUEL_FACTORS["hvo100"]["wtw_kg_co2e_per_mj"]
            / FUEL_FACTORS["diesel"]["wtw_kg_co2e_per_mj"]
        )
        assert hvo.co2e_kg == pytest.approx(diesel.co2e_kg * expected_ratio, rel=1e-6)
        assert hvo.co2e_kg < diesel.co2e_kg * 0.10  # >90% reduction expected
        assert hvo.methodology_reference.fuel_resolved == "hvo100"

    def test_saf_blend_30_air_reduces_by_published_ratio(
        self, calc: EmissionCalculator
    ) -> None:
        req_jet = EmissionRequest(
            weight_kg=500.0,
            distance_km=8000.0,
            transport_type=TransportType.AIR,
            sub_mode="long_haul",
        )
        req_saf = EmissionRequest(
            weight_kg=500.0,
            distance_km=8000.0,
            transport_type=TransportType.AIR,
            sub_mode="long_haul",
            fuel_type=FuelType.SAF_BLEND_30,
        )
        jet = calc.calculate(req_jet)
        saf = calc.calculate(req_saf)
        # 30% SAF blend should give ~26-30% reduction
        reduction = 1 - (saf.co2e_kg / jet.co2e_kg)
        assert 0.20 < reduction < 0.40, f"Unexpected SAF reduction: {reduction:.1%}"

    def test_fuel_substitution_chain_records_ratio(self, calc: EmissionCalculator) -> None:
        req = EmissionRequest(
            weight_kg=1000.0,
            distance_km=100.0,
            transport_type=TransportType.SHIP,
            fuel_type=FuelType.METHANOL_GREEN,
        )
        result = calc.calculate(req)
        steps = {s.step: s for s in result.methodology_reference.resolution_chain}
        assert "base_factor" in steps
        assert "fuel_substitution" in steps
        sub = steps["fuel_substitution"]
        assert sub.ratio is not None
        # Green methanol vs HFO is dramatic — well below 0.2
        assert sub.ratio < 0.20

    def test_fuel_matching_default_is_a_no_op(self, calc: EmissionCalculator) -> None:
        req_default = EmissionRequest(
            weight_kg=1000.0, distance_km=100.0, transport_type=TransportType.TRUCK
        )
        req_explicit = EmissionRequest(
            weight_kg=1000.0,
            distance_km=100.0,
            transport_type=TransportType.TRUCK,
            fuel_type=FuelType.DIESEL,
        )
        a = calc.calculate(req_default).co2e_kg
        b = calc.calculate(req_explicit).co2e_kg
        assert a == b
        # No fuel_substitution step when target == default
        chain_steps = [s.step for s in calc.calculate(req_explicit).methodology_reference.resolution_chain]
        assert "fuel_substitution" not in chain_steps


# ---------------------------------------------------------------------------
# Compatibility matrix — physical impossibility must be a 422-equivalent
# ---------------------------------------------------------------------------


class TestFuelCompatibility:
    def test_jet_fuel_on_ship_is_rejected(self, calc: EmissionCalculator) -> None:
        req = EmissionRequest(
            weight_kg=1000.0,
            distance_km=100.0,
            transport_type=TransportType.SHIP,
            fuel_type=FuelType.JET_A1,
        )
        with pytest.raises(IncompatibleFuelError, match="not compatible"):
            calc.calculate(req)

    def test_hfo_on_truck_is_rejected(self, calc: EmissionCalculator) -> None:
        req = EmissionRequest(
            weight_kg=1000.0,
            distance_km=100.0,
            transport_type=TransportType.TRUCK,
            fuel_type=FuelType.HFO,
        )
        with pytest.raises(IncompatibleFuelError):
            calc.calculate(req)

    def test_saf_on_truck_is_rejected(self, calc: EmissionCalculator) -> None:
        req = EmissionRequest(
            weight_kg=1000.0,
            distance_km=100.0,
            transport_type=TransportType.TRUCK,
            fuel_type=FuelType.SAF_NEAT,
        )
        with pytest.raises(IncompatibleFuelError):
            calc.calculate(req)


# ---------------------------------------------------------------------------
# Electric pathway — regional grid factors
# ---------------------------------------------------------------------------


class TestElectricGridPathway:
    def test_french_grid_emits_far_less_than_polish_grid(
        self, calc: EmissionCalculator
    ) -> None:
        common = dict(
            weight_kg=25_000.0,
            distance_km=600.0,
            transport_type=TransportType.RAIL,
            fuel_type=FuelType.ELECTRIC,
        )
        fr = calc.calculate(EmissionRequest(**common, region="FR"))
        pl = calc.calculate(EmissionRequest(**common, region="PL"))

        # France grid is ~12× cleaner than Poland — emissions should track that.
        ratio = fr.co2e_kg / pl.co2e_kg
        published_ratio = GRID_FACTORS["FR"] / GRID_FACTORS["PL"]
        assert ratio == pytest.approx(published_ratio, rel=1e-6)
        assert fr.methodology_reference.region_resolved == "FR"
        assert pl.methodology_reference.region_resolved == "PL"

    def test_gb_grid_yields_baseline_defra_factor(self, calc: EmissionCalculator) -> None:
        # When region is GB (or omitted) on electric rail, no grid adjustment is applied.
        # Pin to 2023 because the DEFRA rail/electric factor evolves yearly.
        from app.models.emissions import MethodologyVersion
        req = EmissionRequest(
            weight_kg=10_000.0,
            distance_km=500.0,
            transport_type=TransportType.RAIL,
            sub_mode="electric",
            region="GB",
            methodology_version=MethodologyVersion.DEFRA_2023,
        )
        result = calc.calculate(req)
        # DEFRA 2023 rail/electric = 0.02410
        assert result.methodology_reference.factor_kg_co2e_per_tkm == pytest.approx(
            0.02410, rel=1e-6
        )

    def test_fuel_type_electric_overrides_sub_mode(self, calc: EmissionCalculator) -> None:
        # User picks rail/diesel sub_mode but says fuel_type=electric — fuel_type wins.
        req = EmissionRequest(
            weight_kg=10_000.0,
            distance_km=500.0,
            transport_type=TransportType.RAIL,
            sub_mode="diesel",
            fuel_type=FuelType.ELECTRIC,
            region="SE",
        )
        result = calc.calculate(req)
        assert result.methodology_reference.fuel_resolved == "electric"
        assert result.methodology_reference.sub_mode_resolved == "electric"
        steps = [s.step for s in result.methodology_reference.resolution_chain]
        assert "switch_to_electric_base" in steps
        assert "regional_grid_adjustment" in steps

    def test_electric_truck_is_rejected_until_modelled(self, calc: EmissionCalculator) -> None:
        # EV trucks are not yet supported — explicit failure beats silent wrong answer.
        # The fuel_type=electric is rejected at compatibility check first.
        req = EmissionRequest(
            weight_kg=1000.0,
            distance_km=100.0,
            transport_type=TransportType.TRUCK,
            fuel_type=FuelType.ELECTRIC,
        )
        with pytest.raises(IncompatibleFuelError):
            calc.calculate(req)

    def test_unknown_region_is_rejected(self, calc: EmissionCalculator) -> None:
        req = EmissionRequest(
            weight_kg=10_000.0,
            distance_km=500.0,
            transport_type=TransportType.RAIL,
            fuel_type=FuelType.ELECTRIC,
            region="ATLANTIS",
        )
        with pytest.raises((UnknownRegionError, KeyError)):
            calc.calculate(req)

    def test_region_without_electric_fuel_is_recorded_as_ignored(
        self, calc: EmissionCalculator
    ) -> None:
        req = EmissionRequest(
            weight_kg=1000.0,
            distance_km=100.0,
            transport_type=TransportType.TRUCK,
            region="FR",   # supplied but irrelevant — diesel pathway
        )
        result = calc.calculate(req)
        steps = {s.step for s in result.methodology_reference.resolution_chain}
        assert "region_ignored" in steps
        assert result.methodology_reference.region_resolved is None


# ---------------------------------------------------------------------------
# Resolution chain shape
# ---------------------------------------------------------------------------


class TestResolutionChain:
    def test_chain_records_each_step_with_running_factor(
        self, calc: EmissionCalculator
    ) -> None:
        req = EmissionRequest(
            weight_kg=20_000.0,
            distance_km=1500.0,
            transport_type=TransportType.RAIL,
            fuel_type=FuelType.ELECTRIC,
            region="DE",
        )
        result = calc.calculate(req)
        chain = result.methodology_reference.resolution_chain
        steps = [s.step for s in chain]
        assert steps == ["base_factor", "switch_to_electric_base", "regional_grid_adjustment"]
        # Final factor in chain matches the headline factor.
        assert chain[-1].value_kg_co2e_per_tkm == pytest.approx(
            result.methodology_reference.factor_kg_co2e_per_tkm
        )
