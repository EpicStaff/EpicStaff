import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from agents.models import AgentDefinition
from tables.models.llm_models import LLMConfig
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return api_client


@pytest.fixture
def primary(acme):
    return LLMConfig.objects.create(org=acme, custom_name="primary")


@pytest.fixture
def other(acme):
    return LLMConfig.objects.create(org=acme, custom_name="other")


@pytest.fixture
def foreign(beta):
    return LLMConfig.objects.create(org=beta, custom_name="foreign")


@pytest.fixture
def agent(acme, primary):
    return AgentDefinition.objects.create(org=acme, name="agent", llm_config=primary)


def _detail(agent):
    return reverse("agentdefinition-detail", args=[agent.id])


def _assert_invalid(response, field_name):
    body = response.json()
    assert response.status_code == 400, body
    assert field_name in body["message"]


@pytest.mark.django_db
class TestFallbackLlmConfigApi:
    def test_set_fallback(self, client, agent, other):
        response = client.patch(_detail(agent), {"fallback_llm_config": other.id}, format="json")

        assert response.status_code == 200, response.json()
        assert response.json()["fallback_llm_config"] == other.id
        agent.refresh_from_db()
        assert agent.fallback_llm_config_id == other.id

    def test_fallback_equal_to_primary_rejected(self, client, agent, primary):
        response = client.patch(_detail(agent), {"fallback_llm_config": primary.id}, format="json")

        _assert_invalid(response, "fallback_llm_config")

    def test_primary_changed_to_current_fallback_rejected(self, client, agent, other):
        agent.fallback_llm_config = other
        agent.save()

        response = client.patch(_detail(agent), {"llm_config": other.id}, format="json")

        _assert_invalid(response, "fallback_llm_config")
        agent.refresh_from_db()
        assert agent.llm_config_id != other.id

    def test_fallback_without_primary_rejected(self, client, other):
        response = client.post(
            reverse("agentdefinition-list"),
            {"name": "no-primary", "llm_config": None, "fallback_llm_config": other.id},
            format="json",
        )

        _assert_invalid(response, "fallback_llm_config")
        assert not AgentDefinition.objects.filter(name="no-primary").exists()

    def test_clearing_primary_while_fallback_set_rejected(self, client, agent, other):
        agent.fallback_llm_config = other
        agent.save()

        response = client.patch(_detail(agent), {"llm_config": None}, format="json")

        _assert_invalid(response, "fallback_llm_config")
        agent.refresh_from_db()
        assert agent.llm_config_id is not None

    def test_clearing_fallback_allowed(self, client, agent, other):
        agent.fallback_llm_config = other
        agent.save()

        response = client.patch(_detail(agent), {"fallback_llm_config": None}, format="json")

        assert response.status_code == 200, response.json()
        assert response.json()["fallback_llm_config"] is None
        agent.refresh_from_db()
        assert agent.fallback_llm_config_id is None

    def test_unrelated_patch_keeps_valid_fallback(self, client, agent, other):
        agent.fallback_llm_config = other
        agent.save()

        response = client.patch(_detail(agent), {"description": "changed"}, format="json")

        assert response.status_code == 200, response.json()
        assert response.json()["fallback_llm_config"] == other.id

    def test_foreign_org_fallback_rejected(self, client, agent, foreign):
        # Same shape the API returns for llm_config pointing at another org's config.
        fallback_response = client.patch(
            _detail(agent), {"fallback_llm_config": foreign.id}, format="json"
        )
        primary_response = client.patch(_detail(agent), {"llm_config": foreign.id}, format="json")

        _assert_invalid(fallback_response, "fallback_llm_config")
        assert fallback_response.status_code == primary_response.status_code
        agent.refresh_from_db()
        assert agent.fallback_llm_config_id is None

    def test_new_agent_has_no_fallback(self, client, primary):
        response = client.post(
            reverse("agentdefinition-list"),
            {"name": "fresh", "llm_config": primary.id},
            format="json",
        )

        assert response.status_code == 201, response.json()
        assert response.json()["fallback_llm_config"] is None

    def test_filter_by_fallback_llm_config(self, client, agent, other, acme):
        agent.fallback_llm_config = other
        agent.save()
        AgentDefinition.objects.create(org=acme, name="plain")

        response = client.get(reverse("agentdefinition-list"), {"fallback_llm_config": other.id})

        assert response.status_code == 200, response.json()
        results = response.json()
        results = results["results"] if isinstance(results, dict) else results
        assert [item["id"] for item in results] == [agent.id]


@pytest.fixture
def agent_without_primary(agent, primary, other):
    # Deleting the primary config nulls llm_config and leaves the fallback behind.
    agent.fallback_llm_config = other
    agent.save()
    primary.delete()
    agent.refresh_from_db()
    assert agent.llm_config_id is None and agent.fallback_llm_config_id == other.id
    return agent


@pytest.mark.django_db
class TestAgentWhosePrimaryWasDeleted:
    def test_unrelated_patch_is_allowed(self, client, agent_without_primary):
        response = client.patch(
            _detail(agent_without_primary), {"instruction_list": []}, format="json"
        )

        assert response.status_code == 200, response.json()

    def test_form_style_patch_resending_the_stored_pair_is_allowed(
        self, client, agent_without_primary, other
    ):
        response = client.patch(
            _detail(agent_without_primary),
            {"name": "renamed", "llm_config": None, "fallback_llm_config": other.id},
            format="json",
        )

        assert response.status_code == 200, response.json()
        agent_without_primary.refresh_from_db()
        assert agent_without_primary.name == "renamed"
        assert agent_without_primary.fallback_llm_config_id == other.id

    def test_clearing_the_fallback_is_allowed(self, client, agent_without_primary):
        response = client.patch(
            _detail(agent_without_primary), {"fallback_llm_config": None}, format="json"
        )

        assert response.status_code == 200, response.json()
        agent_without_primary.refresh_from_db()
        assert agent_without_primary.fallback_llm_config_id is None

    def test_choosing_another_fallback_without_a_primary_is_rejected(
        self, client, agent_without_primary, acme
    ):
        another = LLMConfig.objects.create(org=acme, custom_name="another")

        response = client.patch(
            _detail(agent_without_primary), {"fallback_llm_config": another.id}, format="json"
        )

        _assert_invalid(response, "fallback_llm_config")


@pytest.mark.django_db
class TestFallbackLlmConfigModel:
    def test_fill_with_defaults_leaves_fallback_empty(self, agent):
        agent.fill_with_defaults()

        assert agent.fallback_llm_config_id is None

    def test_deleting_fallback_config_nulls_it(self, agent, other):
        agent.fallback_llm_config = other
        agent.save()

        other.delete()

        agent.refresh_from_db()
        assert agent.fallback_llm_config_id is None
        assert agent.llm_config_id is not None

    def test_database_rejects_fallback_equal_to_primary(self, agent, primary):
        agent.fallback_llm_config = primary

        with pytest.raises(IntegrityError), transaction.atomic():
            agent.save()
