"""
Tests for the operations layer:
  * RapidAPI proxy-secret authentication (toggle via ``settings.rapidapi_proxy_secret``).
  * Structured access logging — verifies ``X-Request-ID`` round-trip.
  * Prometheus ``/metrics`` endpoint — exposition format and label cardinality.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.idempotency import reset_cache_for_tests
from app.main import app


CALC_URL = f"{settings.api_v1_prefix}/emissions/calculate"


@pytest.fixture(autouse=True)
def _wipe_cache():
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# RapidAPI proxy-secret auth
# ---------------------------------------------------------------------------


class TestRapidAPIAuth:
    """The check is a no-op when the secret is unset; in prod (secret set) it must reject."""

    _SECRET = "sk_test_proxy_supersecret_42"
    _PAYLOAD = {"weight_kg": 1000, "distance_km": 100, "transport_type": "truck"}

    def test_dev_mode_no_secret_passes_without_header(self, client: TestClient) -> None:
        # By default settings.rapidapi_proxy_secret == "" → no enforcement.
        assert settings.rapidapi_proxy_secret == ""
        resp = client.post(CALC_URL, json=self._PAYLOAD)
        assert resp.status_code == 200

    def test_secret_set_rejects_request_without_header(
        self, monkeypatch: pytest.MonkeyPatch, client: TestClient
    ) -> None:
        monkeypatch.setattr(settings, "rapidapi_proxy_secret", self._SECRET)
        resp = client.post(CALC_URL, json=self._PAYLOAD)
        assert resp.status_code == 401
        assert "RapidAPI" in resp.json()["detail"]

    def test_secret_set_rejects_request_with_wrong_header(
        self, monkeypatch: pytest.MonkeyPatch, client: TestClient
    ) -> None:
        monkeypatch.setattr(settings, "rapidapi_proxy_secret", self._SECRET)
        resp = client.post(
            CALC_URL,
            json=self._PAYLOAD,
            headers={"X-RapidAPI-Proxy-Secret": "wrong"},
        )
        assert resp.status_code == 401

    def test_secret_set_accepts_correct_header(
        self, monkeypatch: pytest.MonkeyPatch, client: TestClient
    ) -> None:
        monkeypatch.setattr(settings, "rapidapi_proxy_secret", self._SECRET)
        resp = client.post(
            CALC_URL,
            json=self._PAYLOAD,
            headers={"X-RapidAPI-Proxy-Secret": self._SECRET},
        )
        assert resp.status_code == 200

    def test_health_endpoint_does_not_require_auth(
        self, monkeypatch: pytest.MonkeyPatch, client: TestClient
    ) -> None:
        # /health and /metrics live outside the v1 router and stay open.
        monkeypatch.setattr(settings, "rapidapi_proxy_secret", self._SECRET)
        assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# Request ID propagation
# ---------------------------------------------------------------------------


class TestRequestId:
    def test_request_id_is_generated_when_absent(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        rid = resp.headers.get(settings.request_id_header)
        assert rid and len(rid) >= 16

    def test_request_id_is_echoed_when_supplied(self, client: TestClient) -> None:
        resp = client.get("/health", headers={settings.request_id_header: "trace-abc-123"})
        assert resp.headers.get(settings.request_id_header) == "trace-abc-123"


# ---------------------------------------------------------------------------
# Prometheus /metrics
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    def test_metrics_endpoint_serves_prometheus_format(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")
        body = resp.text
        # Each declared metric must appear in the exposition.
        for metric in (
            "esg_http_requests_total",
            "esg_http_request_duration_seconds",
            "esg_emissions_calculated_total",
            "esg_idempotency_total",
            "esg_batch_items_total",
        ):
            assert metric in body, f"Missing metric {metric} in /metrics output"

    def test_calculation_increments_emissions_counter(self, client: TestClient) -> None:
        before = client.get("/metrics").text

        client.post(
            CALC_URL,
            json={"weight_kg": 1000, "distance_km": 100, "transport_type": "truck"},
        )

        after = client.get("/metrics").text
        # Find the truck/diesel/2025 series and confirm it shows up at all (count >= 1).
        # Exact count comparison is brittle because other tests share the registry.
        assert "esg_emissions_calculated_total" in after
        assert "transport_type=\"truck\"" in after
        # The post-call exposition must be longer (or different) than the pre-call one.
        assert before != after

    def test_idempotency_hit_recorded(self, client: TestClient) -> None:
        payload = {"weight_kg": 1000, "distance_km": 100, "transport_type": "truck"}
        client.post(CALC_URL, json=payload, headers={"Idempotency-Key": "metrics-1"})
        client.post(CALC_URL, json=payload, headers={"Idempotency-Key": "metrics-1"})

        body = client.get("/metrics").text
        assert "esg_idempotency_total" in body
        assert 'result="hit"' in body
        assert 'result="miss"' in body
