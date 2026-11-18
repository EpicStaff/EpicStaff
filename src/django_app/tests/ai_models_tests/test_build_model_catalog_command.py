from pathlib import Path

import ai_models
import pytest
from django.core.management import CommandError, call_command

CATALOG_PATH = Path(ai_models.__file__).parent / "data" / "catalog.json"


def _catalog_bytes() -> bytes | None:
    return CATALOG_PATH.read_bytes() if CATALOG_PATH.exists() else None


@pytest.mark.parametrize("value", [None, "False", ""])
def test_refuses_to_build_from_a_live_fetched_model_map(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("LITELLM_LOCAL_MODEL_COST_MAP", raising=False)
    else:
        monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", value)
    before = _catalog_bytes()

    with pytest.raises(CommandError, match="LITELLM_LOCAL_MODEL_COST_MAP"):
        call_command("build_model_catalog")

    assert _catalog_bytes() == before


def test_refuses_to_build_while_the_daily_refresh_may_change_the_map(settings):
    settings.LITELLM_MODEL_COST_REFRESH_ENABLED = True
    before = _catalog_bytes()

    with pytest.raises(CommandError, match="LITELLM_MODEL_COST_REFRESH_ENABLED"):
        call_command("build_model_catalog")

    assert _catalog_bytes() == before
