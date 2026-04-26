"""
Named request and response examples for the OpenAPI spec.

RapidAPI's test playground uses these to populate the "Try it out" form.
Without explicit examples, the playground auto-generates payloads from
schema defaults — and badly serialises ``str | None`` fields as ``{}`` and
enum defaults as character-indexed objects. Providing named examples
forces it to use real, valid payloads instead.
"""

from __future__ import annotations

from typing import Final


# ──────────────────────────────────────────────────────────────────────────
# Request examples — POST /api/v1/emissions/calculate
# ──────────────────────────────────────────────────────────────────────────

REQUEST_EXAMPLES_CALCULATE: Final[dict] = {
    "simple_truck": {
        "summary": "Simple 1-tonne truck shipment, 100 km",
        "description": (
            "Minimal request — only the three required fields. Mode default "
            "(HGV all-average), fuel default (diesel), latest methodology."
        ),
        "value": {
            "weight_kg": 1000,
            "distance_km": 100,
            "transport_type": "truck",
        },
    },
    "electric_rail_france_2025": {
        "summary": "25-tonne electric rail in France, DEFRA 2025",
        "description": (
            "Showcases regional grid factor: FR grid is ~12× cleaner than "
            "Poland, dragging the electric rail factor down accordingly."
        ),
        "value": {
            "weight_kg": 25000,
            "distance_km": 600,
            "transport_type": "rail",
            "fuel_type": "electric",
            "region": "FR",
            "methodology_version": "2025",
        },
    },
    "air_freight_with_saf": {
        "summary": "Long-haul air freight on 30% SAF blend",
        "description": (
            "Sustainable Aviation Fuel substitution via GLEC v3.0 §6.3 ratio "
            "method. ~25–30% emissions reduction vs neat Jet A-1."
        ),
        "value": {
            "weight_kg": 500,
            "distance_km": 9000,
            "transport_type": "air",
            "sub_mode": "long_haul",
            "fuel_type": "saf_blend_30",
        },
    },
    "container_ship_methanol": {
        "summary": "Container ship on green methanol — alternative-fuel pathway",
        "description": (
            "e-methanol from renewable hydrogen (IMO MEPC.1/Circ.905). "
            "~85–90% reduction vs heavy fuel oil baseline."
        ),
        "value": {
            "weight_kg": 50000,
            "distance_km": 8000,
            "transport_type": "ship",
            "sub_mode": "container",
            "fuel_type": "methanol_green",
        },
    },
    "pinned_historical_2023": {
        "summary": "Pinned to DEFRA 2023 vintage (stable historical reports)",
        "description": (
            "When a customer's CSRD report cites a 2023-vintage figure, pin "
            "the calculation to '2023' so it never drifts as new vintages ship."
        ),
        "value": {
            "weight_kg": 22000,
            "distance_km": 850,
            "transport_type": "truck",
            "sub_mode": "articulated_average",
            "methodology_version": "2023",
            "shipment_id": "PO-2026-08821",
        },
    },
}


# ──────────────────────────────────────────────────────────────────────────
# Request examples — POST /api/v1/emissions/batch
# ──────────────────────────────────────────────────────────────────────────

REQUEST_EXAMPLES_BATCH: Final[dict] = {
    "three_modes": {
        "summary": "Three shipments across truck / rail / ship",
        "value": {
            "items": [
                {"weight_kg": 1000, "distance_km": 100, "transport_type": "truck"},
                {
                    "weight_kg": 25000,
                    "distance_km": 600,
                    "transport_type": "rail",
                    "fuel_type": "electric",
                    "region": "FR",
                },
                {
                    "weight_kg": 50000,
                    "distance_km": 8000,
                    "transport_type": "ship",
                    "sub_mode": "container",
                },
            ]
        },
    },
    "mixed_with_failure": {
        "summary": "Failure isolation — one bad row, rest succeed",
        "description": (
            "Item 1 has an incompatible fuel (jet fuel on a ship). The other "
            "two complete normally; aggregate covers only successful items."
        ),
        "value": {
            "items": [
                {"weight_kg": 1000, "distance_km": 100, "transport_type": "truck"},
                {
                    "weight_kg": 5000,
                    "distance_km": 500,
                    "transport_type": "ship",
                    "fuel_type": "jet_a1",
                },
                {"weight_kg": 2000, "distance_km": 300, "transport_type": "rail"},
            ]
        },
    },
}


# ──────────────────────────────────────────────────────────────────────────
# Response examples (200) — POST /api/v1/emissions/calculate
# ──────────────────────────────────────────────────────────────────────────

_RESPONSE_CALC_SIMPLE_TRUCK = {
    "shipment_id": None,
    "transport_type": "truck",
    "co2e_kg": 10.685,
    "co2e_tonnes": 0.000010685,
    "calculation": {"mass_tonnes": 1.0, "distance_km": 100.0, "tonne_km": 100.0},
    "methodology_reference": {
        "source": "UK DEFRA 2025 GHG Conversion Factors for Company Reporting",
        "dataset": "Freighting goods",
        "scope": "Well-to-Wheel (WTT + TTW combined)",
        "unit": "kgCO2e per tonne-kilometre",
        "version": "2025 v1.0",
        "url": "https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025",
        "csrd_alignment": "ESRS E1 – Climate change. Scope 3 Cat 4 / 9.",
        "factor_kg_co2e_per_tkm": 0.10685,
        "sub_mode_resolved": "default",
        "fuel_resolved": "diesel",
        "region_resolved": None,
        "resolution_chain": [
            {
                "step": "base_factor",
                "description": "DEFRA 2025 freight factor for truck/default",
                "value_kg_co2e_per_tkm": 0.10685,
                "ratio": None,
                "source": "UK DEFRA 2025 GHG Conversion Factors for Company Reporting",
            }
        ],
        "extra_references": {
            "version_resolved": "2025",
            "supported_versions": ["2023", "2024", "2025"],
        },
    },
    "calculated_at": "2026-04-26T12:36:21.000Z",
}

_RESPONSE_CALC_ELECTRIC_RAIL_FR = {
    "shipment_id": None,
    "transport_type": "rail",
    "co2e_kg": 93.706452,
    "co2e_tonnes": 0.000093706,
    "calculation": {"mass_tonnes": 25.0, "distance_km": 600.0, "tonne_km": 15000.0},
    "methodology_reference": {
        "source": "UK DEFRA 2025 GHG Conversion Factors for Company Reporting",
        "dataset": "Freighting goods",
        "scope": "Well-to-Wheel (WTT + TTW combined)",
        "unit": "kgCO2e per tonne-kilometre",
        "version": "2025 v1.0",
        "url": "https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025",
        "csrd_alignment": "ESRS E1 – Climate change. Scope 3 Cat 4 / 9.",
        "factor_kg_co2e_per_tkm": 0.0062471,
        "sub_mode_resolved": "electric",
        "fuel_resolved": "electric",
        "region_resolved": "FR",
        "resolution_chain": [
            {
                "step": "base_factor",
                "description": "DEFRA 2025 freight factor for rail/default",
                "value_kg_co2e_per_tkm": 0.02675,
            },
            {
                "step": "switch_to_electric_base",
                "description": "Replaced base factor with DEFRA rail/electric (0.02105).",
                "value_kg_co2e_per_tkm": 0.02105,
            },
            {
                "step": "regional_grid_adjustment",
                "description": "Adjusted from GB grid (0.15500) to FR grid (0.04600).",
                "ratio": 0.29677,
                "value_kg_co2e_per_tkm": 0.0062471,
            },
        ],
        "extra_references": {
            "version_resolved": "2025",
            "supported_versions": ["2023", "2024", "2025"],
        },
    },
    "calculated_at": "2026-04-26T12:36:21.000Z",
}


RESPONSES_CALCULATE: Final[dict] = {
    200: {
        "description": "Successful calculation with full audit trail.",
        "content": {
            "application/json": {
                "examples": {
                    "simple_truck": {
                        "summary": "Simple truck shipment",
                        "value": _RESPONSE_CALC_SIMPLE_TRUCK,
                    },
                    "electric_rail_france": {
                        "summary": "Electric rail in France with regional grid adjustment",
                        "value": _RESPONSE_CALC_ELECTRIC_RAIL_FR,
                    },
                }
            }
        },
    },
    409: {
        "description": "Idempotency-Key reused with a different request body.",
        "content": {
            "application/json": {
                "example": {
                    "detail": (
                        "Idempotency-Key 'shipment-001' was previously used with "
                        "a different request body."
                    )
                }
            }
        },
    },
    422: {
        "description": "Request validation failed (bad input or incompatible fuel/region).",
        "content": {
            "application/json": {
                "examples": {
                    "incompatible_fuel": {
                        "summary": "Fuel/transport_type incompatibility",
                        "value": {
                            "detail": (
                                "fuel_type 'jet_a1' is not compatible with "
                                "transport_type 'ship'. Compatible: "
                                "['hfo', 'lng', 'methanol_green', 'methanol_grey', 'mgo']."
                            )
                        },
                    },
                    "unknown_region": {
                        "summary": "Region not in supported list",
                        "value": {
                            "detail": "Unknown region 'ATLANTIS'. See /api/v1/reference/regions."
                        },
                    },
                    "field_validation": {
                        "summary": "Field-level validation (Pydantic)",
                        "value": {
                            "detail": [
                                {
                                    "type": "greater_than",
                                    "loc": ["body", "weight_kg"],
                                    "msg": "Input should be greater than 0",
                                    "input": 0,
                                }
                            ]
                        },
                    },
                }
            }
        },
    },
}


# ──────────────────────────────────────────────────────────────────────────
# Response examples (200) — POST /api/v1/emissions/batch
# ──────────────────────────────────────────────────────────────────────────

_RESPONSE_BATCH_SUCCESS = {
    "aggregate": {
        "total_items": 3,
        "successful": 3,
        "failed": 0,
        "total_co2e_kg": 884.69,
        "total_co2e_tonnes": 0.000884690,
        "by_transport_type_kg_co2e": {
            "rail": 93.706452,
            "ship": 780.296,
            "truck": 10.685,
        },
    },
    "items": [
        {"index": 0, "status": "ok", "result": _RESPONSE_CALC_SIMPLE_TRUCK, "error": None},
        {"index": 1, "status": "ok", "result": _RESPONSE_CALC_ELECTRIC_RAIL_FR, "error": None},
        {"index": 2, "status": "ok", "result": "(...EmissionResponse for ship omitted for brevity)", "error": None},
    ],
    "methodology_version_used": "2025",
}

_RESPONSE_BATCH_MIXED = {
    "aggregate": {
        "total_items": 3,
        "successful": 2,
        "failed": 1,
        "total_co2e_kg": 26.985,
        "total_co2e_tonnes": 0.000026985,
        "by_transport_type_kg_co2e": {"rail": 16.300, "truck": 10.685},
    },
    "items": [
        {"index": 0, "status": "ok", "result": "(...EmissionResponse for truck...)", "error": None},
        {
            "index": 1,
            "status": "error",
            "result": None,
            "error": {
                "type": "IncompatibleFuelError",
                "detail": (
                    "fuel_type 'jet_a1' is not compatible with transport_type 'ship'. "
                    "Compatible: ['hfo', 'lng', 'methanol_green', 'methanol_grey', 'mgo']."
                ),
            },
        },
        {"index": 2, "status": "ok", "result": "(...EmissionResponse for rail...)", "error": None},
    ],
    "methodology_version_used": "2025",
}


RESPONSES_BATCH: Final[dict] = {
    200: {
        "description": (
            "Batch result. Per-item failures do not fail the batch — see "
            "items[].status. Aggregate totals cover only successful items."
        ),
        "content": {
            "application/json": {
                "examples": {
                    "all_success": {
                        "summary": "Three modes, all succeeded",
                        "value": _RESPONSE_BATCH_SUCCESS,
                    },
                    "mixed_with_failure": {
                        "summary": "One row failed (incompatible fuel) — others succeeded",
                        "value": _RESPONSE_BATCH_MIXED,
                    },
                }
            }
        },
    },
    409: {
        "description": "Idempotency-Key reused with a different batch body.",
        "content": {
            "application/json": {
                "example": {
                    "detail": "Idempotency-Key 'batch-001' was previously used with a different request body."
                }
            }
        },
    },
    422: {
        "description": "Batch validation failed (empty items, oversize, malformed items).",
        "content": {
            "application/json": {
                "example": {
                    "detail": [
                        {
                            "type": "too_long",
                            "loc": ["body", "items"],
                            "msg": "List should have at most 1000 items after validation, not 1001",
                        }
                    ]
                }
            }
        },
    },
}


# ──────────────────────────────────────────────────────────────────────────
# Reference endpoints
# ──────────────────────────────────────────────────────────────────────────

RESPONSES_MODES: Final[dict] = {
    200: {
        "description": "Per-mode list of valid sub_mode values.",
        "content": {
            "application/json": {
                "example": {
                    "truck": ["articulated_average", "rigid_average", "van_class_iii"],
                    "rail": ["diesel", "electric"],
                    "ship": ["bulk_carrier", "container", "ro_ro_ferry", "tanker_general_cargo"],
                    "air": ["domestic", "long_haul", "short_haul"],
                }
            }
        },
    }
}

RESPONSES_FUELS: Final[dict] = {
    200: {
        "description": "Per-mode list of valid fuel_type values (compatibility matrix).",
        "content": {
            "application/json": {
                "example": {
                    "truck": ["biodiesel_b20", "diesel", "diesel_b7", "hvo100", "lng"],
                    "rail": ["diesel", "electric", "hvo100"],
                    "ship": ["hfo", "lng", "methanol_green", "methanol_grey", "mgo"],
                    "air": ["jet_a1", "saf_blend_30", "saf_neat"],
                }
            }
        },
    }
}

RESPONSES_REGIONS: Final[dict] = {
    200: {
        "description": "Region code → grid factor (kgCO2e/kWh, EEA/EPA/IEA 2025 data).",
        "content": {
            "application/json": {
                "example": {
                    "AT": 0.088,
                    "AU": 0.46,
                    "BE": 0.142,
                    "BR": 0.09,
                    "CA": 0.122,
                    "CH": 0.029,
                    "CN": 0.545,
                    "DE": 0.29,
                    "EU27": 0.195,
                    "FR": 0.046,
                    "GB": 0.155,
                    "PL": 0.575,
                    "US": 0.365,
                    "WORLD": 0.46,
                }
            }
        },
    }
}
