"""
Idempotency support — Stripe-style ``Idempotency-Key`` semantics.

Why
---
RapidAPI bills per call and retries failed requests. Without idempotency,
a flaky network can charge a customer twice and produce two distinct
calculations for what they consider one operation. With idempotency:

  * Same ``Idempotency-Key`` + same request body → identical cached response,
    served with header ``Idempotent-Replayed: true``.
  * Same ``Idempotency-Key`` + *different* body → 409 Conflict (the customer
    re-used a key for a logically different operation; refuse loudly rather
    than silently return stale data).
  * No ``Idempotency-Key`` → no caching, no header, business as usual.

The store is an in-memory thread-safe LRU with TTL. Single-instance only —
for multi-replica deployments swap in a Redis-backed implementation behind
the same ``IdempotencyCache`` interface.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any


class IdempotencyMismatchError(Exception):
    """Raised when an Idempotency-Key is reused with a different request body."""


class IdempotencyCache:
    """In-memory LRU+TTL cache for idempotent request replay."""

    def __init__(self, ttl_seconds: int = 24 * 60 * 60, max_entries: int = 10_000) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._lock = threading.Lock()
        # key -> (expires_at_unix, body_hash, response_payload)
        self._store: OrderedDict[str, tuple[float, str, Any]] = OrderedDict()

    def get(self, key: str, body_hash: str) -> Any | None:
        """
        Return the cached response if present and the body matches; ``None``
        if absent. Raises ``IdempotencyMismatchError`` on body mismatch.
        """
        with self._lock:
            self._evict_expired_locked()
            entry = self._store.get(key)
            if entry is None:
                return None
            _expires, stored_hash, response = entry
            if stored_hash != body_hash:
                raise IdempotencyMismatchError(
                    f"Idempotency-Key '{key}' was previously used with a different request body."
                )
            self._store.move_to_end(key)
            return response

    def set(self, key: str, body_hash: str, response: Any) -> None:
        with self._lock:
            self._store[key] = (time.time() + self._ttl, body_hash, response)
            self._store.move_to_end(key)
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"size": len(self._store), "max": self._max, "ttl_seconds": self._ttl}

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def _evict_expired_locked(self) -> None:
        now = time.time()
        expired = [k for k, (exp, _, _) in self._store.items() if exp < now]
        for k in expired:
            del self._store[k]


def hash_payload(payload: Any) -> str:
    """Deterministic SHA-256 hash of a request payload (dict or Pydantic model)."""
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_singleton: IdempotencyCache | None = None
_singleton_lock = threading.Lock()


def get_cache() -> IdempotencyCache:
    """Module-level singleton — swap to Redis adapter for multi-instance deploys."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = IdempotencyCache()
    return _singleton


def reset_cache_for_tests() -> None:
    """Test helper — wipes the singleton between tests to avoid cross-talk."""
    global _singleton
    with _singleton_lock:
        _singleton = None
