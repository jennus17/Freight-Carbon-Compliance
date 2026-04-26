"""HTTP route declarations for the emissions endpoints."""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Body, Depends, Header, Response

from app.api.controllers.emissions_controller import EmissionsController
from app.api.routes._examples import (
    REQUEST_EXAMPLES_BATCH,
    REQUEST_EXAMPLES_CALCULATE,
    RESPONSES_BATCH,
    RESPONSES_CALCULATE,
    RESPONSES_FUELS,
    RESPONSES_MODES,
    RESPONSES_REGIONS,
)
from app.models.emissions import (
    BatchRequest,
    BatchResponse,
    EmissionRequest,
    EmissionResponse,
)


router = APIRouter(prefix="/emissions", tags=["Emissions"])
reference_router = APIRouter(prefix="/reference", tags=["Reference data"])


def get_controller() -> EmissionsController:
    return EmissionsController()


_IDEMPOTENCY_HEADER_DESC = (
    "Optional Stripe-style idempotency key. Same key + same body → cached "
    "response (header `Idempotent-Replayed: true`). Same key + different "
    "body → 409 Conflict. TTL 24h."
)


# Header-value sentinels that some HTTP playgrounds (notably RapidAPI's) send
# when an optional header is left blank. Treat them as "no key supplied" so
# the customer doesn't see false 409s on consecutive un-keyed calls.
_JUNK_IDEMPOTENCY_VALUES: Final[frozenset[str]] = frozenset(
    {"", "{}", "null", "undefined", "none"}
)


def _normalize_idempotency_key(raw: str | None) -> str | None:
    """Strip whitespace; map known sentinels (``{}``, ``null``, ...) to ``None``."""
    if raw is None:
        return None
    stripped = raw.strip()
    if stripped.lower() in _JUNK_IDEMPOTENCY_VALUES:
        return None
    return stripped


@router.post(
    "/calculate",
    response_model=EmissionResponse,
    summary="Calculate the carbon footprint of a single shipment",
    response_description="Audit-grade CO2e breakdown with methodology reference.",
    responses=RESPONSES_CALCULATE,
)
def calculate_emissions(
    payload: Annotated[
        EmissionRequest,
        Body(openapi_examples=REQUEST_EXAMPLES_CALCULATE),
    ],
    response: Response,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=_IDEMPOTENCY_HEADER_DESC,
            examples=["shipment-2026-08821-attempt-1"],
        ),
    ] = None,
    controller: EmissionsController = Depends(get_controller),
) -> EmissionResponse:
    """
    Calculate CO2-equivalent emissions for a freight shipment.

    Refinements available:
      * `sub_mode` — vehicle/vessel class (e.g. `articulated_average`).
      * `fuel_type` — alternative fuel pathway (`hvo100`, `saf_neat`, `electric`, ...).
      * `region` — ISO-3166 code; localises grid factor when `fuel_type='electric'`.
      * `methodology_version` — pin to a vintage (e.g. `'2023'`) for stable historical reports.

    The full derivation appears in `methodology_reference.resolution_chain`.
    """
    key = _normalize_idempotency_key(idempotency_key)
    result, replayed = controller.calculate(payload, idempotency_key=key)
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.post(
    "/batch",
    response_model=BatchResponse,
    summary="Calculate emissions for up to 1000 shipments in one call",
    response_description="Per-item results with aggregate totals.",
    responses=RESPONSES_BATCH,
)
def calculate_batch(
    payload: Annotated[
        BatchRequest,
        Body(openapi_examples=REQUEST_EXAMPLES_BATCH),
    ],
    response: Response,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=_IDEMPOTENCY_HEADER_DESC,
            examples=["batch-2026-q1-week14"],
        ),
    ] = None,
    controller: EmissionsController = Depends(get_controller),
) -> BatchResponse:
    """
    Bulk calculation endpoint. Each item is processed independently —
    a single bad row does not fail the whole batch. The aggregate totals
    cover only successful items; failed items appear in `items[]` with
    `status='error'` and a structured error payload.
    """
    key = _normalize_idempotency_key(idempotency_key)
    result, replayed = controller.calculate_batch(payload, idempotency_key=key)
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.get(
    "/modes",
    summary="List supported transport modes and sub-modes",
    response_model=dict[str, list[str]],
    responses=RESPONSES_MODES,
)
def list_modes(
    controller: EmissionsController = Depends(get_controller),
) -> dict[str, list[str]]:
    return controller.list_modes()


@reference_router.get(
    "/fuels",
    summary="List fuels compatible with each transport mode",
    response_model=dict[str, list[str]],
    responses=RESPONSES_FUELS,
)
def list_fuels(
    controller: EmissionsController = Depends(get_controller),
) -> dict[str, list[str]]:
    return controller.list_fuels()


@reference_router.get(
    "/regions",
    summary="List supported region codes and their grid factors (kgCO2e/kWh)",
    response_model=dict[str, float],
    responses=RESPONSES_REGIONS,
)
def list_regions(
    controller: EmissionsController = Depends(get_controller),
) -> dict[str, float]:
    return controller.list_regions()
