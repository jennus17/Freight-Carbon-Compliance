"""Pydantic schema validation tests — guards against bad inputs at the boundary."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.emissions import EmissionRequest, TransportType


class TestRequestValidation:
    @pytest.mark.parametrize("bad_weight", [0, -1, -100.5])
    def test_rejects_non_positive_weight(self, bad_weight: float) -> None:
        with pytest.raises(ValidationError):
            EmissionRequest(
                weight_kg=bad_weight, distance_km=10.0, transport_type=TransportType.TRUCK
            )

    @pytest.mark.parametrize("bad_distance", [0, -42.0])
    def test_rejects_non_positive_distance(self, bad_distance: float) -> None:
        with pytest.raises(ValidationError):
            EmissionRequest(
                weight_kg=10.0, distance_km=bad_distance, transport_type=TransportType.TRUCK
            )

    def test_rejects_unknown_transport_type(self) -> None:
        with pytest.raises(ValidationError):
            EmissionRequest(weight_kg=10.0, distance_km=10.0, transport_type="bicycle")

    def test_weight_above_megatonne_cap_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EmissionRequest(
                weight_kg=2_000_000_000,  # 2 megatonnes — clearly bogus
                distance_km=10.0,
                transport_type=TransportType.SHIP,
            )

    def test_distance_above_earth_circumference_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EmissionRequest(
                weight_kg=10.0,
                distance_km=100_000.0,  # 2.5× Earth circumference
                transport_type=TransportType.AIR,
            )

    def test_sub_mode_is_normalised_to_lowercase_and_stripped(self) -> None:
        req = EmissionRequest(
            weight_kg=10.0,
            distance_km=10.0,
            transport_type=TransportType.TRUCK,
            sub_mode="  Articulated_Average  ",
        )
        assert req.sub_mode == "articulated_average"

    def test_blank_sub_mode_becomes_none(self) -> None:
        req = EmissionRequest(
            weight_kg=10.0,
            distance_km=10.0,
            transport_type=TransportType.TRUCK,
            sub_mode="   ",
        )
        assert req.sub_mode is None

    def test_missing_required_fields(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            EmissionRequest(weight_kg=10.0)  # type: ignore[call-arg]
        errors = {e["loc"][0] for e in exc_info.value.errors()}
        assert "distance_km" in errors
        assert "transport_type" in errors
