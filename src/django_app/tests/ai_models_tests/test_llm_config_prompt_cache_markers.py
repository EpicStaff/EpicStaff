"""An LLM config reports whether its model takes Anthropic prompt-cache markers, read-only,
without extra queries per config in a list."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from ai_models.models import LLMConfig, LLMModel, Provider
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

LLM_CONFIGS = "/api/llm-configs/"


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    yield api_client


def _config(acme, custom_name: str, provider_name: str | None, model_name: str | None):
    model = None
    if model_name is not None:
        provider = Provider.objects.get_or_create(name=provider_name)[0] if provider_name else None
        model = LLMModel.objects.get_or_create(name=model_name, llm_provider=provider)[0]
    return LLMConfig.objects.create(custom_name=custom_name, model=model, org=acme)


def _rows(response) -> list[dict]:
    return response.data["results"] if isinstance(response.data, dict) else response.data


@pytest.mark.django_db
@pytest.mark.parametrize(
    "provider_name, model_name, expected",
    [
        ("anthropic", "claude-sonnet-5-5", True),
        ("openai", "gpt-4o", False),
        # A model whose provider was deleted cannot run at all.
        (None, "claude-sonnet-5-5", False),
        (None, None, False),
    ],
    ids=["claude", "openai", "model-without-provider", "no-model"],
)
def test_config_reports_whether_its_model_takes_cache_markers(
    client, acme, provider_name, model_name, expected
):
    config = _config(acme, "config", provider_name, model_name)

    response = client.get(f"{LLM_CONFIGS}{config.id}/")

    assert response.status_code == 200, response.data
    assert response.data["needs_prompt_cache_markers"] is expected


@pytest.mark.django_db
def test_value_sent_on_write_is_ignored(client, acme):
    config = _config(acme, "gpt-config", "openai", "gpt-4o")

    response = client.patch(
        f"{LLM_CONFIGS}{config.id}/", {"needs_prompt_cache_markers": True}, format="json"
    )

    assert response.status_code == 200, response.data
    assert response.data["needs_prompt_cache_markers"] is False


@pytest.mark.django_db
def test_list_adds_no_query_per_config(client, acme):
    _config(acme, "claude-config", "anthropic", "claude-sonnet-5-5")
    with CaptureQueriesContext(connection) as one_config:
        assert client.get(LLM_CONFIGS).status_code == 200

    _config(acme, "second-claude-config", "anthropic", "claude-sonnet-5-5")
    _config(acme, "gpt-config", "openai", "gpt-4o")
    _config(acme, "empty-config", None, None)
    with CaptureQueriesContext(connection) as four_configs:
        response = client.get(LLM_CONFIGS)

    assert {row["custom_name"]: row["needs_prompt_cache_markers"] for row in _rows(response)} == {
        "claude-config": True,
        "second-claude-config": True,
        "gpt-config": False,
        "empty-config": False,
    }
    assert len(four_configs.captured_queries) == len(one_config.captured_queries)
