"""Batch endpoint tests — happy path, per-item failure isolation, idempotency."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.idempotency import reset_cache_for_tests
from app.main import app
from app.models.emissions import MAX_BATCH_ITEMS


BATCH_URL = f"{settings.api_v1_prefix}/emissions/batch"


@pytest.fixture(autouse=True)
def _wipe_cache():
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _item(weight=1000.0, distance=100.0, mode="truck", **kw):
    return {"weight_kg": weight, "distance_km": distance, "transport_type": mode, **kw}


class TestBatchHappyPath:
    def test_three_item_batch_aggregates_correctly(self, client: TestClient) -> None:
        payload = {"items": [
            _item(weight=1000, mode="truck"),
            _item(weight=2000, mode="rail"),
            _item(weight=500, mode="ship", distance=8000),
        ]}
        resp = client.post(BATCH_URL, json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["aggregate"]["total_items"] == 3
        assert body["aggregate"]["successful"] == 3
        assert body["aggregate"]["failed"] == 0
        assert len(body["items"]) == 3
        assert all(it["status"] == "ok" for it in body["items"])

        # Aggregate must equal sum of per-item co2e_kg.
        total_from_items = sum(it["result"]["co2e_kg"] for it in body["items"])
        assert body["aggregate"]["total_co2e_kg"] == pytest.approx(total_from_items, rel=1e-9)

        # By-mode breakdown should cover all three transport modes used.
        by_mode = body["aggregate"]["by_transport_type_kg_co2e"]
        assert set(by_mode.keys()) == {"truck", "rail", "ship"}

    def test_methodology_version_used_is_reported(self, client: TestClient) -> None:
        from app.data.emission_factors import LATEST_VERSION
        payload = {"items": [_item(), _item()]}
        resp = client.post(BATCH_URL, json=payload)
        assert resp.status_code == 200
        # Defaults to current latest vintage when no version is pinned per item.
        assert resp.json()["methodology_version_used"] == LATEST_VERSION


class TestBatchFailureIsolation:
    def test_one_bad_item_does_not_fail_whole_batch(self, client: TestClient) -> None:
        payload = {"items": [
            _item(weight=1000),                                        # ok
            _item(mode="ship", fuel_type="jet_a1"),                    # fail: incompatible fuel
            _item(weight=500, mode="rail"),                            # ok
            _item(mode="rail", fuel_type="electric", region="MARS"),   # fail: unknown region
            _item(weight=2000),                                        # ok
        ]}
        resp = client.post(BATCH_URL, json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["aggregate"]["total_items"] == 5
        assert body["aggregate"]["successful"] == 3
        assert body["aggregate"]["failed"] == 2

        statuses = [it["status"] for it in body["items"]]
        assert statuses == ["ok", "error", "ok", "error", "ok"]

        # Errors carry a structured payload for client-side handling.
        errors = [it["error"] for it in body["items"] if it["status"] == "error"]
        assert errors[0]["type"] == "IncompatibleFuelError"
        assert "not compatible" in errors[0]["detail"]
        assert errors[1]["type"] == "UnknownRegionError"

        # Aggregate co2e covers only the three successful items.
        success_total = sum(
            it["result"]["co2e_kg"] for it in body["items"] if it["status"] == "ok"
        )
        assert body["aggregate"]["total_co2e_kg"] == pytest.approx(success_total, rel=1e-9)

    def test_index_field_preserves_original_position(self, client: TestClient) -> None:
        payload = {"items": [
            _item(mode="ship", fuel_type="jet_a1"),  # 0 — fail
            _item(),                                 # 1 — ok
            _item(mode="ship", fuel_type="jet_a1"),  # 2 — fail
        ]}
        resp = client.post(BATCH_URL, json=payload)
        body = resp.json()
        assert [it["index"] for it in body["items"]] == [0, 1, 2]


class TestBatchValidation:
    def test_empty_items_list_rejected(self, client: TestClient) -> None:
        resp = client.post(BATCH_URL, json={"items": []})
        assert resp.status_code == 422

    def test_oversize_batch_rejected(self, client: TestClient) -> None:
        # MAX_BATCH_ITEMS+1 should fail Pydantic validation before any compute.
        payload = {"items": [_item() for _ in range(MAX_BATCH_ITEMS + 1)]}
        resp = client.post(BATCH_URL, json=payload)
        assert resp.status_code == 422


class TestBatchIdempotency:
    def test_replay_returns_identical_aggregate(self, client: TestClient) -> None:
        payload = {"items": [_item(), _item(weight=2000)]}
        first = client.post(BATCH_URL, json=payload, headers={"Idempotency-Key": "batch-1"})
        second = client.post(BATCH_URL, json=payload, headers={"Idempotency-Key": "batch-1"})

        assert second.headers.get("Idempotent-Replayed") == "true"
        assert first.json() == second.json()

    def test_replay_with_different_payload_returns_409(self, client: TestClient) -> None:
        client.post(BATCH_URL, json={"items": [_item()]}, headers={"Idempotency-Key": "batch-2"})
        resp = client.post(
            BATCH_URL,
            json={"items": [_item(), _item()]},  # different shape
            headers={"Idempotency-Key": "batch-2"},
        )
        assert resp.status_code == 409
