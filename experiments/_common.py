import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

from cao.core.config import load_settings  # noqa: E402
from cao.migration.cost_model import MigrationCostModel  # noqa: E402


def load_cost_model(settings=None):
    settings = settings or load_settings()
    p = os.environ.get("CAO_MIGRATION_MODEL", str(ROOT / "config" / "migration_model.json"))
    if os.path.exists(p):
        return MigrationCostModel.from_json(p)
    return MigrationCostModel.from_config(settings.migration_model, settings.network)
