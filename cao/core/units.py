"""Unit helpers. Internal convention: energy in Joules, CI in gCO2e/kWh, carbon in grams."""

J_PER_KWH = 3_600_000.0


def joules_to_kwh(joules: float) -> float:
    return joules / J_PER_KWH


def kwh_to_joules(kwh: float) -> float:
    return kwh * J_PER_KWH


def carbon_g(energy_kwh: float, ci_g_per_kwh: float) -> float:
    """gCO2e = kWh x gCO2e/kWh."""
    return energy_kwh * ci_g_per_kwh
