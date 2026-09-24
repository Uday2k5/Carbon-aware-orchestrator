from .base import CarbonSource
from .eia import EiaSource
from .electricity_maps import ElectricityMapsSource
from .entsoe import EntsoeSource
from .synthetic import SyntheticSource
from .uk import UkCarbonIntensitySource

SOURCES = {
    "uk": UkCarbonIntensitySource,
    "entsoe": EntsoeSource,
    "eia": EiaSource,
    "electricity-maps": ElectricityMapsSource,
    "synthetic": SyntheticSource,
}


def get_source(name: str, **kw) -> CarbonSource:
    try:
        return SOURCES[name](**kw)
    except KeyError as exc:
        raise ValueError(f"unknown source {name!r}; choose from {sorted(SOURCES)}") from exc


__all__ = ["CarbonSource", "SOURCES", "get_source"]
