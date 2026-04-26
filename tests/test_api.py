"""End-to-end API tests using FastAPI's TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


CALC_URL = f"{settings.api_v1_prefix}/emissions/calculate"
MODES_URL = f"{settings.api_v1_prefix}/emissions/modes"
FUELS_URL = f"{settings.api_v1_prefix}/reference/fuels"
REGIONS_URL = f"{settings.api_v1_prefix}/reference/regions"


class TestCalculateEndpoint:
    def test_happy_path_truck(self, client: TestClient) -> None:
        # Pin to 2023 for stable assertion across DEFRA updates.
        resp = client.post(
            CALC_URL,
            json={
                "weight_kg": 1000,
                "distance_km": 100,
                "transport_type": "truck",
                "methodology_version": "2023",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["transport_type"] == "truck"
        assert body["co2e_kg"] == pytest.approx(10.749, rel=1e-6)
        assert body["calculation"]["tonne_km"] == pytest.approx(100.0)
        assert body["methodology_reference"]["sub_mode_resolved"] == "default"
        assert "ESRS E1" in body["methodology_reference"]["csrd_alignment"]

    def test_happy_path_with_sub_mode_and_shipment_id(self, client: TestClient) -> None:
        resp = client.post(
            CALC_URL,
            json={
                "weight_kg": 22_000,
                "distance_km": 850,
                "transport_type": "truck",
                "sub_mode": "articulated_average",
                "shipment_id": "SHIP-2026-0001",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["shipment_id"] == "SHIP-2026-0001"
        assert body["methodology_reference"]["sub_mode_resolved"] == "articulated_average"

    def test_negative_weight_rejected_with_422(self, client: TestClient) -> None:
        resp = client.post(
            CALC_URL,
            json={"weight_kg": -10, "distance_km": 100, "transport_type": "truck"},
        )
        assert resp.status_code == 422

    def test_unknown_transport_type_rejected_with_422(self, client: TestClient) -> None:
        resp = client.post(
            CALC_URL,
            json={"weight_kg": 10, "distance_km": 100, "transport_type": "bicycle"},
        )
        assert resp.status_code == 422

    def test_unknown_sub_mode_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            CALC_URL,
            json={
                "weight_kg": 10,
                "distance_km": 100,
                "transport_type": "truck",
                "sub_mode": "rocket_powered",
            },
        )
        assert resp.status_code == 422
        assert "rocket_powered" in resp.json()["detail"]


class TestModesEndpoint:
    def test_lists_all_modes(self, client: TestClient) -> None:
        resp = client.get(MODES_URL)
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"truck", "ship", "air", "rail"}


class TestReferenceEndpoints:
    def test_fuels_lists_all_modes(self, client: TestClient) -> None:
        resp = client.get(FUELS_URL)
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"truck", "ship", "air", "rail"}
        assert "hvo100" in body["truck"]
        assert "saf_neat" in body["air"]
        assert "hfo" in body["ship"]

    def test_regions_includes_eu_and_us(self, client: TestClient) -> None:
        resp = client.get(REGIONS_URL)
        assert resp.status_code == 200
        body = resp.json()
        assert {"GB", "FR", "DE", "PL", "US", "EU27", "WORLD"}.issubset(body.keys())
        # France < Poland — sanity check the data, not just the endpoint
        assert body["FR"] < body["PL"]


class TestRegionalAndFuelHTTP:
    def test_hvo_truck_via_http(self, client: TestClient) -> None:
        resp = client.post(
            CALC_URL,
            json={
                "weight_kg": 10000,
                "distance_km": 500,
                "transport_type": "truck",
                "fuel_type": "hvo100",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ref = body["methodology_reference"]
        assert ref["fuel_resolved"] == "hvo100"
        steps = [s["step"] for s in ref["resolution_chain"]]
        assert "fuel_substitution" in steps

    def test_electric_rail_france_via_http(self, client: TestClient) -> None:
        resp = client.post(
            CALC_URL,
            json={
                "weight_kg": 25000,
                "distance_km": 600,
                "transport_type": "rail",
                "fuel_type": "electric",
                "region": "FR",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ref = body["methodology_reference"]
        assert ref["fuel_resolved"] == "electric"
        assert ref["region_resolved"] == "FR"

    def test_incompatible_fuel_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            CALC_URL,
            json={
                "weight_kg": 1000,
                "distance_km": 100,
                "transport_type": "ship",
                "fuel_type": "jet_a1",
            },
        )
        assert resp.status_code == 422
        assert "not compatible" in resp.json()["detail"]

    def test_unknown_region_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            CALC_URL,
            json={
                "weight_kg": 1000,
                "distance_km": 100,
                "transport_type": "rail",
                "fuel_type": "electric",
                "region": "ATLANTIS",
            },
        )
        assert resp.status_code == 422


class TestSystem:
    def test_health(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_openapi_schema_is_generated(self, client: TestClient) -> None:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert schema["info"]["title"] == settings.app_name
        assert f"{settings.api_v1_prefix}/emissions/calculate" in schema["paths"]

    def test_swagger_docs_available(self, client: TestClient) -> None:
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "swagger" in resp.text.lower()
