"""API tests for LLMConfig.reasoning_effort and LLMModel.supports_reasoning.

litellm's model map is replaced by a copy holding two known test models, so the
answers do not depend on the installed litellm version or a snapshot on disk.
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
    yield model_cost


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


def _error_field(response):
    # The project exception handler flattens field errors to "<field>: <message>".
    return response.data["message"].split(":", 1)[0]


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
            {"custom_name": "r", "model": reasoning_model.id, "reasoning_effort": "max"},
            format="json",
        )

        assert response.status_code == 400
        assert _error_field(response) == "reasoning_effort"

    def test_non_reasoning_model_with_effort_is_rejected(self, client, plain_model):
        response = client.post(
            "/api/llm-configs/",
            {"custom_name": "p", "model": plain_model.id, "reasoning_effort": "low"},
            format="json",
        )

        assert response.status_code == 400
        assert _error_field(response) == "reasoning_effort"
        assert not LLMConfig.objects.filter(custom_name="p").exists()

    def test_effort_without_model_is_rejected(self, client):
        response = client.post(
            "/api/llm-configs/",
            {"custom_name": "n", "model": None, "reasoning_effort": "low"},
            format="json",
        )

        assert response.status_code == 400
        assert _error_field(response) == "reasoning_effort"

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

        assert response.status_code == 400
        assert _error_field(response) == "reasoning_effort"
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

        assert response.status_code == 400
        assert _error_field(response) == "reasoning_effort"

    def test_patch_touching_neither_field_skips_the_check(
        self, client, acme, reasoning_model, monkeypatch
    ):
        # The model map may stop listing the model after the config was saved; an
        # unrelated edit must still go through.
        config = _config(acme, reasoning_model, reasoning_effort="high")
        monkeypatch.setattr(
            "tables.serializers.model_serializers.llm_serializers.supports_reasoning",
            lambda provider_name, model_name: False,
        )

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

    def test_supports_reasoning_is_read_only(self, client, acme, openai_provider):
        response = client.post(
            "/api/llm-models/",
            {
                "name": "custom-plain",
                "llm_provider": openai_provider.id,
                "supports_reasoning": True,
            },
            format="json",
        )

        assert response.status_code == 201, response.data
        assert response.data["supports_reasoning"] is False
