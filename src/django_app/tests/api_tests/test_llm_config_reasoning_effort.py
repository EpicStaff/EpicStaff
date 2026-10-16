"""API tests for LLMConfig.reasoning_effort and LLMModel's reasoning capability fields.

litellm's model map is replaced by a copy holding known test models, so the
answers do not depend on a snapshot on disk. TestEffortPerModel and the level list
tests also use real model names from the installed litellm's bundled map, which
tests/settings.py pins over the live one.
"""

from collections import OrderedDict

import litellm
import pytest

from tables.models import LLMConfig, Provider
from tables.models.llm_models import LLMModel
from tables.utils import litellm_model_info
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

REASONING_MODEL = "epicstaff-test-reasoner"
PLAIN_MODEL = "epicstaff-test-plain"


@pytest.fixture(autouse=True)
def model_map(monkeypatch, tmp_path_factory):
    model_cost = dict(litellm.model_cost)
    for name, reasoning in ((REASONING_MODEL, True), (PLAIN_MODEL, False)):
        model_cost[f"openai/{name}"] = {
            "litellm_provider": "openai",
            "mode": "chat",
            "max_input_tokens": 128000,
            "supports_reasoning": reasoning,
        }
    monkeypatch.setattr(litellm, "model_cost", model_cost)
    monkeypatch.setenv("LITELLM_MODEL_COST_SNAPSHOT_PATH", str(tmp_path_factory.mktemp("litellm_snapshot") / "absent.json"))
    monkeypatch.setattr(litellm_model_info, "_loaded_snapshot_mtime", None)
    monkeypatch.setattr(litellm_model_info, "_reasoning_support_cache", OrderedDict())
    monkeypatch.setattr(litellm_model_info, "_model_cost_key_index", {})
    # litellm caches lookups by model name, across the per-test model_cost copies.
    litellm.utils._invalidate_model_cost_lowercase_map()
    yield model_cost
    litellm.utils._invalidate_model_cost_lowercase_map()


@pytest.fixture
def openai_provider(db):
    provider, _ = Provider.objects.get_or_create(name="openai")
    yield provider


@pytest.fixture
def reasoning_model(openai_provider):
    yield LLMModel.objects.create(name=REASONING_MODEL, llm_provider=openai_provider)


@pytest.fixture
def plain_model(openai_provider):
    yield LLMModel.objects.create(name=PLAIN_MODEL, llm_provider=openai_provider)


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    yield api_client


NEEDS_MODEL_REASON = "A reasoning effort needs a model. Select one or clear it."


def _not_a_reasoning_model_reason(model_name):
    return (
        f"Model '{model_name}' does not support a reasoning effort. "
        "Clear it or select a reasoning model."
    )


def _unsupported_level_reason(model_name, effort, supported):
    return (
        f"Model '{model_name}' does not support reasoning effort '{effort}'. "
        f"Supported: {supported}."
    )


def _assert_reasoning_effort_refused(response, value, reason):
    assert response.status_code == 400, response.data
    assert response.data == {
        "status_code": 400,
        "code": "unsupported_reasoning_effort",
        "message": reason,
        "errors": [{"field": "reasoning_effort", "value": value, "reason": reason}],
    }


def _config(org, model, reasoning_effort=None, name="config"):
    return LLMConfig.objects.create(
        custom_name=name, model=model, org=org, reasoning_effort=reasoning_effort
    )


@pytest.mark.django_db
class TestCreate:
    def test_reasoning_model_with_effort_is_created(self, client, reasoning_model):
        response = client.post(
            "/api/llm-configs/",
            {"custom_name": "r", "model": reasoning_model.id, "reasoning_effort": "high"},
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["reasoning_effort"] == "high"
        assert LLMConfig.objects.get(id=response.data["id"]).reasoning_effort == "high"

    def test_unknown_effort_value_is_rejected(self, client, reasoning_model):
        response = client.post(
            "/api/llm-configs/",
            {"custom_name": "r", "model": reasoning_model.id, "reasoning_effort": "ultra"},
            format="json",
        )

        assert response.status_code == 400
        # A value outside the choices is a plain field error, flattened to "<field>: <message>".
        assert response.data["message"].startswith("reasoning_effort: ")

    def test_non_reasoning_model_with_effort_is_rejected(self, client, plain_model):
        response = client.post(
            "/api/llm-configs/",
            {"custom_name": "p", "model": plain_model.id, "reasoning_effort": "low"},
            format="json",
        )

        _assert_reasoning_effort_refused(response, "low", _not_a_reasoning_model_reason(PLAIN_MODEL))
        assert not LLMConfig.objects.filter(custom_name="p").exists()

    def test_effort_without_model_is_rejected(self, client):
        response = client.post(
            "/api/llm-configs/",
            {"custom_name": "n", "model": None, "reasoning_effort": "low"},
            format="json",
        )

        _assert_reasoning_effort_refused(response, "low", NEEDS_MODEL_REASON)
        assert not LLMConfig.objects.filter(custom_name="n").exists()

    def test_non_reasoning_model_without_effort_is_created(self, client, plain_model):
        response = client.post(
            "/api/llm-configs/",
            {"custom_name": "p", "model": plain_model.id},
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["reasoning_effort"] is None


@pytest.mark.django_db
class TestUpdate:
    def test_set_effort_on_reasoning_model(self, client, acme, reasoning_model):
        config = _config(acme, reasoning_model)

        response = client.patch(
            f"/api/llm-configs/{config.id}/", {"reasoning_effort": "medium"}, format="json"
        )

        assert response.status_code == 200, response.data
        config.refresh_from_db()
        assert config.reasoning_effort == "medium"

    def test_swap_to_non_reasoning_model_keeping_effort_is_rejected(
        self, client, acme, reasoning_model, plain_model
    ):
        config = _config(acme, reasoning_model, reasoning_effort="high")

        response = client.patch(
            f"/api/llm-configs/{config.id}/", {"model": plain_model.id}, format="json"
        )

        _assert_reasoning_effort_refused(response, "high", _not_a_reasoning_model_reason(PLAIN_MODEL))
        config.refresh_from_db()
        assert config.model_id == reasoning_model.id

    def test_swap_to_non_reasoning_model_clearing_effort_succeeds(
        self, client, acme, reasoning_model, plain_model
    ):
        config = _config(acme, reasoning_model, reasoning_effort="high")

        response = client.patch(
            f"/api/llm-configs/{config.id}/",
            {"model": plain_model.id, "reasoning_effort": None},
            format="json",
        )

        assert response.status_code == 200, response.data
        config.refresh_from_db()
        assert config.model_id == plain_model.id
        assert config.reasoning_effort is None

    def test_clearing_the_model_while_effort_is_set_is_rejected(
        self, client, acme, reasoning_model
    ):
        config = _config(acme, reasoning_model, reasoning_effort="low")

        response = client.patch(
            f"/api/llm-configs/{config.id}/", {"model": None}, format="json"
        )

        _assert_reasoning_effort_refused(response, "low", NEEDS_MODEL_REASON)
        config.refresh_from_db()
        assert config.model_id == reasoning_model.id

    def test_patch_touching_neither_field_skips_the_check(
        self, client, acme, reasoning_model, model_map
    ):
        # The model map may stop listing the model as a reasoning model after the config
        # was saved; an unrelated edit must still go through.
        config = _config(acme, reasoning_model, reasoning_effort="high")
        model_map[f"openai/{REASONING_MODEL}"]["supports_reasoning"] = False

        response = client.patch(
            f"/api/llm-configs/{config.id}/", {"temperature": 0.3}, format="json"
        )

        assert response.status_code == 200, response.data
        config.refresh_from_db()
        assert config.temperature == 0.3
        assert config.reasoning_effort == "high"

    def test_cross_org_patch_is_not_found_and_row_unchanged(
        self, client, beta, reasoning_model
    ):
        foreign_config = _config(beta, reasoning_model, name="beta-config")

        response = client.patch(
            f"/api/llm-configs/{foreign_config.id}/",
            {"reasoning_effort": "high"},
            format="json",
        )

        assert response.status_code == 404
        foreign_config.refresh_from_db()
        assert foreign_config.reasoning_effort is None


@pytest.mark.django_db
class TestModelSupportsReasoning:
    def _listed(self, client, provider):
        response = client.get("/api/llm-models/", {"llm_provider": provider.id, "limit": 100})
        assert response.status_code == 200, response.data
        return {row["name"]: row for row in response.data["results"]}

    def test_list_reports_support_per_model(
        self, client, openai_provider, reasoning_model, plain_model
    ):
        rows = self._listed(client, openai_provider)

        assert rows[REASONING_MODEL]["supports_reasoning"] is True
        assert rows[PLAIN_MODEL]["supports_reasoning"] is False

    def test_azure_model_is_looked_up_by_name_not_deployment(self, client, model_map):
        model_map["azure/epicstaff-azure-reasoner"] = {
            "litellm_provider": "azure",
            "mode": "chat",
            "supports_reasoning": True,
        }
        azure, _ = Provider.objects.get_or_create(name="azure")
        LLMModel.objects.create(
            name="epicstaff-azure-reasoner", llm_provider=azure, deployment_id="my-deployment"
        )

        rows = self._listed(client, azure)

        assert rows["epicstaff-azure-reasoner"]["supports_reasoning"] is True

    def test_capability_fields_are_read_only(self, client, acme, openai_provider):
        response = client.post(
            "/api/llm-models/",
            {
                "name": "custom-plain",
                "llm_provider": openai_provider.id,
                "supports_reasoning": True,
                "reasoning_efforts": ["high"],
            },
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["supports_reasoning"] is False
        assert response.data["reasoning_efforts"] == []

    def test_list_reports_supported_levels_per_model(self, client, openai_provider):
        _builtin_model("openai", "gpt-5-mini")
        _builtin_model("openai", "gpt-5.4-mini")
        _builtin_model("openai", "o3")

        rows = self._listed(client, openai_provider)

        assert rows["gpt-5-mini"]["supports_reasoning"] is True
        assert rows["gpt-5-mini"]["reasoning_efforts"] == ["minimal", "low", "medium", "high"]
        assert rows["gpt-5.4-mini"]["reasoning_efforts"] == [
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
        ]
        assert rows["o3"]["reasoning_efforts"] == ["low", "medium", "high"]

    def test_non_reasoning_model_lists_no_levels(self, client, openai_provider, plain_model):
        rows = self._listed(client, openai_provider)

        assert rows[PLAIN_MODEL]["reasoning_efforts"] == []


def _builtin_model(provider_name, model_name):
    provider, _ = Provider.objects.get_or_create(name=provider_name)
    model, _ = LLMModel.objects.get_or_create(name=model_name, llm_provider=provider, org=None)
    return model


@pytest.mark.django_db
class TestEffortPerModel:
    # Levels read off the installed litellm's bundled map (tests/settings.py pins it).
    @pytest.mark.parametrize(
        "provider_name, model_name, effort",
        [
            ("openai", "gpt-5.4-mini", "none"),
            ("openai", "gpt-5.4-mini", "xhigh"),
            ("openai", "gpt-5-mini", "minimal"),
            ("azure", "gpt-5-mini", "minimal"),
            ("azure_ai", "claude-sonnet-4-6", "none"),
            ("azure_ai", "claude-sonnet-4-6", "max"),
            ("anthropic", "claude-opus-4-8", "xhigh"),
            ("anthropic", "claude-opus-4-8", "max"),
            ("anthropic", "claude-sonnet-4-6", "max"),
            ("google_ai", "gemini/gemini-2.5-flash", "none"),
        ],
    )
    def test_supported_level_is_saved(self, client, provider_name, model_name, effort):
        model = _builtin_model(provider_name, model_name)

        response = client.post(
            "/api/llm-configs/",
            {"custom_name": "n", "model": model.id, "reasoning_effort": effort},
            format="json",
        )

        assert response.status_code == 201, response.data
        assert LLMConfig.objects.get(id=response.data["id"]).reasoning_effort == effort

    @pytest.mark.parametrize(
        "provider_name, model_name, effort, supported",
        [
            ("openai", "gpt-5-mini", "xhigh", "minimal, low, medium, high"),
            ("openai", "gpt-5-mini", "none", "minimal, low, medium, high"),
            ("openai", "gpt-5.4-mini", "minimal", "none, low, medium, high, xhigh"),
            ("openai", "o3", "none", "low, medium, high"),
            ("openai", "gpt-5.5-pro", "low", "medium, high, xhigh"),
            ("azure", "gpt-5-mini", "none", "minimal, low, medium, high"),
            ("azure_ai", "gpt-5-mini", "xhigh", "minimal, low, medium, high"),
            ("anthropic", "claude-sonnet-4-6", "xhigh", "none, low, medium, high, max"),
            ("anthropic", "claude-sonnet-4-6", "minimal", "none, low, medium, high, max"),
            ("google_ai", "gemini/gemini-2.5-flash", "xhigh", "none, low, medium, high"),
        ],
    )
    def test_unsupported_level_is_rejected_listing_the_supported_ones(
        self, client, provider_name, model_name, effort, supported
    ):
        model = _builtin_model(provider_name, model_name)

        response = client.post(
            "/api/llm-configs/",
            {"custom_name": "n", "model": model.id, "reasoning_effort": effort},
            format="json",
        )

        _assert_reasoning_effort_refused(
            response, effort, _unsupported_level_reason(model_name, effort, supported)
        )
        assert not LLMConfig.objects.filter(custom_name="n").exists()

    def test_swap_to_a_model_refusing_the_kept_level_is_rejected(self, client, acme):
        accepting = _builtin_model("openai", "gpt-5.4-mini")
        refusing = _builtin_model("openai", "gpt-5-mini")
        config = _config(acme, accepting, reasoning_effort="xhigh")

        response = client.patch(
            f"/api/llm-configs/{config.id}/", {"model": refusing.id}, format="json"
        )

        _assert_reasoning_effort_refused(
            response,
            "xhigh",
            _unsupported_level_reason("gpt-5-mini", "xhigh", "minimal, low, medium, high"),
        )
        config.refresh_from_db()
        assert config.model_id == accepting.id

    def test_patch_effort_to_an_unsupported_level_is_rejected(self, client, acme):
        config = _config(acme, _builtin_model("openai", "gpt-5-mini"), reasoning_effort="low")

        response = client.patch(
            f"/api/llm-configs/{config.id}/", {"reasoning_effort": "max"}, format="json"
        )

        _assert_reasoning_effort_refused(
            response,
            "max",
            _unsupported_level_reason("gpt-5-mini", "max", "minimal, low, medium, high"),
        )
        config.refresh_from_db()
        assert config.reasoning_effort == "low"

    def test_patch_unrelated_field_on_a_stored_level_the_model_refuses(self, client, acme):
        # A daily snapshot can change a model's flags after the config was saved, so a
        # stored level the model no longer takes must not block editing another field.
        config = _config(acme, _builtin_model("openai", "gpt-5-mini"), reasoning_effort="xhigh")

        response = client.patch(
            f"/api/llm-configs/{config.id}/", {"temperature": 0.3}, format="json"
        )

        assert response.status_code == 200, response.data
        config.refresh_from_db()
        assert config.temperature == 0.3
        assert config.reasoning_effort == "xhigh"
