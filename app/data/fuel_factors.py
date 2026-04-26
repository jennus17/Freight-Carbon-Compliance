"""
Fuel-pathway emission factors used to substitute the default fossil fuel
implied by the DEFRA freight factors with an alternative fuel (HVO, SAF,
LNG, methanol, etc.).

Method
------
We use the **fuel-substitution ratio method** from the Smart Freight Centre's
GLEC Framework v3.0 §6.3: when primary fuel-quantity data is unavailable but
the operator knows the *fuel type* in use, multiply the activity-based factor
by the ratio of the alternative fuel's WTW emission intensity to the default
fuel's WTW emission intensity (both in kgCO2e per MJ of energy delivered).

This is GLEC Default Data Quality 3 — better than category averages,
weaker than primary fuel-burn data. Buyers wanting Quality 5 should use
the upcoming `/calculate-from-fuel` endpoint instead.

Sources
-------
* Fossil fuels: DEFRA 2023 GHG Conversion Factors — "Fuels" dataset.
* Biofuels (HVO, biodiesel, SAF): EU RED II certified default values
  (Annex V Part A, HEFA-SPK pathway).
* Methanol: IMO MEPC.1/Circ.905 (LCA Guidelines, 2024).
"""

from __future__ import annotations

from typing import Final


FUEL_METHODOLOGY: Final[dict[str, str]] = {
    "method": "GLEC Framework v3.0 §6.3 fuel-substitution ratio method",
    "data_quality": "GLEC Quality Level 3 (modeled, fuel-type known)",
    "basis": "WTW emission intensity per MJ of fuel energy",
    "csrd_alignment": "ESRS E1 §51 — Scope 3 Cat 4/9 with operator-specific fuel",
}


# Default fossil fuel implicitly assumed by each DEFRA freight factor.
# Switching away from this triggers the substitution ratio.
DEFAULT_FUEL_BY_MODE: Final[dict[str, str]] = {
    "truck": "diesel",
    "rail":  "diesel",      # rail/electric is handled via the grid pathway, not fuel substitution
    "ship":  "hfo",
    "air":   "jet_a1",
}


# Fuels that are physically/operationally compatible with each transport mode.
# Anything else is rejected with 422 — burning HFO in a plane is not a calc edge case, it's a typo.
COMPATIBLE_FUELS_BY_MODE: Final[dict[str, frozenset[str]]] = {
    "truck": frozenset({"diesel", "diesel_b7", "hvo100", "biodiesel_b20", "lng"}),
    "rail":  frozenset({"diesel", "hvo100", "electric"}),
    "ship":  frozenset({"hfo", "mgo", "lng", "methanol_grey", "methanol_green"}),
    "air":   frozenset({"jet_a1", "saf_blend_30", "saf_neat"}),
}


# Per-fuel WTW emission intensity in kgCO2e per MJ of delivered energy.
# Where biofuels have a non-zero biogenic share, the value here is the
# *non-biogenic* fraction only — the biogenic CO2 is reported separately
# per ESRS E1 §49 (a) and excluded from the headline total.
FUEL_FACTORS: Final[dict[str, dict]] = {
    "diesel": {
        "wtw_kg_co2e_per_mj": 0.07013,
        "biogenic_share": 0.00,
        "source": "DEFRA 2023 — Diesel (average biofuel blend)",
    },
    "diesel_b7": {
        "wtw_kg_co2e_per_mj": 0.06820,
        "biogenic_share": 0.07,
        "source": "EU mandated B7 blend (93% fossil + 7% FAME)",
    },
    "hvo100": {
        "wtw_kg_co2e_per_mj": 0.00505,
        "biogenic_share": 1.00,
        "source": "EU RED II Annex V — HEFA pathway, certified default",
    },
    "biodiesel_b20": {
        "wtw_kg_co2e_per_mj": 0.05690,
        "biogenic_share": 0.20,
        "source": "Blend of 80% diesel + 20% FAME (RED II certified)",
    },
    "lng": {
        "wtw_kg_co2e_per_mj": 0.05420,
        "biogenic_share": 0.00,
        "source": "DEFRA 2023 marine LNG (incl. methane slip)",
    },
    "hfo": {
        "wtw_kg_co2e_per_mj": 0.07900,
        "biogenic_share": 0.00,
        "source": "DEFRA 2023 — Heavy Fuel Oil (marine residual)",
    },
    "mgo": {
        "wtw_kg_co2e_per_mj": 0.07480,
        "biogenic_share": 0.00,
        "source": "DEFRA 2023 — Marine Gas Oil",
    },
    "jet_a1": {
        "wtw_kg_co2e_per_mj": 0.07330,
        "biogenic_share": 0.00,
        "source": "DEFRA 2023 — Jet kerosene",
    },
    "saf_blend_30": {
        "wtw_kg_co2e_per_mj": 0.05393,
        "biogenic_share": 0.30,
        "source": "70% jet_a1 + 30% saf_neat (RED II HEFA-SPK)",
    },
    "saf_neat": {
        "wtw_kg_co2e_per_mj": 0.01250,
        "biogenic_share": 1.00,
        "source": "EU RED II — neat SAF, HEFA-SPK pathway",
    },
    "methanol_grey": {
        "wtw_kg_co2e_per_mj": 0.10100,
        "biogenic_share": 0.00,
        "source": "IMO MEPC.1/Circ.905 — natural-gas-derived methanol",
    },
    "methanol_green": {
        "wtw_kg_co2e_per_mj": 0.01100,
        "biogenic_share": 1.00,
        "source": "IMO MEPC.1/Circ.905 — e-methanol from renewable H2",
    },
}


def fuel_substitution_ratio(transport_type: str, fuel_id: str) -> float:
    """
    Return ``fuel_factor / default_fuel_factor`` for the given mode.

    Returns 1.0 when the requested fuel is the mode's default.
    Raises ``KeyError`` for unknown fuels and ``ValueError`` for incompatible
    mode/fuel combinations (e.g. HFO on aircraft).
    """
    if fuel_id not in FUEL_FACTORS and fuel_id != "electric":
        raise KeyError(
            f"Unknown fuel_type '{fuel_id}'. Supported: "
            f"{sorted(list(FUEL_FACTORS) + ['electric'])}"
        )

    if fuel_id not in COMPATIBLE_FUELS_BY_MODE[transport_type]:
        raise ValueError(
            f"Fuel '{fuel_id}' is not compatible with transport_type "
            f"'{transport_type}'. Compatible fuels: "
            f"{sorted(COMPATIBLE_FUELS_BY_MODE[transport_type])}"
        )

    if fuel_id == "electric":
        # Electric pathway is handled via the regional grid factor, not fuel substitution.
        # Caller should branch on this case before calling.
        raise ValueError("Electric pathway must be resolved via grid_factors, not fuel substitution.")

    default_fuel = DEFAULT_FUEL_BY_MODE[transport_type]
    if fuel_id == default_fuel:
        return 1.0

    return FUEL_FACTORS[fuel_id]["wtw_kg_co2e_per_mj"] / FUEL_FACTORS[default_fuel]["wtw_kg_co2e_per_mj"]
