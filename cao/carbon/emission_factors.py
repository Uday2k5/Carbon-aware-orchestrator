"""Lifecycle emission factors (gCO2e/kWh), IPCC AR5 WG3 Annex III medians (Schlomer et al. 2014).
Used to turn generation-by-fuel (ENTSO-E, EIA) into a grid carbon intensity:

    CI = sum_f(gen_f * EF_f) / sum_f(gen_f)
"""
from __future__ import annotations

from typing import Dict, Mapping

FACTORS: Dict[str, float] = {
    "coal": 820.0, "lignite": 820.0, "hard coal": 820.0,
    "gas": 490.0, "natural gas": 490.0,
    "oil": 650.0, "petroleum": 650.0,
    "biomass": 230.0,
    "waste": 620.0,
    "nuclear": 12.0,
    "hydro": 24.0, "hydro run-of-river": 24.0, "hydro reservoir": 24.0, "hydro pumped storage": 24.0,
    "wind": 11.0, "wind onshore": 11.0, "wind offshore": 12.0,
    "solar": 45.0,
    "geothermal": 38.0,
    "other": 700.0, "other renewable": 30.0, "unknown": 700.0,
}

# ENTSO-E PSR type names (entsoe-py column names) -> factor key
ENTSOE_MAP = {
    "Biomass": "biomass", "Fossil Brown coal/Lignite": "lignite", "Fossil Coal-derived gas": "gas",
    "Fossil Gas": "gas", "Fossil Hard coal": "hard coal", "Fossil Oil": "oil",
    "Fossil Oil shale": "oil", "Fossil Peat": "coal", "Geothermal": "geothermal",
    "Hydro Pumped Storage": "hydro pumped storage", "Hydro Run-of-river and poundage": "hydro run-of-river",
    "Hydro Water Reservoir": "hydro reservoir", "Marine": "other renewable", "Nuclear": "nuclear",
    "Other": "other", "Other renewable": "other renewable", "Solar": "solar", "Waste": "waste",
    "Wind Offshore": "wind offshore", "Wind Onshore": "wind onshore",
}

# EIA fuel-type codes (electricity/rto/fuel-type-data) -> factor key
EIA_MAP = {"COL": "coal", "NG": "gas", "NUC": "nuclear", "OIL": "oil", "OTH": "other",
           "SUN": "solar", "WAT": "hydro", "WND": "wind", "BAT": "other renewable", "PS": "hydro pumped storage"}


def ci_from_mix(mix_mw: Mapping[str, float], factor_map: Mapping[str, str] = None) -> float:
    """Generation-weighted CI. Keys are fuel names (mapped via factor_map if given)."""
    total = 0.0
    weighted = 0.0
    for fuel, mw in mix_mw.items():
        if mw is None or mw != mw or mw <= 0:
            continue
        key = factor_map.get(fuel, fuel) if factor_map else fuel
        ef = FACTORS.get(key.lower() if isinstance(key, str) else key, FACTORS["other"])
        total += mw
        weighted += mw * ef
    return weighted / total if total > 0 else float("nan")
