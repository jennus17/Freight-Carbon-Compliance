"""
Controller layer — orchestration between transport (HTTP) and the service layer.

Responsibilities:
  * Translate domain exceptions raised by the service layer into HTTP errors.
  * Apply idempotency caching when the caller supplies an ``Idempotency-Key``.
  * Drive batch execution with per-item failure isolation.
  * Keep route handlers thin (parsing/serialisation only).
"""

from __future__ import annotations

import logging
from collections import defaultdict

from fastapi import HTTPException, status

from app.core.idempotency import (
    IdempotencyCache,
    IdempotencyMismatchError,
    get_cache,
    hash_payload,
)
from app.core.metrics import (
    BATCH_ITEMS_TOTAL,
    EMISSIONS_CALCULATED_TOTAL,
    IDEMPOTENCY_TOTAL,
)
from app.models.emissions import (
    BatchAggregate,
    BatchItem,
    BatchItemError,
    BatchRequest,
    BatchResponse,
    EmissionRequest,
    EmissionResponse,
)
from app.services.emission_calculator import (
    EmissionCalculator,
    IncompatibleFuelError,
    UnknownRegionError,
)


_log = logging.getLogger("app.controller")

# Round aggregates to the same precision as individual responses.
_ROUND_KG = 6
_ROUND_TONNES = 9


class EmissionsController:
    def __init__(
        self,
        calculator: EmissionCalculator | None = None,
        cache: IdempotencyCache | None = None,
    ) -> None:
        self._calculator = calculator or EmissionCalculator()
        self._cache = cache or get_cache()

    # ---- Single-shipment ---------------------------------------------------

    def calculate(
        self,
        request: EmissionRequest,
        idempotency_key: str | None = None,
    ) -> tuple[EmissionResponse, bool]:
        """
        Returns ``(response, replayed)``. ``replayed`` is True when the response
        was served from the idempotency cache.
        """
        body_hash: str | None = None
        if idempotency_key:
            body_hash = hash_payload(request)
            cached = self._lookup(idempotency_key, body_hash)
            if cached is not None:
                IDEMPOTENCY_TOTAL.labels(result="hit").inc()
                return cached, True
            IDEMPOTENCY_TOTAL.labels(result="miss").inc()

        result = self._safe_calculate(request)
        _record_calculation_metric(result)
        _log.info(
            "calculation",
            extra={
                "transport_type": result.transport_type.value,
                "fuel_resolved": result.methodology_reference.fuel_resolved,
                "region_resolved": result.methodology_reference.region_resolved,
                "methodology_version": result.methodology_reference.extra_references.get(
                    "version_resolved"
                ),
                "co2e_kg": result.co2e_kg,
                "shipment_id": result.shipment_id,
            },
        )

        if idempotency_key and body_hash is not None:
            self._cache.set(idempotency_key, body_hash, result)
        return result, False

    # ---- Batch -------------------------------------------------------------

    def calculate_batch(
        self,
        batch: BatchRequest,
        idempotency_key: str | None = None,
    ) -> tuple[BatchResponse, bool]:
        body_hash: str | None = None
        if idempotency_key:
            body_hash = hash_payload(batch)
            cached = self._lookup(idempotency_key, body_hash)
            if cached is not None:
                IDEMPOTENCY_TOTAL.labels(result="hit").inc()
                return cached, True
            IDEMPOTENCY_TOTAL.labels(result="miss").inc()

        items: list[BatchItem] = []
        successful = 0
        failed = 0
        total_kg = 0.0
        by_mode: dict[str, float] = defaultdict(float)
        version_used: str | None = None

        for index, req in enumerate(batch.items):
            try:
                result = self._calculator.calculate(req)
            except (IncompatibleFuelError, UnknownRegionError) as exc:
                items.append(BatchItem(
                    index=index,
                    status="error",
                    error=BatchItemError(type=type(exc).__name__, detail=str(exc)),
                ))
                failed += 1
                BATCH_ITEMS_TOTAL.labels(status="error").inc()
                continue
            except KeyError as exc:
                items.append(BatchItem(
                    index=index,
                    status="error",
                    error=BatchItemError(
                        type="KeyError",
                        detail=str(exc).strip("'"),
                    ),
                ))
                failed += 1
                BATCH_ITEMS_TOTAL.labels(status="error").inc()
                continue

            items.append(BatchItem(index=index, status="ok", result=result))
            successful += 1
            total_kg += result.co2e_kg
            by_mode[result.transport_type.value] += result.co2e_kg
            BATCH_ITEMS_TOTAL.labels(status="ok").inc()
            _record_calculation_metric(result)
            # Capture the version from the first successful item (all items share input,
            # but version is per-item — pick the most recent observed for the summary).
            version_used = result.methodology_reference.extra_references.get(
                "version_resolved", version_used
            )

        response = BatchResponse(
            aggregate=BatchAggregate(
                total_items=len(batch.items),
                successful=successful,
                failed=failed,
                total_co2e_kg=round(total_kg, _ROUND_KG),
                total_co2e_tonnes=round(total_kg / 1000.0, _ROUND_TONNES),
                by_transport_type_kg_co2e={
                    k: round(v, _ROUND_KG) for k, v in sorted(by_mode.items())
                },
            ),
            items=items,
            methodology_version_used=version_used,
        )

        if idempotency_key and body_hash is not None:
            self._cache.set(idempotency_key, body_hash, response)
        return response, False

    # ---- Reference data ----------------------------------------------------

    def list_modes(self) -> dict[str, list[str]]:
        return self._calculator.list_supported_modes()

    def list_fuels(self) -> dict[str, list[str]]:
        return self._calculator.list_supported_fuels()

    def list_regions(self) -> dict[str, float]:
        return self._calculator.list_supported_regions()

    # ---- Internals ---------------------------------------------------------

    def _safe_calculate(self, request: EmissionRequest) -> EmissionResponse:
        try:
            return self._calculator.calculate(request)
        except (IncompatibleFuelError, UnknownRegionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc).strip("'"),
            ) from exc

    def _lookup(self, key: str, body_hash: str):
        try:
            return self._cache.get(key, body_hash)
        except IdempotencyMismatchError as exc:
            IDEMPOTENCY_TOTAL.labels(result="conflict").inc()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc


def _record_calculation_metric(result) -> None:
    EMISSIONS_CALCULATED_TOTAL.labels(
        transport_type=result.transport_type.value,
        fuel_resolved=result.methodology_reference.fuel_resolved,
        methodology_version=result.methodology_reference.extra_references.get(
            "version_resolved", "unknown"
        ),
    ).inc()
