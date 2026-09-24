import pytest

from cao.core.config import load_settings
from cao.migration.cost_model import MigrationCostModel


@pytest.fixture(scope="session")
def settings():
    return load_settings()


@pytest.fixture(scope="session")
def cost_model(settings):
    return MigrationCostModel.from_config(settings.migration_model, settings.network)
