from pathlib import Path

import ai_models
import pytest
from ai_models import litellm_adapter
from django.core.management import CommandError, call_command

CATALOG_PATH = Path(ai_models.__file__).parent / "data" / "catalog.json"


def _catalog_bytes() -> bytes | None:
    return CATALOG_PATH.read_bytes() if CATALOG_PATH.exists() else None


def test_refuses_to_build_from_a_live_fetched_model_map(monkeypatch):
    # LiteLLM reads LITELLM_LOCAL_MODEL_COST_MAP once at import, so its own answer is stubbed.
    monkeypatch.setattr(
        litellm_adapter, "get_model_cost_map_source_info", lambda: {"is_env_forced": False}
    )
    before = _catalog_bytes()

    with pytest.raises(CommandError, match="LITELLM_LOCAL_MODEL_COST_MAP"):
        call_command("build_model_catalog")

    assert _catalog_bytes() == before


def test_a_model_map_source_litellm_cannot_report_fails_as_a_command_error(monkeypatch):
    def unreadable_source_info():
        raise KeyError("is_env_forced")

    monkeypatch.setattr(litellm_adapter, "get_model_cost_map_source_info", unreadable_source_info)
    before = _catalog_bytes()

    with pytest.raises(CommandError, match="say where its model map came from"):
        call_command("build_model_catalog")

    assert _catalog_bytes() == before


def test_refuses_to_build_while_the_daily_refresh_may_change_the_map(settings):
    settings.LITELLM_MODEL_COST_REFRESH_ENABLED = True
    before = _catalog_bytes()

    with pytest.raises(CommandError, match="LITELLM_MODEL_COST_REFRESH_ENABLED"):
        call_command("build_model_catalog")

    assert _catalog_bytes() == before
