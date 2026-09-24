from __future__ import annotations

from datetime import datetime

import pandas as pd


class CarbonSource:
    """fetch(region_key, grid_code, start, end) -> normalized DataFrame (see cao.carbon.schema)."""

    name = "base"

    def fetch(self, region: str, grid: str, start: datetime, end: datetime) -> pd.DataFrame:
        raise NotImplementedError
