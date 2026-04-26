"""
Prometheus metrics — exposed at ``/metrics`` for scraping.

Cardinality discipline
----------------------
Every label here is a **bounded enum** (transport mode, fuel type, status
class, ok/error). Never label by user-controlled free-text such as
``shipment_id`` or ``region``: that explodes the time-series cardinality
and crashes the scraper.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST


# Dedicated registry so test reset doesn't clobber the global default registry.
REGISTRY = CollectorRegistry()


# ── HTTP-level metrics (populated by middleware) ──────────────────────────
HTTP_REQUESTS_TOTAL = Counter(
    "esg_http_requests_total",
    "Total HTTP requests served, labelled by method/path/status_class.",
    labelnames=("method", "path", "status_class"),
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "esg_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)


# ── Domain metrics (populated by controller) ──────────────────────────────
EMISSIONS_CALCULATED_TOTAL = Counter(
    "esg_emissions_calculated_total",
    "Successful single-shipment emission calculations.",
    labelnames=("transport_type", "fuel_resolved", "methodology_version"),
    registry=REGISTRY,
)

IDEMPOTENCY_TOTAL = Counter(
    "esg_idempotency_total",
    "Idempotency cache lookups by outcome.",
    labelnames=("result",),    # hit | miss | conflict
    registry=REGISTRY,
)

BATCH_ITEMS_TOTAL = Counter(
    "esg_batch_items_total",
    "Items processed inside /emissions/batch by per-item outcome.",
    labelnames=("status",),    # ok | error
    registry=REGISTRY,
)


def render() -> tuple[bytes, str]:
    """Return ``(payload, content_type)`` for the /metrics endpoint."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def status_class(status_code: int) -> str:
    """Bucket HTTP status codes into 1xx/2xx/3xx/4xx/5xx labels."""
    return f"{status_code // 100}xx"
