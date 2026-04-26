"""HTTP route declarations for the emissions endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Response

from app.api.controllers.emissions_controller import EmissionsController
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


@router.post(
    "/calculate",
    response_model=EmissionResponse,
    summary="Calculate the carbon footprint of a single shipment",
    response_description="Audit-grade CO2e breakdown with methodology reference.",
)
def calculate_emissions(
    payload: EmissionRequest,
    response: Response,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description=_IDEMPOTENCY_HEADER_DESC,
    ),
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
    result, replayed = controller.calculate(payload, idempotency_key=idempotency_key)
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.post(
    "/batch",
    response_model=BatchResponse,
    summary="Calculate emissions for up to 1000 shipments in one call",
    response_description="Per-item results with aggregate totals.",
)
def calculate_batch(
    payload: BatchRequest,
    response: Response,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description=_IDEMPOTENCY_HEADER_DESC,
    ),
    controller: EmissionsController = Depends(get_controller),
) -> BatchResponse:
    """
    Bulk calculation endpoint. Each item is processed independently —
    a single bad row does not fail the whole batch. The aggregate totals
    cover only successful items; failed items appear in `items[]` with
    `status='error'` and a structured error payload.
    """
    result, replayed = controller.calculate_batch(payload, idempotency_key=idempotency_key)
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.get(
    "/modes",
    summary="List supported transport modes and sub-modes",
    response_model=dict[str, list[str]],
)
def list_modes(
    controller: EmissionsController = Depends(get_controller),
) -> dict[str, list[str]]:
    return controller.list_modes()


@reference_router.get(
    "/fuels",
    summary="List fuels compatible with each transport mode",
    response_model=dict[str, list[str]],
)
def list_fuels(
    controller: EmissionsController = Depends(get_controller),
) -> dict[str, list[str]]:
    return controller.list_fuels()


@reference_router.get(
    "/regions",
    summary="List supported region codes and their grid factors (kgCO2e/kWh)",
    response_model=dict[str, float],
)
def list_regions(
    controller: EmissionsController = Depends(get_controller),
) -> dict[str, float]:
    return controller.list_regions()
