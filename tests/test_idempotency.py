"""
Idempotency tests — Stripe-style replay, conflict, isolation by key.

These cover both the unit-level cache and the HTTP integration to confirm
the ``Idempotent-Replayed`` header is set correctly and that 409s are
returned on body mismatch.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.idempotency import (
    IdempotencyCache,
    IdempotencyMismatchError,
    hash_payload,
    reset_cache_for_tests,
)
from app.core.config import settings
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
# Cache unit tests
# ---------------------------------------------------------------------------


class TestIdempotencyCacheUnit:
    def test_miss_returns_none(self) -> None:
        cache = IdempotencyCache()
        assert cache.get("key-1", "abc") is None

    def test_set_then_get_returns_cached(self) -> None:
        cache = IdempotencyCache()
        cache.set("key-1", "abc", {"value": 42})
        assert cache.get("key-1", "abc") == {"value": 42}

    def test_mismatched_body_raises(self) -> None:
        cache = IdempotencyCache()
        cache.set("key-1", "abc", {"value": 42})
        with pytest.raises(IdempotencyMismatchError):
            cache.get("key-1", "different-hash")

    def test_lru_eviction_when_over_capacity(self) -> None:
        cache = IdempotencyCache(max_entries=3)
        for i in range(5):
            cache.set(f"k{i}", f"h{i}", i)
        # First two should have been evicted (LRU).
        assert cache.get("k0", "h0") is None
        assert cache.get("k1", "h1") is None
        assert cache.get("k2", "h2") == 2
        assert cache.get("k4", "h4") == 4

    def test_hash_payload_is_deterministic_across_key_order(self) -> None:
        a = hash_payload({"weight_kg": 1, "distance_km": 2})
        b = hash_payload({"distance_km": 2, "weight_kg": 1})
        assert a == b

    def test_hash_payload_changes_on_value_change(self) -> None:
        a = hash_payload({"weight_kg": 1})
        b = hash_payload({"weight_kg": 2})
        assert a != b


# ---------------------------------------------------------------------------
# HTTP integration
# ---------------------------------------------------------------------------


class TestIdempotencyHTTP:
    _PAYLOAD = {"weight_kg": 1000, "distance_km": 100, "transport_type": "truck"}

    def test_first_call_no_replayed_header(self, client: TestClient) -> None:
        resp = client.post(CALC_URL, json=self._PAYLOAD, headers={"Idempotency-Key": "k-001"})
        assert resp.status_code == 200
        assert "Idempotent-Replayed" not in resp.headers

    def test_second_call_same_key_returns_cached_response(self, client: TestClient) -> None:
        first = client.post(CALC_URL, json=self._PAYLOAD, headers={"Idempotency-Key": "k-002"})
        second = client.post(CALC_URL, json=self._PAYLOAD, headers={"Idempotency-Key": "k-002"})

        assert second.status_code == 200
        assert second.headers.get("Idempotent-Replayed") == "true"
        # calculated_at must be byte-identical — the cached response is returned verbatim.
        assert first.json()["calculated_at"] == second.json()["calculated_at"]
        assert first.json() == second.json()

    def test_same_key_different_body_returns_409(self, client: TestClient) -> None:
        client.post(CALC_URL, json=self._PAYLOAD, headers={"Idempotency-Key": "k-003"})
        resp = client.post(
            CALC_URL,
            json={**self._PAYLOAD, "weight_kg": 9999},
            headers={"Idempotency-Key": "k-003"},
        )
        assert resp.status_code == 409
        assert "different request body" in resp.json()["detail"]

    def test_different_keys_isolated(self, client: TestClient) -> None:
        a = client.post(CALC_URL, json=self._PAYLOAD, headers={"Idempotency-Key": "k-A"})
        b = client.post(CALC_URL, json=self._PAYLOAD, headers={"Idempotency-Key": "k-B"})
        assert "Idempotent-Replayed" not in a.headers
        assert "Idempotent-Replayed" not in b.headers
        # Both compute fresh — calculated_at can differ even by microseconds.
        assert a.status_code == 200 and b.status_code == 200

    def test_no_idempotency_key_means_no_caching(self, client: TestClient) -> None:
        a = client.post(CALC_URL, json=self._PAYLOAD)
        b = client.post(CALC_URL, json=self._PAYLOAD)
        assert "Idempotent-Replayed" not in a.headers
        assert "Idempotent-Replayed" not in b.headers
