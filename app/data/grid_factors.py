"""
Regional electricity grid emission factors in kgCO2e per kWh (operational/generation mix).

Vintage: 2025 (data year), published 2026.

Sources
-------
* EU member states: EEA — Greenhouse gas emission intensity of electricity
  generation in Europe (2025 data, published 2026).
* United States (national + sub-regional): EPA eGRID 2024 (released 2026).
* Other countries: IEA Emissions Factors 2026 edition.

These are *operational* (location-based) factors — i.e., the average grid mix
where the energy is consumed. They are the appropriate factor for ESRS E1
Scope 2 location-based reporting. Buyers wanting *market-based* (residual mix
or PPA-adjusted) values should override via primary data per ESRS E1 §49.

NB: figures here reflect best-known published values as of the
`published` date below. Operators citing them in CSRD disclosures should
verify against the original EEA / EPA / IEA workbooks for their specific
reporting boundary year.
"""

from __future__ import annotations

from typing import Final


GRID_METHODOLOGY: Final[dict[str, str]] = {
    "source": "EEA 2025 (EU), EPA eGRID 2024 (US), IEA 2026 (other)",
    "method": "Location-based, operational grid mix",
    "scope": "Well-to-Wheel (generation + T&D losses)",
    "unit": "kgCO2e per kWh delivered",
    "data_year": "2025",
    "published": "2026-Q1",
    "csrd_alignment": "ESRS E1 §49 — location-based Scope 2 disclosure",
}


# ISO-3166-1 alpha-2 country codes, plus a few sub-national US states and aggregates.
# Trend 2023→2025: most EU grids decarbonised by 15–25% as renewables overtook gas;
# US tracked similarly via coal retirements; PL/CN remained coal-heavy but improved
# at the margin. Values rounded to published precision.
GRID_FACTORS: Final[dict[str, float]] = {
    # United Kingdom — 2025 data; significant reduction vs 2023 (~25%).
    "GB": 0.15500,

    # EU-27 member states (selected)
    "FR": 0.04600,   # nuclear-dominant; minor swing with reactor availability
    "DE": 0.29000,   # coal phase-out + renewables surge
    "PL": 0.57500,   # still coal-heavy, slowly improving
    "ES": 0.13000,   # massive solar build-out
    "SE": 0.01200,   # hydro + nuclear, lowest in Europe
    "IT": 0.23500,
    "NL": 0.24000,
    "BE": 0.14200,
    "PT": 0.11000,
    "AT": 0.08800,
    "DK": 0.11500,
    "FI": 0.06800,
    "IE": 0.24000,
    "CZ": 0.37000,
    "GR": 0.33000,
    "HU": 0.19500,
    "RO": 0.21500,

    # Non-EU Europe
    "CH": 0.02900,
    "NO": 0.01800,

    # North America
    "US":    0.36500,    # national average (eGRID 2024)
    "US-CA": 0.18500,
    "US-WA": 0.09800,
    "US-TX": 0.37800,
    "US-NY": 0.19000,
    "CA":    0.12200,

    # Asia-Pacific
    "CN": 0.54500,
    "IN": 0.68000,
    "JP": 0.42500,
    "KR": 0.40500,
    "AU": 0.46000,

    # South America
    "BR": 0.09000,

    # Aggregates
    "EU27":  0.19500,
    "WORLD": 0.46000,
}


def get_grid_factor(region: str) -> float:
    """Return kgCO2e/kWh for a region. Raises ``KeyError`` if unknown."""
    if region not in GRID_FACTORS:
        raise KeyError(
            f"Unknown region '{region}'. Use ISO-3166-1 alpha-2 (e.g. 'FR', 'DE') "
            f"or supported aggregates ('EU27', 'WORLD'). "
            f"Supported: {sorted(GRID_FACTORS)}"
        )
    return GRID_FACTORS[region]
