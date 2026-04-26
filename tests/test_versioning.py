"""Methodology versioning tests — pinning, defaulting, and rejecting unknown vintages."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.data.emission_factors import LATEST_VERSION, SUPPORTED_VERSIONS
from app.models.emissions import EmissionRequest, MethodologyVersion, TransportType
from app.services.emission_calculator import EmissionCalculator


@pytest.fixture
def calc() -> EmissionCalculator:
    return EmissionCalculator()


class TestVersionDefaulting:
    def test_no_version_resolves_to_latest(self, calc: EmissionCalculator) -> None:
        req = EmissionRequest(
            weight_kg=1000.0, distance_km=100.0, transport_type=TransportType.TRUCK
        )
        result = calc.calculate(req)
        assert result.methodology_reference.extra_references["version_resolved"] == LATEST_VERSION

    def test_explicit_latest_resolves_to_latest(self, calc: EmissionCalculator) -> None:
        req = EmissionRequest(
            weight_kg=1000.0,
            distance_km=100.0,
            transport_type=TransportType.TRUCK,
            methodology_version=MethodologyVersion.LATEST,
        )
        result = calc.calculate(req)
        assert result.methodology_reference.extra_references["version_resolved"] == LATEST_VERSION


class TestVersionPinning:
    def test_pinning_to_2023_yields_2023_factors(self, calc: EmissionCalculator) -> None:
        req = EmissionRequest(
            weight_kg=1000.0,
            distance_km=100.0,
            transport_type=TransportType.TRUCK,
            methodology_version=MethodologyVersion.DEFRA_2023,
        )
        result = calc.calculate(req)
        assert result.methodology_reference.extra_references["version_resolved"] == "2023"
        # Resolution chain should mention the pinned version explicitly.
        base_step = result.methodology_reference.resolution_chain[0]
        assert "2023" in base_step.description


class TestUnknownVersion:
    def test_unknown_version_string_is_rejected_at_pydantic_layer(self) -> None:
        # MethodologyVersion is an Enum — Pydantic rejects invalid strings before reaching the service.
        with pytest.raises(ValidationError):
            EmissionRequest(
                weight_kg=1000.0,
                distance_km=100.0,
                transport_type=TransportType.TRUCK,
                methodology_version="1999",  # type: ignore[arg-type]
            )


class TestCrossVersionComparison:
    """The reason versioning exists — show that pinning matters."""

    def test_2023_vs_2025_electric_rail_emits_less_in_later_vintage(
        self, calc: EmissionCalculator
    ) -> None:
        # UK grid decarbonised significantly 2023→2025, dragging the electric
        # rail factor down with it. Pinned 2023 reports must NOT shift.
        common = dict(
            weight_kg=10_000.0,
            distance_km=500.0,
            transport_type=TransportType.RAIL,
            sub_mode="electric",
        )
        r23 = calc.calculate(EmissionRequest(**common, methodology_version=MethodologyVersion.DEFRA_2023))
        r25 = calc.calculate(EmissionRequest(**common, methodology_version=MethodologyVersion.DEFRA_2025))

        assert r25.co2e_kg < r23.co2e_kg, (
            "Expected lower emissions under DEFRA 2025 vs 2023 for electric rail "
            "(grid decarbonisation), got 2023={r23.co2e_kg}, 2025={r25.co2e_kg}"
        )
        # And the published_date is also surfaced (via methodology resolution).
        assert "2023" in r23.methodology_reference.version
        assert "2025" in r25.methodology_reference.version

    def test_pinning_2023_is_stable_across_calls(self, calc: EmissionCalculator) -> None:
        # Two identical 2023-pinned requests must produce byte-identical factors,
        # even if 'latest' has moved on.
        req = EmissionRequest(
            weight_kg=1000.0,
            distance_km=100.0,
            transport_type=TransportType.TRUCK,
            methodology_version=MethodologyVersion.DEFRA_2023,
        )
        a = calc.calculate(req)
        b = calc.calculate(req)
        assert a.methodology_reference.factor_kg_co2e_per_tkm == b.methodology_reference.factor_kg_co2e_per_tkm
        assert a.co2e_kg == b.co2e_kg


class TestSupportedVersionsExposed:
    def test_response_lists_all_supported_versions(self, calc: EmissionCalculator) -> None:
        req = EmissionRequest(
            weight_kg=1000.0, distance_km=100.0, transport_type=TransportType.TRUCK
        )
        result = calc.calculate(req)
        assert result.methodology_reference.extra_references["supported_versions"] == list(
            SUPPORTED_VERSIONS
        )
