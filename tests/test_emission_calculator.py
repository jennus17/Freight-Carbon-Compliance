"""Unit tests for the calculation service — verifies the core formula and DEFRA factors."""

from __future__ import annotations

import pytest

from app.data.emission_factors import EMISSION_FACTORS
from app.models.emissions import EmissionRequest, TransportType
from app.services.emission_calculator import EmissionCalculator


@pytest.fixture
def calculator() -> EmissionCalculator:
    return EmissionCalculator()


class TestCoreFormula:
    """co2e_kg = (weight_kg / 1000) * distance_km * factor"""

    def test_truck_default_factor_matches_defra(self, calculator: EmissionCalculator) -> None:
        # Pinned to 2023 vintage so the assertion is stable across DEFRA updates.
        from app.models.emissions import MethodologyVersion
        req = EmissionRequest(
            weight_kg=1000.0,
            distance_km=100.0,
            transport_type=TransportType.TRUCK,
            methodology_version=MethodologyVersion.DEFRA_2023,
        )
        result = calculator.calculate(req)

        # DEFRA 2023 truck/default = 0.10749 kgCO2e/tkm  →  1 t × 100 km × 0.10749 = 10.749 kg
        assert result.co2e_kg == pytest.approx(10.749, rel=1e-9)
        assert result.calculation.mass_tonnes == pytest.approx(1.0)
        assert result.calculation.tonne_km == pytest.approx(100.0)

    def test_ship_factor_is_lowest_per_tkm(self, calculator: EmissionCalculator) -> None:
        # Sanity check on physics: per tkm, ship < rail < truck < air
        weight, distance = 10_000.0, 1000.0  # 10 t × 1000 km
        modes = [TransportType.SHIP, TransportType.RAIL, TransportType.TRUCK, TransportType.AIR]
        results = [
            calculator.calculate(
                EmissionRequest(weight_kg=weight, distance_km=distance, transport_type=m)
            ).co2e_kg
            for m in modes
        ]
        assert results == sorted(results), (
            f"Per-tkm ranking violated physics: ship < rail < truck < air, got {results}"
        )

    def test_co2e_tonnes_equals_kg_div_1000(self, calculator: EmissionCalculator) -> None:
        req = EmissionRequest(
            weight_kg=5000.0, distance_km=2000.0, transport_type=TransportType.RAIL
        )
        result = calculator.calculate(req)
        assert result.co2e_tonnes == pytest.approx(result.co2e_kg / 1000.0)

    @pytest.mark.parametrize(
        "transport_type,sub_mode,weight_kg,distance_km",
        [
            (TransportType.TRUCK, None, 1500.0, 420.0),
            (TransportType.TRUCK, "articulated_average", 22_000.0, 850.0),
            (TransportType.RAIL, "electric", 25_000.0, 600.0),
            (TransportType.SHIP, "container", 50_000.0, 8_000.0),
            (TransportType.AIR, "long_haul", 800.0, 9_500.0),
        ],
    )
    def test_factor_resolution_uses_sub_mode(
        self,
        calculator: EmissionCalculator,
        transport_type: TransportType,
        sub_mode: str | None,
        weight_kg: float,
        distance_km: float,
    ) -> None:
        req = EmissionRequest(
            weight_kg=weight_kg,
            distance_km=distance_km,
            transport_type=transport_type,
            sub_mode=sub_mode,
        )
        result = calculator.calculate(req)

        expected_key = sub_mode or "default"
        expected_factor = EMISSION_FACTORS[transport_type.value][expected_key]
        assert result.methodology_reference.factor_kg_co2e_per_tkm == expected_factor
        assert result.methodology_reference.sub_mode_resolved == expected_key

        expected_co2e = (weight_kg / 1000.0) * distance_km * expected_factor
        assert result.co2e_kg == pytest.approx(expected_co2e, rel=1e-9)


class TestMethodologyReference:
    def test_includes_csrd_alignment(self, calculator: EmissionCalculator) -> None:
        req = EmissionRequest(
            weight_kg=100.0, distance_km=10.0, transport_type=TransportType.TRUCK
        )
        result = calculator.calculate(req)
        ref = result.methodology_reference
        assert "ESRS E1" in ref.csrd_alignment
        assert "DEFRA" in ref.source
        assert ref.unit == "kgCO2e per tonne-kilometre"

    def test_calculated_at_is_utc(self, calculator: EmissionCalculator) -> None:
        req = EmissionRequest(
            weight_kg=100.0, distance_km=10.0, transport_type=TransportType.TRUCK
        )
        result = calculator.calculate(req)
        assert result.calculated_at.tzinfo is not None
        assert result.calculated_at.utcoffset().total_seconds() == 0


class TestUnknownSubMode:
    def test_unknown_sub_mode_raises(self, calculator: EmissionCalculator) -> None:
        req = EmissionRequest(
            weight_kg=100.0,
            distance_km=10.0,
            transport_type=TransportType.TRUCK,
            sub_mode="rocket_powered",
        )
        with pytest.raises(KeyError, match="Unknown sub_mode"):
            calculator.calculate(req)


class TestSupportedModes:
    def test_lists_all_four_top_level_modes(self, calculator: EmissionCalculator) -> None:
        modes = calculator.list_supported_modes()
        assert set(modes.keys()) == {"truck", "ship", "air", "rail"}
        for sub_modes in modes.values():
            assert "default" not in sub_modes  # default is implicit, not a user-facing option
            assert len(sub_modes) >= 1
